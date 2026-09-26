"""Quanto costa la sintesi, voce per voce, sulla CPU (PHASE3, analisi del 2026-09-26).

    python benchmarks/tts_misura.py

Il primo pezzo di ogni risposta passa dal TTS prima di essere sentito: la sua
latenza si somma a ogni turno (§6.2 della specifica, budget 100-250 ms). Qui
una frase corta (~25 caratteri, come il primo pezzo) e una lunga, mediana di 4
prove, per le voci installate in `data/piper` e per Kokoro.

Misura del 2026-09-26: Piper 51/135 ms (paola), 52/104 ms (libritts_r inglese);
Kokoro `if_sara` su PyTorch CPU 585/1281 ms. Il costo dipende dal motore, non
dalla lingua.
"""

from __future__ import annotations

import statistics
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

FRASI = {
    "it": ("I sistemi sono operativi.",
           "Informazione non presente nei sistemi, ma posso cercarla sul web se lo desidera."),
    "en": ("All systems are operational.",
           "That information is not in my systems, but I can look it up on the web if you wish."),
}
VOCI_PIPER = Path("data/piper")


def misura(nome: str, synth, frasi) -> None:
    synth(frasi[0])                                   # riscaldamento
    for f in frasi:
        tempi = []
        for _ in range(4):
            t0 = time.perf_counter()
            s = synth(f)
            tempi.append((time.perf_counter() - t0) * 1000)
        print(f"{nome:34s} {len(f):3d} car  {statistics.median(tempi):6.0f} ms  "
              f"audio {getattr(s, 'audio_s', 0):.1f} s")


def main() -> None:
    from metis.tts import kokoro_engine, piper_engine

    for modello in sorted(VOCI_PIPER.glob("*.onnx")):
        voce = modello.stem
        lingua = "it" if voce.startswith("it_") else "en"
        e = piper_engine.PiperEngine(voice=voce, voices_dir=VOCI_PIPER)
        misura(f"piper {voce}", e.synth, FRASI[lingua])
    k = kokoro_engine.KokoroEngine(voice="if_sara", lang_code="i")
    misura("kokoro if_sara (PyTorch, cpu)", k.synth, FRASI["it"])


if __name__ == "__main__":
    main()
