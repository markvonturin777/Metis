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

PHASE2 — IL CONTENIMENTO AMMETTE SOLO CORTESIE
"Apri chrome e mettimi su YouTube un video rilassante" contiene "apri
chrome": il comando rapido scattava, Chrome si apriva e il resto della
richiesta non arrivava mai al router. Il contenimento resta, perche' il
parlato aggiunge davvero "per favore", "Metis", "grazie"; ma le parole in piu'
devono essere tutte di quel tipo (`CORTESIE`). Una parola in piu' di altro
genere vuol dire che la frase chiede qualcos'altro, e interpretarla e' il
lavoro del router, non di un confronto fra stringhe. Il confronto e' anche
per parole intere: "apri vs code" non sta dentro "riapri vs codex".
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from metis.core import frasi_chiuse
from metis.llm.toolcall import Decisione, ToolRouter
from metis.memory.commands import Comando, Libreria, normalizza
from metis.tools.registry import Registry

__all__ = ["CORTESIE", "Comando", "Router", "normalizza"]

# Le parole che possono stare attorno a una frase configurata senza cambiarne
# il senso. Gia' normalizzate: minuscole, senza accenti. Un elenco chiuso e
# corto: ogni parola aggiunta qui e' una frase in piu' che il router non vede.
CORTESIE = frozenset({
    "per", "favore", "perfavore", "cortesia", "cortesemente", "gentilmente",
    "grazie", "mille", "prego", "metis", "puoi", "potresti", "mi", "ok",
    "okay", "ehi", "hey", "ciao", "senti", "dai", "allora", "adesso", "ora",
    "subito", "su", "e", "bene", "perfetto", "si",
})


def _contiene(detto: tuple[str, ...], frase: tuple[str, ...]) -> bool:
    """`frase` compare in `detto` per parole intere, e il resto e' cortesia."""
    n = len(frase)
    for i in range(len(detto) - n + 1):
        if detto[i:i + n] == frase and all(
                p in CORTESIE for p in detto[:i] + detto[i + n:]):
            return True
    return False


def _numeri_a_schermo() -> bool:
    from metis.tools import numeri

    return numeri.attuale() is not None


@dataclass(frozen=True)
class _Voce:
    """Una frase configurata, pronta per il confronto."""

    frase: str                     # gia' normalizzata
    comando: Comando
    parole: tuple[str, ...] = ()   # la frase divisa, una volta sola


class Router:
    """Decide cosa fare di una frase trascritta."""

    def __init__(self, registry: Registry, libreria: Libreria | None = None,
                 tool_router: ToolRouter | None = None, usa_llm: bool = True,
                 comandi: list[Comando] | None = None,
                 numeri_a_schermo: Callable[[], bool] | None = None):
        self.registry = registry
        self.tool_router = tool_router
        # PHASE2: "sul 60" senza verbo e' un clic solo con i numeri a schermo.
        # Iniettabile per i test; di norma lo chiede agli strumenti.
        self._numeri_a_schermo = numeri_a_schermo or _numeri_a_schermo
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
        voci = [_Voce(f, c, tuple(f.split())) for c in self.comandi for f in
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
        altrimenti "apri" da solo aprirebbe qualcosa. E attorno solo
        cortesie: vedi PHASE2 in testa al modulo.
        """
        self._forse_aggiorna()
        detto = normalizza(testo)
        if not detto:
            return None
        parole = tuple(detto.split())
        for v in self._voci:
            if detto == v.frase or _contiene(parole, v.parole):
                return v.comando
        return None

    # -- decisione ---------------------------------------------------------

    def decidi(self, testo: str, storia: list[dict] | None = None,
               slot: str = "") -> Decisione:
        t0 = time.perf_counter()
        c = self.fast_path(testo)
        if c is not None:
            self.fast_hit += 1
            return Decisione(tuple(dict(a) for a in c.azioni), "fast_path",
                             (time.perf_counter() - t0) * 1000,
                             risposta=c.risposta)

        # PHASE2 — le frasi chiuse con un parametro, dopo i comandi
        # dell'utente: una frase che l'utente si e' configurato vince.
        detto = normalizza(testo)
        # La dettatura prima delle altre, e sulla frase originale: vedi
        # `frasi_chiuse.dettatura`.
        chiamate = frasi_chiuse.dettatura(testo) or frasi_chiuse.riconosci(
            detto, self._numeri_a_schermo())
        if chiamate is not None:
            self.fast_hit += 1
            return Decisione(chiamate, "fast_path", (time.perf_counter() - t0) * 1000)

        if not self.usa_llm or self.tool_router is None:
            d = Decisione((), "chat", (time.perf_counter() - t0) * 1000)
        else:
            d = self.tool_router.decidi(testo, storia, slot)
        if d.e_strumento:
            self.llm_hit += 1
        elif d.chiarimento is None:
            # PHASE2, dopo le prove: una frase che sembra un comando e che
            # nessuno ha capito non va alla conversazione, che risponderebbe
            # "Cliccato" senza aver cliccato. Si chiede.
            d.chiarimento = frasi_chiuse.chiarimento(detto)
        return d

    def stats(self) -> dict:
        return {"fast_path": self.fast_hit, "llm": self.llm_hit,
                "comandi_configurati": len(self.comandi),
                "frasi": len(self._voci)}
