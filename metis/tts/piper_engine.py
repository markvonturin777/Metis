"""Sintesi vocale con Piper — motore alternativo a Kokoro.

Nasce come piano B di §10 della specifica, ma in M0 giorno 5 e' diventato un
candidato a pieno titolo: Piper e' ONNX, non torch, quindi non risente della
scelta di installare torch CPU-only e potenzialmente e' molto piu' rapido.

La decisione fra i due si prende con l'orecchio e con il cronometro, non a
priori: vedi `benchmarks/tts_compare.py`.
"""

from __future__ import annotations

import time
import wave
from io import BytesIO
from pathlib import Path

import numpy as np

VOICES_DIR = Path("data/piper")
DEFAULT_VOICE = "it_IT-paola-medium"


class PiperEngine:
    def __init__(self, voice: str = DEFAULT_VOICE, voices_dir: Path = VOICES_DIR):
        from piper import PiperVoice

        model = voices_dir / f"{voice}.onnx"
        if not model.exists():
            raise FileNotFoundError(
                f"voce {voice} assente. Scarica con:\n"
                f"  python -m piper.download_voices --download-dir {voices_dir} {voice}"
            )
        self.voice_name = voice
        self.voice = PiperVoice.load(str(model))
        self.sample_rate = self.voice.config.sample_rate

    def warmup(self) -> float:
        t0 = time.perf_counter()
        self.synth("Sistemi operativi.")
        return (time.perf_counter() - t0) * 1000.0

    def synth(self, text: str):
        from metis.tts.kokoro_engine import Synthesis

        t0 = time.perf_counter()
        buf = BytesIO()
        with wave.open(buf, "wb") as wav:
            self.voice.synthesize_wav(text, wav)
        buf.seek(0)
        with wave.open(buf, "rb") as wav:
            raw = wav.readframes(wav.getnframes())
            sr = wav.getframerate()
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return Synthesis(pcm, sr, text, (time.perf_counter() - t0) * 1000.0)
