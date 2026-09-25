"""Il turno che consulta le fonti, visto dall'orchestratore.

Tre cose si verificano qui e in nessun altro posto, perche' sono proprieta'
della SEQUENZA e non dei pezzi:

    il filler esce prima della ricerca, non dopo
    una ricerca fallita non arriva mai al modello
    in RICERCA_WEB il microfono e' chiuso, perche' li' Metis parla

La terza e' quella che nessuno penserebbe di provare, ed e' la stessa classe
di difetto che in M1 ha fatto rimandare la wake word alla v2: audio che esce
mentre il microfono e' aperto.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from metis.audio.capture import Block
from metis.core.orchestrator import Azioni, Conoscenza, Deps, Orchestrator
from metis.core.risposte import FILLERS, Filler
from metis.core.state_machine import STT_MUTED, Event, State
from metis.llm import grounding as g
from metis.llm.toolcall import Decisione
from metis.memory.conversation import Memoria


class FakePlayer:
    def __init__(self):
        self.queue = []
        self.stopped = 0
        self.drained = 0

    def enqueue(self, pcm):
        self.queue.append(pcm)

    def stop(self):
        self.stopped += 1
        self.queue.clear()

    def wait_drained(self):
        self.drained += 1


@dataclass
class FakeSynth:
    pcm: np.ndarray = field(default_factory=lambda: np.zeros(4, np.float32))


@dataclass
class FakeGen:
    ttft_ms: float = 80.0
    tokens: int = 12
    tok_per_s: float = 50.0
    text: str = "Secondo la fonte, il rendimento e' al tre e settantacinque."


def contesto(ok=True, motivo="", n=2):
    fonti = [g.Fonte(id=i + 1, url=f"https://e{i}.it/a", testo="contenuto " * 40)
             for i in range(n)] if ok else []
    return g.Contesto(fonti=fonti, ok=ok, motivo=motivo, query="btp")


def costruisci(ctx=None, calls=(("web_search", "btp decennale"),), eventi=None):
    """Un orchestratore con il ramo conoscenza e nient'altro di vero."""
    registro = eventi if eventi is not None else []
    player = FakePlayer()
    ordine: list[str] = []

    decisione = Decisione(tuple({"tool": t, **({"query": q} if t == "web_search"
                                               else {"url": q})}
                                for t, q in calls), "llm", 1.0)

    def consulta(query):
        ordine.append(f"ricerca:{query}")
        return ctx if ctx is not None else contesto()

    def filler():
        ordine.append("filler")
        return FILLERS[0]

    def llm_stream(messaggi, cancel=None, **kw):
        ordine.append("genera")
        registro.append(messaggi)
        yield "Secondo la fonte, il rendimento e' al tre e settantacinque.", FakeGen()

    azioni = Azioni(decidi=lambda t, s: decisione,
                    esegui=lambda c, u: None,
                    descrivi=lambda r, x: "",
                    richiede_conferma=lambda n: False)

    d = Deps(wakeword=lambda pcm: False,
             stt=lambda pcm: _Tr(),
             llm_stream=llm_stream,
             tts_synth=lambda t: (ordine.append(f"dice:{t[:12]}"), FakeSynth())[1],
             player=player,
             memoria=Memoria(system="Sei Metis."),
             azioni=azioni,
             conoscenza=Conoscenza(query_web=_query_web, consulta=consulta,
                                   filler=filler))
    o = Orchestrator(d)
    o.synchronous = True
    return o, player, ordine


def _query_web(decisione):
    for c in getattr(decisione, "calls", ()):
        if c.get("tool") == "web_search":
            return c.get("query")
        if c.get("tool") == "web_fetch":
            return c.get("url")
    return None


@dataclass
class _Tr:
    text: str = "quanto rende il btp decennale?"
    suspect: bool = False


def _segmento():
    from metis.audio.vad import Segment

    return Segment(pcm=np.zeros(16000, np.float32), t_speech_start=0.0,
                   t_speech_end=0.0, t_endpoint=0.0, duration_s=1.0,
                   max_prob=0.9)


def esegui_turno(o):
    o.sm.fire(Event.PTT)
    o.sm.fire(Event.SPEECH_START)
    o.sm.fire(Event.SPEECH_END)               # -> ELABORAZIONE
    o._process(_segmento())


# --- la sequenza --------------------------------------------------------------

def test_il_filler_esce_prima_della_ricerca():
    """Invertire le due righe non romperebbe niente e renderebbe il filler
    inutile, che e' il modo in cui un requisito di interazione muore senza
    che nessun test se ne accorga."""
    o, _, ordine = costruisci()
    esegui_turno(o)
    i_ricerca = ordine.index("ricerca:btp decennale")
    assert ordine.index("filler") < i_ricerca
    detto = next(i for i, x in enumerate(ordine) if x.startswith("dice:Un momento"))
    assert detto < i_ricerca, "il filler e' stato sintetizzato dopo la ricerca"


def test_il_filler_e_audio_in_coda_prima_che_la_ricerca_finisca():
    """"Emesso entro 300 ms" significa che il PCM e' gia' nel player quando
    la ricerca comincia, non che la funzione e' stata chiamata."""
    visto = {}

    def consulta(query):
        visto["coda"] = len(player.queue)
        return contesto()

    o, player, _ = costruisci()
    o.d.conoscenza = Conoscenza(query_web=_query_web, consulta=consulta,
                                filler=Filler().prossimo)
    esegui_turno(o)
    assert visto["coda"] == 1


def test_il_percorso_web_attraversa_ricerca_web_e_generazione():
    o, _, _ = costruisci()
    esegui_turno(o)
    stati = [t.to for t in o.sm.history]
    assert State.RICERCA_WEB in stati
    assert stati.index(State.RICERCA_WEB) < stati.index(State.GENERAZIONE)
    assert o.sm.state is State.IN_ASCOLTO


def test_in_ricerca_web_il_microfono_e_chiuso():
    """Il filler dura quanto la ricerca: se il microfono restasse aperto,
    Metis sentirebbe se stesso per 1,5-4 secondi. E' l'auto-innesco da eco,
    lo stesso che ha rimandato la wake word alla v2."""
    assert State.RICERCA_WEB in STT_MUTED

    o, _, _ = costruisci()
    o.sm.fire(Event.PTT)
    o.sm.fire(Event.SPEECH_START)
    o.sm.fire(Event.SPEECH_END)
    o.sm.fire(Event.INTENT_WEB)
    assert o.sm.state is State.RICERCA_WEB
    prima = o.counters.frames_to_vad
    for _ in range(30):
        o.on_audio(Block(np.zeros(512, np.float32), -20.0, -20.0))
    assert o.counters.frames_to_vad == prima


def test_il_ptt_interrompe_anche_durante_la_ricerca():
    """Durante una ricerca lenta l'utente deve poter dire "lascia stare"
    senza aspettare che finisca."""
    o, player, _ = costruisci()
    o.sm.fire(Event.PTT)
    o.sm.fire(Event.SPEECH_START)
    o.sm.fire(Event.SPEECH_END)
    o.sm.fire(Event.INTENT_WEB)
    o.on_ptt()
    assert player.stopped >= 1
    assert o.sm.state is State.IN_ASCOLTO


# --- le fonti nel prompt ------------------------------------------------------

def test_le_fonti_arrivano_al_modello_dentro_i_delimitatori():
    eventi = []
    o, _, _ = costruisci(eventi=eventi)
    esegui_turno(o)
    utente = [m for m in eventi[0] if m["role"] == "user"][-1]["content"]
    assert g.APRI in utente and g.CHIUDI in utente
    assert utente.rindex("quanto rende il btp") > utente.rindex(g.CHIUDI)


def test_le_fonti_non_restano_nella_memoria_del_turno_dopo():
    o, _, _ = costruisci()
    esegui_turno(o)
    assert all("FONTE_ESTERNA" not in m["content"] for m in o.history)
    assert any("rendimento" in m["content"] for m in o.history)


# --- degradazione dichiarata ---------------------------------------------------

def test_ricerca_fallita_non_arriva_mai_al_modello():
    """Lo scenario peggiore del progetto: la ricerca fallisce e il modello
    risponde lo stesso, a memoria. Qui il modello non viene proprio
    interpellato."""
    o, _, ordine = costruisci(ctx=contesto(ok=False, motivo=g.SENZA_FONTI))
    esegui_turno(o)
    assert "genera" not in ordine
    assert any(x.startswith("dice:Le fonti") for x in ordine)
    assert o.counters.ricerche_degradate == 1


def test_dopo_una_ricerca_fallita_il_turno_si_chiude_pulito():
    """Una degradazione che lascia la macchina in RICERCA_WEB la lascia
    appesa fino al timeout, cioe' venticinque secondi di Metis muto."""
    o, player, _ = costruisci(ctx=contesto(ok=False, motivo=g.SENZA_FONTI))
    esegui_turno(o)
    assert o.sm.state is State.IN_ASCOLTO
    assert player.drained == 1


def test_la_frase_di_degradazione_entra_in_memoria():
    """Se non ci entrasse, al turno dopo Metis non saprebbe di aver appena
    detto che non ci arriva."""
    o, _, _ = costruisci(ctx=contesto(ok=False, motivo=g.SENZA_FONTI))
    esegui_turno(o)
    assert o.history[-1]["content"] == g.SENZA_FONTI


# --- le azioni che non si eseguono --------------------------------------------

def test_le_altre_azioni_del_piano_non_si_eseguono():
    """"Cerca X e premi win+r" e' un piano in cui la seconda azione verrebbe
    decisa da una pagina che ancora non e' stata letta."""
    eseguite = []
    o, _, _ = costruisci()
    o.d.azioni.esegui = lambda c, u: eseguite.append(c)
    o.d.azioni.decidi = lambda t, s: Decisione(
        ({"tool": "web_search", "query": "btp"},
         {"tool": "press_hotkey", "keys": ["win", "r"]}), "llm", 1.0)
    esegui_turno(o)
    assert eseguite == [], "un'azione e' partita in un turno con contenuto web"


def test_le_azioni_scartate_restano_nel_log_del_turno():
    """Scartare in silenzio significa che, il giorno in cui il router
    comincia a produrre piani misti, nessuno se ne accorge."""
    visti = []
    o, _, _ = costruisci()
    o.d.on_turn_end = visti.append
    o.d.azioni.decidi = lambda t, s: Decisione(
        ({"tool": "web_search", "query": "btp"},
         {"tool": "press_hotkey", "keys": ["win", "r"]}), "llm", 1.0)
    esegui_turno(o)
    assert visti[0].extra["azioni_scartate"] == "press_hotkey"


# --- il filler ------------------------------------------------------------------

def test_il_filler_non_si_ripete_mai_due_volte_di_fila():
    """Sentire sempre la stessa frase e' peggio del silenzio: diventa un
    suono di sistema e smette di significare "sto lavorando"."""
    f = Filler()
    uscite = [f.prossimo() for _ in range(200)]
    assert all(a != b for a, b in zip(uscite, uscite[1:]))
    assert set(uscite) == set(FILLERS)


def test_con_un_filler_solo_non_va_in_ciclo():
    f = Filler(frasi=("unica",))
    assert [f.prossimo(), f.prossimo()] == ["unica", "unica"]


def test_un_filler_che_non_si_sintetizza_non_perde_il_turno():
    o, _, ordine = costruisci()

    def tts(t):
        if t in FILLERS:
            raise RuntimeError("piper giu'")
        return FakeSynth()

    o.d.tts_synth = tts
    esegui_turno(o)
    assert "genera" in ordine and o.sm.state is State.IN_ASCOLTO


# --- il riassunto in DORMIENTE --------------------------------------------------

def test_il_riassunto_non_parte_mentre_qualcuno_aspetta():
    """Riassumere costa 2-3 secondi. Farlo in un turno a caso e' il tipo
    peggiore di latenza: quella di cui non si indovina la causa."""
    fatti = []
    o, _, _ = costruisci()
    o.mem.riassumi = lambda p: fatti.append(p) or "riassunto"
    for i in range(40):
        o.mem.aggiungi("user", f"d{i} " + "x" * 2000)
        o.mem.aggiungi("assistant", f"r{i} " + "y" * 2000)

    for stato in (State.IN_ASCOLTO, State.GENERAZIONE, State.PARLATO):
        o.sm._state = stato
        o.tick()
    assert fatti == []

    o.sm._state = State.DORMIENTE
    o.tick()
    assert len(fatti) == 1
    assert o.counters.riassunti == 1
