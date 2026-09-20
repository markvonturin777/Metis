"""Strumentazione della latenza per turno.

QUESTA STRUTTURA RESTA IN TUTTO IL PROGETTO. In M0 la riempie lo scheletro da
riga di comando, in M3 la legge la dashboard, in M7 e' l'evidenza di NFR-1.

IL RIFERIMENTO ZERO E' `t_speech_end`, cioe' l'istante in cui l'utente ha
davvero smesso di parlare — NON quando il VAD se ne accorge. Misurare dal
secondo regalerebbe gratis ~264 ms e i numeri sembrerebbero migliori di
quanto sono.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

LOG = Path("data/logs/turns.jsonl")


@dataclass
class TurnMetrics:
    turn_id: str
    t_speech_end: float                  # riferimento zero
    t_endpoint: float = 0.0
    t_stt_done: float = 0.0
    t_llm_sent: float = 0.0
    t_ttft: float = 0.0
    t_first_chunk: float = 0.0           # prima frase pronta per il TTS
    t_tts_done: float = 0.0              # primo audio sintetizzato
    t_first_audio: float = 0.0           # ← NFR-1 si misura qui

    audio_s: float = 0.0
    tokens: int = 0
    tok_per_s: float = 0.0
    vram_gb: float = 0.0
    transcript: str = ""
    reply: str = ""
    extra: dict = field(default_factory=dict)

    # -- scomposizione, in millisecondi dal riferimento zero ---------------

    def _ms(self, t: float) -> float:
        return (t - self.t_speech_end) * 1000.0 if t else 0.0

    @property
    def endpointing_ms(self) -> float:
        return self._ms(self.t_endpoint)

    @property
    def stt_ms(self) -> float:
        return (self.t_stt_done - self.t_endpoint) * 1000.0 if self.t_stt_done else 0.0

    @property
    def ttft_ms(self) -> float:
        return (self.t_ttft - self.t_llm_sent) * 1000.0 if self.t_ttft else 0.0

    @property
    def first_chunk_ms(self) -> float:
        return (self.t_first_chunk - self.t_ttft) * 1000.0 if self.t_first_chunk else 0.0

    @property
    def tts_ms(self) -> float:
        return (self.t_tts_done - self.t_first_chunk) * 1000.0 if self.t_tts_done else 0.0

    @property
    def total_ms(self) -> float:
        """Fine parlato → primo fonema udibile. E' NFR-1."""
        return self._ms(self.t_first_audio)

    def breakdown(self) -> dict[str, float]:
        return {
            "endpointing": self.endpointing_ms,
            "stt": self.stt_ms,
            "ttft": self.ttft_ms,
            "prima_frase": self.first_chunk_ms,
            "tts": self.tts_ms,
            "totale": self.total_ms,
        }

    def append_to_log(self, path: Path = LOG) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {k: v for k, v in asdict(self).items() if not k.startswith("t_")}
        row["ts"] = time.time()
        row.update(self.breakdown())
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


BUDGET = {
    "endpointing": (200, 300),
    "stt": (150, 350),
    "ttft": (150, 400),
    "prima_frase": (0, 330),
    "tts": (100, 250),
    "totale": (0, 1200),          # p50 di NFR-1
}


def report(turns: list[TurnMetrics]) -> str:
    """Tabella di scomposizione con confronto al budget di §6.2."""
    if not turns:
        return "nessun turno registrato"
    rows = [t.breakdown() for t in turns]
    out = [
        "",
        "=" * 68,
        f"  SCOMPOSIZIONE LATENZA  —  {len(turns)} turni",
        "=" * 68,
        f"  {'stadio':<14} {'p50':>9} {'p95':>9} {'budget':>14}  esito",
        "-" * 68,
    ]
    for stage, (lo, hi) in BUDGET.items():
        v = np.array([r[stage] for r in rows])
        p50, p95 = np.percentile(v, 50), np.percentile(v, 95)
        flag = "OK" if p50 <= hi else "!!"
        out.append(
            f"  {flag} {stage:<12} {p50:>6.0f} ms {p95:>6.0f} ms "
            f"{f'{lo}-{hi} ms':>14}"
        )
    tot = np.array([r["totale"] for r in rows])
    out += [
        "-" * 68,
        f"  NFR-1  p50 {np.percentile(tot, 50):.0f} ms (target < 1200)  "
        f"p95 {np.percentile(tot, 95):.0f} ms (target < 1800)",
        "=" * 68,
    ]
    return "\n".join(out)
