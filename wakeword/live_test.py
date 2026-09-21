"""Prova dal vivo della wake word: funziona con la TUA voce?

Il modello e' addestrato su voci sintetiche. Che riconosca l'utente reale e'
un'ipotesi, non un risultato: questo script la verifica.

Due fasi:

  1. RILEVAMENTO — N tentativi guidati di "Hey Metis". Per ognuno si registra
     il punteggio di picco. Il tasso di mancati riconoscimenti e' il criterio
     di uscita D1 (< 10%).

  2. FALSI RISVEGLI — parlato normale che NON contiene la wake word, incluse
     le parole trabocchetto italiane. Ogni picco alto qui e' un falso positivo
     in attesa di accadere.

Tutto l'audio viene salvato: le soglie si possono rivalutare offline, senza
rifare le registrazioni. E' la stessa disciplina del corpus STT di M0, che ha
permesso di correggere due volte la metrica senza ripetere le prove.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from metis.audio.capture import TARGET_SR, AudioCapture  # noqa: E402
from metis.audio.wakeword import WakeWordConfig, WakeWordDetector  # noqa: E402

OUT = Path("wakeword/live")

TRABOCCHETTI = [
    "Metti via quel libro, per favore.",
    "Mettiamoci al lavoro che e' tardi.",
    "Mattia ha telefonato stamattina.",
    "Ehi, mi senti? Ti sento male.",
    "Smettila di mettere tutto in disordine.",
    "La mattina presto metto su il caffe'.",
    "Hey, guarda qui che roba.",
    "Ammettiamo che sia vero, e allora?",
]


def ascolta(det: WakeWordDetector, cap: AudioCapture, secondi: float,
            etichetta: str) -> tuple[float, np.ndarray, bool]:
    """Ascolta per N secondi. Ritorna (picco, audio, ha_scattato)."""
    blocchi, punteggi = [], []
    scattato = False
    t_end = time.time() + secondi
    ultimo = 0.0
    for b in cap.blocks(timeout=1.0):
        blocchi.append(b.pcm)
        if det.feed(b.pcm):
            scattato = True
        punteggi.append(det.last_score)
        if time.time() - ultimo > 0.15:
            barra = "#" * int(det.last_score * 30)
            print(f"\r  {etichetta} [{barra:<30}] {det.last_score:.3f}", end="")
            ultimo = time.time()
        if time.time() > t_end:
            break
    print()
    audio = np.concatenate(blocchi) if blocchi else np.zeros(0, np.float32)
    return float(max(punteggi)) if punteggi else 0.0, audio, scattato


def main() -> None:
    n_tentativi = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    OUT.mkdir(parents=True, exist_ok=True)
    sess = datetime.now().strftime("%Y%m%d_%H%M%S")

    cfg = WakeWordConfig.load()
    det = WakeWordDetector(cfg)
    print(f"modello: {cfg.model_path}")
    print(f"soglia {cfg.threshold} | {cfg.consecutive} blocchi consecutivi | "
          f"refrattario {cfg.refractory_s}s\n")

    righe = []

    with AudioCapture() as cap:
        # --- fase 1: rilevamento ---------------------------------------
        print("=" * 66)
        print(f"  FASE 1 — di' \"Hey Metis\" {n_tentativi} volte")
        print("  Varia distanza, volume e velocita': e' l'uso reale.")
        print("=" * 66)
        input("\n  INVIO per cominciare...")

        for i in range(n_tentativi):
            det.reset()
            det._last_fire = 0.0          # niente refrattario fra i tentativi
            time.sleep(0.4)
            print(f"\n  [{i + 1}/{n_tentativi}] di' ora:")
            picco, audio, scattato = ascolta(det, cap, 2.6, f"{i + 1:2d}")
            esito = "RILEVATA" if scattato else "MANCATA  <--"
            print(f"      picco {picco:.3f}   {esito}")
            wav = OUT / f"{sess}_pos_{i:02d}.wav"
            sf.write(wav, audio, TARGET_SR)
            righe.append({"fase": "positivo", "idx": i, "picco": float(picco),
                          "scattato": bool(scattato), "wav": wav.name})

        # --- fase 2: trabocchetti --------------------------------------
        print("\n" + "=" * 66)
        print("  FASE 2 — frasi che NON devono svegliare Metis")
        print("  Leggile normalmente, come le diresti davvero.")
        print("=" * 66)
        input("\n  INVIO per cominciare...")

        for i, frase in enumerate(TRABOCCHETTI):
            det.reset()
            det._last_fire = 0.0
            time.sleep(0.3)
            print(f"\n  [{i + 1}/{len(TRABOCCHETTI)}] leggi: \"{frase}\"")
            picco, audio, scattato = ascolta(det, cap, 3.4, f"{i + 1:2d}")
            esito = "FALSO RISVEGLIO  <--" if scattato else "ok"
            print(f"      picco {picco:.3f}   {esito}")
            wav = OUT / f"{sess}_neg_{i:02d}.wav"
            sf.write(wav, audio, TARGET_SR)
            righe.append({"fase": "trabocchetto", "idx": i, "frase": frase,
                          "picco": float(picco), "scattato": bool(scattato), "wav": wav.name})

    # --- risultati ------------------------------------------------------
    (OUT / f"{sess}.json").write_text(
        json.dumps(righe, indent=1, ensure_ascii=False), encoding="utf-8"
    )

    pos = [r for r in righe if r["fase"] == "positivo"]
    neg = [r for r in righe if r["fase"] == "trabocchetto"]
    mancati = sum(not r["scattato"] for r in pos)
    falsi = sum(r["scattato"] for r in neg)

    print("\n" + "=" * 66)
    print("  RISULTATI")
    print("=" * 66)
    print(f"  rilevamenti : {len(pos) - mancati}/{len(pos)}  "
          f"mancati {mancati / len(pos) * 100:.0f}%   (D1 chiede < 10%)")
    print(f"  falsi       : {falsi}/{len(neg)} sulle frasi trabocchetto")
    print(f"  picchi positivi     : min {min(r['picco'] for r in pos):.3f}  "
          f"mediana {np.median([r['picco'] for r in pos]):.3f}")
    print(f"  picchi trabocchetti : max {max(r['picco'] for r in neg):.3f}")

    print("\n  SOGLIE ALTERNATIVE (rivalutate sui picchi registrati)")
    print(f"  {'soglia':>7} {'rilevati':>10} {'falsi':>8}")
    for thr in (0.3, 0.5, 0.7, 0.85, 0.95, 0.99):
        r = sum(x["picco"] >= thr for x in pos) / len(pos)
        f = sum(x["picco"] >= thr for x in neg)
        marca = "  <-- attuale" if abs(thr - WakeWordConfig.load().threshold) < 1e-6 else ""
        print(f"  {thr:>7.2f} {r * 100:>9.0f}% {f:>8}{marca}")

    margine = min(r["picco"] for r in pos) - max(r["picco"] for r in neg)
    print(f"\n  margine di separazione: {margine:+.3f}")
    if margine > 0.3:
        print("  Ampio: la soglia si puo' scegliere con comodita'.")
    elif margine > 0:
        print("  Stretto: positivi e trabocchetti quasi si toccano.")
    else:
        print("  NEGATIVO: si sovrappongono. Servono altri dati di training.")
    print(f"\n  audio in {OUT.resolve()}")


if __name__ == "__main__":
    main()
