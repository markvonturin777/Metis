"""Macchina a stati dell'orchestratore — il cuore di M1.

Wake word, anti-eco e barge-in non sono tre funzionalita' separate: sono tre
CONSEGUENZE di questa macchina. Il loop di auto-innesco si rompe qui, nello
stato PARLATO, dove i frame non arrivano a VAD e STT.

PERCHE' LE TRANSIZIONI SONO UN DATO E NON UNA CATENA DI `if`
Una macchina scritta a condizioni annidate non e' testabile senza audio, e i
bug che produce non sono riproducibili. Qui la tabella `TRANSITIONS` e' un
dizionario: si puo' iniettare qualunque sequenza di eventi e verificare lo
stato risultante in millisecondi, senza microfono.

UNA TRANSIZIONE NON PREVISTA NON E' UN'ECCEZIONE
Gli eventi audio arrivano in modo asincrono e fuori sequenza di continuo: un
blocco in coda, un timeout scattato un istante dopo la transizione. Se ogni
evento inatteso sollevasse, Metis morirebbe dopo pochi minuti. Si registra e
si prosegue.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto


class State(Enum):
    DORMIENTE = auto()        # solo wake word attivo, consumo minimo
    IN_ASCOLTO = auto()       # VAD attivo, attende parlato
    TRASCRIZIONE = auto()     # parlato in corso, accumula audio
    ELABORAZIONE = auto()     # routing intento
    RICERCA_WEB = auto()      # M5
    GENERAZIONE = auto()      # LLM in streaming
    ESECUZIONE = auto()       # M2
    ATTESA_CONFERMA = auto()  # M2, azioni T3
    PARLATO = auto()          # TTS in riproduzione — STT SOSPESO
    INTERROTTO = auto()       # barge-in rilevato
    ERRORE = auto()


class Event(Enum):
    WAKE_WORD = auto()
    PTT = auto()
    SPEECH_START = auto()
    SPEECH_END = auto()
    NO_SPEECH = auto()
    INTENT_KNOWN = auto()     # fast-path, M2
    INTENT_CHAT = auto()
    INTENT_WEB = auto()       # M5
    CONTEXT_READY = auto()    # M5
    NEEDS_CONFIRM = auto()    # M2
    CONFIRMED = auto()
    DENIED = auto()
    FIRST_AUDIO = auto()
    PLAYBACK_DONE = auto()
    TTS_STOPPED = auto()
    DONE = auto()
    TIMEOUT = auto()
    FAILED = auto()


# Gli stati in cui i frame audio NON devono raggiungere VAD e STT.
# E' il livello L1 della strategia anti-eco: half-duplex gating.
STT_MUTED = frozenset({State.DORMIENTE, State.PARLATO, State.INTERROTTO})

# Gli stati in cui il rilevatore di wake word resta attivo. Include PARLATO:
# e' il livello L2, il barge-in. Il rilevatore cerca un pattern specifico ed
# e' quindi intrinsecamente robusto all'eco dei propri altoparlanti.
#
# In V1.0 la wake word e' SPENTA e il barge-in passa dal push-to-talk, che
# emette PTT negli stessi stati. L'insieme resta: e' il contratto che dice
# "qui il microfono e' aperto mentre Metis parla", e cancellarlo renderebbe
# caro riaccendere la wake word in v2.
WAKE_ACTIVE = frozenset(
    {State.DORMIENTE, State.IN_ASCOLTO, State.PARLATO, State.GENERAZIONE}
)

TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.DORMIENTE, Event.WAKE_WORD): State.IN_ASCOLTO,
    (State.DORMIENTE, Event.PTT): State.IN_ASCOLTO,

    (State.IN_ASCOLTO, Event.SPEECH_START): State.TRASCRIZIONE,
    (State.IN_ASCOLTO, Event.TIMEOUT): State.DORMIENTE,
    (State.IN_ASCOLTO, Event.PTT): State.DORMIENTE,        # toggle

    (State.TRASCRIZIONE, Event.SPEECH_END): State.ELABORAZIONE,
    (State.TRASCRIZIONE, Event.NO_SPEECH): State.IN_ASCOLTO,
    (State.TRASCRIZIONE, Event.TIMEOUT): State.ELABORAZIONE,   # tronca

    (State.ELABORAZIONE, Event.INTENT_KNOWN): State.ESECUZIONE,
    (State.ELABORAZIONE, Event.INTENT_CHAT): State.GENERAZIONE,
    (State.ELABORAZIONE, Event.INTENT_WEB): State.RICERCA_WEB,
    (State.ELABORAZIONE, Event.NO_SPEECH): State.IN_ASCOLTO,   # STT vuoto
    (State.ELABORAZIONE, Event.TIMEOUT): State.ERRORE,
    (State.ELABORAZIONE, Event.FAILED): State.ERRORE,

    (State.RICERCA_WEB, Event.CONTEXT_READY): State.GENERAZIONE,
    (State.RICERCA_WEB, Event.TIMEOUT): State.GENERAZIONE,     # degrada
    (State.RICERCA_WEB, Event.FAILED): State.GENERAZIONE,

    (State.GENERAZIONE, Event.FIRST_AUDIO): State.PARLATO,
    (State.GENERAZIONE, Event.WAKE_WORD): State.INTERROTTO,    # barge-in precoce
    (State.GENERAZIONE, Event.PTT): State.INTERROTTO,          # barge-in da tastiera
    (State.GENERAZIONE, Event.TIMEOUT): State.ERRORE,
    (State.GENERAZIONE, Event.FAILED): State.ERRORE,

    (State.ESECUZIONE, Event.NEEDS_CONFIRM): State.ATTESA_CONFERMA,
    (State.ESECUZIONE, Event.DONE): State.PARLATO,
    (State.ESECUZIONE, Event.FAILED): State.ERRORE,
    (State.ESECUZIONE, Event.TIMEOUT): State.ERRORE,

    (State.ATTESA_CONFERMA, Event.CONFIRMED): State.ESECUZIONE,
    (State.ATTESA_CONFERMA, Event.DENIED): State.PARLATO,
    (State.ATTESA_CONFERMA, Event.TIMEOUT): State.PARLATO,     # rifiuto implicito

    (State.PARLATO, Event.WAKE_WORD): State.INTERROTTO,        # barge-in
    (State.PARLATO, Event.PTT): State.INTERROTTO,              # barge-in da tastiera
    (State.PARLATO, Event.PLAYBACK_DONE): State.IN_ASCOLTO,
    (State.PARLATO, Event.FAILED): State.ERRORE,              # riproduzione fallita
    (State.PARLATO, Event.TIMEOUT): State.IN_ASCOLTO,

    (State.INTERROTTO, Event.TTS_STOPPED): State.IN_ASCOLTO,
    (State.INTERROTTO, Event.TIMEOUT): State.IN_ASCOLTO,

    (State.ERRORE, Event.DONE): State.PARLATO,
    (State.ERRORE, Event.TIMEOUT): State.IN_ASCOLTO,
}

# Timeout per stato, in secondi. None = nessun timeout.
TIMEOUTS: dict[State, float | None] = {
    State.DORMIENTE: None,
    State.IN_ASCOLTO: 8.0,
    State.TRASCRIZIONE: 30.0,
    State.ELABORAZIONE: 5.0,
    State.RICERCA_WEB: 8.0,
    State.GENERAZIONE: 30.0,
    State.ESECUZIONE: 15.0,
    State.ATTESA_CONFERMA: 20.0,      # deve coincidere con il broker, M2
    State.PARLATO: 120.0,
    State.INTERROTTO: 1.0,
    State.ERRORE: 5.0,
}


@dataclass
class Transition:
    frm: State
    event: Event
    to: State
    at: float = field(default_factory=time.perf_counter)


class StateMachine:
    """Macchina a stati con timeout e osservatori.

    Thread-safe: gli eventi arrivano dal thread audio, dal worker LLM e dal
    timer dei timeout.
    """

    def __init__(self, on_transition: Callable[[Transition], None] | None = None):
        self._state = State.DORMIENTE
        self._lock = threading.RLock()
        self._entered_at = time.perf_counter()
        self._on_transition = on_transition
        self.history: list[Transition] = []
        self.rejected: list[tuple[State, Event]] = []

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    @property
    def stt_muted(self) -> bool:
        """Se True, i frame non vanno a VAD e STT. Vedi STT_MUTED."""
        return self.state in STT_MUTED

    @property
    def wake_active(self) -> bool:
        """Se True, il rilevatore di wake word riceve i frame."""
        return self.state in WAKE_ACTIVE

    def time_in_state(self) -> float:
        with self._lock:
            return time.perf_counter() - self._entered_at

    def fire(self, event: Event) -> State:
        """Applica un evento. Ritorna lo stato risultante.

        Una transizione non prevista viene registrata e ignorata: lo stato
        resta invariato. Non solleva mai.
        """
        with self._lock:
            key = (self._state, event)
            target = TRANSITIONS.get(key)
            if target is None:
                self.rejected.append(key)
                return self._state

            tr = Transition(self._state, event, target)
            self._state = target
            self._entered_at = tr.at
            self.history.append(tr)

        # fuori dal lock: l'osservatore puo' essere lento
        if self._on_transition is not None:
            self._on_transition(tr)
        return target

    def check_timeout(self) -> bool:
        """Da chiamare periodicamente. Emette TIMEOUT se lo stato e' scaduto."""
        with self._lock:
            limit = TIMEOUTS.get(self._state)
            expired = limit is not None and (time.perf_counter() - self._entered_at) > limit
        if expired:
            self.fire(Event.TIMEOUT)
        return expired

    def reset(self) -> None:
        with self._lock:
            self._state = State.DORMIENTE
            self._entered_at = time.perf_counter()


def unreachable_states() -> set[State]:
    """Stati che nessuna transizione raggiunge. Utile come test di integrita'."""
    reachable = {State.DORMIENTE} | {to for to in TRANSITIONS.values()}
    return set(State) - reachable


def dead_end_states() -> set[State]:
    """Stati da cui non si esce. Sarebbero blocchi permanenti."""
    with_exit = {frm for frm, _ in TRANSITIONS}
    return set(State) - with_exit
