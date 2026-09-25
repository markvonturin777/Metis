"""M0 — Strumento di misura.

Risponde alle due domande che determinano il progetto:
    1. Sta in 8 GB di VRAM?
    2. Risponde in meno di 2 secondi?

Va eseguito PRIMA di scrivere il resto di M0: se le risposte sono no,
cambia il modello, non il codice.

Uso:
    python benchmarks/vram_latency.py                    # 8B e 4B, 10 run
    python benchmarks/vram_latency.py --models qwen3:8b  # solo uno
    python benchmarks/vram_latency.py --runs 20
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import ollama
import pynvml  # pacchetto: nvidia-ml-py

RESULTS_DIR = Path(__file__).parent / "results"

# Prompt rappresentativi dell'uso reale: brevi, in italiano, conversazionali.
# Misurare su prompt lunghi in inglese darebbe numeri inutilizzabili.
PROMPTS = [
    "Che ore sono?",
    "Come stanno i sistemi?",
    "Spiegami in due frasi cos'è la latenza di inferenza.",
    "Riassumi in tre righe perché una GPU da 8 GB limita la scelta del modello.",
    "Dimmi qualcosa di interessante sul Ryzen 5800X.",
]

SYSTEM = (
    "Sei Metis, assistente personale. Rispondi in italiano, "
    "in modo conciso: al massimo tre frasi."
)


# --------------------------------------------------------------------------- VRAM


class VramSampler:
    """Campiona la VRAM occupata a 5 Hz su un thread separato."""

    def __init__(self, hz: float = 5.0):
        self.interval = 1.0 / hz
        self.samples: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        pynvml.nvmlInit()
        self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)

    def read_gb(self) -> float:
        info = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
        return info.used / 1024**3

    def total_gb(self) -> float:
        return pynvml.nvmlDeviceGetMemoryInfo(self.handle).total / 1024**3

    def gpu_name(self) -> str:
        name = pynvml.nvmlDeviceGetName(self.handle)
        return name.decode() if isinstance(name, bytes) else name

    def temp_c(self) -> int:
        return pynvml.nvmlDeviceGetTemperature(self.handle, pynvml.NVML_TEMPERATURE_GPU)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.samples.append(self.read_gb())
            time.sleep(self.interval)

    def start(self) -> None:
        self.samples.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def peak(self) -> float:
        return max(self.samples) if self.samples else 0.0


# --------------------------------------------------------------------------- LLM


def _chat_stream(model: str, prompt: str, options: dict):
    """Chiama Ollama in streaming con la thinking mode DISATTIVA.

    think=False e' critico: in thinking mode il TTFT passa da ~300 ms a 5-20 s
    e i numeri diventano inutilizzabili. Le versioni piu' vecchie del client
    non conoscono il parametro, per cui si ripiega sulla direttiva /no_think.
    """
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    try:
        return ollama.chat(
            model=model, messages=messages, stream=True, think=False, options=options
        )
    except TypeError:
        messages[1]["content"] = prompt + " /no_think"
        return ollama.chat(model=model, messages=messages, stream=True, options=options)


@dataclass
class RunResult:
    prompt: str
    ttft_ms: float
    gen_ms: float
    tokens: int
    tok_per_s: float
    reply: str


def single_run(model: str, prompt: str, options: dict) -> RunResult:
    t0 = time.perf_counter()
    ttft: float | None = None
    tokens = 0
    parts: list[str] = []

    for chunk in _chat_stream(model, prompt, options):
        piece = chunk.get("message", {}).get("content", "")
        if not piece:
            continue
        if ttft is None:
            ttft = time.perf_counter() - t0
        tokens += 1
        parts.append(piece)

    total = time.perf_counter() - t0
    ttft = ttft if ttft is not None else total
    gen = max(total - ttft, 1e-6)

    return RunResult(
        prompt=prompt,
        ttft_ms=ttft * 1000,
        gen_ms=gen * 1000,
        tokens=tokens,
        tok_per_s=tokens / gen,
        reply="".join(parts).strip(),
    )


# --------------------------------------------------------------------------- bench


@dataclass
class ModelReport:
    model: str
    runs: int
    vram_baseline_gb: float
    vram_loaded_gb: float
    vram_peak_gb: float
    ttft_p50_ms: float
    ttft_p95_ms: float
    tok_per_s_mean: float
    tokens_mean: float
    gpu_temp_max_c: int
    samples: list[dict]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def bench_model(model: str, runs: int, num_ctx: int, sampler: VramSampler) -> ModelReport:
    options = {
        "num_ctx": num_ctx,
        "temperature": 0.7,
        "top_p": 0.9,
    }

    print(f"\n{'=' * 70}\n  {model}\n{'=' * 70}")

    # 1. baseline: nessun modello caricato
    print("  scarico eventuali modelli residenti...")
    try:
        ollama.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass
    time.sleep(3)
    baseline = sampler.read_gb()
    print(f"  VRAM a riposo ............ {baseline:.2f} GB")

    # 2. warm-up: carica il modello. La VRAM va letta DOPO una generazione
    #    reale, non dopo il pull: altrimenti si sottostima sistematicamente.
    print("  warm-up (caricamento modello)...")
    t_load = time.perf_counter()
    single_run(model, "Ciao.", options)
    print(f"  caricato in {time.perf_counter() - t_load:.1f} s")
    time.sleep(1)
    loaded = sampler.read_gb()
    print(f"  VRAM a modello carico .... {loaded:.2f} GB  (+{loaded - baseline:.2f})")

    # 3. misura
    sampler.start()
    temp_max = 0
    results: list[RunResult] = []
    for i in range(runs):
        prompt = PROMPTS[i % len(PROMPTS)]
        r = single_run(model, prompt, options)
        results.append(r)
        temp_max = max(temp_max, sampler.temp_c())
        print(
            f"  [{i + 1:2d}/{runs}] TTFT {r.ttft_ms:6.0f} ms | "
            f"{r.tok_per_s:5.1f} tok/s | {r.tokens:3d} tok | {r.reply[:45]}..."
        )
    sampler.stop()

    ttfts = [r.ttft_ms for r in results]
    return ModelReport(
        model=model,
        runs=runs,
        vram_baseline_gb=round(baseline, 2),
        vram_loaded_gb=round(loaded, 2),
        vram_peak_gb=round(sampler.peak(), 2),
        ttft_p50_ms=round(percentile(ttfts, 0.50)),
        ttft_p95_ms=round(percentile(ttfts, 0.95)),
        tok_per_s_mean=round(statistics.mean(r.tok_per_s for r in results), 1),
        tokens_mean=round(statistics.mean(r.tokens for r in results), 1),
        gpu_temp_max_c=temp_max,
        samples=[asdict(r) for r in results],
    )


# --------------------------------------------------------------------------- output


def verdict(ok: bool) -> str:
    return "OK" if ok else "NO"


def print_table(reports: list[ModelReport], vram_total: float) -> None:
    """Stampa la tabella gia' nel formato di SPECS/PHASE0/TRACKING/M0_tracking.md §3.1."""
    print(f"\n\n{'=' * 70}")
    print("  RISULTATI — da incollare in SPECS/PHASE0/TRACKING/M0_tracking.md §3.1")
    print(f"{'=' * 70}\n")

    head = "| Metrica | Target | " + " | ".join(r.model for r in reports) + " | Esito |"
    sep = "| :-- | :-- | " + " | ".join(":--" for _ in reports) + " | :-: |"
    print(head)
    print(sep)

    rows = [
        ("Picco VRAM", "<= 7,2 GB", [f"{r.vram_peak_gb:.2f} GB" for r in reports],
         all(r.vram_peak_gb <= 7.2 for r in reports)),
        ("TTFT p50", "< 400 ms", [f"{r.ttft_p50_ms:.0f} ms" for r in reports],
         all(r.ttft_p50_ms < 400 for r in reports)),
        ("TTFT p95", "—", [f"{r.ttft_p95_ms:.0f} ms" for r in reports], True),
        ("tok/s", ">= 45", [f"{r.tok_per_s_mean:.1f}" for r in reports],
         all(r.tok_per_s_mean >= 45 for r in reports)),
        ("Temp GPU max", "—", [f"{r.gpu_temp_max_c} C" for r in reports], True),
    ]
    for label, target, values, ok in rows:
        print(f"| {label} | {target} | " + " | ".join(values) + f" | {verdict(ok)} |")

    print(f"\nVRAM totale della scheda: {vram_total:.2f} GB")
    print("\nNota: questi numeri coprono SOLO l'LLM. In M0 giorno 3 va aggiunta")
    print("la VRAM dello STT (faster-whisper small, stima ~0,6 GB) per avere")
    print("il budget reale di SPECS/PHASE0/TRACKING/M0_tracking.md §3.3.\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen3:8b", "qwen3:4b"])
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--num-ctx", type=int, default=8192)
    args = ap.parse_args()

    sampler = VramSampler()
    print(f"GPU: {sampler.gpu_name()}  —  {sampler.total_gb():.2f} GB totali")

    reports = [bench_model(m, args.runs, args.num_ctx, sampler) for m in args.models]
    print_table(reports, sampler.total_gb())

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"bench_{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "timestamp": stamp,
                "gpu": sampler.gpu_name(),
                "vram_total_gb": round(sampler.total_gb(), 2),
                "num_ctx": args.num_ctx,
                "reports": [asdict(r) for r in reports],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Dettaglio completo: {out}")


if __name__ == "__main__":
    main()
