"""Telemetria su un thread suo: CPU e RAM a 2 Hz, GPU a 1 Hz.

LE DUE FREQUENZE SONO DIVERSE PER UN MOTIVO
`psutil` costa poco. La query NVML no: interroga il driver, e a frequenza
alta ruba tempo alla GPU proprio mentre sta generando. Sarebbe l'ironia
peggiore possibile — un cruscotto che peggiora il numero che sta mostrando.
Un aggiornamento al secondo e' piu' che sufficiente per un valore che si
muove lentamente.

PERCHE' NON UN QTimer SUL THREAD PRINCIPALE
Perche' `nvmlDeviceGetMemoryInfo` puo' bloccare per decine di millisecondi
quando il driver e' occupato, e sul thread della GUI quei millisecondi sono
fotogrammi persi. NFR-8 chiede nessun blocco sopra i 100 ms: la telemetria
non deve essere una delle cause.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal, Slot

SOGLIA_VRAM_GB = 7.5          # §3.2 della specifica: oltre, indicatore rosso


class Telemetria(QObject):
    dati = Signal(dict)
    errore = Signal(str)

    def __init__(self, hz_cpu: float = 2.0, hz_gpu: float = 1.0, parent=None):
        super().__init__(parent)
        self.periodo_cpu = 1.0 / hz_cpu
        self.periodo_gpu = 1.0 / hz_gpu
        self._ferma = False
        self._gpu = None
        self._ultima_gpu: dict = {}

    @Slot()
    def avvia(self) -> None:
        import psutil

        try:
            import pynvml

            pynvml.nvmlInit()
            self._gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:                     # noqa: BLE001
            # Nessuna GPU o driver assente: il resto del cruscotto funziona.
            # M7: niente nome d'eccezione verso l'utente, vedi `core/errors.py`.
            self.errore.emit("La memoria grafica non e' leggibile: il cruscotto "
                             "mostra solo processore e RAM.")
            self._gpu = None

        ultimo_gpu = 0.0
        psutil.cpu_percent(interval=None)     # prima lettura, si scarta
        while not self._ferma:
            ora = time.perf_counter()
            mem = psutil.virtual_memory()
            campione = {
                "cpu": psutil.cpu_percent(interval=None),
                "ram_percento": mem.percent,
                "ram_gb": round((mem.total - mem.available) / 1024**3, 1),
                "ram_totale_gb": round(mem.total / 1024**3, 1),
            }
            if self._gpu is not None and ora - ultimo_gpu >= self.periodo_gpu:
                ultimo_gpu = ora
                self._ultima_gpu = self._leggi_gpu()
            campione.update(self._ultima_gpu)
            self.dati.emit(campione)
            time.sleep(self.periodo_cpu)

    def _leggi_gpu(self) -> dict:
        try:
            import pynvml

            mem = pynvml.nvmlDeviceGetMemoryInfo(self._gpu)
            usata = mem.used / 1024**3
            fuori = {
                "vram_gb": round(usata, 2),
                "vram_totale_gb": round(mem.total / 1024**3, 1),
                "vram_allarme": usata > SOGLIA_VRAM_GB,
                "gpu": pynvml.nvmlDeviceGetUtilizationRates(self._gpu).gpu,
            }
            try:
                import pynvml as n

                fuori["gpu_c"] = n.nvmlDeviceGetTemperature(self._gpu, 0)
            except Exception:                 # noqa: BLE001
                pass
            return fuori
        except Exception:                     # noqa: BLE001
            # Una lettura fallita non spegne la telemetria: si tiene l'ultima
            # buona e si riprova al giro dopo.
            return self._ultima_gpu

    def ferma(self) -> None:
        self._ferma = True
