"""La control room. Tre colonne: conversazione, corrente, cruscotto.

NON E' UN'ALTRA APPLICAZIONE
Minimal e Fullscreen sono due proiezioni dello stesso modello. Il passaggio
fra le due non ricostruisce niente e non perde niente: la conversazione, le
metriche e lo stato restano quelli, perche' i widget sono gli stessi
oggetti, semplicemente mostrati altrove. Se fossero due applicazioni, il
passaggio sarebbe un riavvio travestito.

L'AUDIT LOG STA IN BASSO PERCHE' E' LO STRUMENTO DI M4
Durante l'automazione la domanda sara' sempre "perche' non l'ha fatto?", e
la risposta e' li'. Occupa tutta la larghezza perche' i motivi dei rifiuti
sono frasi, non sigle.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from metis.core.palette import esadecimale
from metis.gui.widgets.audit import VistaAudit
from metis.gui.widgets.comandi import PannelloComandi
from metis.gui.widgets.contesto import PannelloContesto
from metis.gui.widgets.conversazione import Conversazione
from metis.gui.widgets.stato import IndicatoreStato, VuMeter
from metis.gui.widgets.telemetria import Telemetria

FOGLIO = """
QWidget { background: #0f172a; color: #e2e8f0; }
QLabel { color: #cbd5e1; }
QTableWidget { background: #0b1220; gridline-color: #1e293b;
               selection-background-color: #1e3a5f; font-size: 12px; }
QHeaderView::section { background: #1e293b; color: #94a3b8; border: none;
                       padding: 4px; font-size: 11px; }
QComboBox { background: #1e293b; border: 1px solid #334155; padding: 2px 6px; }
QSplitter::handle { background: #1e293b; }
"""


class FullscreenView(QWidget):
    chiede_minimal = Signal()
    chiede_ptt = Signal()
    chiede_kill = Signal()

    def __init__(self, conversazione: Conversazione, telemetria: Telemetria,
                 audit=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metis — control room")
        self.resize(1180, 720)
        self.setStyleSheet(FOGLIO)

        # Gli STESSI oggetti della vista minimal: e' cosi' che il passaggio
        # non perde stato.
        self.conversazione = conversazione
        self.telemetria = telemetria

        radice = QVBoxLayout(self)
        radice.setContentsMargins(10, 8, 10, 8)
        radice.setSpacing(8)
        radice.addLayout(self._barra_superiore())

        centro = QSplitter(Qt.Horizontal)
        centro.addWidget(self._colonna_conversazione())
        centro.addWidget(self._colonna_corrente())
        centro.addWidget(self.telemetria)
        centro.setStretchFactor(0, 4)
        centro.setStretchFactor(1, 3)
        centro.setStretchFactor(2, 2)

        verticale = QSplitter(Qt.Vertical)
        verticale.addWidget(centro)
        self.audit = VistaAudit(audit)
        verticale.addWidget(self.audit)
        verticale.setStretchFactor(0, 3)
        verticale.setStretchFactor(1, 1)
        radice.addWidget(verticale, 1)

    # -- pezzi -------------------------------------------------------------

    def _barra_superiore(self) -> QHBoxLayout:
        riga = QHBoxLayout()
        titolo = QLabel("METIS")
        titolo.setStyleSheet("font-size: 16px; font-weight: bold;"
                             " letter-spacing: 3px; color: #e2e8f0;")
        riga.addWidget(titolo)
        riga.addSpacing(16)

        self.indicatore = IndicatoreStato()
        riga.addWidget(self.indicatore)

        self.kill = QLabel("CAPACITA' SOSPESE")
        self.kill.setStyleSheet(
            f"color: {esadecimale('ERRORE')}; font-weight: bold; font-size: 12px;")
        self.kill.setVisible(False)
        riga.addWidget(self.kill)
        riga.addStretch(1)

        self.avvio = QLabel("")
        self.avvio.setStyleSheet("color: #64748b; font-size: 11px;")
        riga.addWidget(self.avvio)

        ptt = QPushButton("Parla")
        ptt.clicked.connect(self.chiede_ptt.emit)
        stop = QPushButton("Stop")
        stop.clicked.connect(self.chiede_kill.emit)
        mini = QPushButton("Minimal")
        mini.clicked.connect(self.chiede_minimal.emit)
        for b in (ptt, stop, mini):
            b.setStyleSheet("QPushButton { background: #1e293b; border: none;"
                            " padding: 5px 14px; border-radius: 4px; }"
                            "QPushButton:hover { background: #334155; }")
            riga.addWidget(b)
        return riga

    def _colonna_conversazione(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_titolo("CONVERSAZIONE"))
        lay.addWidget(self.conversazione)
        return box

    def _colonna_corrente(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_titolo("ADESSO"))

        self.vu = VuMeter()
        lay.addWidget(self.vu)

        self.corrente = QLabel("—")
        self.corrente.setWordWrap(True)
        self.corrente.setAlignment(Qt.AlignTop)
        self.corrente.setStyleSheet(
            "background: #0b1220; border: 1px solid #1e293b; border-radius: 6px;"
            " padding: 10px; font-size: 13px;")
        lay.addWidget(self.corrente, 1)

        lay.addWidget(_titolo("CONTESTO"))
        # Il pannello di M5. Sta nella colonna "adesso" e non fra i cruscotti
        # perche' non e' una misura: e' il contenuto del prompt corrente, e
        # si guarda mentre si parla, non a fine sessione.
        self.contesto = PannelloContesto()
        lay.addWidget(self.contesto)

        lay.addWidget(_titolo("COMANDI RAPIDI"))
        # In M3 era un'etichetta di sola lettura: il contenitore predisposto
        # per M4. Adesso e' l'editor vero, e il resto della colonna non se
        # ne accorge.
        self.comandi = PannelloComandi()
        lay.addWidget(self.comandi)
        return box

    # -- ingressi ----------------------------------------------------------

    @Slot(str)
    def imposta_stato(self, stato: str) -> None:
        self.indicatore.imposta(stato)

    @Slot(str)
    def imposta_corrente(self, testo: str) -> None:
        self.corrente.setText(testo or "—")

    @Slot(bool)
    def imposta_kill(self, sospeso: bool) -> None:
        self.kill.setVisible(sospeso)

    @Slot(dict)
    def imposta_contesto(self, stato: dict) -> None:
        self.contesto.aggiorna(stato)

    def collega_comandi(self, libreria) -> None:
        """La libreria dei comandi, quando il sistema e' pronto."""
        self.comandi.collega(libreria)


def _titolo(testo: str) -> QLabel:
    lab = QLabel(testo)
    lab.setStyleSheet("color: #64748b; font-size: 11px; letter-spacing: 1px;")
    lab.setFrameShape(QFrame.NoFrame)
    return lab
