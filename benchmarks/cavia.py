"""Una finestra bersaglio per le prove di automazione, in un processo suo.

DEVE essere un altro processo: `finestre.elenca()` scarta di proposito le
finestre di Metis, quindi una cavia creata nello stesso processo sarebbe
invisibile. Di per se' e' gia' una verifica riuscita, ma come bersaglio non
serve a niente.

E' in Qt e non in Tk, e la ragione e' stata misurata: Tk disegna i propri
widget invece di creare controlli nativi, quindi di una finestra Tk UI
Automation vede solo la cornice — riduci a icona, ingrandisci, chiudi — e
nessun pulsante. Andava bene per spostare la finestra e per niente per
cliccarci dentro, che e' meta' di M4.

    python benchmarks/cavia.py [titolo]
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

TITOLO = sys.argv[1] if len(sys.argv) > 1 else "CAVIA-METIS"


class Cavia(QWidget):
    """Riporta su stdout cosa riceve: cosi' le prove non verificano "il
    broker ha detto ok" ma "la cosa e' arrivata dall'altra parte"."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITOLO)
        self.resize(640, 420)
        self.move(120, 120)
        lay = QVBoxLayout(self)

        self.stato = QLabel("in attesa")
        lay.addWidget(self.stato)

        self.campo = QLineEdit()
        self.campo.setAccessibleName("Casella")
        self.campo.textChanged.connect(lambda t: print("TESTO " + t, flush=True))
        lay.addWidget(self.campo)

        b = QPushButton("Bersaglio")
        b.setAccessibleName("Bersaglio")
        b.clicked.connect(self._premuto)
        lay.addWidget(b)

        esca = QPushButton("Esca")
        esca.setAccessibleName("Esca")
        esca.clicked.connect(lambda: print("ESCA", flush=True))
        lay.addWidget(esca)

        lay.addStretch(1)
        self.campo.setFocus()

    def _premuto(self) -> None:
        self.stato.setText("PULSANTE PREMUTO")
        print("CLIC", flush=True)


def main() -> int:
    app = QApplication(sys.argv)
    c = Cavia()
    c.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
