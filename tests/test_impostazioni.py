"""PHASE1, giorni 11-12 — le Impostazioni dell'Hub.

Si scrive solo `gui.local.toml` (ignorato da git), si conserva quello che non
si conosce, e la geocodifica resta al worker del meteo: dal dialogo non
parte nessuna richiesta di rete.
"""
import tomllib

import pytest
from PySide6.QtWidgets import QApplication

from metis.gui import impostazioni as imp
from metis.gui.workers import meteo


@pytest.fixture
def config(tmp_path):
    p = tmp_path / "gui.toml"
    p.write_text('[meteo]\ncitta = ""\n', encoding="utf-8")
    return p


def _locale(config):
    return tomllib.loads(imp.locale(config).read_text(encoding="utf-8"))


def test_senza_file_locale_valgono_i_predefiniti(config):
    assert imp.leggi(config) == imp.Preferenze()
    assert imp.leggi(config).vista_avvio == "minimal"


def test_salva_e_rileggi(config):
    pref = imp.Preferenze(citta="Torino", riduci_animazioni=True, vista_avvio="hub",
                          muto_avvio=True)
    assert imp.salva(pref, config) is True
    assert imp.leggi(config) == pref
    assert config.read_text(encoding="utf-8") == '[meteo]\ncitta = ""\n'   # il repository no


def test_cambiata_la_citta_le_vecchie_coordinate_se_ne_vanno(config):
    imp.locale(config).write_text('[meteo]\ncitta = "Milano"\nlatitudine = 45.46\n'
                                  'longitudine = 9.19\n', encoding="utf-8")
    assert imp.salva(imp.Preferenze(citta="Torino"), config) is True
    assert _locale(config)["meteo"] == {"citta": "Torino"}
    # E il meteo, che legge lo stesso file, dovra' geocodificare.
    assert meteo.leggi_config(config) == {"citta": "Torino", "coordinate": None}


def test_stessa_citta_le_coordinate_restano(config):
    imp.locale(config).write_text('[meteo]\ncitta = "Milano"\nlatitudine = 45.46\n'
                                  'longitudine = 9.19\n', encoding="utf-8")
    assert imp.salva(imp.Preferenze(citta="milano ", vista_avvio="hub"), config) is False
    assert _locale(config)["meteo"]["latitudine"] == 45.46


def test_quello_che_non_si_conosce_resta(config):
    imp.locale(config).write_text('[meteo]\ncitta = "Milano"\nnota = "mia"\n'
                                  '[altro]\nx = 3\n', encoding="utf-8")
    imp.salva(imp.Preferenze(citta="Milano", riduci_animazioni=True), config)
    dati = _locale(config)
    assert dati["meteo"]["nota"] == "mia" and dati["altro"] == {"x": 3}


@pytest.mark.parametrize("citta", ['Sant\'Agata de\' Goti', 'Città "vecchia"', "C:\\strano"])
def test_nomi_con_caratteri_speciali(config, citta):
    imp.salva(imp.Preferenze(citta=citta), config)
    assert imp.leggi(config).citta == citta


def test_una_vista_sconosciuta_torna_quella_predefinita(config):
    imp.locale(config).write_text('[interfaccia]\nvista_avvio = "cinema"\n', encoding="utf-8")
    assert imp.leggi(config).vista_avvio == "minimal"


def test_un_file_rovinato_non_ferma_niente(config):
    imp.locale(config).write_text("[interfaccia\nvista", encoding="utf-8")
    assert imp.leggi(config) == imp.Preferenze()


def test_il_dialogo_non_fa_rete():
    """La geocodifica sul thread della GUI sarebbe un blocco di NFR-8."""
    import ast
    from pathlib import Path

    albero = ast.parse(Path(imp.__file__).read_text(encoding="utf-8"))
    importati = {n.module for n in ast.walk(albero) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(albero) if isinstance(n, ast.Import) for a in n.names}
    assert not importati & {"httpx", "requests", "urllib.request", "metis.gui.workers.meteo"}


# --- il dialogo ---------------------------------------------------------------------------

def test_il_dialogo_parte_dalle_preferenze_e_le_restituisce(app_qt):
    pref = imp.Preferenze(citta="Milano", riduci_animazioni=True, vista_avvio="diagnostica")
    d = imp.DialogoImpostazioni(pref)
    try:
        assert d.citta.text() == "Milano" and d.animazioni.isChecked()
        assert d.vista.currentData() == "diagnostica" and not d.muto.isChecked()
        d.citta.setText("  Torino ")
        d.muto.setChecked(True)
        d.vista.setCurrentIndex(1)
        assert d.preferenze() == imp.Preferenze(citta="Torino", riduci_animazioni=True,
                                                vista_avvio="hub", muto_avvio=True)
        assert not d.salva.autoDefault() and not d.annulla.autoDefault()
    finally:
        d.deleteLater()


# --- nell'applicazione ----------------------------------------------------------------------

def _gira():
    for _ in range(10):
        QApplication.processEvents()


def test_riduci_animazioni_vale_subito(crea_applicazione):
    a = crea_applicazione()
    a.mostra_hub()
    _gira()
    assert a.hub.nucleo.animato()
    a.salva_preferenze(imp.Preferenze(riduci_animazioni=True))
    assert not a.hub.nucleo.animato() and not a.minimal.nucleo.animazioni
    a.salva_preferenze(imp.Preferenze(riduci_animazioni=False))
    assert a.hub.nucleo.animato()


def test_cambiare_citta_chiede_subito_un_giro_al_meteo(crea_applicazione):
    a = crea_applicazione()
    a.salva_preferenze(imp.Preferenze(citta="Torino"))
    assert a.worker_meteo._subito
    a.worker_meteo._subito = False
    a.salva_preferenze(imp.Preferenze(citta="Torino", riduci_animazioni=True))
    assert not a.worker_meteo._subito


def test_muto_all_avvio(crea_applicazione, tmp_path):
    imp.salva(imp.Preferenze(muto_avvio=True), tmp_path / "gui.toml")
    a = crea_applicazione()
    assert a.hub.b_voce.isChecked() and a.nucleo._muto
    assert a.modello[-1].testo.startswith("Voce disattivata")


def test_senza_muto_all_avvio_la_voce_c_e(crea_applicazione):
    a = crea_applicazione()
    assert not a.hub.b_voce.isChecked() and not a.nucleo._muto


def test_la_vista_all_avvio(crea_applicazione, tmp_path):
    imp.salva(imp.Preferenze(vista_avvio="diagnostica"), tmp_path / "gui.toml")
    a = crea_applicazione()
    assert a.vista_iniziale(False, False) == (False, True)
    assert a.vista_iniziale(True, False) == (True, False)      # la riga di comando vince


def test_il_pulsante_apre_il_dialogo(crea_applicazione, monkeypatch):
    aperti = []

    class Finto:
        def __init__(self, pref, parent=None):
            aperti.append((pref, parent))

        def exec(self):
            return 0                                            # "Annulla"

    monkeypatch.setattr(imp, "DialogoImpostazioni", Finto)
    a = crea_applicazione()
    a.hub.b_impostazioni.click()
    assert aperti == [(a.preferenze, a.hub)]


def test_un_file_che_non_si_scrive_lo_dice(crea_applicazione, monkeypatch):
    def rotto(pref, path):
        raise PermissionError("sola lettura")

    monkeypatch.setattr(imp, "salva", rotto)
    a = crea_applicazione()
    prima = a.preferenze
    a.salva_preferenze(imp.Preferenze(citta="Torino"))
    assert a.preferenze is prima
    assert "Non riesco a salvare" in a.modello[-1].testo
