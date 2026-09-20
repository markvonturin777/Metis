"""Sonda le capacita' del device di ingresso prima di scrivere capture.py.

Il Yeti e' nativo a 48 kHz stereo; la pipeline vuole 16 kHz mono.
Va deciso CHI fa il resampling: il motore audio di Windows o noi.
"""
import numpy as np
import sounddevice as sd

DEV = 15  # WASAPI - Microfono (Yeti Classic)

print(f"device [{DEV}]: {sd.query_devices(DEV)['name']}")
print(f"host api  : {sd.query_hostapis(sd.query_devices(DEV)['hostapi'])['name']}\n")

print("=== quali combinazioni samplerate/canali accetta? ===")
for sr in (16000, 22050, 44100, 48000):
    for ch in (1, 2):
        try:
            sd.check_input_settings(device=DEV, samplerate=sr, channels=ch, dtype="int16")
            print(f"  {sr:>5} Hz  {ch} ch  OK")
        except Exception as e:
            print(f"  {sr:>5} Hz  {ch} ch  NO  ({str(e)[:45]})")

print("\n=== latenza dichiarata dal driver ===")
d = sd.query_devices(DEV)
print(f"  low  : {d['default_low_input_latency'] * 1000:.1f} ms")
print(f"  high : {d['default_high_input_latency'] * 1000:.1f} ms")

print("\n=== dimensione blocco per Silero VAD ===")
print("  Silero vuole esattamente 512 campioni a 16 kHz = 32,0 ms")
print(f"  a 48 kHz sarebbero 1536 campioni, decimati 3:1 -> 512")
