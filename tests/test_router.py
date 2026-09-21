"""Fast-path e instradamento.

La proprieta' che conta non e' la velocita': e' che il fast-path salti il
MODELLO e non i CONTROLLI. Se esistesse una via che aggira anche solo uno
stadio del broker, sarebbe quella percorsa dai comandi piu' frequenti, cioe'
esattamente quelli che vale la pena controllare.
"""
import json
from pathlib import Path

import pytest

from metis.core.router import Comando, Router, carica_comandi, normalizza
from metis.tools.registry import carica_tutti

REG = carica_tutti()


# --- normalizzazione ---------------------------------------------------------

@pytest.mark.parametrize("dato,atteso", [
    ("Apri VS Code!", "apri vs code"),
    ("  APRI   vs    code  ", "apri vs code"),
    ("Che finestra è in primo piano?", "che finestra e in primo piano"),
    ("perché, però, città", "perche pero citta"),
    ("", ""),
])
def test_normalizza(dato, atteso):
    assert normalizza(dato) == atteso


# --- fast path ---------------------------------------------------------------

@pytest.fixture
def router():
    return Router(REG, comandi=carica_comandi(), usa_llm=False)


def test_corrispondenza_esatta(router):
    assert router.fast_path("apri vs code") == {"tool": "open_application",
                                                "app": "vscode"}


def test_corrispondenza_con_cortesie_intorno(router):
    """Il parlato aggiunge parole: 'per favore apri vs code, grazie'."""
    assert router.fast_path("per favore apri vs code grazie") is not None


def test_maiuscole_accenti_e_punteggiatura_non_contano(router):
    assert router.fast_path("Apri VS Code!") is not None


def test_una_parola_sola_non_basta(router):
    """Il contenimento va in un verso solo: la frase configurata dentro il
    detto. Al contrario, 'apri' aprirebbe qualcosa a caso."""
    assert router.fast_path("apri") is None
    assert router.fast_path("vs") is None


def test_frase_estranea_non_corrisponde(router):
    for frase in ("che ne pensi del progetto", "raccontami una barzelletta",
                  "che ore sono", ""):
        assert router.fast_path(frase) is None, frase


def test_la_chiamata_restituita_e_una_copia(router):
    """Chi la riceve la passa al broker, che la muta durante la validazione:
    senza copia, il secondo uso dello stesso comando sarebbe diverso."""
    a = router.fast_path("apri vs code")
    a["app"] = "manomesso"
    b = router.fast_path("apri vs code")
    assert b["app"] == "vscode"


# --- coerenza fra configurazione e strumenti reali --------------------------

def test_ogni_comando_configurato_esiste_davvero():
    """Un refuso in commands.json produrrebbe un comando che il broker
    rifiuta sempre, e l'utente lo scoprirebbe parlando."""
    adapter = REG.adapter()
    for c in carica_comandi():
        nome = c.call.get("tool")
        assert nome in REG, f"{nome} non e' nel registro"
        adapter.validate_python(c.call)      # solleva se gli argomenti non vanno


def test_i_comandi_configurati_sono_tutti_eseguibili():
    """Niente fast-path verso strumenti che in questa iterazione non hanno
    ancora un corpo: sarebbero promesse non mantenute."""
    for c in carica_comandi():
        spec = REG.get(c.call["tool"])
        assert spec.implemented, f"{spec.name} non e' ancora implementato"


def test_nessuna_frase_duplicata_fra_comandi_diversi():
    """Due comandi che rispondono alla stessa frase: vince il primo, e quale
    sia il primo dipende dall'ordine nel file. Meglio accorgersene qui."""
    visto: dict[str, str] = {}
    for c in carica_comandi():
        for f in c.frasi:
            assert f not in visto, f"{f!r} porta sia a {visto[f]} sia a {c.call['tool']}"
            visto[f] = c.call["tool"]


def test_il_file_dei_comandi_e_json_valido():
    dati = json.loads(Path("config/commands.json").read_text(encoding="utf-8"))
    assert dati["comandi"], "nessun comando configurato"


# --- instradamento -----------------------------------------------------------

def test_il_fast_path_ha_la_precedenza(router):
    d = router.decidi("apri vs code")
    assert d.e_strumento and d.origine == "fast_path"


def test_il_fast_path_e_rapido(router):
    """Il senso di esistere del fast-path: 5-30 ms contro 400+."""
    import time

    t0 = time.perf_counter()
    for _ in range(100):
        router.fast_path("per favore apri vs code")
    ms = (time.perf_counter() - t0) * 1000 / 100
    assert ms < 5, f"{ms:.2f} ms per frase"


def test_senza_llm_una_frase_sconosciuta_diventa_conversazione(router):
    d = router.decidi("raccontami qualcosa")
    assert not d.e_strumento


def test_il_router_conta_cosa_ha_fatto(router):
    router.decidi("apri vs code")
    router.decidi("ciao")
    assert router.stats()["fast_path"] == 1


def test_llm_consultato_solo_se_il_fast_path_manca():
    chiamate = []

    class FintoLlm:
        def decidi(self, testo, storia=None):
            from metis.llm.toolcall import Decisione
            chiamate.append(testo)
            return Decisione(None, "llm", 1.0)

    r = Router(REG, comandi=carica_comandi(), tool_router=FintoLlm())
    r.decidi("apri vs code")
    assert chiamate == [], "l'LLM e' stato consultato per un comando noto"
    r.decidi("che ne pensi")
    assert chiamate == ["che ne pensi"]


def test_comandi_da_file_mancante():
    assert carica_comandi(Path("config/non_esiste.json")) == []


def test_router_senza_comandi_manda_tutto_all_llm():
    r = Router(REG, comandi=[], usa_llm=False)
    assert r.fast_path("apri vs code") is None


def test_comando_costruito_a_mano():
    r = Router(REG, comandi=[Comando(("prova magica",), {"tool": "get_telemetry"})],
               usa_llm=False)
    assert r.fast_path("fai la prova magica adesso") == {"tool": "get_telemetry"}
