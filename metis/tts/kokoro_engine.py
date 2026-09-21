"""Sintesi vocale con Kokoro, su CPU.

PERCHE' SU CPU
Decisione di §3.2 della specifica: Kokoro ha 82M parametri e resta ampiamente
in tempo reale su un 5800X. Tenerlo sulla CPU libera ~0,4 GB di VRAM, che sulla
2070 Super valgono piu' della manciata di millisecondi risparmiati.

RIPRODUZIONE INTERROMPIBILE
`stop()` deve fermare l'audio entro poche decine di ms: e' il presupposto del
barge-in di M1. Non basta smettere di accodare, va svuotata anche la coda di
riproduzione, altrimenti Metis tace un istante e poi riparte da solo — che e'
il bug piu' fastidioso di tutta quella fase.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

KOKORO_SR = 24_000
VOICES_IT = ("if_sara", "im_nicola")


@dataclass(frozen=True)
class Synthesis:
    pcm: np.ndarray
    sample_rate: int
    text: str
    latency_ms: float

    @property
    def audio_s(self) -> float:
        return self.pcm.size / self.sample_rate

    @property
    def rtf(self) -> float:
        """Real-time factor. Sotto 1 significa piu' veloce del tempo reale."""
        return (self.latency_ms / 1000.0) / self.audio_s if self.audio_s else 0.0


class KokoroEngine:
    def __init__(self, voice: str = "if_sara", lang_code: str = "i", speed: float = 1.0):
        from kokoro import KPipeline

        self.voice = voice
        self.speed = speed
        self.pipeline = KPipeline(lang_code=lang_code)

    def warmup(self) -> float:
        t0 = time.perf_counter()
        self.synth("Sistemi operativi.")
        return (time.perf_counter() - t0) * 1000.0

    def synth(self, text: str) -> Synthesis:
        t0 = time.perf_counter()
        chunks = [
            audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            for _, _, audio in self.pipeline(text, voice=self.voice, speed=self.speed)
        ]
        pcm = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
        return Synthesis(pcm, KOKORO_SR, text, (time.perf_counter() - t0) * 1000.0)


class Player:
    """Riproduzione su thread, con coda e interruzione immediata."""

    def __init__(self, sample_rate: int = KOKORO_SR):
        self.sample_rate = sample_rate
        self._q: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.speaking = threading.Event()
        # Che cosa sta suonando ADESSO. Serve a chi deve attribuire un evento
        # acustico alla frase giusta: la coda tiene due frasi di anticipo,
        # quindi "l'ultima sintetizzata" e' un'etichetta sbagliata.
        self.now_playing = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                continue
            pcm, etichetta = item
            if pcm is None:
                continue
            self.speaking.set()
            self.now_playing = etichetta
            try:
                sd.play(pcm, self.sample_rate)
                sd.wait()
            finally:
                if self._q.empty():
                    self.speaking.clear()
                    self.now_playing = None

    def enqueue(self, pcm: np.ndarray, etichetta=None) -> None:
        """L'etichetta e' facoltativa: chi deve sapere cosa sta suonando la
        passa, gli altri no."""
        self._q.put((pcm, etichetta))

    def pending(self) -> int:
        """Frasi ancora in coda. Serve a chi deve tenerla piena."""
        return self._q.qsize()

    def wait_drained(self, timeout: float = 120.0) -> bool:
        """Attende che la coda sia vuota e l'ultima frase finita di suonare.

        Serve a sapere QUANDO Metis ha smesso di parlare: e' il momento in cui
        lo stato torna a IN_ASCOLTO e il microfono riprende. Senza, PLAYBACK_DONE
        scatterebbe mentre gli altoparlanti stanno ancora suonando e i frame
        dell'eco rientrerebbero nel VAD — esattamente il loop che M1 esiste per
        rompere.
        """
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if self._q.empty() and not self.speaking.is_set():
                return True
            time.sleep(0.02)
        return False

    def stop(self) -> None:
        """Interruzione immediata: audio fermo E coda svuotata.

        Svuotare la coda e' la meta' che si dimentica. Senza, dopo il barge-in
        Metis riprende a parlare con la frase successiva gia' accodata.
        """
        sd.stop()
        self.now_playing = None
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self.speaking.clear()

    def close(self) -> None:
        self._stop.set()
        sd.stop()
        if self._thread:
            self._thread.join(timeout=1.0)
