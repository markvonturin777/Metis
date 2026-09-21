"""Orchestratore M1 — sostituisce lo scheletro di M0.

Differenze rispetto a `skeleton.py`, che era sequenziale e usa-e-getta:

* lo stato e' esplicito e governato da `StateMachine`;
* i frame audio vanno a destinazioni diverse a seconda dello stato, ed e' li'
  che vivono half-duplex gating e barge-in;
* il TTS gira su un thread proprio, altrimenti non lo si potrebbe interrompere;
* la generazione LLM e' annullabile a meta'.

IL TURNO GIRA SU UN THREAD PROPRIO (corretto il 2026-09-21)
La prima versione chiamava `_process` in modo sincrono dentro `on_audio`.
Sembrava innocuo ed era invece fatale: mentre il turno elabora e parla,
`on_audio` non viene piu' chiamato, quindi il rilevatore di wake word non
riceve frame, quindi **il barge-in non puo' scattare**. La funzione che il
barge-in deve interrompere era proprio quella che ne impediva il rilevamento.

IL TOKEN DI ANNULLAMENTO E' PER TURNO, NON CONDIVISO
Un token unico da resettare a ogni turno ha una corsa: un annullamento che
arriva subito prima del `reset()` viene inghiottito. Ogni turno crea invece
il proprio token; il barge-in annulla quello corrente e basta. Niente reset,
niente corsa.

IL BARGE-IN RICHIEDE DI FERMARE TRE COSE, NON UNA
Dimenticarne una produce il bug piu' fastidioso di questa fase: Metis si
interrompe, tace un istante, e riparte da solo perche' la frase successiva era
gia' in coda. Le tre sono:

    1. l'audio in riproduzione        -> player.stop()
    2. la coda di riproduzione        -> svuotata dentro player.stop()
    3. lo stream di generazione LLM   -> CancelToken

Il test `test_barge_in_ferma_tutte_e_tre` verifica proprio questo.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from metis.audio.capture import Block
from metis.audio.vad import Segment, SpeechSegmenter
from metis.core.metrics import TurnMetrics
from metis.core.state_machine import Event, State, StateMachine, Transition
from metis.llm.client import CancelToken


@dataclass
class Deps:
    """Dipendenze iniettate: in test si sostituiscono con finti."""

    wakeword: Callable[[np.ndarray], bool]
    stt: Callable[[np.ndarray], object]
    llm_stream: Callable[..., object]
    tts_synth: Callable[[str], object]
    player: object
    system_prompt: str = ""


@dataclass
class Counters:
    wake_detections: int = 0
    barge_ins: int = 0
    frames_to_vad: int = 0
    frames_muted: int = 0
    turns: int = 0
    discarded: int = 0
    cancel_latency_ms: list[float] = field(default_factory=list)


class Orchestrator:
    def __init__(self, deps: Deps, on_transition: Callable[[Transition], None] | None = None):
        self.d = deps
        self.sm = StateMachine(on_transition=on_transition)
        self.seg = SpeechSegmenter()
        # Un token PER TURNO: vedi la nota in testa al modulo.
        self._cancel: CancelToken | None = None
        self.counters = Counters()
        self.history: list[dict] = (
            [{"role": "system", "content": deps.system_prompt}] if deps.system_prompt else []
        )
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self.synchronous = False      # solo nei test: evita i thread

    # -- ingresso audio ----------------------------------------------------

    def on_audio(self, block: Block) -> None:
        """Instrada un blocco audio in base allo stato.

        E' il cuore di M1: le due righe che decidono chi riceve i frame sono
        l'intera strategia anti-eco.
        """
        st = self.sm.state

        # Il rilevatore di wake word riceve anche durante PARLATO: e' il
        # barge-in. Cerca un pattern specifico, quindi l'eco degli
        # altoparlanti non lo attiva come farebbe con un VAD generico.
        if self.sm.wake_active and self.d.wakeword(block.pcm):
            self.counters.wake_detections += 1
            self._on_wake_word()
            return

        # Half-duplex: in PARLATO, DORMIENTE e INTERROTTO i frame NON
        # raggiungono VAD e STT. Lo stream resta aperto, i blocchi si
        # scartano: riaprire il device costerebbe 50-200 ms e a volte fallisce.
        if self.sm.stt_muted:
            self.counters.frames_muted += 1
            return

        self.counters.frames_to_vad += 1
        segment = self.seg.feed(block)

        if segment is not None and st is State.TRASCRIZIONE:
            self.sm.fire(Event.SPEECH_END)
            self._start_turn(segment)
        elif segment is None and st is State.IN_ASCOLTO and self.seg._active:
            self.sm.fire(Event.SPEECH_START)

    def _on_wake_word(self) -> None:
        st = self.sm.state
        if st in (State.PARLATO, State.GENERAZIONE):
            t0 = time.perf_counter()
            self.sm.fire(Event.WAKE_WORD)          # -> INTERROTTO
            self._stop_everything()
            self.counters.barge_ins += 1
            self.counters.cancel_latency_ms.append((time.perf_counter() - t0) * 1000)
            self.sm.fire(Event.TTS_STOPPED)        # -> IN_ASCOLTO
            self.seg.reset()
        elif st is State.DORMIENTE:
            self.sm.fire(Event.WAKE_WORD)
            self.seg.reset()

    def _stop_everything(self) -> None:
        """Le tre cose da fermare. Ometterne una e' il bug classico."""
        with self._lock:
            tok = self._cancel
        if tok is not None:
            tok.cancel()              # 1+3: lo stream si ferma al prossimo token
        self.d.player.stop()          # 2: audio corrente + coda di riproduzione

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancel is not None and self._cancel.cancelled

    # -- avvio del turno ---------------------------------------------------

    def _start_turn(self, segment: Segment) -> None:
        """Il turno gira su un thread proprio: altrimenti `on_audio` resta
        bloccato e il barge-in non puo' essere rilevato."""
        if self.synchronous:
            self._process(segment)
            return
        self._worker = threading.Thread(
            target=self._process, args=(segment,), daemon=True, name="metis-turn"
        )
        self._worker.start()

    # -- turno -------------------------------------------------------------

    def _process(self, segment: Segment) -> None:
        m = TurnMetrics(
            turn_id=uuid.uuid4().hex[:8],
            t_speech_end=segment.t_speech_end,
            t_endpoint=segment.t_endpoint,
            audio_s=segment.duration_s,
        )
        tr = self.d.stt(segment.pcm)
        m.t_stt_done = time.perf_counter()
        m.transcript = getattr(tr, "text", "")

        if not m.transcript or getattr(tr, "suspect", False):
            self.counters.discarded += 1
            self.sm.fire(Event.NO_SPEECH)
            return

        self.sm.fire(Event.INTENT_CHAT)
        self.history.append({"role": "user", "content": m.transcript})

        # Token NUOVO per questo turno. Se un barge-in e' gia' arrivato su un
        # token precedente, non contamina questo; e se arriva adesso, non puo'
        # essere inghiottito da un reset.
        with self._lock:
            if self._cancel is not None and self._cancel.cancelled:
                return                      # annullato prima ancora di partire
            tok = CancelToken()
            self._cancel = tok

        m.t_llm_sent = time.perf_counter()
        first = True
        gm = None
        for chunk, gm in self.d.llm_stream(self.history, cancel=tok):
            if tok.cancelled:
                break
            syn = self.d.tts_synth(chunk)
            self.d.player.enqueue(syn.pcm)
            if first:
                m.t_ttft = m.t_llm_sent + (getattr(gm, "ttft_ms", 0) or 0) / 1000.0
                m.t_first_chunk = m.t_ttft
                m.t_tts_done = time.perf_counter()
                m.t_first_audio = time.perf_counter()
                self.sm.fire(Event.FIRST_AUDIO)     # -> PARLATO
                first = False

        if tok.cancelled:
            return                                   # gia' in IN_ASCOLTO

        if gm is not None:
            m.tokens = gm.tokens
            m.reply = gm.text
            self.history.append({"role": "assistant", "content": gm.text})
        self.counters.turns += 1
        m.append_to_log()

        self.d.player.wait_drained()
        self.sm.fire(Event.PLAYBACK_DONE)

    # -- manutenzione ------------------------------------------------------

    def tick(self) -> None:
        """Da chiamare ~1 Hz: fa scattare i timeout degli stati."""
        self.sm.check_timeout()
