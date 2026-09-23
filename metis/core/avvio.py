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
from metis.core.orchestrator import Azioni, Conoscenza, Deps, Orchestrator
from metis.core.risposte import Filler, descrivi_sequenza, domanda_conferma
from metis.core.router import Router
from metis.memory.commands import Libreria
from metis.memory.conversation import Memoria
from metis.memory.slots import SLOTS
from metis.llm.client import LlmClient
from metis.llm.grounding import Consulente
from metis.llm.prompts import SYSTEM
from metis.llm.toolcall import ToolRouter
from metis.security.audit import AuditLog
from metis.security.broker import Broker
from metis.security.conferma import scegli_conferma
from metis.security.killswitch import KILL_SWITCH
from metis.security.policies import Context
from metis.stt.whisper_engine import WhisperEngine
from metis.tools import finestre
from metis.tools.registry import Registry, carica_tutti, serve_conferma
from metis.tts import create_engine
from metis.tts.kokoro_engine import Player

__all__ = ["SYSTEM", "Opzioni", "Sistema", "CicloAudio", "costruisci_sistema",
           "costruisci_azioni"]


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
    consulente: Consulente | None = None
    memoria: Memoria | None = None
    pianificatore: Any = None
    casa: Any = None
    avvio_s: float = 0.0
    note: list[str] = field(default_factory=list)

    def chiudi(self) -> None:
        """Ferma cio' che gira su thread propri: scheduler e Home Assistant.

        Lo scheduler si ferma SENZA aspettare i job in corso: un'email che
        sta partendo finisce da sola, e i job futuri restano in `jobs.db` —
        e' il loro posto, e al prossimo avvio ripartono.
        """
        for pezzo in (self.pianificatore, self.casa):
            if pezzo is not None:
                try:
                    pezzo.ferma()
                except Exception:                  # noqa: BLE001
                    pass


def costruisci_azioni(opz: Opzioni, log, riporta: Callable[[str], None],
                      chiedi_conferma: Callable | None = None
                      ) -> tuple[Azioni | None, Conoscenza | None, dict[str, Any]]:
    """Il perimetro d'azione: registro, broker, router. Oppure niente.

    `chiedi_conferma` e' il solo punto in cui console e GUI differiscono. Il
    default sceglie la console se c'e' un terminale, e il rifiuto se non
    c'e': quando nessuno puo' acconsentire, la risposta e' no.
    """
    if not opz.tools:
        return None, None, {}

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

    def esegui(call: dict, untrusted: bool = False):
        """L'unico punto da cui si passa dal broker, e l'unico che aggiorna
        gli slot.

        `untrusted` arriva dall'orchestratore e dal consulente, e finisce nel
        `Context` del broker. E' la difesa 3 di M5: da qui in giu' nessun
        prompt puo' piu' cambiare l'esito, perche' e' un confronto fra due
        insiemi in `policies.valuta_tier`.
        """
        r = broker.execute(call, Context(turn_id=None, chiedi_conferma=chiedi,
                                         has_untrusted_content=untrusted,
                                         origine="orchestratore"))
        log.info("strumento", tool=r.tool, esito=r.outcome.value,
                 stadio=r.stage, motivo=r.detail[:80], ms=round(r.duration_ms),
                 web=untrusted or None)
        # Gli slot si aggiornano qui e in nessun altro posto: un secondo
        # scrittore renderebbe impossibile sapere perche' "la" si riferisce a
        # quella cosa li'. Solo sugli esiti riusciti — vedi `slots.osserva`.
        SLOTS.osserva(call, r)
        return r

    def conferma_serve(nome: str) -> bool:
        # M6: non solo il tier. `schedule_reminder` e' T1 ma chiede conferma
        # della data: se l'orchestratore non lo sapesse, non passerebbe da
        # ATTESA_CONFERMA e la domanda non verrebbe pronunciata.
        spec = reg.get(nome)
        return spec is not None and serve_conferma(spec)

    def al_risveglio() -> None:
        """Due cose nello stesso istante: fissare "questa finestra" per gli
        strumenti, e scriverla negli slot perche' il modello possa nominarla.

        Sono due lettori diversi dello stesso fatto. Tenerli in due momenti
        diversi vorrebbe dire che `move_window_to_monitor` agisce su una
        finestra e la frase pronunciata ne nomina un'altra.
        """
        hwnd = finestre.cattura_riferimento()
        if hwnd is None:
            return
        try:
            info = finestre.info(hwnd)
        except Exception:                          # noqa: BLE001
            return
        if info is not None:
            SLOTS.vista_finestra(info.titolo, info.processo)

    azioni = Azioni(
        decidi=lambda testo, storia: router.decidi(testo, storia, SLOTS.blocco()),
        esegui=esegui,
        descrivi=descrivi_sequenza,
        richiede_conferma=conferma_serve,
        # "Questa finestra" si fissa qui, all'ingresso in ascolto. Il
        # cablaggio sta in questo file e non nell'orchestratore perche' e'
        # l'unico posto che conosce sia il ciclo di vita del turno sia gli
        # strumenti: l'orchestratore non deve sapere che esistono le
        # finestre, e `finestre.py` non deve sapere che esiste un turno.
        al_risveglio=al_risveglio,
        domanda_conferma=domanda_conferma,
    )

    # -- il ramo conoscenza ------------------------------------------------
    #
    # `Consulente` riceve `esegui`, cioe' lo stesso callable che usa
    # l'orchestratore: ricerche e letture attraversano il broker come
    # qualunque altra azione. Non e' pignoleria — il percorso che porta
    # dentro il testo non fidato e' proprio quello che non puo' permettersi
    # di saltare la validazione e l'audit.
    consulente = Consulente(esegui)
    filler = Filler()

    def query_web(decisione) -> str | None:
        """La query di questo turno, se c'e'.

        Guarda TUTTE le azioni del piano e non solo la prima: un modello che
        risponde `[open_url, web_search]` ha comunque chiesto delle fonti, e
        trattare quel turno come un turno normale significherebbe eseguire
        `open_url` e poi la ricerca — cioe' agire prima di sapere.
        """
        for c in getattr(decisione, "calls", ()):
            if c.get("tool") == "web_search":
                return (c.get("query") or "").strip() or None
            if c.get("tool") == "web_fetch":
                return (c.get("url") or "").strip() or None
        return None

    conoscenza = Conoscenza(query_web=query_web,
                            consulta=consulente.consulta,
                            filler=filler.prossimo)

    return azioni, conoscenza, {"registry": reg, "audit": audit, "broker": broker,
                                "router": router, "libreria": libreria,
                                "consulente": consulente}


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

    azioni, conoscenza, pezzi = costruisci_azioni(opz, log, riporta, chiedi_conferma)
    player.start()

    # La memoria riassume con lo STESSO modello che conversa, a temperatura
    # 0,1: un riassunto non deve essere creativo, deve essere lo stesso ogni
    # volta. Il client e' quello gia' caricato in VRAM — un secondo modello
    # per riassumere costerebbe un secondo caricamento e un secondo picco.
    memoria = Memoria(system=SYSTEM, riassumi=llm.riassumi)
    riporta(f"memoria      : finestra {memoria.finestra} messaggi, "
            f"riassunto al {int(memoria.soglia * 100)}% del contesto")

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
        memoria=memoria,
        conoscenza=conoscenza,
        contesto=SLOTS.blocco,
    )
    orch = Orchestrator(deps, on_transition=osserva)

    # M6 — scheduler e casa DOPO l'orchestratore, e lo scheduler per ULTIMO.
    # I promemoria scaduti mentre il PC era spento partono appena lo
    # scheduler si avvia: chi li riceve deve esistere gia'. Vedi la nota in
    # testa a `tools/scheduler.py`.
    pian, casa = (None, None)
    if azioni is not None:
        pian, casa = costruisci_integrazioni(orch, pezzi.get("audit"), log, riporta)

    avvio = time.perf_counter() - t0
    riporta(f"pronti in {avvio:.1f} s")

    return Sistema(orchestrator=orch, player=player, detector=det,
                   memoria=memoria, pianificatore=pian, casa=casa,
                   avvio_s=avvio, **pezzi)


def costruisci_integrazioni(orch, audit, log, riporta: Callable[[str], None]):
    """Scheduler, consegne e Home Assistant. Ritorna (pianificatore, client).

    Separata da `costruisci_sistema` perche' e' la parte che non carica
    modelli: si prova senza microfono ne' VRAM.
    """
    from metis.core import tempo
    from metis.tools import home_assistant, posta
    from metis.tools import scheduler as sch

    consegne = Consegne(orch, audit, log)
    sch.imposta_consegna(sch.PROMEMORIA, consegne.promemoria)
    sch.imposta_consegna(sch.EMAIL, consegne.email)
    sch.imposta_consegna(sch.SPEGNI, consegne.spegni)

    casa = home_assistant.avvia_da_segreti()
    for a in home_assistant.carica()[1]:
        log.warning("home assistant", configurazione=a)
    riporta("casa         : " + ("connessione in corso" if casa is not None
                                 else "non configurata (scripts/setup_secrets.py)"))
    riporta(f"posta        : {len(posta.allowlist())} destinatari autorizzati")

    # Le notifiche sono la via dei promemoria quando Metis non puo' parlare
    # — kill switch, audio occupato. Se Windows le ha spente, i promemoria
    # arrivano solo a voce, e va detto adesso, non scoperto quando un
    # promemoria si perde. Metis non cambia l'impostazione: la riferisce.
    from metis.tools import notify

    if notify.abilitate() is False:
        riporta("notifiche   : DISATTIVATE in Windows — i promemoria arriveranno "
                "solo a voce (Impostazioni > Sistema > Notifiche)")
        log.warning("notifiche disattivate", impostazione="ToastEnabled=0")

    pian = sch.pianificatore()
    try:
        pian.avvia()
        voci = pian.voci()
        prossimo = f", il prossimo {tempo.in_parole(voci[0].quando)}" if voci else ""
        riporta(f"promemoria   : {len(voci)} in programma{prossimo}")
    except Exception as exc:                       # noqa: BLE001
        log.error("scheduler", errore=f"{type(exc).__name__}: {exc}")
        riporta(f"promemoria   : NON disponibili ({type(exc).__name__})")
    return pian, casa


def _ora_prevista(dati: dict) -> str:
    from datetime import datetime

    from metis.core import tempo

    try:
        return tempo.in_parole(datetime.strptime(dati.get("previsto", ""),
                                                 tempo.FORMATO))
    except ValueError:
        return "un orario che non ricordo"


class Consegne:
    """Cosa succede quando un job scatta. Una classe e non tre closure
    perche' i test la usano senza costruire l'applicazione intera.

    I job scattano fuori da un turno e fuori dal broker: la conferma c'e'
    stata alla creazione. L'audit pero' deve sapere che l'effetto e' avvenuto
    ADESSO — la riga della creazione dice "programmata", queste dicono
    "partita".
    """

    def __init__(self, orch, audit, log=None):
        self.orch = orch
        self.audit = audit
        self.log = log

    def _registra(self, tool, tier, args, esito, stadio, dettaglio, confermata):
        from metis.security.audit import Entry

        if self.audit is None:
            return
        try:
            self.audit.record(Entry(tool=tool, tier=tier, args=args, outcome=esito,
                                    stage=stadio, detail=dettaglio,
                                    confirmed=confermata))
        except Exception:                          # noqa: BLE001
            pass

    def promemoria(self, dati: dict) -> None:
        from metis.tools import notify

        testo = dati.get("testo", "")
        # La notifica subito, la voce quando Metis e' libero: vedi
        # `Orchestrator.annuncia`.
        if dati.get("in_ritardo"):
            # Scaduto a PC spento, oltre l'ora di tolleranza. Arriva lo stesso
            # — un promemoria in ritardo e' meglio di uno sparito — ma dice per
            # quando era: "chiamare il commercialista" detto alle 11 di sera
            # ha un significato diverso se era per le 17.
            quando = _ora_prevista(dati)
            notify.mostra("Promemoria in ritardo", f"{testo} (era per {quando})")
            self.orch.annuncia(f"Promemoria in ritardo, era per {quando}: {testo}.")
            return
        notify.mostra("Promemoria", testo)
        self.orch.annuncia(f"Promemoria: {testo}.")

    def email(self, dati: dict) -> None:
        from metis.security.audit import Outcome, Tier
        from metis.tools import notify, posta

        to, subject = dati.get("to", ""), dati.get("subject", "")
        args = {"to": to, "subject": subject, "body": dati.get("body", "")}
        if dati.get("in_ritardo"):
            # NON si manda. L'utente ha confermato un invio alle 9, non alle 14:
            # "ricordati la riunione delle 10" spedito a mezzogiorno e' un'altra
            # email. Si dice che non e' partita, e perche'; se la vuole ancora,
            # la chiede di nuovo.
            quando = _ora_prevista(dati)
            motivo = f"il PC era spento all'orario previsto ({quando})"
            self._registra("schedule_email", Tier.T3, args, Outcome.DENIED,
                           "invio_programmato", f"non inviata: {motivo}", True)
            notify.mostra("Email NON inviata", f"A {to}: {motivo}.")
            self.orch.annuncia(f"L'email programmata a {to} non e' partita: "
                               f"{motivo}. Se la vuole ancora, me lo chieda.")
            return
        try:
            posta.invia(to, subject, dati.get("body", ""))
        except Exception as exc:                   # noqa: BLE001
            # Non partita: lo si dice in tutti i modi possibili, perche'
            # l'utente conta che sia partita e non e' davanti al PC.
            motivo = str(exc)[:160]
            self._registra("schedule_email", Tier.T3, args, Outcome.ERROR,
                           "invio_programmato", motivo, True)
            notify.mostra("Email NON inviata", f"A {to}: {motivo}")
            self.orch.annuncia(f"Attenzione: l'email programmata a {to} "
                               f"non e' partita. {motivo}")
            return
        self._registra("schedule_email", Tier.T3, args, Outcome.OK,
                       "invio_programmato",
                       f"inviata, confermata il {dati.get('confermata_il', '?')}",
                       True)
        notify.mostra("Email inviata", f"A {to}: {subject}")

    def spegni(self, dati: dict) -> None:
        from metis.security.audit import Outcome, Tier
        from metis.tools import home_assistant, notify

        r = home_assistant.spegni_per_sicurezza(dati)
        nome = r.get("nome", dati.get("dispositivo", ""))
        ok = r.get("esito") == "spento"
        # T1 e non T3 nel log. Spegnere per un limite di sicurezza riduce il
        # rischio invece di aggiungerne, e non c'e' nessuno a cui chiedere
        # conferma. Registrarlo come T3 non confermata falserebbe NFR-9, che
        # esiste per contare le azioni rischiose partite senza consenso.
        dettaglio = r.get("esito", "")
        if not ok:
            dettaglio += f": {r.get('motivo', '')}"
        self._registra("spegnimento_sicurezza", Tier.T1,
                       {"dispositivo": dati.get("dispositivo", ""),
                        "tentativo": dati.get("tentativo", 0)},
                       Outcome.OK if ok else Outcome.ERROR, "sicurezza",
                       dettaglio, None)
        if ok:
            notify.mostra("Spegnimento di sicurezza",
                          f"Ho spento {nome}: era in funzione da troppo tempo.")
            return
        coda = ("Riprovo fra un minuto." if r.get("riprova")
                else "Ho smesso di riprovare: va spento a mano.")
        notify.mostra("NON riesco a spegnere", f"{nome}. {coda}")
        self.orch.annuncia(f"Attenzione: non riesco a spegnere {nome}. {coda}")


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
