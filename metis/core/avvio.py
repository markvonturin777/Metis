"""Costruzione del sistema. Un posto solo, due interfacce.

PERCHE' NON DUE CABLAGGI
Da M3 esistono due modi di avviare Metis: la console e la GUI. Se ognuno
costruisse il proprio sistema, prima o poi divergerebbero — e divergerebbero
in silenzio, perche' entrambi funzionerebbero. Il punto in cui non ci si puo'
permettere una divergenza e' la sicurezza: una GUI che dimentica di passare
il kill switch al broker sarebbe un'applicazione senza kill switch, e nessun
test dell'altra interfaccia lo direbbe.

Qui il sistema si costruisce una volta. Le interfacce scelgono due cose:
come riportare l'avanzamento dell'avvio, e come chiedere conferma per le
azioni T3. Tutto il resto e' identico per costruzione.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from metis.audio.wakeword import WakeWordConfig, WakeWordDetector
from metis.core.logging import bind_turn, clear_turn, log_transition
from metis.core.orchestrator import Azioni, Deps, Orchestrator
from metis.core.risposte import descrivi_sequenza
from metis.core.router import Router
from metis.memory.commands import Libreria
from metis.llm.client import LlmClient
from metis.llm.toolcall import ToolRouter
from metis.security.audit import AuditLog
from metis.security.broker import Broker
from metis.security.conferma import scegli_conferma
from metis.security.killswitch import KILL_SWITCH
from metis.security.policies import Context, richiede_conferma
from metis.stt.whisper_engine import WhisperEngine
from metis.tools import finestre
from metis.tools.registry import Registry, carica_tutti
from metis.tts import create_engine
from metis.tts.kokoro_engine import Player

SYSTEM = (
    "Sei Metis, assistente personale su questo PC. Rispondi in italiano, "
    "formale ma con ironia discreta. MASSIMO DUE FRASI BREVI: l'utente ti "
    "ascolta, non ti legge. Niente preamboli, niente 'Certamente'."
)


@dataclass
class Opzioni:
    """Quello che cambia fra un avvio e l'altro. Il resto no."""

    wakeword: bool = True
    tools: bool = True
    whisper: str = "small"
    log_level: str = "INFO"
    minutes: float = 0.0

    @classmethod
    def da_args(cls, args) -> "Opzioni":
        return cls(
            wakeword=getattr(args, "wakeword", True),
            tools=getattr(args, "tools", True),
            whisper=getattr(args, "whisper", "small"),
            log_level=getattr(args, "log_level", "INFO"),
            minutes=getattr(args, "minutes", 0.0),
        )


@dataclass
class Sistema:
    """Tutto quello che un'interfaccia deve poter vedere."""

    orchestrator: Orchestrator
    player: Player
    detector: WakeWordDetector | None = None
    audit: AuditLog | None = None
    registry: Registry | None = None
    broker: Broker | None = None
    router: Router | None = None
    libreria: Libreria | None = None
    avvio_s: float = 0.0
    note: list[str] = field(default_factory=list)


def costruisci_azioni(opz: Opzioni, log, riporta: Callable[[str], None],
                      chiedi_conferma: Callable | None = None
                      ) -> tuple[Azioni | None, dict[str, Any]]:
    """Il perimetro d'azione: registro, broker, router. Oppure niente.

    `chiedi_conferma` e' il solo punto in cui console e GUI differiscono. Il
    default sceglie la console se c'e' un terminale, e il rifiuto se non
    c'e': quando nessuno puo' acconsentire, la risposta e' no.
    """
    if not opz.tools:
        return None, {}

    reg = carica_tutti()
    audit = AuditLog()
    broker = Broker(registry=reg, audit=audit, kill=KILL_SWITCH)
    tool_router = ToolRouter(reg)
    libreria = Libreria(reg)
    router = Router(reg, libreria=libreria, tool_router=tool_router)
    chiedi = chiedi_conferma or scegli_conferma()
    for avviso in libreria.avvisi:
        log.warning("comando custom scartato", motivo=avviso)

    # Ollama compila la grammatica dell'output strutturato alla prima
    # richiesta: 3,8 s contro 250 ms. Si paga adesso.
    riporta(f"router       : {tool_router.warmup():6.0f} ms (a freddo)")

    disponibili = [s.name for s in reg.disponibili()]
    riporta(f"strumenti    : {len(disponibili)} attivi ({', '.join(disponibili)})")
    riporta(f"perimetro    : {len(reg)} registrati, "
            f"{len(reg) - len(disponibili)} senza capacita' (M4/M6)")
    s = router.stats()
    riporta(f"comandi rapidi: {s['comandi_configurati']} comandi, "
            f"{s['frasi']} frasi"
            + (f" ({len(libreria.avvisi)} scartati)" if libreria.avvisi else ""))

    def esegui(call: dict):
        r = broker.execute(call, Context(turn_id=None, chiedi_conferma=chiedi,
                                         origine="orchestratore"))
        log.info("strumento", tool=r.tool, esito=r.outcome.value,
                 stadio=r.stage, motivo=r.detail[:80], ms=round(r.duration_ms))
        return r

    def conferma_serve(nome: str) -> bool:
        spec = reg.get(nome)
        return spec is not None and richiede_conferma(spec.tier)

    azioni = Azioni(
        decidi=lambda testo, storia: router.decidi(testo, storia),
        esegui=esegui,
        descrivi=descrivi_sequenza,
        richiede_conferma=conferma_serve,
        # "Questa finestra" si fissa qui, all'ingresso in ascolto. Il
        # cablaggio sta in questo file e non nell'orchestratore perche' e'
        # l'unico posto che conosce sia il ciclo di vita del turno sia gli
        # strumenti: l'orchestratore non deve sapere che esistono le
        # finestre, e `finestre.py` non deve sapere che esiste un turno.
        al_risveglio=finestre.cattura_riferimento,
    )
    return azioni, {"registry": reg, "audit": audit, "broker": broker,
                    "router": router, "libreria": libreria}


def costruisci_sistema(opz: Opzioni, log,
                       riporta: Callable[[str], None] = print,
                       chiedi_conferma: Callable | None = None,
                       on_transition: Callable | None = None,
                       on_trascritto: Callable[[object], None] | None = None,
                       on_dice: Callable[[str], None] | None = None,
                       on_turno: Callable[[object], None] | None = None,
                       ) -> Sistema:
    """Carica i motori, li scalda, li cabla. Gli `on_*` sono per la GUI.

    Sono osservatori, non punti di controllo: possono guardare cosa succede
    e non possono cambiarlo. Un'interfaccia che potesse alterare il flusso
    diventerebbe parte della logica, e la logica dev'essere verificabile
    senza aprire una finestra.
    """
    t0 = time.perf_counter()

    stt = WhisperEngine(opz.whisper)
    llm = LlmClient()
    tts = create_engine()
    player = Player(sample_rate=tts.sample_rate)

    riporta(f"STT {opz.whisper:<8} : {stt.warmup():6.0f} ms")
    riporta(f"LLM {llm.model:<8} : {llm.warmup():6.0f} ms")
    riporta(f"TTS          : {tts.warmup():6.0f} ms")

    det: WakeWordDetector | None = None
    cfg_ww = WakeWordConfig.load()
    if opz.wakeword and cfg_ww.enabled:
        det = WakeWordDetector(cfg_ww)
        muto = np.zeros(512, dtype=np.float32)
        t_w = time.perf_counter()
        for _ in range(8):
            det.feed(muto)
        caldo = time.perf_counter()
        for _ in range(20):
            det.feed(muto)
        riporta(f"wake word    : {(caldo - t_w) * 1000 / 8:6.2f} ms primo blocco, "
                f"{(time.perf_counter() - caldo) * 1000 / 20:.2f} ms a regime")
        det.reset()
        det.scores.clear()
        det.scores_dual.clear()

    azioni, pezzi = costruisci_azioni(opz, log, riporta, chiedi_conferma)
    player.start()

    # I motori si avvolgono qui, non dentro l'orchestratore: l'orchestratore
    # deve restare ignaro di quale STT o TTS stia usando, e di chi lo guarda.
    def stt_loggato(pcm):
        tr = stt.transcribe(pcm)
        log.info("trascritto", testo=tr.text, sospetto=tr.suspect, rtf=round(tr.rtf, 2))
        if on_trascritto is not None:
            on_trascritto(tr)
        return tr

    def tts_loggato(testo: str):
        log.info("dice", testo=testo)
        if on_dice is not None:
            on_dice(testo)
        return tts.synth(testo)

    def fine_turno(m) -> None:
        b = m.breakdown()
        log.info("turno", totale_ms=round(b["totale"]), stt_ms=round(b["stt"]),
                 ttft_ms=round(b["ttft"]), tts_ms=round(b["tts"]), tokens=m.tokens)
        if on_turno is not None:
            on_turno(m)
        clear_turn()

    def osserva(tr) -> None:
        log_transition(log, tr)
        if on_transition is not None:
            on_transition(tr)

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
        azioni=azioni,
    )
    orch = Orchestrator(deps, on_transition=osserva)
    avvio = time.perf_counter() - t0
    riporta(f"pronti in {avvio:.1f} s")

    return Sistema(orchestrator=orch, player=player, detector=det,
                   avvio_s=avvio, **pezzi)


TICK_S = 0.5          # ogni quanto si controllano i timeout degli stati


class CicloAudio:
    """Il ciclo che alimenta l'orchestratore.

    Sta qui e non nelle interfacce perche' e' lo stesso ciclo in console e in
    GUI: nella prima gira sul thread principale, nella seconda su un QThread.
    Duplicarlo vorrebbe dire che un giorno uno dei due smette di far scattare
    i timeout, e il difetto comparirebbe solo in una delle due.

    `on_blocco` serve al VU meter: e' l'unico punto in cui un'interfaccia
    vede i singoli blocchi audio, e viene chiamato ~31 volte al secondo,
    quindi deve costare quasi niente. In GUI e' un emit di segnale, e il
    diradamento lo fa chi riceve.
    """

    def __init__(self, orchestrator, tick_s: float = TICK_S,
                 on_blocco: Callable[[object], None] | None = None):
        self.orchestrator = orchestrator
        self.tick_s = tick_s
        self.on_blocco = on_blocco
        self._ferma = False
        self.capture = None
        self.durata_s = 0.0

    def ferma(self) -> None:
        """Chiamabile da un altro thread: il ciclo esce al giro successivo."""
        self._ferma = True

    def esegui(self, limite_s: float | None = None) -> float:
        from metis.audio.capture import AudioCapture

        self._ferma = False
        t0 = time.perf_counter()
        ultimo_tick = t0
        self.capture = AudioCapture()
        try:
            with self.capture as cap:
                while not self._ferma:
                    blocco = cap.read(timeout=0.25)
                    if blocco is not None:
                        self.orchestrator.on_audio(blocco)
                        if self.on_blocco is not None:
                            self.on_blocco(blocco)

                    ora = time.perf_counter()
                    if ora - ultimo_tick >= self.tick_s:
                        # I timeout scattano qui, non dal flusso audio: se il
                        # microfono smettesse di consegnare blocchi, la
                        # macchina resterebbe appesa per sempre.
                        self.orchestrator.tick()
                        ultimo_tick = ora
                    if limite_s is not None and ora - t0 > limite_s:
                        break
        finally:
            self.durata_s = time.perf_counter() - t0
        return self.durata_s
