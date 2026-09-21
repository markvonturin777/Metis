"""Barge-in e half-duplex, verificati con finti al posto di audio e modelli.

Il barge-in e' la funzionalita' con piu' insidie di M1: fermare due cose su
tre produce un bug che si manifesta come "Metis riparte da solo" e che dal
vivo e' difficile da riprodurre.
"""
from dataclasses import dataclass, field
import numpy as np
import pytest

from metis.audio.capture import Block
from metis.core.orchestrator import Deps, Orchestrator
from metis.core.state_machine import Event, State


# --- finti -------------------------------------------------------------------

class FakePlayer:
    def __init__(self):
        self.queue = []
        self.stopped = 0
        self.drained = 0
    def enqueue(self, pcm): self.queue.append(pcm)
    def stop(self):
        self.stopped += 1
        self.queue.clear()          # LA meta' che si dimentica
    def wait_drained(self): self.drained += 1


@dataclass
class FakeTranscript:
    text: str = "ciao"
    suspect: bool = False


@dataclass
class FakeGen:
    ttft_ms: float = 100.0
    tokens: int = 10
    text: str = "risposta finta"


@dataclass
class FakeSynth:
    pcm: np.ndarray = field(default_factory=lambda: np.zeros(100, np.float32))


def blocco(rms=-20.0):
    return Block(np.zeros(512, np.float32), rms, rms)


def make(wake_on_call=None, n_chunks=3, text="ciao"):
    """wake_on_call: indice della chiamata in cui la wake word scatta."""
    stato = {"chiamate": 0}
    def wakeword(pcm):
        stato["chiamate"] += 1
        return wake_on_call is not None and stato["chiamate"] == wake_on_call
    def llm_stream(history, cancel=None, **kw):
        gm = FakeGen()
        for _ in range(n_chunks):
            if cancel is not None and cancel.cancelled:
                return
            yield "frase di prova abbastanza lunga.", gm
    player = FakePlayer()
    d = Deps(wakeword=wakeword,
             stt=lambda pcm: FakeTranscript(text),
             llm_stream=llm_stream,
             tts_synth=lambda t: FakeSynth(),
             player=player)
    o = Orchestrator(d)
    o.synchronous = True      # niente thread nei test: deterministico
    return o, player


# --- half-duplex -------------------------------------------------------------

def test_in_parlato_i_frame_non_arrivano_al_vad():
    """L1: e' qui che si rompe il loop di auto-innesco con gli altoparlanti."""
    o, _ = make()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    assert o.sm.state is State.PARLATO
    prima = o.counters.frames_to_vad
    for _ in range(50):
        o.on_audio(blocco())
    assert o.counters.frames_to_vad == prima      # nessuno passato
    assert o.counters.frames_muted >= 50


def test_in_ascolto_i_frame_arrivano_al_vad():
    o, _ = make()
    o.sm.fire(Event.WAKE_WORD)
    for _ in range(10):
        o.on_audio(blocco())
    assert o.counters.frames_to_vad == 10


# --- barge-in ----------------------------------------------------------------

def test_barge_in_ferma_tutte_e_tre():
    """Audio, coda e stream LLM. Ometterne una: Metis riparte da solo."""
    from metis.llm.client import CancelToken
    o, player = make(wake_on_call=1)
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    # Un turno in volo: nel sistema reale `_process` gira su un thread proprio
    # e ha gia' registrato il suo token. Qui lo si simula.
    o._cancel = CancelToken()
    player.queue.extend([1, 2, 3])          # frasi gia' accodate

    o.on_audio(blocco())                    # scatta la wake word

    assert player.stopped == 1, "l'audio non e' stato fermato"
    assert player.queue == [], "la coda non e' stata svuotata: riprendera' a parlare"
    assert o.cancelled, "lo stream LLM non e' stato annullato"
    assert o.sm.state is State.IN_ASCOLTO
    assert o.counters.barge_ins == 1


def test_barge_in_misura_la_latenza():
    from metis.llm.client import CancelToken
    o, _ = make(wake_on_call=1)
    o._cancel = CancelToken()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    o.on_audio(blocco())
    assert len(o.counters.cancel_latency_ms) == 1
    assert o.counters.cancel_latency_ms[0] < 200   # NFR di M1


def _segmento():
    from metis.audio.vad import Segment
    import time as _t
    n = _t.perf_counter()
    return Segment(np.zeros(16000, np.float32), n, n, n, 1.0, 1.0)


def test_annullamento_a_meta_generazione():
    """Il generatore deve RISPETTARE il token, non solo riceverlo.

    L'annullamento arriva al terzo chunk, come farebbe un barge-in reale.
    """
    o, player = make(n_chunks=100)
    def llm_stream(history, cancel=None, **kw):
        gm = FakeGen()
        for i in range(100):
            if cancel is not None and cancel.cancelled:
                return
            if i == 3:
                cancel.cancel()          # barge-in a meta' flusso
            yield "frase di prova abbastanza lunga.", gm
    o.d.llm_stream = llm_stream
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert len(player.queue) <= 5, "il flusso non si e' fermato all'annullamento"


def test_ogni_turno_ha_il_proprio_token():
    """Un token condiviso da resettare ha una corsa: l'annullamento arrivato
    subito prima del reset verrebbe inghiottito."""
    o, _ = make(n_chunks=1)
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    primo = o._cancel
    o.sm.fire(Event.PLAYBACK_DONE) if o.sm.state.name == "PARLATO" else None
    o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert o._cancel is not primo, "il secondo turno riusa il token del primo"


def test_wake_word_in_dormiente_sveglia():
    o, _ = make(wake_on_call=1)
    assert o.sm.state is State.DORMIENTE
    o.on_audio(blocco())
    assert o.sm.state is State.IN_ASCOLTO
    assert o.counters.wake_detections == 1


def test_wake_word_non_ascoltata_in_trascrizione():
    """Mentre l'utente parla, dire 'Hey Metis' non deve resettare il turno."""
    o, _ = make(wake_on_call=1)
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START)
    assert o.sm.state is State.TRASCRIZIONE
    assert o.sm.wake_active is False
    o.on_audio(blocco())
    assert o.counters.wake_detections == 0   # il rilevatore non e' stato nemmeno chiamato


def test_trascrizione_sospetta_scartata():
    o, _ = make()
    o.d.stt = lambda pcm: FakeTranscript(".", suspect=True)
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert o.counters.discarded == 1
    assert o.sm.state is State.IN_ASCOLTO


# --- robustezza (aggiunti con l'integrazione end-to-end) ---------------------

def test_il_rilevatore_si_azzera_dopo_una_pausa():
    """Durante TRASCRIZIONE il rilevatore non riceve frame. Al rientro il suo
    buffer interno contiene ancora l'audio di prima della pausa: incollato a
    quello nuovo puo' formare un pattern che non e' mai stato pronunciato."""
    azzeramenti = {"n": 0}
    o, _ = make()
    o.d.wake_reset = lambda: azzeramenti.__setitem__("n", azzeramenti["n"] + 1)

    o.on_audio(blocco())                       # DORMIENTE: riceve, nessuna pausa
    assert azzeramenti["n"] == 0

    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START)
    assert o.sm.wake_active is False
    o.on_audio(blocco())                       # pausa: il rilevatore salta

    o.sm.fire(Event.SPEECH_END); o.sm.fire(Event.INTENT_CHAT)
    assert o.sm.wake_active is True
    o.on_audio(blocco())
    assert azzeramenti["n"] == 1, "il buffer non e' stato azzerato al rientro"
    o.on_audio(blocco())
    assert azzeramenti["n"] == 1, "azzerato di nuovo senza che ci fosse una pausa"


def test_un_errore_nel_turno_non_appende_la_macchina():
    """Ollama giu' a meta' generazione. Senza guscio lo stato resterebbe in
    GENERAZIONE fino al timeout: 30 secondi di Metis muto."""
    visti = []
    o, player = make()
    o.d.on_error = visti.append
    def llm_rotto(history, cancel=None, **kw):
        raise ConnectionError("ollama non risponde")
        yield  # pragma: no cover - rende la funzione un generatore
    o.d.llm_stream = llm_rotto

    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._run_turn(_segmento())

    assert o.counters.errors == 1
    assert isinstance(visti[0], ConnectionError)
    assert o.sm.state is State.ERRORE, "la macchina e' rimasta appesa"
    assert player.stopped == 1, "l'audio gia' accodato continuerebbe a suonare"


def test_errore_durante_la_riproduzione_finisce_in_errore():
    """Da PARLATO: senza la transizione PARLATO+FAILED si aspetterebbero 120 s."""
    o, _ = make()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    assert o.sm.state is State.PARLATO
    assert o.sm.fire(Event.FAILED) is State.ERRORE


def test_panic_zittisce_da_qualunque_stato():
    """Il kill switch non puo' dipendere dalla salute della macchina a stati."""
    from metis.llm.client import CancelToken
    for stato in State:
        o, player = make()
        o.sm._state = stato
        o._cancel = CancelToken()
        o.panic()
        assert o.sm.state is State.DORMIENTE, f"panic non ha funzionato da {stato.name}"
        assert player.stopped == 1
        assert o.cancelled


def test_playback_done_di_un_turno_superato_non_passa():
    """Il turno 1 finisce di attendere DOPO che il turno 2 e' gia' partito.
    Sparare PLAYBACK_DONE allora riaprirebbe il microfono sull'eco del turno 2."""
    o, player = make(n_chunks=1)
    o.sm.fire(Event.WAKE_WORD); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)

    class PlayerLento(FakePlayer):
        """Mentre il turno 1 attende, arriva il turno 2."""
        def wait_drained(self):
            self.drained += 1
            o._cancel = __import__("metis.llm.client", fromlist=["x"]).CancelToken()
    o.d.player = PlayerLento()

    o._process(_segmento())
    assert o.sm.state is State.PARLATO, "il turno superato ha riaperto il microfono"


# --- push-to-talk come unica via in V1.0 -------------------------------------

def test_il_ptt_interrompe_metis_mentre_parla():
    """Con la wake word spenta e' l'unico modo di interrompere.

    Prima di D1 questo non funzionava: (PARLATO, PTT) non era in tabella,
    quindi premere la scorciatoia mentre Metis parlava non faceva nulla.
    """
    from metis.llm.client import CancelToken
    o, player = make()
    for ev in (Event.PTT, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    assert o.sm.state is State.PARLATO
    o._cancel = CancelToken()
    player.queue.extend([1, 2, 3])

    o.on_ptt()

    assert player.stopped == 1, "l'audio non e' stato fermato"
    assert player.queue == [], "la coda non e' stata svuotata"
    assert o.cancelled, "lo stream LLM non e' stato annullato"
    assert o.sm.state is State.IN_ASCOLTO, "non e' tornato in ascolto"
    assert o.counters.barge_ins == 1


def test_il_ptt_interrompe_anche_durante_la_generazione():
    from metis.llm.client import CancelToken
    o, player = make()
    for ev in (Event.PTT, Event.SPEECH_START, Event.SPEECH_END, Event.INTENT_CHAT):
        o.sm.fire(ev)
    assert o.sm.state is State.GENERAZIONE
    o._cancel = CancelToken()
    o.on_ptt()
    assert o.cancelled and o.sm.state is State.IN_ASCOLTO


def test_il_ptt_resta_un_interruttore():
    """Il comportamento di sempre non deve essersi rotto."""
    o, _ = make()
    assert o.sm.state is State.DORMIENTE
    o.on_ptt()
    assert o.sm.state is State.IN_ASCOLTO
    o.on_ptt()
    assert o.sm.state is State.DORMIENTE


def test_ptt_e_wake_word_percorrono_la_stessa_strada():
    """Due implementazioni separate del barge-in divergono: una delle due
    dimenticherebbe una delle tre cose da fermare."""
    from metis.llm.client import CancelToken
    esiti = []
    for via in ("ptt", "wake"):
        o, player = make(wake_on_call=1 if via == "wake" else None)
        for ev in (Event.PTT, Event.SPEECH_START, Event.SPEECH_END,
                   Event.INTENT_CHAT, Event.FIRST_AUDIO):
            o.sm.fire(ev)
        o._cancel = CancelToken()
        player.queue.extend([1, 2])
        o.on_ptt() if via == "ptt" else o.on_audio(blocco())
        esiti.append((player.stopped, player.queue, o.cancelled,
                      o.sm.state, o.counters.barge_ins))
    assert esiti[0] == esiti[1], f"le due strade divergono: {esiti}"


# --- ramo strumenti (M2) -----------------------------------------------------

class FintaDecisione:
    def __init__(self, call):
        self.call = call
        self.e_strumento = call is not None


class FintoResult:
    def __init__(self, ok=True, detail="eseguito"):
        self.ok = ok
        self.detail = detail
        self.outcome = type("O", (), {"value": "ok" if ok else "denied"})()


def con_azioni(o, call, *, ok=True, conferma=False, eseguiti=None):
    from metis.core.orchestrator import Azioni

    eseguiti = [] if eseguiti is None else eseguiti

    def esegui(c):
        eseguiti.append(c)
        return FintoResult(ok)

    o.d.azioni = Azioni(
        decidi=lambda testo, storia: FintaDecisione(call),
        esegui=esegui,
        descrivi=lambda r: "Ho aperto l'editor." if r.ok else f"Non lo faccio: {r.detail}",
        richiede_conferma=lambda nome: conferma,
    )
    return eseguiti


def stati(o):
    return [t.to.name for t in o.sm.history]


def test_uno_strumento_attraversa_esecuzione_e_parlato():
    o, player = make()
    eseguiti = con_azioni(o, {"tool": "open_application", "app": "vscode"})
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())

    assert eseguiti == [{"tool": "open_application", "app": "vscode"}]
    assert stati(o)[-4:] == ["ESECUZIONE", "PARLATO", "IN_ASCOLTO"][-4:] or \
           stati(o)[-3:] == ["ESECUZIONE", "PARLATO", "IN_ASCOLTO"]
    assert o.counters.tools_ok == 1 and o.counters.turns == 1
    assert len(player.queue) == 1, "l'esito non e' stato pronunciato"


def test_una_t3_passa_da_attesa_conferma():
    """La sequenza di stati e' quella vera gia' in M2: in M3 cambia il
    dialogo, non l'orchestratore."""
    o, _ = make()
    con_azioni(o, {"tool": "send_email"}, conferma=True)
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())

    percorso = stati(o)
    assert "ATTESA_CONFERMA" in percorso
    assert percorso.index("ATTESA_CONFERMA") < percorso.index("PARLATO")
    assert o.counters.tools_ok == 1


def test_una_t3_rifiutata_lo_dice_e_non_resta_appesa():
    o, player = make()
    eseguiti = con_azioni(o, {"tool": "send_email"}, ok=False, conferma=True)
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())

    assert eseguiti, "il broker non e' stato nemmeno interpellato"
    assert o.counters.tools_denied == 1 and o.counters.tools_ok == 0
    assert "ATTESA_CONFERMA" in stati(o)
    assert o.sm.state is State.IN_ASCOLTO, "rimasta appesa dopo il rifiuto"
    assert len(player.queue) == 1, "il rifiuto non e' stato pronunciato"


def test_se_il_router_dice_conversazione_si_parla_come_prima():
    o, player = make(n_chunks=2)
    con_azioni(o, None)
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert "GENERAZIONE" in stati(o) and o.counters.tools_ok == 0
    assert o.counters.turns == 1


def test_senza_azioni_l_orchestratore_si_comporta_come_in_m1():
    """Il ramo strumenti e' interamente opzionale: spegnerlo riporta a M1."""
    o, _ = make(n_chunks=1)
    assert o.d.azioni is None
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert "GENERAZIONE" in stati(o)


def test_un_errore_nel_broker_non_appende_il_turno():
    o, _ = make()
    from metis.core.orchestrator import Azioni
    o.d.azioni = Azioni(
        decidi=lambda t, s: FintaDecisione({"tool": "x"}),
        esegui=lambda c: (_ for _ in ()).throw(RuntimeError("broker esploso")),
        descrivi=lambda r: "",
        richiede_conferma=lambda n: False,
    )
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._run_turn(_segmento())
    assert o.counters.errors == 1
    assert o.sm.state in (State.ERRORE, State.IN_ASCOLTO)
