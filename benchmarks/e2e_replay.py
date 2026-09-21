"""Catena completa, guidata da file invece che dal microfono.

PERCHE' ESISTE
Fino a ieri wake word, macchina a stati e barge-in erano verificati ognuno per
conto suo: la wake word dal vivo, la macchina a stati con eventi finti, il
barge-in con motori finti. Tutti e tre verdi non dimostrano che il sistema
intero funzioni — il bug del thread mancante, trovato ieri, era esattamente di
quel tipo: ogni pezzo corretto, l'insieme rotto.

Qui gli oggetti sono quelli veri (Whisper, Qwen, Piper, il rilevatore ONNX) e
l'unica cosa sostituita e' la sorgente audio: al posto del microfono, i WAV
registrati con la voce dell'utente in M0 e in M1 giorno 7.

L'AUDIO SI RIPRODUCE A VELOCITA' REALE, NON A RAFFICA
Sarebbe piu' rapido consumare il WAV in un colpo solo, e sarebbe una prova
senza valore: il VAD misura il silenzio in blocchi, l'endpointing e i timeout
dipendono dall'orologio, e il barge-in ha senso solo se il secondo "Hey Metis"
arriva davvero mentre Metis sta parlando. Si va a 32 ms per blocco.

    python benchmarks/e2e_replay.py --ptt --bargein   # il percorso della V1.0
    python benchmarks/e2e_replay.py --bargein         # con la wake word (v2)
    python benchmarks/e2e_replay.py --audio           # fa uscire il suono davvero

IL PERCORSO PREDEFINITO DELLA V1.0 E' `--ptt`
Con D1 la wake word e' spenta in configurazione, quindi l'attivazione e
l'interruzione passano dal push-to-talk. Senza `--ptt` il banco accende il
rilevatore a forza e prova il percorso della v2: serve a tenerlo vivo e
verificato mentre e' spento, cosi' la riaccensione non trova sorprese.
"""

from __future__ import annotations

import argparse
import time
import warnings
from dataclasses import replace
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from metis.audio.capture import TARGET_SR, VAD_BLOCK, Block, _dbfs  # noqa: E402
from metis.audio.wakeword import WakeWordConfig, WakeWordDetector  # noqa: E402
from metis.core.app import SYSTEM  # noqa: E402
from metis.core.logging import bind_turn, clear_turn, configure, get_logger, log_transition  # noqa: E402
from metis.core.orchestrator import Deps, Orchestrator  # noqa: E402
from metis.core.state_machine import State  # noqa: E402
from metis.llm.client import LlmClient  # noqa: E402
from metis.stt.whisper_engine import WhisperEngine  # noqa: E402
from metis.tts import create_engine  # noqa: E402

WAKE_WAV = Path("wakeword/live/20260921_102600_pos_01.wav")
FRASE_WAV = Path("data/corpus/20260920_184152_00.wav")
BLOCK_S = VAD_BLOCK / TARGET_SR


class PlayerMuto:
    """Non emette suono ma RISPETTA I TEMPI. Con --audio si usa il Player vero.

    La prima versione tornava subito da `wait_drained`, e la prova del
    barge-in diventava priva di senso: lo stato lasciava PARLATO dopo pochi
    millisecondi, quindi non esisteva piu' una finestra in cui interrompere.
    La durata dell'audio accodato e' esattamente cio' che tiene Metis in
    PARLATO, e va simulata anche quando non si vuole sentire niente.
    """

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.chunks = 0
        self.samples = 0
        self.stopped = 0
        self._fine = 0.0          # istante in cui la coda finirebbe di suonare

    def enqueue(self, pcm) -> None:
        n = int(np.asarray(pcm).size)
        self._fine = max(self._fine, time.perf_counter()) + n / self.sample_rate
        self.chunks += 1
        self.samples += n

    def stop(self) -> None:
        self._fine = 0.0          # coda svuotata: l'audio non suona piu'
        self.stopped += 1

    def wait_drained(self, timeout: float = 120.0) -> bool:
        limite = time.perf_counter() + timeout
        while time.perf_counter() < min(self._fine, limite):
            time.sleep(0.02)
        return True

    def close(self) -> None:
        pass


def carica(path: Path) -> np.ndarray:
    pcm, sr = sf.read(path, dtype="float32")
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    assert sr == TARGET_SR, f"{path} non e' a 16 kHz"
    return pcm.astype(np.float32)


def silenzio(secondi: float) -> np.ndarray:
    """Silenzio vero, non zeri: il rumore di fondo fa parte del segnale.

    Con zeri esatti il VAD e il rilevatore vedono un ingresso che dal
    microfono non arriva mai, e la prova direbbe poco.
    """
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(secondi * TARGET_SR)) * 1e-4).astype(np.float32)


def attendi_stato(orch: Orchestrator, atteso: State, max_s: float = 8.0) -> bool:
    """Alimenta silenzio finche' la macchina non raggiunge `atteso`.

    La prima versione aspettava un tempo fisso prima di interrompere, e la
    prova falliva per un motivo che non c'entrava nulla col prodotto: la wake
    word sta in fondo al clip registrato, e quando arrivava la risposta era
    gia' finita. L'istante giusto non si conosce a priori — dipende da quanto
    e' lunga la risposta del modello — quindi si aspetta lo STATO.
    """
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < max_s:
        if orch.sm.state is atteso:
            return True
        riproduci(orch, silenzio(0.1))
    return False


def riproduci(orch: Orchestrator, pcm: np.ndarray, pace: bool = True) -> None:
    n = (pcm.size // VAD_BLOCK) * VAD_BLOCK
    t0 = time.perf_counter()
    for i in range(0, n, VAD_BLOCK):
        chunk = pcm[i : i + VAD_BLOCK]
        rms, peak = _dbfs(chunk)
        orch.on_audio(Block(chunk.copy(), rms, peak))
        if pace:
            atteso = t0 + (i / VAD_BLOCK + 1) * BLOCK_S
            ritardo = atteso - time.perf_counter()
            if ritardo > 0:
                time.sleep(ritardo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bargein", action="store_true",
                    help="secondo 'Hey Metis' mentre Metis risponde")
    ap.add_argument("--audio", action="store_true", help="riproduci davvero")
    ap.add_argument("--wake", type=Path, default=WAKE_WAV)
    ap.add_argument("--frase", type=Path, default=FRASE_WAV)
    ap.add_argument("--ptt", action="store_true",
                    help="percorso V1.0: attivazione e interruzione da push-to-talk")
    ap.add_argument("--whisper", default="small")
    args = ap.parse_args()

    configure()
    log = get_logger()

    print("=" * 62)
    print("  CATENA COMPLETA — sorgente: file, motori: veri")
    print("=" * 62)
    print(f"  attivazione: {'push-to-talk (percorso V1.0)' if args.ptt else args.wake.name}")
    print(f"  frase : {args.frase.name}")

    t0 = time.perf_counter()
    stt = WhisperEngine(args.whisper)
    llm = LlmClient()
    tts = create_engine()
    # Acceso a forza: in V1.0 la configurazione lo tiene spento (D1), ma
    # questo banco serve proprio a provarlo. Con --ptt non viene nemmeno
    # costruito, e si prova il percorso che la V1.0 usa davvero.
    det = None if args.ptt else WakeWordDetector(
        replace(WakeWordConfig.load(), enabled=True))
    if det is not None:
        for _ in range(8):
            det.feed(np.zeros(VAD_BLOCK, dtype=np.float32))
        det.reset()
        det.scores.clear()
    stt.warmup(); llm.warmup(); tts.warmup()
    print(f"  motori pronti in {time.perf_counter() - t0:.1f} s")

    if args.audio:
        from metis.tts.kokoro_engine import Player

        player = Player(sample_rate=tts.sample_rate)
        player.start()
    else:
        player = PlayerMuto(tts.sample_rate)

    traccia: list[tuple[float, str, str, str]] = []
    t_zero = time.perf_counter()

    def osserva(tr) -> None:
        traccia.append((time.perf_counter() - t_zero, tr.frm.name, tr.event.name, tr.to.name))
        log_transition(log, tr)

    deps = Deps(
        wakeword=(det.feed if det is not None else (lambda pcm: False)),
        stt=stt.transcribe,
        llm_stream=llm.stream_sentences,
        tts_synth=tts.synth,
        player=player,
        system_prompt=SYSTEM,
        wake_reset=(det.reset if det is not None else None),
        on_error=lambda e: log.error("turno fallito", errore=repr(e)),
        on_turn_start=bind_turn,
        on_turn_end=lambda m: clear_turn(),
    )
    orch = Orchestrator(deps, on_transition=osserva)

    # --- la sequenza ----------------------------------------------------
    print("\n  riproduzione a velocita' reale...\n")
    if args.ptt:
        orch.on_ptt()                      # sveglia: DORMIENTE -> IN_ASCOLTO
    else:
        riproduci(orch, carica(args.wake))
    riproduci(orch, silenzio(0.4))
    riproduci(orch, carica(args.frase))
    # Il VAD chiude la frase dopo 250 ms di silenzio: qui glieli si danno.
    riproduci(orch, silenzio(0.6))

    if args.bargein:
        if not attendi_stato(orch, State.PARLATO):
            print("\n  Metis non ha mai iniziato a parlare: niente da interrompere")
        elif args.ptt:
            print("\n  --- interruzione da push-to-talk ---")
            orch.on_ptt()
        else:
            print("\n  --- interruzione: Metis sta parlando ---")
            riproduci(orch, carica(args.wake))

    if orch._worker is not None:
        orch._worker.join(timeout=60)
    time.sleep(0.3)
    player.close()

    # --- esito ----------------------------------------------------------
    print("\n" + "=" * 62)
    print("  TRACCIA DEGLI STATI")
    print("=" * 62)
    for t, frm, ev, to in traccia:
        print(f"  {t:6.2f}s  {frm:<13} --{ev:<14}-> {to}")

    c = orch.counters
    print(f"\n  rilevamenti wake : {c.wake_detections}")
    print(f"  turni completati : {c.turns}")
    print(f"  scartati         : {c.discarded}")
    print(f"  errori           : {c.errors}")
    print(f"  barge-in         : {c.barge_ins}"
          + (f"   stop in {c.cancel_latency_ms[0]:.1f} ms" if c.cancel_latency_ms else ""))
    print(f"  frame al VAD     : {c.frames_to_vad}")
    print(f"  frame silenziati : {c.frames_muted}")
    if isinstance(player, PlayerMuto):
        print(f"  audio sintetizzato: {player.chunks} frasi, "
              f"{player.samples / tts.sample_rate:.1f} s")

    stati = [to for _, _, _, to in traccia]
    atteso = ["IN_ASCOLTO", "TRASCRIZIONE", "ELABORAZIONE", "GENERAZIONE", "PARLATO"]
    mancanti = [s for s in atteso if s not in stati]

    print("\n" + "=" * 62)
    if mancanti:
        print(f"  INCOMPLETA — stati mai raggiunti: {', '.join(mancanti)}")
    elif args.bargein and c.barge_ins == 0:
        print("  INTERRUZIONE NON RILEVATA — il barge-in non e' scattato")
    elif args.bargein:
        print(f"  OK — turno completo e interruzione a {c.cancel_latency_ms[0]:.0f} ms")
    else:
        print("  OK — turno completo attraverso tutti gli stati previsti")
    print(f"  stato finale: {orch.sm.state.name}"
          + ("" if orch.sm.state in (State.IN_ASCOLTO, State.DORMIENTE)
             else "   <-- inatteso"))
    print("=" * 62)


if __name__ == "__main__":
    main()
