"""Il sistema di design dell'Hub: colori della cornice, font, icone, stile.

DUE TABELLE, DUE MESTIERI
`metis/core/palette.py` dice **in che stato e' Metis**: un colore per stato,
uguale nell'overlay, nella tray e nel terminale. Questo file dice **com'e'
fatta la cornice**: pannelli, bordi, testo. Le due cose non si mescolano:
l'estetica ciano della reference vale per la cornice, e il nucleo al centro
prende il colore dallo stato. Se la cornice usasse i colori di stato, un
pannello blu sembrerebbe "in ascolto".

I VALORI VENGONO DALLA REFERENCE, MISURATI
`NEW FEATURES/JARVIS_INTERFACE.png`, campionata pixel per pixel: sfondo
#060a0f, pannelli #0b161f, testate #0e202e, bordi #163850, testo ciano
#5edfff. Non sono stime a occhio, e chi li ritocca sa da dove partono.

UN SOLO POSTO PER I COLORI
`tests/test_tema.py` cerca i colori esadecimali scritti nei moduli della
GUI e li vuole solo qui e in `palette.py`. I file di PHASE0 non ancora
ridisegnati sono in un elenco che deve svuotarsi entro la fine della fase:
un cricchetto, che puo' solo stringere.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

RISORSE = Path(__file__).resolve().parent / "risorse"

# --- colori della cornice ----------------------------------------------------------

SFONDO = "#060a0f"            # la finestra
SFONDO_ALTO = "#090f16"       # intestazione, pulsanti, campo di testo
PANNELLO = "#0b161f"
PANNELLO_TESTATA = "#0e202e"
TESSERA = "#0f1d29"           # un filo piu' chiaro del pannello: si stacca senza bordo
BORDO = "#163850"
BORDO_FORTE = "#33778a"       # fuoco, passaggio del mouse

ACCENTO = "#5edfff"           # titoli, etichette, valori
ACCENTO_PIENO = "#06b6d4"     # barre
ACCENTO_SCURO = "#26668b"     # pulsante di invio, selezioni
TRACCIA = "#1c2b38"           # la parte vuota delle barre

TESTO = "#c8f4ff"             # testo principale (fumetti, nomi)
TESTO_SECONDARIO = "#7c9da9"  # orari, didascalie
TESTO_TENUE = "#45a3bc"       # etichette delle tessere
SEGNAPOSTO = "#1d5073"        # "Scrivi un messaggio…"

FUMETTO_METIS = "#12252e"
FUMETTO_UTENTE = "#0f2f40"

# Esiti, non stati: una barra oltre soglia, un'azione negata, un avviso.
OK = "#4ade80"
ATTENZIONE = "#fbbf24"
ERRORE = "#f87171"
ERRORE_FONDO = "#3b1219"      # il fondo del pulsante "Stop": rosso, ma scuro
BIANCO = "#ffffff"            # le due barre della pausa sull'icona della tray

# Le cinque voci del budget di contesto, nella Diagnostica (M5). Categorie,
# non esiti: devono distinguersi fra loro, e "web" — l'unica voce non
# fidata — resta del colore dell'attenzione.
VOCI_CONTESTO = {
    "system": TESTO_SECONDARIO,    # la persona: fissa, non si tocca
    "slot": "#a78bfa",             # il contesto corrente
    "riassunto": "#38bdf8",        # la memoria condensata
    "turni": OK,                   # la finestra scorrevole
    "web": ATTENZIONE,             # le fonti
}

# --- misure ------------------------------------------------------------------------

RAGGIO = 12
RAGGIO_PICCOLO = 8
SPAZIO = 8                    # l'unita': i margini sono multipli

# --- font --------------------------------------------------------------------------

FONT_TITOLI = "Orbitron"          # il nome, i titoli dei pannelli
FONT_TESTO = "Inter"              # tutto quello che si legge
FONT_NUMERI = "JetBrains Mono"    # orologio, percentuali: cifre a larghezza fissa

_FILE_FONT = ("Orbitron.ttf", "Inter.ttf", "JetBrainsMono-Regular.ttf",
              "JetBrainsMono-Bold.ttf")


def carica_font() -> dict[str, bool]:
    """Registra i font del progetto. Da chiamare dopo `QApplication`.

    Ritorna, per ogni famiglia, se e' davvero disponibile. Qt, quando un font
    manca, ripiega su un altro senza dirlo (qui: Tahoma), e l'interfaccia
    sembrerebbe solo "un po' diversa" — nel bundle, dove non la guarda
    nessuno prima dell'utente. Per questo si verifica con `QFontInfo`, che
    riporta la famiglia usata davvero, e non con `exactMatch`, che su
    Windows risponde False anche quando il font c'e'.
    """
    for nome in _FILE_FONT:
        QFontDatabase.addApplicationFont(str(RISORSE / "font" / nome))
    return {fam: QFontInfo(QFont(fam)).family() == fam
            for fam in (FONT_TITOLI, FONT_TESTO, FONT_NUMERI)}


def font(famiglia: str = FONT_TESTO, px: int = 13,
         peso: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(famiglia)
    f.setPixelSize(px)
    f.setWeight(peso)
    if famiglia == FONT_TITOLI:
        # Orbitron e' largo e stretto in altezza: con un filo di spaziatura
        # il nome "M.E.T.I.S" si legge come nella reference.
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    return f


# --- icone -------------------------------------------------------------------------

def icone_disponibili() -> list[str]:
    return sorted(p.stem for p in (RISORSE / "icone").glob("*.svg"))


@lru_cache(maxsize=256)
def _svg(nome: str) -> str:
    return (RISORSE / "icone" / f"{nome}.svg").read_text(encoding="utf-8")


def pixmap_icona(nome: str, colore: str = ACCENTO, lato: int = 20,
                 scala: float = 1.0) -> QPixmap:
    """L'icona Lucide `nome`, colorata e disegnata a `lato` pixel logici.

    Le icone Lucide usano `stroke="currentColor"`: il colore si sostituisce
    nel testo dell'SVG prima di disegnarlo, cosi' la stessa icona serve in
    ciano, in rosso e disattivata. `scala` e' il rapporto dei pixel del
    monitor: a 150% un'icona da 20 px si disegna a 30, o si sfoca.
    """
    svg = _svg(nome).replace("currentColor", colore)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    reali = max(1, round(lato * scala))
    pix = QPixmap(reali, reali)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, reali, reali))
    p.end()
    pix.setDevicePixelRatio(scala)
    return pix


def icona(nome: str, colore: str = ACCENTO, lato: int = 20,
          colore_disattivo: str = SEGNAPOSTO) -> QIcon:
    """Un `QIcon` con lo stato disattivato gia' colorato, non grigio di Qt."""
    ic = QIcon()
    for scala in (1.0, 1.25, 1.5, 2.0):
        ic.addPixmap(pixmap_icona(nome, colore, lato, scala), QIcon.Mode.Normal)
        ic.addPixmap(pixmap_icona(nome, colore_disattivo, lato, scala), QIcon.Mode.Disabled)
    return ic


def con_alfa(colore: str, alfa: float) -> QColor:
    """Lo stesso colore, trasparente: i bagliori del nucleo e i fondi tenui."""
    c = QColor(colore)
    c.setAlphaF(max(0.0, min(1.0, alfa)))
    return c


# --- il foglio di stile ------------------------------------------------------------

def applica(app) -> dict[str, bool]:
    """Font, font predefinito e foglio di stile, sull'applicazione intera.

    IL FONT NON STA NEL FOGLIO DI STILE
    Una regola `QWidget { font-family: ...; font-size: ... }` vale per
    OGNI widget e, in Qt, vince su `setFont`: i valori delle tessere in
    JetBrains Mono e il nome in Orbitron uscivano tutti in Inter a 13 px.
    Il font di base si imposta con `setFont` sull'applicazione, e ogni
    widget che ne vuole un altro lo chiede con `setFont` a sua volta.
    """
    disponibili = carica_font()
    app.setFont(font(FONT_TESTO, 13))
    app.setStyleSheet(foglio())
    return disponibili


def foglio() -> str:
    """Lo stile di tutta l'applicazione. I componenti specifici aggiungono
    solo cio' che li distingue, per `objectName`."""
    return f"""
QWidget {{
    background: {SFONDO};
    color: {TESTO};
}}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {PANNELLO_TESTATA}; color: {TESTO};
    border: 1px solid {BORDO}; padding: 4px 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDO}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {BORDO_FORTE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDO}; border-radius: 3px; min-width: 24px; }}
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {SFONDO_ALTO}; color: {TESTO};
    border: 1px solid {BORDO}; border-radius: {RAGGIO_PICCOLO}px;
    padding: 8px 10px; selection-background-color: {ACCENTO_SCURO};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {BORDO_FORTE}; }}
QPushButton {{
    background: {SFONDO_ALTO}; color: {ACCENTO};
    border: 1px solid {BORDO}; border-radius: {RAGGIO_PICCOLO}px;
    padding: 6px 12px;
}}
QPushButton:hover {{ border-color: {BORDO_FORTE}; }}
QPushButton:pressed {{ background: {PANNELLO_TESTATA}; }}
QPushButton:disabled {{ color: {SEGNAPOSTO}; border-color: {PANNELLO_TESTATA}; }}
QPushButton:checked {{ background: {PANNELLO_TESTATA}; border-color: {ACCENTO_PIENO}; }}
QMenu {{
    background: {PANNELLO}; border: 1px solid {BORDO}; padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {PANNELLO_TESTATA}; color: {ACCENTO}; }}
QMenu::item:disabled {{ color: {TESTO_SECONDARIO}; }}
QMenu::separator {{ height: 1px; background: {BORDO}; margin: 4px 6px; }}
QTableWidget {{
    background: {PANNELLO}; gridline-color: {PANNELLO_TESTATA};
    border: 1px solid {BORDO}; border-radius: {RAGGIO_PICCOLO}px;
    selection-background-color: {ACCENTO_SCURO}; font-size: 12px;
}}
QHeaderView::section {{
    background: {PANNELLO_TESTATA}; color: {TESTO_TENUE};
    border: none; padding: 5px; font-size: 11px;
}}
QComboBox {{
    background: {SFONDO_ALTO}; border: 1px solid {BORDO};
    border-radius: 6px; padding: 3px 8px;
}}
QComboBox QAbstractItemView {{ background: {PANNELLO}; border: 1px solid {BORDO}; }}
QSplitter::handle {{ background: {PANNELLO_TESTATA}; }}
QDialog {{ background: {PANNELLO}; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border-radius: 4px;
    border: 1px solid {BORDO_FORTE}; background: {SFONDO_ALTO};
}}
QCheckBox::indicator:checked {{ background: {ACCENTO_PIENO}; border-color: {ACCENTO}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENTO}; }}
"""
