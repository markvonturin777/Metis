"""PHASE2 — cio' che e' emerso dalla prima prova a voce dell'utente.

Le frasi qui sotto sono quelle trascritte davvero il 2026-09-26
(`CONVOS/Metis_20260926_1920.md`), non esempi inventati. Tre difetti:

1. Metis diceva di aver agito senza averlo fatto: "Cliccato l'ottantuno",
   "Ecco 99 numeri", "Indietro", e nessuno strumento nel log;
2. le storpiature di "mostra i numeri" e dei numeri non si riconoscevano, e
   una volta "Mastrami i numeri" li ha NASCOSTI;
4. "chiudi la prima scheda di Chrome" ha ridotto Chrome a icona, e "torna
   indietro" non esisteva.
"""
import pytest

from metis.core import frasi_chiuse
from metis.core.frasi_chiuse import CHIEDI_COMANDO, CHIEDI_NUMERO
from metis.core.risposte import descrivi_sequenza
from metis.core.router import Router, normalizza
from metis.llm.toolcall import CHIARIRE_SE_TOLTO, chiesta
from metis.tools.registry import carica_tutti

REG = carica_tutti()


def router(numeri=False):
    return Router(REG, comandi=[], usa_llm=False, numeri_a_schermo=lambda: numeri)


# --- 2. le storpiature, misurate ------------------------------------------------------

@pytest.mark.parametrize("detto", [
    "Mostra in umere.", "Mastra in numeri.", "Mastrami i numeri.", "Mostrain Numery.",
    "Mastering numeria.", "Mastra in numeria.", "Mostra inumere.", "Mostrami i numeri.",
    # PHASE4: segnalata dall'utente dal pannello delle frasi (2026-09-28).
    "ma stra minumere.", "mastra i numeri.",
])
def test_le_storpiature_di_mostra_i_numeri(detto):
    d = router().decidi(detto)
    assert d.origine == "fast_path" and d.calls == ({"tool": "mostra_numeri"},), detto


@pytest.mark.parametrize("detto", ["mostra i numeri di telefono", "mostrami come si fa",
                                   "mastica bene"])
def test_ma_non_tutto_quello_che_comincia_per_mostra(detto):
    assert frasi_chiuse.riconosci(normalizza(detto)) is None


@pytest.mark.parametrize("detto,n", [
    ("clicca su ottanto uno.", 81), ("clicca su ottantuna", 81), ("Clicca i 60.", 60),
    ("clicca il settanto", 70), ("clicca l'ottant'uno", 81), ("click su 64.", 64),
    ("clicca sul ventuna", 21),
])
def test_i_numeri_storpiati(detto, n):
    assert router().decidi(detto).calls == ({"tool": "clicca_numero", "numero": n},)


def test_senza_verbo_e_un_clic_solo_con_i_numeri_a_schermo():
    assert router(numeri=True).decidi("su ottantuna.").calls == (
        {"tool": "clicca_numero", "numero": 81},)
    assert router(numeri=True).decidi("sul 60").calls == ({"tool": "clicca_numero", "numero": 60},)
    assert router(numeri=False).decidi("sul 60").calls == ()


@pytest.mark.parametrize("detto", ["sei", "tre", "sette per favore", "il sei nazioni"])
def test_un_numero_nudo_non_e_un_clic(detto):
    """"Sei" da solo non clicca il 6, nemmeno con i numeri a schermo."""
    assert all(c.get("tool") != "clicca_numero" for c in router(numeri=True).decidi(detto).calls)


# --- 1. niente azioni dichiarate e non fatte ------------------------------------------

@pytest.mark.parametrize("detto,domanda", [
    ("clicca su oltra un tunnel.", CHIEDI_NUMERO),
    ("sul tunnel", CHIEDI_NUMERO),
    ("fai i numeri", CHIEDI_COMANDO),
    ("chiudi quella cosa della scheda li'", CHIEDI_COMANDO),
])
def test_un_comando_non_capito_diventa_una_domanda(detto, domanda):
    d = router().decidi(detto)
    assert d.calls == () and d.chiarimento == domanda, detto


@pytest.mark.parametrize("detto", ["come stai", "che tempo fa domani", "mi spieghi le api",
                                   "raccontami una barzelletta"])
def test_la_conversazione_resta_conversazione(detto):
    assert router().decidi(detto).chiarimento is None


def test_il_numero_non_detto_tolto_dal_router_diventa_una_domanda():
    """Nei due clic della prova il router aveva proposto clicca_numero(81) e il
    controllo "numero detto" l'aveva tolto. Giusto; ma poi la frase finiva alla
    conversazione. Ora c'e' la domanda."""
    assert not chiesta({"tool": "clicca_numero", "numero": 81}, "clicca su oltra un tunnel")
    assert "numero" in CHIARIRE_SE_TOLTO["clicca_numero"]


def test_l_orchestratore_dice_la_domanda_senza_generare(monkeypatch):
    from metis.core.orchestrator import Azioni
    from metis.core.state_machine import Event
    from tests.test_orchestrator import _segmento, make

    o, player = make(text="clicca su oltra un tunnel")
    generato = []
    o.d.llm_stream = lambda *a, **k: generato.append(1) or iter(())
    r = router()
    o.d.azioni = Azioni(decidi=lambda t, s: r.decidi(t), esegui=lambda c, u=False: None,
                        descrivi=descrivi_sequenza, richiede_conferma=lambda c: False)
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert generato == [], "la conversazione non doveva nemmeno partire"
    assert o.history[-1] == {"role": "assistant", "content": CHIEDI_NUMERO}
    assert len(player.queue) == 1
    assert o.sm.state.name == "IN_ASCOLTO"


def test_la_persona_non_dichiara_azioni():
    """Da PHASE6 la persona in uso e' `metis_v2`, e la protezione vera e' la
    guardia nel codice (`risposte.dichiara_azione`, test_conversazione.py):
    qui resta il controllo che la persona lo dica."""
    from metis.llm import prompts

    assert "non dici mai di aver" in prompts.carica().lower()


# --- 4. schede e indietro ---------------------------------------------------------------

@pytest.mark.parametrize("detto,tasti", [
    ("Torna indietro.", [["alt", "left"]]),
    ("indietro", [["alt", "left"]]),
    ("torna alla pagina precedente", [["alt", "left"]]),
    ("vai avanti", [["alt", "right"]]),
    ("chiudi la scheda", [["ctrl", "w"]]),
    ("chiudi questa scheda di Chrome", [["ctrl", "w"]]),
    ("chiudi la prima aperta scheda di Chrome.", [["ctrl", "1"], ["ctrl", "w"]]),
    ("chiudi l'ultima scheda", [["ctrl", "9"], ["ctrl", "w"]]),
    ("riapri la scheda chiusa", [["ctrl", "shift", "t"]]),
    ("apri una nuova scheda", [["ctrl", "t"]]),
])
def test_schede_e_navigazione(detto, tasti):
    d = router().decidi(detto)
    assert d.origine == "fast_path"
    assert [c["keys"] for c in d.calls] == tasti and all(
        c["tool"] == "press_hotkey" for c in d.calls)
    for c in d.calls:
        REG.get("press_hotkey").schema.model_validate(c)


def test_ridurre_a_icona_chiede_un_verbo():
    m = {"tool": "minimize_window", "window": "chrome"}
    assert not chiesta(m, "chiudi la prima aperta scheda di chrome")
    for detto in ("riduci a icona chrome", "minimizza la finestra", "no, rimpiccioliscila",
                  "nascondi vs code"):
        assert chiesta(m, detto), detto


@pytest.mark.parametrize("tasti,frase", [
    (["alt", "left"], "Indietro."), (["ctrl", "w"], "Scheda chiusa."),
    (["ctrl", "shift", "t"], "Scheda riaperta."),
])
def test_le_frasi_dei_tasti(tasti, frase):
    from metis.security.audit import Outcome
    from metis.security.broker import Result

    r = Result(True, Outcome.OK, "esecuzione", "eseguito",
               value={"tasti": "+".join(tasti)}, tool="press_hotkey")
    assert descrivi_sequenza([r]) == frase


def test_chiudere_la_prima_scheda_si_dice_una_volta():
    from metis.security.audit import Outcome
    from metis.security.broker import Result

    rs = [Result(True, Outcome.OK, "esecuzione", "eseguito", value={"tasti": t},
                 tool="press_hotkey") for t in ("ctrl+1", "ctrl+w")]
    assert descrivi_sequenza(rs) == "Scheda chiusa."


# --- lo scorrimento a blocchi (2026-09-28) ------------------------------------------------

@pytest.mark.parametrize("detto,tasti", [
    ("scorri giù", [["pagedown"]]),
    ("Scorri in basso.", [["pagedown"]]),
    ("scorri su", [["pageup"]]),
    ("scorri verso l'alto", [["pageup"]]),
    ("scorri verso il basso", [["pagedown"]]),
    ("scorri in alto", [["pageup"]]),
    ("scorri giù di una pagina", [["pagedown"]]),
    ("pagina giù", [["pagedown"]]),
    ("scendi", [["pagedown"]]),
    ("sali", [["pageup"]]),
    ("vai giù", [["pagedown"]]),
    ("scorri giù di tre pagine", [["pagedown"]] * 3),
    ("scorri su di 2 blocchi", [["pageup"]] * 2),
    ("vai in cima", [["home"]]),
    ("torna all'inizio della pagina", [["home"]]),
    ("vai in fondo", [["end"]]),
    ("in fondo alla pagina", None),
])
def test_scorrimento_a_blocchi(detto, tasti):
    d = router().decidi(detto)
    if tasti is None:
        assert all(c.get("tool") != "press_hotkey" for c in d.calls), detto
        return
    assert d.origine == "fast_path", detto
    assert [c["keys"] for c in d.calls] == tasti, detto
    for c in d.calls:
        REG.get("press_hotkey").schema.model_validate(c)


@pytest.mark.parametrize("detto,verso", [
    ("scorri un po' giù", "giu"), ("scorri giù un po'", "giu"), ("scorri piano su", "su"),
])
def test_il_passo_piccolo_resta_la_rotellina(detto, verso):
    assert router().decidi(detto).calls == ({"tool": "scroll", "verso": verso},)


@pytest.mark.parametrize("detto", ["scorri giù di dieci pagine", "vai su youtube",
                                   "vai giù in cantina", "fine"])
def test_non_sono_scorrimenti(detto):
    assert all(c.get("tool") != "press_hotkey" for c in router().decidi(detto).calls), detto


@pytest.mark.parametrize("tasti,frase", [
    ("pagedown", "Giù."), ("pageup", "Su."), ("home", "In cima."), ("end", "In fondo."),
])
def test_le_frasi_dello_scorrimento(tasti, frase):
    from metis.security.audit import Outcome
    from metis.security.broker import Result

    rs = [Result(True, Outcome.OK, "esecuzione", "eseguito", value={"tasti": tasti},
                 tool="press_hotkey")] * 2
    assert descrivi_sequenza(rs) == frase           # tre pagine: si dice una volta
