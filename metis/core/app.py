"""Metis da riga di comando.

    microfono -> [wake word] -> VAD -> Whisper -> Qwen -> Piper -> altoparlanti
                      |                     |                        |
                      +--- barge-in / PTT --+       router -> broker -+

IN V1.0 LA WAKE WORD E' SPENTA
Decisione D1: "Hey Metis" non ha superato NFR-7 nella seduta del 21 settembre
e viene rimandata alla v2. Si riaccende con `enabled = true` in
`config/wakeword.toml`; modello, banchi di prova e dati restano in
repository, e con loro tutto l'impianto anti-eco, che e' quello che rende la
riaccensione una riga di configurazione invece che una riscrittura.

QUESTO FILE E' UN'INTERFACCIA, NON IL SISTEMA
Da M3 esistono due modi di avviare Metis, questo e la GUI. Il sistema si
costruisce in `metis/core/avvio.py`, una volta sola: due cablaggi
divergerebbero in silenzio, e il punto in cui non ci si puo' permettere una
divergenza e' la sicurezza. Qui restano solo le cose che sono davvero della
console — le scorciatoie globali, cosa si stampa, il riepilogo finale.
"""

from __future__ import annotations

import argparse
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from metis.audio.capture import find_input_device  # noqa: E402
from metis.audio.ptt import (  # noqa: E402
    DEFAULT_HOTKEY,
    DEFAULT_KILL_SWITCH,
    GlobalHotkeys,
)
from metis.core.avvio import (  # noqa: E402
    SYSTEM,  # noqa: F401  (ri-esportato: lo importano i banchi di prova)
    CicloAudio,
    Opzioni,
    Sistema,
    costruisci_sistema,
)
from metis.core.logging import JSONL, clear_turn, configure, get_logger  # noqa: E402
from metis.security.killswitch import KILL_SWITCH  # noqa: E402


def riepilogo(sis: Sistema, ciclo: CicloAudio) -> None:
    c = sis.orchestrator.counters
    durata_s = ciclo.durata_s
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
    print(f"  strumenti eseguiti   : {c.tools_ok}")
    print(f"  strumenti rifiutati  : {c.tools_denied}")
    print(f"  turni scartati       : {c.discarded}")
    print(f"  errori               : {c.errors}")
    print(f"  frame al VAD         : {c.frames_to_vad}")
    print(f"  frame silenziati     : {c.frames_muted}   (half-duplex, L1)")
    if ciclo.capture is not None:
        print(f"  blocchi persi        : {ciclo.capture.dropped}")
    if sis.detector is not None and sis.detector.scores:
        s = sis.detector.stats()
        print(f"  punteggi wake word   : p50 {s['p50']:.3f}  p99 {s['p99']:.3f}  "
              f"max {s['max']:.3f}   su {s['blocchi']} blocchi")
    if sis.audit is not None:
        print(f"  audit                : {sis.audit.stats()}")
    if sis.orchestrator.sm.rejected:
        # Eventi fuori sequenza: un blocco in coda, un timeout scattato un
        # istante dopo la transizione. Sono attesi, si contano e basta.
        print(f"  transizioni rifiutate: {len(sis.orchestrator.sm.rejected)}"
              "   (fuori sequenza)")
    print(f"\n  log: {JSONL}   turni: data/logs/turns.jsonl")


def main() -> None:
    ap = argparse.ArgumentParser(description="Metis - assistente vocale locale")
    ap.add_argument("--minutes", type=float, default=0.0,
                    help="ferma la sessione dopo N minuti (0 = finche' non esci)")
    ap.add_argument("--no-wakeword", dest="wakeword", action="store_false",
                    help="solo push-to-talk, rilevatore spento")
    ap.add_argument("--no-tools", dest="tools", action="store_false",
                    help="solo voce: nessuno strumento, nessun broker")
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

    sis = costruisci_sistema(Opzioni.da_args(args), log,
                             riporta=lambda r: print(f"  {r}"))
    orch = sis.orchestrator

    # Il push-to-talk resta anche con la wake word attiva: serve quando c'e'
    # rumore, quando si e' in chiamata, o quando non si vuole parlare forte.
    hk = GlobalHotkeys()
    hk.bind(DEFAULT_HOTKEY, orch.on_ptt)

    # Lo stesso tasto fa due cose perche' sono due effetti della stessa
    # intenzione: "fermati". Chi lo preme non deve ricordarsi quale dei due
    # gli serve mentre sta cercando di fermare qualcosa.
    def kill_switch() -> None:
        orch.panic()
        sospeso = KILL_SWITCH.commuta()
        log.warning("kill switch", capacita="SOSPESE" if sospeso else "ripristinate")
        stato = "SOSPESI" if sospeso else "ripristinati"
        print(f"\n  [kill switch] T2 e T3 {stato}\n")

    hk.bind(DEFAULT_KILL_SWITCH, kill_switch)
    hk.start()

    if sis.detector is not None:
        print('\n  Di\' "Hey Metis", oppure usa il push-to-talk.')
    else:
        print("\n  Wake word spenta (D1: rimandata alla v2). Push-to-talk:")
    print(f"  {DEFAULT_HOTKEY:<24} parla, e interrompi Metis mentre parla")
    print(f"  {DEFAULT_KILL_SWITCH:<24} kill switch: zittisce e sospende T2/T3")
    print(f"  {'Ctrl+C':<24} esci\n")

    ciclo = CicloAudio(orch)
    try:
        ciclo.esegui(limite_s=args.minutes * 60 if args.minutes else None)
        if args.minutes:
            print("\n  tempo scaduto")
    except KeyboardInterrupt:
        print("\n  interrotto")
    finally:
        hk.stop()
        orch.panic()
        sis.player.close()
        clear_turn()

    riepilogo(sis, ciclo)


if __name__ == "__main__":
    main()
