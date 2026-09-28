"""PHASE6 — la qualità della conversazione.

Giorno 1: due cronologie. Il router vede tutto; la conversazione vede solo gli
scambi a parole, e le ultime azioni in una riga del messaggio di sistema.
"""
from metis.core.orchestrator import Azioni
from metis.core.risposte import descrivi_sequenza
from metis.core.state_machine import Event
from metis.llm.toolcall import Decisione
from metis.memory.conversation import AZIONE, INTESTAZIONE_AZIONI, PAROLE, Memoria
from metis.security.audit import Outcome
from metis.security.broker import Result
from tests.test_orchestrator import FakeGen, _segmento, make


# --- la memoria -----------------------------------------------------------------------

def _memoria():
    m = Memoria(system="persona")
    m.aggiungi("user", "ciao")
    m.aggiungi("assistant", "Buongiorno.")
    m.aggiungi("user", "mostra i numeri")
    m.segna_azione()
    m.aggiungi("assistant", "Ecco 71 numeri.", AZIONE)
    m.aggiungi("user", "clicca il 58", AZIONE)
    m.aggiungi("assistant", "Cliccato il 58.", AZIONE)
    m.aggiungi("user", "quali azioni puoi fare?")
    return m


def test_la_conversazione_non_vede_gli_scambi_con_il_sistema():
    msgs = _memoria().messaggi(per="conversazione")
    testi = [x["content"] for x in msgs if x["role"] != "system"]
    assert testi == ["ciao", "Buongiorno.", "quali azioni puoi fare?"]


def test_le_ultime_azioni_stanno_nel_messaggio_di_sistema():
    sistema = _memoria().messaggi(per="conversazione")[0]["content"]
    assert sistema.startswith("persona")
    assert INTESTAZIONE_AZIONI in sistema
    assert "- Ecco 71 numeri.\n- Cliccato il 58." in sistema


def test_al_massimo_tre_azioni():
    m = Memoria(system="p")
    for i in range(5):
        m.aggiungi("user", f"comando {i}", AZIONE)
        m.aggiungi("assistant", f"esito {i}", AZIONE)
    sistema = m.messaggi(per="conversazione")[0]["content"]
    assert "esito 1" not in sistema and "esito 2" in sistema and "esito 4" in sistema


def test_il_router_vede_tutto():
    testi = [x["content"] for x in _memoria().messaggi() if x["role"] != "system"]
    assert "Ecco 71 numeri." in testi and "clicca il 58" in testi
    assert INTESTAZIONE_AZIONI not in _memoria().messaggi()[0]["content"]


def test_l_origine_non_arriva_al_modello():
    for per in ("tutto", "conversazione"):
        assert all(set(x) == {"role", "content"} for x in _memoria().messaggi(per=per))


def test_segna_azione_tocca_solo_l_ultima_frase_dell_utente():
    m = Memoria()
    m.aggiungi("user", "uno")
    m.aggiungi("assistant", "a")
    m.aggiungi("user", "due")
    m.segna_azione()
    assert [t["origine"] for t in m.turni] == [PAROLE, PAROLE, AZIONE]


def test_la_domanda_con_le_fonti_resta_nella_conversazione():
    """Il percorso web sostituisce l'ultima frase dell'utente con la domanda e
    le fonti: deve funzionare anche nella vista filtrata."""
    m = _memoria()
    msgs = m.messaggi(domanda="DOMANDA CON FONTI", per="conversazione")
    assert msgs[-1] == {"role": "user", "content": "DOMANDA CON FONTI"}
    assert "quali azioni puoi fare?" not in [x["content"] for x in msgs]


def test_senza_azioni_nessuna_riga():
    m = Memoria(system="p")
    m.aggiungi("user", "ciao")
    assert m.messaggi(per="conversazione")[0]["content"] == "p"


# --- l'orchestratore ------------------------------------------------------------------

def _ok():
    return Result(ok=True, outcome=Outcome.OK, stage="esecuzione", detail="ok",
                  tool="open_application")


def _orchestratore(decisioni, testi):
    """Turni in fila; ritorna l'orchestratore e i messaggi mandati alla conversazione."""
    o, _ = make(text=testi[0])
    mandati = []

    def llm_stream(history, cancel=None, **kw):
        mandati.append(history)
        yield "Risposta a parole.", FakeGen(text="Risposta a parole.")

    coda_d, coda_t = list(decisioni), list(testi)
    o.d.llm_stream = llm_stream
    o.d.stt = lambda pcm: type("T", (), {"text": coda_t.pop(0), "suspect": False})()
    o.d.azioni = Azioni(decidi=lambda t, s: coda_d.pop(0), esegui=lambda c, u=False: _ok(),
                        descrivi=descrivi_sequenza, richiede_conferma=lambda c: False)
    for _ in testi:
        if o.sm.state.name == "DORMIENTE":
            o.sm.fire(Event.PTT)
        o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
        o._process(_segmento())
    return o, mandati


def test_dopo_un_azione_la_conversazione_non_la_vede_nella_cronologia():
    o, mandati = _orchestratore(
        [Decisione(({"tool": "open_application", "app": "chrome"},)), Decisione(())],
        ["apri chrome", "quali azioni puoi fare?"])
    assert len(mandati) == 1
    testi = [x["content"] for x in mandati[0] if x["role"] != "system"]
    assert testi == ["quali azioni puoi fare?"]
    assert INTESTAZIONE_AZIONI in mandati[0][0]["content"]


def test_il_router_continua_a_vedere_l_azione():
    """"spostala" dopo "apri chrome" ha bisogno dello scambio intero."""
    o, _ = _orchestratore([Decisione(({"tool": "open_application", "app": "chrome"},))],
                          ["apri chrome"])
    testi = [x["content"] for x in o.history if x["role"] != "system"]
    assert testi[0] == "apri chrome" and len(testi) == 2


def test_un_chiarimento_e_un_azione():
    o, mandati = _orchestratore(
        [Decisione((), chiarimento="Non ho capito il numero: me lo ripete?"), Decisione(())],
        ["clicca su oltra un tunnel", "come stai?"])
    testi = [x["content"] for x in mandati[0] if x["role"] != "system"]
    assert testi == ["come stai?"]


def test_una_conversazione_resta_nella_conversazione():
    o, mandati = _orchestratore([Decisione(()), Decisione(())], ["ciao", "come stai?"])
    testi = [x["content"] for x in mandati[1] if x["role"] != "system"]
    assert testi == ["ciao", "Risposta a parole.", "come stai?"]


# === Giorni 3-4: la persona v2 e la guardia ============================================

import pytest  # noqa: E402

from metis.core.risposte import NON_FATTO, dichiara_azione  # noqa: E402
from metis.llm import prompts  # noqa: E402


@pytest.mark.parametrize("risposta,atteso", [
    ("Cliccato l'ottantuno.", True),          # PHASE2, la prova del 2026-09-26
    ("Ecco 99 numeri.", True),
    ("Indietro.", True),
    ("Ho aperto Chrome.", True),
    ("Fatto.", True),
    ("Numeri tolti.", True),
    ("Posso aprire applicazioni e cercare sul web.", False),
    ("Ho capito, ma non so cosa intende.", False),
    ("Il fatto e' che il lunedi' e' difficile.", False),
    ("Indietro non si torna, signore: si va avanti.", False),
])
def test_dichiara_azione(risposta, atteso):
    assert dichiara_azione(risposta) is atteso


def _conversazione(prima_frase):
    o, player = make(text="su ottantuna")

    def llm_stream(history, cancel=None, **kw):
        yield prima_frase, FakeGen(text=prima_frase)
        yield "E poi altro.", FakeGen(text=prima_frase + " E poi altro.")

    detti = []
    o.d.llm_stream = llm_stream
    o.d.tts_synth = lambda t: detti.append(t) or type("S", (), {"pcm": b""})()
    visti = []
    o.d.on_turn_end = visti.append
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    return o, detti, visti[0]


def test_la_conversazione_non_dice_di_aver_cliccato():
    """D-CONV 5: la protezione di PHASE2 passa dal prompt al codice."""
    o, detti, m = _conversazione("Cliccato l'ottantuno.")
    assert detti == [NON_FATTO]                        # e il resto non si genera
    assert m.reply == NON_FATTO and o.history[-1]["content"] == NON_FATTO
    assert m.extra["non_capito"] == "conversazione" and m.extra["azione_dichiarata"]


def test_una_risposta_normale_passa_intera():
    o, detti, m = _conversazione("Il cielo e' blu per via della luce.")
    assert detti == ["Il cielo e' blu per via della luce.", "E poi altro."]
    assert "azione_dichiarata" not in m.extra


def test_gli_esempi_ruotano():
    coppie = prompts.esempi("metis_v2")
    assert len(coppie) >= 12
    assert all(c.startswith("Utente:") and "\nMetis:" in c for c in coppie)
    uno, due = prompts.per_turno("metis_v2", 0), prompts.per_turno("metis_v2", 1)
    assert uno != due and prompts.carica("metis_v2") in uno
    assert uno.count("Utente:") == prompts.PER_TURNO


def test_nessun_esempio_e_un_saluto():
    """Con un saluto fra gli esempi, la risposta a "ciao" era l'esempio (4/4)."""
    for c in prompts.esempi("metis_v2"):
        utente = c.splitlines()[0].lower()
        assert not any(s in utente for s in ("ciao", "buongiorno", "buonasera", "salve", "hey"))


def test_una_persona_senza_repertorio_resta_com_e():
    assert prompts.per_turno("metis_v1", 3) == prompts.carica("metis_v1")


def test_la_memoria_chiede_la_persona_per_la_domanda():
    viste = []
    m = Memoria(system="riserva", persona=lambda n: viste.append(n) or f"persona {n}")
    m.aggiungi("user", "uno")
    m.aggiungi("assistant", "a")
    m.aggiungi("user", "due")
    assert m.messaggi()[0]["content"] == "persona 2"


def test_una_persona_che_esplode_non_ferma_il_turno():
    def rotta(n):
        raise RuntimeError("file sparito")

    m = Memoria(system="riserva", persona=rotta)
    m.aggiungi("user", "ciao")
    assert m.messaggi()[0]["content"] == "riserva"


def test_la_v2_da_del_lei_e_sa_cosa_sa_fare():
    testo = prompts.carica("metis_v2")
    assert "dai del lei" in testo and "COSA SAI FARE" in testo and "cercare sul web" in testo
    assert "signore" in testo
    assert "non ho capito cosa fare" not in testo.lower()      # il ripiego e' nel codice


# === Giorno 5: il router =================================================================

from metis.llm.toolcall import chiesta  # noqa: E402
from tests.test_dopo_le_prove import router as router_senza_llm  # noqa: E402


@pytest.mark.parametrize("frase,atteso", [
    ("Qual è il David di Caravaggio che ti piace di più?", False),   # la seduta
    ("Qual è il tuo film preferito?", False),
    ("Che ne pensi delle elezioni?", False),
    ("Quanto vale oggi il bitcoin?", True),
    ("Ultime notizie su OpenAI", True),
])
def test_le_opinioni_non_vanno_sul_web(frase, atteso):
    assert chiesta({"tool": "web_search", "query": "x"}, frase) is atteso


@pytest.mark.parametrize("frase,atteso", [
    ("bravissimo, hai schippato una pubblicità su youtube.", False),   # la seduta
    ("clicca su Contatti", True),
    ("premi il pulsante Invia", True),
    ("seleziona la seconda voce", True),
])
def test_il_clic_per_nome_vuole_il_verbo(frase, atteso):
    assert chiesta({"tool": "click_element", "elemento": "x", "tipo": "pulsante"}, frase) is atteso


def test_cerca_sul_web_cerca_la_domanda_di_prima():
    storia = [{"role": "system", "content": "p"},
              {"role": "user", "content": "Qual è il David di Caravaggio più famoso?"},
              {"role": "assistant", "content": "Informazione non presente nei sistemi."},
              {"role": "user", "content": "Cerca sul web."}]
    d = router_senza_llm().decidi("Cerca sul web.", storia)
    assert d.origine == "fast_path"
    assert d.calls == ({"tool": "web_search", "query": "Qual è il David di Caravaggio più famoso?"},)


def test_cerca_sul_web_ripetuto_salta_i_cerca_di_prima():
    storia = [{"role": "user", "content": "chi ha vinto il Giro d'Italia"},
              {"role": "user", "content": "cercalo"},
              {"role": "user", "content": "cerca su internet"}]
    d = router_senza_llm().decidi("cerca su internet", storia)
    assert d.calls[0]["query"] == "chi ha vinto il Giro d'Italia"


def test_cerca_sul_web_senza_domanda_prima_decide_il_router():
    d = router_senza_llm().decidi("cerca sul web", [{"role": "user", "content": "cerca sul web"}])
    assert d.calls == ()


def test_una_ricerca_tolta_per_opinione_non_e_una_frase_non_capita():
    from tests.test_router import _tool_router

    d = _tool_router([{"tool": "web_search", "query": "David Caravaggio"}]).decidi(
        "Qual è il David di Caravaggio che ti piace di più?")
    assert d.calls == () and d.tolte == ()
