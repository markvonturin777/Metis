"""T0 — stato della macchina. Sola lettura, nessun effetto.

Riusa la strumentazione di M0: le stesse letture che hanno prodotto i numeri
di NFR-3 e NFR-4, esposte al modello invece che al banco di prova.
"""

from __future__ import annotations

from metis.llm.schemas import GetTelemetry
from metis.security.audit import Tier
from metis.tools.registry import REGISTRY


@REGISTRY.strumento(Tier.T0, GetTelemetry)
def _get_telemetry(call: GetTelemetry) -> dict:
    """Stato di GPU, CPU e memoria."""
    import psutil

    out: dict = {
        "cpu_percento": psutil.cpu_percent(interval=0.1),
        "ram_percento": psutil.virtual_memory().percent,
        "ram_disponibile_gb": round(psutil.virtual_memory().available / 1024**3, 2),
    }
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        out["vram_usata_gb"] = round(mem.used / 1024**3, 2)
        out["vram_totale_gb"] = round(mem.total / 1024**3, 2)
        out["gpu_percento"] = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
    except Exception as exc:                      # noqa: BLE001
        # Nessuna GPU, driver assente, nvml non inizializzabile: e' uno
        # strumento di sola lettura, degrada invece di fallire.
        out["vram"] = f"non disponibile ({type(exc).__name__})"
    return out
