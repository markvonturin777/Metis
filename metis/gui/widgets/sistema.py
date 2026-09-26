"""La colonna sinistra dell'Hub: sistema, meteo, fotocamera, sessione.

LA VRAM C'E', ANCHE SE NELLA REFERENCE NO
La reference mostra CPU, RAM e disco. Per Metis la risorsa che conta e' la
memoria grafica: oltre 7,5 GB su 8 Whisper viene spostato sul processore
(matrice degli errori di M7), e la barra rossa e' l'indicatore promesso da
quella riga. Toglierla per somiglianza estetica toglierebbe un avviso.

IL CARICO NON E' `getloadavg`
Su Windows `psutil.getloadavg` e' un'emulazione che parte da zero e impiega
minuti a stabilizzarsi. Il "carico" della sessione e' la media mobile della
CPU campionata dalla telemetria, che c'e' gia'.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from metis.gui import tema
from metis.gui.componenti import Barra, Pannello, Tessera

SOGLIA_VRAM_GB = 7.5          # la stessa di metis/gui/workers/telemetria.py


def _gb(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


class PannelloSistema(Pannello):
    def __init__(self, parent=None):
        super().__init__("Sistema", "cpu", parent)
        self.cpu = Barra("CPU")
        self.ram = Barra("RAM")
        self.vram = Barra("VRAM", soglia=SOGLIA_VRAM_GB / 8)
        for b in (self.cpu, self.ram, self.vram):
            self.corpo.addWidget(b)
        griglia = QGridLayout()
        griglia.setSpacing(tema.SPAZIO)
        self.t_gpu = Tessera("GPU")
        self.t_temp = Tessera("Temperatura")
        self.t_disco = Tessera("Disco")
        self.t_ram = Tessera("Memoria")
        for i, t in enumerate((self.t_gpu, self.t_temp, self.t_disco, self.t_ram)):
            griglia.addWidget(t, i // 2, i % 2)
        self.corpo.addLayout(griglia)

    @Slot(dict)
    def aggiorna(self, d: dict) -> None:
        cpu = float(d.get("cpu", 0))
        self.cpu.imposta(cpu / 100, f"{cpu:.0f}%")
        ram = float(d.get("ram_percento", 0))
        usata, totale = d.get("ram_gb", 0), d.get("ram_totale_gb", 0)
        self.ram.imposta(ram / 100, f"{_gb(usata)} / {totale:.0f} GB")
        self.t_ram.imposta(f"{ram:.0f}%")
        if "vram_gb" in d:
            tot = d.get("vram_totale_gb") or 8
            self.vram.soglia = SOGLIA_VRAM_GB / tot
            self.vram.imposta(d["vram_gb"] / tot, f"{_gb(d['vram_gb'])} / {tot:.0f} GB")
        if "gpu" in d:
            self.t_gpu.imposta(f"{d['gpu']}%")
        if "gpu_c" in d:
            c = d["gpu_c"]
            self.t_temp.imposta(f"{c} °C", tema.ERRORE if c >= 85 else None)
        if "disco_usato_gb" in d:
            self.t_disco.imposta(f"{d['disco_usato_gb']:.0f}/{d['disco_totale_gb']:.0f} GB")


class PannelloSessione(Pannello):
    """Da quanto e' acceso Metis e quanto ha lavorato. Il "System Uptime"
    della reference, con i contatori dell'orchestratore."""

    def __init__(self, parent=None):
        super().__init__("Sessione", "timer", parent)
        self._t0 = time.monotonic()
        riga = QHBoxLayout()
        etichetta = QLabel("Attivo da")
        etichetta.setStyleSheet(f"color: {tema.TESTO_TENUE};")
        self.durata = QLabel("00:00:00")
        self.durata.setFont(tema.font(tema.FONT_NUMERI, 20))
        self.durata.setStyleSheet(f"color: {tema.TESTO};")
        riga.addWidget(etichetta)
        riga.addStretch(1)
        riga.addWidget(self.durata)
        self.corpo.addLayout(riga)
        tessere = QHBoxLayout()
        tessere.setSpacing(tema.SPAZIO)
        self.t_turni = Tessera("Turni", "0")
        self.t_azioni = Tessera("Azioni", "0")
        self.t_negate = Tessera("Negate", "0")
        for t in (self.t_turni, self.t_azioni, self.t_negate):
            tessere.addWidget(t)
        self.corpo.addLayout(tessere)
        self.carico = Barra("Carico medio")
        self.corpo.addWidget(self.carico)
        self._carico = None

        # L'orologio gira solo con il pannello visibile: vedi il principio
        # delle animazioni ferme in tray, nel piano di PHASE1.
        self._orologio = QTimer(self)
        self._orologio.setInterval(1000)
        self._orologio.timeout.connect(self._aggiorna_durata)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._aggiorna_durata()
        self._orologio.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._orologio.stop()

    def _aggiorna_durata(self) -> None:
        s = int(time.monotonic() - self._t0)
        self.durata.setText(f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")

    @Slot(dict)
    def aggiorna_contatori(self, d: dict) -> None:
        self.t_turni.imposta(str(d.get("turni", 0)))
        self.t_azioni.imposta(str(d.get("strumenti_ok", 0)))
        negate = d.get("strumenti_negati", 0)
        self.t_negate.imposta(str(negate), tema.ATTENZIONE if negate else None)

    @Slot(dict)
    def aggiorna_risorse(self, d: dict) -> None:
        """Media mobile esponenziale della CPU: circa un minuto di memoria a
        due campioni al secondo."""
        cpu = float(d.get("cpu", 0))
        self._carico = cpu if self._carico is None else self._carico * 0.98 + cpu * 0.02
        livello = ("basso" if self._carico < 30 else "moderato" if self._carico < 70 else "alto")
        self.carico.imposta(self._carico / 100, f"{livello} · {self._carico:.0f}%")


class PannelloSegnaposto(Pannello):
    """Un pannello con un'icona grande e una frase: niente dati, niente
    worker. E' il modulo fotocamera di D-UI 1, e il meteo finche' non c'e'."""

    def __init__(self, titolo: str, icona: str, icona_corpo: str, frase: str, parent=None):
        super().__init__(titolo, icona, parent)
        colonna = QVBoxLayout()
        colonna.setSpacing(6)
        grande = QLabel()
        grande.setPixmap(tema.pixmap_icona(icona_corpo, tema.SEGNAPOSTO, 34,
                                           self.devicePixelRatioF()))
        grande.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frase = QLabel(frase)
        self.frase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frase.setWordWrap(True)
        self.frase.setStyleSheet(f"color: {tema.TESTO_SECONDARIO};")
        colonna.addWidget(grande)
        colonna.addWidget(self.frase)
        self.corpo.addLayout(colonna)
        self.corpo.setContentsMargins(12, 18, 12, 18)
