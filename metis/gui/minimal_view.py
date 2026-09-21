"""Overlay compatto: sta in un angolo mentre si lavora.

COSA CI STA E COSA NO
Ci sta quello che si guarda **di sfuggita**: lo stato, il livello del
microfono, l'ultima frase, e il fatto che le capacita' siano sospese. Non
ci sta niente che richieda di fermarsi a leggere — per quello c'e' la
control room, a un clic di distanza.

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

from metis.core.palette import esadecimale
from metis.gui.widgets.stato import IndicatoreStato, VuMeter

IMPOSTAZIONI = Path("config/settings.toml")


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
        self.setFixedWidth(340)
        self._trascina_da: QPoint | None = None

        cornice = QWidget(self)
        cornice.setObjectName("cornice")
        cornice.setStyleSheet(
            "#cornice { background: rgba(15, 23, 42, 235); border-radius: 10px;"
            " border: 1px solid #1e293b; }")
        esterno = QVBoxLayout(self)
        esterno.setContentsMargins(0, 0, 0, 0)
        esterno.addWidget(cornice)

        lay = QVBoxLayout(cornice)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)

        riga = QHBoxLayout()
        self.indicatore = IndicatoreStato()
        riga.addWidget(self.indicatore, 1)
        self.kill = QLabel("SOSPESO")
        self.kill.setStyleSheet(
            f"color: {esadecimale('ERRORE')}; font-size: 10px; font-weight: bold;")
        self.kill.setVisible(False)
        riga.addWidget(self.kill)
        espandi = QPushButton("▣")
        espandi.setFixedSize(22, 22)
        espandi.setToolTip("Control room")
        espandi.clicked.connect(self.chiede_fullscreen.emit)
        riga.addWidget(espandi)
        lay.addLayout(riga)

        self.vu = VuMeter()
        lay.addWidget(self.vu)

        self.ultima = QLabel("—")
        self.ultima.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.ultima.setWordWrap(False)
        lay.addWidget(self.ultima)

        pulsanti = QHBoxLayout()
        self.ptt = QPushButton("Parla  (Ctrl+Alt+M)")
        self.ptt.clicked.connect(self.chiede_ptt.emit)
        self.ptt.setStyleSheet(_stile_pulsante("#1e293b"))
        pulsanti.addWidget(self.ptt, 1)
        stop = QPushButton("Stop")
        stop.setToolTip("Zittisce e sospende T2/T3")
        stop.clicked.connect(self.chiede_kill.emit)
        stop.setStyleSheet(_stile_pulsante("#7f1d1d"))
        pulsanti.addWidget(stop)
        lay.addLayout(pulsanti)

        self._carica_posizione()

    # -- ingressi ----------------------------------------------------------

    @Slot(str)
    def imposta_stato(self, stato: str) -> None:
        self.indicatore.imposta(stato)

    @Slot(str)
    def imposta_ultima(self, testo: str) -> None:
        t = testo.strip()
        if len(t) > 46:
            t = t[:46] + "…"
        self.ultima.setText(t or "—")

    @Slot(bool)
    def imposta_kill(self, sospeso: bool) -> None:
        self.kill.setVisible(sospeso)

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


def _stile_pulsante(sfondo: str) -> str:
    return (f"QPushButton {{ background: {sfondo}; color: #e2e8f0; border: none;"
            " border-radius: 5px; padding: 6px; font-size: 12px; }"
            f"QPushButton:hover {{ background: #334155; }}")
