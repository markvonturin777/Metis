"""PHASE2, giorni 11-12 — la bolla che mostra dove Metis sta per cliccare.

Tre famiglie: la bolla come funzione del tempo (pura), l'overlay che la
disegna (timer solo mentre vive, niente ridisegni a riposo, "riduci
animazioni" senza timer), e la conferma nell'app (bolla fucsia finche' il
dialogo e' aperto, spenta per ogni esito).
"""
import statistics
import threading
import time

import pytest

from metis.gui import evidenza
from metis.gui.evidenza import (
    ALFA,
    ENTRATA_MS,
    ONDA_MS,
    PAUSA_DOPO_CLIC_MS,
    RIFIUTO_MS,
    USCITA_MS,
    Stile,
    fotogramma,
    raggio_per,
)

R = 20.0


# --- la bolla, pura ---------------------------------------------------------------

def test_il_raggio_dipende_dal_lato_corto_e_sta_in_un_intervallo():
    assert raggio_per((0, 0, 20, 20)) == 20
    assert raggio_per((0, 0, 400, 20)) == 20            # link lungo: non una bolla enorme
    assert raggio_per((0, 0, 4, 4)) == evidenza.RAGGIO_MIN
    assert raggio_per((0, 0, 500, 500)) == evidenza.RAGGIO_MAX


def test_la_bolla_entra_larga_e_si_stringe_sul_punto():
    inizio = fotogramma(Stile.CLIC, 0, R)
    fine = fotogramma(Stile.CLIC, ENTRATA_MS, R)
    assert inizio.raggio == pytest.approx(2.2 * R) and inizio.alfa == 0
    assert fine.raggio == pytest.approx(R) and fine.alfa == pytest.approx(ALFA)
    raggi = [fotogramma(Stile.CLIC, t, R).raggio for t in range(0, ENTRATA_MS + 1, 20)]
    assert raggi == sorted(raggi, reverse=True)


def test_senza_clic_la_bolla_resta():
    assert not fotogramma(Stile.CLIC, 5000, R).finito


def test_il_clic_fa_partire_l_onda_e_poi_la_bolla_sfuma():
    t_clic = 300
    f = fotogramma(Stile.CLIC, t_clic + ONDA_MS / 2, R, t_clic=t_clic)
    assert R < f.onda_raggio < 2.4 * R and 0 < f.onda_alfa < 0.7
    assert fotogramma(Stile.CLIC, t_clic + PAUSA_DOPO_CLIC_MS + USCITA_MS / 2, R,
                      t_clic=t_clic).alfa < ALFA
    assert fotogramma(Stile.CLIC, t_clic + PAUSA_DOPO_CLIC_MS + USCITA_MS + 1, R,
                      t_clic=t_clic).finito


def test_in_attesa_respira_e_non_finisce_da_sola():
    for t in range(ENTRATA_MS, 20_000, 137):
        f = fotogramma(Stile.ATTESA, t, R)
        assert not f.finito and 0.9 * R <= f.raggio <= 1.1 * R
    assert fotogramma(Stile.ATTESA, 25_000, R, t_spegni=24_000).finito


def test_il_rifiuto_e_un_lampo():
    assert fotogramma(Stile.RIFIUTO, 0, R).alfa == pytest.approx(ALFA)
    assert fotogramma(Stile.RIFIUTO, RIFIUTO_MS / 2, R).alfa < ALFA / 2
    assert fotogramma(Stile.RIFIUTO, RIFIUTO_MS, R).finito


def test_spegnere_sfuma_in_uscita():
    assert 0 < fotogramma(Stile.CLIC, 400 + USCITA_MS / 2, R, t_spegni=400).alfa < ALFA
    assert fotogramma(Stile.CLIC, 400 + USCITA_MS, R, t_spegni=400).finito


def test_riduci_animazioni_bolla_ferma():
    for t in (0, 10, 100, 1000):
        f = fotogramma(Stile.CLIC, t, R, animato=False)
        assert f.raggio == R and f.alfa == ALFA and f.onda_alfa == 0
    assert fotogramma(Stile.CLIC, 1150, R, t_clic=1000, animato=False).finito
    assert fotogramma(Stile.RIFIUTO, 500, R, animato=False).finito
    assert fotogramma(Stile.ATTESA, 60_000, R, animato=False).raggio == R


def test_i_colori_sono_quelli_della_palette():
    from metis.core.palette import esadecimale
    from metis.gui import tema

    assert evidenza.colore("clic") == tema.ACCENTO
    assert evidenza.colore("attesa") == esadecimale("ATTESA_CONFERMA")
    assert evidenza.colore("rifiuto") == tema.ERRORE


# --- l'overlay ----------------------------------------------------------------------

def _gira(app, s):
    fine = time.perf_counter() + s
    while time.perf_counter() < fine:
        app.processEvents()
        time.sleep(0.005)


def _cornice():
    from metis.tools.display import monitors

    m = next(m for m in monitors() if m.primario)
    return (m.rect[0] + 100, m.rect[1] + 100, m.rect[0] + 700, m.rect[1] + 500)


@pytest.fixture
def overlay(app_qt):
    from metis.gui.numeri import OverlayNumeri

    o = OverlayNumeri()
    yield o
    o.nascondi()
    o.deleteLater()
    app_qt.processEvents()


def test_la_bolla_compare_anima_e_se_ne_va(app_qt, overlay):
    c = _cornice()
    overlay.evidenzia(c, (c[0] + 50, c[1] + 50, c[0] + 150, c[1] + 80), "clic")
    assert overlay.isVisible() and overlay.animazione_attiva
    _gira(app_qt, 0.3)
    overlay.clic()
    _gira(app_qt, 0.9)
    assert overlay.bolla is None and not overlay.animazione_attiva
    assert not overlay.isVisible(), "senza numeri e senza bolla la finestra sparisce"


def test_a_riposo_zero_ridisegni(app_qt, overlay):
    c = _cornice()
    overlay.evidenzia(c, (c[0] + 50, c[1] + 50, c[0] + 150, c[1] + 80), "clic")
    overlay.clic()
    _gira(app_qt, 1.0)
    fermi = overlay.disegni
    _gira(app_qt, 0.5)
    assert overlay.disegni == fermi


def test_i_numeri_spariscono_ma_la_bolla_finisce_la_sua_onda(app_qt, overlay):
    c = _cornice()
    r = (c[0] + 50, c[1] + 50, c[0] + 150, c[1] + 80)
    overlay.mostra(c, [(1, r)])
    overlay.evidenzia(c, r, "clic")
    overlay.clic()
    overlay.nascondi()                      # come fa `invalida()` dopo il clic
    _gira(app_qt, 0.1)
    assert overlay.isVisible() and overlay.bolla is not None
    _gira(app_qt, 0.9)
    assert not overlay.isVisible()


def test_stesso_stile_prima_del_clic_si_sposta_senza_ricominciare(app_qt, overlay):
    c = _cornice()
    overlay.evidenzia(c, (c[0] + 50, c[1] + 50, c[0] + 150, c[1] + 80), "clic")
    t0 = overlay.bolla.t0
    _gira(app_qt, 0.1)
    overlay.evidenzia(c, (c[0] + 53, c[1] + 52, c[0] + 153, c[1] + 82), "clic")
    assert overlay.bolla.t0 == t0 and overlay.bolla.rect[0] == pytest.approx(53)
    overlay.evidenzia(c, (c[0] + 53, c[1] + 52, c[0] + 153, c[1] + 82), "rifiuto")
    assert overlay.bolla.t0 != t0 and overlay.bolla.stile is Stile.RIFIUTO


def test_riduci_animazioni_nessun_timer(app_qt, overlay):
    overlay.imposta_animazioni(False)
    c = _cornice()
    overlay.evidenzia(c, (c[0] + 50, c[1] + 50, c[0] + 150, c[1] + 80), "clic")
    assert overlay.isVisible() and not overlay.animazione_attiva
    overlay.clic()
    assert not overlay.animazione_attiva
    _gira(app_qt, 0.4)
    assert overlay.bolla is None and not overlay.isVisible()


def test_disegno_sotto_i_4_ms_durante_l_animazione(app_qt, overlay):
    """NFR-8, come il nucleo di PHASE1: p95 del disegno sotto i 4 ms. Con
    99 numeri a schermo, il caso peggiore."""
    c = _cornice()
    numerati = [(n, (c[0] + 10 + (n % 10) * 55, c[1] + 10 + (n // 10) * 35,
                     c[0] + 50 + (n % 10) * 55, c[1] + 30 + (n // 10) * 35))
                for n in range(1, 100)]
    overlay.mostra(c, numerati)
    overlay.tempi_disegno.clear()
    overlay.evidenzia(c, numerati[44][1], "attesa")
    _gira(app_qt, 1.0)
    assert len(overlay.tempi_disegno) >= 10
    p95 = statistics.quantiles(overlay.tempi_disegno, n=20)[-1]
    assert p95 < 4.0, f"p95 {p95:.2f} ms"


def test_il_ponte_consegna_bolla_e_clic_dal_thread_del_turno(app_qt, overlay):
    from metis.gui.numeri import Ponte

    ponte = Ponte(overlay)
    c = _cornice()

    def turno():
        ponte.evidenzia(c, (c[0] + 50, c[1] + 50, c[0] + 150, c[1] + 80), "clic")
        ponte.clic()
    t = threading.Thread(target=turno)
    t.start(); t.join()
    _gira(app_qt, 0.05)
    assert overlay.bolla is not None and overlay.bolla.t_clic is not None


# --- la conferma, nell'app ------------------------------------------------------------

def test_durante_la_conferma_di_un_clic_la_bolla_fucsia_sta_sull_elemento(crea_applicazione):
    from metis.tools import numeri
    from metis.tools.uia import Elemento

    app = crea_applicazione()
    c = _cornice()
    rect = (c[0] + 50, c[1] + 50, c[0] + 150, c[1] + 80)
    with numeri._lock:
        numeri._stato = numeri.Numerazione(1, c, (Elemento("Condividi", "pulsante", rect),),
                                           "chrome.exe", "c", time.monotonic())
    try:
        app._mostra_conferma("clicca_numero", "T2",
                             {"numero": "1", "elemento": "Condividi", "finestra": "x"}, 20)
        assert app.numeri.bolla is not None and app.numeri.bolla.stile is Stile.ATTESA
        app._chiudi_conferma()                      # per qualunque esito
        assert app.numeri.bolla.t_spegni is not None
    finally:
        numeri._stato = None


def test_la_conferma_di_altro_non_accende_niente(crea_applicazione):
    app = crea_applicazione()
    app._mostra_conferma("send_email", "T3", {"a": "x@y.it", "oggetto": "o", "corpo": "c"}, 20)
    assert app.numeri.bolla is None
    app._chiudi_conferma()
