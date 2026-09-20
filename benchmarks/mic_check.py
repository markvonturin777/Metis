"""Diagnostica microfono: livelli, rumore di fondo, SNR, margine di clipping.

NOTA SULLA MISURA (correzione del 2026-09-20)
La prima versione usava la mediana dell'RMS su tutta la finestra di ascolto.
Sbagliato: in 6 secondi con una frase breve la maggior parte dei blocchi sono
silenzio, quindi la mediana misurava le pause e sottostimava la voce di ~35 dB.
Ora si separano i blocchi con voce attiva da quelli di silenzio usando una
soglia ricavata dal rumore di fondo appena misurato.
"""
import time
import numpy as np
import sounddevice as sd
from metis.audio.capture import AudioCapture, find_input_device

def bar(dbfs: float, width: int = 40) -> str:
    n = int(max(0.0, min(1.0, (dbfs + 60) / 60)) * width)
    return "#" * n + "." * (width - n)

def listen(seconds: float, label: str) -> tuple[np.ndarray, np.ndarray, int]:
    print(f"\n>>> {label} ({seconds:.0f} s)")
    rms, peak = [], []
    with AudioCapture() as cap:
        t_end, last = time.time() + seconds, 0.0
        for b in cap.blocks(timeout=1.0):
            rms.append(b.rms_dbfs); peak.append(b.peak_dbfs)
            if time.time() - last > 0.1:
                print(f"\r  {bar(b.rms_dbfs)}  rms {b.rms_dbfs:6.1f}  peak {b.peak_dbfs:6.1f} dBFS", end="")
                last = time.time()
            if time.time() > t_end:
                break
        dropped = cap.dropped
    print()
    return np.array(rms), np.array(peak), dropped

dev = find_input_device()
print(f"device: [{dev}] {sd.query_devices(dev)['name']}  (WASAPI, 48 kHz -> 16 kHz)")

sil_rms, sil_peak, d1 = listen(4, "NON PARLARE — misuro il rumore di fondo")
noise_floor = float(np.median(sil_rms))

input("\nPremi INVIO, poi leggi ad alta voce la frase che appare...")
print('  >> "Hey Metis, sposta questa finestra sullo schermo a destra."')
v_rms, v_peak, d2 = listen(6, "PARLA ORA, tono e distanza abituali")

# --- separazione voce / silenzio -------------------------------------------
# Soglia ADATTIVA. Una soglia ancorata solo al rumore di fondo fallisce quando
# la stanza e' molto silenziosa: con un fondo a -88 dBFS, "fondo + 15" cade a
# -73, dove c'e' ancora silenzio, e nei blocchi "attivi" finiscono respiri e
# code di parola che abbassano la media di ~17 dB. Si ancora quindi la soglia
# anche al livello del parlato stesso, nello spirito di ITU-T P.56.
loud = float(np.percentile(v_rms, 95))
gate = max(noise_floor + 15.0, loud - 20.0)
active = v_rms[v_rms > gate]
frac = len(active) / len(v_rms) if len(v_rms) else 0.0

if len(active) < 5:
    print("\n!! Quasi nessun blocco sopra la soglia di voce. Hai parlato?")
    raise SystemExit(1)

voice_rms = float(np.mean(active))
voice_p95 = float(np.percentile(active, 95))
peak_max = float(np.max(v_peak))
crest = peak_max - voice_rms
snr = voice_rms - noise_floor
headroom = -peak_max

print("\n" + "=" * 64)
print("  RISULTATI")
print("=" * 64)
print(f"  rumore di fondo                : {noise_floor:6.1f} dBFS")
print(f"  soglia voce usata              : {gate:6.1f} dBFS")
print(f"  blocchi con voce attiva        : {frac * 100:5.1f} %  ({len(active)}/{len(v_rms)})")
print(f"  VOCE rms (solo blocchi attivi) : {voice_rms:6.1f} dBFS   <-- il numero che conta")
print(f"  VOCE rms p95                   : {voice_p95:6.1f} dBFS")
print(f"  picco assoluto                 : {peak_max:6.1f} dBFS")
print(f"  margine prima del clipping     : {headroom:6.1f} dB")
print(f"  fattore di cresta              : {crest:6.1f} dB   (normale 12-18)")
print(f"  obiettivo picco                :  -12.0 .. -6.0 dBFS")
print(f"  SNR reale                      : {snr:6.1f} dB")
print(f"  blocchi persi                  : {d1 + d2}")

print("\n  DIAGNOSI")
ok = True
if peak_max > -3.0:
    print(f"  !! MARGINE INSUFFICIENTE ({headroom:.1f} dB). Abbassa il guadagno del Yeti:")
    print("     basta una parola detta piu' forte per andare in clipping, e il")
    print("     clipping distrugge il riconoscimento molto piu' di un livello basso."); ok = False
elif peak_max > -6.0:
    print(f"  ~  Margine stretto ({headroom:.1f} dB). Abbassa il guadagno di un filo.")
if voice_rms < -35:
    print(f"  ~  Voce debole ({voice_rms:.0f} dBFS rms). Alza il guadagno o avvicinati."); ok = False
elif voice_rms > -14:
    print(f"  ~  Voce molto forte ({voice_rms:.0f} dBFS rms).")
if crest > 25:
    print(f"  ~  Cresta {crest:.0f} dB: insolita. Picco isolato, o blocchi attivi pochi.")
if snr >= 40:
    print(f"  OK SNR {snr:.0f} dB: eccellente. VAD e STT lavoreranno senza fatica.")
elif snr >= 25:
    print(f"  OK SNR {snr:.0f} dB: buono.")
else:
    print(f"  !! SNR {snr:.0f} dB: basso, il VAD fara' fatica."); ok = False
if noise_floor < -70:
    print(f"  OK Fondo a {noise_floor:.0f} dBFS: stanza molto silenziosa.")
if ok and -35 <= voice_rms <= -14 and peak_max <= -6:
    print("\n  >> Configurazione audio pronta. Si puo' tarare il VAD.")
