"""Misura prolungata di VRAM, temperatura e memoria di sistema.

Campiona passivamente a 1 Hz mentre il sistema viene usato davvero: e' una
misura piu' onesta di un carico sintetico, perche' cattura i picchi veri —
caricamento dei modelli, inferenza, sintesi, e le pause in mezzo.

Verifica NFR-4 (picco VRAM <= 7,2 GB) e anticipa NFR-10 (stabilita'): se la
VRAM o la RSS crescono in modo lineare invece di stabilizzarsi, e' un leak.

Uso:
    python benchmarks/vram_soak.py 72        # minuti
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil
import pynvml

OUT = Path("benchmarks/results")
CEILING_GB = 7.2          # NFR-4
WARN_GB = 7.5             # soglia di allarme di §3.2


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 72.0
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl = OUT / f"soak_{stamp}.jsonl"
    summary = OUT / f"soak_{stamp}_summary.txt"

    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
    total_gb = pynvml.nvmlDeviceGetMemoryInfo(gpu).total / 1024**3

    t_end = time.time() + minutes * 60
    samples: list[dict] = []
    peak = 0.0
    peak_at = 0.0
    breaches = 0
    t0 = time.time()

    with jsonl.open("w", encoding="utf-8") as f:
        while time.time() < t_end:
            mem = pynvml.nvmlDeviceGetMemoryInfo(gpu)
            vram = mem.used / 1024**3
            row = {
                "t": round(time.time() - t0, 1),
                "vram_gb": round(vram, 3),
                "gpu_temp_c": pynvml.nvmlDeviceGetTemperature(gpu, pynvml.NVML_TEMPERATURE_GPU),
                "gpu_util_pct": pynvml.nvmlDeviceGetUtilizationRates(gpu).gpu,
                "cpu_pct": psutil.cpu_percent(interval=None),
                "ram_gb": round(psutil.virtual_memory().used / 1024**3, 2),
            }
            samples.append(row)
            f.write(json.dumps(row) + "\n")
            f.flush()

            if vram > peak:
                peak, peak_at = vram, row["t"]
            if vram > WARN_GB:
                breaches += 1
            time.sleep(1.0)

    # --- analisi ---------------------------------------------------------
    v = [s["vram_gb"] for s in samples]
    r = [s["ram_gb"] for s in samples]
    n = len(v)
    q = max(1, n // 4)

    def trend(series: list[float]) -> float:
        """Differenza fra l'ultimo e il primo quarto: positiva = crescita."""
        return sum(series[-q:]) / q - sum(series[:q]) / q

    lines = [
        "=" * 64,
        f"  SOAK VRAM  —  {minutes:.0f} minuti, {n} campioni",
        "=" * 64,
        f"  VRAM totale scheda   : {total_gb:.2f} GB",
        f"  VRAM minima          : {min(v):.2f} GB",
        f"  VRAM mediana         : {sorted(v)[n // 2]:.2f} GB",
        f"  VRAM PICCO           : {peak:.2f} GB   (a {peak_at / 60:.1f} min)",
        f"  NFR-4 (<= {CEILING_GB} GB)     : {'RISPETTATO' if peak <= CEILING_GB else 'VIOLATO'}",
        f"  superamenti di {WARN_GB} GB : {breaches}",
        "",
        f"  temperatura GPU max  : {max(s['gpu_temp_c'] for s in samples)} C",
        f"  utilizzo GPU medio   : {sum(s['gpu_util_pct'] for s in samples) / n:.0f} %",
        f"  CPU media            : {sum(s['cpu_pct'] for s in samples) / n:.0f} %",
        "",
        "  DERIVA (ultimo quarto meno primo quarto)",
        f"    VRAM : {trend(v):+.3f} GB",
        f"    RAM  : {trend(r):+.3f} GB",
        "",
    ]
    drift = trend(v)
    if drift > 0.3:
        lines.append("  !! La VRAM cresce: possibile leak, o modelli caricati in corsa.")
    elif drift > 0.05:
        lines.append("  ~  Leggera crescita VRAM: plausibile se i modelli sono stati caricati")
        lines.append("     durante la sessione. Da riverificare in M7 a regime.")
    else:
        lines.append("  OK VRAM stabile.")
    lines.append(f"\n  dati: {jsonl}")

    text = "\n".join(lines)
    summary.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
