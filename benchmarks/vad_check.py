"""Taratura VAD + prova push-to-talk.

Misura il costo reale dell'endpointing, che nella specifica e' stimato
200-300 ms ed e' il pavimento irriducibile della latenza.
"""
import sys, time
import numpy as np
from metis.audio.capture import AudioCapture
from metis.audio.vad import SpeechSegmenter
from metis.audio.ptt import GlobalHotkeys, PushToTalk, DEFAULT_HOTKEY

MIN_SILENCE_MS = int(sys.argv[1]) if len(sys.argv) > 1 else 250

print(f"VAD: min_silence_duration_ms = {MIN_SILENCE_MS}")
print(f"Push-to-talk: {DEFAULT_HOTKEY}  (toggle)")
print("Pronuncia 5 frasi brevi, con una pausa netta dopo ognuna.")
print("Ctrl+C per uscire.\n")

ptt = PushToTalk(on_change=lambda s: print(f"  [PTT] ascolto {'ON' if s else 'OFF'}"))
hk = GlobalHotkeys()
hk.bind(DEFAULT_HOTKEY, ptt.toggle)
hk.start()
ptt.set(True)   # in M0 partiamo gia' in ascolto

seg_er = SpeechSegmenter(min_silence_ms=MIN_SILENCE_MS)
costs, durs = [], []

try:
    with AudioCapture() as cap:
        for b in cap.blocks(timeout=1.0):
            if not ptt.listening:
                continue
            seg = seg_er.feed(b)
            if seg is None:
                continue
            costs.append(seg.endpoint_cost_ms)
            durs.append(seg.duration_s)
            print(f"  frase {len(costs)}: durata {seg.duration_s:5.2f} s | "
                  f"endpointing {seg.endpoint_cost_ms:6.0f} ms | "
                  f"p_max {seg.max_prob:.2f} | {seg.pcm.size} campioni")
            if len(costs) >= 5:
                break
except KeyboardInterrupt:
    print("\ninterrotto")
finally:
    hk.stop()

if costs:
    print("\n" + "=" * 56)
    print(f"  endpointing medio  : {np.mean(costs):6.0f} ms")
    print(f"  endpointing p95    : {np.percentile(costs, 95):6.0f} ms")
    print(f"  endpointing min-max: {np.min(costs):6.0f} - {np.max(costs):.0f} ms")
    print(f"  dispersione        : {np.std(costs):6.0f} ms   <-- deve essere piccola")
    print(f"  atteso teorico     : {MIN_SILENCE_MS} ms + 1 blocco = {MIN_SILENCE_MS+32} ms")
    print(f"  budget specifica   : 200-300 ms")
    print(f"  durata media frase : {np.mean(durs):6.2f} s")
    m = np.mean(costs)
    if m > 350:   print("  !! sopra budget: prova min_silence_ms piu' basso")
    elif m < 150: print("  ~  molto reattivo: rischio di tagliare le pause naturali")
    else:         print("  OK dentro il budget")
