"""Fast-path e instradamento.

La proprieta' che conta non e' la velocita': e' che il fast-path salti il
MODELLO e non i CONTROLLI. Se esistesse una via che aggira anche solo uno
stadio del broker, sarebbe quella percorsa dai comandi piu' frequenti, cioe'
esattamente quelli che vale la pena controllare.

In M4 un comando puo' contenere piu' di un'azione, quindi `fast_path`
restituisce un `Comando` invece di una singola chiamata. La proprieta'
verificata qui sotto non cambia: cio' che esce di qui e' materiale per il
broker, non un permesso di eseguire.
"""
import json
from pathlib import Path

import pytest

from metis.core.router import Comando, Router, normalizza
from metis.memory.commands import Libreria, carica
from metis.tools.registry import carica_tutti

REG = carica_tutti()


def comandi_veri():
    c, _ = carica(REG)
    return c


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
    return Router(REG, comandi=comandi_veri(), usa_llm=False)


def test_corrispondenza_esatta(router):
    c = router.fast_path("apri vs code")
    assert c.azioni == ({"tool": "open_application", "app": "vscode"},)


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


def test_vince_la_frase_configurata_piu_lunga():
    """Con frasi che si contengono a vicenda, la piu' corta e' la meno
    specifica: se vincesse lei, la piu' lunga non si attiverebbe mai."""
    corto = Comando("corto", ("apri il codice",),
                    ({"tool": "open_application", "app": "vscode"},))
    lungo = Comando("lungo", ("apri il codice e il git",),
                    ({"tool": "open_application", "app": "vscode"},
                     {"tool": "open_application", "app": "github_desktop"}))
    # L'ordine nella lista e' quello sfavorevole apposta.
    r = Router(REG, comandi=[corto, lungo], usa_llm=False)
    assert r.fast_path("apri il codice e il git").id == "lungo"
    assert r.fast_path("apri il codice").id == "corto"


def test_le_azioni_restituite_sono_copie(router):
    """Chi le riceve le passa al broker, che le muta durante la validazione:
    senza copia, il secondo uso dello stesso comando sarebbe diverso."""
    a = router.decidi("apri vs code").calls[0]
    a["app"] = "manomesso"
    b = router.decidi("apri vs code").calls[0]
    assert b["app"] == "vscode"


# --- coerenza fra configurazione e strumenti reali --------------------------

def test_ogni_comando_configurato_esiste_davvero():
    """Un refuso in commands.json produrrebbe un comando che il broker
    rifiuta sempre, e l'utente lo scoprirebbe parlando."""
    adapter = REG.adapter()
    for c in comandi_veri():
        for azione in c.azioni:
            assert azione["tool"] in REG, f"{azione['tool']} non e' nel registro"
            adapter.validate_python(azione)   # solleva se gli argomenti non vanno


def test_i_comandi_configurati_sono_tutti_eseguibili():
    """Niente fast-path verso strumenti che in questa iterazione non hanno
    ancora un corpo: sarebbero promesse non mantenute."""
    for c in comandi_veri():
        for azione in c.azioni:
            spec = REG.get(azione["tool"])
            assert spec.implemented, f"{spec.name} non e' ancora implementato"


def test_il_file_dei_comandi_si_carica_senza_avvisi():
    """Un avviso qui significa un comando che l'utente ha perso senza
    accorgersene: la frase c'e' nel file e Metis non la riconosce."""
    _, avvisi = carica(REG)
    assert avvisi == []


def test_il_file_dei_comandi_e_json_valido():
    dati = json.loads(Path("config/commands.json").read_text(encoding="utf-8"))
    assert dati["comandi"], "nessun comando configurato"


# --- instradamento -----------------------------------------------------------

def test_il_fast_path_ha_la_precedenza(router):
    d = router.decidi("apri vs code")
    assert d.e_strumento and d.origine == "fast_path"


def test_un_comando_composto_produce_piu_azioni(router):
    d = router.decidi("inizia a lavorare")
    assert [a["tool"] for a in d.calls] == ["open_application",
                                            "open_application"]
    assert d.risposta, "il comando dichiara una frase sua e deve arrivare"


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
        def decidi(self, testo, storia=None, slot=""):
            from metis.llm.toolcall import Decisione
            chiamate.append(testo)
            return Decisione((), "llm", 1.0)

    r = Router(REG, comandi=comandi_veri(), tool_router=FintoLlm())
    r.decidi("apri vs code")
    assert chiamate == [], "l'LLM e' stato consultato per un comando noto"
    r.decidi("che ne pensi")
    assert chiamate == ["che ne pensi"]


def test_router_senza_comandi_manda_tutto_all_llm():
    r = Router(REG, comandi=[], usa_llm=False)
    assert r.fast_path("apri vs code") is None


def test_comando_costruito_a_mano():
    r = Router(REG, comandi=[Comando("magia", ("prova magica",),
                                     ({"tool": "get_telemetry"},))],
               usa_llm=False)
    c = r.fast_path("fai la prova magica adesso")
    assert c is not None and c.azioni == ({"tool": "get_telemetry"},)


# --- ricarica a caldo --------------------------------------------------------

def test_i_comandi_salvati_valgono_subito(tmp_path):
    """Il criterio di uscita "nuovo comando senza riavvio", dal lato del
    router: nessun segnale, nessun riavvio, solo la libreria che cambia."""
    percorso = tmp_path / "commands.json"
    percorso.write_text('{"comandi": []}', encoding="utf-8")
    lib = Libreria(REG, percorso)
    r = Router(REG, libreria=lib, usa_llm=False)
    assert r.fast_path("fai il caffe") is None

    lib.aggiungi({"id": "caffe", "frasi": ["fai il caffe"],
                  "azioni": [{"tool": "get_telemetry"}]})
    assert r.fast_path("fai il caffe") is not None
