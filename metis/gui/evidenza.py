"""La bolla che mostra dove Metis sta per cliccare (PHASE2, D-NAV 6 e 7).

    "clicca il 7"  ->  la bolla compare larga e si stringe sul punto del clic,
                       resta, il clic parte, un'onda si allarga, la bolla sfuma
    conferma       ->  bolla fucsia, ferma, che respira finche' il dialogo e' aperto
    rifiuto        ->  un lampo rosso dove l'elemento ERA, che sfuma

L'effetto e' quello di un eye tracker: una bolla morbida sul punto guardato.
Qui il punto e' quello del clic — il centro della parte visibile
dell'elemento, lo stesso che riceve `SendInput` — e un contorno tenue dice
quale elemento e' stato trovato (D-NAV 6: la bolla dice *dove*, il contorno
*cosa*).

TUTTO E' UNA FUNZIONE DEL TEMPO
`fotogramma(stile, t, ...)` restituisce raggio, opacita', onda: nessuno stato,
nessun widget. L'overlay chiede un fotogramma a ogni tic e lo disegna; i test
verificano i valori senza aprire finestre. Con "riduci animazioni"
(`animato=False`) la bolla e' ferma: compare, resta, sparisce.

I colori sono quelli che ci sono gia': il ciano del tema per "sto per
cliccare", il fucsia di ATTESA_CONFERMA per "aspetto te", il rosso
dell'errore per "non clicco".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

ENTRATA_MS = 220           # la bolla si stringe sul punto
ONDA_MS = 320              # l'onda del clic
PAUSA_DOPO_CLIC_MS = 120   # la bolla resta un attimo, poi sfuma
USCITA_MS = 300
RIFIUTO_MS = 600
RESPIRO_MS = 1400          # il periodo della bolla in attesa
FERMA_DOPO_CLIC_MS = 150   # senza animazioni: quanto resta dopo il clic
FERMA_RIFIUTO_MS = 500

RAGGIO_MIN, RAGGIO_MAX = 16.0, 44.0     # px logici
ALFA = 0.85


class Stile(str, Enum):
    CLIC = "clic"
    ATTESA = "attesa"
    RIFIUTO = "rifiuto"


def colore(stile: Stile | str) -> str:
    from metis.core.palette import esadecimale
    from metis.gui import tema

    stile = Stile(stile)
    if stile is Stile.ATTESA:
        return esadecimale("ATTESA_CONFERMA")
    if stile is Stile.RIFIUTO:
        return tema.ERRORE
    return tema.ACCENTO


def centro(rect) -> tuple[float, float]:
    l, t, r, b = rect
    return ((l + r) / 2, (t + b) / 2)


def raggio_per(rect) -> float:
    """Poco piu' della meta' del lato corto, dentro un intervallo.

    Un pulsantino da 20 px ha una bolla da 20 px; un link lungo 400 e alto 20
    non ha una bolla da 200, che coprirebbe mezza pagina: per quello c'e' il
    contorno.
    """
    l, t, r, b = rect
    return max(RAGGIO_MIN, min(RAGGIO_MAX, min(r - l, b - t) / 2 + 10))


@dataclass(frozen=True)
class Fotogramma:
    raggio: float
    alfa: float
    onda_raggio: float = 0.0
    onda_alfa: float = 0.0
    finito: bool = False

    @property
    def contorno_alfa(self) -> float:
        return 0.6 * self.alfa / ALFA

    @property
    def ingombro(self) -> float:
        """Il raggio massimo disegnato: serve al riquadro da ridisegnare."""
        return max(self.raggio, self.onda_raggio)


FINITO = Fotogramma(0.0, 0.0, finito=True)


def _uscita(t: float) -> float:
    """1 -> 0 in USCITA_MS, dolce."""
    x = min(1.0, max(0.0, t / USCITA_MS))
    return 1.0 - x * x


def _entrata(t: float) -> float:
    """0 -> 1 in ENTRATA_MS, che rallenta verso la fine (cubica)."""
    x = min(1.0, max(0.0, t / ENTRATA_MS))
    return 1.0 - (1.0 - x) ** 3


def fotogramma(stile: Stile | str, t: float, raggio: float, t_clic: float | None = None,
               t_spegni: float | None = None, animato: bool = True) -> Fotogramma:
    """La bolla all'istante `t` (ms dalla comparsa). `t_clic` e `t_spegni`
    sono gli istanti del clic e della richiesta di spegnimento, se ci sono."""
    stile = Stile(stile)

    if not animato:
        if t_spegni is not None and t >= t_spegni:
            return FINITO
        if t_clic is not None and t >= t_clic + FERMA_DOPO_CLIC_MS:
            return FINITO
        if stile is Stile.RIFIUTO and t >= FERMA_RIFIUTO_MS:
            return FINITO
        return Fotogramma(raggio, ALFA)

    if stile is Stile.RIFIUTO:
        if t >= RIFIUTO_MS:
            return FINITO
        x = t / RIFIUTO_MS
        return Fotogramma(raggio * (1 + 0.15 * x), ALFA * (1 - x) ** 2)

    e = _entrata(t)
    r = raggio * (2.2 - 1.2 * e)
    a = ALFA * e
    if stile is Stile.ATTESA and e >= 1.0:
        r = raggio * (1 + 0.08 * math.sin(2 * math.pi * (t - ENTRATA_MS) / RESPIRO_MS))

    onda_r = onda_a = 0.0
    fine_onda = True
    if t_clic is not None and t >= t_clic:
        dt = t - t_clic
        if dt < ONDA_MS:
            x = dt / ONDA_MS
            onda_r, onda_a = raggio * (1 + 1.4 * x), 0.7 * (1 - x)
            fine_onda = False
        dopo = dt - PAUSA_DOPO_CLIC_MS
        if dopo > 0:
            a *= _uscita(dopo)
            if dopo >= USCITA_MS and fine_onda:
                return FINITO

    if t_spegni is not None and t >= t_spegni:
        dopo = t - t_spegni
        if dopo >= USCITA_MS:
            return FINITO
        a *= _uscita(dopo)

    return Fotogramma(r, a, onda_r, onda_a)
