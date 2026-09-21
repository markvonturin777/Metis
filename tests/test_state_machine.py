"""La macchina a stati e' testabile senza audio: e' il motivo per cui le
transizioni sono un dato e non una catena di `if`."""
import random
import pytest
from metis.core.state_machine import (
    Event, State, StateMachine, TIMEOUTS, TRANSITIONS,
    dead_end_states, unreachable_states,
)


# --- integrita' della tabella ------------------------------------------------

def test_nessuno_stato_irraggiungibile():
    assert unreachable_states() == set()


def test_nessun_vicolo_cieco():
    """Uno stato senza uscite bloccherebbe Metis per sempre."""
    assert dead_end_states() == set()


def test_ogni_stato_ha_un_timeout_definito():
    """Anche None e' una decisione, ma va presa esplicitamente."""
    assert set(TIMEOUTS) == set(State)


def test_dormiente_non_ha_timeout():
    """E' lo stato di riposo: non deve scadere in nulla."""
    assert TIMEOUTS[State.DORMIENTE] is None


# --- percorsi nominali -------------------------------------------------------

def test_giro_completo_conversazionale():
    m = StateMachine()
    for ev, atteso in [
        (Event.WAKE_WORD, State.IN_ASCOLTO),
        (Event.SPEECH_START, State.TRASCRIZIONE),
        (Event.SPEECH_END, State.ELABORAZIONE),
        (Event.INTENT_CHAT, State.GENERAZIONE),
        (Event.FIRST_AUDIO, State.PARLATO),
        (Event.PLAYBACK_DONE, State.IN_ASCOLTO),
    ]:
        assert m.fire(ev) is atteso


def test_push_to_talk_equivale_alla_wake_word():
    a, b = StateMachine(), StateMachine()
    assert a.fire(Event.WAKE_WORD) is b.fire(Event.PTT) is State.IN_ASCOLTO


def test_timeout_riporta_a_dormiente():
    m = StateMachine()
    m.fire(Event.WAKE_WORD)
    assert m.fire(Event.TIMEOUT) is State.DORMIENTE


# --- anti-eco e barge-in: il cuore di M1 -------------------------------------

def test_stt_sospeso_mentre_parla():
    """L1 half-duplex: e' qui che si rompe il loop di auto-innesco."""
    m = StateMachine()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        m.fire(ev)
    assert m.state is State.PARLATO
    assert m.stt_muted is True


def test_wake_word_attiva_anche_mentre_parla():
    """L2 barge-in: senza questo non si puo' interrompere Metis."""
    m = StateMachine()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        m.fire(ev)
    assert m.state is State.PARLATO
    assert m.wake_active is True


def test_barge_in_interrompe_e_torna_in_ascolto():
    m = StateMachine()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        m.fire(ev)
    assert m.fire(Event.WAKE_WORD) is State.INTERROTTO
    assert m.stt_muted is True          # ancora sospeso finche' il TTS non si ferma
    assert m.fire(Event.TTS_STOPPED) is State.IN_ASCOLTO
    assert m.stt_muted is False


def test_barge_in_anche_prima_del_primo_audio():
    """Se l'utente interrompe durante la generazione, prima che il TTS parta."""
    m = StateMachine()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END, Event.INTENT_CHAT):
        m.fire(ev)
    assert m.state is State.GENERAZIONE
    assert m.fire(Event.WAKE_WORD) is State.INTERROTTO


def test_in_dormiente_lo_stt_e_sospeso_ma_la_wake_word_ascolta():
    m = StateMachine()
    assert m.state is State.DORMIENTE
    assert m.stt_muted is True
    assert m.wake_active is True


# --- azioni T3 (M2) ----------------------------------------------------------

def test_conferma_negata_non_esegue():
    m = StateMachine()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END, Event.INTENT_KNOWN):
        m.fire(ev)
    assert m.fire(Event.NEEDS_CONFIRM) is State.ATTESA_CONFERMA
    assert m.fire(Event.DENIED) is State.PARLATO


def test_timeout_conferma_equivale_a_rifiuto():
    """Il silenzio non e' consenso: scaduto il tempo, l'azione non avviene."""
    m = StateMachine()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_KNOWN, Event.NEEDS_CONFIRM):
        m.fire(ev)
    assert m.fire(Event.TIMEOUT) is State.PARLATO


def test_timeout_conferma_coincide_col_broker():
    """M2 usera' lo stesso valore: se divergono, uno dei due si blocca."""
    assert TIMEOUTS[State.ATTESA_CONFERMA] == 20.0


# --- robustezza --------------------------------------------------------------

def test_evento_fuori_sequenza_non_solleva():
    m = StateMachine()
    assert m.fire(Event.PLAYBACK_DONE) is State.DORMIENTE   # ignorato
    assert m.rejected == [(State.DORMIENTE, Event.PLAYBACK_DONE)]


def test_cento_eventi_casuali_non_sollevano():
    """Gli eventi audio arrivano fuori sequenza di continuo."""
    rng = random.Random(42)
    m = StateMachine()
    for _ in range(100):
        m.fire(rng.choice(list(Event)))
    assert m.state in set(State)


def test_ricerca_web_degrada_invece_di_bloccare():
    """Rete assente: si genera comunque, dichiarando l'assenza di fonti."""
    m = StateMachine()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END, Event.INTENT_WEB):
        m.fire(ev)
    assert m.state is State.RICERCA_WEB
    assert m.fire(Event.FAILED) is State.GENERAZIONE


def test_le_transizioni_sono_registrate():
    m = StateMachine()
    m.fire(Event.WAKE_WORD)
    m.fire(Event.SPEECH_START)
    assert [t.to for t in m.history] == [State.IN_ASCOLTO, State.TRASCRIZIONE]


def test_osservatore_chiamato_a_ogni_transizione():
    visti = []
    m = StateMachine(on_transition=visti.append)
    m.fire(Event.WAKE_WORD)
    m.fire(Event.PLAYBACK_DONE)      # rifiutata, non deve notificare
    assert len(visti) == 1
    assert visti[0].to is State.IN_ASCOLTO
