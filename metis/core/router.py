"""Router degli intenti: comandi rapidi, poi LLM, poi conversazione.

    "apri vs code"      ->  comando rapido   ~0,1 ms
    "apri il browser"   ->  LLM              ~300 ms
    "che ne pensi?"     ->  chat

IL FAST-PATH SALTA IL MODELLO, NON I CONTROLLI
E' la distinzione che regge tutta la sicurezza di M2. Una frase riconosciuta
risparmia la chiamata a Qwen — 400 ms buoni — ma le tool call che ne escono
attraversano lo stesso identico broker: validazione, policy, guardie,
conferma, audit. Se esistesse una via che salta anche solo uno stadio,
sarebbe quella usata dai comandi piu' frequenti, cioe' esattamente quelli
che vale la pena controllare.

IL CONFRONTO E' NORMALIZZATO, NON FUZZY
Minuscole, senza accenti, senza punteggiatura, spazi compattati. Niente
distanza di edit e niente somiglianze: un fast-path che indovina e' un
fast-path che ogni tanto apre l'applicazione sbagliata, e la fiducia si
perde molto piu' in fretta di quanto si guadagni con qualche frase in piu'.
Quello che non si riconosce con certezza passa all'LLM, che e' li' apposta.

M4 — LA FRASE PIU' LUNGA VINCE
Con i comandi componibili dell'utente le frasi configurate si sovrappongono:
"apri vs code" e "apri vs code e github". Prendere la prima che combacia
farebbe vincere quella piu' corta, cioe' la meno specifica, e la seconda non
si attiverebbe mai. Si ordina per lunghezza decrescente una volta sola, alla
ricarica, non a ogni frase.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from metis.llm.toolcall import Decisione, ToolRouter
from metis.memory.commands import Comando, Libreria, normalizza
from metis.tools.registry import Registry

__all__ = ["Comando", "Router", "normalizza"]


@dataclass(frozen=True)
class _Voce:
    """Una frase configurata, pronta per il confronto."""

    frase: str                     # gia' normalizzata
    comando: Comando


class Router:
    """Decide cosa fare di una frase trascritta."""

    def __init__(self, registry: Registry, libreria: Libreria | None = None,
                 tool_router: ToolRouter | None = None, usa_llm: bool = True,
                 comandi: list[Comando] | None = None):
        self.registry = registry
        self.tool_router = tool_router
        self.usa_llm = usa_llm
        self.fast_hit = 0
        self.llm_hit = 0
        # `comandi` esiste per i test, che devono poter descrivere due o tre
        # frasi senza scrivere un file. Con una libreria vera si ricarica da
        # sola; con una lista fissa resta ferma, che nei test e' cio' che
        # serve.
        self.libreria = libreria
        self._fissi = comandi
        self._voci: list[_Voce] = []
        self._ricariche_viste = -1
        self._aggiorna()

    # -- indice ------------------------------------------------------------

    @property
    def comandi(self) -> list[Comando]:
        if self._fissi is not None:
            return self._fissi
        return self.libreria.comandi if self.libreria is not None else []

    def _aggiorna(self) -> None:
        # Il contatore si legge PRIMA di costruire l'indice. L'editor salva
        # dal thread della GUI mentre questo codice gira sul thread del
        # nucleo: leggendolo dopo, una ricarica avvenuta nel frattempo
        # verrebbe registrata come gia' vista, e l'indice resterebbe
        # vecchio per sempre. Leggendolo prima, al massimo si ricostruisce
        # una volta di troppo.
        visto = self.libreria.ricariche if self.libreria is not None else -1
        voci = [_Voce(f, c) for c in self.comandi for f in
                (c.normalizzate or tuple(normalizza(x) for x in c.frasi))]
        # Piu' lunga prima: vedi la nota in testa al modulo.
        voci.sort(key=lambda v: len(v.frase), reverse=True)
        self._voci = voci
        self._ricariche_viste = visto

    def _forse_aggiorna(self) -> None:
        """La ricarica a caldo, dal lato di chi legge.

        La `Libreria` conta le proprie ricariche; qui si guarda quel numero.
        E' un controllo di un intero per frase pronunciata, e ha il pregio di
        non richiedere nessun segnale, nessun blocco e nessuna sveglia: chi
        salva non deve sapere che esiste un router.
        """
        if self.libreria is not None and self._ricariche_viste != self.libreria.ricariche:
            self._aggiorna()

    # -- fast path ---------------------------------------------------------

    def fast_path(self, testo: str) -> Comando | None:
        """Corrispondenza esatta o per contenimento sulla frase normalizzata.

        Il contenimento serve perche' il parlato aggiunge cortesie: "per
        favore apri vs code" contiene "apri vs code". Il verso e' solo
        questo: la frase configurata dentro il detto, mai il contrario —
        altrimenti "apri" da solo aprirebbe qualcosa.
        """
        self._forse_aggiorna()
        detto = normalizza(testo)
        if not detto:
            return None
        for v in self._voci:
            if detto == v.frase or v.frase in detto:
                return v.comando
        return None

    # -- decisione ---------------------------------------------------------

    def decidi(self, testo: str, storia: list[dict] | None = None) -> Decisione:
        t0 = time.perf_counter()
        c = self.fast_path(testo)
        if c is not None:
            self.fast_hit += 1
            return Decisione(tuple(dict(a) for a in c.azioni), "fast_path",
                             (time.perf_counter() - t0) * 1000,
                             risposta=c.risposta)

        if not self.usa_llm or self.tool_router is None:
            return Decisione((), "chat", (time.perf_counter() - t0) * 1000)

        d = self.tool_router.decidi(testo, storia)
        if d.e_strumento:
            self.llm_hit += 1
        return d

    def stats(self) -> dict:
        return {"fast_path": self.fast_hit, "llm": self.llm_hit,
                "comandi_configurati": len(self.comandi),
                "frasi": len(self._voci)}
