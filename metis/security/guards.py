"""Guardie: controlli specifici che un singolo strumento deve superare.

Una guardia risponde a una domanda sola e risponde con un MOTIVO oppure con
None. Nessuna solleva, nessuna decide da sola: la decisione la prende il
broker, che e' l'unico posto dove si vede la sequenza intera.

LA FINESTRA IN PRIMO PIANO CAMBIA MENTRE DECIDI
E' il rischio piu' subdolo di M2. Fra il momento in cui il broker verifica che
in primo piano non ci sia Esplora risorse e il momento in cui l'evento di
tastiera parte possono passare centinaia di millisecondi, e l'utente in quel
frattempo ha cliccato altrove. Il testo finirebbe nella finestra sbagliata —
che nel caso peggiore e' una casella di rinomina file.

La contromisura non e' "ricordarsi di ricontrollare" dentro ogni strumento
futuro: e' il campo `immediato`. Il broker rivaluta da solo le guardie cosi'
marcate subito prima di chiamare l'handler. Chi aggiunge uno strumento in M4
eredita la protezione senza saperlo, ed e' l'unico modo perche' regga.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

_CONFIG_APPS = Path("config/apps.toml")


# --- il contratto ------------------------------------------------------------

@dataclass(frozen=True)
class Guard:
    """`controlla` ritorna il motivo del rifiuto, oppure None se va bene.

    Il verso e' volutamente scomodo: restituire un motivo e' piu' faticoso che
    restituire False, e questo garantisce che ogni rifiuto arrivi nell'audit
    log con scritto perche'. Un log che dice solo "negato" non serve a niente
    quando alle undici di sera Metis rifiuta qualcosa e non si capisce cosa.
    """

    nome: str
    controlla: Callable[[BaseModel], str | None]
    immediato: bool = False        # rivalutata subito prima dell'esecuzione


# --- finestra in primo piano -------------------------------------------------

@dataclass(frozen=True)
class Finestra:
    titolo: str
    processo: str
    classe: str
    # 0 = sconosciuto. Serve a riconoscere le finestre di Metis stesso, e va
    # confrontato con il PID e non con il nome del processo: "python.exe" e'
    # anche il nome di qualunque altro script aperto sul desktop.
    pid: int = 0


# Processi in cui non si scrive mai. Non sono "applicazioni pericolose": sono
# i posti in cui una battuta di tasti sbagliata cancella o esegue qualcosa.
DENY_PROCESSI = frozenset({
    "explorer.exe",        # rinomina ed eliminazione file
    "cmd.exe", "powershell.exe", "pwsh.exe", "WindowsTerminal.exe",
    "conhost.exe", "regedit.exe", "taskmgr.exe", "mmc.exe",
    "SystemSettings.exe", "control.exe", "msiexec.exe",
    "LogonUI.exe", "consent.exe",          # UAC: mai, in nessun caso
})

# #32770 e' la classe dei dialoghi comuni di Windows, quindi anche di
# "Apri file", "Salva con nome" ed "Elimina". Un testo sintetico li' dentro
# agisce sul filesystem senza che nessuno strumento tocchi mai un percorso.
DENY_CLASSI = frozenset({"#32770", "Shell_TrayWnd", "Progman", "WorkerW"})


def finestra_in_primo_piano() -> Finestra:
    """Legge la finestra attiva. Su errore ritorna una finestra ignota.

    Non solleva mai: una guardia che esplode bloccherebbe Metis, e un
    fallimento nel LEGGERE lo stato deve tradursi in rifiuto, non in crash.
    """
    try:
        import psutil
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return Finestra("", "?", "?")
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            processo = psutil.Process(pid).name()
        except Exception:
            processo = "?"
        return Finestra(win32gui.GetWindowText(hwnd), processo,
                        win32gui.GetClassName(hwnd), pid)
    except Exception:
        return Finestra("", "?", "?")


def guardia_finestra(fornitore: Callable[[], Finestra] | None = None) -> Guard:
    """Rifiuta l'input sintetico se in primo piano c'e' un posto pericoloso.

    Il fornitore e' iniettabile perche' i test devono poter descrivere la
    situazione invece di crearla: aprire davvero Esplora risorse per
    verificare un rifiuto renderebbe la suite dipendente dal desktop.

    Quando non lo si passa, la lettura vera viene risolta **al momento del
    controllo** e non alla costruzione: cosi' anche le guardie gia' montate
    sugli strumenti veri restano verificabili, ed e' su quelle che i casi
    avversariali hanno davvero valore.
    """

    def controlla(_: BaseModel) -> str | None:
        f = (fornitore or finestra_in_primo_piano)()
        if f.processo in DENY_PROCESSI:
            return f"finestra in primo piano non consentita: {f.processo}"
        if f.classe in DENY_CLASSI:
            return f"classe di finestra non consentita: {f.classe} ({f.titolo[:40]})"
        if f.pid and f.pid == os.getpid():
            # Metis che scrive dentro Metis non e' pericoloso, e' insensato:
            # succede quando l'utente clicca sull'overlay e poi detta. Meglio
            # dirlo che consegnare i tasti a una finestra che non li aspetta.
            return "in primo piano ci sono io: clicca prima sulla finestra giusta"
        if f.processo == "?":
            # Non sapere dove si sta scrivendo e' peggio che saperlo male.
            return "finestra in primo piano non identificabile"
        return None

    return Guard("finestra", controlla, immediato=True)


# --- combinazioni di tasti ---------------------------------------------------

# Combinazioni che non si premono mai, qualunque sia la finestra davanti.
DENY_COMBINAZIONI: tuple[frozenset[str], ...] = (
    frozenset({"shift", "delete"}),          # eliminazione definitiva
    frozenset({"win", "r"}),                 # Esegui
    frozenset({"ctrl", "shift", "enter"}),   # esecuzione elevata
    frozenset({"ctrl", "alt", "delete"}),    # schermata di sicurezza
    frozenset({"alt", "f4"}),                # chiusura forzata
    frozenset({"win", "x"}),                 # menu utente esperto
    frozenset({"win", "e"}),                 # Esplora risorse
    frozenset({"win", "l"}),                 # blocco sessione
)


def guardia_combinazione() -> Guard:
    """Rifiuta le combinazioni distruttive o che aprono vie di esecuzione.

    Confronta come INSIEME, non come sequenza: `["delete", "shift"]` e
    `["shift", "delete"]` premono gli stessi tasti, e una denylist ordinata
    si aggirerebbe scambiandoli.
    """

    def controlla(call: BaseModel) -> str | None:
        tasti = frozenset(t.lower() for t in getattr(call, "keys", ()))
        for vietata in DENY_COMBINAZIONI:
            if vietata <= tasti:
                return "combinazione non consentita: " + "+".join(sorted(vietata))
        return None

    return Guard("combinazione", controlla)


# --- allowlist applicazioni --------------------------------------------------

@dataclass(frozen=True)
class VoceApp:
    """Un'applicazione dell'allowlist: dove sta e con quali argomenti parte.

    Gli argomenti vivono qui e non nello schema dello strumento. E' una
    distinzione di sicurezza, non di comodita': `--remote-debugging-port` e'
    una proprieta' di questa macchina, decisa da chi ha scritto il TOML. Un
    campo `args` che il modello potesse riempire sarebbe una riga di comando
    libera, e un'allowlist con una riga di comando libera dentro non e'
    un'allowlist.
    """

    percorso: Path
    args: tuple[str, ...] = ()

    @staticmethod
    def da(valore) -> "VoceApp":
        """Accetta un `Path`, una stringa o la tabella del TOML.

        La forma breve regge perche' la usano i test, che parlano di
        percorsi e non di righe di comando.
        """
        if isinstance(valore, VoceApp):
            return valore
        if isinstance(valore, dict):
            return VoceApp(Path(valore["path"]),
                           tuple(str(a) for a in valore.get("args", ())))
        return VoceApp(Path(valore))


def carica_allowlist(path: Path = _CONFIG_APPS) -> dict[str, VoceApp]:
    if not path.exists():
        return {}
    dati = tomllib.loads(path.read_text(encoding="utf-8")).get("apps", {})
    return {k: VoceApp.da(v) for k, v in dati.items()}


ALLOWLIST_APP = carica_allowlist()


def guardia_app(allowlist: dict | None = None) -> Guard:
    """Seconda barriera sull'apertura di applicazioni.

    Il `Literal` nello schema impedisce gia' al modello di nominare altro.
    Questa e' ridondanza voluta: le due barriere hanno modi di rompersi
    diversi. Lo schema cede se qualcuno allarga l'enum senza pensarci,
    l'allowlist cede se qualcuno modifica il TOML. Perche' passi qualcosa di
    non previsto devono cedere entrambe.
    """
    tabella = ALLOWLIST_APP if allowlist is None else allowlist

    def controlla(call: BaseModel) -> str | None:
        chiave = getattr(call, "app", None)
        voce = tabella.get(chiave)
        if voce is None:
            return f"applicazione non in allowlist: {chiave!r}"
        percorso = VoceApp.da(voce).percorso
        if not percorso.is_absolute():
            return f"percorso non assoluto in allowlist: {percorso}"
        if not percorso.exists():
            return f"eseguibile assente: {percorso}"
        return None

    return Guard("allowlist_app", controlla)
