"""WAV -> feature di embedding, con augmentation.

PERCHE' NON SI USA `openwakeword.train`
Il modulo di training del progetto tira dentro speechbrain, datasets,
pronouncing, yaml e altro: una catena pensata per il loro notebook e le loro
sorgenti dati. Il contratto vero del modello e' invece banale, verificato
ispezionando i modelli preaddestrati:

    input  (batch, 16, 96) float32     16 finestre x 96 feature di embedding
    output (batch, 1)      float32     punteggio

Sedici finestre corrispondono a **esattamente 2,000 secondi** di audio a
16 kHz, misurato. Bastano quindi torch e numpy, gia' presenti nel runtime.

L'AUGMENTATION E' IL PUNTO, NON UN CONTORNO
Un modello addestrato su TTS pulito riconosce il TTS pulito. Deve invece
funzionare nella stanza dell'utente, con le ventole del PC, la musica, la
distanza dal microfono che cambia. Le tre trasformazioni che contano:

  * POSIZIONE nella finestra: senza, il modello impara che la parola comincia
    sempre allo stesso istante. In esecuzione arriva in mezzo a un flusso.
  * RUMORE a SNR variabile: e' la differenza fra studio e scrivania.
  * GUADAGNO: la distanza dal microfono cambia di continuo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from openwakeword.utils import AudioFeatures

DATA = Path("wakeword/data")
CLIP_SAMPLES = 32_000          # 2,000 s a 16 kHz = esattamente 16 finestre
SR = 16_000


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """Rumore rosa: spettro 1/f, molto piu' simile al rumore ambientale
    (ventole, traffico, brusio) del rumore bianco."""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    freqs[0] = freqs[1]
    spec /= np.sqrt(freqs)
    out = np.fft.irfft(spec, n)
    return (out / (np.abs(out).max() + 1e-9)).astype(np.float32)


def place_in_window(pcm: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Colloca il clip in una posizione casuale della finestra da 2 s.

    E' la trasformazione piu' importante: senza, il modello impara la
    posizione invece della parola.
    """
    out = np.zeros(CLIP_SAMPLES, dtype=np.float32)
    if pcm.size >= CLIP_SAMPLES:
        start = rng.integers(0, pcm.size - CLIP_SAMPLES + 1)
        return pcm[start : start + CLIP_SAMPLES].astype(np.float32)
    off = int(rng.integers(0, CLIP_SAMPLES - pcm.size + 1))
    out[off : off + pcm.size] = pcm
    return out


def augment(pcm: np.ndarray, rng: np.random.Generator, noises: list[np.ndarray]) -> np.ndarray:
    x = place_in_window(pcm, rng)

    # guadagno: la distanza dal microfono varia
    x *= float(rng.uniform(0.25, 1.4))

    # rumore additivo a SNR variabile. 30 dB = stanza silenziosa come quella
    # misurata in M0; 5 dB = condizioni difficili.
    if rng.random() < 0.8:
        snr_db = float(rng.uniform(5.0, 30.0))
        noise = noises[int(rng.integers(len(noises)))] if noises else pink_noise(CLIP_SAMPLES, rng)
        if noise.size < CLIP_SAMPLES:
            noise = np.pad(noise, (0, CLIP_SAMPLES - noise.size))
        start = int(rng.integers(0, max(1, noise.size - CLIP_SAMPLES + 1)))
        noise = noise[start : start + CLIP_SAMPLES]
        sp = float(np.mean(x**2)) + 1e-12
        npw = float(np.mean(noise**2)) + 1e-12
        x = x + noise * np.sqrt(sp / (npw * 10 ** (snr_db / 10)))

    # riverbero semplice: eco singola attenuata, approssima una stanza piccola
    if rng.random() < 0.3:
        delay = int(rng.uniform(0.01, 0.06) * SR)
        x[delay:] += x[:-delay] * float(rng.uniform(0.1, 0.35))

    peak = float(np.abs(x).max())
    if peak > 0.99:
        x = x / peak * 0.99
    return x.astype(np.float32)


def load_noises(folder: Path | None) -> list[np.ndarray]:
    """Rumore ambientale reale, se disponibile. Vale molto piu' del sintetico:
    cattura le ventole, la tastiera e l'acustica della stanza vera."""
    if folder is None or not folder.exists():
        return []
    out = []
    for f in sorted(folder.glob("*.wav")):
        a, sr = sf.read(f, dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        if sr == SR:
            out.append(a)
    return out


def process(kind: str, variants: int, seed: int, noise_dir: Path | None) -> None:
    src = DATA / kind
    files = sorted(src.glob("*.wav"))
    if not files:
        raise SystemExit(f"nessun wav in {src}")

    rng = np.random.default_rng(seed)
    noises = load_noises(noise_dir)
    print(f"{kind}: {len(files)} file x {variants} varianti"
          f"{f', {len(noises)} tracce di rumore reale' if noises else ', rumore sintetico'}")

    af = AudioFeatures()
    feats: list[np.ndarray] = []
    batch: list[np.ndarray] = []

    def flush() -> None:
        if not batch:
            return
        arr = (np.stack(batch) * 32767).astype(np.int16)
        feats.append(af.embed_clips(arr, batch_size=len(batch)))
        batch.clear()

    for i, f in enumerate(files):
        pcm, sr = sf.read(f, dtype="float32")
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1)
        assert sr == SR, f"{f} non e' a 16 kHz"
        for _ in range(variants):
            batch.append(augment(pcm, rng, noises))
            if len(batch) >= 128:
                flush()
        if (i + 1) % 1000 == 0:
            print(f"  {i + 1}/{len(files)}")
    flush()

    X = np.concatenate(feats).astype(np.float32)
    assert X.shape[1:] == (16, 96), f"forma inattesa: {X.shape}"
    out = DATA / f"features_{kind}.npy"
    np.save(out, X)
    print(f"  -> {out}  {X.shape}  {X.nbytes / 1024**2:.0f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["positive", "negative", "hard", "both"])
    ap.add_argument("--variants", type=int, default=3,
                    help="varianti augmentate per ogni file sorgente")
    ap.add_argument("--noise-dir", type=Path, default=DATA / "noise",
                    help="rumore ambientale reale, se disponibile")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    for k in (["positive", "negative"] if a.kind == "both" else [a.kind]):
        process(k, a.variants, a.seed, a.noise_dir)


if __name__ == "__main__":
    main()
