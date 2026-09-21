"""Metis M1 — l'applicazione vera, sostituisce lo scheletro di M0.

    microfono -> [wake word] -> VAD -> Whisper -> Qwen -> Piper -> altoparlanti
                      |                                              |
                      +------------- barge-in / PTT -----------------+

IN V1.0 LA WAKE WORD E' SPENTA
Decisione D1: "Hey Metis" non ha superato NFR-7 nella seduta del 21 settembre
e viene rimandata alla v2. Si riaccende con `enabled = true` in
`config/wakeword.toml`; modello, banchi di prova e dati di addestramento
restano in repository. Tutto il resto dell'impianto — il gating half-duplex,
`WAKE_ACTIVE`, il barge-in — resta identico, perche' e' quello che rende la
riaccensione una riga di configurazione invece che una riscrittura.

Lo scheletro di M0 era una catena sequenziale: serviva a misurare la latenza e
ha fatto il suo lavoro. Qui il ciclo principale non sa nulla della catena, fa
una cosa sola — passare blocchi all'orchestratore e far scattare i timeout — e
tutte le decisioni stanno nella macchina a stati.

QUESTO FILE E' IL CABLAGGIO, NON LA LOGICA
Costruisce gli oggetti, li inietta e li spegne in ordine. Se qui dentro
comparisse un `if` sullo stato, sarebbe nel posto sbagliato: quella e' roba
della macchina a stati, dove e' verificabile senza microfono.

L'AVVIO A FREDDO NON E' UN DETTAGLIO
Whisper, Qwen e Piper caricati a freddo costano una settantina di secondi, e
il grosso e' Qwen che sale in VRAM. Vanno scaldati PRIMA di dire all'utente
che Metis e' pronto: il primo turno non deve mai pagare il caricamento.
"""

from __future__ import annotations

import argparse
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from metis.audio.capture import AudioCapture, find_input_device  # noqa: E402
from metis.audio.ptt import (  # noqa: E402
    DEFAULT_HOTKEY,
    DEFAULT_KILL_SWITCH,
    GlobalHotkeys,
)
from metis.audio.wakeword import WakeWordConfig, WakeWordDetector  # noqa: E402
from metis.core.logging import (  # noqa: E402
    JSONL,
    bind_turn,
    clear_turn,
    configure,
    get_logger,
    log_transition,
)
from metis.core.orchestrator import Deps, Orchestrator  # noqa: E402
from metis.llm.client import LlmClient  # noqa: E402
from metis.stt.whisper_engine import WhisperEngine  # noqa: E402
from metis.tts import create_engine  # noqa: E402
from metis.tts.kokoro_engine import Player  # noqa: E402

SYSTEM = (
    "Sei Metis, assistente personale su questo PC. Rispondi in italiano, "
    "formale ma con ironia discreta. MASSIMO DUE FRASI BREVI: l'utente ti "
    "ascolta, non ti legge. Niente preamboli, niente 'Certamente'."
)

TICK_S = 0.5          # ogni quanto si controllano i timeout degli stati


def costruisci(args, log) -> tuple[Orchestrator, Player, WakeWordDetector | None]:
    """Carica i motori, li scalda e li cabla nell'orchestratore."""
    t0 = time.perf_counter()

    stt = WhisperEngine(args.whisper)
    llm = LlmClient()
    tts = create_engine()
    player = Player(sample_rate=tts.sample_rate)

    print(f"  STT {args.whisper:<8} : {stt.warmup():6.0f} ms")
    print(f"  LLM {llm.model:<8} : {llm.warmup():6.0f} ms")
    print(f"  TTS          : {tts.warmup():6.0f} ms")

    det: WakeWordDetector | None = None
    cfg_ww = WakeWordConfig.load()
    if args.wakeword and cfg_ww.enabled:
        cfg = cfg_ww
        det = WakeWordDetector(cfg)
        # La prima inferenza ONNX include l'allocazione delle arene: costa
        # decine di millisecondi contro 1,7. Si paga adesso, non al primo
        # "Hey Metis" dell'utente.
        muto = np.zeros(512, dtype=np.float32)
        t_w = time.perf_counter()
        for _ in range(8):
            det.feed(muto)
        caldo = time.perf_counter()
        for _ in range(20):
            det.feed(muto)
        # Due numeri diversi: il primo include l'allocazione delle arene ONNX,
        # il secondo e' il costo vero a regime. Riportare solo la media dei
        # primi blocchi farebbe sembrare il rilevatore sette volte piu' caro.
        print(f"  wake word    : {(caldo - t_w) * 1000 / 8:6.2f} ms primo blocco, "
              f"{(time.perf_counter() - caldo) * 1000 / 20:.2f} ms a regime (budget 80)")
        print(f"                 soglia {cfg.threshold}  x{cfg.consecutive} blocchi"
              + ("  DOPPIA FASE" if cfg.dual_phase else ""))
        det.reset()
        det.scores.clear()
        det.scores_dual.clear()

    print(f"  pronti in {time.perf_counter() - t0:.1f} s")
    player.start()

    # I motori si avvolgono qui, non dentro l'orchestratore: l'orchestratore
    # deve restare ignaro di quale STT o TTS stia usando.
    def stt_loggato(pcm):
        tr = stt.transcribe(pcm)
        log.info("trascritto", testo=tr.text, sospetto=tr.suspect, rtf=round(tr.rtf, 2))
        return tr

    def tts_loggato(testo: str):
        log.info("dice", testo=testo)
        return tts.synth(testo)

    def fine_turno(m) -> None:
        b = m.breakdown()
        log.info("turno", totale_ms=round(b["totale"]), stt_ms=round(b["stt"]),
                 ttft_ms=round(b["ttft"]), tts_ms=round(b["tts"]), tokens=m.tokens)
        clear_turn()

    deps = Deps(
        wakeword=(det.feed if det is not None else (lambda pcm: False)),
        stt=stt_loggato,
        llm_stream=llm.stream_sentences,
        tts_synth=tts_loggato,
        player=player,
        system_prompt=SYSTEM,
        wake_reset=(det.reset if det is not None else None),
        on_error=lambda e: log.error("turno fallito", errore=f"{type(e).__name__}: {e}"),
        on_turn_start=bind_turn,
        on_turn_end=fine_turno,
    )
    orch = Orchestrator(deps, on_transition=lambda tr: log_transition(log, tr))
    return orch, player, det


def riepilogo(orch: Orchestrator, det: WakeWordDetector | None,
              cap: AudioCapture, durata_s: float) -> None:
    c = orch.counters
    ore = durata_s / 3600.0
    print("\n" + "=" * 62)
    print(f"  SESSIONE  {durata_s / 60:.1f} minuti")
    print("=" * 62)
    print(f"  turni completati     : {c.turns}")
    print(f"  rilevamenti wake     : {c.wake_detections}"
          + (f"   ({c.wake_detections / ore:.1f}/h)" if ore > 0.05 else ""))
    print(f"  barge-in             : {c.barge_ins}")
    if c.cancel_latency_ms:
        v = np.array(c.cancel_latency_ms)
        print(f"     latenza stop      : p50 {np.percentile(v, 50):.0f} ms  "
              f"max {v.max():.0f} ms    (NFR: < 200)")
    print(f"  turni scartati       : {c.discarded}")
    print(f"  errori               : {c.errors}")
    print(f"  frame al VAD         : {c.frames_to_vad}")
    print(f"  frame silenziati     : {c.frames_muted}   (half-duplex, L1)")
    print(f"  blocchi persi        : {cap.dropped}")
    if det is not None and det.scores:
        s = det.stats()
        print(f"  punteggi wake word   : p50 {s['p50']:.3f}  p99 {s['p99']:.3f}  "
              f"max {s['max']:.3f}   su {s['blocchi']} blocchi")
    if orch.sm.rejected:
        # Eventi fuori sequenza: un blocco in coda, un timeout scattato un
        # istante dopo la transizione. Sono attesi, si contano e basta.
        print(f"  transizioni rifiutate: {len(orch.sm.rejected)}   (fuori sequenza)")
    print(f"\n  log: {JSONL}   turni: data/logs/turns.jsonl")


def main() -> None:
    ap = argparse.ArgumentParser(description="Metis - assistente vocale locale (M1)")
    ap.add_argument("--minutes", type=float, default=0.0,
                    help="ferma la sessione dopo N minuti (0 = finche' non esci)")
    ap.add_argument("--no-wakeword", dest="wakeword", action="store_false",
                    help="solo push-to-talk, rilevatore spento")
    ap.add_argument("--whisper", default="small")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    configure(level=args.log_level)
    log = get_logger()

    print("=" * 62)
    print("  Metis V1.0 - push-to-talk, half-duplex, barge-in")
    print("=" * 62)
    try:
        print(f"  microfono    : #{find_input_device()}")
    except RuntimeError as e:
        print(f"  microfono    : {e}")
        return

    orch, player, det = costruisci(args, log)

    # Il push-to-talk resta anche con la wake word attiva: serve quando c'e'
    # rumore, quando si e' in chiamata, o quando non si vuole parlare forte.
    hk = GlobalHotkeys()
    hk.bind(DEFAULT_HOTKEY, orch.on_ptt)
    hk.bind(DEFAULT_KILL_SWITCH, lambda: (log.warning("kill switch"), orch.panic()))
    hk.start()

    if det is not None:
        print('\n  Di\' "Hey Metis", oppure usa il push-to-talk.')
    else:
        print("\n  Wake word spenta (D1: rimandata alla v2). Push-to-talk:")
    print(f"  {DEFAULT_HOTKEY:<24} parla, e interrompi Metis mentre parla")
    print(f"  {DEFAULT_KILL_SWITCH:<24} kill switch: zittisce e torna in attesa")
    print(f"  {'Ctrl+C':<24} esci\n")

    t_inizio = time.perf_counter()
    limite = args.minutes * 60 if args.minutes else None
    ultimo_tick = t_inizio
    cap = AudioCapture()

    try:
        with cap:
            while True:
                blocco = cap.read(timeout=0.25)
                if blocco is not None:
                    orch.on_audio(blocco)

                ora = time.perf_counter()
                if ora - ultimo_tick >= TICK_S:
                    # I timeout scattano qui, non dal flusso audio: se il
                    # microfono smettesse di consegnare blocchi, la macchina
                    # resterebbe appesa nello stato corrente per sempre.
                    orch.tick()
                    ultimo_tick = ora
                if limite is not None and ora - t_inizio > limite:
                    print("\n  tempo scaduto")
                    break
    except KeyboardInterrupt:
        print("\n  interrotto")
    finally:
        hk.stop()
        orch.panic()
        player.close()
        clear_turn()

    riepilogo(orch, det, cap, time.perf_counter() - t_inizio)


if __name__ == "__main__":
    main()
