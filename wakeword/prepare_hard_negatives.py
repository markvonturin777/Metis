"""Dai falsi risvegli registrati ai negativi duri per il riaddestramento.

DA DOVE VENGONO
La seduta NFR-7 del 21 settembre ha prodotto 57 auto-inneschi e un centinaio
di quasi-scatti, tutti catturati con 3 s di contesto e 1,5 s di coda. Sono
registrazioni REALI del modo esatto in cui il modello sbaglia, prese dal
microfono vero nella stanza vera. I negativi duri sintetici provati il giorno
prima avevano peggiorato il margine (da +0,184 a +0,122): questi sono l'altra
cosa, ed e' l'unico modo per ottenerli.

DUE ACCORTEZZE, ENTRAMBE NECESSARIE

1. LA FINESTRA VA RITAGLIATA A MANO. `extract_features.place_in_window`
   prende una fetta casuale da 2 s dalle clip piu' lunghe: su una clip da
   4,5 s mancherebbe spesso l'istante dello scatto, e addestreremmo il
   modello sul silenzio intorno all'errore invece che sull'errore. Lo scatto
   sta a CONTESTO_S dall'inizio, quindi la finestra da 2 s che il rilevatore
   aveva davvero in pancia e' [CONTESTO_S - 2, CONTESTO_S].

2. IL JITTER DI POCHI MILLISECONDI E' IL PUNTO, NON UN DETTAGLIO. Il
   punteggio dipende da dove cadono i confini dei blocchi rispetto alla
   griglia del melspettrogramma: la stessa audio spostata di 4 ms passa da
   0,016 a 0,969. Generare varianti sfasate insegna al modello a rifiutare
   questi suoni a TUTTI gli allineamenti, non solo a quello fortunato con cui
   sono stati registrati.

SICUREZZA: NON ADDESTRARE CONTRO SE STESSI
Se una clip contenesse un "Hey Metis" pronunciato davvero, usarla come
negativo insegnerebbe al modello a ignorare la wake word. Ogni clip viene
quindi trascritta e scartata se contiene qualcosa che somiglia alla frase.

    python wakeword/prepare_hard_negatives.py
    python wakeword/prepare_hard_negatives.py --jitter 12 --no-stt
"""

from __future__ import annotations

import argparse
import glob
import re
import shutil
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

SR = 16_000
FINESTRA = 2.0          # la finestra del modello
CONTESTO_S = 3.0        # quanto contesto salvano i banchi PRIMA dello scatto
DEST = Path("wakeword/data/hard")
ARCHIVIO = Path("wakeword/data/hard_sintetici_scartati")

# Somiglia alla wake word? Whisper scrive "Metis", "Mettis", "Met is"...
_SOSPETTO = re.compile(r"\b(hey|ehi|hei)\s*,?\s*met", re.IGNORECASE)


def sorgenti() -> list[Path]:
    """Clip dei banchi: auto-inneschi e quasi-scatti, fase A e ambiente.

    La fase B e' esclusa di proposito: li' Metis pronuncia il proprio nome e
    uno scatto non e' un errore, e' il rilevatore che funziona.
    """
    out: list[Path] = []
    for pat in ("wakeword/nfr7/*/A_*.wav", "wakeword/ambient/*/*.wav"):
        out += [Path(f) for f in sorted(glob.glob(pat))]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jitter", type=int, default=8,
                    help="varianti sfasate per clip")
    ap.add_argument("--spread-ms", type=float, default=120.0,
                    help="ampiezza dello sfasamento, in millisecondi")
    ap.add_argument("--no-stt", dest="stt", action="store_false",
                    help="salta il controllo di sicurezza sulla wake word")
    args = ap.parse_args()

    files = sorgenti()
    if not files:
        raise SystemExit("nessuna clip: lancia prima nfr7_test.py o record_ambient.py")

    print("=" * 66)
    print(f"  NEGATIVI DURI REALI — {len(files)} clip sorgente")
    print("=" * 66)

    # I duri sintetici del v2 avevano PEGGIORATO il margine: vanno tolti di
    # mezzo, non mescolati ai reali, altrimenti non si capisce piu' cosa ha
    # funzionato.
    if DEST.exists() and any(DEST.glob("*.wav")):
        ARCHIVIO.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in DEST.glob("*.wav"):
            shutil.move(str(f), ARCHIVIO / f.name)
            n += 1
        print(f"  archiviati {n} duri sintetici in {ARCHIVIO}")
    DEST.mkdir(parents=True, exist_ok=True)

    stt = None
    if args.stt:
        from metis.stt.whisper_engine import WhisperEngine
        stt = WhisperEngine("small")
        print("  controllo di sicurezza: Whisper su ogni clip")

    n_win = int(FINESTRA * SR)
    rng = np.random.default_rng(11)
    spread = int(args.spread_ms / 1000 * SR)

    scritti = scartati = corti = 0
    for f in files:
        a, sr = sf.read(f, dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        a = a.astype(np.float32)
        if sr != SR or a.size < n_win:
            corti += 1
            continue

        if stt is not None:
            testo = stt.transcribe(a).text
            if _SOSPETTO.search(testo):
                print(f"  SCARTATA {f.name}: sembra contenere la wake word "
                      f"-> {testo.strip()[:60]!r}")
                scartati += 1
                continue

        # La finestra che il rilevatore aveva davvero in pancia allo scatto.
        centro = int(CONTESTO_S * SR)
        for k in range(args.jitter):
            delta = int(rng.integers(-spread, spread + 1))
            fine = np.clip(centro + delta, n_win, a.size)
            taglio = a[fine - n_win : fine]
            if taglio.size != n_win:
                continue
            sf.write(DEST / f"{f.stem}_j{k:02d}.wav", taglio, SR)
            scritti += 1

    print(f"\n  scritti  {scritti} file da {FINESTRA:.0f} s in {DEST}")
    print(f"  scartati {scartati} (somigliano alla wake word)"
          + (f", {corti} troppo corti" if corti else ""))
    print("\n  Passo successivo:")
    print("    .venv-train/Scripts/python.exe wakeword/extract_features.py hard --variants 3")
    print("    .venv-train/Scripts/python.exe wakeword/train_model.py")


if __name__ == "__main__":
    main()
