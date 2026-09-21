"""Kill switch: sospende le capacita' che agiscono sul mondo.

COSA SOSPENDE E COSA NO
T2 (input sintetico) e T3 (effetti esterni). T0 e T1 continuano: leggere la
telemetria o aprire VS Code non e' cio' da cui si vuole scappare quando si
schiaccia la scorciatoia in fretta. Se sospendesse tutto, Metis diventerebbe
muto e inerte e la si userebbe di meno — e un interruttore di sicurezza che
si evita di usare non e' un interruttore di sicurezza.

E' UN INTERRUTTORE, NON UN PULSANTE
Resta attivo finche' non lo si rimette a posto. Un ripristino automatico dopo
N secondi sembrerebbe comodo e sarebbe sbagliato: chi lo ha premuto lo ha
premuto perche' stava succedendo qualcosa che non voleva, e decidere per lui
quando e' passata la paura non spetta al programma.

LO STESSO TASTO FA ANCHE TACERE METIS
`Ctrl+Alt+Shift+M` chiama sia `Orchestrator.panic()` sia questo. Sono due
effetti della stessa intenzione — "fermati" — e separarli vorrebbe dire
chiedere all'utente di ricordarsi quale dei due tasti serve mentre sta
cercando di fermare qualcosa.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from metis.security.audit import Tier

# I livelli che vengono sospesi. T0 e T1 restano vivi: vedi la nota in testa.
TIER_SOSPESI: frozenset[Tier] = frozenset({Tier.T2, Tier.T3})


class KillSwitch:
    """Stato condiviso fra il thread delle hotkey e quello degli strumenti."""

    def __init__(self, on_change: Callable[[bool], None] | None = None):
        self._evento = threading.Event()
        self._on_change = on_change
        self.attivato_a: float | None = None
        self.attivazioni = 0

    @property
    def attivo(self) -> bool:
        return self._evento.is_set()

    def sospendi(self) -> None:
        if self._evento.is_set():
            return
        self._evento.set()
        self.attivato_a = time.perf_counter()
        self.attivazioni += 1
        if self._on_change is not None:
            self._on_change(True)

    def ripristina(self) -> None:
        if not self._evento.is_set():
            return
        self._evento.clear()
        self.attivato_a = None
        if self._on_change is not None:
            self._on_change(False)

    def commuta(self) -> bool:
        """Ritorna lo stato risultante. E' cio' che lega la scorciatoia."""
        if self.attivo:
            self.ripristina()
        else:
            self.sospendi()
        return self.attivo

    def blocca(self, tier: Tier) -> str | None:
        """Motivo del rifiuto, oppure None. La forma di tutte le guardie."""
        if self.attivo and tier in TIER_SOSPESI:
            return f"kill switch attivo: {tier.value} sospeso"
        return None


# Istanza condivisa dall'applicazione. I test costruiscono la propria.
KILL_SWITCH = KillSwitch()
