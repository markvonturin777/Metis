"""Le date: validarle e dirle in italiano.

Il riferimento temporale e' sempre fissato a mano: un test che usa l'ora vera
passa o fallisce a seconda di quando lo si lancia, e quello che fallisce
alle 23:59 del 31 dicembre non lo si riproduce piu'.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from metis.core import tempo

# Mercoledi' 23 settembre 2026, 21:40.
ORA = datetime(2026, 9, 23, 21, 40)


@pytest.mark.parametrize("quando,atteso", [
    (datetime(2026, 9, 23, 22, 0), "oggi alle 22:00"),
    (datetime(2026, 9, 24, 17, 0), "domani, giovedì 24 settembre, alle 17:00"),
    (datetime(2026, 9, 25, 9, 0), "dopodomani, venerdì 25 settembre, alle 09:00"),
    (datetime(2026, 9, 28, 9, 0), "lunedì 28 settembre, alle 09:00"),
    (datetime(2027, 1, 4, 9, 0), "lunedì 4 gennaio 2027, alle 09:00"),
])
def test_in_parole(quando, atteso):
    assert tempo.in_parole(quando, ORA) == atteso


def test_il_giorno_della_settimana_c_e_anche_con_domani():
    """E' il pezzo che fa accorgere l'utente che il modello ha sbagliato:
    "domani, sabato" detto di mercoledi' suona sbagliato subito."""
    assert "giovedì" in tempo.in_parole(datetime(2026, 9, 24, 9, 0), ORA)


def test_una_data_passata_si_rifiuta():
    motivo = tempo.motivo_rifiuto("2026-09-23T21:00", ORA)
    assert motivo and "passato" in motivo


def test_fra_venti_secondi_e_un_errore_non_una_richiesta():
    assert tempo.motivo_rifiuto("2026-09-23T21:40", ORA) is not None


def test_oltre_un_anno_si_rifiuta():
    motivo = tempo.motivo_rifiuto("2027-12-01T09:00", ORA)
    assert motivo and "anno" in motivo


def test_una_data_valida_passa():
    assert tempo.motivo_rifiuto("2026-09-24T17:00", ORA) is None


@pytest.mark.parametrize("sbagliata", ["domani alle 17", "2026-09-24 17:00",
                                       "2026-09-24T17:00:00", "2026-13-40T99:00", ""])
def test_un_formato_sbagliato_si_rifiuta(sbagliata):
    assert tempo.motivo_rifiuto(sbagliata, ORA) is not None


def test_il_contesto_temporale_dice_giorno_e_formato():
    """Senza questa riga nel prompt del router, "domani" e' il giorno dopo la
    data di addestramento del modello."""
    riga = tempo.contesto_temporale(ORA)
    assert "mercoledì 23 settembre 2026" in riga
    assert "2026-09-23T21:40" in riga


def test_il_router_riceve_la_data_di_oggi():
    from metis.llm.toolcall import ToolRouter
    from metis.tools.registry import carica_tutti

    prompt = ToolRouter.__new__(ToolRouter)
    prompt.registry = carica_tutti()
    assert "[ADESSO]" in prompt._prompt()


def test_il_calendario_dice_i_giorni_da_copiare():
    """Misurato in M6: senza calendario Qwen trasformava "lunedi'" detto di
    mercoledi' in SABATO. Il modello sa leggere, non sa fare l'aritmetica
    dei giorni della settimana."""
    righe = tempo.contesto_temporale(ORA)
    assert "lunedì = 2026-09-28" in righe
    assert "venerdì = 2026-09-25" in righe
    assert "giovedì = 2026-09-24 (domani)" in righe
    assert "OGGI mercoledì = 2026-09-23" in righe
    # Il mercoledi' fra sette giorni si chiama diversamente: con lo stesso
    # nome di oggi, "fra due ore" di mercoledi' diventava la settimana dopo.
    assert "mercoledì della settimana prossima = 2026-09-30" in righe
    assert "\n  mercoledì = " not in righe


def test_gli_intervalli_scavalcano_l_ora_gia_calcolati():
    """Misurato in M6: alle 21:40, "tra mezz'ora" dava 22:40 tre volte su tre.
    Sommare minuti che scavalcano l'ora e' l'aritmetica che il modello
    sbaglia; il risultato scritto si copia."""
    righe = tempo.contesto_temporale(ORA)
    assert "fra mezz'ora = 2026-09-23T22:10" in righe
    assert "fra due ore = 2026-09-23T23:40" in righe
    assert "fra tre ore = 2026-09-24T00:40" in righe          # scavalca il giorno
