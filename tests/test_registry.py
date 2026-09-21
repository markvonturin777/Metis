"""Il registro: una lista sola per il modello e per il broker.

La proprieta' che vale la pena difendere e' proprio quella — che siano la
stessa lista. Se divergessero, il modello imparerebbe a chiedere cose che il
broker rifiuta, oppure il broker accetterebbe cose che nessuno ha descritto.
"""
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from metis.security.audit import Tier
from metis.security.guards import Guard
from metis.tools.registry import Registry


class Uno(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["uno"]


class Due(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["due"]


def reg_con(*coppie) -> Registry:
    r = Registry("prova")
    for tier, schema, implemented in coppie:
        @r.strumento(tier, schema, implemented=implemented)
        def _h(call, _s=schema):
            """Documentazione dello strumento."""
            return {"eco": _s.__name__}
    return r


# --- registrazione -----------------------------------------------------------

def test_il_nome_viene_dallo_schema_non_a_mano():
    """Scriverlo due volte e' la premessa perche' un giorno differiscano."""
    r = reg_con((Tier.T0, Uno, True))
    assert r.nomi() == ["uno"]
    assert r.get("uno").schema is Uno


def test_registrare_due_volte_lo_stesso_strumento_e_un_errore():
    r = reg_con((Tier.T0, Uno, True))
    with pytest.raises(ValueError, match="gia' registrato"):
        @r.strumento(Tier.T1, Uno)
        def _altro(call):
            return {}


def test_strumento_sconosciuto_ritorna_none():
    """Deny-by-default comincia da qui: nessuna eccezione, nessun default."""
    assert reg_con((Tier.T0, Uno, True)).get("inesistente") is None


def test_contiene_e_lunghezza():
    r = reg_con((Tier.T0, Uno, True), (Tier.T1, Due, True))
    assert "uno" in r and "tre" not in r and len(r) == 2
    assert {s.name for s in r} == {"uno", "due"}


def test_la_descrizione_viene_dalla_docstring():
    r = reg_con((Tier.T0, Uno, True))
    assert r.get("uno").descrizione == "Documentazione dello strumento."


def test_le_guardie_sono_una_tupla_immutabile():
    """Una lista condivisa si modifica da fuori, e le guardie sono l'ultima
    cosa che si vuole modificabile a runtime."""
    r = Registry("g")
    guardie = [Guard("x", lambda call: None)]

    @r.strumento(Tier.T2, Uno, guards=tuple(guardie))
    def _h(call):
        return {}

    guardie.append(Guard("y", lambda call: "no"))
    assert len(r.get("uno").guards) == 1


# --- cio' che si offre al modello --------------------------------------------

def test_i_non_implementati_restano_nel_registro_ma_non_nell_offerta():
    """Il broker deve conoscerli per poter dire 'capacita' non ancora
    disponibile' invece di 'strumento sconosciuto', che sarebbe una bugia."""
    r = reg_con((Tier.T0, Uno, True), (Tier.T3, Due, False))
    assert "due" in r
    assert [s.name for s in r.disponibili()] == ["uno"]
    assert "due" not in str(r.json_schema())


def test_schema_json_con_un_solo_strumento():
    schema = reg_con((Tier.T0, Uno, True)).json_schema()
    assert "uno" in str(schema)


def test_schema_json_con_piu_strumenti_e_discriminato():
    schema = reg_con((Tier.T0, Uno, True), (Tier.T1, Due, True)).json_schema()
    testo = str(schema)
    assert "uno" in testo and "due" in testo


def test_registro_vuoto_non_esplode():
    """All'avvio, prima che i moduli si importino, il registro e' vuoto."""
    r = Registry("vuoto")
    assert r.json_schema() == {} and r.adapter() is None and len(r) == 0


def test_registro_di_soli_non_implementati_non_offre_niente():
    r = reg_con((Tier.T3, Uno, False))
    assert r.json_schema() == {} and r.disponibili() == []


# --- validazione -------------------------------------------------------------

def test_l_adapter_copre_anche_i_non_implementati():
    r = reg_con((Tier.T0, Uno, True), (Tier.T3, Due, False))
    a = r.adapter()
    assert a.validate_python({"tool": "due"}).tool == "due"


def test_adapter_con_un_solo_strumento():
    a = reg_con((Tier.T0, Uno, True)).adapter()
    assert a.validate_python({"tool": "uno"}).tool == "uno"


def test_descrizione_per_prompt_ordinata_per_livello():
    r = reg_con((Tier.T1, Due, True), (Tier.T0, Uno, True))
    righe = r.descrizione_per_prompt().splitlines()
    assert righe[0].startswith("- uno (T0)")
    assert righe[1].startswith("- due (T1)")


def test_descrizione_per_prompt_ignora_i_non_implementati():
    r = reg_con((Tier.T0, Uno, True), (Tier.T3, Due, False))
    assert "due" not in r.descrizione_per_prompt()
