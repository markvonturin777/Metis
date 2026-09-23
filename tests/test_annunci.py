"""Cio' che Metis dice senza che nessuno l'abbia chiesto, e quando lo dice.

Due regole del piano, entrambe sulla sequenza e quindi dell'orchestratore:

    un promemoria durante una conversazione si ACCODA, non interrompe
    la data di un promemoria si SENTE prima di confermarla
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from metis.audio.capture import Block
from metis.core.orchestrator import Azioni, Deps, Orchestrator
from metis.core.risposte import descrivi, domanda_conferma
from metis.core.state_machine import STT_MUTED, Event, State
from metis.llm.toolcall import Decisione


class FakePlayer:
    def __init__(self):
        self.queue = []
        self.stopped = 0

    def enqueue(self, pcm):
        self.queue.append(pcm)

    def stop(self):
        self.stopped += 1
        self.queue.clear()

    def wait_drained(self):
        pass


@dataclass
class Synth:
    testo: str
    pcm: np.ndarray = field(default_factory=lambda: np.zeros(4, np.float32))


def orchestratore(azioni=None):
    detti: list[str] = []

    def tts(t):
        detti.append(t)
        return Synth(t)

    d = Deps(wakeword=lambda pcm: False, stt=lambda pcm: None,
             llm_stream=lambda *a, **k: iter(()), tts_synth=tts,
             player=FakePlayer(), azioni=azioni)
    o = Orchestrator(d)
    o.synchronous = True
    return o, detti


# --- i promemoria non interrompono ---------------------------------------------

def test_in_dormiente_l_annuncio_parte_al_tick():
    o, detti = orchestratore()
    o.annuncia("Promemoria: chiamare il commercialista.")
    assert detti == []                          # non parla subito
    o.tick()
    assert detti == ["Promemoria: chiamare il commercialista."]
    assert o.counters.annunci == 1


def test_durante_una_conversazione_l_annuncio_aspetta():
    o, detti = orchestratore()
    for ev in (Event.PTT, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    assert o.sm.state is State.PARLATO
    o.annuncia("Promemoria: latte.")
    for _ in range(5):
        o.tick()
    assert detti == [], "il promemoria ha interrotto Metis mentre parlava"
    assert o.counters.annunci_rimandati >= 1

    o.sm.reset()                                # conversazione finita
    o.tick()
    assert detti == ["Promemoria: latte."]


def test_in_ascolto_l_annuncio_aspetta():
    """IN_ASCOLTO vuol dire che l'utente ha appena premuto il PTT e sta per
    parlare: e' il momento peggiore per un promemoria."""
    o, detti = orchestratore()
    o.sm.fire(Event.PTT)
    o.annuncia("Promemoria: x.")
    o.tick()
    assert detti == []


def test_gli_annunci_escono_in_ordine_uno_per_tick():
    o, detti = orchestratore()
    for t in ("uno", "due", "tre"):
        o.annuncia(t)
    o.tick()
    o.tick()
    o.tick()
    assert detti == ["uno", "due", "tre"]


def test_il_ptt_durante_un_annuncio_lo_ferma():
    """In DORMIENTE il microfono e' chiuso e l'annuncio suona. Se l'utente
    preme il PTT, il microfono si apre: l'annuncio deve tacere prima, o VAD e
    STT sentirebbero Metis."""
    o, _ = orchestratore()
    o.annuncia("Promemoria: una frase lunga.")
    o.tick()
    assert o.d.player.queue
    o.on_ptt()
    assert o.sm.state is State.IN_ASCOLTO
    assert o.d.player.stopped >= 1 and o.d.player.queue == []


def test_un_annuncio_che_non_si_sintetizza_non_rompe_il_tick():
    o, _ = orchestratore()

    def rotto(t):
        raise RuntimeError("piper giu'")

    o.d.tts_synth = rotto
    o.annuncia("x")
    o.tick()                                    # non solleva
    assert o.counters.errors == 1


# --- la domanda di conferma si sente ---------------------------------------------

def _azioni(decisione, eseguite):
    return Azioni(decidi=lambda t, s: decisione,
                  esegui=lambda c, u: eseguite.append(c) or _Ok(),
                  descrivi=lambda r, x: "Fatto.",
                  richiede_conferma=lambda nome: nome == "schedule_reminder",
                  domanda_conferma=domanda_conferma)


class _Ok:
    ok = True
    outcome = type("O", (), {"value": "ok"})()


def test_la_data_si_pronuncia_prima_della_conferma():
    decisione = Decisione(({"tool": "schedule_reminder", "testo": "commercialista",
                            "quando": "2099-06-04T17:00"},), "llm", 1.0)
    eseguite = []
    o, detti = orchestratore(_azioni(decisione, eseguite))
    o.sm.fire(Event.PTT)
    o.sm.fire(Event.SPEECH_START)
    o.sm.fire(Event.SPEECH_END)
    o._esegui_strumento(_Turno(), decisione)
    domanda = next(t for t in detti if "Confermo?" in t)
    assert "giovedì 4 giugno 2099" in domanda and "17:00" in domanda
    assert detti.index(domanda) < detti.index("Fatto.")


@dataclass
class _Turno:
    extra: dict = field(default_factory=dict)
    reply: str = ""
    t_first_audio: float = 0.0

    def append_to_log(self):
        pass


def test_in_attesa_di_conferma_il_microfono_e_chiuso():
    """Da M6 Metis parla in ATTESA_CONFERMA. La regola di M5: se in uno
    stato esce audio, quello stato sta in STT_MUTED."""
    assert State.ATTESA_CONFERMA in STT_MUTED
    o, _ = orchestratore()
    for ev in (Event.PTT, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_KNOWN, Event.NEEDS_CONFIRM):
        o.sm.fire(ev)
    assert o.sm.state is State.ATTESA_CONFERMA
    prima = o.counters.frames_to_vad
    for _ in range(20):
        o.on_audio(Block(np.zeros(512, np.float32), -20.0, -20.0))
    assert o.counters.frames_to_vad == prima


# --- le frasi ---------------------------------------------------------------------

class R:
    def __init__(self, tool, value, ok=True):
        from metis.security.audit import Outcome
        self.tool, self.value, self.ok = tool, value, ok
        self.outcome = Outcome.OK if ok else Outcome.DENIED
        self.stage, self.detail = "esecuzione", ""


def test_la_conferma_del_promemoria_ripete_la_data():
    frase = descrivi(R("schedule_reminder",
                       {"in_parole": "domani, giovedì 24 settembre, alle 17:00"}))
    assert frase == "Promemoria per domani, giovedì 24 settembre, alle 17:00."


def test_lo_stato_di_un_dispositivo_non_indovina_il_genere():
    """I nomi vengono dal file di configurazione: "acceso/accesa" sbaglierebbe
    una volta su due, e una frase che sbaglia il genere suona rotta anche
    quando dice il vero."""
    frase = descrivi(R("get_home_state", {"nome": "la friggitrice ad aria",
                                          "noto": True, "acceso": True}))
    assert frase == "La friggitrice ad aria è in funzione."


def test_l_accensione_dice_quando_si_spegne():
    frase = descrivi(R("set_home_device", {"nome": "la friggitrice ad aria",
                                           "azione": "accendi",
                                           "spegnimento": "18:30"}))
    assert "Ho acceso la friggitrice ad aria" in frase and "18:30" in frase


def test_se_lo_spegnimento_non_e_programmato_lo_dice():
    frase = descrivi(R("set_home_device", {"nome": "la friggitrice ad aria",
                                           "azione": "accendi",
                                           "spegnimento": None}))
    assert "Attenzione" in frase


def test_la_domanda_per_un_dispositivo_usa_il_nome_configurato():
    assert domanda_conferma({"tool": "set_home_device", "dispositivo": "crocchette",
                             "azione": "accendi"}) == \
        "Accendo il distributore di crocchette?"


def test_lista_vuota_detta_bene():
    assert descrivi(R("list_reminders", {"totale": 0, "voci": []})) == \
        "Non ha niente in programma."
