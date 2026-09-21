"""Cruscotto: risorse della macchina e latenze degli NFR.

LE LATENZE SONO LA META' CHE CONTA
CPU e VRAM sono piacevoli da guardare; NFR-1 e NFR-2 sono quelli che
decidono se Metis e' usabile. Tenerli nello stesso riquadro significa che
quando la p95 sale lo si vede subito, invece di scoprirlo rileggendo i log
a fine giornata.

FINESTRA SCORREVOLE, NON MEDIA DA SEMPRE
Gli ultimi 50 turni. Una media cumulativa da inizio sessione diventa via via
insensibile: dopo due ore un peggioramento non muove piu' il numero, ed e'
esattamente quando servirebbe vederlo.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

FINESTRA_TURNI = 50
VERDE, AMBRA, ROSSO = "#22c55e", "#f59e0b", "#ef4444"


def _barra(massimo: int = 100) -> QProgressBar:
    b = QProgressBar()
    b.setRange(0, massimo)
    b.setTextVisible(True)
    b.setFixedHeight(16)
    return b


def _colora(barra: QProgressBar, colore: str) -> None:
    barra.setStyleSheet(
        "QProgressBar { background: #1e293b; border: none; border-radius: 3px;"
        " color: #cbd5e1; font-size: 11px; }"
        f"QProgressBar::chunk {{ background: {colore}; border-radius: 3px; }}")


class Telemetria(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.latenze: deque[float] = deque(maxlen=FINESTRA_TURNI)
        self._costruisci()

    def _costruisci(self) -> None:
        radice = QVBoxLayout(self)
        radice.setContentsMargins(8, 8, 8, 8)

        radice.addWidget(_titolo("RISORSE"))
        griglia = QGridLayout()
        self.barre: dict[str, QProgressBar] = {}
        for riga, (chiave, etichetta) in enumerate(
                [("cpu", "CPU"), ("ram", "RAM"), ("vram", "VRAM"), ("gpu", "GPU")]):
            griglia.addWidget(QLabel(etichetta), riga, 0)
            b = _barra()
            _colora(b, VERDE)
            self.barre[chiave] = b
            griglia.addWidget(b, riga, 1)
        radice.addLayout(griglia)

        self.temperatura = QLabel("—")
        self.temperatura.setStyleSheet("color: #94a3b8; font-size: 11px;")
        radice.addWidget(self.temperatura)

        radice.addSpacing(8)
        radice.addWidget(_titolo("LATENZA"))
        self.valori: dict[str, QLabel] = {}
        griglia2 = QGridLayout()
        for riga, (chiave, etichetta) in enumerate(
                [("ttft", "TTFT"), ("tok", "tok/s"),
                 ("p50", "e2e p50"), ("p95", "e2e p95")]):
            griglia2.addWidget(QLabel(etichetta), riga, 0)
            v = QLabel("—")
            v.setAlignment(Qt.AlignRight)
            v.setStyleSheet("font-family: Consolas, monospace;")
            self.valori[chiave] = v
            griglia2.addWidget(v, riga, 1)
        radice.addLayout(griglia2)
        radice.addStretch(1)

    # -- ingressi ----------------------------------------------------------

    @Slot(dict)
    def aggiorna_risorse(self, d: dict) -> None:
        cpu = d.get("cpu", 0)
        self.barre["cpu"].setValue(int(cpu))
        self.barre["cpu"].setFormat(f"{cpu:.0f}%")
        _colora(self.barre["cpu"], VERDE if cpu < 80 else AMBRA)

        ram = d.get("ram_percento", 0)
        self.barre["ram"].setValue(int(ram))
        self.barre["ram"].setFormat(
            f"{d.get('ram_gb', 0):.0f} / {d.get('ram_totale_gb', 0):.0f} GB")
        _colora(self.barre["ram"], VERDE if ram < 85 else AMBRA)

        if "vram_gb" in d:
            tot = d.get("vram_totale_gb", 8) or 8
            usata = d["vram_gb"]
            self.barre["vram"].setValue(int(usata / tot * 100))
            self.barre["vram"].setFormat(f"{usata:.2f} / {tot:.0f} GB")
            # Oltre 7,5 GB su 8 si rischia lo sfratto del modello: e' il
            # numero di §3.2, e va visto prima che accada, non dopo.
            _colora(self.barre["vram"], ROSSO if d.get("vram_allarme") else VERDE)
        if "gpu" in d:
            self.barre["gpu"].setValue(int(d["gpu"]))
            self.barre["gpu"].setFormat(f"{d['gpu']}%")
            _colora(self.barre["gpu"], VERDE)
        if "gpu_c" in d:
            self.temperatura.setText(f"GPU {d['gpu_c']} °C")

    @Slot(dict)
    def aggiorna_turno(self, m: dict) -> None:
        if m.get("totale_ms"):
            self.latenze.append(float(m["totale_ms"]))
        self.valori["ttft"].setText(f"{m.get('ttft_ms', 0):.0f} ms")
        self.valori["tok"].setText(f"{m.get('tok_per_s', 0):.0f}")
        if self.latenze:
            import numpy as np

            v = np.array(self.latenze)
            p50 = float(np.percentile(v, 50))
            p95 = float(np.percentile(v, 95))
            self.valori["p50"].setText(f"{p50 / 1000:.2f} s")
            self.valori["p95"].setText(f"{p95 / 1000:.2f} s")
            # I target di NFR-1, sotto gli occhi mentre si usa.
            self.valori["p50"].setStyleSheet(
                _stile_valore(VERDE if p50 < 1200 else AMBRA))
            self.valori["p95"].setStyleSheet(
                _stile_valore(VERDE if p95 < 1800 else AMBRA))


def _stile_valore(colore: str) -> str:
    return f"font-family: Consolas, monospace; color: {colore};"


def _titolo(testo: str) -> QLabel:
    lab = QLabel(testo)
    lab.setStyleSheet("color: #64748b; font-size: 11px; letter-spacing: 1px;")
    lab.setFrameShape(QFrame.NoFrame)
    return lab
