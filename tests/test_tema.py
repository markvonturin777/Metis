"""PHASE1 — il sistema di design: font, icone, palette, componenti.

L'estetica si giudica guardando (`benchmarks/gui_catalogo.py --cattura`).
Qui si verifica quello che guardando non si vede: un font che manca e viene
sostituito in silenzio, due stati con colori troppo vicini, un colore
scritto a mano in un file che poi diverge dagli altri.
"""
import colorsys
import re
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QFontInfo

from metis.core.palette import esadecimale
from metis.gui import tema


@pytest.fixture
def app_tema(app_qt):
    """Il tema applicato, e tolto alla fine: la QApplication e' condivisa con
    i test di PHASE0, che non devono vederlo."""
    font_prima = app_qt.font()
    disponibili = tema.applica(app_qt)
    yield disponibili
    app_qt.setStyleSheet("")
    app_qt.setFont(font_prima)


# --- font --------------------------------------------------------------------------

def test_i_tre_font_si_caricano_davvero(app_tema):
    """Qt, se un font manca, ripiega su Tahoma senza dirlo."""
    assert app_tema == {"Orbitron": True, "Inter": True, "JetBrains Mono": True}


def test_il_font_di_un_widget_non_viene_scavalcato_dal_foglio(app_tema):
    """Il primo difetto del catalogo: una regola `QWidget { font-family }`
    nel foglio di stile vinceva su ogni `setFont`, e tutto usciva in Inter
    a 13 px. Il foglio non deve piu' parlare di font."""
    from PySide6.QtWidgets import QLabel

    lab = QLabel("M.E.T.I.S")
    lab.setFont(tema.font(tema.FONT_TITOLI, 26))
    lab.ensurePolished()
    info = QFontInfo(lab.font())
    assert info.family() == "Orbitron" and info.pixelSize() == 26
    assert "font-family" not in tema.foglio()


def test_i_file_dei_font_hanno_la_loro_licenza():
    cartella = tema.RISORSE / "font"
    assert {p.name for p in cartella.glob("*OFL.txt")} == {
        "Orbitron-OFL.txt", "Inter-OFL.txt", "JetBrainsMono-OFL.txt"}
    assert (tema.RISORSE / "icone" / "LICENSE-lucide.txt").exists()


# --- icone -------------------------------------------------------------------------

def _pixel_colorati(pix, colore: str) -> int:
    img = pix.toImage()
    atteso = QColor(colore)
    n = 0
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if c.alpha() > 200 and abs(c.red() - atteso.red()) < 40 \
                    and abs(c.green() - atteso.green()) < 40 and abs(c.blue() - atteso.blue()) < 40:
                n += 1
    return n


@pytest.mark.parametrize("nome", tema.icone_disponibili())
def test_ogni_icona_si_disegna_nel_colore_chiesto(app_qt, nome):
    pix = tema.pixmap_icona(nome, "#ff2020", 24)
    assert _pixel_colorati(pix, "#ff2020") > 10, f"{nome}: vuota o del colore sbagliato"


def test_l_icona_rispetta_la_scala_del_monitor(app_qt):
    """A 150% un'icona da 20 px logici va disegnata a 30 reali, o si sfoca."""
    pix = tema.pixmap_icona("mic", tema.ACCENTO, 20, 1.5)
    assert (pix.width(), pix.height()) == (30, 30)
    assert pix.devicePixelRatio() == 1.5


def test_le_icone_usate_esistono():
    """Un nome d'icona sbagliato in un modulo si vede solo come un buco."""
    # Primo argomento per le funzioni d'icona, secondo per `Pannello`.
    chiamata = re.compile(
        r"""(?:PulsanteIcona|icona|pixmap_icona|imposta_icona)\(\s*["']([a-z0-9-]+)["']"""
        r"""|Pannello\([^,()]+,\s*["']([a-z0-9-]+)["']""")
    usate = set()
    for f in Path("metis/gui").rglob("*.py"):
        for m in chiamata.finditer(f.read_text(encoding="utf-8")):
            usate.add(m.group(1) or m.group(2))
    assert usate                               # la ricerca trova davvero qualcosa
    mancanti = usate - set(tema.icone_disponibili())
    assert not mancanti, mancanti


# --- palette degli stati -----------------------------------------------------------

# Gli stati che si devono distinguere a colpo d'occhio: dorme, ascolta,
# pensa, parla, aspetta te, errore. I sotto-stati (TRASCRIZIONE, RICERCA_WEB)
# sono varianti del proprio gruppo e non entrano nel confronto.
DA_DISTINGUERE = ("IN_ASCOLTO", "ELABORAZIONE", "PARLATO", "ATTESA_CONFERMA", "ERRORE")


def _tonalita(esa: str) -> tuple[float, float]:
    c = QColor(esa)
    h, _l, s = colorsys.rgb_to_hls(c.redF(), c.greenF(), c.blueF())
    return h * 360, s


def test_gli_stati_che_contano_sono_lontani_almeno_30_gradi():
    """In PHASE0 "ASPETTA TE" (arancione) stava a 11 gradi da "sta pensando"
    (ambra) e a 27 dal rosso. Proprio lo stato che chiede di intervenire."""
    for i, a in enumerate(DA_DISTINGUERE):
        for b in DA_DISTINGUERE[i + 1:]:
            ha, hb = _tonalita(esadecimale(a))[0], _tonalita(esadecimale(b))[0]
            distanza = min(abs(ha - hb), 360 - abs(ha - hb))
            assert distanza >= 30, f"{a} e {b} a {distanza:.0f} gradi"


def test_dormiente_si_riconosce_perche_e_spento():
    """Il grigio non ha tonalita': si distingue per saturazione."""
    assert _tonalita(esadecimale("DORMIENTE"))[1] < 0.3
    for stato in DA_DISTINGUERE:
        assert _tonalita(esadecimale(stato))[1] > 0.6, stato


# --- un solo posto per i colori ----------------------------------------------------

# I file di PHASE0 non ancora ridisegnati. L'elenco puo' solo accorciarsi:
# vedi `test_l_elenco_dei_file_da_ridisegnare_non_mente`.
# Vuoto dai giorni 11-12: Minimal, Diagnostica, dialogo T3, tray e widget di
# PHASE0 sono passati tutti da `tema.py`. Resta come cricchetto: un file che
# ci rientrasse sarebbe un colore reintrodotto.
DA_RIDISEGNARE: set[str] = set()
_ESA = re.compile(r"#[0-9a-fA-F]{6}\b")


def _con_colori() -> set[str]:
    return {f.as_posix() for f in Path("metis/gui").rglob("*.py")
            if f.name != "tema.py" and _ESA.search(f.read_text(encoding="utf-8"))}


def test_nessun_colore_scritto_fuori_dal_tema():
    nuovi = _con_colori() - DA_RIDISEGNARE
    assert not nuovi, f"colori scritti a mano in {sorted(nuovi)}: vanno in tema.py"


def test_l_elenco_dei_file_da_ridisegnare_non_mente():
    """Il cricchetto: un file ridisegnato che resta nell'elenco lascerebbe la
    porta aperta a un colore reintrodotto dopo."""
    ripuliti = DA_RIDISEGNARE - _con_colori()
    assert not ripuliti, f"togliere da DA_RIDISEGNARE: {sorted(ripuliti)}"


# --- componenti --------------------------------------------------------------------

def test_la_barra_va_in_allarme_alla_soglia(app_qt):
    from metis.gui.componenti import Barra

    b = Barra("VRAM", soglia=7.5 / 8)
    b.imposta(6.1 / 8, "6,1 GB")
    assert not b.in_allarme and b.colore() == tema.ACCENTO_PIENO
    b.imposta(7.6 / 8, "7,6 GB")
    assert b.in_allarme and b.colore() == tema.ERRORE
    b.imposta(3.0, "fuori scala")
    assert b.frazione == 1.0


def test_la_barra_non_ridisegna_se_non_cambia_niente(app_qt):
    from metis.gui.componenti import Barra

    b = Barra("CPU")
    b.imposta(0.5, "50%")
    chiamate = []
    b.update = lambda *a: chiamate.append(1)
    b.imposta(0.5, "50%")
    assert chiamate == []
    b.imposta(0.6, "60%")
    assert chiamate == [1]


def test_la_pillola_si_allarga_con_il_testo(app_qt):
    from metis.gui.componenti import Pillola

    p = Pillola("ok", tema.OK)
    corta = p.sizeHint().width()
    p.imposta("sta cercando in rete", esadecimale("RICERCA_WEB"))
    assert p.sizeHint().width() > corta + 50


def test_il_pulsante_disattivato_ha_l_icona_spenta(app_qt):
    from PySide6.QtGui import QIcon

    from metis.gui.componenti import PulsanteIcona

    b = PulsanteIcona("camera-off", "non collegata")
    b.setEnabled(False)
    pix = b.icon().pixmap(b.iconSize(), QIcon.Mode.Disabled)
    assert _pixel_colorati(pix, tema.SEGNAPOSTO) > 10
    assert _pixel_colorati(pix, tema.ACCENTO) == 0


def test_il_pannello_mette_le_azioni_nella_testata(app_qt):
    from metis.gui.componenti import Pannello, PulsanteIcona

    pan = Pannello("Sistema", "cpu")
    azione = pan.aggiungi_azione(PulsanteIcona("activity", "Diagnostica", lato=26))
    assert azione.parent() is pan.testata
    assert pan.titolo.text() == "Sistema"
    assert pan.titolo.font().family() == tema.FONT_TITOLI
