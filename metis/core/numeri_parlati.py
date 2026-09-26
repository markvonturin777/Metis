"""I numeri da 1 a 99 come escono dalla trascrizione (PHASE2).

    "clicca il 7"            -> 7      la forma che Whisper produce davvero
    "clicca il sette"        -> 7
    "clicca il ventotto"     -> 28
    "clicca il venti otto"   -> 28     la parola spezzata

COSA DICE IL CORPUS
Sulle frasi registrate di M1 (`data/corpus/`), Whisper scrive i numeri in
cifre: "alle diciassette" diventa "alle 17", "per venti minuti" diventa "per
20 minuti". Le cifre sono la forma principale; le parole restano come
ripiego, perche' un numero da solo a fine frase ("clicca il sette.") ogni
tanto esce scritto.

Il testo arriva gia' normalizzato (minuscole, senza accenti, senza
punteggiatura): "ventitré" e' "ventitre", "l'11" e' "l 11".
"""

from __future__ import annotations

MASSIMO = 99

_UNITA = {"uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
          "sette": 7, "otto": 8, "nove": 9}
_DIECI = {"dieci": 10, "undici": 11, "dodici": 12, "tredici": 13,
          "quattordici": 14, "quindici": 15, "sedici": 16, "diciassette": 17,
          "diciotto": 18, "diciannove": 19}
_DECINE = {"venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50,
           "sessanta": 60, "settanta": 70, "ottanta": 80, "novanta": 90}


def _parole() -> dict[str, int]:
    p = {**_UNITA, **_DIECI, **_DECINE, "un": 1, "una": 1}
    for d, vd in _DECINE.items():
        for u, vu in _UNITA.items():
            p[d + u] = vd + vu                     # ventiuno, ventiotto
            if u in ("uno", "otto"):
                p[d[:-1] + u] = vd + vu            # ventuno, ventotto: l'elisione
    return p


PAROLE = _parole()


def numero(testo: str) -> int | None:
    """Un numero solo, in cifre o in parole (anche "venti otto", "venti e
    otto"). None se non e' un numero da 1 a 99."""
    t = testo.strip().split()
    if len(t) == 1:
        w = t[0]
        if w.isdigit():
            n = int(w)
            return n if 1 <= n <= MASSIMO else None
        return PAROLE.get(w)
    if len(t) in (2, 3) and t[0] in _DECINE and t[-1] in _UNITA and (
            len(t) == 2 or t[1] == "e"):
        return _DECINE[t[0]] + _UNITA[t[-1]]
    return None


def numeri_in(testo: str) -> set[int]:
    """Tutti i numeri da 1 a 99 nominati nel testo, in cifre o in parole.

    Serve a chi deve verificare che un numero sia stato DETTO: un indice
    che il modello mette in una tool call deve comparire nella frase.
    "un" e "una" non contano: sono articoli molto piu' spesso che numeri.
    """
    parole = testo.split()
    fuori: set[int] = set()
    for i, w in enumerate(parole):
        if w in ("un", "una"):
            continue
        n = numero(w)
        if n is not None:
            fuori.add(n)
        if w in _DECINE and i + 1 < len(parole):
            coppia = numero(" ".join(parole[i:i + 2]))
            terna = numero(" ".join(parole[i:i + 3])) if i + 2 < len(parole) else None
            fuori.update(x for x in (coppia, terna) if x is not None)
    return fuori
