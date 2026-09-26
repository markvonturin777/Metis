"""Overlay compatto: sta in un angolo mentre si lavora.

COSA CI STA E COSA NO
Ci sta quello che si guarda **di sfuggita**: lo stato, il livello del
microfono, l'ultima frase, e il fatto che le capacita' siano sospese. Non
ci sta niente che richieda di fermarsi a leggere — per quello c'e' l'Hub, a
un clic di distanza.

PHASE1 — IL NUCLEO IN MINIATURA
Al posto del pallino, lo stesso nucleo dell'Hub a 64 px: stessi colori,
stessi movimenti, cosi' chi passa da una vista all'altra legge lo stato
nello stesso modo. A 20 fotogrammi al secondo e non 30: in un angolo dello
schermo, tutto il giorno, la differenza non si vede e la CPU si'. Come
nell'Hub, con l'overlay nascosto il nucleo non si muove.

FRAMELESS VUOL DIRE GESTIRE IL TRASCINAMENTO A MANO
Togliendo la cornice si perde anche la barra del titolo, quindi lo
spostamento va implementato con gli eventi del mouse. La posizione si salva
alla chiusura: un overlay che ogni mattina ricompare in mezzo allo schermo
viene chiuso e non riaperto.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from metis.gui import tema
from metis.gui.componenti import PulsanteIcona
from metis.gui.widgets.nucleo import Nucleo
from metis.gui.widgets.stato import IndicatoreStato, VuMeter

IMPOSTAZIONI = Path("config/settings.toml")
LATO_NUCLEO = 64
FPS_NUCLEO = 20


class MinimalView(QWidget):
    chiede_fullscreen = Signal()
    chiede_ptt = Signal()
    chiede_kill = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metis")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                  # niente icona nella barra delle applicazioni
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(360)
        self._trascina_da: QPoint | None = None

        cornice = QWidget(self)
        cornice.setObjectName("cornice")
        fondo = tema.con_alfa(tema.PANNELLO, 0.94)
        cornice.setStyleSheet(
            f"#cornice {{ background: rgba({fondo.red()}, {fondo.green()}, {fondo.blue()},"
            f" {fondo.alpha()}); border-radius: {tema.RAGGIO}px;"
            f" border: 1px solid {tema.BORDO}; }}")
        esterno = QVBoxLayout(self)
        esterno.setContentsMargins(0, 0, 0, 0)
        esterno.addWidget(cornice)

        lay = QHBoxLayout(cornice)
        lay.setContentsMargins(10, 10, 12, 10)
        lay.setSpacing(10)

        self.nucleo = Nucleo(lato=LATO_NUCLEO, fps=FPS_NUCLEO)
        self.nucleo.setFixedSize(LATO_NUCLEO, LATO_NUCLEO)
        lay.addWidget(self.nucleo, 0, Qt.AlignTop)

        destra = QVBoxLayout()
        destra.setSpacing(6)
        riga = QHBoxLayout()
        riga.setSpacing(6)
        self.indicatore = IndicatoreStato()
        # Il pallino lo sostituisce il nucleo: resta l'etichetta, colorata.
        self.indicatore.pallino.hide()
        riga.addWidget(self.indicatore, 1)
        self.kill = QLabel("SOSPESO")
        self.kill.setFont(tema.font(tema.FONT_TITOLI, 10))
        self.kill.setStyleSheet(f"color: {tema.ERRORE};")
        self.kill.setVisible(False)
        riga.addWidget(self.kill)
        espandi = PulsanteIcona("maximize-2", "Apri l'Hub", lato=26, lato_icona=14)
        espandi.clicked.connect(self.chiede_fullscreen.emit)
        riga.addWidget(espandi)
        destra.addLayout(riga)

        self.vu = VuMeter()
        destra.addWidget(self.vu)

        self.ultima = QLabel("—")
        self.ultima.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; font-size: 12px;")
        self.ultima.setWordWrap(False)
        destra.addWidget(self.ultima)

        pulsanti = QHBoxLayout()
        pulsanti.setSpacing(6)
        self.ptt = QPushButton("Parla  ·  Ctrl+Alt+M")
        self.ptt.clicked.connect(self.chiede_ptt.emit)
        self.ptt.setStyleSheet("QPushButton { padding: 5px 10px; font-size: 12px; }")
        pulsanti.addWidget(self.ptt, 1)
        stop = QPushButton("Stop")
        stop.setToolTip("Zittisce e sospende T2/T3")
        stop.clicked.connect(self.chiede_kill.emit)
        stop.setStyleSheet(
            f"QPushButton {{ background: {tema.ERRORE_FONDO}; color: {tema.ERRORE};"
            f" border-color: {tema.ERRORE_FONDO}; padding: 5px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {tema.ERRORE}; }}")
        pulsanti.addWidget(stop)
        destra.addLayout(pulsanti)
        lay.addLayout(destra, 1)

        self._carica_posizione()

    # -- ingressi ----------------------------------------------------------

    @Slot(str)
    def imposta_stato(self, stato: str) -> None:
        self.indicatore.imposta(stato)
        self.nucleo.imposta_stato(stato)

    @Slot(str)
    def imposta_ultima(self, testo: str) -> None:
        t = testo.strip()
        if len(t) > 46:
            t = t[:46] + "…"
        self.ultima.setText(t or "—")

    @Slot(bool)
    def imposta_kill(self, sospeso: bool) -> None:
        self.kill.setVisible(sospeso)
        self.nucleo.imposta_kill(sospeso)

    @Slot(bool)
    def imposta_pausa(self, attiva: bool) -> None:
        self.nucleo.imposta_pausa(attiva)

    # -- trascinamento -----------------------------------------------------

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._trascina_da = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._trascina_da is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._trascina_da)
            e.accept()

    def mouseReleaseEvent(self, e) -> None:
        self._trascina_da = None

    # -- posizione persistita ----------------------------------------------

    def _carica_posizione(self) -> None:
        try:
            if IMPOSTAZIONI.exists():
                d = tomllib.loads(IMPOSTAZIONI.read_text(encoding="utf-8"))
                pos = d.get("minimal", {})
                if "x" in pos and "y" in pos:
                    self.move(int(pos["x"]), int(pos["y"]))
                    return
        except Exception:                     # noqa: BLE001
            pass                              # posizione predefinita, non e' grave
        self.move(60, 60)

    def salva_posizione(self) -> None:
        try:
            IMPOSTAZIONI.parent.mkdir(parents=True, exist_ok=True)
            p = self.pos()
            testo = IMPOSTAZIONI.read_text(encoding="utf-8") if IMPOSTAZIONI.exists() else ""
            righe = [r for r in testo.splitlines()
                     if not r.startswith(("x ", "y ", "[minimal]"))]
            righe += ["[minimal]", f"x = {p.x()}", f"y = {p.y()}"]
            IMPOSTAZIONI.write_text("\n".join(righe) + "\n", encoding="utf-8")
        except Exception:                     # noqa: BLE001
            pass
