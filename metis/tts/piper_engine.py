"""Sintesi vocale con Piper — motore alternativo a Kokoro.

Nasce come piano B di §10 della specifica, ma in M0 giorno 5 e' diventato un
candidato a pieno titolo: Piper e' ONNX, non torch, quindi non risente della
scelta di installare torch CPU-only e potenzialmente e' molto piu' rapido.

La decisione fra i due si prende con l'orecchio e con il cronometro, non a
priori: vedi `benchmarks/tts_compare.py`.

PHASE3 — LA VELOCITA' DI LETTURA
Paola a velocita' 1 e' lenta: l'utente, provate anche le voci di Kokoro, ha
scelto Paola a 1,2. Piper la chiama `length_scale`, ed e' l'inverso: quanto
durano i fonemi. Velocita' 1,2 vuol dire `length_scale` 1/1,2 = 0,83. Frasi
piu' corte costano anche meno da sintetizzare.
"""

from __future__ import annotations

import time
import wave
from io import BytesIO
from pathlib import Path

import numpy as np

VOICES_DIR = Path("data/piper")
DEFAULT_VOICE = "it_IT-paola-medium"
VELOCITA_MIN, VELOCITA_MAX = 0.5, 2.0


def valida_velocita(velocita: float) -> float:
    """Un valore fuori da qui e' un errore di battitura in `tts.toml`, non una
    scelta: si dice subito, invece di far parlare Metis a velocita' 12."""
    v = float(velocita)
    if not VELOCITA_MIN <= v <= VELOCITA_MAX:
        raise ValueError(f"velocita' della voce fuori intervallo ({VELOCITA_MIN}-"
                         f"{VELOCITA_MAX}): {velocita}")
    return v


class PiperEngine:
    def __init__(self, voice: str = DEFAULT_VOICE, voices_dir: Path = VOICES_DIR,
                 velocita: float = 1.0):
        from piper import PiperVoice, SynthesisConfig

        model = voices_dir / f"{voice}.onnx"
        if not model.exists():
            raise FileNotFoundError(
                f"voce {voice} assente. Scarica con:\n"
                f"  python -m piper.download_voices --download-dir {voices_dir} {voice}"
            )
        self.voice_name = voice
        self.velocita = valida_velocita(velocita)
        self.voice = PiperVoice.load(str(model))
        self.sample_rate = self.voice.config.sample_rate
        # None a velocita' 1: la sintesi resta identica a quella di sempre.
        self._config = (None if self.velocita == 1.0
                        else SynthesisConfig(length_scale=1.0 / self.velocita))

    def warmup(self) -> float:
        t0 = time.perf_counter()
        self.synth("Sistemi operativi.")
        return (time.perf_counter() - t0) * 1000.0

    def synth(self, text: str):
        from metis.tts.kokoro_engine import Synthesis

        t0 = time.perf_counter()
        buf = BytesIO()
        with wave.open(buf, "wb") as wav:
            self.voice.synthesize_wav(text, wav, syn_config=self._config)
        buf.seek(0)
        with wave.open(buf, "rb") as wav:
            raw = wav.readframes(wav.getnframes())
            sr = wav.getframerate()
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return Synthesis(pcm, sr, text, (time.perf_counter() - t0) * 1000.0)
