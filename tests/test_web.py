"""Ricerca e recupero: la cache, il backoff, la degradazione, l'estrazione.

Nessun test qui tocca la rete. Non e' una scelta di velocita': un test che
dipende da DuckDuckGo fallisce quando DuckDuckGo limita, cioe' proprio nelle
condizioni che questo modulo esiste per gestire, e a quel punto non si
distingue piu' un difetto del codice da un difetto della giornata.

Cio' che va provato contro la rete vera sta in `benchmarks/prova_web.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.injection import CASI, Server  # noqa: E402

from metis.tools import web  # noqa: E402
from metis.tools.registry import Rifiuto  # noqa: E402


@pytest.fixture
def cache(tmp_path):
    return web.Cache(tmp_path / "c.db")


def _r(n=2):
    return [web.Risultato(f"t{i}", f"https://e{i}.it/a", f"corpo {i}")
            for i in range(n)]


# --- normalizzazione della chiave --------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Le NEWS sui mercati!", "le news sui mercati"),
    ("perché  il  BTP", "perche il btp"),
    ("  spazi   in   mezzo  ", "spazi in mezzo"),
])
def test_query_diverse_a_vedersi_sono_la_stessa_chiave(a, b):
    """Pagare due volte il rate limiter per la stessa domanda e' il modo piu'
    semplice di farlo scattare."""
    assert web.normalizza_query(a) == web.normalizza_query(b)


def test_query_diverse_restano_diverse():
    """Meta-test: una normalizzazione che appiattisce tutto e' una cache che
    risponde sempre la stessa cosa."""
    assert web.normalizza_query("btp decennale") != web.normalizza_query("btp triennale")


# --- cache -------------------------------------------------------------------

def test_la_cache_risponde_entro_il_ttl(cache):
    cache.scrivi("k", _r())
    assert [x.url for x in cache.leggi("k")] == ["https://e0.it/a", "https://e1.it/a"]


def test_la_cache_scade(tmp_path):
    c = web.Cache(tmp_path / "c.db", ttl_s=-1)
    c.scrivi("k", _r())
    assert c.leggi("k") is None


def test_la_cache_evita_la_seconda_chiamata(cache, monkeypatch):
    chiamate = []
    monkeypatch.setattr(web, "MOTORI", (("finto", lambda q, n: chiamate.append(q) or _r()),))
    web.cerca("btp decennale", cache=cache)
    web.cerca("BTP  Decennale!", cache=cache)
    assert len(chiamate) == 1, "la seconda query normalizzata ha ricomprato la ricerca"


def test_anche_lo_zero_risultati_si_mette_in_cache(cache, monkeypatch):
    """Una ricerca senza risultati e' una risposta del motore, e ripeterla
    costa quanto una con risultati. E' il caso che si dimentica."""
    chiamate = []
    monkeypatch.setattr(web, "MOTORI", (("finto", lambda q, n: chiamate.append(q) or []),))
    assert web.cerca("xyzzy plugh", cache=cache) == []
    assert web.cerca("xyzzy plugh", cache=cache) == []
    assert len(chiamate) == 1


# --- backoff e fallback ------------------------------------------------------

def test_backoff_tre_tentativi_poi_il_motore_dopo(cache):
    tentativi = []
    pause = []

    def rotto(q, n):
        tentativi.append("ddg")
        raise RuntimeError("Ratelimit")

    def buono(q, n):
        tentativi.append("fallback")
        return _r()

    web.MOTORI, salvati = (("ddg", rotto), ("fallback", buono)), web.MOTORI
    try:
        out = web.cerca("x", cache=cache, attendi=pause.append)
    finally:
        web.MOTORI = salvati
    assert len(out) == 2
    assert tentativi == ["ddg", "ddg", "ddg", "fallback"]
    assert pause == [1.0, 3.0], "l'ultimo tentativo ha aspettato per nessuno"


def test_non_si_riprova_per_una_chiave_mancante(cache):
    """La chiave non comparira' fra un secondo: tre tentativi sono tredici
    secondi di attesa per un esito gia' noto."""
    tentativi = []

    def senza_chiave(q, n):
        tentativi.append(1)
        raise RuntimeError("nessuna chiave Brave")

    web.MOTORI, salvati = (("brave", senza_chiave),), web.MOTORI
    try:
        with pytest.raises(Rifiuto):
            web.cerca("x", cache=cache, attendi=lambda s: None)
    finally:
        web.MOTORI = salvati
    assert tentativi == [1]


def test_ricerca_fallita_e_un_rifiuto_dichiarato_non_una_lista_vuota(cache):
    """Lo scenario peggiore del progetto, in forma eseguibile.

    Una lista vuota direbbe al modello "non ho trovato niente", e un modello
    che non trova niente risponde a memoria. Un `Rifiuto` diventa DENIED nel
    broker e una frase precisa nella voce di Metis.
    """
    def rotto(q, n):
        raise RuntimeError("Ratelimit")

    web.MOTORI, salvati = (("ddg", rotto),), web.MOTORI
    try:
        with pytest.raises(Rifiuto) as e:
            web.cerca("quanto vale il btp oggi", cache=cache, attendi=lambda s: None)
    finally:
        web.MOTORI = salvati
    assert str(e.value) == web.NON_RAGGIUNGIBILE


def test_una_query_vuota_non_arriva_alla_rete(cache):
    with pytest.raises(Rifiuto):
        web.cerca("   ", cache=cache)


# --- recupero ----------------------------------------------------------------

def test_solo_https(cache):
    """Non e' una preferenza: `http://` e `file://` sono lo stesso problema
    visto da due distanze diverse."""
    p = web.scarica("http://127.0.0.1:1/x", cache=cache)
    assert not p.ok and p.motivo == "solo https"


def test_il_server_del_corpus_e_raggiungibile_e_viene_rifiutato_lo_stesso(cache):
    """Il rifiuto di `http` provato contro un server che risponde davvero.

    Un test che punta a una porta chiusa non distingue "rifiutato per lo
    schema" da "non ha risposto nessuno", ed e' proprio quella la differenza
    che interessa.
    """
    import httpx

    with Server() as s:
        url = s.url(CASI[0])
        assert httpx.get(url, timeout=5).status_code == 200
        p = web.scarica(url, cache=cache)
    assert not p.ok and p.motivo == "solo https"


def test_la_pagina_in_cache_non_si_riscarica(cache):
    cache.scrivi_pagina(web.Pagina(url="https://e.it/a", titolo="T",
                                   testo="contenuto", ok=True))
    p = web.scarica("https://e.it/a", cache=cache)
    assert p.ok and p.testo == "contenuto" and p.motivo == "cache"


def test_scarica_molte_conserva_l_ordine(monkeypatch, cache):
    """L'ordine di uscita e' quello di rilevanza, non quello di arrivo: e'
    da quello che dipende chi viene troncato quando il budget stringe."""
    import time as _t

    def finta(url, c=None):
        _t.sleep(0.05 if url.endswith("0") else 0.0)
        return web.Pagina(url=url, testo="x", ok=True)

    monkeypatch.setattr(web, "scarica", finta)
    urls = ["https://a.it/0", "https://b.it/1", "https://c.it/2"]
    assert [p.url for p in web.scarica_molte(urls, cache)] == urls


def test_scarica_molte_su_lista_vuota():
    assert web.scarica_molte([]) == []


# --- estrazione --------------------------------------------------------------

def test_i_commenti_html_non_entrano_nel_testo():
    _, testo = web.estrai("<html><body><p>visibile</p><!-- nascosto --></body></html>")
    assert "visibile" in testo and "nascosto" not in testo


@pytest.mark.parametrize("stile", [
    "color:#ffffff;background:#ffffff",
    "display:none",
    "visibility:hidden",
    "font-size:0",
    "opacity:0",
])
def test_il_testo_invisibile_non_entra_nel_testo(stile):
    html = f'<html><body><p>visibile</p><p style="{stile}">segreto</p></body></html>'
    _, testo = web.estrai(html)
    assert "visibile" in testo and "segreto" not in testo


def test_gli_attributi_non_entrano_nel_testo():
    html = ('<html><body><p>visibile</p>'
            '<img src="a.png" alt="segreto" title="anche questo"></body></html>')
    _, testo = web.estrai(html)
    assert "segreto" not in testo and "anche questo" not in testo


def test_script_e_noscript_non_entrano_nel_testo():
    html = ("<html><body><p>visibile</p><script>var segreto=1</script>"
            "<noscript>anche questo</noscript></body></html>")
    _, testo = web.estrai(html)
    assert "segreto" not in testo and "anche questo" not in testo


def test_il_titolo_si_estrae():
    titolo, _ = web.estrai("<html><head><title>Il titolo</title></head>"
                           "<body><p>corpo</p></body></html>")
    assert titolo == "Il titolo"


def test_bs4_e_una_dipendenza():
    """`_ripulisci` degrada senza BeautifulSoup invece di sollevare, e la
    degradazione lascia passare il testo nascosto. E' accettabile solo
    perche' non deve mai succedere."""
    import bs4  # noqa: F401
    import lxml  # noqa: F401


def test_elementi_invisibili_annidati_non_fanno_cadere_la_pulizia():
    """M7, trovato dal soak su ilmeteo.it: un contenitore nascosto con dentro
    altri elementi con `style` o `hidden`. Distrutto il genitore, i figli
    restavano nella lista di `find_all` e il `.get` su di loro sollevava
    AttributeError — la pagina diventava un errore dello strumento."""
    from metis.tools.web import _ripulisci

    html = ("<html><body><p>visibile</p>"
            '<div style="display:none"><span style="color:red">nascosto</span>'
            '<em hidden>anche</em><b aria-hidden="true">pure</b></div>'
            '<section hidden><i style="visibility:hidden">x</i></section>'
            "</body></html>")
    pulito = _ripulisci(html)
    assert "visibile" in pulito
    assert "nascosto" not in pulito and "anche" not in pulito


# --- PHASE1: le pubblicita' non sono risultati -------------------------------

ANNUNCIO = "https://www.bing.com/aclick?ld=e8eXxJ7OjXw5HkTEzaqIqLx" + "TVUCUz4TacPaqfJ_Lw8" * 40


@pytest.mark.parametrize("url,pubblicita", [
    (ANNUNCIO, True),
    ("https://bing.com/aclick?ld=corto", True),
    ("https://duckduckgo.com/y.js?ad_provider=bing&u3=x", True),
    ("https://adclick.g.doubleclick.net/pcs/click?x", True),
    ("https://www.googleadservices.com/pagead/aclk?sa=L", True),
    ("https://www.bing.com/search?q=chatbot", False),
    ("https://botpress.com/it/blog/how-to-build-your-own-ai-chatbot", False),
    ("https://www.aranzulla.it/come-creare-un-chatbot-1595755.html", False),
])
def test_riconosce_le_pubblicita(url, pubblicita):
    assert web.e_pubblicita(url) is pubblicita


def test_le_pubblicita_non_occupano_i_posti_delle_fonti(cache, monkeypatch):
    """Il caso visto in esercizio: i primi due risultati erano annunci di Bing
    da 942 e 622 caratteri. `web_fetch` li rifiutava, ma occupavano due dei
    tre posti da fonte."""
    chieste = []

    def motore(q, n):
        chieste.append(n)
        annunci = [web.Risultato("Chatbot IA", ANNUNCIO, ""),
                   web.Risultato("Create AI Chatbots", "https://www.bing.com/aclick?ld=x", "")]
        return annunci + _r(n - 2)

    monkeypatch.setattr(web, "MOTORI", (("finto", motore),))
    risultati = web.cerca("come creare un chatbot ai", cache=cache)
    assert chieste == [web.MAX_RISULTATI + web.MARGINE_PUBBLICITA]
    assert len(risultati) == web.MAX_RISULTATI
    assert not any("aclick" in r.url for r in risultati)
    assert risultati[0].url == "https://e0.it/a"          # l'ordine resta


def test_un_link_troppo_lungo_per_web_fetch_non_e_un_risultato(cache, monkeypatch):
    lungo = "https://esempio.it/" + "a" * 600
    monkeypatch.setattr(web, "MOTORI", (("finto", lambda q, n: [
        web.Risultato("lungo", lungo, "")] + _r()),))
    assert [r.url for r in web.cerca("qualcosa", cache=cache)] == \
        ["https://e0.it/a", "https://e1.it/a"]


def test_la_cache_scritta_prima_del_filtro_si_filtra_in_lettura(cache):
    cache.scrivi("vecchia query", [web.Risultato("annuncio", ANNUNCIO, "")] + _r())
    assert [r.url for r in web.cerca("vecchia query", cache=cache)] == \
        ["https://e0.it/a", "https://e1.it/a"]
