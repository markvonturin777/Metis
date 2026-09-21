"""Genera i campioni sintetici per addestrare la wake word "Hey Metis".

IL PROBLEMA DELLA VARIETA'
Le due voci italiane di Piper sono a parlante singolo: un modello addestrato
solo su quelle riconoscerebbe due timbri e nient'altro. Il modello inglese
`en_US-libritts_r-medium` ne ha **904**, ed e' la fonte di varieta' che serve.

IL PROBLEMA DELLA PRONUNCIA
Un parlante inglese dice "Metis" come /ˈmiːtɪs/, un italiano come /ˈmɛtis/.
Addestrare solo sull'inglese produrrebbe un modello sordo a come l'utente
parla davvero. Si usano quindi:

  * le voci italiane, poche ma con la pronuncia giusta;
  * le 904 inglesi con **grafie alternative** che spingono verso il suono
    italiano ("Mettis", "Mehtis"), per la varieta' di timbro;
  * in seguito, registrazioni reali dell'utente col suo microfono.

La diversita' di pronuncia nel set non e' un difetto: rende il modello
robusto a come la frase viene detta nelle diverse situazioni.

I NEGATIVI MIRATI SONO LA PARTE CHE DECIDE
In italiano "metti", "mettiamo", "Mattia" sono parole comunissime e
foneticamente vicine. Senza di loro nei negativi, Metis si sveglia ogni volta
che dici "metti via". Indizio da M0: Whisper, che ha 244M parametri,
trascriveva "Metis" come "Mattis".
"""

from __future__ import annotations

import argparse
import io
import json
import random
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from piper import PiperVoice, SynthesisConfig

OUT = Path("wakeword/data")
VOICES = Path("data/piper")
TARGET_SR = 16_000          # richiesto da openWakeWord

MULTI = "en_US-libritts_r-medium"
ITALIAN = ["it_IT-paola-medium", "it_IT-riccardo-x_low"]

# Grafie che spingono la pronuncia inglese verso il suono italiano.
#
# SCELTA ALL'ASCOLTO (2026-09-21): fra cinque candidate confrontate con le voci
# italiane di riferimento, "Hey Met-iss" e' risultata la piu' vicina a come
# l'utente pronuncia davvero la parola. Viene quindi pesata al 50%.
#
# Le altre restano nel set, con peso minore: un modello addestrato su una sola
# pronuncia e' fragile: basta un raffreddore o una frase detta di fretta.
POSITIVE_EN = (
    ["Hey Met-iss"] * 10      # la piu' vicina all'italiano
    + ["Hey Mettis"] * 4
    + ["Hey Mehtis"] * 3
    + ["Hey Metis"] * 2
    + ["Hey Metiss"] * 1
)
POSITIVE_IT = ["Hey Metis", "Ehi Metis", "Hey Metis.", "Ehi, Metis"]

# --- NEGATIVI MIRATI ---------------------------------------------------------
# Parole italiane comuni foneticamente vicine. Senza queste il modello e'
# inutilizzabile nell'uso quotidiano.
NEGATIVE_IT = [
    "metti", "mettiamo", "metterlo", "mettila", "mettiamoci", "metti via",
    "metti su", "rimetti", "ammettiamo", "permettimi", "smettila",
    "Mattia", "mattina", "matita", "meta", "mete", "medici",
    "ehi", "ehi tu", "hey", "hey ciao", "ok", "adesso",
    "amnesie", "mimetismo", "metrica", "metro", "mettere",
    # frasi intere: il contesto conta piu' della parola isolata
    "metti via quel libro", "mettiamo che sia vero", "smettila per favore",
    "Mattia ha telefonato", "la mattina presto", "mettiamoci al lavoro",
    "ehi, mi senti", "hey, guarda qui", "metti la musica",
]
# --- NEGATIVI DURI -----------------------------------------------------------
# Aggiunti il 2026-09-21 dopo la prova dal vivo: "Ehi, mi senti? Ti sento male"
# ha prodotto un punteggio di 0,986, indistinguibile da una wake word vera.
#
# Foneticamente si capisce perche':
#     "Hey Metis"     /'ei 'mEtis/
#     "Ehi mi senti"  /'ei mi 'sEnti/
# Condividono l'attacco /ei/ + /m/ e uno scheletro consonantico simile.
#
# La frase ERA gia' nei negativi sintetici. Non e' bastata: il TTS la pronuncia
# diversamente da come la dice l'utente. Serve saturare l'intera famiglia
# fonetica, non la singola frase.
NEGATIVE_HARD_IT = [
    "ehi mi senti", "ehi, mi senti?", "ehi mi senti bene",
    "mi senti", "mi senti adesso", "non mi senti",
    "ehi senti", "ehi, senti una cosa", "ehi ma senti",
    "ehi mi sente", "ehi ci senti", "ehi mi dici",
    "ehi mi metti", "ehi mettici", "ehi me lo dici",
    "ehi Matteo", "ehi Mattia", "ehi mamma",
    "ehi mi serve", "ehi mi segui", "ehi mi sembra",
    "ti sento male", "non ti sento", "mi sentite",
    "hey mi senti", "hey senti", "hey mettici",
    "ehi, mi senti? ti sento male",
]

NEGATIVE_EN = [
    "hey there", "hey you", "hey Chris", "hey Betty", "hey medics",
    "metrics", "meters", "mattress", "Matthias", "notice", "melodies",
    "hey let us", "may this", "hey my dear", "metals",
]


def load_voice(name: str) -> PiperVoice:
    return PiperVoice.load(str(VOICES / f"{name}.onnx"))


def synth(voice: PiperVoice, text: str, cfg: SynthesisConfig) -> np.ndarray:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(text, w, cfg)
    buf.seek(0)
    with wave.open(buf, "rb") as w:
        raw = w.readframes(w.getnframes())
        sr = w.getframerate()
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if sr != TARGET_SR:
        pcm = soxr.resample(pcm, sr, TARGET_SR, quality="HQ")
    return pcm.astype(np.float32)


def pad(pcm: np.ndarray, rng: random.Random) -> np.ndarray:
    """Silenzio variabile davanti e dietro.

    Senza, il modello impara che la parola comincia sempre al campione zero,
    e in esecuzione — dove arriva in mezzo a un flusso continuo — sbaglia.
    """
    head = int(rng.uniform(0.05, 0.40) * TARGET_SR)
    tail = int(rng.uniform(0.10, 0.50) * TARGET_SR)
    return np.concatenate([np.zeros(head, np.float32), pcm, np.zeros(tail, np.float32)])


def generate(kind: str, n: int, seed: int) -> None:
    rng = random.Random(seed)
    out = OUT / kind
    out.mkdir(parents=True, exist_ok=True)

    multi = load_voice(MULTI)
    ital = [(name, load_voice(name)) for name in ITALIAN]

    if kind == "positive":
        texts_en, texts_it = POSITIVE_EN, POSITIVE_IT
        # Un terzo dai due timbri italiani: pronuncia corretta. Due terzi dai
        # 904 inglesi: varieta' di voce.
        frac_it = 0.34
    elif kind == "hard":
        # Solo voci italiane: la confusione nasce dalla pronuncia italiana.
        texts_en, texts_it = NEGATIVE_HARD_IT, NEGATIVE_HARD_IT
        frac_it = 1.0
    else:
        texts_en, texts_it = NEGATIVE_EN, NEGATIVE_IT
        frac_it = 0.70          # i negativi che contano sono quelli italiani

    manifest = []
    for i in range(n):
        use_it = rng.random() < frac_it
        cfg = SynthesisConfig(
            speaker_id=None if use_it else rng.randrange(904),
            length_scale=rng.uniform(0.80, 1.25),      # velocita'
            noise_scale=rng.uniform(0.50, 0.85),       # variazione timbrica
            noise_w_scale=rng.uniform(0.60, 1.00),     # variazione di durata
        )
        if use_it:
            name, voice = rng.choice(ital)
            text = rng.choice(texts_it)
        else:
            name, voice = MULTI, multi
            text = rng.choice(texts_en)

        pcm = pad(synth(voice, text, cfg), rng)
        fn = out / f"{kind}_{i:05d}.wav"
        sf.write(fn, pcm, TARGET_SR)
        manifest.append({"file": fn.name, "text": text, "voice": name,
                         "speaker_id": cfg.speaker_id, "length_scale": round(cfg.length_scale, 3)})

        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{n}")

    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    tot_s = sum(sf.info(out / m["file"]).duration for m in manifest[:100]) / 100 * n
    print(f"  {kind}: {n} file, ~{tot_s / 60:.1f} min di audio in {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["positive", "negative", "hard", "both"])
    ap.add_argument("-n", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1337)
    a = ap.parse_args()

    kinds = ["positive", "negative"] if a.kind == "both" else [a.kind]
    for k in kinds:
        print(f"genero {k}...")
        generate(k, a.n, a.seed + (0 if k == "positive" else 1))


if __name__ == "__main__":
    main()
