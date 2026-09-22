"""I comandi custom: validazione, persistenza, ricarica a caldo.

IL TEST CHE CONTA E' QUELLO CHE RIFIUTA
Un comando custom e' un pezzo di configurazione che qualcuno scrive una
volta e pronuncia per mesi. Se contiene un errore, l'errore non si
manifesta quando lo si scrive: si manifesta a voce, la prima volta che
serve davvero, e in quel momento nessuno collega le due cose. Per questo
`valida()` e' severa e l'editor non lascia salvare.

Il caricamento invece e' tollerante, e i test lo verificano separatamente:
un file con un comando rotto deve far partire Metis lo stesso, con un
avviso. Le due politiche sono opposte apposta.
"""
import json

import pytest

from metis.memory.commands import (
    Comando,
    Errore,
    Libreria,
    carica,
    normalizza,
    salva,
    valida,
)
from metis.tools.registry import carica_tutti

REG = carica_tutti()


@pytest.fixture
def percorso(tmp_path):
    p = tmp_path / "commands.json"
    p.write_text('{"comandi": []}', encoding="utf-8")
    return p


def buono(ident="prova", **extra):
    return {"id": ident, "frasi": ["fai la prova"],
            "azioni": [{"tool": "get_telemetry"}], **extra}


# --- validazione: cosa passa -------------------------------------------------

def test_un_comando_minimo_e_valido():
    c = valida(buono(), REG)
    assert c.id == "prova" and c.strumenti == ("get_telemetry",)
    assert c.risposta is None


def test_le_frasi_vengono_normalizzate_alla_validazione():
    c = valida(buono(frasi=["Fai la PROVA, però!"]), REG)
    assert c.normalizzate == ("fai la prova pero",)


def test_piu_azioni_in_ordine():
    c = valida(buono(azioni=[{"tool": "open_application", "app": "vscode"},
                             {"tool": "open_application", "app": "github_desktop"}]),
               REG)
    assert [a["app"] for a in c.azioni] == ["vscode", "github_desktop"]


def test_i_valori_di_default_dello_schema_vengono_riempiti():
    """La validazione passa dallo schema vero, quindi `window` vuoto c'e'
    anche se l'utente non l'ha scritto: e' lo stesso oggetto che vedra' il
    broker, non un dizionario parallelo."""
    c = valida(buono(azioni=[{"tool": "maximize_window"}]), REG)
    assert c.azioni[0] == {"tool": "maximize_window", "window": ""}


# --- validazione: cosa si rifiuta, ed e' il punto del file -------------------

def test_strumento_inesistente():
    """Criterio di uscita di M4, in forma eseguibile."""
    with pytest.raises(Errore) as e:
        valida(buono(azioni=[{"tool": "delete_file", "path": "C:/"}]), REG)
    assert "non esiste" in str(e.value) and "delete_file" in str(e.value)


def test_strumento_senza_corpo():
    """`send_email` e' registrato ma arriva in M6: prometterlo in un comando
    custom significa un rifiuto a voce fra qualche settimana."""
    with pytest.raises(Errore) as e:
        valida(buono(azioni=[{"tool": "send_email", "to": "a@b.it",
                              "subject": "x", "body": "y"}]), REG)
    assert "non ha ancora un corpo" in str(e.value)


def test_argomenti_non_conformi_allo_schema():
    with pytest.raises(Errore) as e:
        valida(buono(azioni=[{"tool": "open_application", "app": "photoshop"}]), REG)
    assert "argomenti non validi" in str(e.value)


def test_campo_inventato_rifiutato():
    """`extra="forbid"` vale anche qui: un campo ignorato in silenzio e'
    un'ipotesi non verificata su cosa il comando credeva di fare."""
    with pytest.raises(Errore):
        valida(buono(azioni=[{"tool": "get_telemetry", "quando": "subito"}]), REG)


def test_un_url_che_e_un_percorso_locale_viene_rifiutato():
    """L'unico campo di tutto il perimetro che assomiglia a un percorso.
    Se `file://` passasse di qui, il vincolo principale del progetto
    sarebbe aggirabile scrivendo un JSON."""
    for cattivo in ("file:///C:/Users/Marco/Documenti",
                    "javascript:alert(1)", "data:text/html,x",
                    "C:/Users/Marco", "https://sito.it/ x"):
        with pytest.raises(Errore):
            valida(buono(azioni=[{"tool": "open_url", "url": cattivo}]), REG)


def test_senza_frasi():
    with pytest.raises(Errore) as e:
        valida(buono(frasi=[]), REG)
    assert "almeno una frase" in str(e.value)


def test_una_frase_di_sola_punteggiatura():
    """Si normalizza a stringa vuota, che poi corrisponderebbe a tutto."""
    with pytest.raises(Errore) as e:
        valida(buono(frasi=["!!!"]), REG)
    assert "si riduce a niente" in str(e.value)


def test_senza_azioni():
    with pytest.raises(Errore) as e:
        valida(buono(azioni=[]), REG)
    assert "almeno un'azione" in str(e.value)


def test_troppe_azioni():
    with pytest.raises(Errore) as e:
        valida(buono(azioni=[{"tool": "get_telemetry"}] * 7), REG)
    assert "troppe" in str(e.value)


def test_senza_identificativo():
    with pytest.raises(Errore):
        valida(buono(id=""), REG)


# --- caricamento tollerante --------------------------------------------------

def test_un_comando_rotto_non_impedisce_gli_altri(percorso):
    percorso.write_text(json.dumps({"comandi": [
        buono("sano"),
        {"id": "rotto", "frasi": ["x"], "azioni": [{"tool": "inesistente"}]},
    ]}), encoding="utf-8")
    comandi, avvisi = carica(REG, percorso)
    assert [c.id for c in comandi] == ["sano"]
    assert len(avvisi) == 1 and "rotto" in avvisi[0]


def test_un_file_illeggibile_non_impedisce_l_avvio(percorso):
    percorso.write_text("{ questo non e' json", encoding="utf-8")
    comandi, avvisi = carica(REG, percorso)
    assert comandi == [] and len(avvisi) == 1


def test_file_mancante(tmp_path):
    assert carica(REG, tmp_path / "niente.json") == ([], [])


def test_identificativo_ripetuto(percorso):
    percorso.write_text(json.dumps({"comandi": [buono("x"), buono("x")]}),
                        encoding="utf-8")
    comandi, avvisi = carica(REG, percorso)
    assert len(comandi) == 1 and "ripetuto" in avvisi[0]


def test_frase_condivisa_fra_due_comandi_produce_un_avviso(percorso):
    """Non un errore: il file resta usabile e vince il primo. Ma se nessuno
    lo dicesse, il secondo comando non si attiverebbe mai e sembrerebbe
    rotto."""
    percorso.write_text(json.dumps({"comandi": [
        buono("uno", frasi=["fai la cosa"]),
        buono("due", frasi=["Fai la cosa!"]),
    ]}), encoding="utf-8")
    comandi, avvisi = carica(REG, percorso)
    assert len(comandi) == 2
    assert any("vincera' il primo" in a for a in avvisi)


# --- persistenza -------------------------------------------------------------

def test_salva_e_ricarica_conserva_tutto(percorso):
    originale = valida(buono(risposta="Fatto, capo."), REG)
    salva([originale], percorso)
    tornati, avvisi = carica(REG, percorso)
    assert avvisi == []
    assert tornati[0].come_dizionario() == originale.come_dizionario()


def test_il_file_salvato_e_leggibile_da_un_umano(percorso):
    salva([valida(buono(frasi=["città perché"]), REG)], percorso)
    testo = percorso.read_text(encoding="utf-8")
    assert "città" in testo, "gli accenti non devono uscire come \\uXXXX"
    assert "\n  " in testo, "indentato"


# --- la libreria viva --------------------------------------------------------

def test_aggiungi_modifica_elimina(percorso):
    lib = Libreria(REG, percorso)
    assert len(lib) == 0

    lib.aggiungi(buono("uno"))
    assert [c.id for c in lib] == ["uno"]

    lib.modifica("uno", buono("uno", risposta="Ecco."))
    assert lib.get("uno").risposta == "Ecco."

    lib.elimina("uno")
    assert len(lib) == 0


def test_non_si_aggiunge_due_volte_lo_stesso_id(percorso):
    lib = Libreria(REG, percorso)
    lib.aggiungi(buono("uno"))
    with pytest.raises(Errore) as e:
        lib.aggiungi(buono("uno"))
    assert "esiste gia'" in str(e.value)


def test_un_salvataggio_rifiutato_non_tocca_il_file(percorso):
    """Il caso in cui la severita' di `valida` conta davvero: se scrivesse
    prima di validare, un errore nell'editor cancellerebbe il lavoro."""
    lib = Libreria(REG, percorso)
    lib.aggiungi(buono("sano"))
    prima = percorso.read_text(encoding="utf-8")
    with pytest.raises(Errore):
        lib.aggiungi(buono("rotto", azioni=[{"tool": "inesistente"}]))
    assert percorso.read_text(encoding="utf-8") == prima
    assert [c.id for c in lib] == ["sano"]


def test_modificare_o_eliminare_cio_che_non_esiste(percorso):
    lib = Libreria(REG, percorso)
    with pytest.raises(Errore):
        lib.modifica("fantasma", buono("fantasma"))
    with pytest.raises(Errore):
        lib.elimina("fantasma")


def test_ogni_scrittura_incrementa_il_contatore_di_ricariche(percorso):
    """E' il segnale su cui il router si accorge di dover rileggere: senza,
    la ricarica a caldo non funziona e nessun test lo direbbe."""
    lib = Libreria(REG, percorso)
    n = lib.ricariche
    lib.aggiungi(buono("uno"))
    assert lib.ricariche == n + 1


def test_normalizza_e_la_stessa_funzione_del_router():
    from metis.core.router import normalizza as dal_router

    assert dal_router is normalizza


def test_un_comando_costruito_a_mano_resta_confrontabile():
    a = Comando("x", ("frase",), ({"tool": "get_telemetry"},))
    b = Comando("x", ("frase",), ({"tool": "get_telemetry"},),
                normalizzate=("frase",))
    assert a == b, "le normalizzate sono derivate: non devono pesare sull'uguaglianza"
