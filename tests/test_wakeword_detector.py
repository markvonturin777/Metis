"""Regola di conferma e sensibilita' all'allineamento.

La `Confirmer` e' logica pura: si verifica senza modello e senza audio.
La parte sull'allineamento usa invece le registrazioni vere, perche' e' un
fatto sui dati, non sul codice.
"""
import glob
from pathlib import Path

import numpy as np
import pytest

from metis.audio.wakeword import Confirmer


# --- regola di conferma ------------------------------------------------------

def conf(threshold=0.95, consecutive=2, refractory_s=2.0):
    return Confirmer(threshold, consecutive, refractory_s)


def test_un_picco_isolato_non_basta():
    """E' il motivo per cui la regola esiste: un colpo di tastiera fortunato."""
    c = conf()
    assert c.feed(0.99, now=0.0) is False


def test_due_blocchi_consecutivi_scattano():
    c = conf()
    assert c.feed(0.99, now=0.00) is False
    assert c.feed(0.99, now=0.03) is True


def test_due_blocchi_non_consecutivi_non_scattano():
    c = conf()
    c.feed(0.99, now=0.00)
    c.feed(0.10, now=0.03)          # la serie si spezza
    assert c.feed(0.99, now=0.06) is False


def test_il_refrattario_sopprime():
    c = conf()
    c.feed(0.99, now=0.0)
    assert c.feed(0.99, now=0.03) is True
    for t in (0.1, 0.2, 0.5, 1.0, 1.9):
        assert c.feed(0.99, now=t) is False, f"scattato di nuovo a {t}s"


def test_dopo_il_refrattario_si_puo_riscattare():
    c = conf()
    c.feed(0.99, now=0.0)
    c.feed(0.99, now=0.03)
    assert c.feed(0.99, now=2.10) is False   # primo blocco della nuova serie
    assert c.feed(0.99, now=2.13) is True


def test_la_soglia_e_inclusiva():
    c = conf(threshold=0.95)
    c.feed(0.95, now=0.0)
    assert c.feed(0.95, now=0.03) is True


# --- sensibilita' all'allineamento (fatto misurato, non opinione) ------------

MODELLO = Path("data/wakeword/hey_metis.onnx")
POSITIVI = sorted(glob.glob("wakeword/live/*_pos_*.wav"))
pytestmark_data = pytest.mark.skipif(
    not MODELLO.exists() or not POSITIVI,
    reason="servono il modello addestrato e le registrazioni dal vivo",
)


@pytestmark_data
def test_la_wake_word_vera_e_stabile_allo_sfasamento():
    """Il risultato su cui poggia la regola a doppia fase.

    Se un giorno i positivi diventassero instabili quanto i quasi-falsi, la
    doppia fase perderebbe senso e questo test lo direbbe subito.
    """
    import soundfile as sf

    from dataclasses import replace

    from metis.audio.wakeword import WakeWordConfig, WakeWordDetector

    # Acceso a forza: in V1.0 la configurazione lo tiene spento (D1), ma qui
    # si verifica una proprieta' del MODELLO, che vale comunque e che deve
    # continuare a valere quando in v2 lo si riaccende.
    det = WakeWordDetector(replace(WakeWordConfig.load(), enabled=True))

    def massimo(pcm):
        det.reset()
        det._last_fire = 0.0
        det.scores.clear()
        for i in range(0, (pcm.size // 512) * 512, 512):
            det.feed(pcm[i : i + 512])
        return max(det.scores)

    a, sr = sf.read(POSITIVI[1], dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    a = a.astype(np.float32)
    punteggi = [massimo(a[o:]) for o in (0, 128, 256, 384)]
    escursione = max(punteggi) - min(punteggi)

    assert min(punteggi) >= 0.9, f"un allineamento manca la wake word: {punteggi}"
    assert escursione < 0.15, (
        f"la wake word vera e' diventata instabile allo sfasamento: {escursione:.3f}"
    )
