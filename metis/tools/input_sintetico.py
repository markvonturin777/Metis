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
Non si decide: si cerca. Il modello dice il nome dell'elemento, e il
risolutore prova a trovarlo davvero.

    qualunque finestra, Chrome compreso  ->  UI Automation (`cliccabili.py`)
    nessun candidato                     ->  rifiuto esplicito
    piu' candidati alla pari             ->  i numeri sui soli candidati

PHASE2 — UNA SORGENTE SOLA
Fino a M4 Chrome passava da Playwright su CDP. Da Chrome 136 la porta di
debug non si apre sul profilo dell'utente (spike del 2026-09-26), quindi quel
percorso sulla sessione vera non c'era piu'. UI Automation legge anche le
pagine, e con `FindAll` senza limite di profondita' trova in VS Code 78
elementi dove il visitatore di M4 ne trovava 7. `browser.py` resta per i
banchi che aprono un Chrome loro.

E l'ambiguita' non si risolve piu' elencando i nomi a voce: su una pagina web
sono testo di sconosciuti, e la frase finirebbe in memoria. Si mettono i
numeri sui candidati, e l'utente dice "clicca il 2".

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


def _risolvi_elemento(nome: str, tipo: str = "qualsiasi",
                      numeri_se_ambiguo: bool = True) -> tuple[Elemento, str]:
    from metis.tools import cliccabili, uia

    i = _davanti()
    try:
        return uia.scegli(cliccabili.candidati(i.hwnd, nome, tipo), nome), "uia"
    except uia.Ambiguo as a:
        if numeri_se_ambiguo:
            _numeri_sui_candidati(i, a.candidati)
        raise Rifiuto(f"{a}: sia piu' preciso") from None


def _numeri_sui_candidati(i, candidati: list[Elemento]) -> None:
    """Solleva sempre: con i numeri a schermo, oppure senza se non si puo'."""
    from metis.tools import cliccabili, numeri

    try:
        n = numeri.numera(i.hwnd, cliccabili.ordina(candidati)[:cliccabili.MAX_NUMERI],
                          cliccabili.cornice_visibile(i.rect))
    except Rifiuto:
        return                  # niente interfaccia: il chiamante rifiuta a parole
    raise Rifiuto(f"ce ne sono {n}: le ho messo i numeri, mi dica quale")


def _mai_sensibile(i, e: Elemento) -> None:
    """Per nome non si clicca niente che pubblichi, invii o paghi (D-NAV 2).

    La conferma dei clic sensibili ha un percorso solo, `clicca_numero`, ed e'
    quello che controlla la verifica sull'audit. Qui, invece di duplicarla, si
    mette il numero sull'elemento e si rimanda li'. I pagamenti non partono
    da nessuna delle due vie.
    """
    from metis.tools import cliccabili, numeri

    parola = numeri.vietata(e.nome)
    if parola:
        raise Rifiuto(f"su quel pulsante non clicco ('{parola}'): pagamenti e accessi "
                      "restano a lei")
    parola = numeri.sensibile(e.nome)
    if parola is None:
        return
    try:
        numeri.numera(i.hwnd, [e], cliccabili.cornice_visibile(i.rect))
    except Rifiuto:
        raise Rifiuto(f"quel pulsante ('{parola}') chiede conferma, e senza "
                      "l'interfaccia non posso chiedergliela") from None
    raise Rifiuto(f"quel pulsante ('{parola}') chiede conferma: le ho messo il "
                  "numero 1, dica 'clicca il 1'")


# --- tastiera ----------------------------------------------------------------

def _fuoco_scrivibile() -> bool:
    from metis.tools import cliccabili

    try:
        f = cliccabili.fuoco()
    except Rifiuto:
        return False
    return f is not None and f.scrivibile


def _invio_serve_conferma(call) -> bool:
    """D-NAV 11 (PHASE2, dopo le prove): ogni Invio con il fuoco in un campo di
    testo chiede conferma, su qualunque sito e in qualunque campo.

    Nessuna eccezione per i campi "di ricerca": che lo siano lo dice la pagina,
    e un nome scritto dalla pagina puo' aggiungere una conferma, mai toglierla.
    Un commento che si chiamasse "Cerca" partirebbe senza chiedere. Se non si
    riesce a sapere dove sia il fuoco, si chiede.
    """
    if "enter" not in [k.lower() for k in getattr(call, "keys", ())]:
        return False
    from metis.tools import cliccabili

    try:
        f = cliccabili.fuoco()
    except Rifiuto:
        return True
    return f is None or f.scrivibile


def _presenta_tasti(call) -> dict[str, str]:
    voci = {"tasti": "+".join(call.keys)}
    if "enter" in call.keys:
        from metis.tools import cliccabili

        try:
            f = cliccabili.fuoco()
        except Rifiuto:
            f = None
        if f is not None:
            voci["campo"] = f.nome or "(senza nome)"
            voci["testo che parte"] = f.valore or "(vuoto)"
    return voci


@REGISTRY.strumento(Tier.T2, TypeText, guards=(guardia_finestra(),))
def _type_text(call: TypeText) -> dict:
    """Scrive testo nella finestra in primo piano."""
    # PHASE2: solo se il fuoco e' in un campo. Fuori, i caratteri diventano
    # scorciatoie della pagina: su YouTube "f" e' lo schermo intero.
    if not _fuoco_scrivibile():
        raise Rifiuto("il cursore non e' in un campo di testo: non scrivo niente. "
                      "Mi dica 'mostra i numeri' e 'scrivi nel' con il numero del campo")
    i = _davanti()
    inviati = sendinput.scrivi(call.text)
    return {"caratteri": inviati, "finestra": i.titolo[:80],
            "processo": i.processo}


@REGISTRY.strumento(
    Tier.T2, PressHotkey,
    guards=(guardia_combinazione(), guardia_finestra()),
    conferma=_invio_serve_conferma, presenta=_presenta_tasti,
)
def _press_hotkey(call: PressHotkey) -> dict:
    """Preme una combinazione di tasti."""
    from metis.tools import numeri

    i = _davanti()
    # PHASE2: indietro, una scheda chiusa, una scheda nuova: la pagina cambia.
    numeri.invalida()
    sendinput.combinazione(list(call.keys))
    return {"tasti": "+".join(call.keys), "finestra": i.titolo[:80],
            "processo": i.processo}


# --- mouse -------------------------------------------------------------------

@REGISTRY.strumento(Tier.T2, ClickElement, guards=(guardia_finestra(),))
def _click_element(call: ClickElement) -> dict:
    """Clicca un elemento individuato per nome, mai per coordinate."""
    from metis.tools import cliccabili, numeri

    elemento, via = _risolvi_elemento(call.elemento, call.tipo)
    i = _davanti()
    _mai_sensibile(i, elemento)

    # Giorni 11-12: la bolla su cio' che il risolutore ha trovato. Il nome lo
    # ha scelto il modello, l'elemento UIA: la bolla mostra il risultato
    # prima che il clic parta (D-NAV 7).
    comparsa = numeri.evidenzia(cliccabili.cornice_visibile(i.rect), elemento.rect, "clic")
    x, y = elemento.centro
    if comparsa is not None:
        # Le pause del clic scorrono mentre la bolla si vede; poi il kill
        # switch e la guardia, che il broker ha valutato prima dell'attesa.
        sendinput.avvicina(x, y)
        numeri.aspetta_bolla(comparsa)
        motivo = numeri._motivo_ultimo_istante(call)
        if motivo is None and _davanti().hwnd != i.hwnd:
            motivo = "in primo piano e' cambiata finestra: non clicco"
        if motivo is not None:
            numeri.spegni_evidenza()
            raise Rifiuto(motivo)

    sendinput.clic(x, y, doppio=call.doppio, avvicinato=comparsa is not None)
    numeri.segnala_clic()
    return {"elemento": elemento.nome, "tipo": elemento.tipo, "via": via,
            "punto": [x, y], "doppio": call.doppio,
            # PHASE2: il nome letto va nell'audit, per la verifica dei clic
            # sensibili (`numeri.clic_sensibili_non_confermati`).
            "audit": f"{elemento.nome[:120]}"}


@REGISTRY.strumento(Tier.T2, ScrollWindow, guards=(guardia_finestra(),))
def _scroll(call: ScrollWindow) -> dict:
    """Scorre la finestra in primo piano.

    Il puntatore viene portato al centro della finestra prima di girare la
    rotellina: Windows consegna l'evento alla finestra sotto il puntatore,
    non a quella con il fuoco, e senza questo passo lo scorrimento finirebbe
    dove il mouse era rimasto.
    """
    from metis.tools import numeri

    i = _davanti()
    # PHASE2: la pagina si sposta, i numeri non corrispondono piu' a niente.
    numeri.invalida()
    l, t, r, b = i.rect
    sendinput.muovi((l + r) // 2, (t + b) // 2)
    tacche = call.quantita if call.verso == "su" else -call.quantita
    sendinput.scorri(tacche)
    return {"verso": call.verso, "tacche": abs(tacche),
            "finestra": i.titolo[:80]}


@REGISTRY.strumento(Tier.T2, DragElement, guards=(guardia_finestra(),))
def _drag(call: DragElement) -> dict:
    """Trascina un elemento su un altro. Entrambi individuati per nome."""
    # Senza numeri: "clicca il 2" poi cliccherebbe, non trascinerebbe.
    partenza, via = _risolvi_elemento(call.da, numeri_se_ambiguo=False)
    arrivo, _ = _risolvi_elemento(call.a, numeri_se_ambiguo=False)
    from metis.tools import numeri

    for e in (partenza, arrivo):
        if numeri.vietata(e.nome) or numeri.sensibile(e.nome):
            raise Rifiuto("non trascino su un pulsante che pubblica, invia o paga")
    x1, y1 = partenza.centro
    x2, y2 = arrivo.centro
    sendinput.trascina(x1, y1, x2, y2)
    return {"da": partenza.nome, "a": arrivo.nome, "via": via,
            "punti": [[x1, y1], [x2, y2]]}
