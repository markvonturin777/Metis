"""Home Assistant, contro un server WebSocket che parla il protocollo vero.

I casi del piano §Giorno 8, quelli che non richiedono dispositivi veri:

    4  "Accendi la friggitrice"       conferma T3, accensione, limite attivo
    5  "La friggitrice e' accesa?"    dalla cache, senza conferma
    6  "Dai le crocchette al gatto"   limite giornaliero al quarto tentativo
    7  Home Assistant spento          indisponibilita' dichiarata, mai finta

E il caso che il piano chiama il peggiore: uno stato memorizzato spacciato
per attuale.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.casa import TOKEN, FintoHA  # noqa: E402

from metis.security.audit import AuditLog  # noqa: E402
from metis.security.broker import Broker  # noqa: E402
from metis.security.policies import Context  # noqa: E402
from metis.tools import home_assistant as casa  # noqa: E402
from metis.tools import scheduler as sch  # noqa: E402
from metis.tools.registry import Rifiuto, carica_tutti  # noqa: E402

REG = carica_tutti()
FRIGGITRICE = "switch.friggitrice_aria"
CROCCHETTE = "switch.distributore_crocchette"


def aspetta(condizione, secondi=5.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < secondi:
        if condizione():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def ha():
    s = FintoHA().avvia()
    yield s
    s.ferma()


@pytest.fixture
def client(ha):
    c = casa.ClienteHA(ha.url, TOKEN, backoff=(0.1,))
    c.avvia()
    assert c.attendi_connessione(5)
    casa.usa_cliente(c)
    yield c
    c.ferma()
    casa.usa_cliente(None)


@pytest.fixture
def registro(tmp_path):
    r = casa.Registro(tmp_path / "casa.db")
    casa.usa_registro(r)
    yield r
    casa.usa_registro(None)


@pytest.fixture
def pian(tmp_path):
    p = sch.Pianificatore(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    p.avvia(in_pausa=True)
    sch.usa_pianificatore(p)
    yield p
    p.ferma()
    sch.usa_pianificatore(None)


def broker(tmp_path, conferma=True, chiesti=None):
    def chiedi(spec, call):
        if chiesti is not None:
            chiesti.append(call.model_dump())
        return conferma

    return Broker(registry=REG, audit=AuditLog(tmp_path / "a.db")), \
        Context(chiedi_conferma=chiedi)


# --- configurazione e perimetro -------------------------------------------------

def test_la_configurazione_del_repository_si_carica():
    dispositivi, avvisi = casa.carica()
    assert set(dispositivi) == {"friggitrice", "crocchette", "videocamera"}
    assert avvisi == []
    assert dispositivi["friggitrice"].max_durata_min == 60
    assert dispositivi["crocchette"].max_erogazioni_giorno == 3


@pytest.mark.parametrize("detto,chiave", [
    ("friggitrice", "friggitrice"),
    ("la friggitrice ad aria", "friggitrice"),
    ("Crocchette", "crocchette"),
    ("il cibo del gatto", "crocchette"),
    ("telecamera", "videocamera"),
])
def test_i_nomi_detti_si_risolvono(detto, chiave):
    assert casa.risolvi(detto).chiave == chiave


def test_un_nome_inventato_si_rifiuta():
    with pytest.raises(Rifiuto):
        casa.risolvi("forno a microonde")


def test_il_modello_non_puo_nominare_un_entita_fuori_dal_file(tmp_path, client, ha):
    """Il finto Home Assistant ha `lock.porta_ingresso`. Il client la vede;
    nessuno strumento deve poterla toccare, perche' il perimetro di Metis e'
    il file di configurazione, non Home Assistant."""
    b, ctx = broker(tmp_path)
    for nome in ("lock.porta_ingresso", "porta ingresso", "serratura"):
        r = b.execute({"tool": "set_home_device", "dispositivo": nome,
                       "azione": "spegni"}, ctx)
        assert r.denied and r.stage == "guardie"
    assert not any(e == "lock.porta_ingresso" for _, _, e in ha.servizi)


def test_il_tier_non_si_abbassa_dal_file(tmp_path):
    f = tmp_path / "ha.toml"
    f.write_text('[entities.luce]\nentity_id = "light.sala"\nnome = "la luce"\n'
                 'tier = "T1"\n', encoding="utf-8")
    dispositivi, avvisi = casa.carica(f)
    assert "luce" in dispositivi
    assert any("sempre T3" in a for a in avvisi)
    assert REG.get("set_home_device").tier.value == "T3"


def test_una_riga_storta_non_spegne_la_domotica(tmp_path):
    f = tmp_path / "ha.toml"
    f.write_text('[entities.buona]\nentity_id = "switch.a"\n\n'
                 '[entities.storta]\nentity_id = "senza_punto"\n', encoding="utf-8")
    dispositivi, avvisi = casa.carica(f)
    assert list(dispositivi) == ["buona"] and len(avvisi) == 1


# --- caso 5: lettura dalla cache, T0, senza conferma ---------------------------

def test_lo_stato_si_legge_senza_conferma(tmp_path, client):
    chiesti = []
    b, ctx = broker(tmp_path, chiesti=chiesti)
    r = b.execute({"tool": "get_home_state", "dispositivo": "friggitrice"}, ctx)
    assert r.ok and r.value["stato"] == "off" and chiesti == []


def test_la_cache_segue_gli_eventi(tmp_path, client, ha):
    """Qualcuno accende la friggitrice dall'app del telefono: Metis lo sa
    senza chiederlo, perche' Home Assistant lo spinge."""
    ha.cambia(FRIGGITRICE, "on")
    assert aspetta(lambda: client.stato(FRIGGITRICE)["state"] == "on")


# --- caso 7 e la regola del modulo: mai uno stato vecchio ------------------------

def test_disconnesso_non_c_e_nessuno_stato(tmp_path, client, ha):
    """Il difetto peggiore del modulo: dire "spenta" di una friggitrice che
    qualcuno ha acceso mentre la connessione era giu'."""
    ha.cambia(FRIGGITRICE, "on")
    assert aspetta(lambda: client.stato(FRIGGITRICE)["state"] == "on")
    ha.ferma()
    assert aspetta(lambda: not client.disponibile)
    with pytest.raises(Rifiuto) as e:
        client.stato(FRIGGITRICE)
    assert "non risponde" in str(e.value)
    ha.avvia()                         # per il teardown della fixture


def test_hub_giu_si_dice_prima_di_chiedere_conferma(tmp_path, client, ha):
    """Chiedere "accendo la friggitrice?" e poi dire che l'hub non risponde
    fa sprecare una conferma, e insegna a darle senza leggere."""
    ha.ferma()
    assert aspetta(lambda: not client.disponibile)
    chiesti = []
    b, ctx = broker(tmp_path, chiesti=chiesti)
    r = b.execute({"tool": "set_home_device", "dispositivo": "friggitrice",
                   "azione": "accendi"}, ctx)
    assert r.denied and r.stage == "guardie" and "non risponde" in r.detail
    assert chiesti == []
    ha.avvia()


def test_si_riconnette_da_solo(tmp_path, client, ha):
    ha.ferma()
    assert aspetta(lambda: not client.disponibile)
    ha.avvia()
    assert client.attendi_connessione(5)
    assert client.stato(FRIGGITRICE) is not None
    assert client.disconnessioni >= 1


def test_senza_credenziali_lo_dice(tmp_path):
    casa.usa_cliente(None)
    b, ctx = broker(tmp_path)
    r = b.execute({"tool": "get_home_state", "dispositivo": "friggitrice"}, ctx)
    assert r.denied and "non e' configurato" in r.detail


def test_un_token_sbagliato_non_connette(ha):
    c = casa.ClienteHA(ha.url, "token-sbagliato", backoff=(0.1,))
    c.avvia()
    try:
        assert not c.attendi_connessione(1.0)
        assert "token" in c.ultimo_errore
    finally:
        c.ferma()


# --- caso 4: accensione con conferma e limite di durata ------------------------

def test_accendere_e_t3_e_chiede_conferma(tmp_path, client, ha, registro, pian):
    chiesti = []
    b, ctx = broker(tmp_path, conferma=False, chiesti=chiesti)
    r = b.execute({"tool": "set_home_device", "dispositivo": "friggitrice",
                   "azione": "accendi"}, ctx)
    assert r.denied and r.stage == "conferma" and len(chiesti) == 1
    assert ha.servizi == []


def test_accensione_confermata_e_spegnimento_programmato(tmp_path, client, ha,
                                                         registro, pian):
    b, ctx = broker(tmp_path)
    r = b.execute({"tool": "set_home_device", "dispositivo": "friggitrice",
                   "azione": "accendi"}, ctx)
    assert r.ok
    assert ha.servizi == [("switch", "turn_on", FRIGGITRICE)]
    assert aspetta(lambda: client.stato(FRIGGITRICE)["state"] == "on")

    spegnimenti = pian.voci(tipi=(sch.SPEGNI,))
    assert len(spegnimenti) == 1
    atteso = datetime.now() + timedelta(minutes=60)
    assert abs((spegnimenti[0].quando - atteso).total_seconds()) < 90


def test_chi_conferma_vede_il_limite(tmp_path, client, registro, pian):
    from metis.tools.registry import presentazione

    spec = REG.get("set_home_device")
    call = spec.schema.model_validate({"tool": "set_home_device",
                                       "dispositivo": "friggitrice",
                                       "azione": "accendi"})
    voci = presentazione(spec, call)
    assert voci["dispositivo"] == "la friggitrice ad aria"
    assert "60 minuti" in voci["limite"]


def test_lo_spegnimento_di_sicurezza_spegne(client, ha, pian):
    ha.cambia(FRIGGITRICE, "on")
    r = casa.spegni_per_sicurezza({"dispositivo": "friggitrice"})
    assert r["esito"] == "spento"
    assert ha.servizi[-1] == ("switch", "turn_off", FRIGGITRICE)


def test_lo_spegnimento_fallito_si_riprogramma(client, ha, pian):
    """Se all'ora prevista l'hub e' giu', il job scatta una volta e basta:
    senza riprogrammazione la friggitrice resterebbe accesa per sempre."""
    ha.ferma()
    assert aspetta(lambda: not client.disponibile)
    r = casa.spegni_per_sicurezza({"dispositivo": "friggitrice", "tentativo": 0})
    assert r["esito"] == "non riuscito" and r["riprova"]
    riprova = pian.voci(tipi=(sch.SPEGNI,))
    assert len(riprova) == 1
    assert riprova[0].quando <= datetime.now() + timedelta(minutes=1, seconds=5)
    ha.avvia()


def test_dopo_trenta_tentativi_si_smette_e_lo_si_dice(client, ha, pian):
    ha.ferma()
    assert aspetta(lambda: not client.disponibile)
    r = casa.spegni_per_sicurezza({"dispositivo": "friggitrice",
                                   "tentativo": casa.TENTATIVI_SPEGNIMENTO})
    assert r["esito"] == "non riuscito" and not r["riprova"]
    ha.avvia()


# --- caso 6: il limite del gatto ------------------------------------------------

def test_il_quarto_pasto_si_rifiuta(tmp_path, client, ha, registro, pian):
    b, ctx = broker(tmp_path)
    chiamata = {"tool": "set_home_device", "dispositivo": "crocchette",
                "azione": "accendi"}
    for i in range(3):
        r = b.execute(chiamata, ctx)
        assert r.ok, f"pasto {i + 1}: {r.detail}"
    quarto = b.execute(chiamata, ctx)
    assert quarto.denied and quarto.stage == "guardie"
    assert "limite" in quarto.detail
    assert sum(1 for _, s, e in ha.servizi if e == CROCCHETTE and s == "turn_on") == 3


def test_il_limite_sopravvive_al_riavvio(tmp_path, registro):
    """Riavviare Metis non deve azzerare il conto del gatto."""
    for _ in range(3):
        registro.registra("crocchette")
    assert casa.Registro(tmp_path / "casa.db").oggi("crocchette") == 3


def test_spegnere_non_consuma_il_limite(tmp_path, client, registro, pian):
    b, ctx = broker(tmp_path)
    b.execute({"tool": "set_home_device", "dispositivo": "crocchette",
               "azione": "spegni"}, ctx)
    assert registro.oggi("crocchette") == 0


# --- la difesa di M5 vale anche qui ---------------------------------------------

def test_una_pagina_web_non_accende_niente(tmp_path, client, ha, registro, pian):
    """La condizione del piano per collegare dispositivi fisici: le difese
    contro l'injection verificate. Qui sul dispositivo vero del perimetro."""
    b, _ = broker(tmp_path)
    r = b.execute({"tool": "set_home_device", "dispositivo": "friggitrice",
                   "azione": "accendi"},
                  Context(has_untrusted_content=True, chiedi_conferma=lambda s, c: True))
    assert r.denied and r.stage == "policy"
    assert ha.servizi == []


def test_lo_slot_ultimo_dispositivo_si_popola(tmp_path, client, registro, pian):
    from metis.memory.slots import Slots

    s = Slots()
    b, ctx = broker(tmp_path)
    call = {"tool": "get_home_state", "dispositivo": "friggitrice"}
    s.osserva(call, b.execute(call, ctx))
    assert s.ultimo_dispositivo == "la friggitrice ad aria"
    assert "Ultimo dispositivo: la friggitrice ad aria" in s.blocco()
