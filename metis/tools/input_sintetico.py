"""T2 — input sintetico. Perimetro definito in M2, capacita' arrivata in M4.

PERCHE' IL PERIMETRO E' STATO SCRITTO DUE ITERAZIONI PRIMA DEL CORPO
Le guardie che governano questi strumenti — dove si puo' scrivere, quali
combinazioni non si premono mai — sono logica di sicurezza, non dettagli
implementativi. Sono state scritte e verificate mentre si costruiva il
broker, quando l'obiettivo era la sicurezza. Scriverle adesso, insieme
all'automazione, avrebbe significato scriverle mentre l'obiettivo era far
funzionare l'automazione: la guardia sarebbe diventata la cosa che
ostacola, e l'avrebbe scritta qualcuno che voleva vederla passare.

Il risultato pratico di quella scelta e' che in M4 questo file non contiene
nessuna decisione di sicurezza. Non ricontrolla la finestra — lo fa il
broker, rivalutando le guardie `immediato` un istante prima di chiamare gli
handler — e non decide cosa sia lecito. Fa gesti.

COME SI DECIDE DOVE CLICCARE
Non si decide: si cerca. Il modello dice il nome dell'elemento, e due
risolutori diversi provano a trovarlo davvero.

    finestra in primo piano e' Chrome  ->  Playwright sulla scheda attiva
    qualunque altra applicazione       ->  UI Automation sull'albero
    nessuno dei due lo trova           ->  rifiuto esplicito

Il terzo caso e' un esito corretto, non un fallimento. Il piano lo dice in
una riga e vale la pena ripeterla: meglio "non riesco a individuare quel
link" che un clic a caso in mezzo allo schermo.

TUTTI I GESTI PASSANO DA `SendInput`
Anche quelli sul web. La ragione sta in testa a `browser.py`: se il clic nel
browser fosse sintetizzato dentro il browser, sarebbe l'unico gesto di Metis
non soggetto alla guardia sulla finestra in primo piano, e ne esisterebbero
due tipi di cui uno solo controllato.
"""

from __future__ import annotations

from metis.llm.schemas import (
    ClickElement,
    DragElement,
    PressHotkey,
    ScrollWindow,
    TypeText,
)
from metis.security.audit import Tier
from metis.security.guards import guardia_combinazione, guardia_finestra
from metis.tools import sendinput
from metis.tools.registry import REGISTRY, Rifiuto
from metis.tools.uia import Elemento

PROCESSI_BROWSER = frozenset({"chrome.exe", "msedge.exe"})


def _davanti():
    """La finestra su cui il gesto andra' a finire.

    Si legge adesso e non si usa quella di riferimento del turno: un evento
    di `SendInput` arriva alla finestra che ha il fuoco nell'istante in cui
    parte, e fingere altrimenti — lavorando sull'handle catturato prima —
    vorrebbe dire calcolare le coordinate su una finestra e cliccare su
    un'altra. Per gli strumenti T1, che spostano una finestra nominata,
    vale la regola opposta; qui no, e la differenza e' proprio che questi
    gesti non nominano un bersaglio, lo colpiscono.
    """
    import win32gui

    from metis.tools.finestre import info

    hwnd = win32gui.GetForegroundWindow()
    i = info(hwnd) if hwnd else None
    if i is None:
        raise Rifiuto("non c'e' nessuna finestra in primo piano")
    return i


def _risolvi_elemento(nome: str, tipo: str = "qualsiasi") -> tuple[Elemento, str]:
    i = _davanti()
    if i.processo.lower() in PROCESSI_BROWSER:
        from metis.tools import browser

        return browser.trova(nome, tipo), "playwright"
    from metis.tools import uia

    return uia.trova(i.hwnd, nome, tipo), "uia"


# --- tastiera ----------------------------------------------------------------

@REGISTRY.strumento(Tier.T2, TypeText, guards=(guardia_finestra(),))
def _type_text(call: TypeText) -> dict:
    """Scrive testo nella finestra in primo piano."""
    i = _davanti()
    inviati = sendinput.scrivi(call.text)
    return {"caratteri": inviati, "finestra": i.titolo[:80],
            "processo": i.processo}


@REGISTRY.strumento(
    Tier.T2, PressHotkey,
    guards=(guardia_combinazione(), guardia_finestra()),
)
def _press_hotkey(call: PressHotkey) -> dict:
    """Preme una combinazione di tasti."""
    i = _davanti()
    sendinput.combinazione(list(call.keys))
    return {"tasti": "+".join(call.keys), "finestra": i.titolo[:80],
            "processo": i.processo}


# --- mouse -------------------------------------------------------------------

@REGISTRY.strumento(Tier.T2, ClickElement, guards=(guardia_finestra(),))
def _click_element(call: ClickElement) -> dict:
    """Clicca un elemento individuato per nome, mai per coordinate."""
    elemento, via = _risolvi_elemento(call.elemento, call.tipo)
    x, y = elemento.centro
    sendinput.clic(x, y, doppio=call.doppio)
    return {"elemento": elemento.nome, "tipo": elemento.tipo, "via": via,
            "punto": [x, y], "doppio": call.doppio}


@REGISTRY.strumento(Tier.T2, ScrollWindow, guards=(guardia_finestra(),))
def _scroll(call: ScrollWindow) -> dict:
    """Scorre la finestra in primo piano.

    Il puntatore viene portato al centro della finestra prima di girare la
    rotellina: Windows consegna l'evento alla finestra sotto il puntatore,
    non a quella con il fuoco, e senza questo passo lo scorrimento finirebbe
    dove il mouse era rimasto.
    """
    i = _davanti()
    l, t, r, b = i.rect
    sendinput.muovi((l + r) // 2, (t + b) // 2)
    tacche = call.quantita if call.verso == "su" else -call.quantita
    sendinput.scorri(tacche)
    return {"verso": call.verso, "tacche": abs(tacche),
            "finestra": i.titolo[:80]}


@REGISTRY.strumento(Tier.T2, DragElement, guards=(guardia_finestra(),))
def _drag(call: DragElement) -> dict:
    """Trascina un elemento su un altro. Entrambi individuati per nome."""
    partenza, via = _risolvi_elemento(call.da)
    arrivo, _ = _risolvi_elemento(call.a)
    x1, y1 = partenza.centro
    x2, y2 = arrivo.centro
    sendinput.trascina(x1, y1, x2, y2)
    return {"da": partenza.nome, "a": arrivo.nome, "via": via,
            "punti": [[x1, y1], [x2, y2]]}
