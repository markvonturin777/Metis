"""I mattoni dell'Hub: pannello, tessera, barra, pulsante con icona, pillola.

Ogni vista di PHASE1 si costruisce con questi, e basta. Il motivo e' lo
stesso della palette unica: se il pannello del meteo e quello del sistema
avessero ciascuno il proprio stile, divergerebbero al primo ritocco — e la
coerenza visiva e' esattamente quello che la reference ha e la control room
di PHASE0 non aveva.

BARRA E PILLOLA SI DISEGNANO, NON SI STILIZZANO
`QProgressBar` con un foglio di stile ridisegna tutto a ogni valore e si
presta male a una traccia sottile con i testi sopra. Una barra aggiornata
due volte al secondo per tre metriche e' poca cosa, ma NFR-8 si misura
anche qui, e disegnarla in `paintEvent` costa meno e non ha sorprese.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metis.gui import tema


class Pannello(QFrame):
    """Una card: testata con icona, titolo e azioni, poi il corpo.

        pan = Pannello("Sistema", "cpu")
        pan.corpo.addWidget(...)
        pan.aggiungi_azione(PulsanteIcona("download", lato=26))
    """

    def __init__(self, titolo: str, icona: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("pannello")
        self.setStyleSheet(f"""
            #pannello {{ background: {tema.PANNELLO}; border: 1px solid {tema.BORDO};
                         border-radius: {tema.RAGGIO}px; }}
            #testata {{ background: {tema.PANNELLO_TESTATA};
                        border: none; border-bottom: 1px solid {tema.BORDO};
                        border-top-left-radius: {tema.RAGGIO - 1}px;
                        border-top-right-radius: {tema.RAGGIO - 1}px; }}
            #corpo {{ background: transparent; border: none; }}
        """)
        esterno = QVBoxLayout(self)
        esterno.setContentsMargins(1, 1, 1, 1)
        esterno.setSpacing(0)

        self.testata = QFrame()
        self.testata.setObjectName("testata")
        riga = QHBoxLayout(self.testata)
        riga.setContentsMargins(14, 9, 10, 9)
        riga.setSpacing(8)
        if icona:
            ic = QLabel()
            ic.setPixmap(tema.pixmap_icona(icona, tema.ACCENTO, 16,
                                           self.devicePixelRatioF()))
            riga.addWidget(ic)
        self.titolo = QLabel(titolo)
        self.titolo.setFont(tema.font(tema.FONT_TITOLI, 13, QFont.Weight.Medium))
        self.titolo.setStyleSheet(f"color: {tema.ACCENTO};")
        riga.addWidget(self.titolo)
        riga.addStretch(1)
        self._azioni = riga
        esterno.addWidget(self.testata)

        contenitore = QFrame()
        contenitore.setObjectName("corpo")
        self.corpo = QVBoxLayout(contenitore)
        self.corpo.setContentsMargins(12, 12, 12, 12)
        self.corpo.setSpacing(tema.SPAZIO)
        esterno.addWidget(contenitore, 1)

    def aggiungi_azione(self, widget: QWidget) -> QWidget:
        self._azioni.addWidget(widget)
        return widget


class Tessera(QFrame):
    """Un'etichetta e un valore, centrati. Le caselle "CPU 8%" della reference."""

    def __init__(self, etichetta: str, valore: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("tessera")
        self.setStyleSheet(f"#tessera {{ background: {tema.TESSERA}; border: none;"
                           f" border-radius: {tema.RAGGIO_PICCOLO}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(3)
        self.etichetta = QLabel(etichetta)
        self.etichetta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etichetta.setFont(tema.font(tema.FONT_TESTO, 11))
        self.etichetta.setStyleSheet(f"color: {tema.TESTO_TENUE};")
        self.valore = QLabel(valore)
        self.valore.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.valore.setFont(tema.font(tema.FONT_NUMERI, 13))
        self.valore.setStyleSheet(f"color: {tema.ACCENTO};")
        lay.addWidget(self.etichetta)
        lay.addWidget(self.valore)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def imposta(self, valore: str, colore: str | None = None) -> None:
        if valore != self.valore.text():
            self.valore.setText(valore)
        self.valore.setStyleSheet(f"color: {colore or tema.ACCENTO};")


class Barra(QWidget):
    """Etichetta a sinistra, valore a destra, traccia sottile sotto.

    Sopra `soglia` la barra diventa del colore d'errore: e' l'indicatore
    rosso della VRAM che la matrice degli errori di M7 promette.
    """

    ALTEZZA = 30

    def __init__(self, etichetta: str, soglia: float | None = None, parent=None):
        super().__init__(parent)
        self.etichetta = etichetta
        self.soglia = soglia
        self.frazione = 0.0
        self.testo = "—"
        self.setFixedHeight(self.ALTEZZA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._f_etichetta = tema.font(tema.FONT_TESTO, 11, QFont.Weight.Medium)
        self._f_valore = tema.font(tema.FONT_NUMERI, 11)

    @property
    def in_allarme(self) -> bool:
        return self.soglia is not None and self.frazione >= self.soglia

    def imposta(self, frazione: float, testo: str) -> None:
        frazione = max(0.0, min(1.0, frazione))
        if (frazione, testo) == (self.frazione, self.testo):
            return                      # due volte al secondo: niente ridisegno inutile
        self.frazione, self.testo = frazione, testo
        self.update()

    def colore(self) -> str:
        return tema.ERRORE if self.in_allarme else tema.ACCENTO_PIENO

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setFont(self._f_etichetta)
        p.setPen(tema.con_alfa(tema.ACCENTO, 1.0))
        p.drawText(QRectF(0, 0, w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.etichetta)
        p.setFont(self._f_valore)
        p.setPen(tema.con_alfa(tema.ERRORE if self.in_allarme else tema.ACCENTO, 1.0))
        p.drawText(QRectF(0, 0, w, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self.testo)
        traccia = QRectF(0, 21, w, 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tema.con_alfa(tema.TRACCIA, 1.0))
        p.drawRoundedRect(traccia, 2.5, 2.5)
        if self.frazione > 0:
            piena = QRectF(0, 21, max(5.0, w * self.frazione), 5)
            p.setBrush(tema.con_alfa(self.colore(), 1.0))
            p.drawRoundedRect(piena, 2.5, 2.5)
        p.end()


class PulsanteIcona(QPushButton):
    """Un pulsante quadrato con un'icona e un suggerimento. Niente testo:
    il suggerimento c'e' sempre, perche' un'icona da sola e' un indovinello."""

    def __init__(self, icona: str, suggerimento: str = "", lato: int = 56,
                 lato_icona: int | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("pulsanteIcona")
        self.lato_icona = lato_icona or max(14, lato // 2 - 4)
        self.setFixedSize(lato, lato)
        self.setToolTip(suggerimento)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setStyleSheet(f"""
            #pulsanteIcona {{ background: {tema.SFONDO_ALTO}; border: 1px solid {tema.BORDO};
                              border-radius: {tema.RAGGIO if lato >= 40 else tema.RAGGIO_PICCOLO}px;
                              padding: 0; }}
            #pulsanteIcona:hover {{ border-color: {tema.BORDO_FORTE}; }}
            #pulsanteIcona:pressed {{ background: {tema.PANNELLO_TESTATA}; }}
            #pulsanteIcona:checked {{ background: {tema.PANNELLO_TESTATA};
                                      border-color: {tema.ACCENTO_PIENO}; }}
            #pulsanteIcona:disabled {{ border-color: {tema.PANNELLO_TESTATA}; }}
        """)
        self.nome_icona = ""
        self.colore_icona = ""
        self.imposta_icona(icona)

    def imposta_icona(self, nome: str, colore: str = tema.ACCENTO) -> None:
        if (nome, colore) == (self.nome_icona, self.colore_icona):
            return
        self.nome_icona, self.colore_icona = nome, colore
        self.setIcon(tema.icona(nome, colore, self.lato_icona))
        self.setIconSize(QSize(self.lato_icona, self.lato_icona))


class Pillola(QWidget):
    """Un pallino e una frase in una capsula: "● Operativo", "● sta pensando".

    Il colore arriva da fuori (dalla palette degli stati, di solito): la
    pillola non sa cosa significa, lo mostra e basta.
    """

    def __init__(self, testo: str = "", colore: str = tema.OK, px: int = 12, parent=None):
        super().__init__(parent)
        self._font = tema.font(tema.FONT_TESTO, px, QFont.Weight.Medium)
        self.testo = testo
        self.colore = colore
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def imposta(self, testo: str, colore: str) -> None:
        if (testo, colore) == (self.testo, self.colore):
            return
        self.testo, self.colore = testo, colore
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        m = QFontMetrics(self._font)
        return QSize(m.horizontalAdvance(self.testo) + 38, m.height() + 12)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        capsula = QPainterPath()
        capsula.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(capsula, tema.con_alfa(self.colore, 0.10))
        p.setPen(tema.con_alfa(self.colore, 0.30))
        p.drawPath(capsula)
        d = 7.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tema.con_alfa(self.colore, 1.0))
        p.drawEllipse(QRectF(12, r.center().y() - d / 2, d, d))
        p.setFont(self._font)
        p.setPen(tema.con_alfa(self.colore, 1.0))
        p.drawText(r.adjusted(26, 0, -10, 0),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.testo)
        p.end()
