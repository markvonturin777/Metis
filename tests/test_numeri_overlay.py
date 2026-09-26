"""PHASE2 — l'overlay dei numeri.

Due famiglie di verifiche. La geometria e' pura: pixel fisici e logici a
100, 125 e 150%, sul primo e sul secondo schermo, ed etichette che non si
coprono. La finestra invece si verifica con Windows: la domanda non e' cosa
creda Qt, e' quale finestra Windows consideri in primo piano dopo che i
numeri sono comparsi — perche' e' quella che legge la guardia del clic.
"""
import time

import pytest

from metis.gui.numeri import (
    ALTEZZA,
    OverlayNumeri,
    Ponte,
    Schermo,
    _si_toccano,
    a_logico,
    posiziona,
    rect_logico,
)

# --- conversioni ------------------------------------------------------------------


@pytest.mark.parametrize("schermo,fisico,logico", [
    (Schermo((0, 0), 1.0), (250, 100), (250, 100)),
    (Schermo((0, 0), 1.25), (250, 100), (200, 80)),
    (Schermo((0, 0), 1.5), (300, 150), (200, 100)),
    # Secondo schermo a destra: l'angolo resta nativo, si scala dentro.
    (Schermo((1920, 0), 1.0), (2170, 100), (2170, 100)),
    (Schermo((1920, 0), 1.25), (2170, 100), (2120, 80)),
    (Schermo((1920, 0), 1.5), (2220, 150), (2120, 100)),
    # A sinistra del primario, coordinate negative.
    (Schermo((-2560, 0), 1.5), (-2260, 300), (-2360, 200)),
])
def test_da_fisico_a_logico(schermo, fisico, logico):
    assert a_logico(fisico, schermo) == pytest.approx(logico)


def test_un_rettangolo_scala_attorno_all_angolo_dello_schermo():
    assert rect_logico((1920 + 150, 300, 1920 + 450, 600), Schermo((1920, 0), 1.5)) == \
        pytest.approx((2020, 200, 2220, 400))


# --- etichette --------------------------------------------------------------------

def test_etichette_dentro_e_senza_sovrapposizioni_quando_c_e_posto():
    elementi = [(10, 10, 200, 40), (210, 10, 400, 40), (10, 50, 200, 80)]
    etichette = posiziona(elementi, [20, 20, 20], ALTEZZA, (0, 0, 800, 600))
    assert etichette[0][:2] == (10, 10)          # l'angolo in alto a sinistra, dentro
    for i, a in enumerate(etichette):
        assert 0 <= a[0] and a[2] <= 800 and 0 <= a[1] and a[3] <= 600
        for b in etichette[i + 1:]:
            assert not _si_toccano(a, b)


def test_elementi_ammassati_si_spostano_invece_di_coprirsi():
    # Dieci pulsantini uno sull'altro, piu' piccoli delle etichette.
    elementi = [(100 + i * 6, 100, 110 + i * 6, 108) for i in range(10)]
    etichette = posiziona(elementi, [24] * 10, ALTEZZA, (0, 0, 800, 600))
    sovrapposte = sum(_si_toccano(a, b) for i, a in enumerate(etichette)
                      for b in etichette[i + 1:])
    assert sovrapposte == 0


def test_sul_bordo_l_etichetta_resta_dentro():
    (e,) = posiziona([(790, 590, 800, 600)], [30], ALTEZZA, (0, 0, 800, 600))
    assert e[2] <= 800 and e[3] <= 600


# --- la finestra, con Windows -----------------------------------------------------

def _gira(app, secondi):
    fine = time.perf_counter() + secondi
    while time.perf_counter() < fine:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def overlay(app_qt):
    o = OverlayNumeri(scadenza_s=60)
    yield o
    o.nascondi()
    o.deleteLater()
    app_qt.processEvents()


def _primario():
    from metis.tools.display import monitors

    return next(m for m in monitors() if m.primario)


# La suite gira su `offscreen`, dove una finestra non esiste per Windows. Le
# domande che si fanno a Windows le fa `tests/desktop/overlay_vero.py`, in un
# processo suo con la piattaforma vera, una volta per tutti i monitor.

@pytest.fixture(scope="module")
def vero():
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    if sys.platform != "win32":
        pytest.skip("serve Windows")
    radice = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-m", "tests.desktop.overlay_vero"], cwd=radice,
                       env={**os.environ, "QT_QPA_PLATFORM": "windows"},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_i_numeri_non_diventano_la_finestra_in_primo_piano(vero):
    for m in vero:
        assert m["visibile"], m["monitor"]
        assert m["primo_piano_dopo"] != m["overlay"], m["monitor"]
        assert m["primo_piano_dopo"] == m["primo_piano_prima"], m["monitor"]


def test_i_clic_attraversano_i_numeri(vero):
    """Al centro di un'etichetta Windows vede la finestra di sotto."""
    for m in vero:
        assert m["sotto_il_punto"] != m["overlay"], m["monitor"]


def test_windows_la_vede_come_non_attivabile_e_trasparente(vero):
    for m in vero:
        assert m["stile"] & 0x08000000, "manca WS_EX_NOACTIVATE"
        assert m["stile"] & 0x00000020, "manca WS_EX_TRANSPARENT"
        assert m["stile"] & 0x00000080, "manca WS_EX_TOOLWINDOW"


def test_copre_esattamente_la_cornice_su_ogni_monitor(vero):
    """Il rettangolo NATIVO della finestra, letto da Windows, e' la cornice in
    pixel fisici: la conversione in logici e ritorno non perde niente."""
    for m in vero:
        assert m["rect_finestra"] == m["cornice"], m["monitor"]
        assert [m["geometria"][0], m["geometria"][1]] == m["attesa"][:2], m["monitor"]


def test_sul_secondo_monitor_sta_sullo_schermo_giusto(vero):
    secondi = [m for m in vero if not m["primario"]]
    if not secondi:
        pytest.skip("un solo monitor")
    for m in secondi:
        assert m["schermo_qt_x"] != 0 and m["rect_finestra"][0] >= m["schermo_qt_x"]


def test_la_bolla_da_sola_non_prende_il_fuoco_e_lascia_passare_i_clic(vero):
    for m in vero:
        assert m["bolla_visibile"], m["monitor"]
        assert m["bolla_primo_piano_dopo"] == m["bolla_primo_piano_prima"], m["monitor"]
        assert m["bolla_primo_piano_dopo"] != m["bolla_overlay"], m["monitor"]
        assert m["sotto_la_bolla"] != m["bolla_overlay"], m["monitor"]
        assert m["bolla_sparita"], m["monitor"]


def test_le_etichette_sono_in_coordinate_locali(app_qt, overlay):
    m = _primario()
    c = (m.rect[0] + 100, m.rect[1] + 120, m.rect[0] + 500, m.rect[1] + 420)
    overlay.mostra(c, [(7, (c[0] + 10, c[1] + 20, c[0] + 110, c[1] + 40))])
    _gira(app_qt, 0.1)
    testo, elemento, _ = overlay._voci[0]
    assert testo == "7" and elemento == pytest.approx((10, 20, 110, 40))


def test_fermo_dopo_la_comparsa_niente_ridisegni(app_qt, overlay):
    m = _primario()
    c = (m.rect[0] + 100, m.rect[1] + 100, m.rect[0] + 600, m.rect[1] + 500)
    overlay.mostra(c, [(n, (c[0] + 10, c[1] + 10 + 20 * n, c[0] + 100, c[1] + 25 + 20 * n))
                       for n in range(1, 20)])
    _gira(app_qt, 0.3)
    dopo_la_comparsa = overlay.disegni
    _gira(app_qt, 0.6)
    assert overlay.disegni == dopo_la_comparsa


def test_scade_da_solo_e_lo_dice(app_qt):
    o = OverlayNumeri(scadenza_s=0.2)
    segnalati = []
    o.nascosto.connect(lambda: segnalati.append(1))
    m = _primario()
    c = (m.rect[0] + 100, m.rect[1] + 100, m.rect[0] + 300, m.rect[1] + 300)
    o.mostra(c, [(1, (c[0] + 5, c[1] + 5, c[0] + 60, c[1] + 30))])
    _gira(app_qt, 0.5)
    assert not o.isVisible() and segnalati == [1]
    o.deleteLater()


def test_il_ponte_consegna_dal_thread_del_turno(app_qt, overlay):
    import threading

    ponte = Ponte(overlay)
    m = _primario()
    c = (m.rect[0] + 100, m.rect[1] + 100, m.rect[0] + 300, m.rect[1] + 300)
    visto = {}

    def turno():
        visto["thread"] = threading.current_thread().name
        ponte.mostra(c, [(3, (c[0] + 5, c[1] + 5, c[0] + 60, c[1] + 30))])
    t = threading.Thread(target=turno, name="metis-turno")
    t.start(); t.join()
    _gira(app_qt, 0.2)
    assert overlay.isVisible() and overlay._voci[0][0] == "3"
    threading.Thread(target=ponte.nascondi).start()
    _gira(app_qt, 0.2)
    assert not overlay.isVisible()


def test_niente_numeri_niente_finestra(app_qt, overlay):
    m = _primario()
    overlay.mostra((m.rect[0] + 10, m.rect[1] + 10, m.rect[0] + 100, m.rect[1] + 100), [])
    _gira(app_qt, 0.1)
    assert not overlay.isVisible()
