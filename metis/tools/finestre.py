"""Le finestre: trovarle, spostarle, disporle. Il livello sotto gli strumenti.

Qui non c'e' nessun `@REGISTRY.strumento`: sono funzioni normali, e servono
sia agli strumenti T1 sia al risolutore di elementi di `uia.py`, che deve
sapere in quale finestra cercare. Tenerle separate dagli handler significa
che si possono provare con un `python -c` senza passare dal broker, il che
non e' un buco: queste funzioni spostano e ridimensionano, non digitano ne'
cliccano. Tutto cio' che e' T2 sta altrove ed e' irraggiungibile.

COSA VUOL DIRE "QUESTA FINESTRA"
Il comando e' "sposta questa finestra sullo schermo a destra". Fra il
momento in cui l'utente comincia a parlare e quello in cui Metis esegue
passano uno o due secondi: la trascrizione, il router, il broker. In quel
tempo il fuoco puo' essere cambiato — e molto spesso e' cambiato proprio
verso Metis, che si e' appena messo in ascolto e ha una finestra sua.

Leggere il primo piano al momento dell'esecuzione sposterebbe quindi la
finestra sbagliata, e la sbaglierebbe in modo sistematico. Il valore giusto
si cattura all'ingresso in IN_ASCOLTO — `cattura_riferimento()` — e da li'
in poi resta fermo per tutto il turno.

E SE IN PRIMO PIANO C'E' METIS
Si scende nello Z-order fino alla prima finestra che non sia nostra. E' la
regola del piano, e vale anche al momento della cattura: se l'utente clicca
sull'overlay e poi parla, "questa finestra" e' quella che stava usando
prima, non il pannello dell'assistente.

L'IDENTIFICAZIONE E' PER TITOLO, MAI PER HANDLE INVENTATO
Vedi la nota in testa a `metis/llm/schemas.py`. Qui la conseguenza pratica
e': esatto, poi per sottostringa, e **se le corrispondenze sono piu' di una
si rifiuta**. Una scelta arbitraria fra due finestre e' un'azione sulla
finestra sbagliata una volta su due, ed e' peggio di non fare niente.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from metis.tools.display import (
    Monitor,
    monitor_di_rect,
    monitors,
    rect_trasferito,
)
from metis.tools.registry import Rifiuto

MAX_FINESTRE = 40          # niente elenchi sterminati nel contesto del modello

# Windows puo' aggiustare il rettangolo dopo lo spostamento: una finestra con
# dimensione minima, o con bordi non client, non finisce esattamente dove le
# si e' detto. Sotto questa soglia lo scarto non e' un errore.
TOLLERANZA_PX = 4

# Quante volte riprovare a portare una finestra in primo piano, e quanto
# aspettare fra un tentativo e l'altro. Vedi `porta_davanti`.
TENTATIVI_FUOCO = 3
PAUSA_FUOCO_S = 0.15

SW_MINIMIZE = 6
SW_RESTORE = 9
SW_MAXIMIZE = 3
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


@dataclass(frozen=True)
class Info:
    hwnd: int
    titolo: str
    processo: str
    classe: str
    rect: tuple[int, int, int, int]
    stato: str                 # "normale" | "massimizzata" | "ridotta"

    @property
    def nostra(self) -> bool:
        return self.hwnd in _nostre()


# --- lettura -----------------------------------------------------------------

def _nostre() -> set[int]:
    """Gli handle delle finestre di questo processo. Metis non agisce su di se'."""
    import win32gui
    import win32process

    mie: set[int] = set()
    mio_pid = os.getpid()

    def visita(hwnd: int, _) -> None:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == mio_pid:
                mie.add(hwnd)
        except Exception:                      # noqa: BLE001
            pass

    try:
        win32gui.EnumWindows(visita, None)
    except Exception:                          # noqa: BLE001
        pass
    return mie


def _processo(hwnd: int) -> str:
    try:
        import psutil
        import win32process

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name()
    except Exception:                          # noqa: BLE001
        return "?"


def info(hwnd: int) -> Info | None:
    """Tutto quello che si sa di una finestra. None se non esiste piu'."""
    import win32con
    import win32gui

    try:
        if not win32gui.IsWindow(hwnd):
            return None
        placement = win32gui.GetWindowPlacement(hwnd)
        stato = {win32con.SW_SHOWMAXIMIZED: "massimizzata",
                 win32con.SW_SHOWMINIMIZED: "ridotta"}.get(placement[1], "normale")
        return Info(
            hwnd=hwnd,
            titolo=win32gui.GetWindowText(hwnd),
            processo=_processo(hwnd),
            classe=win32gui.GetClassName(hwnd),
            rect=tuple(win32gui.GetWindowRect(hwnd)),
            stato=stato,
        )
    except Exception:                          # noqa: BLE001
        return None


def elenca(includi_nostre: bool = False) -> list[Info]:
    """Le finestre visibili con un titolo, nell'ordine dello Z-order.

    L'ordine e' quello di `EnumWindows`, cioe' dalla piu' in alto alla piu'
    in basso. Conta: la prima che non sia nostra e' "quella che l'utente
    stava usando".
    """
    import win32gui

    mie = _nostre()
    fuori: list[Info] = []

    def visita(hwnd: int, _) -> None:
        if len(fuori) >= MAX_FINESTRE:
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        if not win32gui.GetWindowText(hwnd).strip():
            return
        if not includi_nostre and hwnd in mie:
            return
        i = info(hwnd)
        if i is not None:
            fuori.append(i)

    win32gui.EnumWindows(visita, None)
    return fuori


# --- la finestra di riferimento ----------------------------------------------

_riferimento: int | None = None


def cattura_riferimento() -> int | None:
    """Fissa "questa finestra". Da chiamare all'ingresso in IN_ASCOLTO.

    Non solleva mai e non registra niente: viene invocata sul percorso
    audio, dove un'eccezione fermerebbe l'ascolto per un dettaglio che nel
    peggiore dei casi produce un rifiuto educato piu' tardi.
    """
    global _riferimento
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        mie = _nostre()
        if hwnd and hwnd not in mie and win32gui.GetWindowText(hwnd).strip():
            _riferimento = hwnd
            return hwnd
        # Il primo piano e' Metis, o non c'e': si scende nello Z-order.
        for i in elenca():
            _riferimento = i.hwnd
            return i.hwnd
        _riferimento = None
    except Exception:                          # noqa: BLE001
        pass
    return _riferimento


def riferimento() -> int | None:
    return _riferimento


def imposta_riferimento(hwnd: int | None) -> None:
    """Solo per i test e per il banco di prova."""
    global _riferimento
    _riferimento = hwnd


# --- risoluzione -------------------------------------------------------------

def risolvi(window: str) -> Info:
    """Da cio' che il modello ha detto alla finestra vera. O un rifiuto.

    Ordine: titolo esatto, poi sottostringa, poi nome del processo. Nessuna
    somiglianza approssimata, e nessuna scelta arbitraria in caso di parita':
    la stessa regola del risolutore di elementi, per la stessa ragione.
    """
    testo = (window or "").strip()
    if not testo:
        hwnd = _riferimento
        if hwnd is None:
            raise Rifiuto("non so quale finestra intendi: non ne avevo una "
                          "in primo piano quando hai cominciato a parlare")
        i = info(hwnd)
        if i is None:
            raise Rifiuto("la finestra di cui stavamo parlando non c'e' piu'")
        return i

    aperte = elenca()
    basso = testo.lower()

    esatte = [i for i in aperte if i.titolo.lower() == basso]
    parziali = [i for i in aperte if basso in i.titolo.lower()]
    per_processo = [i for i in aperte
                    if basso in i.processo.lower().removesuffix(".exe")]

    for gruppo in (esatte, parziali, per_processo):
        if len(gruppo) == 1:
            return gruppo[0]
        if len(gruppo) > 1:
            # Con piu' candidati si preferisce quello piu' in alto nello
            # Z-order SOLO se il primo e' l'unico attivo di recente: qui non
            # lo sappiamo, quindi si chiede. Rifiutare costa una frase;
            # indovinare costa una finestra spostata a caso.
            titoli = ", ".join(f'"{i.titolo[:40]}"' for i in gruppo[:3])
            raise Rifiuto(f"{len(gruppo)} finestre contengono "
                          f"'{testo}': {titoli}. Dimmi quale")

    raise Rifiuto(f"non trovo nessuna finestra che contenga '{testo}'")


def risolvi_monitor(rif: str, corrente: Monitor,
                    elenco: list[Monitor] | None = None) -> Monitor:
    """Da "destra" / "altro" / "1" al monitor vero."""
    ms = elenco if elenco is not None else monitors()
    if not ms:
        raise Rifiuto("non vedo nessun monitor")

    if rif.isdigit():
        i = int(rif)
        if i >= len(ms):
            raise Rifiuto(f"non hai un monitor numero {i}: ne vedo {len(ms)}")
        return ms[i]

    if rif == "primario":
        for m in ms:
            if m.primario:
                return m
        return ms[0]

    if rif == "altro":
        if len(ms) < 2:
            raise Rifiuto("hai un monitor solo: non c'e' un altro schermo")
        # Con due schermi "l'altro" e' univoco. Con tre lo si interpreta
        # come "il successivo", che e' l'unica lettura che non richiede di
        # indovinare cosa avesse in mente l'utente.
        return ms[(corrente.indice + 1) % len(ms)]

    passo = 1 if rif == "destra" else -1
    i = corrente.indice + passo
    if not (0 <= i < len(ms)):
        dove = "a destra" if passo > 0 else "a sinistra"
        raise Rifiuto(f"non c'e' nessuno schermo {dove} di quello dov'e' adesso")
    return ms[i]


# --- azioni -------------------------------------------------------------------

def _applica_rect(hwnd: int, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Posiziona e ridimensiona, poi verifica e corregge UNA volta.

    Il passo di verifica non e' paranoia. Windows riaggancia il DPI alla
    finestra quando questa attraversa il confine fra due monitor, e puo'
    ridimensionarla per conto suo subito dopo; le finestre con una dimensione
    minima ignorano in parte cio' che si chiede. Senza rilettura, il
    risultato sarebbe "ho spostato" anche quando la finestra e' rimasta
    grande il doppio del previsto.

    Una sola correzione, non un ciclo: se la seconda non basta, la finestra
    ha vincoli suoi e insistere diventa uno sfarfallio.
    """
    import win32gui

    l, t, r, b = rect
    win32gui.SetWindowPos(hwnd, 0, l, t, r - l, b - t,
                          SWP_NOZORDER | SWP_NOACTIVATE)
    ottenuto = tuple(win32gui.GetWindowRect(hwnd))
    if max(abs(a - c) for a, c in zip(ottenuto, rect)) > TOLLERANZA_PX:
        win32gui.SetWindowPos(hwnd, 0, l, t, r - l, b - t,
                              SWP_NOZORDER | SWP_NOACTIVATE)
        ottenuto = tuple(win32gui.GetWindowRect(hwnd))
    return ottenuto


def sposta_su_monitor(i: Info, rif: str) -> dict:
    """Il comando 2 dell'accettazione. L'ordine dei passi conta."""
    import win32gui

    ms = monitors()
    sorgente = monitor_di_rect(i.rect, ms)
    if sorgente is None:
        raise Rifiuto("non capisco su quale schermo sia adesso quella finestra")
    destinazione = risolvi_monitor(rif, sorgente, ms)
    if destinazione.indice == sorgente.indice:
        return {"titolo": i.titolo, "monitor": destinazione.indice,
                "spostata": False, "nota": "era gia' su quello schermo"}

    era_massimizzata = i.stato == "massimizzata"
    if era_massimizzata:
        # Una finestra massimizzata non si sposta: e' agganciata al suo
        # schermo. Si ripristina, si sposta, si rimassimizza — e a quel punto
        # Windows la massimizza sul monitor dove ora si trova.
        win32gui.ShowWindow(i.hwnd, SW_RESTORE)
        corrente = tuple(win32gui.GetWindowRect(i.hwnd))
    else:
        corrente = i.rect

    voluto = rect_trasferito(corrente, sorgente, destinazione)
    ottenuto = _applica_rect(i.hwnd, voluto)

    if era_massimizzata:
        win32gui.ShowWindow(i.hwnd, SW_MAXIMIZE)
        ottenuto = tuple(win32gui.GetWindowRect(i.hwnd))

    finale = monitor_di_rect(ottenuto, ms)
    return {
        "titolo": i.titolo,
        "monitor": finale.indice if finale else -1,
        "monitor_chiesto": destinazione.indice,
        "spostata": bool(finale and finale.indice == destinazione.indice),
        "rect": ottenuto,
        "riscalata": round(destinazione.dpi / sorgente.dpi, 3),
    }


def rect_disposizione(disposizione: str, m: Monitor) -> tuple[int, int, int, int]:
    """Frazioni dell'area di lavoro. Funzione pura, quindi verificabile."""
    l, t, r, b = m.lavoro
    w, h = r - l, b - t
    match disposizione:
        case "meta_sinistra":
            return (l, t, l + w // 2, b)
        case "meta_destra":
            return (l + w // 2, t, r, b)
        case "meta_alto":
            return (l, t, r, t + h // 2)
        case "meta_basso":
            return (l, t + h // 2, r, b)
        case "due_terzi":
            return (l, t, l + (w * 2) // 3, b)
        case "centrata":
            cw, ch = (w * 2) // 3, (h * 2) // 3
            return (l + (w - cw) // 2, t + (h - ch) // 2,
                    l + (w - cw) // 2 + cw, t + (h - ch) // 2 + ch)
        case _:                                  # "piena"
            return (l, t, r, b)


def disponi(i: Info, disposizione: str) -> dict:
    import win32gui

    if i.stato != "normale":
        win32gui.ShowWindow(i.hwnd, SW_RESTORE)
    m = monitor_di_rect(tuple(win32gui.GetWindowRect(i.hwnd)))
    if m is None:
        raise Rifiuto("non capisco su quale schermo sia quella finestra")
    ottenuto = _applica_rect(i.hwnd, rect_disposizione(disposizione, m))
    return {"titolo": i.titolo, "disposizione": disposizione,
            "monitor": m.indice, "rect": ottenuto}


def mostra(i: Info, comando: str) -> dict:
    """massimizza / riduci / ripristina. Un solo `ShowWindow`."""
    import win32gui

    codice = {"massimizza": SW_MAXIMIZE, "riduci": SW_MINIMIZE,
              "ripristina": SW_RESTORE}[comando]
    win32gui.ShowWindow(i.hwnd, codice)
    dopo = info(i.hwnd)
    return {"titolo": i.titolo, "comando": comando,
            "stato": dopo.stato if dopo else "?",
            "monitor": (monitor_di_rect(dopo.rect).indice
                        if dopo and monitor_di_rect(dopo.rect) else -1)}


def porta_davanti(i: Info) -> dict:
    """Portare una finestra in primo piano da un processo che non ha il
    fuoco e' una cosa che Windows ostacola apposta, per impedire alle
    applicazioni di rubarsi il fuoco a vicenda. `SetForegroundWindow` puo'
    fallire in silenzio e limitarsi a far lampeggiare l'icona.

    Il rimedio abituale e' agganciare la coda di input del nostro thread a
    quella del thread proprietario: cosi' Windows ci considera "lo stesso
    utente che sta gia' interagendo" e concede il cambio. Si sgancia subito
    dopo, perche' restare agganciati significherebbe condividere lo stato
    della tastiera con un altro processo.

    L'ESITO SI GUARDA, NON SI CHIEDE ALL'API
    `SetForegroundWindow` restituisce FALSE — e pywin32 lo trasforma in
    un'eccezione con `GetLastError()` a zero, cioe' "nessun errore" — anche
    in casi in cui la finestra viene su lo stesso. Trattare quell'eccezione
    come un fallimento significa dire "non ci sono riuscito" di una cosa
    riuscita, e l'ho visto succedere. Quindi si prova, si assorbe, e poi si
    guarda **chi e' davvero in primo piano**: quella e' la risposta.
    """
    import win32gui
    import win32process

    if info(i.hwnd) is None:
        raise Rifiuto("quella finestra non c'e' piu'")

    if i.stato == "ridotta":
        try:
            win32gui.ShowWindow(i.hwnd, SW_RESTORE)
        except Exception:                        # noqa: BLE001
            pass

    # Fino a tre tentativi. Una finestra appena comparsa — l'applicazione
    # che Metis ha aperto un istante prima — spesso non accetta il fuoco al
    # primo colpo, e il comando composto "aprila e portala davanti"
    # fallirebbe sistematicamente sulla seconda meta'.
    #
    # Ritentare qui e' lecito e ritentare un clic no, e la differenza non e'
    # di gusto: alzare una finestra due volte la lascia alzata, cliccare due
    # volte preme due volte.
    for tentativo in range(TENTATIVI_FUOCO):
        agganciato = False
        nostro = suo = 0
        try:
            nostro = win32api_thread_id()
            suo, _ = win32process.GetWindowThreadProcessId(i.hwnd)
            if suo and suo != nostro:
                agganciato = bool(win32process.AttachThreadInput(nostro, suo, True))
            win32gui.BringWindowToTop(i.hwnd)
            win32gui.SetForegroundWindow(i.hwnd)
        except Exception:                        # noqa: BLE001
            pass
        finally:
            if agganciato:
                try:
                    win32process.AttachThreadInput(nostro, suo, False)
                except Exception:                # noqa: BLE001
                    pass
        if win32gui.GetForegroundWindow() == i.hwnd:
            return {"titolo": i.titolo, "in_primo_piano": True,
                    "tentativi": tentativo + 1}
        time.sleep(PAUSA_FUOCO_S)

    return {"titolo": i.titolo, "in_primo_piano": False,
            "tentativi": TENTATIVI_FUOCO}


def win32api_thread_id() -> int:
    import win32api

    return win32api.GetCurrentThreadId()
