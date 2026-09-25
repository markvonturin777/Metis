"""Orchestratore M1 — sostituisce lo scheletro di M0.

Differenze rispetto a `skeleton.py`, che era sequenziale e usa-e-getta:

* lo stato e' esplicito e governato da `StateMachine`;
* i frame audio vanno a destinazioni diverse a seconda dello stato, ed e' li'
  che vivono half-duplex gating e barge-in;
* il TTS gira su un thread proprio, altrimenti non lo si potrebbe interrompere;
* la generazione LLM e' annullabile a meta'.

IL TURNO GIRA SU UN THREAD PROPRIO (corretto il 2026-09-21)
La prima versione chiamava `_process` in modo sincrono dentro `on_audio`.
Sembrava innocuo ed era invece fatale: mentre il turno elabora e parla,
`on_audio` non viene piu' chiamato, quindi il rilevatore di wake word non
riceve frame, quindi **il barge-in non puo' scattare**. La funzione che il
barge-in deve interrompere era proprio quella che ne impediva il rilevamento.

IL TOKEN DI ANNULLAMENTO E' PER TURNO, NON CONDIVISO
Un token unico da resettare a ogni turno ha una corsa: un annullamento che
arriva subito prima del `reset()` viene inghiottito. Ogni turno crea invece
il proprio token; il barge-in annulla quello corrente e basta. Niente reset,
niente corsa.

IL BARGE-IN RICHIEDE DI FERMARE TRE COSE, NON UNA
Dimenticarne una produce il bug piu' fastidioso di questa fase: Metis si
interrompe, tace un istante, e riparte da solo perche' la frase successiva era
gia' in coda. Le tre sono:

    1. l'audio in riproduzione        -> player.stop()
    2. la coda di riproduzione        -> svuotata dentro player.stop()
    3. lo stream di generazione LLM   -> CancelToken

Il test `test_barge_in_ferma_tutte_e_tre` verifica proprio questo.

M5 — IL TURNO SI PUO' CONTAMINARE, E QUANDO SUCCEDE NON TORNA PULITO
Dal momento in cui nel turno entra testo recuperato dal web, ogni chiamata a
uno strumento parte con `untrusted=True` e il broker rifiuta T2 e T3. La
bandiera vive nel turno e non nell'istanza, perche' un attributo sopravvissuto
al turno renderebbe contaminati anche quelli dopo — che non lo sono — e Metis
smetterebbe di poter agire per il resto della sessione dopo una sola ricerca.

E' la difesa 3 del piano, l'unica delle tre che non dipende da come il modello
interpreta un prompt. Le altre due stanno nei delimitatori
(`llm/grounding.py`) e nel system prompt.

M5 — IL RIASSUNTO SI FA IN DORMIENTE
`tick()` gira a 2 Hz e non e' solo un contatore di timeout: e' l'unico punto
del sistema che si accorge che **nessuno sta aspettando**. Riassumere costa
2-3 secondi, e farlo su un turno a caso e' il tipo di latenza peggiore —
quella di cui l'utente non riesce a indovinare la causa.

M6 — I PROMEMORIA NON INTERROMPONO
Un promemoria che scatta mentre l'utente sta parlando con Metis non si
pronuncia in mezzo alla conversazione: si accoda, e parte al primo passaggio
in DORMIENTE. E' la stessa regola del riassunto, per la stessa ragione — solo
`tick()` sa quando nessuno sta aspettando. La notifica desktop invece parte
subito: e' silenziosa, e non ruba la parola a nessuno.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from metis.audio.capture import Block
from metis.audio.vad import Segment, SpeechSegmenter
from metis.core.errors import Categoria, messaggio
from metis.core.metrics import TurnMetrics
from metis.core.state_machine import Event, State, StateMachine, Transition
from metis.llm.client import CancelToken
from metis.memory.conversation import Memoria


@dataclass
class Conoscenza:
    """Il ramo "consultare le fonti". Assente = Metis sa solo cio' che ha nei pesi.

    Tre callable e nessun oggetto: l'orchestratore non impara cos'e' una
    ricerca, cos'e' una fonte e cosa siano i delimitatori. Sa che c'e' un
    momento in cui si dice qualcosa per non far aspettare in silenzio, uno in
    cui si va a leggere, e che da quel momento il turno e' contaminato.

    `query_web` riceve la Decisione del router e ritorna la query, oppure
    None se questo turno non richiede fonti. Una sola chiamata invece di un
    predicato piu' un estrattore: due funzioni che devono essere d'accordo
    fra loro sono due funzioni che prima o poi non lo sono.
    """

    query_web: Callable[[object], str | None]
    consulta: Callable[[str], object]            # query -> Contesto
    filler: Callable[[], str]


@dataclass
class Azioni:
    """Il ramo "strumenti" del turno. Assente = Metis sa solo conversare.

    Un solo campo opzionale in `Deps` invece di quattro sparsi: cosi'
    l'intera capacita' di agire sul mondo si accende e si spegne in un punto,
    e l'orchestratore non impara mai cos'e' un broker. Sa che qualcuno decide
    e qualcuno esegue; chi siano, e quali controlli applichino, non lo
    riguarda.
    """

    decidi: Callable[[str, list], object]      # testo -> Decisione
    # M5 — il secondo argomento e' `untrusted`: se in questo turno e' entrato
    # testo dal web. Non ha un default, ed e' voluto: chi scrive un nuovo
    # chiamante deve fermarsi a chiedersi cosa passare, invece di ereditare
    # un False che nessuno ha deciso.
    esegui: Callable[[dict, bool], object]     # (tool call, untrusted) -> Result
    descrivi: Callable[[list, object], str]    # Result[] -> frase da dire
    richiede_conferma: Callable[[str], bool]   # nome strumento -> bool
    # Chiamata ogni volta che Metis si mette in ascolto. Serve a fissare
    # "questa finestra" nell'istante in cui l'utente comincia a parlare,
    # invece che uno o due secondi dopo, quando il fuoco e' gia' cambiato —
    # spesso verso Metis stesso. L'orchestratore non sa cosa venga
    # catturato: sa solo che c'e' un momento in cui va fatto, e qual e'.
    al_risveglio: Callable[[], None] | None = None
    # M6 — la frase da dire mentre la finestra di conferma e' aperta: "Promemoria
    # per domani, giovedi' 24 settembre, alle 17. Confermo?". Vedi
    # `risposte.domanda_conferma`.
    domanda_conferma: Callable[[dict], str] | None = None


@dataclass
class Deps:
    """Dipendenze iniettate: in test si sostituiscono con finti."""

    wakeword: Callable[[np.ndarray], bool]
    stt: Callable[[np.ndarray], object]
    llm_stream: Callable[..., object]
    tts_synth: Callable[[str], object]
    player: object
    system_prompt: str = ""
    # Il rilevatore non riceve frame in TRASCRIZIONE ed ELABORAZIONE: al
    # rientro il suo buffer interno conterrebbe audio di prima della pausa,
    # incollato a quello di adesso. Si azzera prima di riprendere.
    wake_reset: Callable[[], None] | None = None
    on_error: Callable[[BaseException], None] | None = None
    # Il turno gira su un thread proprio e le sue transizioni finiscono nel
    # log insieme a quelle del thread audio. Senza l'identificativo, in una
    # sessione lunga non si capisce piu' quale riga appartenga a quale turno.
    on_turn_start: Callable[[str], None] | None = None
    on_turn_end: Callable[[TurnMetrics], None] | None = None
    azioni: "Azioni | None" = None
    # M5 — la memoria. Se manca se ne costruisce una dal solo system prompt,
    # cosi' i test di M1 continuano a funzionare senza sapere che esiste.
    memoria: "Memoria | None" = None
    conoscenza: "Conoscenza | None" = None
    # Il blocco [CONTESTO CORRENTE] degli slot, ricalcolato a ogni turno.
    # E' un callable e non una stringa perche' gli slot cambiano fra un turno
    # e l'altro, ed e' un callable qui e non un import perche' altrimenti
    # l'orchestratore saprebbe che esistono le finestre.
    contesto: Callable[[], str] | None = None


@dataclass
class Counters:
    wake_detections: int = 0
    barge_ins: int = 0
    frames_to_vad: int = 0
    frames_muted: int = 0
    frames_in_pausa: int = 0      # M7: scartati con l'ascolto in pausa
    turns: int = 0
    discarded: int = 0
    errors: int = 0
    tools_ok: int = 0
    tools_denied: int = 0
    cancel_latency_ms: list[float] = field(default_factory=list)
    # M5
    ricerche: int = 0
    ricerche_degradate: int = 0
    riassunti: int = 0
    filler_ms: list[float] = field(default_factory=list)
    web_ms: list[float] = field(default_factory=list)
    # M6
    annunci: int = 0
    annunci_rimandati: int = 0


class Orchestrator:
    def __init__(self, deps: Deps, on_transition: Callable[[Transition], None] | None = None):
        self.d = deps
        self.sm = StateMachine(on_transition=on_transition)
        self.seg = SpeechSegmenter()
        # Un token PER TURNO: vedi la nota in testa al modulo.
        self._cancel: CancelToken | None = None
        self.counters = Counters()
        self.mem = deps.memoria if deps.memoria is not None else Memoria(
            system=deps.system_prompt)
        self._worker: threading.Thread | None = None
        self._riassunto: threading.Thread | None = None
        # M6 — le frasi che nessuno ha chiesto: promemoria scaduti, email
        # partite. Aspettano qui finche' Metis non e' libero. Vedi `annuncia`.
        self._annunci: deque[str] = deque()
        self._annuncio: threading.Thread | None = None
        self._lock = threading.Lock()
        self._wake_gap = False        # il rilevatore ha saltato dei frame
        self._in_pausa = False        # M7: vedi `pausa`
        self.synchronous = False      # solo nei test: evita i thread

    @property
    def history(self) -> list[dict]:
        """La conversazione come la vede il modello, slot compresi.

        Resta una proprieta' e non un attributo perche' da M5 la cronologia
        non e' piu' una lista che si appende: e' una finestra scorrevole con
        un riassunto davanti, e chi la legge deve vedere quella — non i
        messaggi grezzi, che sono un dettaglio della memoria.
        """
        return self.mem.messaggi(slot=self._contesto())

    def _contesto(self) -> str:
        """Il blocco degli slot. Non solleva: e' contorno, non sostanza."""
        if self.d.contesto is None:
            return ""
        try:
            return self.d.contesto() or ""
        except Exception:                        # noqa: BLE001
            self.counters.errors += 1
            return ""

    # -- ingresso audio ----------------------------------------------------

    def on_audio(self, block: Block) -> None:
        """Instrada un blocco audio in base allo stato.

        E' il cuore di M1: le due righe che decidono chi riceve i frame sono
        l'intera strategia anti-eco.
        """
        st = self.sm.state

        # M7 — in pausa il microfono non arriva a nessuno, nemmeno al
        # rilevatore di wake word: e' l'unico punto in cui lo si puo'
        # garantire, perche' e' l'unica porta da cui entrano i frame.
        if self._in_pausa:
            self.counters.frames_in_pausa += 1
            self._wake_gap = True
            return

        # Il rilevatore di wake word riceve anche durante PARLATO: e' il
        # barge-in. Cerca un pattern specifico, quindi l'eco degli
        # altoparlanti non lo attiva come farebbe con un VAD generico.
        if self.sm.wake_active:
            if self._wake_gap:
                self._wake_gap = False
                if self.d.wake_reset is not None:
                    self.d.wake_reset()
            if self.d.wakeword(block.pcm):
                self.counters.wake_detections += 1
                self._on_wake_word()
                return
        else:
            self._wake_gap = True

        # Half-duplex: in PARLATO, DORMIENTE e INTERROTTO i frame NON
        # raggiungono VAD e STT. Lo stream resta aperto, i blocchi si
        # scartano: riaprire il device costerebbe 50-200 ms e a volte fallisce.
        if self.sm.stt_muted:
            self.counters.frames_muted += 1
            return

        self.counters.frames_to_vad += 1
        segment = self.seg.feed(block)

        if segment is not None and st is State.TRASCRIZIONE:
            self.sm.fire(Event.SPEECH_END)
            self._start_turn(segment)
        elif segment is None and st is State.IN_ASCOLTO and self.seg._active:
            self.sm.fire(Event.SPEECH_START)

    def _on_wake_word(self) -> None:
        self._attiva(Event.WAKE_WORD)

    def on_ptt(self) -> None:
        """Pressione del push-to-talk. Fa le stesse cose della wake word.

        In V1.0, con la wake word spenta, questo e' l'UNICO modo di
        interrompere Metis mentre parla. Il kill switch zittisce e riporta a
        DORMIENTE: e' "taci", non "taci e ascoltami".
        """
        self._attiva(Event.PTT)

    def _attiva(self, evento: Event) -> None:
        """Wake word e push-to-talk sono due porte sullo stesso corridoio.

        Tenere due implementazioni separate vorrebbe dire che un giorno il
        barge-in da tastiera dimentica una delle tre cose da fermare, e il
        difetto salterebbe fuori solo in uno dei due modi di usare Metis.
        """
        st = self.sm.state
        # M5 — RICERCA_WEB e' nell'elenco perche' li' il filler sta suonando.
        # Senza, il PTT premuto durante una ricerca lenta faceva transire la
        # macchina in INTERROTTO e lasciava il filler in riproduzione: Metis
        # continuava a dire "un momento, consulto le fonti" a un utente che
        # aveva appena chiesto di smettere. L'elenco va tenuto uguale a
        # STT_MUTED meno DORMIENTE: sono gli stati in cui esce audio.
        if self._in_pausa and st not in (State.PARLATO, State.GENERAZIONE,
                                         State.RICERCA_WEB):
            # In pausa il PTT resta un modo per zittire Metis, non per
            # riaprire il microfono: una pausa che si toglie con un tasto
            # premuto per sbaglio non e' una pausa.
            return
        if st in (State.PARLATO, State.GENERAZIONE, State.RICERCA_WEB):
            t0 = time.perf_counter()
            self.sm.fire(evento)                   # -> INTERROTTO
            self._stop_everything()
            self.counters.barge_ins += 1
            self.counters.cancel_latency_ms.append((time.perf_counter() - t0) * 1000)
            self.sm.fire(Event.TTS_STOPPED)        # -> IN_ASCOLTO
            self.seg.reset()
        elif self.sm.fire(evento) is not st:
            # DORMIENTE -> IN_ASCOLTO, oppure il PTT che chiude l'ascolto.
            self.seg.reset()
            # M6: in DORMIENTE puo' esserci un annuncio in riproduzione — un
            # promemoria. Il microfono si sta aprendo: se l'annuncio
            # continuasse, VAD e STT sentirebbero Metis. Si ferma. Su un
            # player gia' fermo non costa niente.
            if st is State.DORMIENTE:
                self.d.player.stop()

        if self.sm.state is State.IN_ASCOLTO:
            self._risveglio()

    def _risveglio(self) -> None:
        """Il gancio di M4, isolato perche' gira sul thread audio.

        Un'eccezione qui fermerebbe la cattura, cioe' il microfono, per un
        dettaglio il cui peggior esito e' un rifiuto educato piu' tardi
        ("non so quale finestra intendi"). Si assorbe e si conta.
        """
        a = self.d.azioni
        if a is None or a.al_risveglio is None:
            return
        try:
            a.al_risveglio()
        except Exception:                        # noqa: BLE001
            self.counters.errors += 1

    def _stop_everything(self) -> None:
        """Le tre cose da fermare. Ometterne una e' il bug classico."""
        with self._lock:
            tok = self._cancel
        if tok is not None:
            tok.cancel()              # 1+3: lo stream si ferma al prossimo token
        self.d.player.stop()          # 2: audio corrente + coda di riproduzione

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancel is not None and self._cancel.cancelled

    # -- avvio del turno ---------------------------------------------------

    def _start_turn(self, segment: Segment) -> None:
        """Il turno gira su un thread proprio: altrimenti `on_audio` resta
        bloccato e il barge-in non puo' essere rilevato."""
        if self.synchronous:
            self._run_turn(segment)
            return
        self._worker = threading.Thread(
            target=self._run_turn, args=(segment,), daemon=True, name="metis-turn"
        )
        self._worker.start()

    def _run_turn(self, segment: Segment) -> None:
        """Guscio del turno. Ollama va giu', il modello TTS manca un file, la
        scheda audio sparisce: sul thread del turno un'eccezione passerebbe
        inosservata e lascerebbe la macchina appesa fino al timeout, cioe' 30
        secondi di Metis muto. Si chiude invece in ERRORE, che dura 5 s.
        """
        try:
            self._process(segment)
        except Exception as exc:                 # noqa: BLE001 - qui si cattura tutto
            self.counters.errors += 1
            self._stop_everything()
            if self.d.on_error is not None:
                self.d.on_error(exc)
            self._dichiara_errore(exc)

    def _dichiara_errore(self, exc: BaseException) -> None:
        """M7 — il turno fallito DICE perche', in persona.

        Fino a M6 finiva in ERRORE e Metis taceva: con Ollama spento l'utente
        parlava e non succedeva niente, e un assistente che smette di
        rispondere senza dire perche' sembra rotto anche quando si riprendera'
        da solo. Adesso la frase della matrice degli errori si pronuncia. MAI
        il testo dell'eccezione: quello e' andato nel log, con `on_error`.

        La sequenza e' ERRORE -> PARLATO -> IN_ASCOLTO. Si passa a PARLATO
        PRIMA di accodare l'audio: ERRORE non sta in STT_MUTED, e la regola
        di M5 dice che dove esce audio il microfono e' chiuso.

        Se la sintesi stessa e' il guasto, non si dice niente e si lascia
        scadere ERRORE: c'e' poco da fare quando e' la voce che manca.
        """
        # Da RICERCA_WEB, FAILED porta in GENERAZIONE e serve un secondo
        # FAILED per arrivare in ERRORE: si insiste finche' ci si arriva.
        for _ in range(3):
            if self.sm.state is State.ERRORE:
                break
            if self.sm.fire(Event.FAILED) is not State.ERRORE and \
                    self.sm.state not in (State.GENERAZIONE, State.PARLATO):
                break
        if self.sm.state is not State.ERRORE:
            return

        frase = messaggio(exc)
        if not frase:
            return
        try:
            pcm = self.d.tts_synth(frase).pcm
        except Exception:                        # noqa: BLE001
            return
        self.mem.aggiungi("assistant", frase)
        self.sm.fire(Event.DONE)                 # ERRORE -> PARLATO
        self.d.player.enqueue(pcm)
        self.d.player.wait_drained()
        if self.sm.state is State.PARLATO:
            self.sm.fire(Event.PLAYBACK_DONE)

    # -- turno -------------------------------------------------------------

    def _process(self, segment: Segment) -> None:
        m = TurnMetrics(
            turn_id=uuid.uuid4().hex[:8],
            t_speech_end=segment.t_speech_end,
            t_endpoint=segment.t_endpoint,
            audio_s=segment.duration_s,
        )
        if self.d.on_turn_start is not None:
            self.d.on_turn_start(m.turn_id)
        tr = self.d.stt(segment.pcm)
        m.t_stt_done = time.perf_counter()
        m.transcript = getattr(tr, "text", "")

        if not m.transcript or getattr(tr, "suspect", False):
            self.counters.discarded += 1
            self.sm.fire(Event.NO_SPEECH)
            return

        self.mem.aggiungi("user", m.transcript)
        slot = self._contesto()

        # Strumento, fonti o conversazione? Il router decide, e nel dubbio
        # sceglie la conversazione: rispondere a parole non fa danni, agire
        # quando non era richiesto sì.
        if self.d.azioni is not None:
            decisione = self.d.azioni.decidi(m.transcript, self.history)
            # Le fonti si guardano PRIMA degli strumenti. Una decisione che
            # contiene una ricerca e' un turno di conoscenza anche se
            # contiene altro: cio' che verrebbe dopo sarebbe deciso da una
            # pagina che ancora non e' stata letta. Vedi `_percorso_web`.
            query = self._query_web(decisione)
            if query:
                return self._percorso_web(m, decisione, query, slot)
            if getattr(decisione, "e_strumento", False):
                return self._esegui_strumento(m, decisione)

        self.sm.fire(Event.INTENT_CHAT)

        # Token NUOVO per questo turno. Se un barge-in e' gia' arrivato su un
        # token precedente, non contamina questo; e se arriva adesso, non puo'
        # essere inghiottito da un reset.
        with self._lock:
            if self._cancel is not None and self._cancel.cancelled:
                return                      # annullato prima ancora di partire
            tok = CancelToken()
            self._cancel = tok

        messaggi = self.mem.messaggi(slot=slot)
        m.extra["contesto_token"] = self.mem.conteggio(slot).totale
        gm = self._genera(m, messaggi, tok)

        if tok.cancelled:
            return                                   # gia' in IN_ASCOLTO

        if gm is not None:
            # M7: anche il throughput. Mancava da M1 — lo copiava solo lo
            # skeleton — e il cruscotto mostrava 0 tok/s a ogni turno.
            m.tokens, m.tok_per_s = gm.tokens, gm.tok_per_s
            m.reply = gm.text
            self.mem.aggiungi("assistant", gm.text)
        self.counters.turns += 1
        m.append_to_log()
        if self.d.on_turn_end is not None:
            self.d.on_turn_end(m)

        self.d.player.wait_drained()

        # Solo se questo turno e' ancora quello corrente. Durante l'attesa
        # puo' essere arrivato un barge-in e l'utente puo' aver gia' iniziato
        # un turno nuovo: PLAYBACK_DONE sparato adesso riporterebbe a
        # IN_ASCOLTO una macchina che sta gia' parlando per il turno dopo, e
        # il microfono riaprirebbe sull'eco.
        with self._lock:
            corrente = self._cancel is tok and not tok.cancelled
        if corrente:
            self.sm.fire(Event.PLAYBACK_DONE)

    def _genera(self, m: TurnMetrics, messaggi: list[dict], tok: CancelToken):
        """Streaming frase per frase verso il TTS. La meta' comune ai due
        percorsi di conversazione, quello a memoria e quello fondato.

        Estratta da `_process` quando e' arrivato il secondo chiamante: le
        due copie avrebbero divergiuto sulla riga che fa scattare
        FIRST_AUDIO, e il sintomo sarebbe stato "sul percorso web il
        microfono si riapre mentre Metis parla" — cioe' l'eco, di nuovo.
        """
        m.t_llm_sent = time.perf_counter()
        first = True
        gm = None
        for chunk, gm in self.d.llm_stream(messaggi, cancel=tok):
            if tok.cancelled:
                break
            syn = self.d.tts_synth(chunk)
            self.d.player.enqueue(syn.pcm)
            if first:
                m.t_ttft = m.t_llm_sent + (getattr(gm, "ttft_ms", 0) or 0) / 1000.0
                m.t_first_chunk = m.t_ttft
                m.t_tts_done = time.perf_counter()
                m.t_first_audio = time.perf_counter()
                self.sm.fire(Event.FIRST_AUDIO)     # -> PARLATO
                first = False
        return gm

    # -- ramo conoscenza ---------------------------------------------------

    def _query_web(self, decisione) -> str | None:
        """La query di questo turno, o None. Non solleva.

        Un difetto qui non deve impedire di rispondere: nel peggiore dei casi
        si perde la ricerca e si risponde a parole, che e' il comportamento
        innocuo.
        """
        if self.d.conoscenza is None:
            return None
        try:
            return self.d.conoscenza.query_web(decisione)
        except Exception:                        # noqa: BLE001
            self.counters.errors += 1
            return None

    def _percorso_web(self, m: TurnMetrics, decisione, query: str,
                      slot: str) -> None:
        """Filler, fonti, risposta fondata. Il turno da qui e' contaminato.

        LE ALTRE AZIONI DEL PIANO NON SI ESEGUONO
        Se il router ha prodotto `[web_search, press_hotkey]`, la seconda non
        parte. Non perche' il broker la rifiuterebbe — la rifiuterebbe, ed e'
        la difesa 3 — ma per una ragione che viene prima: quell'azione e'
        stata decisa **da una frase**, e fra la decisione e l'esecuzione si e'
        messo di mezzo il testo di una pagina. Eseguirla significherebbe dare
        l'ultima parola a chi ha scritto la pagina. Si scarta e si conta.

        L'ordine delle due righe che contano — filler prima, ricerca dopo —
        e' il requisito dei 300 ms. Invertirle non romperebbe niente e
        renderebbe il filler inutile, che e' il modo in cui un requisito di
        interazione muore senza che nessun test se ne accorga.
        """
        k = self.d.conoscenza
        self.sm.fire(Event.INTENT_WEB)                # -> RICERCA_WEB
        self.counters.ricerche += 1

        t0 = time.perf_counter()
        try:
            self.d.player.enqueue(self.d.tts_synth(k.filler()).pcm)
        except Exception:                            # noqa: BLE001
            # Un filler che non si sintetizza non giustifica la perdita del
            # turno: si tace e si cerca lo stesso.
            self.counters.errors += 1
        m.extra["filler_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self.counters.filler_ms.append((time.perf_counter() - t0) * 1000)

        scartate = [c for c in getattr(decisione, "calls", ())
                    if c.get("tool") not in ("web_search", "web_fetch")]
        if scartate:
            m.extra["azioni_scartate"] = "+".join(c.get("tool", "?") for c in scartate)

        ctx = k.consulta(query)
        m.extra["fonti"] = len(getattr(ctx, "fonti", ()))
        m.extra["web_ms"] = round(getattr(ctx, "ms", 0.0))
        self.counters.web_ms.append(getattr(ctx, "ms", 0.0))

        # Da qui il turno e' contaminato, anche se le fonti non sono
        # arrivate: gli estratti della ricerca sono gia' contenuto esterno.
        untrusted = bool(getattr(ctx, "contaminato", True))
        m.extra["untrusted"] = untrusted

        if not getattr(ctx, "ok", False):
            # DEGRADAZIONE DICHIARATA. Non si genera niente: se si passasse
            # comunque dal modello, quello risponderebbe a memoria, che e' lo
            # scenario che questo progetto esiste per evitare.
            self.counters.ricerche_degradate += 1
            self.sm.fire(Event.FAILED)                # -> GENERAZIONE
            frase = getattr(ctx, "motivo", "") or messaggio(Categoria.RETE)
            return self._chiudi_parlando(m, frase)

        with self._lock:
            if self._cancel is not None and self._cancel.cancelled:
                return
            tok = CancelToken()
            self._cancel = tok

        self.sm.fire(Event.CONTEXT_READY)             # -> GENERAZIONE
        messaggi = self.mem.messaggi(slot=slot, domanda=ctx.messaggio(m.transcript))
        m.extra["contesto_token"] = self.mem.conteggio(
            slot, fonti=ctx.blocco()).totale
        m.extra["fonte"] = (ctx.citazioni() or [""])[0][:80]

        gm = self._genera(m, messaggi, tok)
        if tok.cancelled:
            return

        if gm is not None:
            # M7: anche il throughput. Mancava da M1 — lo copiava solo lo
            # skeleton — e il cruscotto mostrava 0 tok/s a ogni turno.
            m.tokens, m.tok_per_s = gm.tokens, gm.tok_per_s
            m.reply = gm.text
            # In memoria entra la RISPOSTA, mai le fonti. Vedi la nota in
            # testa a `llm/grounding.py`: un testo ostile che restasse in
            # cronologia continuerebbe a insistere per tutti i turni
            # successivi, e quelli non sarebbero piu' marcati contaminati.
            self.mem.aggiungi("assistant", gm.text)

        self.counters.turns += 1
        m.append_to_log()
        if self.d.on_turn_end is not None:
            self.d.on_turn_end(m)
        self.d.player.wait_drained()
        with self._lock:
            corrente = self._cancel is tok and not tok.cancelled
        if corrente:
            self.sm.fire(Event.PLAYBACK_DONE)

    def _chiudi_parlando(self, m: TurnMetrics, frase: str) -> None:
        """Dire una frase sola e chiudere il turno. Usato dalla degradazione."""
        m.reply = frase
        self.mem.aggiungi("assistant", frase)
        self.d.player.enqueue(self.d.tts_synth(frase).pcm)
        m.t_first_audio = time.perf_counter()
        if self.sm.state is not State.PARLATO:
            self.sm.fire(Event.FIRST_AUDIO)
        self.counters.turns += 1
        m.append_to_log()
        if self.d.on_turn_end is not None:
            self.d.on_turn_end(m)
        self.d.player.wait_drained()
        self.sm.fire(Event.PLAYBACK_DONE)

    # -- ramo strumenti ----------------------------------------------------

    def _esegui_strumento(self, m: TurnMetrics, decisione) -> None:
        """Esegue le tool call del turno, in ordine, e ne pronuncia l'esito.

        Gli stati sono quelli veri della macchina, conferma compresa: in M2
        la conferma era una domanda da console, in M3 e' diventata una
        finestra, e la sequenza di stati non e' cambiata.

        M4 — LA SEQUENZA SI FERMA AL PRIMO RIFIUTO
        "Metti Chrome sull'altro schermo e massimizzala" sono due azioni, e
        se la prima viene negata la seconda non ha piu' senso: massimizzare
        una finestra rimasta dov'era non e' meta' del lavoro, e' un'altra
        cosa. Proseguire darebbe anche il risultato peggiore possibile per
        chi ascolta — un "fatto" parziale che sembra un successo.

        Vale anche per l'interruzione: se l'utente parla sopra a Metis fra
        la prima e la seconda azione, la seconda non parte.
        """
        a = self.d.azioni
        self.sm.fire(Event.INTENT_KNOWN)              # -> ESECUZIONE

        risultati = []
        # M5 — la bandiera vive nel turno. Una volta alzata non si abbassa:
        # se la seconda azione di un piano porta dentro del web, la terza
        # nasce in un turno contaminato anche se la prima non lo era.
        untrusted = False
        for call in decisione.calls:
            if self.cancelled:
                break
            nome = call.get("tool", "?")
            conferma = a.richiede_conferma(nome)
            if conferma:
                self.sm.fire(Event.NEEDS_CONFIRM)     # -> ATTESA_CONFERMA
                self._chiedi_a_voce(call)

            res = a.esegui(call, untrusted)
            untrusted = untrusted or nome in ("web_search", "web_fetch")

            if conferma:
                # CONFIRMED torna in ESECUZIONE, DENIED va dritto a PARLATO:
                # in entrambi i casi c'e' qualcosa da dire all'utente.
                self.sm.fire(Event.CONFIRMED if res.ok else Event.DENIED)

            risultati.append(res)
            if res.ok:
                self.counters.tools_ok += 1
            else:
                self.counters.tools_denied += 1
                break

        if not risultati:
            self.sm.fire(Event.NO_SPEECH)             # niente da dire
            return

        frase = a.descrivi(risultati, decisione.risposta)
        ultimo = risultati[-1]
        m.reply = frase
        # I nomi si prendono dalla decisione e non dai Result: un Result
        # nato da una chiamata malformata ha `tool` a None, e nel log
        # servirebbe sapere proprio cosa si era tentato.
        m.extra["tool"] = "+".join(c.get("tool", "?")
                                   for c in decisione.calls[:len(risultati)])
        m.extra["azioni"] = len(risultati)
        m.extra["esito"] = getattr(ultimo.outcome, "value", str(ultimo.outcome))
        if untrusted:
            m.extra["untrusted"] = True
        self.mem.aggiungi("assistant", frase)

        syn = self.d.tts_synth(frase)
        m.t_first_audio = time.perf_counter()
        self.d.player.enqueue(syn.pcm)
        if self.sm.state is not State.PARLATO:
            self.sm.fire(Event.DONE)                  # ESECUZIONE -> PARLATO

        self.counters.turns += 1
        m.append_to_log()
        if self.d.on_turn_end is not None:
            self.d.on_turn_end(m)

        self.d.player.wait_drained()
        self.sm.fire(Event.PLAYBACK_DONE)

    def _chiedi_a_voce(self, call: dict) -> None:
        """La domanda di conferma, pronunciata mentre la finestra e' aperta.

        Non blocca: il PCM va in coda e la finestra resta la sola via per
        rispondere. Non solleva: una sintesi fallita toglie la voce alla
        domanda, non la domanda — la finestra c'e' comunque.
        """
        a = self.d.azioni
        if a is None or a.domanda_conferma is None:
            return
        try:
            frase = a.domanda_conferma(call)
            if frase:
                self.d.player.enqueue(self.d.tts_synth(frase).pcm)
        except Exception:                        # noqa: BLE001
            self.counters.errors += 1

    # -- annunci: cio' che nessuno ha chiesto --------------------------------

    def annuncia(self, testo: str) -> None:
        """Accoda una frase da dire appena Metis e' libero. Thread-safe.

        Chiamata dallo scheduler, su un thread suo, quando scatta un
        promemoria. Non parla subito: vedi la nota su M6 in testa al modulo.
        """
        if not testo:
            return
        with self._lock:
            self._annunci.append(testo)

    def _forse_annuncia(self) -> None:
        """Da `tick()`: se Metis e' libero e c'e' qualcosa in coda, lo dice.

        Libero significa DORMIENTE, e nient'altro. In IN_ASCOLTO l'utente ha
        appena premuto il PTT e sta per parlare; in qualunque altro stato un
        turno e' in corso. In tutti quei casi l'annuncio aspetta, e si conta:
        se il numero cresce, i promemoria arrivano sistematicamente mentre
        l'utente parla, ed e' un'informazione.

        In DORMIENTE il microfono e' gia' chiuso, quindi l'annuncio non ha
        bisogno di cambiare stato: se l'utente preme il PTT mentre Metis sta
        annunciando, `_attiva` ferma il player prima di aprire il microfono.
        """
        with self._lock:
            if not self._annunci:
                return
            if self.sm.state is not State.DORMIENTE:
                self.counters.annunci_rimandati += 1
                return
            if self._annuncio is not None and self._annuncio.is_alive():
                return
            testo = self._annunci.popleft()

        def parla() -> None:
            try:
                self.d.player.enqueue(self.d.tts_synth(testo).pcm)
                self.counters.annunci += 1
            except Exception:                    # noqa: BLE001
                self.counters.errors += 1

        if self.synchronous:
            parla()
            return
        self._annuncio = threading.Thread(target=parla, daemon=True,
                                          name="metis-annuncio")
        self._annuncio.start()

    # -- manutenzione ------------------------------------------------------

    def panic(self) -> None:
        """Kill switch: silenzio immediato e ritorno a DORMIENTE.

        Non passa dalla tabella delle transizioni di proposito: deve
        funzionare da QUALUNQUE stato, compresi quelli in cui la macchina
        fosse bloccata. E' l'unica scorciatoia ammessa, e c'e' perche'
        l'utente deve poter zittire Metis senza dipendere dal fatto che la
        macchina a stati sia sana.
        """
        self._stop_everything()
        self.seg.reset()
        self.sm.reset()

    # -- M7: pausa dell'ascolto --------------------------------------------

    @property
    def in_pausa(self) -> bool:
        return self._in_pausa

    def pausa(self, attiva: bool) -> None:
        """Sospende wake word e VAD. Dalla tray: "Pausa ascolto".

        Diversa dal kill switch, e le due cose non vanno confuse. Il kill
        switch toglie a Metis le mani (T2/T3) e lo zittisce; la pausa gli
        toglie le orecchie e basta. Un turno gia' in corso finisce — la
        risposta a una domanda gia' fatta si da' — ma appena Metis
        tornerebbe ad ascoltare, torna invece a dormire (`tick`).

        Lo stream audio resta aperto: riaprirlo alla ripresa costerebbe
        50-200 ms e a volte fallisce, esattamente come nel half-duplex.
        """
        self._in_pausa = attiva
        if attiva:
            self._chiudi_ascolto()

    def _chiudi_ascolto(self) -> None:
        """Da IN_ASCOLTO o TRASCRIZIONE a DORMIENTE, passando dalla tabella
        delle transizioni (e quindi notificando la GUI), non da `sm.reset`."""
        if self.sm.state is State.TRASCRIZIONE:
            self.sm.fire(Event.NO_SPEECH)
        if self.sm.state is State.IN_ASCOLTO:
            self.seg.reset()
            self.sm.fire(Event.TIMEOUT)

    def tick(self) -> None:
        """Da chiamare ~2 Hz: timeout degli stati e manutenzione della memoria."""
        self.sm.check_timeout()
        if self._in_pausa:
            self._chiudi_ascolto()
        self._forse_annuncia()
        self._forse_riassumi()

    def _forse_riassumi(self) -> None:
        """Il riassunto, e solo quando nessuno sta aspettando.

        Tre condizioni, tutte necessarie:

            DORMIENTE        nessun turno in corso, nessuno in ascolto
            serve_riassunto  il contesto e' al 70% e c'e' roba da condensare
            nessun thread    non se ne avviano due

        Gira su un thread proprio anche qui: `tick()` e' chiamata dal ciclo
        audio, e due o tre secondi dentro `tick()` sono due o tre secondi in
        cui i blocchi del microfono si accumulano e poi si perdono.
        """
        if self.sm.state is not State.DORMIENTE:
            return
        if self._riassunto is not None and self._riassunto.is_alive():
            return
        slot = self._contesto()
        if not self.mem.serve_riassunto(slot):
            return

        def lavora() -> None:
            try:
                if self.mem.compatta(slot):
                    self.counters.riassunti += 1
            except Exception:                    # noqa: BLE001
                self.counters.errors += 1

        if self.synchronous:
            lavora()
            return
        self._riassunto = threading.Thread(target=lavora, daemon=True,
                                           name="metis-riassunto")
        self._riassunto.start()
