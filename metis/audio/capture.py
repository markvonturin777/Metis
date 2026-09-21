"""Cattura microfono → blocchi mono a 16 kHz.

Vincoli hardware rilevati su questa macchina (2026-09-20):

* Blue Yeti Classic su WASAPI accetta **solo 48 kHz**. Ogni altra frequenza
  viene rifiutata con PaErrorCode -9997, quindi il resampling lo facciamo noi:
  non e' una scelta di qualita', e' l'unica strada.
* 48000 / 16000 = 3 esatto, quindi e' una decimazione pulita 3:1.
* Silero VAD vuole blocchi di **esattamente 512 campioni a 16 kHz** (32 ms).
  A monte servono quindi 1536 campioni a 48 kHz per blocco.
* Latenza dichiarata dal driver: 3 ms in modalita' low. Ampiamente sufficiente.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
import soxr

DEVICE_SR = 48_000
TARGET_SR = 16_000
VAD_BLOCK = 512                      # campioni a 16 kHz, imposto da Silero
DEVICE_BLOCK = VAD_BLOCK * (DEVICE_SR // TARGET_SR)   # 1536 a 48 kHz


@dataclass(frozen=True)
class Block:
    """Un blocco di 512 campioni float32 a 16 kHz, normalizzati in [-1, 1]."""

    pcm: np.ndarray
    rms_dbfs: float
    peak_dbfs: float


def _dbfs(x: np.ndarray) -> tuple[float, float]:
    if x.size == 0:
        return -120.0, -120.0
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(x)))
    to_db = lambda v: 20.0 * np.log10(v) if v > 1e-6 else -120.0  # noqa: E731
    return to_db(rms), to_db(peak)


def find_input_device(name_hint: str = "Yeti", hostapi: str = "Windows WASAPI") -> int:
    """Cerca il device per nome sull'host API preferita.

    Il Yeti compare su quattro host API diverse. WASAPI e' la scelta giusta:
    latenza piu' bassa di MME e DirectSound, piu' robusta di WDM-KS.
    """
    apis = sd.query_hostapis()
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        if name_hint.lower() not in dev["name"].lower():
            continue
        if apis[dev["hostapi"]]["name"] == hostapi:
            return idx
    raise RuntimeError(f"nessun device di ingresso '{name_hint}' su {hostapi}")


class AudioCapture:
    """Stream sempre aperto che emette blocchi da 512 campioni a 16 kHz.

    Lo stream **non si chiude mai** durante l'esecuzione: in M1 lo stato
    PARLATO scarta i frame invece di chiudere il device. Riaprirlo costerebbe
    50-200 ms e ogni tanto fallisce.
    """

    def __init__(self, device: int | None = None, maxsize: int = 256):
        self.device = device if device is not None else find_input_device()
        self.q: queue.Queue[Block] = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self._stream: sd.InputStream | None = None
        self._resampler: soxr.ResampleStream | None = None
        self._tail = np.empty(0, dtype=np.float32)
        self._lock = threading.Lock()

    # -- callback ----------------------------------------------------------

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            # overflow/underflow: va loggato, non ignorato
            self.dropped += 1

        # Downmix a mono. Il Yeti in modalita' Stereo usa due capsule diverse;
        # in Cardioide i due canali sono quasi identici. In entrambi i casi
        # la media e' la cosa giusta per il riconoscimento vocale.
        mono = indata.mean(axis=1).astype(np.float32)

        # Il resampling avviene qui dentro di proposito: soxr su 1536 campioni
        # costa una decina di microsecondi contro un budget di 32 ms per blocco.
        # Passarlo a un thread aggiungerebbe un salto di contesto per niente.
        out = self._resampler.resample_chunk(mono)

        # soxr non garantisce esattamente 512 campioni per chunk durante il
        # warm-up del filtro: si accumula e si emette a blocchi esatti.
        with self._lock:
            buf = np.concatenate((self._tail, out)) if self._tail.size else out
            n_full = buf.size // VAD_BLOCK
            for i in range(n_full):
                chunk = buf[i * VAD_BLOCK : (i + 1) * VAD_BLOCK]
                rms, peak = _dbfs(chunk)
                try:
                    self.q.put_nowait(Block(chunk.copy(), rms, peak))
                except queue.Full:
                    self.dropped += 1
            self._tail = buf[n_full * VAD_BLOCK :].copy()

    # -- ciclo di vita -----------------------------------------------------

    def start(self) -> None:
        self._resampler = soxr.ResampleStream(
            DEVICE_SR, TARGET_SR, 1, dtype="float32", quality="HQ"
        )
        self._tail = np.empty(0, dtype=np.float32)
        self._stream = sd.InputStream(
            device=self.device,
            samplerate=DEVICE_SR,
            channels=2,
            dtype="float32",
            blocksize=DEVICE_BLOCK,
            latency="low",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self) -> "AudioCapture":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- lettura -----------------------------------------------------------

    def read(self, timeout: float = 0.25) -> Block | None:
        """Un blocco, o None se entro `timeout` non ne arrivano.

        Diversa da `blocks()`, che a coda vuota termina: il ciclo principale
        deve invece restare vivo e usare le pause per far scattare i timeout
        della macchina a stati.
        """
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> int:
        """Butta via i blocchi accumulati. Ritorna quanti erano.

        Lo stream non si ferma mai: se il programma resta fermo — un
        `input()`, il caricamento di un modello — la coda continua a
        riempirsi, e la lettura successiva riceverebbe audio di alcuni
        secondi prima. Per una misura di livello significa misurare il
        momento sbagliato.
        """
        n = 0
        while True:
            try:
                self.q.get_nowait()
                n += 1
            except queue.Empty:
                return n

    def blocks(self, timeout: float | None = None):
        """Generatore di Block. Consuma la coda finche' lo stream e' attivo."""
        while self._stream is not None:
            try:
                yield self.q.get(timeout=timeout)
            except queue.Empty:
                return
