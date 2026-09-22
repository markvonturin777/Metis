"""Gli slot di riferimento, cioe' i quattro casi anaforici del piano.

I casi di §4.4 sono descritti come sequenze parlate — "Apri Chrome" poi
"spostalo sull'altro schermo". Qui si prova la meta' che non dipende dal
modello: che dopo la prima frase lo slot contenga la cosa giusta, e che il
blocco iniettato la nomini. Se questa meta' sbaglia, nessuna taratura del
prompt puo' rimediare, perche' il modello leggerebbe un contesto falso.

L'altra meta' — il modello riesce a usarli? — si misura in
`benchmarks/prova_anafora.py`, con Qwen vero.
"""
from __future__ import annotations

from metis.memory.slots import Slots


class R:
    """Un Result quanto basta: il broker vero e' provato altrove."""

    def __init__(self, ok=True, value=None, tool=None):
        self.ok = ok
        self.value = value or {}
        self.tool = tool


def s() -> Slots:
    return Slots()


# --- scrittura ----------------------------------------------------------------

def test_solo_gli_esiti_riusciti_aggiornano_gli_slot():
    """Un'azione rifiutata non ha cambiato il mondo. Registrarla farebbe
    riferire i pronomi successivi a qualcosa che non e' mai successo."""
    x = s()
    x.osserva({"tool": "open_application", "app": "chrome"}, R(ok=False))
    assert x.vuoto


def test_un_result_malformato_non_rompe_il_turno():
    """Gira subito dopo un'azione riuscita: un'eccezione qui farebbe fallire
    qualcosa che era andato bene, che e' il caso peggiore."""
    x = s()
    x.osserva({"tool": "open_application"}, object())
    assert x.vuoto


# --- caso 1: "Apri Chrome" -> "spostalo sull'altro schermo" -------------------

def test_caso_1_app_aperta_e_finestra():
    x = s()
    x.osserva({"tool": "open_application", "app": "chrome"},
              R(value={"app": "chrome"}))
    assert x.ultima_app_aperta == "Chrome"
    assert x.ultima_finestra.titolo == "Chrome"
    assert "Chrome" in x.blocco()


def test_caso_1_poi_lo_spostamento_aggiorna_la_finestra():
    x = s()
    x.osserva({"tool": "open_application", "app": "chrome"}, R(value={"app": "chrome"}))
    x.osserva({"tool": "move_window_to_monitor", "window": "Chrome",
               "monitor": "altro"},
              R(value={"titolo": "Chrome - Investing.com", "monitor": 1,
                       "processo": "chrome.exe"}))
    assert x.ultima_finestra.monitor == 1
    assert "monitor 2" in x.blocco()


# --- caso 2: "Cerca le news" -> "aprimi il primo risultato" -------------------

def test_caso_2_la_prima_fonte_diventa_citabile():
    x = s()
    x.osserva({"tool": "web_search", "query": "news mercati"},
              R(value={"query": "news mercati",
                       "risultati": [{"url": "https://a.it/1"},
                                     {"url": "https://b.it/2"}]}))
    assert x.ultimo_argomento_cercato == "news mercati"
    assert x.ultima_fonte_url == "https://a.it/1"


def test_caso_2_una_lettura_sposta_la_fonte():
    x = s()
    x.osserva({"tool": "web_fetch", "url": "https://c.it/3"},
              R(value={"url": "https://c.it/3"}))
    assert x.ultima_fonte_url == "https://c.it/3"


# --- caso 3: "Massimizza VS Code" -> "no, rimpiccioliscila" -------------------

def test_caso_3_l_ultima_azione_e_ricostruibile():
    """Il blocco deve contenere il NOME dello strumento, non una parafrasi:
    e' quello che permette al router di scegliere l'opposto."""
    x = s()
    x.osserva({"tool": "maximize_window", "window": "Visual Studio Code"},
              R(value={"titolo": "Visual Studio Code", "comando": "massimizza"}))
    assert x.ultima_azione["tool"] == "maximize_window"
    assert 'maximize_window(window="Visual Studio Code")' in x.blocco()


def test_caso_3_una_lettura_non_cancella_l_ultima_azione():
    """"Massimizza VS Code" -> "che finestre ho aperte?" -> "no,
    rimpiccioliscila": la terza frase si riferisce alla prima."""
    x = s()
    x.osserva({"tool": "maximize_window", "window": "Code"},
              R(value={"titolo": "Code"}))
    x.osserva({"tool": "list_windows"}, R(value={"totale": 7}))
    assert x.ultima_azione["tool"] == "maximize_window"


def test_una_ricerca_non_diventa_l_ultima_azione():
    x = s()
    x.osserva({"tool": "web_search", "query": "x"}, R(value={"query": "x"}))
    assert x.ultima_azione is None


# --- il blocco iniettato ------------------------------------------------------

def test_il_blocco_vuoto_e_vuoto():
    """"Ultima app aperta: nessuna" occupa token per dire che non c'e'
    niente da dire, e su un modello piccolo invita a menzionare l'assenza."""
    assert s().blocco() == ""


def test_il_blocco_ha_l_intestazione_che_il_prompt_si_aspetta():
    x = s()
    x.vista_finestra("Blocco note", "notepad.exe")
    assert x.blocco().startswith("[CONTESTO CORRENTE]")


def test_il_blocco_pieno_sta_nel_suo_budget():
    """§1.3 del piano: ~150 token. Se sforasse, li toglierebbe alla memoria
    conversazionale senza che nessuno se ne accorga."""
    from metis.llm.grounding import BUDGET, conta_token

    x = s()
    x.vista_finestra("x" * 200, "processo.exe", monitor=1)
    x.osserva({"tool": "open_application", "app": "vscode"}, R(value={"app": "vscode"}))
    x.osserva({"tool": "web_search", "query": "y" * 200},
              R(value={"query": "y" * 200,
                       "risultati": [{"url": "https://" + "z" * 300}]}))
    x.osserva({"tool": "move_window_to_monitor", "window": "w" * 200,
               "monitor": "altro"}, R(value={"titolo": "w" * 200, "monitor": 1}))
    x.ultimo_dispositivo = "d" * 100
    assert conta_token(x.blocco()) <= BUDGET["slot"]


# --- la cattura al risveglio --------------------------------------------------

def test_la_finestra_vista_al_risveglio_entra_negli_slot():
    x = s()
    x.vista_finestra("Documento - Word", "winword.exe")
    assert x.ultima_finestra.titolo == "Documento - Word"


def test_la_cattura_non_cancella_un_riferimento_piu_preciso():
    """Se nel turno prima si e' agito su quella finestra, il monitor gia'
    noto vale piu' di un None."""
    x = s()
    x.osserva({"tool": "move_window_to_monitor", "window": "Code",
               "monitor": "altro"}, R(value={"titolo": "Code", "monitor": 1}))
    x.vista_finestra("Code", "code.exe")
    assert x.ultima_finestra.monitor == 1


def test_una_finestra_senza_titolo_non_si_registra():
    x = s()
    x.vista_finestra("", "qualcosa.exe")
    assert x.ultima_finestra is None


def test_reset():
    x = s()
    x.osserva({"tool": "open_application", "app": "chrome"}, R(value={"app": "chrome"}))
    x.reset()
    assert x.vuoto and x.blocco() == ""


def test_come_dizionario_e_serializzabile():
    """La GUI lo legge da un altro thread e lo mostra: se `asdict` fallisse
    sul lock, il pannello del contesto sarebbe vuoto senza dirlo."""
    import json

    x = s()
    x.vista_finestra("Code", "code.exe", monitor=0)
    assert json.dumps(x.come_dizionario())
