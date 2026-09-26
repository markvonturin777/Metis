"""La segmentazione in frasi e' il punto dove lo streaming vive o muore:
se un chunk resta indietro, il TTS parte tardi e la latenza percepita salta.
"""
import pytest
from metis.llm.client import split_sentences


@pytest.mark.parametrize(
    "testo, chunk_attesi, resto_atteso",
    [
        # frase lunga: esce subito
        ("I sistemi sono operativi. Tutto in ordine.",
         ["I sistemi sono operativi."], "Tutto in ordine."),
        # troppo corta: resta in buffer, uscira' come coda
        ("Si.", [], "Si."),
        # frasi corte consecutive: si ACCUMULANO in un chunk solo
        ("Domanda? Risposta! Terza frase molto lunga davvero.",
         ["Domanda? Risposta! Terza frase molto lunga davvero."], ""),
        # niente punteggiatura: tutto in buffer
        ("Sto ancora scrivendo questa frase senza mai chiuderla",
         [], "Sto ancora scrivendo questa frase senza mai chiuderla"),
        # piu' chunk in un colpo
        ("Prima frase abbastanza lunga da uscire. Seconda frase altrettanto lunga da uscire. Coda",
         ["Prima frase abbastanza lunga da uscire.",
          "Seconda frase altrettanto lunga da uscire."], "Coda"),
        # i puntini di sospensione contano come fine frase; entrambe superano
        # la soglia, quindi escono come due chunk distinti
        ("Mi lasci riflettere un momento… Ecco la risposta che cercava.",
         ["Mi lasci riflettere un momento…", "Ecco la risposta che cercava."], ""),
    ],
)
def test_split(testo, chunk_attesi, resto_atteso):
    chunk, resto = split_sentences(testo)
    assert chunk == chunk_attesi
    assert resto == resto_atteso


def test_nessun_testo_perduto():
    """Invariante: niente si perde fra chunk e resto."""
    testi = [
        "Domanda? Risposta! Terza frase molto lunga davvero.",
        "Prima frase abbastanza lunga da uscire. Poi. Altro. Fine della storia qui.",
        "Si. No. Forse. Dipende da come la si guarda, in fondo.",
    ]
    for t in testi:
        chunk, resto = split_sentences(t)
        ricomposto = " ".join([*chunk, resto]).strip()
        assert ricomposto.replace("  ", " ") == t.strip()


def test_decimali_non_spezzano_la_frase():
    """Un punto fra cifre non e' fine frase: 'sei virgola due' non deve
    diventare due chunk."""
    chunk, resto = split_sentences("La VRAM occupata e' di 6.58 GB su 8 totali.")
    assert chunk == ["La VRAM occupata e' di 6.58 GB su 8 totali."]
    assert resto == ""


def test_a_capo_normalizzati():
    """Il modello va a capo negli elenchi: per il TTS diventano pause
    innaturali a meta' chunk."""
    chunk, _ = split_sentences("Attivo.  \nBloccato.  \nInattivo. ")
    assert chunk == ["Attivo. Bloccato. Inattivo."]


def test_markdown_rimosso():
    """Il modello marca in grassetto anche sul canale vocale: osservato in
    4 turni su 30 in M0. Gli asterischi finirebbero dritti nel TTS."""
    chunk, _ = split_sentences("La **Bauhaus** fu una *scuola* di `design` moderna.")
    assert chunk == ["La Bauhaus fu una scuola di design moderna."]


def test_frase_lunga_spezzata_a_virgola():
    """Una frase di 130 caratteri ha il suo punto, ma aspettarlo costa
    ~700 ms. Oltre max_chars si spezza a un confine secondario."""
    lunga = (
        "Jackson Pollock apparteneva alla corrente dell'astrattismo, "
        "piu precisamente al movimento action painting, che enfatizzava il gesto."
    )
    chunk, resto = split_sentences(lunga, min_chars=25, max_chars=90)
    # il primo chunk esce subito, spezzato alla virgola: ~59 car invece di 132
    assert len(chunk[0]) <= 90
    assert chunk[0].endswith(",")
    assert len(chunk) == 2          # il resto della frase segue come secondo chunk
    assert " ".join([*chunk, resto]).strip().replace("  ", " ") == lunga


def test_max_chars_non_spezza_frasi_gia_brevi():
    """Se la frase finisce prima di max_chars, si usa la fine frase vera."""
    chunk, resto = split_sentences("I sistemi sono operativi, tutto bene.", 25, 90)
    assert chunk == ["I sistemi sono operativi, tutto bene."]
    assert resto == ""


def test_nessun_testo_perduto_con_max_chars():
    lunga = ("Prima parte della frase molto lunga, seconda parte altrettanto lunga, "
             "terza parte finale.")
    chunk, resto = split_sentences(lunga, 25, 60)
    assert " ".join([*chunk, resto]).strip().replace("  ", " ") == lunga


# --- M5: i marcatori delle fonti non si pronunciano --------------------------

def test_il_marcatore_non_arriva_al_tts():
    """Misurato in M5: su una fonte senza titolo Qwen chiude la risposta
    citando la fonte con il nome del DELIMITATORE, 3 volte su 3. Il prompt lo
    scoraggia; qui diventa impossibile."""
    from metis.llm.client import _clean

    assert _clean("La pagina parla dei BTP. FONTEESTERNANONFIDATA") == \
        "La pagina parla dei BTP."
    assert _clean("Testo. <<<FINE_FONTE_ESTERNA id=1>>>") == "Testo."
    assert _clean("Secondo <<<FONTE_ESTERNA_NON_FIDATA id=2 url=\"x\">>> il tasso") \
        == "Secondo il tasso"


def test_un_chunk_di_solo_marcatore_non_si_pronuncia():
    """Un PCM di zero campioni in coda al player e' un buco nella
    riproduzione, non un silenzio voluto."""
    from metis.llm.client import _clean, split_sentences

    assert _clean("<<<FINE_FONTE_ESTERNA id=1>>>") == ""
    chunk, _ = split_sentences(
        "Questa e' la risposta vera e completa. FONTEESTERNANONFIDATA. ")
    assert all(c for c in chunk), "un chunk vuoto e' finito in coda al TTS"


def test_la_pulizia_non_tocca_il_testo_normale():
    """Una regola che rovina le risposte buone e' una regola che si toglie."""
    from metis.llm.client import _clean

    normale = "Secondo Investing.com il rendimento e' al 3,75 per cento."
    assert _clean(normale) == normale


# --- PHASE1: link e indirizzi non si pronunciano -----------------------------

def test_il_link_markdown_si_pronuncia_come_nome():
    """Visto in esercizio: "descritto su [Tuttosemplice.com](https://blog...)",
    e Piper ha letto l'indirizzo intero."""
    from metis.llm.client import _clean

    detto = _clean("Questo e' descritto su [Tuttosemplice.com]"
                   "(https://blog.tuttosemplice.com/ai-sul-tuo-pc-gratis-e-offline/).")
    assert detto == "Questo e' descritto su Tuttosemplice.com."


def test_l_indirizzo_nudo_diventa_il_nome_del_sito():
    from metis.llm.client import _clean

    assert _clean("Fonti, per esempio https://www.bing.com/aclick?ld=e8_7G&u=aH.") == \
        "Fonti, per esempio bing."
    assert _clean("Vedi www.ilsole24ore.com/art/x_y, poi dimmi.") == \
        "Vedi ilsole24ore, poi dimmi."


def test_un_link_spezzato_fra_due_pezzi_non_lascia_l_indirizzo():
    """Il testo arriva al TTS a pezzi, e il taglio puo' cadere dentro il nome
    del link: nessuna delle due meta' contiene il link intero."""
    from metis.llm.client import _clean

    assert _clean("secondo [Il Sole") == "secondo Il Sole"
    assert _clean("24 Ore](https://www.ilsole24ore.com/a_b) dice cosi'.") == \
        "24 Ore dice cosi'."


def test_i_numeri_con_il_punto_non_sono_indirizzi():
    from metis.llm.client import _clean

    testo = "Il modello pesa 6.58 GB e la v1.2 e' uscita."
    assert _clean(testo) == testo


@pytest.mark.parametrize("url,nome", [
    ("https://blog.tuttosemplice.com/ai/", "tuttosemplice"),
    ("https://it.investing.com/news", "investing"),
    ("https://www.bbc.co.uk/news", "bbc"),
    ("ilsoftware.it", "ilsoftware"),
    ("non un indirizzo", ""),
])
def test_sito(url, nome):
    from metis.llm.client import sito

    assert sito(url) == nome
