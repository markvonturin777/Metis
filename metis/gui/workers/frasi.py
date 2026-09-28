"""La lettura delle frasi non capite, su un thread suo (PHASE4).

`turns.jsonl` cresce senza limite: anche se se ne leggono solo gli ultimi 30
giorni, lo si fa qui e non sul thread della GUI (NFR-8), come il meteo di
PHASE1. Nessun timer: si rilegge quando qualcuno lo chiede — all'avvio, a fine
turno, dopo una decisione nel pannello — perche' fra un turno e l'altro il
file non cambia.

Come ogni worker, non importa `QtWidgets`: lo verifica `tests/test_gui_thread.py`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from metis.memory import frasi


class LettoreFrasi(QObject):
    """Rilegge il log su richiesta e spedisce la `Raccolta` alla GUI."""

    pronta = Signal(object)          # frasi.Raccolta

    def __init__(self, config: Path = frasi.CONFIG, log: Path | None = None,
                 decise: Path | None = None, leggi=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.log = log
        self.decise = decise
        self._leggi = leggi or frasi.raccogli

    @Slot()
    def rileggi(self) -> None:
        """Mai un'eccezione verso la GUI: un log illeggibile e' un pannello vuoto."""
        try:
            r = self._leggi(log=self.log, decise=self.decise, config=self.config)
        except Exception:                          # noqa: BLE001
            r = frasi.Raccolta()
        self.pronta.emit(r)
