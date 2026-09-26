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

PHASE1 — E' LA VISTA "DIAGNOSTICA"
La vista di tutti i giorni e' diventata l'Hub; questa resta per capire
perche' Metis ha fatto qualcosa (D-UI 4). Il contenuto e' quello di PHASE0;
l'aspetto viene da `tema.py`, come il resto.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from metis.gui import tema
from metis.gui.componenti import Pillola, PulsanteIcona
from metis.gui.testo import elastica, per_etichetta
from metis.gui.widgets.audit import VistaAudit
from metis.gui.widgets.comandi import PannelloComandi
from metis.gui.widgets.contesto import PannelloContesto
from metis.gui.widgets.conversazione import Conversazione
from metis.gui.widgets.stato import IndicatoreStato, VuMeter
from metis.gui.widgets.telemetria import Telemetria

class FullscreenView(QWidget):
    chiede_minimal = Signal()
    chiede_hub = Signal()
    chiede_ptt = Signal()
    chiede_kill = Signal()

    def __init__(self, conversazione: Conversazione, telemetria: Telemetria,
                 audit=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metis — diagnostica")
        self.resize(1180, 720)

        # Gli STESSI oggetti della vista minimal: e' cosi' che il passaggio
        # non perde stato.
        self.conversazione = conversazione
        self.telemetria = telemetria

        radice = QVBoxLayout(self)
        radice.setContentsMargins(0, 0, 0, 10)
        radice.setSpacing(10)
        radice.addWidget(self._barra_superiore())

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
        interno = QHBoxLayout()
        interno.setContentsMargins(12, 0, 12, 0)
        interno.addWidget(verticale)
        radice.addLayout(interno, 1)

    # -- pezzi -------------------------------------------------------------

    def _barra_superiore(self) -> QFrame:
        """La stessa intestazione dell'Hub, con "Diagnostica" accanto al nome."""
        barra = QFrame()
        barra.setObjectName("intestazioneDiagnostica")
        barra.setFixedHeight(58)
        barra.setStyleSheet(f"#intestazioneDiagnostica {{ background: {tema.SFONDO_ALTO};"
                            f" border: none; border-bottom: 1px solid {tema.BORDO}; }}")
        riga = QHBoxLayout(barra)
        riga.setContentsMargins(20, 0, 14, 0)
        riga.setSpacing(12)

        titolo = QLabel("M.E.T.I.S")
        titolo.setFont(tema.font(tema.FONT_TITOLI, 18, QFont.Weight.Bold))
        titolo.setStyleSheet(f"color: {tema.ACCENTO};")
        riga.addWidget(titolo)
        riga.addWidget(Pillola("Diagnostica", tema.TESTO_TENUE, px=11))
        riga.addSpacing(10)

        self.indicatore = IndicatoreStato()
        riga.addWidget(self.indicatore)

        self.kill = QLabel("CAPACITA' SOSPESE")
        self.kill.setFont(tema.font(tema.FONT_TITOLI, 11))
        self.kill.setStyleSheet(f"color: {tema.ERRORE};")
        self.kill.setVisible(False)
        riga.addWidget(self.kill)
        riga.addStretch(1)

        self.avvio = QLabel("")
        self.avvio.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; font-size: 11px;")
        riga.addWidget(self.avvio)

        for icona, suggerimento, segnale in (
                ("mic", "Parla (Ctrl+Alt+M)", self.chiede_ptt),
                ("shield", "Kill switch: sospende le azioni sul PC", self.chiede_kill),
                ("layout-dashboard", "Torna all'Hub", self.chiede_hub),
                ("minimize-2", "Vista compatta", self.chiede_minimal)):
            b = PulsanteIcona(icona, suggerimento, lato=36)
            b.clicked.connect(segnale)
            riga.addWidget(b)
        return barra

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

        # Elastica: una risposta con un URL lungo non deve allargare la
        # colonna. Vedi `metis/gui/testo.py`.
        self.corrente = elastica(QLabel("—"))
        self.corrente.setAlignment(Qt.AlignTop)
        self.corrente.setStyleSheet(
            f"background: {tema.PANNELLO}; border: 1px solid {tema.BORDO};"
            f" border-radius: {tema.RAGGIO_PICCOLO}px; padding: 10px; font-size: 13px;")
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
        self.corrente.setText(per_etichetta(testo or "—"))

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
    lab.setFont(tema.font(tema.FONT_TITOLI, 11))
    lab.setStyleSheet(f"color: {tema.ACCENTO}; letter-spacing: 1px;")
    lab.setFrameShape(QFrame.NoFrame)
    return lab
