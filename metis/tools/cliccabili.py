"""Gli elementi cliccabili visibili di una finestra (PHASE2, D-NAV 1).

    finestra di riferimento  ->  [Elemento(nome, tipo, rect), ...]   <= 99

UNA CHIAMATA, FILTRATA ALLA SORGENTE
UI Automation, non CDP: da Chrome 136 la porta di debug non si apre sul
profilo dell'utente, e UIA non ne ha bisogno (spike del 2026-09-26). Si
chiede a UIA una cosa sola, `FindAllBuildCache`, con dentro la condizione —
tipo cliccabile, abilitato, non fuori schermo — e con nome, tipo e
rettangolo nella cache della stessa chiamata. Niente visita dell'albero e
niente giro fra processi per ogni proprieta': 34 ms su YouTube, 48 su VS
Code. Il visitatore di `uia.py` sullo stesso VS Code trovava 7 elementi su
78, perche' si ferma a 12 livelli e Electron ne ha di piu'.

LA PRIMA LETTURA DI CHROME E' QUASI VUOTA
Chrome ed Electron accendono l'accessibilita' del contenuto quando si
accorgono che un client la chiede: al primo giro Chrome mostra 37 elementi
su 76, VS Code 3 su 78. Su una finestra che non si e' letta da poco si rilegge
finche' il conteggio non smette di crescere (`_stabile`), dentro un tempo
massimo. Sulle finestre gia' lette la lettura e' una.

UN THREAD SUO, E UN TEMPO MASSIMO
Un'applicazione che non risponde tiene appesa la chiamata UIA per secondi.
La lettura gira su un thread dedicato, con COM inizializzato una volta, e chi
chiede aspetta al massimo `TIMEOUT_S`: poi rifiuta, in parole. Se il thread
resta appeso, alla richiesta dopo se ne fa uno nuovo. Non e' mai il thread
della GUI (NFR-8) ne' quello dell'audio.

IL NOME SERVE AL BROKER, NON AL MODELLO
Qui si legge il testo della pagina — i nomi dei link — e da qui non esce
verso il prompt: lo usano solo la numerazione (per riconoscere che l'elemento
e' ancora lui) e la guardia dei clic sensibili. Vedi `numeri.py`.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from metis.tools.registry import Rifiuto
from metis.tools.uia import Elemento

# D-NAV 5: link, pulsanti, schede, caselle di spunta. Le voci di menu perche'
# nelle applicazioni sono meta' di cio' che si clicca. Gli id sono quelli di
# UIAutomationClient.h; i nomi sono quelli di `TipoElemento`.
TIPI = {
    50000: "pulsante",           # Button
    50031: "pulsante",           # SplitButton
    50005: "link",               # Hyperlink
    50019: "scheda",             # TabItem
    50002: "casella_di_spunta",  # CheckBox
    50013: "casella_di_spunta",  # RadioButton
    50011: "voce_di_menu",       # MenuItem
    # D-NAV 12 (PHASE2, dopo le prove): anche le caselle di testo, per la
    # dettatura. Il Document della pagina no: e' la pagina intera.
    50004: "casella_di_testo",   # Edit
    50003: "casella_di_testo",   # ComboBox (la ricerca di molti siti)
}
# Per `click_element`, che nomina un tipo (`TipoElemento`): anche le caselle
# di testo e le voci di elenco, che non prendono numeri ma si cliccano per nome.
# "link" comprende il testo semplice, come in `uia.py` da M4: nelle
# applicazioni un collegamento e' spesso un TextControl.
ALTRI = {50004: "casella_di_testo", 50030: "casella_di_testo",
         50003: "casella_di_testo", 50007: "elemento_lista",
         50024: "elemento_lista", 50029: "elemento_lista", 50020: "link"}
PER_TIPO: dict[str, tuple[int, ...]] = {
    "pulsante": (50000, 50031),
    "link": (50005, 50020),
    "casella_di_testo": (50004, 50030, 50003),
    "voce_di_menu": (50011,),
    "casella_di_spunta": (50002, 50013),
    "scheda": (50019,),
    "elemento_lista": (50007, 50024, 50029),
    "qualsiasi": (*TIPI, 50004, 50003, 50007, 50024),
}
_NOMI = {**ALTRI, **TIPI}
_P_RECT, _P_TIPO, _P_NOME = 30001, 30003, 30005
_P_ABILITATO, _P_FUORI = 30010, 30022
_DISCENDENTI = 4

MAX_NUMERI = 99            # D-NAV 5: oltre, i numeri coprono la pagina
LATO_MIN = 4               # px: sotto, non e' qualcosa che si possa indicare
TIMEOUT_S = 1.5            # la soglia del piano e' 1 s per mostrare i numeri
PAUSA_S = 0.12             # fra due letture di una finestra fredda
LETTURE_MAX = 4
CALDA_PER_S = 120.0        # una finestra letta da poco ha l'accessibilita' accesa
RIGA_PX = 12               # tolleranza verticale dell'ordine di lettura


# --- geometria, pura ------------------------------------------------------------

def interseca(a, b) -> tuple[int, int, int, int] | None:
    l, t = max(a[0], b[0]), max(a[1], b[1])
    r, bb = min(a[2], b[2]), min(a[3], b[3])
    return (l, t, r, bb) if r > l and bb > t else None


def ordina(elementi: list[Elemento]) -> list[Elemento]:
    """Ordine di lettura: righe dall'alto, e in ogni riga da sinistra.

    Le righe hanno una tolleranza: due pulsanti sulla stessa barra possono
    stare a un paio di pixel di altezza diversa, e senza tolleranza i numeri
    andrebbero a zig-zag.
    """
    return sorted(elementi, key=lambda e: (e.rect[1] // RIGA_PX, e.rect[0], e.rect[1]))


def filtra(grezzi: list[Elemento], cornice) -> list[Elemento]:
    """Dentro la cornice, con area, senza doppioni; in ordine; al massimo 99.

    Il rettangolo che resta e' la parte VISIBILE: il centro di un elemento
    tagliato dal bordo della finestra puo' stare fuori, e il clic va dove
    l'elemento si vede.
    """
    visti: set[tuple[int, int, int, int]] = set()
    fuori: list[Elemento] = []
    for e in grezzi:
        r = interseca(e.rect, cornice)
        if r is None or r[2] - r[0] < LATO_MIN or r[3] - r[1] < LATO_MIN:
            continue
        if r in visti:
            continue            # un link dentro un pulsante con lo stesso rettangolo
        visti.add(r)
        fuori.append(Elemento(e.nome, e.tipo, r))
    return ordina(fuori)[:MAX_NUMERI]


# --- UIA, sul thread dedicato -----------------------------------------------------

class _UIA:
    """Client, condizione e cache: si costruiscono una volta, sul thread che li usa."""

    def __init__(self):
        import uiautomation.uiautomation as m

        self.uia = m._AutomationClient.instance().IUIAutomation
        self._condizioni: dict[tuple[int, ...], object] = {}
        self.cache = self.uia.CreateCacheRequest()
        for p in (_P_NOME, _P_TIPO, _P_RECT):
            self.cache.AddProperty(p)

    def condizione(self, tipi: tuple[int, ...]):
        """Uno di questi tipi, E non fuori schermo, E abilitato."""
        c = self._condizioni.get(tipi)
        if c is None:
            u = self.uia
            o = u.CreatePropertyCondition(_P_TIPO, tipi[0])
            for t in tipi[1:]:
                o = u.CreateOrCondition(o, u.CreatePropertyCondition(_P_TIPO, t))
            c = u.CreateAndCondition(
                o, u.CreateAndCondition(u.CreatePropertyCondition(_P_FUORI, False),
                                        u.CreatePropertyCondition(_P_ABILITATO, True)))
            self._condizioni[tipi] = c
        return c

    def leggi(self, hwnd: int, tipi: tuple[int, ...] = tuple(TIPI)) -> list[Elemento]:
        radice = self.uia.ElementFromHandle(hwnd)
        if radice is None:
            raise Rifiuto("non riesco a leggere quella finestra")
        arr = radice.FindAllBuildCache(_DISCENDENTI, self.condizione(tipi), self.cache)
        fuori: list[Elemento] = []
        for i in range(arr.Length if arr is not None else 0):
            try:
                el = arr.GetElement(i)
                rc = el.CachedBoundingRectangle
                fuori.append(Elemento((el.CachedName or "").strip()[:200],
                                      _NOMI.get(el.CachedControlType, "pulsante"),
                                      (rc.left, rc.top, rc.right, rc.bottom)))
            except Exception:                      # noqa: BLE001
                continue
        return fuori


def _stabile(leggi, pausa_s: float = PAUSA_S, letture: int = LETTURE_MAX,
             dormi=time.sleep) -> list:
    """Rilegge finche' il conteggio non smette di crescere. Separata per i test."""
    ultimo = leggi()
    for _ in range(letture - 1):
        dormi(pausa_s)
        nuovo = leggi()
        if len(nuovo) <= len(ultimo):
            return nuovo            # sempre la piu' recente: la pagina puo' essersi mossa
        ultimo = nuovo
    return ultimo


class Lettore:
    """Un thread con COM inizializzato, e una coda di lavori."""

    def __init__(self, timeout_s: float = TIMEOUT_S):
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._coda: queue.Queue | None = None
        self._calde: dict[int, float] = {}

    def _ciclo(self, coda: queue.Queue) -> None:
        # `uiautomation`, importato per primo, fissa la consapevolezza DPI
        # del PROCESSO alla versione 1, e dopo non si torna indietro: le
        # coordinate di tutto M4 si sfalserebbero sui monitor scalati. La V2
        # di Metis si dichiara prima; se c'era gia', la chiamata non fa niente.
        from metis.tools.display import set_dpi_awareness

        set_dpi_awareness()
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            uia = None
            while True:
                lavoro, esito = coda.get()
                try:
                    if uia is None:
                        uia = _UIA()
                    esito.put((True, lavoro(uia)))
                except BaseException as exc:         # noqa: BLE001
                    esito.put((False, exc))

    def _coda_viva(self) -> queue.Queue:
        with self._lock:
            if self._coda is None:
                self._coda = queue.Queue()
                threading.Thread(target=self._ciclo, args=(self._coda,), daemon=True,
                                 name="metis-cliccabili").start()
            return self._coda

    def esegui(self, lavoro):
        esito: queue.Queue = queue.Queue(maxsize=1)
        self._coda_viva().put((lavoro, esito))
        try:
            ok, valore = esito.get(timeout=self.timeout_s)
        except queue.Empty:
            # Il thread e' appeso dentro una chiamata UIA. Lo si abbandona:
            # e' un daemon, e la richiesta dopo ne avra' uno nuovo.
            with self._lock:
                self._coda = None
            raise Rifiuto("quella finestra non risponde, non riesco a leggerla") from None
        if not ok:
            if isinstance(valore, Rifiuto):
                raise valore
            raise Rifiuto("non riesco a leggere quella finestra") from valore
        return valore

    def grezzi(self, hwnd: int, tipi: tuple[int, ...] = tuple(TIPI)) -> list[Elemento]:
        """Gli elementi di quei tipi, cosi' come li da' UIA."""
        calda = time.monotonic() - self._calde.get(hwnd, -1e9) < CALDA_PER_S

        def lavoro(uia: _UIA):
            if calda:
                return uia.leggi(hwnd, tipi)
            return _stabile(lambda: uia.leggi(hwnd, tipi))

        fuori = self.esegui(lavoro)
        self._calde[hwnd] = time.monotonic()
        return fuori

    def elementi(self, hwnd: int, cornice) -> list[Elemento]:
        """Gli elementi cliccabili visibili, gia' filtrati e ordinati."""
        return filtra(self.grezzi(hwnd), cornice)


LETTORE = Lettore()


# --- dove sta il fuoco (PHASE2, dopo le prove) --------------------------------------
#
# Serve a due cose che devono sapere se i tasti finirebbero SCRITTI: i comandi
# del video (una "f" nella casella di ricerca non mette lo schermo intero, la
# scrive) e la dettatura (che deve scrivere SOLO in un campo). Misurato su
# Chrome vero, 2026-09-28: pagina senza campo attivo = Document di sola
# lettura; input, textarea, contenteditable = Edit scrivibile; pulsanti e link
# no; una select = ComboBox scrivibile, e la si tratta da campo per prudenza.

_EDIT, _DOCUMENTO, _COMBO = 50004, 50030, 50003
_P_VALORE_DISPONIBILE, _P_SOLA_LETTURA, _P_VALORE = 30043, 30046, 30045


@dataclass(frozen=True)
class Fuoco:
    tipo: int
    nome: str                   # della pagina: per il broker e il dialogo, mai per il modello
    rect: tuple[int, int, int, int]
    scrivibile: bool
    valore: str = ""            # il testo nel campo: solo per chi conferma un Invio


def _fuoco(uia: _UIA) -> Fuoco | None:
    el = uia.uia.GetFocusedElement()
    if el is None:
        return None
    tipo = el.CurrentControlType
    r = el.CurrentBoundingRectangle
    valore = bool(el.GetCurrentPropertyValue(_P_VALORE_DISPONIBILE))
    sola_lettura = bool(el.GetCurrentPropertyValue(_P_SOLA_LETTURA))
    scrivibile = tipo in (_EDIT, _DOCUMENTO, _COMBO) and valore and not sola_lettura
    try:
        testo = str(el.GetCurrentPropertyValue(_P_VALORE) or "")[:500] if valore else ""
    except Exception:                              # noqa: BLE001
        testo = ""
    return Fuoco(tipo, (el.CurrentName or "").strip()[:200],
                 (r.left, r.top, r.right, r.bottom), scrivibile, testo)


def fuoco() -> Fuoco | None:
    """L'elemento con il fuoco della tastiera, o None. Solleva `Rifiuto` se UIA
    non risponde: chi chiede deve trattare il dubbio come "non si sa"."""
    return LETTORE.esegui(_fuoco)


def cornice_visibile(rect) -> tuple[int, int, int, int]:
    """Il rettangolo della finestra, tagliato sul monitor su cui sta.

    Una finestra massimizzata sborda di qualche pixel oltre lo schermo, e
    un elemento li' sotto non si vede: non deve prendere un numero.
    """
    from metis.tools.display import monitor_di_rect

    m = monitor_di_rect(rect)
    if m is None:
        return rect
    return interseca(rect, m.rect) or rect


def _cornice(hwnd: int):
    from metis.tools import finestre

    i = finestre.info(hwnd)
    if i is None:
        raise Rifiuto("quella finestra non c'e' piu'")
    if i.stato == "ridotta":
        raise Rifiuto("la finestra e' ridotta a icona")
    return cornice_visibile(i.rect)


def elementi(hwnd: int) -> list[Elemento]:
    """La funzione che usano gli strumenti. Ritorna, oppure solleva `Rifiuto`."""
    return LETTORE.elementi(hwnd, _cornice(hwnd))


def candidati(hwnd: int, nome: str, tipo: str = "qualsiasi") -> list[Elemento]:
    """Per `click_element`: gli elementi visibili di quel tipo il cui nome
    contiene quello cercato. Il tetto dei 99 si applica dopo il filtro per
    nome, non prima."""
    from metis.tools.uia import _piatto

    cercato = _piatto(nome)
    tipi = PER_TIPO.get(tipo, PER_TIPO["qualsiasi"])
    trovati = [e for e in LETTORE.grezzi(hwnd, tipi)
               if e.nome and cercato in _piatto(e.nome)]
    return filtra(trovati, _cornice(hwnd))
