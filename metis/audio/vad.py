"""Segmentazione del parlato con Silero VAD.

Silero vuole blocchi di esattamente 512 campioni a 16 kHz: e' il motivo per cui
`capture.py` emette proprio quella dimensione.

PERCHE' NON SI USA VADIterator (revisione del 2026-09-20)
La prima versione si appoggiava a `VADIterator`, che comunica solo gli eventi
start/end e non quali blocchi siano parlato. Per sapere quando l'utente avesse
davvero smesso si usava una soglia di livello arbitraria (rms > -55 dBFS), e su
questa macchina produceva una dispersione dell'endpointing da 90 a 390 ms: le
code di parola cadono fra il rumore di fondo e quella soglia, quindi a volte
contavano come voce e a volte no.

Il modello espone gia' una probabilita' di parlato per blocco, e chiamarlo
direttamente costa 0,68 ms contro un budget di 32. La logica start/end e'
quindi implementata qui, con isteresi, e il numero magico e' sparito.

SUI DUE TIMESTAMP
`min_silence_ms` e' il silenzio che si attende prima di chiudere una frase.
Quel ritardo e' reale e va nel budget di latenza, ma non e' l'istante in cui
l'utente ha smesso di parlare. Il segmento riporta percio' due tempi:

    t_speech_end  ultimo blocco con probabilita' di parlato  <- ZERO per NFR-1
    t_endpoint    istante in cui la frase e' stata chiusa

La differenza e' il costo dell'endpointing, che si misura invece di assumerlo.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import torch
from silero_vad import load_silero_vad

from metis.audio.capture import TARGET_SR, VAD_BLOCK, Block

BLOCK_MS = VAD_BLOCK / TARGET_SR * 1000.0        # 32.0 ms


@dataclass(frozen=True)
class Segment:
    pcm: np.ndarray            # mono float32 a 16 kHz
    t_speech_start: float
    t_speech_end: float        # riferimento zero per la latenza end-to-end
    t_endpoint: float
    duration_s: float
    max_prob: float

    @property
    def endpoint_cost_ms(self) -> float:
        return (self.t_endpoint - self.t_speech_end) * 1000.0


class SpeechSegmenter:
    """Consuma Block e restituisce un Segment a ogni frase completa."""

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_ms: int = 250,
        min_speech_ms: int = 200,
        preroll_ms: int = 300,
        max_utterance_s: float = 30.0,
    ):
        self.model = load_silero_vad()
        self.threshold = threshold
        # Isteresi: serve una probabilita' piu' alta per DICHIARARE l'inizio che
        # per restare dentro. Senza, le brevi cadute di energia in mezzo a una
        # parola spezzano la frase in due.
        self.neg_threshold = max(0.05, threshold - 0.15)
        self.min_silence_blocks = max(1, round(min_silence_ms / BLOCK_MS))
        self.min_speech_blocks = max(1, round(min_speech_ms / BLOCK_MS))
        self._preroll: deque[np.ndarray] = deque(maxlen=max(1, round(preroll_ms / BLOCK_MS)))
        self._max_blocks = round(max_utterance_s * 1000 / BLOCK_MS)

        self._active = False
        self._buf: list[np.ndarray] = []
        self._silence_run = 0
        self._speech_blocks = 0
        self._t_start = 0.0
        self._t_last_speech = 0.0
        self._max_prob = 0.0

    def reset(self) -> None:
        self.model.reset_states()
        self._active = False
        self._buf.clear()
        self._preroll.clear()
        self._silence_run = 0
        self._speech_blocks = 0
        self._max_prob = 0.0

    def _prob(self, pcm: np.ndarray) -> float:
        with torch.no_grad():
            return float(self.model(torch.from_numpy(pcm), TARGET_SR).item())

    def feed(self, block: Block) -> Segment | None:
        now = time.perf_counter()
        p = self._prob(block.pcm)

        if not self._active:
            self._preroll.append(block.pcm)
            if p >= self.threshold:
                self._active = True
                self._t_start = now
                self._t_last_speech = now
                self._silence_run = 0
                self._speech_blocks = 1
                self._max_prob = p
                self._buf = list(self._preroll)   # recupera le sillabe iniziali
                self._preroll.clear()
            return None

        # frase in corso
        self._buf.append(block.pcm)
        self._max_prob = max(self._max_prob, p)

        if p >= self.neg_threshold:
            self._t_last_speech = now
            self._silence_run = 0
            self._speech_blocks += 1
        else:
            self._silence_run += 1

        too_long = len(self._buf) >= self._max_blocks
        ended = self._silence_run >= self.min_silence_blocks

        if not (ended or too_long):
            return None

        # Frase troppo corta per essere parlato: probabile colpo di tastiera
        # o schiocco. Si scarta invece di mandarla allo STT.
        if self._speech_blocks < self.min_speech_blocks and not too_long:
            self.reset()
            return None

        pcm = np.concatenate(self._buf)
        seg = Segment(
            pcm=pcm,
            t_speech_start=self._t_start,
            t_speech_end=self._t_last_speech,
            t_endpoint=now,
            duration_s=pcm.size / TARGET_SR,
            max_prob=self._max_prob,
        )
        self.reset()
        return seg
