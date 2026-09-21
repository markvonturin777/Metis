"""Registra la stanza vera e, sulla stessa registrazione, misura NFR-6.

DUE LAVORI CON UNA SOLA SEDUTA
  1. RUMORE PER L'ADDESTRAMENTO. Il modello attuale e' addestrato su rumore
     sintetico: rumore rosa ed eco finta. Le ventole di questo PC, la tastiera
     meccanica e l'acustica di questa stanza valgono molto di piu', e vanno in
     `wakeword/data/noise/`, dove `extract_features.py` li cerca da solo.
  2. NFR-6, cioe' meno di un falso risveglio ogni 8 ore. Sulla stessa audio si
     fa girare il rilevatore vero, con la configurazione vera.

PERCHE' LA MISURA VA FATTA COSI' E NON SUI DATI SINTETICI
Sul set di validazione il modello ha uno 0% di falsi positivi su 4800 clip
negativi, e non significa nulla per NFR-6: in esecuzione il rilevatore valuta
un blocco ogni 32 ms, cioe' 900.000 volte in 8 ore. Servirebbe un FPR sotto lo
0,00011%, mentre 4800 campioni risolvono al minimo lo 0,021%. Due ordini di
grandezza di distanza. L'unico modo di sapere quanti falsi risvegli ci sono e'
**lasciarlo acceso e contarli**.

COSA VIENE SALVATO
  * qualche minuto di rumore ambientale, per il riaddestramento;
  * quattro secondi di audio intorno a OGNI picco sospetto, anche sotto la
    soglia di scatto. Sono i negativi duri migliori che esistano: vengono
    dalla stanza vera, non da un generatore.

PRIVACY
Registra il microfono. Se in stanza c'e' altra gente, o si e' in chiamata,
questo banco non si lancia.

    python wakeword/record_ambient.py --minutes 30
    python wakeword/record_ambient.py --minutes 480 --noise-minutes 0   # NFR-6
"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from collections import deque
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from metis.audio.capture import TARGET_SR, VAD_BLOCK, AudioCapture  # noqa: E402
from metis.audio.wakeword import Confirmer, WakeWordConfig, WakeWordDetector  # noqa: E402

NOISE_DIR = Path("wakeword/data/noise")
AMBIENT_DIR = Path("wakeword/ambient")

BLOCK_S = VAD_BLOCK / TARGET_SR          # 0,032 s
CONTESTO_S = 3.0                         # audio da tenere PRIMA di un picco
CODA_S = 1.5                             # e dopo
NOISE_CHUNK_S = 60.0                     # lunghezza di ogni file di rumore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--noise-minutes", type=float, default=10.0,
                    help="quanti minuti di rumore tenere per l'addestramento")
    ap.add_argument("--peak", type=float, default=0.5,
                    help="punteggio oltre il quale si salva il contesto")
    ap.add_argument("--full-audio", action="store_true",
                    help="salva l'audio integrale: rende la seduta rivalutabile "
                         "offline con qualunque modello futuro (~115 MB/ora)")
    args = ap.parse_args()

    sess = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = AMBIENT_DIR / sess
    out.mkdir(parents=True, exist_ok=True)
    NOISE_DIR.mkdir(parents=True, exist_ok=True)

    cfg = WakeWordConfig.load()
    det = WakeWordDetector(cfg)
    for _ in range(8):
        det.feed(np.zeros(VAD_BLOCK, dtype=np.float32))
    det.reset()
    det.scores.clear()

    durata_s = args.minutes * 60
    quota_rumore = args.noise_minutes * 60
    # I file di rumore si distribuiscono lungo tutta la seduta: dieci minuti
    # presi tutti all'inizio raccontano un momento solo, non la giornata.
    n_chunk = max(1, int(quota_rumore / NOISE_CHUNK_S)) if quota_rumore else 0
    passo_rumore = durata_s / n_chunk if n_chunk else 0.0

    print("=" * 66)
    print(f"  AMBIENTE + NFR-6 — {args.minutes:.0f} minuti")
    print("=" * 66)
    print(f"  modello  : {cfg.model_path.name}   soglia {cfg.threshold} "
          f"x{cfg.consecutive} blocchi")
    print(f"  rumore   : {n_chunk} file da {NOISE_CHUNK_S:.0f} s -> {NOISE_DIR}")
    print(f"  picchi   : sopra {args.peak} salva {CONTESTO_S + CODA_S:.1f} s -> {out}")
    print("\n  Vivi la giornata normalmente: lavora, ascolta musica, parla al")
    print("  telefono. Se la stanza resta in silenzio, la prova non misura nulla.")
    print("  Ctrl+C per chiudere prima.\n")

    contesto: deque[np.ndarray] = deque(maxlen=int(CONTESTO_S / BLOCK_S))
    coda_blocchi = int(CODA_S / BLOCK_S)

    punteggi: list[float] = []
    punteggi_dual: list[float] = []
    livelli: list[float] = []
    eventi: list[dict] = []
    risvegli = 0
    # Confronto appaiato: sulla STESSA audio si conta anche cosa avrebbe
    # fatto la regola a doppia fase. Otto ore sono troppo care per ripeterle
    # una volta per regola, e due sedute diverse non sarebbero confrontabili.
    conf_dual = Confirmer(cfg.threshold, cfg.consecutive, cfg.refractory_s)
    risvegli_dual = 0

    in_cattura: list[np.ndarray] | None = None
    cattura_resta = 0
    cattura_info: dict = {}

    rumore: list[np.ndarray] | None = None
    prossimo_rumore = 0.0
    n_rumore = 0

    # Con l'audio integrale la seduta si rivaluta offline quante volte si
    # vuole: otto ore costano ~920 MB e non si ripetono piu'.
    sessione_wav = None
    if args.full_audio:
        sessione_wav = sf.SoundFile(out / "sessione.wav", "w", samplerate=TARGET_SR,
                                    channels=1, subtype="PCM_16")
        print(f"  audio integrale -> {out / 'sessione.wav'}  "
              f"(~{durata_s * TARGET_SR * 2 / 1024**3:.1f} GB)")

    t0 = time.perf_counter()
    ultimo_stampa = 0.0
    cap = AudioCapture()

    try:
        with cap:
            while True:
                b = cap.read(timeout=0.5)
                ora = time.perf_counter()
                trascorso = ora - t0
                if trascorso > durata_s:
                    break
                if b is None:
                    continue

                scattato = det.feed(b.pcm)
                s = det.last_score
                s_dual = min(det.last_score_a, det.last_score_b)
                if conf_dual.feed(s_dual, ora):
                    risvegli_dual += 1
                punteggi.append(s)
                punteggi_dual.append(s_dual)
                livelli.append(b.rms_dbfs)
                contesto.append(b.pcm)
                if sessione_wav is not None:
                    sessione_wav.write(b.pcm)

                # --- picco sospetto: si salva il contesto ------------------
                if in_cattura is None and (s >= args.peak or scattato):
                    in_cattura = list(contesto)
                    cattura_resta = coda_blocchi
                    cattura_info = {"t_s": round(trascorso, 1), "picco": float(s),
                                    "risveglio": bool(scattato)}
                elif in_cattura is not None:
                    in_cattura.append(b.pcm)
                    cattura_info["picco"] = max(cattura_info["picco"], float(s))
                    cattura_info["risveglio"] = cattura_info["risveglio"] or bool(scattato)
                    cattura_resta -= 1
                    if cattura_resta <= 0:
                        nome = (f"{'RISVEGLIO' if cattura_info['risveglio'] else 'picco'}"
                                f"_{cattura_info['t_s']:07.1f}s_{cattura_info['picco']:.3f}.wav")
                        sf.write(out / nome, np.concatenate(in_cattura), TARGET_SR)
                        cattura_info["wav"] = nome
                        eventi.append(cattura_info)
                        in_cattura, cattura_info = None, {}

                if scattato:
                    risvegli += 1
                    print(f"\n  !! FALSO RISVEGLIO a {trascorso / 60:.1f} min "
                          f"(punteggio {s:.3f})")

                # --- campione di rumore per l'addestramento ----------------
                if n_chunk and rumore is None and trascorso >= prossimo_rumore:
                    rumore = []
                elif rumore is not None:
                    rumore.append(b.pcm)
                    if len(rumore) * BLOCK_S >= NOISE_CHUNK_S:
                        f = NOISE_DIR / f"{sess}_{n_rumore:02d}.wav"
                        sf.write(f, np.concatenate(rumore), TARGET_SR)
                        n_rumore += 1
                        rumore = None
                        prossimo_rumore = trascorso + passo_rumore
                        if n_rumore >= n_chunk:
                            prossimo_rumore = float("inf")

                if ora - ultimo_stampa > 1.0:
                    resta = (durata_s - trascorso) / 60
                    print(f"\r  {trascorso / 60:6.1f} min   restano {resta:5.1f}   "
                          f"picco max {max(punteggi):.3f}   risvegli {risvegli}   "
                          f"rumore {n_rumore}/{n_chunk}   livello {b.rms_dbfs:6.1f} dBFS",
                          end="")
                    ultimo_stampa = ora
    except KeyboardInterrupt:
        print("\n  interrotto")
    finally:
        if sessione_wav is not None:
            sessione_wav.close()

    # --- esito ----------------------------------------------------------
    ore = (time.perf_counter() - t0) / 3600.0
    s = np.array(punteggi) if punteggi else np.zeros(1)
    sd = np.array(punteggi_dual) if punteggi_dual else np.zeros(1)
    liv = np.array(livelli) if livelli else np.zeros(1)

    report = {
        "sessione": sess,
        "ore": round(ore, 3),
        "blocchi": len(punteggi),
        "soglia": cfg.threshold,
        "consecutive": cfg.consecutive,
        "risvegli": risvegli,
        "risvegli_per_8h": round(risvegli / ore * 8, 2) if ore > 0 else None,
        "risvegli_doppia_fase": risvegli_dual,
        "dual_p9999": float(np.percentile(sd, 99.99)),
        "dual_max": float(sd.max()),
        "punteggio_p50": float(np.percentile(s, 50)),
        "punteggio_p99": float(np.percentile(s, 99)),
        "punteggio_p9999": float(np.percentile(s, 99.99)),
        "punteggio_max": float(s.max()),
        "livello_medio_dbfs": float(liv.mean()),
        "eventi": eventi,
        "file_rumore": n_rumore,
    }
    (AMBIENT_DIR / f"{sess}.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    print("\n\n" + "=" * 66)
    print(f"  RISULTATO — {ore * 60:.1f} minuti, {len(punteggi):,} blocchi valutati")
    print("=" * 66)
    print(f"  falsi risvegli      : {risvegli}        regola attuale (fase singola)")
    print(f"                        {risvegli_dual}        regola a doppia fase")
    if ore > 0:
        print(f"  proiettati su 8 h   : {risvegli / ore * 8:.2f}      (NFR-6 chiede < 1)")
    print(f"  punteggi   p50 {report['punteggio_p50']:.4f}   p99 {report['punteggio_p99']:.4f}"
          f"   p99.99 {report['punteggio_p9999']:.4f}   max {report['punteggio_max']:.4f}")
    print(f"  livello medio       : {report['livello_medio_dbfs']:.1f} dBFS")
    print(f"  picchi salvati      : {len(eventi)}   -> {out}")
    print(f"  file di rumore      : {n_rumore}   -> {NOISE_DIR}")

    if ore < 1.0:
        print("\n  Seduta breve: la proiezione su 8 ore ha un'incertezza enorme.")
        print("  Con meno di un'ora si guardano i picchi, non il tasso.")

    print("\n  SOGLIE ALTERNATIVE (quanti blocchi le avrebbero superate)")
    print(f"  {'soglia':>6}  {'fase singola':>14}  {'doppia fase':>13}")
    for thr in (0.5, 0.7, 0.85, 0.9, 0.95, 0.99):
        marca = "  <-- attuale" if abs(thr - cfg.threshold) < 1e-6 else ""
        print(f"  {thr:>6.2f}  {int((s >= thr).sum()):>14}  "
              f"{int((sd >= thr).sum()):>13}{marca}")
    print("\n  Nota: i blocchi sopra soglia NON sono risvegli — ne servono"
          f" {cfg.consecutive} di fila.")
    print("\n  Se ci sono picchi alti, i WAV salvati sono negativi duri pronti:")
    print("    copiali in wakeword/data/hard/ e rilancia extract_features.py hard")


if __name__ == "__main__":
    main()
