"""Quale grafia fa pronunciare "Metis" come lo dici tu?

Le voci inglesi di libritts leggono "Metis" all'inglese. Prima di generare
migliaia di campioni va verificato QUALE grafia si avvicina alla pronuncia
italiana, altrimenti si addestra il modello sul suono sbagliato.
"""
import io
import wave
import pathlib
import numpy as np
import soundfile as sf
import soxr
from piper import PiperVoice, SynthesisConfig

OUT = pathlib.Path("wakeword/pronuncia"); OUT.mkdir(parents=True, exist_ok=True)
V = pathlib.Path("data/piper")

def synth(voice, text, cfg):
    b = io.BytesIO()
    with wave.open(b, "wb") as w: voice.synthesize_wav(text, w, cfg)
    b.seek(0)
    with wave.open(b, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768
        sr = w.getframerate()
    return soxr.resample(pcm, sr, 16000, quality="HQ").astype(np.float32)

GRAFIE = ["Hey Metis", "Hey Mettis", "Hey Mehtis", "Hey Metiss", "Hey Met-iss"]
SPEAKERS = [12, 201, 555]          # tre timbri inglesi diversi

print("RIFERIMENTO — voci italiane, pronuncia corretta")
it = PiperVoice.load(str(V/"it_IT-paola-medium.onnx"))
sf.write(OUT/"00_RIFERIMENTO_paola.wav", synth(it, "Hey Metis", SynthesisConfig()), 16000)
it2 = PiperVoice.load(str(V/"it_IT-riccardo-x_low.onnx"))
sf.write(OUT/"01_RIFERIMENTO_riccardo.wav", synth(it2, "Hey Metis", SynthesisConfig()), 16000)
print("  00_RIFERIMENTO_paola.wav, 01_RIFERIMENTO_riccardo.wav")

print("\nCANDIDATE — voci inglesi, grafie diverse")
en = PiperVoice.load(str(V/"en_US-libritts_r-medium.onnx"))
for i, g in enumerate(GRAFIE):
    for j, sid in enumerate(SPEAKERS):
        # NB: il trattino va sostituito, non rimosso: altrimenti "Metiss" e
        # "Met-iss" producono lo stesso nome file e il confronto e' ambiguo.
        nome = f"{10+i}{j}_EN_{g.replace(' ','_').replace('-','TRATT')}_sp{sid}.wav"
        sf.write(OUT/nome, synth(en, g, SynthesisConfig(speaker_id=sid)), 16000)
    print(f"  grafia {g!r} -> 3 file {10+i}*")

print(f"\nAscolta in {OUT.resolve()}")
print("Confronta le CANDIDATE con i due RIFERIMENTO e dimmi quale grafia")
print("si avvicina di piu' a come pronunci tu 'Metis'.")
