"""Slot di riferimento: lo stato degli oggetti che si possono citare.

Senza questo file Metis non puo' rispondere a "e adesso spostala sull'altro
schermo", perche' non sa cosa sia "la". Il pronome e' la forma normale del
parlato — nessuno dice "sposta la finestra di Visual Studio Code sul secondo
monitor" due volte di fila — e un assistente vocale che pretende il nome
completo a ogni frase e' un assistente che si smette di usare.

SI INIETTANO, NON SI DEDUCONO
Sperare che il modello ricavi "la" dalla cronologia costa affidabilita': a
volte ci arriva, a volte prende la finestra del turno prima, e non c'e' modo
di sapere in anticipo quale delle due. Iniettarli esplicitamente costa ~150
token a turno — meno del 2% del contesto — ed e' il prezzo piu' basso di
tutto M5 per il guadagno piu' visibile.

IL BLOCCO VA IN DUE POSTI, NON IN UNO
Al modello di conversazione, perche' possa parlarne. E al **router**, perche'
possa agirci: "spostala sull'altro schermo" diventa
`move_window_to_monitor(window="Visual Studio Code")` solo se chi decide sa
cosa sia "la". Dimenticare il secondo e' il difetto che sembra un problema di
comprensione del linguaggio e invece e' una riga di cablaggio.

CHI SCRIVE QUI
Un punto solo: `osserva(call, result)`, chiamata dopo ogni passaggio dal
broker. Gli slot si aggiornano **solo sugli esiti riusciti** — un'azione
rifiutata non ha cambiato il mondo, e registrarla farebbe riferire i pronomi
successivi a qualcosa che non e' mai successo.

L'unica eccezione e' `ultima_finestra`, che si popola anche dalla cattura del
riferimento all'ingresso in IN_ASCOLTO: li' non c'e' nessuna azione, c'e' il
fatto che l'utente stava guardando qualcosa quando ha cominciato a parlare.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass

MAX_TITOLO = 70
MAX_ARGOMENTO = 60
MAX_URL = 90
MAX_VALORE = 60          # per ogni argomento dentro `ultima_azione`

# Tetto duro sull'intero blocco. §1.3 del piano assegna ~150 token agli slot,
# e sforarli significa toglierli alla memoria conversazionale senza che
# nessuno se ne accorga — il sintomo sarebbe "Metis ogni tanto dimentica".
#
# Ogni singolo valore e' gia' accorciato quando entra; questo tetto e' la
# rete per i casi che nessuno ha previsto, per esempio un titolo di finestra
# di duecento caratteri che arriva da un'applicazione che nessuno ha provato.
MAX_TOKEN_BLOCCO = 150


@dataclass(frozen=True)
class WindowRef:
    titolo: str
    processo: str = ""
    monitor: int | None = None

    def __str__(self) -> str:
        pezzi = [self.titolo[:MAX_TITOLO]]
        if self.monitor is not None:
            pezzi.append(f"(monitor {self.monitor + 1})")
        return " ".join(pezzi)


# Come si dicono le app all'utente. Le stesse di `risposte.py`: se
# divergessero, Metis chiamerebbe la stessa applicazione in due modi nella
# stessa frase.
_APP = {"vscode": "Visual Studio Code", "github_desktop": "GitHub Desktop",
        "chrome": "Chrome"}

# Gli strumenti che cambiano lo stato di una finestra. Dopo uno di questi,
# "quella finestra" e' quella su cui si e' appena agito, non quella che era
# in primo piano quando l'utente ha cominciato a parlare.
_SU_FINESTRA = {"move_window_to_monitor", "resize_window", "maximize_window",
                "minimize_window", "restore_window", "focus_window"}

# Gli strumenti che non meritano di diventare "l'ultima azione": leggere lo
# stato non e' un'azione da annullare, e registrarla cancellerebbe quella
# vera. "Massimizza VS Code" -> "che finestre ho aperte?" -> "no,
# rimpiccioliscila": la terza frase si riferisce alla prima.
_NON_AZIONI = {"get_telemetry", "list_windows", "get_active_window",
               "list_monitors", "web_search", "web_fetch",
               # M6
               "list_reminders", "get_home_state", "list_home_devices"}


@dataclass
class Slots:
    """Lo stato citabile. Vive quanto la sessione, come tutto in V1.0."""

    ultima_finestra: WindowRef | None = None
    ultima_app_aperta: str | None = None
    ultimo_argomento_cercato: str | None = None
    ultima_fonte_url: str | None = None
    ultimo_dispositivo: str | None = None          # M6
    ultima_azione: dict | None = None

    def __post_init__(self) -> None:
        # Attributo e non campo: `asdict` copia in profondita' ogni campo, e
        # un lock non si lascia copiare. Gli slot si leggono dal thread della
        # GUI mentre il turno li scrive, quindi il lock serve davvero.
        self._lock = threading.RLock()

    # -- scrittura ---------------------------------------------------------

    def osserva(self, call: dict, result) -> None:
        """Aggiorna gli slot dopo un passaggio dal broker. Non solleva mai.

        Gira sul thread del turno, subito dopo l'esecuzione. Un'eccezione
        qui farebbe fallire un'azione gia' riuscita — il caso peggiore, che
        e' anche il piu' difficile da diagnosticare — quindi si assorbe
        tutto e si prosegue senza slot.
        """
        try:
            self._osserva(call, result)
        except Exception:                          # noqa: BLE001
            pass

    def _osserva(self, call: dict, result) -> None:
        if not getattr(result, "ok", False):
            return
        tool = call.get("tool") or getattr(result, "tool", "") or ""
        v = result.value if isinstance(getattr(result, "value", None), dict) else {}

        with self._lock:
            if tool not in _NON_AZIONI:
                self.ultima_azione = {"tool": tool,
                                      "args": {k: x for k, x in call.items()
                                               if k != "tool"}}

            if tool == "open_application":
                self.ultima_app_aperta = _APP.get(v.get("app") or call.get("app"),
                                                  call.get("app"))
                # Il titolo esatto della finestra appena aperta non si
                # conosce ancora: l'applicazione ci mette qualche centinaio
                # di millisecondi a mostrarla. Si registra il nome, che e'
                # cio' che `finestre.trova` sa cercare per sottostringa.
                self.ultima_finestra = WindowRef(titolo=self.ultima_app_aperta or "")

            elif tool == "open_url":
                self.ultima_fonte_url = (v.get("url") or call.get("url") or "")[:MAX_URL]

            elif tool == "web_search":
                self.ultimo_argomento_cercato = (
                    v.get("query") or call.get("query") or "")[:MAX_ARGOMENTO]
                primi = v.get("risultati") or []
                if primi:
                    self.ultima_fonte_url = (primi[0].get("url") or "")[:MAX_URL]

            elif tool == "web_fetch":
                self.ultima_fonte_url = (v.get("url") or call.get("url") or "")[:MAX_URL]

            elif tool in ("get_home_state", "set_home_device"):
                # M6: lo slot che aspettava da M5. "Accendi la friggitrice" ->
                # "spegnila": il pronome si risolve con il nome del
                # dispositivo, quello del file di configurazione.
                nome = v.get("nome") or call.get("dispositivo") or ""
                if nome:
                    self.ultimo_dispositivo = nome[:MAX_VALORE]

            elif tool in _SU_FINESTRA:
                titolo = v.get("titolo") or call.get("window") or ""
                if titolo:
                    self.ultima_finestra = WindowRef(
                        titolo=titolo, processo=v.get("processo", ""),
                        monitor=v.get("monitor"))

    def vista_finestra(self, titolo: str, processo: str = "",
                       monitor: int | None = None) -> None:
        """"Questa finestra" al momento del risveglio. Vedi la nota in testa.

        Non cancella un riferimento piu' preciso: se nel turno precedente si
        e' agito su una finestra e adesso in primo piano c'e' la stessa, il
        monitor gia' noto vale piu' di un None.
        """
        if not titolo:
            return
        with self._lock:
            prec = self.ultima_finestra
            if prec is not None and prec.titolo == titolo and monitor is None:
                return
            self.ultima_finestra = WindowRef(titolo=titolo, processo=processo,
                                             monitor=monitor)

    def reset(self) -> None:
        with self._lock:
            self.ultima_finestra = None
            self.ultima_app_aperta = None
            self.ultimo_argomento_cercato = None
            self.ultima_fonte_url = None
            self.ultimo_dispositivo = None
            self.ultima_azione = None

    # -- lettura -----------------------------------------------------------

    def come_dizionario(self) -> dict:
        with self._lock:
            return asdict(self)

    @property
    def vuoto(self) -> bool:
        with self._lock:
            return not any((self.ultima_finestra, self.ultima_app_aperta,
                            self.ultimo_argomento_cercato, self.ultima_fonte_url,
                            self.ultimo_dispositivo, self.ultima_azione))

    def blocco(self) -> str:
        """Gli slot in forma compatta, da iniettare nel prompt.

        Una riga per slot, e le righe vuote non si scrivono: "Ultima app
        aperta: nessuna" occupa token per dire che non c'e' niente da dire,
        e su un modello piccolo invita a menzionare l'assenza.
        """
        with self._lock:
            righe = []
            if self.ultima_finestra is not None:
                righe.append(f"Finestra di riferimento: {self.ultima_finestra}")
            if self.ultima_app_aperta:
                righe.append(f"Ultima app aperta: {self.ultima_app_aperta}")
            if self.ultimo_argomento_cercato:
                righe.append(f"Ultimo argomento cercato: {self.ultimo_argomento_cercato}")
            if self.ultima_fonte_url:
                righe.append(f"Ultima fonte: {self.ultima_fonte_url}")
            if self.ultimo_dispositivo:
                righe.append(f"Ultimo dispositivo: {self.ultimo_dispositivo[:MAX_VALORE]}")
            if self.ultima_azione:
                righe.append(f"Ultima azione: {_azione_in_parole(self.ultima_azione)}")
        if not righe:
            return ""
        return _entro("[CONTESTO CORRENTE]\n" + "\n".join(righe))


def _entro(blocco: str, max_token: int = MAX_TOKEN_BLOCCO) -> str:
    """Il tetto duro, applicato togliendo righe dal fondo.

    Si taglia dal fondo e non a meta' riga perche' meta' riga e' peggio di
    nessuna riga: "Ultima azione: maximize_wind" e' un'informazione
    sbagliata, non un'informazione parziale. L'ordine delle righe in
    `blocco()` e' quindi anche un ordine di priorita'.
    """
    from metis.llm.grounding import conta_token

    righe = blocco.split("\n")
    while len(righe) > 1 and conta_token("\n".join(righe)) > max_token:
        righe.pop()
    return "\n".join(righe)


def _azione_in_parole(azione: dict) -> str:
    """`{"tool": "maximize_window", "args": {"window": "Code"}}` diventa
    `maximize_window(window="Code")`.

    Si tiene la forma dello strumento invece di una frase italiana perche'
    questo blocco lo legge anche il router, che deve produrre una chiamata:
    vedergli davanti il nome esatto dello strumento e' cio' che gli permette
    di scegliere l'opposto quando l'utente dice "no, rimpiccioliscila".
    """
    args = azione.get("args") or {}
    dentro = ", ".join(f'{k}="{str(v)[:MAX_VALORE]}"'
                       for k, v in args.items() if v not in ("", None))
    return f"{azione.get('tool', '?')}({dentro})"


# Gli slot dell'applicazione. Uno solo, come il registro degli strumenti: due
# copie divergerebbero, e il pronome si riferirebbe a cose diverse a seconda
# di chi lo legge.
SLOTS = Slots()
