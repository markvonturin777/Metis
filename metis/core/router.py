"""Router degli intenti: fast-path, poi LLM, poi conversazione.

    "apri vs code"      ->  fast-path   ~0,1 ms
    "apri il browser"   ->  LLM         ~300 ms
    "che ne pensi?"     ->  chat

IL FAST-PATH SALTA IL MODELLO, NON I CONTROLLI
E' la distinzione che regge tutta la sicurezza di M2. Una frase riconosciuta
risparmia la chiamata a Qwen — 400 ms buoni — ma la tool call che ne esce
attraversa lo stesso identico broker: validazione, policy, guardie,
conferma, audit. Se esistesse una via che salta anche solo uno stadio,
sarebbe quella usata dai comandi piu' frequenti, cioe' esattamente quelli
che vale la pena controllare.

IL CONFRONTO E' NORMALIZZATO, NON FUZZY
Minuscole, senza accenti, senza punteggiatura, spazi compattati. Niente
distanza di edit e niente somiglianze: un fast-path che indovina e' un
fast-path che ogni tanto apre l'applicazione sbagliata, e la fiducia si
perde molto piu' in fretta di quanto si guadagni con qualche frase in piu'.
Quello che non si riconosce con certezza passa all'LLM, che e' li' apposta.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from metis.llm.toolcall import Decisione, ToolRouter
from metis.tools.registry import Registry

_CONFIG = Path("config/commands.json")
_PUNTEGGIATURA = re.compile(r"[^\w\s]", re.UNICODE)
_SPAZI = re.compile(r"\s+")


def normalizza(testo: str) -> str:
    """minuscole, senza accenti, senza punteggiatura, spazi compattati."""
    t = unicodedata.normalize("NFD", testo.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return _SPAZI.sub(" ", _PUNTEGGIATURA.sub(" ", t)).strip()


@dataclass(frozen=True)
class Comando:
    frasi: tuple[str, ...]        # gia' normalizzate
    call: dict


def carica_comandi(path: Path = _CONFIG) -> list[Comando]:
    if not path.exists():
        return []
    dati = json.loads(path.read_text(encoding="utf-8"))
    return [
        Comando(tuple(normalizza(f) for f in c["frasi"]), c["call"])
        for c in dati.get("comandi", [])
    ]


class Router:
    """Decide cosa fare di una frase trascritta."""

    def __init__(self, registry: Registry, comandi: list[Comando] | None = None,
                 tool_router: ToolRouter | None = None, usa_llm: bool = True):
        self.registry = registry
        self.comandi = carica_comandi() if comandi is None else comandi
        self.tool_router = tool_router
        self.usa_llm = usa_llm
        self.fast_hit = 0
        self.llm_hit = 0

    # -- fast path ---------------------------------------------------------

    def fast_path(self, testo: str) -> dict | None:
        """Corrispondenza esatta o per contenimento sulla frase normalizzata.

        Il contenimento serve perche' il parlato aggiunge cortesie: "per
        favore apri vs code" contiene "apri vs code". Il verso e' solo
        questo: la frase configurata dentro il detto, mai il contrario —
        altrimenti "apri" da solo aprirebbe qualcosa.
        """
        detto = normalizza(testo)
        if not detto:
            return None
        for c in self.comandi:
            for frase in c.frasi:
                if detto == frase or frase in detto:
                    return dict(c.call)
        return None

    # -- decisione ---------------------------------------------------------

    def decidi(self, testo: str, storia: list[dict] | None = None) -> Decisione:
        t0 = time.perf_counter()
        call = self.fast_path(testo)
        if call is not None:
            self.fast_hit += 1
            return Decisione(call, "fast_path", (time.perf_counter() - t0) * 1000)

        if not self.usa_llm or self.tool_router is None:
            return Decisione(None, "chat", (time.perf_counter() - t0) * 1000)

        d = self.tool_router.decidi(testo, storia)
        if d.e_strumento:
            self.llm_hit += 1
        return d

    def stats(self) -> dict:
        return {"fast_path": self.fast_hit, "llm": self.llm_hit,
                "comandi_configurati": len(self.comandi)}
