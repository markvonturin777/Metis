"""M0 giorno 6 — la catena completa, da riga di comando.

    push-to-talk → microfono → VAD → Whisper → Ollama → Piper → altoparlanti

Questo file e' CODICE USA-E-GETTA, per progetto. In M1 viene sostituito dalla
macchina a stati: qui il ciclo e' sequenziale e non sa nulla di wake word,
barge-in o stati. Serve a una cosa sola — misurare la latenza end-to-end
reale della catena intera, che e' la seconda domanda di M0.

Quello che invece SOPRAVVIVE e' tutto il resto: capture, vad, stt, llm, tts e
TurnMetrics. La macchina a stati li riusera' cosi' come sono.
"""

from __future__ import annotations

import sys
import time
import uuid
import warnings

warnings.filterwarnings("ignore")

import pynvml  # noqa: E402

from metis.audio.capture import AudioCapture  # noqa: E402
from metis.audio.ptt import DEFAULT_HOTKEY, GlobalHotkeys, PushToTalk  # noqa: E402
from metis.audio.vad import SpeechSegmenter  # noqa: E402
from metis.core.metrics import TurnMetrics, report  # noqa: E402
from metis.llm.client import LlmClient  # noqa: E402
from metis.stt.whisper_engine import WhisperEngine  # noqa: E402
from metis.tts import create_engine  # noqa: E402
from metis.tts.kokoro_engine import Player  # noqa: E402

SYSTEM = (
    "Sei Metis, assistente personale su questo PC. Rispondi in italiano, "
    "formale ma con ironia discreta. MASSIMO DUE FRASI BREVI: l'utente ti "
    "ascolta, non ti legge. Niente preamboli, niente 'Certamente'."
)


def main() -> None:
    n_target = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
    vram = lambda: pynvml.nvmlDeviceGetMemoryInfo(gpu).used / 1024**3  # noqa: E731

    print("carico i motori...")
    t0 = time.perf_counter()
    stt = WhisperEngine("small")
    llm = LlmClient()
    tts = create_engine()
    print(f"  STT warmup : {stt.warmup():6.0f} ms")
    print(f"  LLM warmup : {llm.warmup():6.0f} ms")
    print(f"  TTS warmup : {tts.warmup():6.0f} ms")
    print(f"  totale     : {time.perf_counter() - t0:.1f} s   VRAM {vram():.2f} GB")

    player = Player(sample_rate=tts.sample_rate)
    player.start()

    ptt = PushToTalk(on_change=lambda s: print(f"\n[ascolto {'ON' if s else 'OFF'}]"))
    hk = GlobalHotkeys()
    hk.bind(DEFAULT_HOTKEY, ptt.toggle)
    hk.start()
    ptt.set(True)

    seg_er = SpeechSegmenter()
    history: list[dict] = [{"role": "system", "content": SYSTEM}]
    turns: list[TurnMetrics] = []

    print(f"\nParla pure. {DEFAULT_HOTKEY} per sospendere, Ctrl+C per uscire.")
    print(f"Obiettivo: {n_target} turni.\n")

    try:
        with AudioCapture() as cap:
            for block in cap.blocks(timeout=1.0):
                if not ptt.listening or player.speaking.is_set():
                    # Half-duplex rudimentale: mentre parla, non ascolta. In M1
                    # diventa uno stato vero della macchina, con barge-in.
                    continue

                seg = seg_er.feed(block)
                if seg is None:
                    continue

                m = TurnMetrics(
                    turn_id=uuid.uuid4().hex[:8],
                    t_speech_end=seg.t_speech_end,
                    t_endpoint=seg.t_endpoint,
                    audio_s=seg.duration_s,
                )

                tr = stt.transcribe(seg.pcm)
                m.t_stt_done = time.perf_counter()
                m.transcript = tr.text
                if not tr.text or tr.suspect:
                    print(f"  (scartato: {tr.text!r})")
                    continue
                print(f"  tu     : {tr.text}")

                history.append({"role": "user", "content": tr.text})
                m.t_llm_sent = time.perf_counter()

                first = True
                # Le soglie del primo chunk le gestisce stream_sentences:
                # qui `first` sarebbe valutato una sola volta alla creazione
                # del generatore, quindi il ramo non avrebbe alcun effetto.
                for chunk, gm in llm.stream_sentences(history):
                    if first:
                        m.t_ttft = m.t_llm_sent + (gm.ttft_ms or 0) / 1000.0
                        m.t_first_chunk = time.perf_counter()

                    syn = tts.synth(chunk)
                    if first:
                        m.t_tts_done = time.perf_counter()

                    player.enqueue(syn.pcm)
                    if first:
                        m.t_first_audio = time.perf_counter()
                        first = False
                    print(f"  Metis  : {chunk}")

                m.tokens, m.tok_per_s = gm.tokens, gm.tok_per_s
                m.reply = gm.text
                m.vram_gb = vram()
                history.append({"role": "assistant", "content": gm.text})

                b = m.breakdown()
                print(
                    f"         [endpoint {b['endpointing']:.0f} | stt {b['stt']:.0f} | "
                    f"ttft {b['ttft']:.0f} | frase {b['prima_frase']:.0f} | "
                    f"tts {b['tts']:.0f}]  TOTALE {b['totale']:.0f} ms\n"
                )
                m.append_to_log()
                turns.append(m)
                if len(turns) >= n_target:
                    break
    except KeyboardInterrupt:
        print("\ninterrotto")
    finally:
        hk.stop()
        player.close()

    print(report(turns))
    if turns:
        print(f"\n  VRAM finale: {vram():.2f} GB   log: data/logs/turns.jsonl")


if __name__ == "__main__":
    main()
