"""La collocazione nella finestra e' la trasformazione che conta di piu':
senza, il modello impara la POSIZIONE invece della parola, e in esecuzione —
dove il parlato arriva in mezzo a un flusso continuo — sbaglia.

Il test vive qui e non in wakeword/ perche' verifica codice, non dati.
"""
import importlib.util
import numpy as np

spec = importlib.util.spec_from_file_location("ef", "wakeword/extract_features.py")
ef = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ef)


def _parola(dur_s=0.9):
    """Impulso riconoscibile che sta per la parola pronunciata."""
    n = int(dur_s * ef.SR)
    return (np.ones(n, dtype=np.float32) * 0.5)


def test_finestra_sempre_di_due_secondi():
    """16 finestre di embedding = 2,000 s esatti. Non negoziabile."""
    rng = np.random.default_rng(0)
    for dur in (0.3, 0.9, 1.9, 2.0, 3.5):
        out = ef.place_in_window(_parola(dur), rng)
        assert out.size == ef.CLIP_SAMPLES == 32000


def test_la_posizione_varia_davvero():
    """Se la parola cadesse sempre allo stesso offset, l'augmentation non
    servirebbe a nulla."""
    rng = np.random.default_rng(1)
    parola = _parola(0.5)
    offsets = set()
    for _ in range(40):
        out = ef.place_in_window(parola, rng)
        offsets.add(int(np.nonzero(out)[0][0]))
    assert len(offsets) > 20, f"solo {len(offsets)} posizioni distinte su 40"


def test_clip_lungo_viene_ritagliato_non_troncato_sempre_uguale():
    rng = np.random.default_rng(2)
    lungo = np.arange(48000, dtype=np.float32) / 48000
    inizi = {float(ef.place_in_window(lungo, rng)[0]) for _ in range(30)}
    assert len(inizi) > 15, "il ritaglio parte sempre dallo stesso punto"


def test_parola_conservata_integralmente():
    """Augmentation non deve tagliare pezzi della parola."""
    rng = np.random.default_rng(3)
    parola = _parola(1.0)
    out = ef.place_in_window(parola, rng)
    assert np.count_nonzero(out) == parola.size


def test_augment_non_satura():
    """Il clipping distrugge le transizioni consonantiche: peggio di un
    livello basso, come misurato in M0 sulla taratura del Yeti."""
    rng = np.random.default_rng(4)
    for _ in range(50):
        out = ef.augment(_parola(1.0), rng, [])
        assert np.abs(out).max() <= 1.0


def test_rumore_rosa_ha_spettro_decrescente():
    """Il rumore rosa somiglia al rumore ambientale — ventole, brusio —
    molto piu' del bianco."""
    rng = np.random.default_rng(5)
    n = ef.pink_noise(32000, rng)
    spec = np.abs(np.fft.rfft(n))
    basse = spec[10:200].mean()
    alte = spec[3000:6000].mean()
    assert basse > alte * 2, "lo spettro non decresce: non e' rumore rosa"


def test_snr_rispettato_entro_una_tolleranza():
    """Se l'SNR chiesto non e' quello ottenuto, l'augmentation non copre le
    condizioni che crede di coprire."""
    rng = np.random.default_rng(6)
    pulito = ef.place_in_window(_parola(1.5), rng)
    sp = np.mean(pulito**2)
    rumore = ef.pink_noise(32000, rng)
    for snr_db in (5.0, 20.0):
        npw = np.mean(rumore**2)
        scaled = rumore * np.sqrt(sp / (npw * 10 ** (snr_db / 10)))
        ottenuto = 10 * np.log10(sp / np.mean(scaled**2))
        assert abs(ottenuto - snr_db) < 0.5
