"""PHASE2 — frasi chiuse con un parametro, riconosciute senza il modello.

La proprieta' che conta e' la stretta della porta: una frase senza la parola
che la giustifica ("youtube") deve passare al router, e cio' che esce deve
essere una chiamata valida per lo schema del broker, non un'eccezione.
"""
import pytest

from metis.core.frasi_chiuse import riconosci
from metis.core.router import Router, normalizza
from metis.tools.registry import carica_tutti

REG = carica_tutti()


def _r(frase):
    return riconosci(normalizza(frase))


@pytest.mark.parametrize("frase,query", [
    ("Apri Chrome e mettimi su YouTube un video rilassante", "video rilassante"),
    ("apri chrome e aprimi youtube su una canzone rilassante", "canzone rilassante"),
    ("mettimi su youtube un po' di musica jazz", "musica jazz"),
    ("metti su un po di lofi su youtube", "lofi"),
    ("Metis, riproduci su YouTube Bohemian Rhapsody, per favore", "bohemian rhapsody"),
    ("fammi sentire su youtube la sigla di Naruto", "sigla di naruto"),
    ("apri youtube su un documentario sui gatti", "documentario sui gatti"),
])
def test_riproduci_su_youtube(frase, query):
    assert _r(frase) == ({"tool": "riproduci_youtube", "query": query},)


@pytest.mark.parametrize("frase,pezzo", [
    ("cerca su youtube ricette di pasta", "search_query=ricette+di+pasta"),
    ("per favore cercami tutorial di python su youtube", "search_query=tutorial+di+python"),
    ("apri chrome e cerca su YouTube più bei gol", "search_query=piu+bei+gol"),
])
def test_cerca_su_youtube_apre_i_risultati(frase, pezzo):
    (c,) = _r(frase)
    assert c["tool"] == "open_url"
    assert c["url"].startswith("https://www.youtube.com/results?") and pezzo in c["url"]


@pytest.mark.parametrize("frase", [
    "fammi sentire bohemian rhapsody",          # niente "youtube": al router
    "cerca ricette di pasta",
    "apri youtube",
    "mettimi su youtube",                       # niente da cercare
    "cosa ne pensi di youtube",
    "cerca su youtube",
    "metti chrome sull altro schermo",
    "apri chrome e mettimi su youtube youtube",
    "",
])
def test_il_resto_va_al_router(frase):
    assert _r(frase) is None


def test_una_query_senza_caratteri_strani_ma_lunga_si_accorcia():
    (c,) = _r("mettimi su youtube " + "musica " * 40)
    assert len(c["query"]) <= 120


@pytest.mark.parametrize("frase", [
    "cerca su youtube ricette di pasta", "mettimi su youtube un video rilassante",
    "cerca su youtube città d'arte & musei", "apri youtube su " + "a" * 300,
])
def test_ogni_chiamata_prodotta_e_valida_per_lo_schema(frase):
    for c in _r(frase):
        REG.get(c["tool"]).schema.model_validate(c)


def test_nel_router_sono_un_percorso_rapido_dopo_i_comandi_dell_utente():
    from metis.core.router import Comando

    mio = Comando("mio", ("mettimi su youtube la mia playlist",), ({"tool": "get_telemetry"},))
    r = Router(REG, comandi=[mio], usa_llm=False)
    assert r.decidi("mettimi su youtube la mia playlist").calls == ({"tool": "get_telemetry"},)
    d = r.decidi("apri chrome e mettimi su youtube un video rilassante")
    assert d.origine == "fast_path"
    assert d.calls == ({"tool": "riproduci_youtube", "query": "video rilassante"},)
