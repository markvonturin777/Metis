"""PHASE3 — la velocita' della voce.

La velocita' si legge da `config/tts.toml` ([voce] velocita) e vale per
Piper e per Kokoro, che e' la riserva: se Piper cade, Metis non deve cambiare
ritmo. Un valore assurdo e' un errore di battitura, e si dice all'avvio.
"""
from pathlib import Path

import pytest

from metis import tts
from metis.tts.piper_engine import VOICES_DIR, PiperEngine, valida_velocita

PAOLA = VOICES_DIR / "it_IT-paola-medium.onnx"


@pytest.mark.parametrize("v", [0.5, 1, 1.3, 2.0])
def test_velocita_ammesse(v):
    assert valida_velocita(v) == float(v)


@pytest.mark.parametrize("v", [0, 0.4, 2.1, 12, -1])
def test_velocita_assurde(v):
    with pytest.raises(ValueError, match="velocita"):
        valida_velocita(v)


@pytest.mark.skipif(not PAOLA.exists(), reason="voce Paola non scaricata")
def test_piu_veloce_vuol_dire_parlato_piu_corto():
    frase = "Le danze abbiano inizio non appena lo desidera, e i sistemi sono pronti."
    normale = PiperEngine(velocita=1.0).synth(frase)
    rapida = PiperEngine(velocita=1.3).synth(frase)
    assert len(rapida.pcm) < 0.92 * len(normale.pcm)
    assert rapida.sample_rate == normale.sample_rate


@pytest.mark.skipif(not PAOLA.exists(), reason="voce Paola non scaricata")
def test_a_velocita_uno_la_sintesi_e_quella_di_sempre():
    assert PiperEngine(velocita=1.0)._config is None


def _config(tmp_path, monkeypatch, testo):
    f = tmp_path / "tts.toml"
    f.write_text(testo, encoding="utf-8")
    monkeypatch.setattr(tts, "_CONFIG", f)


@pytest.mark.skipif(not PAOLA.exists(), reason="voce Paola non scaricata")
def test_la_velocita_arriva_dalla_configurazione(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, '[voce]\nvelocita = 1.3\n[engine]\nbackend = "piper"\n'
                                   '[piper]\nvoice = "it_IT-paola-medium"\n')
    assert tts.create_engine().velocita == 1.3


def test_kokoro_riserva_ha_la_stessa_velocita(tmp_path, monkeypatch):
    from metis.tts import kokoro_engine

    visti = {}

    class Finto:
        def __init__(self, voice, lang_code, speed=1.0):
            visti["speed"] = speed
    monkeypatch.setattr(kokoro_engine, "KokoroEngine", Finto)
    _config(tmp_path, monkeypatch, '[voce]\nvelocita = 1.3\n[engine]\nbackend = "kokoro"\n')
    tts.create_engine()
    assert visti["speed"] == 1.3


def test_senza_la_voce_nella_configurazione_la_velocita_e_uno(tmp_path, monkeypatch):
    from metis.tts import kokoro_engine

    visti = {}
    monkeypatch.setattr(kokoro_engine, "KokoroEngine",
                        lambda voice, lang_code, speed=1.0: visti.setdefault("speed", speed))
    _config(tmp_path, monkeypatch, '[engine]\nbackend = "kokoro"\n')
    tts.create_engine()
    assert visti["speed"] == 1.0


def test_la_configurazione_del_repository_e_valida():
    import tomllib

    cfg = tomllib.loads(Path("config/tts.toml").read_text(encoding="utf-8"))
    assert valida_velocita(cfg["voce"]["velocita"]) == 1.3
