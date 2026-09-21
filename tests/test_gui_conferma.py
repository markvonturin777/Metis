"""Il ponte della conferma T3 fra thread.

E' il punto in cui un difetto blocca Metis per sempre invece di produrre un
fastidio: il broker resta fermo ad aspettare una risposta che non arriva.
Per questo i casi limite qui valgono piu' dei casi normali.
"""
import threading
import time
from dataclasses import dataclass

import pytest
from PySide6.QtCore import QCoreApplication

from metis.gui.conferma import PonteConferma
from metis.security.audit import Tier
from metis.security.policies import CONFERMA_TIMEOUT_S


@dataclass
class FintoSpec:
    name: str = "send_email"
    tier: Tier = Tier.T3


class FintaCall:
    def model_dump(self):
        return {"tool": "send_email", "to": "a@b.it", "body": "x"}


@pytest.fixture
def app(app_qt):
    """Una sola QApplication per processo, creata in conftest: vedi la nota
    li' sul perche' una QCoreApplication qui bloccava tutta la suite."""
    yield app_qt


def chiedi_in_thread(ponte, risultati):
    def lavora():
        risultati.append(ponte.chiedi(FintoSpec(), FintaCall()))
    t = threading.Thread(target=lavora, daemon=True)
    t.start()
    return t


def attendi(condizione, secondi=3.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < secondi:
        QCoreApplication.processEvents()
        if condizione():
            return True
        time.sleep(0.005)
    return False


# --- casi normali ------------------------------------------------------------

def test_approvazione(app):
    ponte = PonteConferma(timeout_s=5)
    ricevute = []
    ponte.richiesta.connect(lambda *a: ricevute.append(a))
    esiti = []
    t = chiedi_in_thread(ponte, esiti)

    assert attendi(lambda: ricevute), "la richiesta non e' arrivata alla GUI"
    nome, tier, args, timeout = ricevute[0]
    assert nome == "send_email" and tier == "T3" and args["to"] == "a@b.it"

    ponte.rispondi(True)
    t.join(timeout=2)
    assert esiti == [True]
    assert ponte.approvate == 1


def test_rifiuto(app):
    ponte = PonteConferma(timeout_s=5)
    esiti = []
    t = chiedi_in_thread(ponte, esiti)
    assert attendi(lambda: ponte.richieste == 1)
    ponte.rispondi(False)
    t.join(timeout=2)
    assert esiti == [False] and ponte.approvate == 0


def test_timeout_e_un_rifiuto(app):
    """Un'attesa che scade in sì produrrebbe un audit log che dice che
    l'utente aveva acconsentito. E' peggio di nessuna conferma."""
    ponte = PonteConferma(timeout_s=0.3)
    esiti = []
    t = chiedi_in_thread(ponte, esiti)
    t.join(timeout=3)
    assert esiti == [False] and ponte.scadute == 1


# --- i casi che bloccherebbero Metis ----------------------------------------

def test_risveglio_perduto(app):
    """L'utente risponde PRIMA che il worker si metta in attesa.

    Senza il flag `_risposto`, il `wakeAll` arriverebbe quando nessuno sta
    ancora aspettando, e il worker resterebbe fermo per tutto il timeout su
    un'azione gia' approvata. E' la corsa che rende questi ponti difficili.

    Si forza con una connessione DIRETTA: cosi' `rispondi` gira dentro
    l'emit, sul thread del worker, esattamente nella finestra fra l'emit e
    l'attesa. Con la connessione in coda il momento dipenderebbe da quando
    il thread principale processa gli eventi, e il test proverebbe la corsa
    solo ogni tanto.
    """
    from PySide6.QtCore import Qt

    ponte = PonteConferma(timeout_s=10)
    ponte.richiesta.connect(lambda *a: ponte.rispondi(True), Qt.DirectConnection)

    esiti = []
    t0 = time.perf_counter()
    t = chiedi_in_thread(ponte, esiti)
    t.join(timeout=3)
    trascorso = time.perf_counter() - t0

    assert esiti == [True], "risposta persa: il worker sta ancora aspettando"
    assert trascorso < 1.0, f"ha aspettato {trascorso:.1f}s su una risposta immediata"


def test_risposta_in_coda_dal_thread_principale(app):
    """Il caso vero: la GUI risponde mentre il suo event loop gira.

    Qui la connessione e' quella predefinita, cioe' in coda, e la risposta
    arriva solo quando il thread principale processa gli eventi — come
    succede nell'applicazione vera.
    """
    ponte = PonteConferma(timeout_s=10)
    ponte.richiesta.connect(lambda *a: ponte.rispondi(True))
    esiti = []
    t = chiedi_in_thread(ponte, esiti)
    assert attendi(lambda: esiti), "la risposta non e' mai arrivata al worker"
    t.join(timeout=2)
    assert esiti == [True]


def test_chiamata_dal_thread_della_gui_non_si_blocca(app):
    """Se un giorno qualcuno chiamasse `chiedi` dal thread principale, la
    connessione sarebbe diretta e lo slot girerebbe dentro l'emit. Con il
    mutex preso sarebbe un blocco permanente: l'emit sta fuori apposta."""
    ponte = PonteConferma(timeout_s=0.5)
    ponte.richiesta.connect(lambda *a: ponte.rispondi(True))
    t0 = time.perf_counter()
    esito = ponte.chiedi(FintoSpec(), FintaCall())
    assert esito is True
    assert time.perf_counter() - t0 < 0.4, "si e' bloccato"


def test_annulla_libera_chi_aspetta(app):
    """Chiudere Metis con una conferma aperta non deve lasciare il nucleo
    fermo per venti secondi."""
    ponte = PonteConferma(timeout_s=30)
    esiti = []
    t = chiedi_in_thread(ponte, esiti)
    assert attendi(lambda: ponte.richieste == 1)
    t0 = time.perf_counter()
    ponte.annulla()
    t.join(timeout=3)
    assert esiti == [False]
    assert time.perf_counter() - t0 < 1.0


def test_risposte_successive_non_contaminano(app):
    """Una risposta arrivata in ritardo, dopo che il timeout ha gia' deciso,
    non deve valere per la richiesta successiva."""
    ponte = PonteConferma(timeout_s=0.2)
    esiti = []
    t = chiedi_in_thread(ponte, esiti)
    t.join(timeout=3)
    assert esiti == [False]

    ponte.rispondi(True)                 # risposta tardiva alla PRIMA richiesta

    esiti2 = []
    t2 = chiedi_in_thread(ponte, esiti2)
    t2.join(timeout=3)
    assert esiti2 == [False], "la risposta tardiva ha approvato la richiesta dopo"


def test_piu_conferme_di_fila(app):
    ponte = PonteConferma(timeout_s=5)
    ponte.richiesta.connect(lambda *a: ponte.rispondi(True))
    for _ in range(5):
        assert ponte.chiedi(FintoSpec(), FintaCall()) is True
    assert ponte.richieste == 5 and ponte.approvate == 5


def test_il_timeout_e_quello_del_broker(app):
    """Due timeout diversi vorrebbero dire che uno dei due aspetta l'altro."""
    assert PonteConferma().timeout_s == CONFERMA_TIMEOUT_S


def test_chiusa_viene_emessa_sempre(app):
    """Il dialogo deve sparire anche quando la risposta e' un timeout."""
    ponte = PonteConferma(timeout_s=0.2)
    chiusure = []
    ponte.chiusa.connect(lambda: chiusure.append(1))
    esiti = []
    chiedi_in_thread(ponte, esiti).join(timeout=3)
    assert attendi(lambda: len(chiusure) == 1)
