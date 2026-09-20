"""Rivaluta lo STT sul corpus gia' registrato, senza rifare le registrazioni.

E' il motivo per cui `stt_check.py` salva i WAV: confrontare configurazioni
diverse sullo STESSO audio, invece di rileggere le frasi ogni volta — che
introdurrebbe la variabilita' della pronuncia nel confronto.

Configurazioni a confronto:
  * baseline         small, nessun aiuto
  * hotwords         small + vocabolario di dominio via initial_prompt
  * medium           modello piu' grande, se la VRAM lo consente
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from metis.stt.metrics import diff_words, wer
from metis.stt.whisper_engine import WhisperEngine

CORPUS = Path("data/corpus")

# Parole che il modello non puo' indovinare da solo: nome dell'assistente,
# prodotti, termini domestici. Whisper le usa come contesto, non come vincolo.
HOTWORDS = (
    "Metis. Visual Studio Code. GitHub Desktop. Ollama. "
    "friggitrice ad aria. Banca Centrale Europea. investing punto com. "
    "schermo, finestra, monitor, promemoria, commercialista."
)


def load_corpus() -> list[dict]:
    files = sorted(CORPUS.glob("*_small.jsonl"))
    if not files:
        sys.exit("nessun corpus in data/corpus — esegui prima stt_check.py")
    rows = [json.loads(line) for line in files[-1].open(encoding="utf-8")]
    for r in rows:
        pcm, sr = sf.read(CORPUS / r["wav"], dtype="float32")
        assert sr == 16000
        r["pcm"] = pcm
    print(f"corpus: {files[-1].name} — {len(rows)} frasi\n")
    return rows


def evaluate(rows: list[dict], name: str, model: str, prompt: str | None) -> dict:
    eng = WhisperEngine(model)
    eng.warmup()
    errs = words = 0
    lat: list[float] = []
    hyps: list[str] = []
    for r in rows:
        tr = eng.transcribe(r["pcm"], initial_prompt=prompt)
        rate, e, w = wer(r["reference"], tr.text)
        errs += e
        words += w
        lat.append(tr.latency_ms)
        hyps.append(tr.text)
    return {
        "name": name,
        "model": model,
        "wer": errs / words if words else 0.0,
        "errors": errs,
        "words": words,
        "lat_mean": float(np.mean(lat)),
        "lat_p95": float(np.percentile(lat, 95)),
        "hyps": hyps,
    }


def main() -> None:
    rows = load_corpus()

    configs = [
        ("baseline  small", "small", None),
        ("hotwords  small", "small", HOTWORDS),
    ]
    if "--medium" in sys.argv:
        configs += [("baseline  medium", "medium", None),
                    ("hotwords  medium", "medium", HOTWORDS)]

    results = []
    for name, model, prompt in configs:
        print(f"valuto: {name} ...")
        results.append(evaluate(rows, name, model, prompt))

    print("\n" + "=" * 74)
    print(f"  {'configurazione':<18} {'WER':>7} {'errori':>8} {'STT medio':>11} {'p95':>8}")
    print("=" * 74)
    for r in results:
        flag = "OK " if r["wer"] < 0.12 else "!! "
        print(
            f"  {flag}{r['name']:<16} {r['wer'] * 100:6.1f}% "
            f"{r['errors']:>4}/{r['words']:<3} {r['lat_mean']:>8.0f} ms "
            f"{r['lat_p95']:>7.0f} ms"
        )
    print("=" * 74)
    print("  target NFR-5: WER < 12%   |   budget latenza STT: 150-350 ms")

    base, best = results[0], min(results, key=lambda r: r["wer"])
    if best is not base:
        print(f"\n  migliore: {best['name'].strip()} "
              f"({base['wer'] * 100:.1f}% -> {best['wer'] * 100:.1f}%)")

    print("\n  DIFFERENZE RIMASTE NELLA CONFIGURAZIONE MIGLIORE")
    for r, hyp in zip(rows, best["hyps"]):
        d = diff_words(r["reference"], hyp)
        if d:
            print(f"    [{r['idx']}] {r['reference']}")
            for a, b in d:
                print(f"         {a!r} -> {b!r}")


if __name__ == "__main__":
    main()
