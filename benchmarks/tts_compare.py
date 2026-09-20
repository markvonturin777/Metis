"""M0 giorno 5 — decision gate sul TTS: Kokoro contro Piper.

Genera le 10 frasi di prova con tutte le voci candidate e misura la latenza.
La qualita' si giudica con l'orecchio: il confronto e' inutile se non lo si
ascolta, e §10 della specifica dice esplicitamente che il supporto italiano
di Kokoro va verificato, non assunto.

Le frasi non sono casuali: coprono prosodia dichiarativa e interrogativa,
numeri, nomi propri inglesi in frase italiana, urgenza e ironia. Le numero 5
e 6 sono le decisive — la prima la si sentira' centinaia di volte, la seconda
definisce se la persona di Metis funziona.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

OUT = Path("data/tts_compare")

PHRASES = [
    "I sistemi sono perfettamente operativi.",
    "Ha davvero intenzione di aprire ventisette schede?",
    "La CPU è al sessantatré per cento, la VRAM a sei virgola due gigabyte.",
    "Aprirò Visual Studio Code e GitHub Desktop.",
    "Informazione non presente nei sistemi.",
    "Le danze abbiano inizio non appena lo desidera.",
    "Promemoria impostato per domani alle diciassette.",
    "Attenzione: la temperatura della GPU ha raggiunto ottantadue gradi.",
    "Perché no. In fondo è solo il suo computer.",
    "Cerco su investing.com le notizie sui mercati.",
]


def engines():
    from metis.tts.kokoro_engine import KokoroEngine
    from metis.tts.piper_engine import PiperEngine

    out = []
    for voice in ("if_sara", "im_nicola"):
        try:
            out.append((f"kokoro_{voice}", KokoroEngine(voice=voice)))
        except Exception as e:
            print(f"  kokoro {voice}: non disponibile ({e})")
    for voice in ("it_IT-paola-medium", "it_IT-riccardo-x_low"):
        try:
            short = voice.replace("it_IT-", "").replace("-", "_")
            out.append((f"piper_{short}", PiperEngine(voice=voice)))
        except Exception as e:
            print(f"  piper {voice}: non disponibile ({e})")
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("carico i motori...")
    engs = engines()
    for name, e in engs:
        e.warmup()
        print(f"  {name}: pronto")

    stats: dict[str, list[float]] = {name: [] for name, _ in engs}
    index = []

    print("\nsintetizzo...")
    for i, text in enumerate(PHRASES):
        row = {"idx": i, "text": text, "files": {}}
        for name, eng in engs:
            s = eng.synth(text)
            path = OUT / f"{i:02d}_{name}.wav"
            sf.write(path, s.pcm, s.sample_rate)
            stats[name].append(s.latency_ms)
            row["files"][name] = path.name
        index.append(row)
        print(f"  [{i}] {text[:52]}")

    (OUT / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n" + "=" * 70)
    print("  LATENZA DI SINTESI")
    print("=" * 70)
    print(f"  {'motore':<26} {'media':>9} {'max':>9}   budget 100-250 ms")
    for name, _ in engs:
        v = np.array(stats[name])
        flag = "OK " if v.mean() <= 250 else "!! "
        print(f"  {flag}{name:<24} {v.mean():>6.0f} ms {v.max():>6.0f} ms")

    print("\n" + "=" * 70)
    print("  ORA ASCOLTA")
    print("=" * 70)
    print(f"  I file sono in {OUT.resolve()}")
    print("  Confronta la stessa frase fra i motori: 00_*.wav, 01_*.wav, ...")
    print("\n  Le due decisive:")
    print("    05_*.wav  'Informazione non presente nei sistemi.'  <- la sentirai spesso")
    print("    06_*.wav  'Le danze abbiano inizio...'              <- definisce la persona")


if __name__ == "__main__":
    main()
