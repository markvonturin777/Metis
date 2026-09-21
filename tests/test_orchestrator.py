"""Barge-in e half-duplex, verificati con finti al posto di audio e modelli.

Il barge-in e' la funzionalita' con piu' insidie di M1: fermare due cose su
tre produce un bug che si manifesta come "Metis riparte da solo" e che dal
vivo e' difficile da riprodurre.
"""
from dataclasses import dataclass, field
import numpy as np
import pytest

from metis.audio.capture import Block
from metis.core.orchestrator import Deps, Orchestrator
from metis.core.state_machine import Event, State


# --- finti -------------------------------------------------------------------

class FakePlayer:
    def __init__(self):
        self.queue = []
        self.stopped = 0
        self.drained = 0
    def enqueue(self, pcm): self.queue.append(pcm)
    def stop(self):
        self.stopped += 1
        self.queue.clear()          # LA meta' che si dimentica
    def wait_drained(self): self.drained += 1


@dataclass
class FakeTranscript:
    text: str = "ciao"
    suspect: bool = False


@dataclass
class FakeGen:
    ttft_ms: float = 100.0
    tokens: int = 10
    text: str = "risposta finta"


@dataclass
class FakeSynth:
    pcm: np.ndarray = field(default_factory=lambda: np.zeros(100, np.float32))


def blocco(rms=-20.0):
    return Block(np.zeros(512, np.float32), rms, rms)


def make(wake_on_call=None, n_chunks=3, text="ciao"):
    """wake_on_call: indice della chiamata in cui la wake word scatta."""
    stato = {"chiamate": 0}
    def wakeword(pcm):
        stato["chiamate"] += 1
        return wake_on_call is not None and stato["chiamate"] == wake_on_call
    def llm_stream(history, cancel=None, **kw):
        gm = FakeGen()
        for _ in range(n_chunks):
            if cancel is not None and cancel.cancelled:
                return
            yield "frase di prova abbastanza lunga.", gm
    player = FakePlayer()
    d = Deps(wakeword=wakeword,
             stt=lambda pcm: FakeTranscript(text),
             llm_stream=llm_stream,
             tts_synth=lambda t: FakeSynth(),
             player=player)
    o = Orchestrator(d)
    o.synchronous = True      # niente thread nei test: deterministico
    return o, player


# --- half-duplex -------------------------------------------------------------

def test_in_parlato_i_frame_non_arrivano_al_vad():
    """L1: e' qui che si rompe il loop di auto-innesco con gli altoparlanti."""
    o, _ = make()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    assert o.sm.state is State.PARLATO
    prima = o.counters.frames_to_vad
    for _ in range(50):
        o.on_audio(blocco())
    assert o.counters.frames_to_vad == prima      # nessuno passato
    assert o.counters.frames_muted >= 50


def test_in_ascolto_i_frame_arrivano_al_vad():
    o, _ = make()
    o.sm.fire(Event.WAKE_WORD)
    for _ in range(10):
        o.on_audio(blocco())
    assert o.counters.frames_to_vad == 10


# --- barge-in ----------------------------------------------------------------

def test_barge_in_ferma_tutte_e_tre():
    """Audio, coda e stream LLM. Ometterne una: Metis riparte da solo."""
    from metis.llm.client import CancelToken
    o, player = make(wake_on_call=1)
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    # Un turno in volo: nel sistema reale `_process` gira su un thread proprio
    # e ha gia' registrato il suo token. Qui lo si simula.
    o._cancel = CancelToken()
    player.queue.extend([1, 2, 3])          # frasi gia' accodate

    o.on_audio(blocco())                    # scatta la wake word

    assert player.stopped == 1, "l'audio non e' stato fermato"
    assert player.queue == [], "la coda non e' stata svuotata: riprendera' a parlare"
    assert o.cancelled, "lo stream LLM non e' stato annullato"
    assert o.sm.state is State.IN_ASCOLTO
    assert o.counters.barge_ins == 1


def test_barge_in_misura_la_latenza():
    from metis.llm.client import CancelToken
    o, _ = make(wake_on_call=1)
    o._cancel = CancelToken()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    o.on_audio(blocco())
    assert len(o.counters.cancel_latency_ms) == 1
    assert o.counters.cancel_latency_ms[0] < 200   # NFR di M1


def _segmento():
    from metis.audio.vad import Segment
    import time as _t
    n = _t.perf_counter()
    return Segment(np.zeros(16000, np.float32), n, n, n, 1.0, 1.0)


def test_annullamento_a_meta_generazione():
    """Il generatore deve RISPETTARE il token, non solo riceverlo.

    L'annullamento arriva al terzo chunk, come farebbe un barge-in reale.
    """
    o, player = make(n_chunks=100)
    def llm_stream(history, cancel=None, **kw):
        gm = FakeGen()
        for i in range(100):
            if cancel is not None and cancel.cancelled:
                return
            if i == 3:
                cancel.cancel()          # barge-in a meta' flusso
            yield "frase di prova abbastanza lunga.", gm
    o.d.llm_stream = llm_stream
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert len(player.queue) <= 5, "il flusso non si e' fermato all'annullamento"


def test_ogni_turno_ha_il_proprio_token():
    """Un token condiviso da resettare ha una corsa: l'annullamento arrivato
    subito prima del reset verrebbe inghiottito."""
    o, _ = make(n_chunks=1)
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    primo = o._cancel
    o.sm.fire(Event.PLAYBACK_DONE) if o.sm.state.name == "PARLATO" else None
    o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert o._cancel is not primo, "il secondo turno riusa il token del primo"


def test_wake_word_in_dormiente_sveglia():
    o, _ = make(wake_on_call=1)
    assert o.sm.state is State.DORMIENTE
    o.on_audio(blocco())
    assert o.sm.state is State.IN_ASCOLTO
    assert o.counters.wake_detections == 1


def test_wake_word_non_ascoltata_in_trascrizione():
    """Mentre l'utente parla, dire 'Hey Metis' non deve resettare il turno."""
    o, _ = make(wake_on_call=1)
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START)
    assert o.sm.state is State.TRASCRIZIONE
    assert o.sm.wake_active is False
    o.on_audio(blocco())
    assert o.counters.wake_detections == 0   # il rilevatore non e' stato nemmeno chiamato


def test_trascrizione_sospetta_scartata():
    o, _ = make()
    o.d.stt = lambda pcm: FakeTranscript(".", suspect=True)
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert o.counters.discarded == 1
    assert o.sm.state is State.IN_ASCOLTO
