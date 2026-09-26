"""Catalogo dei componenti dell'Hub, con dati finti.

    python benchmarks/gui_catalogo.py                  # apre la finestra
    python benchmarks/gui_catalogo.py --cattura c.png  # salva un'immagine ed esce

Serve a guardare i mattoni prima di costruirci sopra: un pannello brutto qui
e' brutto in ogni vista. L'immagine serve alla revisione visiva, che per
un'interfaccia non si delega a un test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from metis.core.palette import STATI, esadecimale, significato  # noqa: E402
from metis.gui import tema  # noqa: E402
from metis.gui.componenti import Barra, Pannello, Pillola, PulsanteIcona, Tessera  # noqa: E402


def costruisci() -> QWidget:
    finestra = QWidget()
    finestra.setWindowTitle("Metis — catalogo dei componenti")
    finestra.resize(1180, 760)
    radice = QHBoxLayout(finestra)
    radice.setContentsMargins(20, 20, 20, 20)
    radice.setSpacing(20)

    # colonna 1: pannelli come nella reference
    col = QVBoxLayout()
    sistema = Pannello("Sistema", "cpu")
    sistema.aggiungi_azione(PulsanteIcona("activity", "Diagnostica", lato=26))
    for nome, fr, testo, soglia in (("CPU", 0.08, "8%", None), ("RAM", 0.44, "7,0 GB", None),
                                    ("VRAM", 0.95, "7,6 GB", 7.5 / 8)):
        b = Barra(nome, soglia=soglia)
        b.imposta(fr, testo)
        sistema.corpo.addWidget(b)
    griglia = QGridLayout()
    for i, (e, v) in enumerate((("CPU", "8%"), ("Memoria", "44%"), ("Disco", "439/475 GB"),
                                ("GPU", "54 °C"))):
        griglia.addWidget(Tessera(e, v), i // 2, i % 2)
    sistema.corpo.addLayout(griglia)
    col.addWidget(sistema)

    meteo = Pannello("Meteo", "cloud")
    t = QLabel("18,4 °C")
    t.setFont(tema.font(tema.FONT_NUMERI, 26))
    meteo.corpo.addWidget(t)
    luogo = QLabel("Milano · coperto")
    luogo.setStyleSheet(f"color: {tema.TESTO_TENUE};")
    meteo.corpo.addWidget(luogo)
    riga = QHBoxLayout()
    for e, v in (("Umidità", "94%"), ("Vento", "5,8 m/s"), ("Percepita", "17,9 °C")):
        riga.addWidget(Tessera(e, v))
    meteo.corpo.addLayout(riga)
    col.addWidget(meteo)
    col.addStretch(1)
    radice.addLayout(col, 1)

    # colonna 2: pillole di stato, pulsanti, campo di testo
    col2 = QVBoxLayout()
    titolo = QLabel("M.E.T.I.S")
    titolo.setFont(tema.font(tema.FONT_TITOLI, 26, tema.QFont.Weight.Bold))
    titolo.setStyleSheet(f"color: {tema.TESTO};")
    col2.addWidget(titolo)
    for stato in STATI:
        col2.addWidget(Pillola(f"{significato(stato)}  ·  {stato}", esadecimale(stato)))
    pulsanti = QHBoxLayout()
    for nome, sugg in (("camera", "Fotocamera"), ("mic", "Parla"), ("keyboard", "Scrivi"),
                       ("volume-2", "Voce")):
        pulsanti.addWidget(PulsanteIcona(nome, sugg))
    spento = PulsanteIcona("camera-off", "Fotocamera non collegata")
    spento.setEnabled(False)
    pulsanti.addWidget(spento)
    pulsanti.addStretch(1)
    col2.addLayout(pulsanti)
    campo = QLineEdit()
    campo.setPlaceholderText("Scrivi un messaggio…")
    col2.addWidget(campo)
    col2.addStretch(1)
    radice.addLayout(col2, 1)

    # colonna 3: tutte le icone
    icone = Pannello("Icone", "layout-dashboard")
    g = QGridLayout()
    for i, nome in enumerate(tema.icone_disponibili()):
        lab = QLabel()
        lab.setPixmap(tema.pixmap_icona(nome, tema.ACCENTO, 22, finestra.devicePixelRatioF()))
        lab.setToolTip(nome)
        g.addWidget(lab, i // 6, i % 6)
    icone.corpo.addLayout(g)
    icone.corpo.addStretch(1)
    radice.addWidget(icone, 1)
    return finestra


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cattura", type=Path)
    args = ap.parse_args()
    app = QApplication(sys.argv)
    font = tema.applica(app)
    w = costruisci()
    w.show()
    print("font:", font)
    if args.cattura:
        def scatta():
            w.grab().save(str(args.cattura))
            app.quit()
        QTimer.singleShot(400, scatta)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
