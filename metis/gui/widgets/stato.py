"""Indicatore di stato e VU meter. Li usano entrambe le viste.

L'INDICATORE E' L'INFORMAZIONE PIU' IMPORTANTE DELL'OVERLAY
Deve dire una cosa sola, e dirla **di sbieco e a due metri**: sto
ascoltando, sto pensando, sto parlando, aspetto te. Da qui il pallino
grande e i colori distanti fra loro invece di sfumature eleganti.

IL DIRADAMENTO DEL VU METER STA QUI
Il nucleo emette il livello 31 volte al secondo. Ridisegnare a quel ritmo
satura la coda eventi di Qt e produce scatti — proprio il difetto che NFR-8
misura. Si accumula il massimo e si ridisegna a 15 Hz: l'occhio non
distingue di piu', e il picco non si perde perche' si tiene il massimo e non
l'ultimo valore.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from metis.core.palette import esadecimale, significato

VU_HZ = 15.0
DB_MIN, DB_MAX = -60.0, -6.0        # sotto -60 e' silenzio, sopra -6 e' clipping


class Pallino(QWidget):
    """Un cerchio colorato. Piu' leggibile di qualunque etichetta."""

    def __init__(self, diametro: int = 14, parent=None):
        super().__init__(parent)
        self._colore = QColor(esadecimale("DORMIENTE"))
        self.setFixedSize(diametro, diametro)

    def imposta(self, stato: str) -> None:
        self._colore = QColor(esadecimale(stato))
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._colore)
        p.setPen(Qt.NoPen)
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class IndicatoreStato(QWidget):
    """Pallino piu' nome dello stato, in parole comprensibili."""

    def __init__(self, con_testo: bool = True, parent=None):
        super().__init__(parent)
        self.stato = "DORMIENTE"
        self.pallino = Pallino()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.pallino)
        self.etichetta = QLabel(significato(self.stato)) if con_testo else None
        if self.etichetta is not None:
            self.etichetta.setStyleSheet("color: #cbd5e1; font-size: 13px;")
            lay.addWidget(self.etichetta)
        lay.addStretch(1)

    @Slot(str)
    def imposta(self, stato: str) -> None:
        self.stato = stato
        self.pallino.imposta(stato)
        if self.etichetta is not None:
            self.etichetta.setText(significato(stato))
            self.etichetta.setStyleSheet(
                f"color: {esadecimale(stato)}; font-size: 13px;")


class VuMeter(QWidget):
    """Barra del livello in ingresso, ridisegnata a 15 Hz."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._livello = 0.0          # 0..1, gia' normalizzato
        self._picco_grezzo = DB_MIN
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._ridisegna)
        self._timer.start(int(1000 / VU_HZ))

    @Slot(float, float)
    def campiona(self, rms_db: float, picco_db: float) -> None:
        """Chiamata ~31 volte al secondo: accumula e basta, non ridisegna.

        Si tiene il MASSIMO dell'intervallo e non l'ultimo valore: con
        l'ultimo, un picco caduto fra due ridisegni sparirebbe, e il VU
        meter mostrerebbe meno di quello che il microfono ha sentito.
        """
        self._picco_grezzo = max(self._picco_grezzo, rms_db)

    def _ridisegna(self) -> None:
        db = max(DB_MIN, min(DB_MAX, self._picco_grezzo))
        nuovo = (db - DB_MIN) / (DB_MAX - DB_MIN)
        self._picco_grezzo = DB_MIN
        # Discesa morbida: un VU che cade a picco e' fastidioso da guardare.
        self._livello = max(nuovo, self._livello * 0.7)
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor("#1e293b"))
        larghezza = int(r.width() * self._livello)
        if larghezza > 0:
            colore = "#22c55e" if self._livello < 0.85 else "#f59e0b"
            p.fillRect(0, 0, larghezza, r.height(), QColor(colore))
