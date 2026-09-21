"""Rivaluta una seduta registrata, offline, con qualunque modello e soglia.

PERCHE' ESISTE
La seduta NFR-7 costa due ore di altoparlanti accesi e una stanza che deve
restare vuota. Rifarla a ogni tentativo di riaddestramento sarebbe assurdo:
l'audio e' lo stesso, l'unica cosa che cambia e' il modello. Con l'audio
integrale salvato, ogni tentativo successivo costa sette minuti di CPU e
nessun rumore.

IL PUNTEGGIO SI CALCOLA UNA VOLTA SOLA
Le soglie si spazzolano DOPO, sulle serie di punteggi gia' calcolate: sono
migliaia di combinazioni al secondo invece di una passata di audio ciascuna.
Le serie finiscono in un .npy accanto al WAV, quindi la seconda spazzolata
sullo stesso modello e' istantanea.

DURANTE IL CALCOLO IL RILEVATORE NON DEVE SCATTARE
Si usa una soglia irraggiungibile: uno scatto chiamerebbe `reset()`, che
azzera il buffer interno e spezzerebbe la serie proprio nei punti piu'
interessanti. Le regole di conferma si applicano dopo, sui numeri.

    python wakeword/rescore_session.py wakeword/nfr7/<sess>/sessione.wav
    python wakeword/rescore_session.py <wav> --model data/wakeword/hey_metis_v3.onnx
    python wakeword/rescore_session.py <wav> --confronta data/wakeword/hey_metis.onnx
"""

from __future__ import annotations

import argparse
import time
import warnings
from dataclasses import replace
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from metis.audio.capture import TARGET_SR, VAD_BLOCK  # noqa: E402
from metis.audio.wakeword import (  # noqa: E402
    Confirmer,
    WakeWordConfig,
    WakeWordDetector,
)

SOGLIE = (0.90, 0.95, 0.97, 0.98, 0.99, 0.995, 0.999)
BLOCK_S = VAD_BLOCK / TARGET_SR


def serie(wav: Path, modello: Path, cache: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Punteggi delle due fasi, blocco per blocco. Ritorna (fase_a, fase_b)."""
    npy = wav.with_suffix(f".{modello.stem}.punteggi.npy")
    if cache and npy.exists():
        d = np.load(npy)
        print(f"  punteggi da cache: {npy.name}  {d.shape[1]:,} blocchi")
        return d[0], d[1]

    cfg = WakeWordConfig.load()
    # Soglia irraggiungibile: il rilevatore non deve scattare durante il
    # calcolo, altrimenti si azzera da solo e spezza la serie.
    det = WakeWordDetector(replace(cfg, model_path=modello, threshold=2.0))

    info = sf.info(wav)
    tot = info.frames // VAD_BLOCK
    print(f"  {wav.name}: {info.duration / 60:.1f} min, {tot:,} blocchi da valutare")

    a, b = np.empty(tot, np.float32), np.empty(tot, np.float32)
    t0 = time.perf_counter()
    i = 0
    with sf.SoundFile(wav) as f:
        while i < tot:
            blocco = f.read(VAD_BLOCK, dtype="float32", always_2d=False)
            if blocco.size < VAD_BLOCK:
                break
            if blocco.ndim > 1:
                blocco = blocco.mean(axis=1)
            det.feed(blocco.astype(np.float32))
            a[i], b[i] = det.last_score_a, det.last_score_b
            i += 1
            if i % 20000 == 0:
                fatto = i / tot
                resta = (time.perf_counter() - t0) * (1 - fatto) / max(fatto, 1e-9)
                print(f"    {fatto:5.1%}   restano ~{resta / 60:.1f} min")
    a, b = a[:i], b[:i]
    print(f"  calcolati in {(time.perf_counter() - t0) / 60:.1f} min")
    if cache:
        np.save(npy, np.stack([a, b]))
    return a, b


def scatti(punteggi: np.ndarray, soglia: float, consecutive: int,
           refractory_s: float) -> list[float]:
    """Istanti in cui la regola di conferma avrebbe fatto scattare.

    Usa la `Confirmer` del prodotto, non una sua copia: una copia che diverge
    farebbe misurare una regola diversa da quella che gira davvero.
    """
    c = Confirmer(soglia, consecutive, refractory_s)
    return [i * BLOCK_S for i, s in enumerate(punteggi) if c.feed(float(s), i * BLOCK_S)]


def tabella(a: np.ndarray, b: np.ndarray, cfg: WakeWordConfig, ore: float) -> None:
    d = np.minimum(a, b)
    print(f"\n  {'soglia':>7} {'fase singola':>14} {'doppia fase':>14}   (scatti, e /8h)")
    for thr in SOGLIE:
        ns = len(scatti(a, thr, cfg.consecutive, cfg.refractory_s))
        nd = len(scatti(d, thr, cfg.consecutive, cfg.refractory_s))
        marca = "  <-- soglia attuale" if abs(thr - cfg.threshold) < 1e-9 else ""
        print(f"  {thr:>7.3f} {ns:>6}  ({ns / ore * 8:>5.1f}) {nd:>6}  ({nd / ore * 8:>5.1f})"
              f"{marca}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path, help="sessione.wav salvata da un banco")
    ap.add_argument("--model", type=Path, default=None,
                    help="modello da valutare (default: quello in configurazione)")
    ap.add_argument("--confronta", type=Path, default=None,
                    help="secondo modello, sulla STESSA audio")
    ap.add_argument("--no-cache", dest="cache", action="store_false")
    args = ap.parse_args()

    cfg = WakeWordConfig.load()
    modello = args.model or cfg.model_path
    if not args.wav.exists():
        raise SystemExit(f"manca {args.wav}")

    print("=" * 68)
    print("  RIVALUTAZIONE OFFLINE — stessa audio, modelli e soglie diversi")
    print("=" * 68)

    ore = sf.info(args.wav).duration / 3600.0
    a, b = serie(args.wav, modello, args.cache)
    print(f"\n  MODELLO: {modello.name}")
    print(f"  punteggi  p50 {np.percentile(a, 50):.4f}   p99 {np.percentile(a, 99):.4f}"
          f"   p99.99 {np.percentile(a, 99.99):.4f}   max {a.max():.4f}")
    tabella(a, b, cfg, ore)

    if args.confronta:
        a2, b2 = serie(args.wav, args.confronta, args.cache)
        print(f"\n  MODELLO: {args.confronta.name}")
        print(f"  punteggi  p50 {np.percentile(a2, 50):.4f}   p99 {np.percentile(a2, 99):.4f}"
              f"   p99.99 {np.percentile(a2, 99.99):.4f}   max {a2.max():.4f}")
        tabella(a2, b2, cfg, ore)

        s1 = len(scatti(a, cfg.threshold, cfg.consecutive, cfg.refractory_s))
        s2 = len(scatti(a2, cfg.threshold, cfg.consecutive, cfg.refractory_s))
        print(f"\n  A soglia {cfg.threshold}: {modello.name} {s1} scatti, "
              f"{args.confronta.name} {s2} scatti "
              f"({(s2 - s1) / max(s1, 1) * 100:+.0f}%)")

    print("\n  Questo dice solo quanti FALSI scatti evita. Un modello che non")
    print("  scatta mai ha zero falsi ed e' inutile: i mancati riconoscimenti")
    print("  si misurano a parte, su wakeword/live/*_pos_*.wav.")


if __name__ == "__main__":
    main()
