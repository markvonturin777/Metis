"""Lo scheduler: il primo stato di Metis che sopravvive al riavvio.

Il riavvio si simula chiudendo un pianificatore e aprendone un altro sullo
stesso database — due oggetti che non condividono niente se non il file. Il
riavvio vero del PC resta un criterio di uscita da provare a mano, e il banco
`prova_riavvio.py` fa il passo intermedio: due PROCESSI diversi.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from metis.security.audit import AuditLog
from metis.security.broker import Broker
from metis.security.policies import Context
from metis.tools import scheduler as sch
from metis.tools.registry import Rifiuto, carica_tutti

REG = carica_tutti()


def _url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"


@pytest.fixture
def pian(tmp_path):
    p = sch.Pianificatore(_url(tmp_path))
    p.avvia(in_pausa=True)          # nei test i job non devono scattare da soli
    sch.usa_pianificatore(p)
    yield p
    p.ferma()
    sch.usa_pianificatore(None)


@pytest.fixture
def consegne():
    """Registra cosa scatta, e ripulisce le consegne alla fine."""
    ricevuti: dict[str, list] = {sch.PROMEMORIA: [], sch.EMAIL: [], sch.SPEGNI: []}
    for tipo, lista in ricevuti.items():
        sch.imposta_consegna(tipo, lista.append)
    yield ricevuti
    for tipo in ricevuti:
        sch.imposta_consegna(tipo, None)
    sch._in_attesa.clear()


def domani(ora=17):
    return (datetime.now() + timedelta(days=1)).replace(hour=ora, minute=0,
                                                        second=0, microsecond=0)


# --- il requisito che determina tutto -----------------------------------------

def test_il_promemoria_sopravvive_a_un_nuovo_pianificatore(tmp_path):
    """Il riavvio, simulato: due pianificatori che condividono solo il file."""
    p1 = sch.Pianificatore(_url(tmp_path))
    p1.avvia(in_pausa=True)
    p1.promemoria("chiamare il commercialista", domani())
    p1.ferma()

    p2 = sch.Pianificatore(_url(tmp_path))
    p2.avvia(in_pausa=True)
    try:
        voci = p2.voci()
        assert [v.testo for v in voci] == ["chiamare il commercialista"]
        assert voci[0].quando == domani()
    finally:
        p2.ferma()


def test_un_promemoria_scaduto_a_pc_spento_scatta_alla_riaccensione(tmp_path, consegne):
    """`misfire_grace_time`, provato davvero: l'ora prevista passa mentre
    nessun pianificatore e' acceso, e il job parte al riavvio."""
    p1 = sch.Pianificatore(_url(tmp_path))
    p1.avvia(in_pausa=True)
    p1.promemoria("prendere le medicine",
                  datetime.now().replace(microsecond=0) + timedelta(seconds=1))
    p1.ferma()

    time.sleep(2.2)              # l'ora passa a "PC spento"

    p2 = sch.Pianificatore(_url(tmp_path))
    p2.avvia()
    try:
        t0 = time.perf_counter()
        while not consegne[sch.PROMEMORIA] and time.perf_counter() - t0 < 5:
            time.sleep(0.05)
        assert [d["testo"] for d in consegne[sch.PROMEMORIA]] == ["prendere le medicine"]
    finally:
        p2.ferma()


def test_la_tolleranza_e_quella_del_piano():
    assert sch.GRAZIA_S == 3600


def test_la_funzione_dei_job_non_cambia_nome():
    """I job gia' salvati in `data/jobs.db` la chiamano per nome. Rinominarla
    significa che i promemoria programmati prima dell'aggiornamento non
    scattano piu' — e non lo dice nessuno."""
    import importlib

    modulo, nome = sch.FUNZIONE.split(":")
    assert getattr(importlib.import_module(modulo), nome) is sch._scatta


# --- la consegna ---------------------------------------------------------------

def test_cio_che_scatta_prima_dell_avvio_aspetta_la_consegna():
    """Il caso dei promemoria recuperati dopo un riavvio: scattano appena lo
    scheduler parte, magari prima che l'applicazione sia pronta."""
    sch.imposta_consegna(sch.PROMEMORIA, None)
    sch._in_attesa.clear()
    sch._scatta("promemoria", testo="arrivato presto", id="x")
    ricevuti = []
    sch.imposta_consegna(sch.PROMEMORIA, ricevuti.append)
    try:
        assert [d["testo"] for d in ricevuti] == ["arrivato presto"]
    finally:
        sch.imposta_consegna(sch.PROMEMORIA, None)


def test_una_consegna_che_esplode_non_ferma_le_altre():
    def rotta(dati):
        raise RuntimeError("TTS giu'")

    sch.imposta_consegna(sch.PROMEMORIA, rotta)
    prima = sch.STATO_CONSEGNE["fallite"]
    try:
        sch._scatta("promemoria", testo="x", id="y")   # non solleva
        assert sch.STATO_CONSEGNE["fallite"] == prima + 1
    finally:
        sch.imposta_consegna(sch.PROMEMORIA, None)


# --- non mentire sull'elenco ----------------------------------------------------

def test_prima_dell_avvio_non_dice_che_non_c_e_niente(tmp_path):
    """Prima di `start()` APScheduler non ha aperto il database e l'elenco
    torna vuoto. "Non ha promemoria" detto quando la verita' e' "non so
    guardare" e' la stessa bugia evitata in M5 sulla ricerca."""
    p = sch.Pianificatore(_url(tmp_path))
    with pytest.raises(Rifiuto):
        p.voci()
    with pytest.raises(Rifiuto):
        p.promemoria("x", domani())


# --- gli strumenti, attraverso il broker ----------------------------------------

def _broker(tmp_path, chiedi=None):
    return Broker(registry=REG, audit=AuditLog(tmp_path / "a.db")), \
        Context(chiedi_conferma=chiedi)


def test_schedule_reminder_chiede_conferma_anche_se_e_t1(tmp_path, pian):
    """T1, reversibile — ma il piano vuole la conferma della data SEMPRE.
    Senza nessuno che confermi, non si programma niente."""
    b, ctx = _broker(tmp_path)
    r = b.execute({"tool": "schedule_reminder", "testo": "commercialista",
                   "quando": domani().strftime("%Y-%m-%dT%H:%M")}, ctx)
    assert r.denied and r.stage == "conferma"
    assert pian.voci() == []


def test_chi_conferma_vede_la_data_in_parole(tmp_path, pian):
    visti = []

    def chiedi(spec, call):
        from metis.tools.registry import presentazione
        visti.append(presentazione(spec, call))
        return True

    b, ctx = _broker(tmp_path, chiedi)
    r = b.execute({"tool": "schedule_reminder", "testo": "commercialista",
                   "quando": domani().strftime("%Y-%m-%dT%H:%M")}, ctx)
    assert r.ok
    assert visti[0]["quando"].startswith("domani, ")
    assert "alle 17:00" in visti[0]["quando"]


def test_una_data_nel_passato_si_rifiuta_prima_della_conferma(tmp_path, pian):
    """Chiedere di confermare un promemoria per ieri insegna a premere
    Approva senza leggere."""
    chiesto = []
    b, ctx = _broker(tmp_path, lambda s, c: chiesto.append(1) or True)
    ieri = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = b.execute({"tool": "schedule_reminder", "testo": "x", "quando": ieri}, ctx)
    assert r.denied and r.stage == "guardie" and chiesto == []


def test_schedule_email_e_t3_e_richiede_l_allowlist(tmp_path, pian, monkeypatch):
    from metis.tools import posta

    lista = tmp_path / "email.toml"
    lista.write_text('[allowlist]\nindirizzi = ["marco@esempio.it"]\n',
                     encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", lista)
    b, ctx = _broker(tmp_path, lambda s, c: True)
    quando = domani(9).strftime("%Y-%m-%dT%H:%M")

    fuori = b.execute({"tool": "schedule_email", "to": "altro@esempio.it",
                       "subject": "s", "body": "b", "quando": quando}, ctx)
    assert fuori.denied and fuori.stage == "guardie"

    dentro = b.execute({"tool": "schedule_email", "to": "marco@esempio.it",
                        "subject": "Lista della spesa", "body": "latte, pane",
                        "quando": quando}, ctx)
    assert dentro.ok and dentro.confirmed is True
    assert [v.tipo for v in pian.voci()] == [sch.EMAIL]


def test_elenco_e_cancellazione_per_testo(tmp_path, pian):
    pian.promemoria("chiamare il commercialista", domani(17))
    pian.promemoria("comprare il latte", domani(9))
    b, ctx = _broker(tmp_path)

    elenco = b.execute({"tool": "list_reminders"}, ctx)
    assert elenco.ok and [v["testo"] for v in elenco.value["voci"]] == \
        ["comprare il latte", "chiamare il commercialista"]

    r = b.execute({"tool": "cancel_reminder", "riferimento": "commercialista"}, ctx)
    assert r.ok
    assert [v.testo for v in pian.voci()] == ["comprare il latte"]


def test_un_riferimento_ambiguo_si_rifiuta(tmp_path, pian):
    """Stessa regola delle finestre in M4: fra due corrispondenze non si
    sceglie a caso."""
    pian.promemoria("chiamare Luca", domani(9))
    pian.promemoria("chiamare Anna", domani(10))
    b, ctx = _broker(tmp_path)
    r = b.execute({"tool": "cancel_reminder", "riferimento": "chiamare"}, ctx)
    assert r.denied and r.stage == "strumento"
    assert len(pian.voci()) == 2


def test_un_riferimento_inventato_non_cancella_niente(tmp_path, pian):
    pian.promemoria("chiamare Luca", domani(9))
    b, ctx = _broker(tmp_path)
    r = b.execute({"tool": "cancel_reminder", "riferimento": "dentista"}, ctx)
    assert r.denied and len(pian.voci()) == 1


def test_lo_spegnimento_di_sicurezza_non_si_vede_e_non_si_cancella(tmp_path, pian):
    """Togliere un limite di sicurezza con uno strumento T1 sarebbe un modo
    di spegnere una guardia parlando."""
    pian.spegnimento("friggitrice", domani())
    assert pian.voci() == []
    b, ctx = _broker(tmp_path)
    r = b.execute({"tool": "cancel_reminder", "riferimento": "spegnimento"}, ctx)
    assert r.denied
    assert len(pian.voci(tipi=(sch.SPEGNI,))) == 1


def test_riaccendere_fa_ripartire_il_conto_dello_spegnimento(pian):
    pian.spegnimento("friggitrice", domani(10))
    pian.spegnimento("friggitrice", domani(11))
    voci = pian.voci(tipi=(sch.SPEGNI,))
    assert len(voci) == 1 and voci[0].quando.hour == 11


# --- quando un'email programmata scatta ----------------------------------------

def test_l_email_programmata_ricontrolla_l_allowlist_all_invio(tmp_path, monkeypatch):
    """Togliere un indirizzo dal file deve bloccare anche le email gia'
    programmate verso di lui: la conferma e' di ieri, l'allowlist di oggi."""
    from metis.core.avvio import Consegne
    from metis.tools import notify, posta

    lista = tmp_path / "email.toml"
    lista.write_text('[allowlist]\nindirizzi = []\n', encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", lista)
    notify.usa_backend(lambda n, c: None)

    annunci = []

    class Orch:
        def annuncia(self, t):
            annunci.append(t)

    audit = AuditLog(tmp_path / "a.db")
    try:
        Consegne(Orch(), audit).email({"to": "marco@esempio.it", "subject": "s",
                                       "body": "b"})
    finally:
        notify.usa_backend(None)
    assert annunci and "non e' partita" in annunci[0]
    riga = audit.recent(1)[0]
    assert riga["outcome"] == "error" and riga["stage"] == "invio_programmato"


def test_la_cancellazione_ignora_le_parole_di_contorno(tmp_path, pian):
    """Misurato con Qwen: "cancella il promemoria del commercialista"
    produceva `riferimento="promemoria del commercialista"`, e con il
    confronto per sottostringa non si trovava "chiamare il commercialista"."""
    pian.promemoria("chiamare il commercialista", domani(17))
    b, ctx = _broker(tmp_path)
    r = b.execute({"tool": "cancel_reminder",
                   "riferimento": "promemoria del commercialista"}, ctx)
    assert r.ok and pian.voci() == []


def test_una_parola_in_comune_non_basta(tmp_path, pian):
    """Tutte le parole, non una: "chiamare Luca" non cancella "chiamare
    Anna" perche' condividono il verbo."""
    pian.promemoria("chiamare Anna", domani(9))
    b, ctx = _broker(tmp_path)
    r = b.execute({"tool": "cancel_reminder", "riferimento": "chiamare Luca"}, ctx)
    assert r.denied and len(pian.voci()) == 1


# --- oltre l'ora di tolleranza (M6, misurato) -----------------------------------

def test_oltre_l_ora_il_promemoria_arriva_lo_stesso_dicendo_il_ritardo(tmp_path, consegne):
    """Con `misfire_grace_time = 3600` come nel piano, un promemoria scaduto
    da due ore alla riaccensione veniva scartato con una riga di log e
    nient'altro. Adesso arriva, e sa di essere in ritardo."""
    adesso = datetime.now().replace(second=0, microsecond=0)
    p1 = sch.Pianificatore(_url(tmp_path))
    p1.avvia(in_pausa=True)
    p1.promemoria("scaduto da due ore", adesso - timedelta(hours=2))
    p1.promemoria("scaduto da dieci minuti", adesso - timedelta(minutes=10))
    p1.ferma()

    p2 = sch.Pianificatore(_url(tmp_path))
    p2.avvia()
    try:
        t0 = time.perf_counter()
        while len(consegne[sch.PROMEMORIA]) < 2 and time.perf_counter() - t0 < 5:
            time.sleep(0.05)
        per_testo = {d["testo"]: d for d in consegne[sch.PROMEMORIA]}
        assert per_testo["scaduto da due ore"]["in_ritardo"] is True
        assert per_testo["scaduto da dieci minuti"]["in_ritardo"] is False
    finally:
        p2.ferma()


def test_un_email_in_ritardo_non_parte(tmp_path, monkeypatch):
    """L'utente ha confermato l'invio alle 9, non alle 14. Si dice che non e'
    partita, e decide lui."""
    from metis.core.avvio import Consegne
    from metis.tools import notify, posta

    inviate = []
    monkeypatch.setattr(posta, "invia", lambda *a, **k: inviate.append(a))
    notify.usa_backend(lambda n, c: None)
    annunci = []

    class Orch:
        def annuncia(self, t):
            annunci.append(t)

    audit = AuditLog(tmp_path / "a.db")
    try:
        Consegne(Orch(), audit).email({"to": "marco@esempio.it", "subject": "s",
                                       "body": "b", "in_ritardo": True,
                                       "previsto": "2026-09-23T09:00"})
    finally:
        notify.usa_backend(None)
    assert inviate == [], "un'email in ritardo e' partita da sola"
    assert "non e' partita" in annunci[0] and "spento" in annunci[0]
    assert audit.recent(1)[0]["outcome"] == "denied"


def test_chiudere_con_un_job_scaduto_non_uccide_il_thread(tmp_path):
    """La corsa di APScheduler trovata provando il riavvio: `shutdown()`
    svegliava il thread, che processava i job con gli esecutori gia' chiusi
    e moriva con uno stack trace. Il job non si perdeva, ma il log mostrava
    eccezioni a ogni chiusura."""
    import threading

    morti = []
    vecchio = threading.excepthook
    threading.excepthook = lambda a: morti.append(a.exc_type.__name__)
    try:
        p = sch.Pianificatore(_url(tmp_path))
        p.avvia(in_pausa=True)
        p.promemoria("scaduto", datetime.now().replace(microsecond=0)
                     - timedelta(minutes=5))
        p.ferma()
        time.sleep(0.5)
    finally:
        threading.excepthook = vecchio
    assert morti == [], f"il thread dello scheduler e' morto: {morti}"
