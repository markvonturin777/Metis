"""PHASE1 — il messaggio scritto nell'Hub.

La domanda che conta non e' "il testo arriva?", ma "il testo passa dalle
stesse porte della voce?". Un ingresso laterale che arrivasse al broker per
un'altra strada — o che non ci arrivasse affatto — sarebbe il modo piu'
semplice di togliere la conferma T3 senza che nessuno se ne accorga. Per
questo l'ultimo gruppo di test usa il broker VERO, non un finto.
"""
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from metis.core.state_machine import Event, State
from tests.test_orchestrator import FintaDecisione, con_azioni, make


def _senza_stt(o):
    def stt(pcm):
        pytest.fail("un messaggio scritto non deve passare dalla trascrizione")
    o.d.stt = stt


def stati(o):
    return [t.to.name for t in o.sm.history]


# --- il percorso ---------------------------------------------------------------------

def test_da_dormiente_il_testo_fa_un_turno_intero():
    o, player = make()
    _senza_stt(o)
    assert o.on_testo("Che ore sono?") is True
    assert stati(o)[:2] == ["ELABORAZIONE", "GENERAZIONE"]
    assert o.sm.state is State.IN_ASCOLTO                # come dopo un turno parlato
    assert {"role": "user", "content": "Che ore sono?"} in o.history
    assert player.queue, "la risposta non e' stata pronunciata (D-UI 2: voce e testo)"


def test_anche_in_ascolto_il_testo_parte():
    o, _ = make()
    _senza_stt(o)
    o.sm.fire(Event.PTT)
    assert o.on_testo("ciao") is True
    assert "ELABORAZIONE" in stati(o)


def test_il_testo_vuoto_non_fa_niente():
    o, _ = make()
    assert o.on_testo("   ") is False
    assert o.on_testo("") is False
    assert o.sm.state is State.DORMIENTE and o.sm.history == []


@pytest.mark.parametrize("eventi", [
    (Event.PTT, Event.SPEECH_START, Event.SPEECH_END),                          # ELABORAZIONE
    (Event.PTT, Event.SPEECH_START, Event.SPEECH_END, Event.INTENT_KNOWN),      # ESECUZIONE
    (Event.PTT, Event.SPEECH_START, Event.SPEECH_END, Event.INTENT_KNOWN,
     Event.NEEDS_CONFIRM),                                                      # ATTESA_CONFERMA
    (Event.PTT, Event.SPEECH_START),                                            # TRASCRIZIONE
])
def test_a_turno_in_corso_il_testo_non_parte(eventi):
    """A meta' di un turno non c'e' un punto in cui inserirne un altro. E
    in ATTESA_CONFERMA meno che mai: il messaggio arriverebbe mentre
    l'utente sta decidendo su un'azione."""
    o, _ = make()
    for ev in eventi:
        o.sm.fire(ev)
    prima = o.sm.state
    assert o.on_testo("e adesso questo") is False
    assert o.sm.state is prima


def test_mentre_parla_il_testo_lo_interrompe_come_il_ptt():
    o, player = make()
    _senza_stt(o)
    for ev in (Event.PTT, Event.SPEECH_START, Event.SPEECH_END, Event.INTENT_CHAT,
               Event.FIRST_AUDIO):
        o.sm.fire(ev)
    player.queue.extend([1, 2, 3])                     # frasi gia' accodate
    fermate = player.stopped
    assert o.on_testo("basta, dimmi un'altra cosa") is True
    assert player.stopped > fermate
    assert "INTERROTTO" in stati(o)
    assert o.counters.barge_ins == 1


def test_il_turno_scritto_e_marcato_per_la_verifica_nfr():
    """NFR-1 va dalla fine del parlato al primo audio: un turno scritto non
    ha parlato, e `verifica_nfr` lo esclude leggendo `origine`."""
    o, _ = make()
    _senza_stt(o)
    visti = []
    o.d.on_turn_end = visti.append
    o.on_testo("ciao")
    assert visti and visti[0].extra.get("origine") == "testo"


def test_i_turni_scritti_non_entrano_in_nfr1():
    from tests.nfr.verifica_nfr import nfr_turni

    parlati = [{"event": "turno", "totale_ms": 900, "ttft_ms": 200, "tok_s": 50}] * 100
    scritti = [{"event": "turno", "totale_ms": 50, "ttft_ms": 200, "tok_s": 50,
                "origine": "testo"}] * 100
    e1 = nfr_turni(parlati + scritti)[0]
    assert "100 turni" in e1.evidenza and e1.misurato.startswith("900")


def test_un_errore_nel_turno_scritto_si_dice_come_nel_parlato():
    """Stesso guscio: l'eccezione non resta sul thread del turno."""
    o, player = make()
    _senza_stt(o)

    def rotto(*a, **k):
        raise ConnectionError("Ollama giu'")
        yield                                            # pragma: no cover
    o.d.llm_stream = rotto
    o.on_testo("ciao")
    assert "ERRORE" in stati(o)
    assert o.counters.errors == 1


# --- pulisci (D-UI 3) ----------------------------------------------------------------

def test_pulisci_svuota_la_memoria_a_macchina_ferma():
    o, _ = make()
    _senza_stt(o)
    o.on_testo("ricordati che mi chiamo Marco")
    assert any(m["role"] == "user" for m in o.history)
    o.sm.fire(Event.TIMEOUT)                             # IN_ASCOLTO -> DORMIENTE
    assert o.azzera_conversazione() is True
    assert not any(m["role"] in ("user", "assistant") for m in o.history)


def test_pulisci_a_turno_in_corso_non_fa_niente():
    o, _ = make()
    o.mem.aggiungi("user", "qualcosa")
    for ev in (Event.PTT, Event.SPEECH_START, Event.SPEECH_END):
        o.sm.fire(ev)
    assert o.azzera_conversazione() is False
    assert any(m["role"] == "user" for m in o.history)


def test_pulisci_non_si_fa_durante_un_riassunto():
    """Il riassunto scriverebbe il suo risultato su una memoria appena
    svuotata: la conversazione cancellata tornerebbe sotto altra forma."""
    import threading

    o, _ = make()
    o.mem.aggiungi("user", "qualcosa")
    fermo = threading.Event()
    o._riassunto = threading.Thread(target=fermo.wait, daemon=True)
    o._riassunto.start()
    try:
        assert o.azzera_conversazione() is False
    finally:
        fermo.set()
        o._riassunto.join(1)


# --- lo stesso broker, la stessa conferma ----------------------------------------------

class Manda(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["manda"]
    to: str = Field(..., max_length=254)


@pytest.fixture
def con_broker_vero(tmp_path):
    """Un registro con una T3 vera e il `Broker` di M2, cablati come in
    `costruisci_azioni`: l'orchestratore chiama `esegui`, `esegui` chiama
    `broker.execute` con la funzione di conferma."""
    from metis.core.orchestrator import Azioni
    from metis.security.audit import AuditLog, Tier
    from metis.security.broker import Broker
    from metis.security.killswitch import KillSwitch
    from metis.security.policies import Context
    from metis.tools.registry import Registry

    reg = Registry("test")
    partite = []

    @reg.strumento(Tier.T3, Manda)
    def _manda(call):
        partite.append(call.to)
        return {"inviata": call.to}

    audit = AuditLog(tmp_path / "audit.db")
    broker = Broker(registry=reg, audit=audit, kill=KillSwitch(), timeout_conferma_s=0.5)
    def chiedi(spec, call):
        return chiedi.risposta                          # cosa risponde l'utente al dialogo
    chiedi.risposta = False

    def esegui(call, untrusted=False):
        return broker.execute(call, Context(turn_id=None, chiedi_conferma=chiedi,
                                            has_untrusted_content=untrusted))

    o, player = make()
    _senza_stt(o)
    o.d.azioni = Azioni(
        decidi=lambda testo, storia: FintaDecisione({"tool": "manda", "to": "a@b.it"}),
        esegui=esegui,
        descrivi=lambda risultati, risposta=None: "fatto" if risultati[-1].ok else "no",
        richiede_conferma=lambda nome: True,
    )
    yield o, partite, chiedi, audit
    audit.close()


def test_un_messaggio_scritto_chiede_la_conferma_t3(con_broker_vero):
    o, partite, chiedi, audit = con_broker_vero
    chiedi.risposta = False
    assert o.on_testo("mandami una mail") is True
    assert "ATTESA_CONFERMA" in stati(o)
    assert partite == [], "una T3 e' partita senza conferma da un messaggio scritto"
    assert audit.unconfirmed_t3() == 0


def test_confermata_la_t3_scritta_parte(con_broker_vero):
    o, partite, chiedi, _ = con_broker_vero
    chiedi.risposta = True
    o.on_testo("mandami una mail")
    assert partite == ["a@b.it"]


def test_con_il_broker_finto_il_percorso_degli_strumenti_e_lo_stesso():
    """Lo stesso test di `test_una_t3_passa_da_attesa_conferma`, dal testo."""
    o, _ = make()
    _senza_stt(o)
    con_azioni(o, {"tool": "send_email"}, conferma=True)
    o.on_testo("mandami una mail")
    percorso = stati(o)
    assert percorso.index("ATTESA_CONFERMA") < percorso.index("PARLATO")
