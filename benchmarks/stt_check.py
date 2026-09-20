"""M0 giorno 3 — catena cattura → VAD → STT su parlato reale.

Due obiettivi in un colpo solo:

1. Misurare la latenza REALE dello STT. Sul rumore sintetico Whisper esce
   subito perche' non trova voce, quindi quei numeri non valgono nulla.
2. Cominciare a raccogliere il corpus di riferimento per il WER. NFR-5 chiede
   50 frasi trascritte a mano: tanto vale partire adesso invece che in M7.

Ogni frase viene salvata come WAV accanto al testo di riferimento, cosi' il
corpus e' riutilizzabile senza ripetere la registrazione a ogni prova.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from metis.audio.capture import TARGET_SR, AudioCapture
from metis.audio.vad import SpeechSegmenter
from metis.stt.metrics import wer
from metis.stt.whisper_engine import WhisperEngine

CORPUS = Path("data/corpus")

# Frasi scelte per coprire i casi che contano: comandi del progetto, numeri,
# nomi propri inglesi dentro frasi italiane, domande, negazioni.
PHRASES = [
    "Hey Metis, inizia a lavorare.",
    "Sposta questa finestra sullo schermo a destra.",
    "Aprimi le news dei mercati.",
    "Ricordami di chiamare il commercialista domani alle diciassette.",
    "Quanta memoria video sta usando il sistema adesso?",
    "Apri Visual Studio Code e GitHub Desktop.",
    "Cerca le ultime novità sui tassi della Banca Centrale Europea.",
    "No, annulla, non intendevo quello.",
    "Accendi la friggitrice ad aria per venti minuti.",
    "Che temperatura ha raggiunto la scheda grafica?",
]


def main() -> None:
    model_size = sys.argv[1] if len(sys.argv) > 1 else "small"
    CORPUS.mkdir(parents=True, exist_ok=True)
    session = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Carico faster-whisper '{model_size}' su GPU...")
    eng = WhisperEngine(model_size)
    print(f"  warmup: {eng.warmup():.0f} ms\n")

    print("=" * 72)
    print("  Leggi ad alta voce ogni frase, poi FAI UNA PAUSA.")
    print("  Il VAD chiude da solo. Ctrl+C per interrompere.")
    print("=" * 72)

    rows = []
    idx = 0
    seg_er = SpeechSegmenter()

    try:
        with AudioCapture() as cap:
            print(f"\n[{idx + 1}/{len(PHRASES)}]  >> {PHRASES[idx]}")
            for b in cap.blocks(timeout=1.0):
                seg = seg_er.feed(b)
                if seg is None:
                    continue

                tr = eng.transcribe(seg.pcm)
                ref = PHRASES[idx]
                rate, err, nwords = wer(ref, tr.text)

                wav = CORPUS / f"{session}_{idx:02d}.wav"
                sf.write(wav, seg.pcm, TARGET_SR)

                # latenza percepita: dalla fine reale del parlato al testo
                total_ms = (time.perf_counter() - seg.t_speech_end) * 1000.0

                flag = "  <-- SOSPETTA" if tr.suspect else ""
                print(f"      trascritto: {tr.text}{flag}")
                print(
                    f"      WER {rate * 100:5.1f}%  ({err}/{nwords} parole) | "
                    f"STT {tr.latency_ms:5.0f} ms (RTF {tr.rtf:.3f}) | "
                    f"endpoint+STT {total_ms:5.0f} ms | audio {seg.duration_s:.2f} s"
                )

                rows.append(
                    {
                        "idx": idx,
                        "reference": ref,
                        "hypothesis": tr.text,
                        "wer": rate,
                        "errors": err,
                        "words": nwords,
                        "stt_ms": tr.latency_ms,
                        "rtf": tr.rtf,
                        "endpoint_ms": seg.endpoint_cost_ms,
                        "total_ms": total_ms,
                        "audio_s": seg.duration_s,
                        "avg_logprob": tr.avg_logprob,
                        "no_speech_prob": tr.no_speech_prob,
                        "suspect": tr.suspect,
                        "wav": wav.name,
                    }
                )

                idx += 1
                if idx >= len(PHRASES):
                    break
                print(f"\n[{idx + 1}/{len(PHRASES)}]  >> {PHRASES[idx]}")
    except KeyboardInterrupt:
        print("\ninterrotto")

    if not rows:
        return

    out = CORPUS / f"{session}_{model_size}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    tot_err = sum(r["errors"] for r in rows)
    tot_words = sum(r["words"] for r in rows)
    wer_glob = tot_err / tot_words if tot_words else 0.0
    stt = np.array([r["stt_ms"] for r in rows])

    print("\n" + "=" * 72)
    print(f"  RISULTATI  —  modello '{model_size}', {len(rows)} frasi")
    print("=" * 72)
    print(f"  WER globale        : {wer_glob * 100:5.1f} %   (target NFR-5 < 12%)")
    print(f"  errori totali      : {tot_err} su {tot_words} parole")
    print(f"  STT latenza media  : {stt.mean():5.0f} ms   (budget 150-350 ms)")
    print(f"  STT latenza p95    : {np.percentile(stt, 95):5.0f} ms")
    print(f"  RTF medio          : {np.mean([r['rtf'] for r in rows]):.3f}")
    print(f"  trascrizioni sospette: {sum(r['suspect'] for r in rows)}")
    print(f"\n  corpus salvato in  : {out}")

    peggiori = sorted(rows, key=lambda r: -r["wer"])[:3]
    if peggiori and peggiori[0]["wer"] > 0:
        print("\n  FRASI PEGGIORI")
        for r in peggiori:
            if r["wer"] == 0:
                continue
            print(f"    WER {r['wer'] * 100:5.1f}%")
            print(f"      atteso : {r['reference']}")
            print(f"      ottenuto: {r['hypothesis']}")


if __name__ == "__main__":
    main()
