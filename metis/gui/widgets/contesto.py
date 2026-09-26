"""Cosa c'e' dentro il prompt, adesso. Il pannello di M5.

E' l'unico posto in cui si vede la cosa che in M5 decide tutto e che non
compare da nessun'altra parte: **il contenuto del contesto**. La
conversazione mostra cosa e' stato detto, l'audit mostra cosa e' stato fatto,
la telemetria mostra quanto e' costato. Nessuno dei tre dice quali fonti il
modello stesse leggendo quando ha risposto, ne' se la memoria fosse al
quaranta o al novanta per cento.

Senza questo pannello, la domanda "perche' ha risposto cosi'?" si risolve
rileggendo i log e ricostruendo il prompt a mano. E' esattamente la stessa
ragione per cui l'audit log sta in basso nella control room: durante
un'iterazione la domanda ricorrente ha un posto dove si risponde da sola.

LA BARRA DEL BUDGET E' UNA SOLA BARRA A SEGMENTI
Quattro barre separate direbbero quanto occupa ciascuna voce e non
direbbero la cosa che conta, cioe' che sono in concorrenza: ogni token
speso in fonti e' un token tolto alla memoria. Una barra sola con quattro
segmenti lo dice guardandola.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from metis.gui import tema
from metis.gui.testo import elastica, per_etichetta, url_breve
from metis.llm.grounding import BUDGET, CONTESTO_MAX

# Un colore per voce del budget. Gli stessi nomi delle chiavi di
# `grounding.BUDGET`: se qualcuno ne aggiunge una, qui compare grigia invece
# di sparire.
COLORI = tema.VOCI_CONTESTO
GRIGIO = tema.TRACCIA
ROSSO = tema.ERRORE
_RIQUADRO = (f"background: {tema.PANNELLO}; border: 1px solid {tema.BORDO};"
             f" border-radius: {tema.RAGGIO_PICCOLO}px; padding: 8px; font-size: 11px;")

# Oltre questa frazione la barra diventa rossa: e' la soglia oltre la quale
# il riassunto scattera' al prossimo passaggio in DORMIENTE.
SOGLIA_ALLARME = 0.70


class PannelloContesto(QWidget):
    """Budget, slot iniettati e fonti dell'ultimo turno."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._costruisci()
        self.aggiorna({})

    def _costruisci(self) -> None:
        radice = QVBoxLayout(self)
        radice.setContentsMargins(0, 0, 0, 0)
        radice.setSpacing(6)

        self.totale = QLabel("—")
        self.totale.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; font-size: 11px;")
        radice.addWidget(self.totale)

        # La barra a segmenti: un QWidget per voce, larghezza proporzionale.
        self.barra = QWidget()
        self.barra.setFixedHeight(14)
        self._segmenti_lay = QHBoxLayout(self.barra)
        self._segmenti_lay.setContentsMargins(0, 0, 0, 0)
        self._segmenti_lay.setSpacing(1)
        self._segmenti: dict[str, QWidget] = {}
        for voce in list(BUDGET) + ["libero"]:
            s = QWidget()
            s.setStyleSheet(f"background: {COLORI.get(voce, GRIGIO)};"
                            " border-radius: 2px;")
            self._segmenti[voce] = s
            self._segmenti_lay.addWidget(s, 0)
        radice.addWidget(self.barra)

        self.legenda = QLabel("")
        self.legenda.setStyleSheet("font-size: 10px;")
        self.legenda.setTextFormat(Qt.RichText)
        radice.addWidget(self.legenda)

        # Slot e fonti portano testo che arriva da fuori: vedi
        # `metis/gui/testo.py` sul link di 1500 caratteri che allargava la
        # finestra oltre lo schermo.
        self.slot = elastica(QLabel("—"))
        self.slot.setAlignment(Qt.AlignTop)
        self.slot.setStyleSheet(f"{_RIQUADRO} color: {tema.TESTO};")
        radice.addWidget(self.slot)

        self.fonti = elastica(QLabel("—"))
        self.fonti.setAlignment(Qt.AlignTop)
        self.fonti.setStyleSheet(f"{_RIQUADRO} color: {tema.ATTENZIONE};")
        radice.addWidget(self.fonti)
        radice.addStretch(1)

    # -- ingresso ----------------------------------------------------------

    @Slot(dict)
    def aggiorna(self, stato: dict) -> None:
        """Un dizionario, non oggetti: arriva da un altro thread via Signal.

        Passare `Memoria` e `Slots` significherebbe leggerli dal thread della
        GUI mentre il turno li scrive. Hanno un lock e reggerebbero, ma la
        regola di M3 vale ancora: fra i due thread passano dati, mai oggetti
        vivi.
        """
        conteggio = stato.get("conteggio") or {}
        totale = int(conteggio.get("totale", 0))
        self._barra(conteggio, totale)

        riassunti = stato.get("riassunti", 0)
        coda = f"  ·  {riassunti} riassunti" if riassunti else ""
        occupato = totale / max(1, CONTESTO_MAX - BUDGET["risposta"])
        self.totale.setText(
            f"CONTESTO  {totale} / {CONTESTO_MAX} token  "
            f"({occupato * 100:.0f}% dello spazio utile){coda}")

        self.slot.setText(per_etichetta(stato.get("slot") or "nessun riferimento attivo"))

        fonti = stato.get("fonti") or []
        if fonti:
            self.fonti.setText("FONTI DELL'ULTIMO TURNO — contenuto non fidato\n"
                               + "\n".join(f"{i}. {url_breve(u)}"
                                            for i, u in enumerate(fonti, 1)))
            # Gli URL interi restano a portata di mouse.
            self.fonti.setToolTip("\n".join(fonti))
        else:
            self.fonti.setText("nessuna fonte nell'ultimo turno")
            self.fonti.setToolTip("")

    def _barra(self, conteggio: dict, totale: int) -> None:
        utile = max(1, CONTESTO_MAX - BUDGET["risposta"])
        pezzi = []
        for voce in BUDGET:
            n = int(conteggio.get(voce, 0))
            # Lo stretch e' un intero: i token vanno bene come sono, e una
            # voce da zero token deve sparire, non diventare una scheggia.
            self._segmenti_lay.setStretch(
                list(self._segmenti).index(voce), n)
            self._segmenti[voce].setVisible(n > 0)
            if n:
                pezzi.append(f'<span style="color:{COLORI[voce]}">&#9632;</span> '
                             f'{voce} {n}')
        libero = max(0, utile - totale)
        self._segmenti_lay.setStretch(len(self._segmenti) - 1, libero)
        self._segmenti["libero"].setVisible(True)
        allarme = totale / utile >= SOGLIA_ALLARME
        self._segmenti["libero"].setStyleSheet(
            f"background: {ROSSO if allarme else GRIGIO}; border-radius: 2px;")
        self.legenda.setText("&nbsp;&nbsp;".join(pezzi) or "&nbsp;")


def titolo() -> QLabel:
    lab = QLabel("CONTESTO")
    lab.setStyleSheet(f"color: {tema.TESTO_TENUE}; font-size: 11px; letter-spacing: 1px;")
    lab.setFrameShape(QFrame.NoFrame)
    return lab
