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
