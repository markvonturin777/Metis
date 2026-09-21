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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app_qt():
    from PySide6.QtWidgets import QApplication

    istanza = QApplication.instance() or QApplication([])
    yield istanza
