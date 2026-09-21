"""T2 — input sintetico. Perimetro definito in M2, capacita' in M4.

PERCHE' REGISTRARLI ADESSO SENZA CORPO
Le guardie che governano questi due strumenti — dove si puo' scrivere, quali
combinazioni non si premono mai — sono logica di sicurezza, non dettagli
implementativi. Vanno scritte e verificate mentre si costruisce il broker,
non fra due iterazioni accanto allo strumento che dovrebbero contenere: in
quel momento la fretta sara' di far funzionare l'automazione, e la guardia
diventera' la cosa che la ostacola.

Registrati qui, sono gia' dentro la catena: il broker li riconosce, applica
le policy, rivaluta la guardia della finestra subito prima dell'esecuzione, e
si ferma sull'ultimo scalino perche' `implemented=False`. In M4 si toglie
quel flag e si scrive il corpo. Nient'altro.

E' anche il motivo per cui i casi avversariali di M2 sono veri: "scrivi testo
mentre in primo piano c'e' Esplora risorse" viene rifiutato dalla guardia
giusta, non da un generico "strumento sconosciuto".
"""

from __future__ import annotations

from metis.llm.schemas import PressHotkey, TypeText
from metis.security.audit import Tier
from metis.security.guards import guardia_combinazione, guardia_finestra
from metis.tools.registry import REGISTRY


@REGISTRY.strumento(Tier.T2, TypeText, guards=(guardia_finestra(),), implemented=False)
def _type_text(call: TypeText) -> dict:
    """Scrive testo nella finestra in primo piano. Capacita' in M4."""
    raise NotImplementedError


@REGISTRY.strumento(
    Tier.T2, PressHotkey,
    guards=(guardia_combinazione(), guardia_finestra()),
    implemented=False,
)
def _press_hotkey(call: PressHotkey) -> dict:
    """Preme una combinazione di tasti. Capacita' in M4."""
    raise NotImplementedError
