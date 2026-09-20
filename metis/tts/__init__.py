"""Sintesi vocale. Il backend si sceglie da config/tts.toml."""
from __future__ import annotations

import tomllib
from pathlib import Path

_CONFIG = Path("config/tts.toml")


def load_config() -> dict:
    if not _CONFIG.exists():
        return {"engine": {"backend": "piper"}, "piper": {"voice": "it_IT-paola-medium"}}
    return tomllib.loads(_CONFIG.read_text(encoding="utf-8"))


def create_engine(backend: str | None = None):
    """Motore TTS configurato. Default: Piper, vedi config/tts.toml."""
    cfg = load_config()
    backend = backend or cfg["engine"]["backend"]

    if backend == "piper":
        from metis.tts.piper_engine import PiperEngine

        p = cfg.get("piper", {})
        return PiperEngine(
            voice=p.get("voice", "it_IT-paola-medium"),
            voices_dir=Path(p.get("voices_dir", "data/piper")),
        )
    if backend == "kokoro":
        from metis.tts.kokoro_engine import KokoroEngine

        k = cfg.get("kokoro", {})
        return KokoroEngine(voice=k.get("voice", "if_sara"), lang_code=k.get("lang_code", "i"))
    raise ValueError(f"backend TTS sconosciuto: {backend}")
