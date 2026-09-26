"""Configurazione comune della suite.

QT GIRA OFFSCREEN
La suite non deve aprire finestre. Non e' solo educazione verso chi la
lancia: una suite che apre finestre non gira in CI, e i test della GUI
diventerebbero quelli che nessuno esegue.

UNA SOLA QApplication PER PROCESSO, E DEVE ESSERE QUELLA GRAFICA
Qt ne ammette una. Se un file di test ne crea una `QCoreApplication` e un
altro poi chiede una `QApplication`, la seconda non si puo' costruire —
`instance()` restituisce quella senza widget e il processo si pianta senza
messaggio. E' successo: la suite si e' fermata a meta' senza dire niente.

La fixture e' quindi di sessione e crea sempre la versione grafica, che
comprende tutto quello che serve anche a chi userebbe solo il nucleo di Qt.
"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

import metis.core.logging as _log  # noqa: E402

# PHASE1 — IL LOG DEI TEST NON E' IL LOG DI METIS
# `get_logger()` configura il log alla prima chiamata, e fino a qui la suite
# scriveva in `data/logs/metis.jsonl`: kill switch, pause, conversazioni
# azzerate, tutte finte, nello stesso file da cui `tests/nfr/verifica_nfr.py`
# certifica NFR-8 sull'uso reale. Lo stesso accorgimento del soak: il percorso
# si sposta prima che qualcuno configuri. Un file fisso, riscritto a ogni
# esecuzione, per poterlo guardare quando un test fallisce.
CARTELLA_LOG = Path(tempfile.gettempdir()) / "metis-test-log"
CARTELLA_LOG.mkdir(exist_ok=True)
_log.JSONL = CARTELLA_LOG / "metis.jsonl"
_log.STDERR = CARTELLA_LOG / "metis.stderr.log"
try:
    _log.JSONL.unlink(missing_ok=True)
except OSError:                 # un'altra suite lo tiene aperto: si accoda
    pass


@pytest.fixture(scope="session")
def app_qt():
    from PySide6.QtWidgets import QApplication

    istanza = QApplication.instance() or QApplication([])
    yield istanza


@pytest.fixture
def crea_applicazione(app_qt, tmp_path):
    """Costruisce `Applicazione` per i test e la SMONTA alla fine.

    PHASE1 — PERCHE' SERVE
    Senza, ogni test lasciava un'Applicazione intera — tre viste, la tray,
    decine di widget — in un ciclo di riferimenti che il garbage collector
    raccoglieva quando capitava: spesso nel mezzo della costruzione della
    successiva. Con l'Hub i widget sono diventati abbastanza da farlo
    succedere, e una volta su sei la suite moriva con "access violation"
    senza un test fallito. Qui la distruzione avviene in un punto solo, a
    event loop fermo: `deleteLater` eseguiti subito, poi `gc.collect()`.

    In esercizio il problema non esiste: l'Applicazione e' una sola e vive
    quanto il processo (provato: avvio con l'Hub, uscita con codice 0).
    """
    import gc

    from PySide6.QtCore import QEvent

    from metis.core.avvio import Opzioni
    from metis.gui.app import Applicazione

    create = []

    def crea(**kw):
        kw.setdefault("tray", False)
        # Mai il `gui.local.toml` vero: con il muto o le animazioni ridotte
        # scelti dall'utente, i test dell'Hub partirebbero da un altro stato.
        kw.setdefault("config", tmp_path / "gui.toml")
        a = Applicazione(Opzioni(tools=False, wakeword=False), **kw)
        create.append(a)
        return a

    gc.collect()
    yield crea
    for a in create:
        a.hotkeys.stop()
        if a.tray is not None:
            a.tray.nascondi()
        app_qt.setQuitOnLastWindowClosed(True)
        for vista in (a.minimal, a.hub, a.fullscreen):
            vista.hide()
            vista.deleteLater()
        a.deleteLater()
    app_qt.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    create.clear()
    gc.collect()
