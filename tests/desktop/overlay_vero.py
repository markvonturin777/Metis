"""L'overlay dei numeri su Windows vero, non su `offscreen`.

    python -m tests.desktop.overlay_vero

La suite gira con QT_QPA_PLATFORM=offscreen (vedi `conftest.py`): li' una
finestra non esiste per Windows, e "quale finestra e' in primo piano" non ha
risposta. Questo script parte in un processo suo, con la piattaforma vera,
mostra l'overlay per qualche centinaio di millisecondi su ogni monitor e
stampa su una riga JSON cosa ne pensa Windows. `test_numeri_overlay.py` lo
lancia e legge quella riga.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "windows"


def main() -> int:
    import win32gui
    from PySide6.QtWidgets import QApplication

    from metis.gui.numeri import OverlayNumeri, rect_logico, schermo_per
    from metis.tools.display import monitors

    app = QApplication.instance() or QApplication([])

    def gira(s: float) -> None:
        fine = time.perf_counter() + s
        while time.perf_counter() < fine:
            app.processEvents()
            time.sleep(0.01)

    esiti = []
    for m in monitors():
        o = OverlayNumeri(scadenza_s=60)
        c = (m.rect[0] + 100, m.rect[1] + 120, m.rect[0] + 500, m.rect[1] + 420)
        prima = win32gui.GetForegroundWindow()
        o.mostra(c, [(7, (c[0] + 10, c[1] + 20, c[0] + 110, c[1] + 40))])
        gira(0.3)
        mio = int(o.winId())
        trovato = schermo_per(c)
        g = o.geometry()
        atteso = rect_logico(c, trovato[0]) if trovato else None
        esiti.append({
            "monitor": m.nome, "primario": m.primario, "scala": m.dpi / 96,
            "visibile": o.isVisible(),
            "primo_piano_prima": prima, "primo_piano_dopo": win32gui.GetForegroundWindow(),
            "overlay": mio,
            "sotto_il_punto": win32gui.WindowFromPoint((c[0] + 20, c[1] + 30)),
            "stile": ctypes.windll.user32.GetWindowLongW(mio, -20),
            "geometria": [g.x(), g.y(), g.width(), g.height()],
            "attesa": [round(v) for v in atteso] if atteso else None,
            "schermo_qt_x": o.screen().geometry().x(),
            "rect_finestra": list(win32gui.GetWindowRect(mio)),
            "cornice": list(c),
        })
        o.nascondi()
        o.deleteLater()
        gira(0.05)

        # PHASE2, giorni 11-12: la bolla da sola, senza numeri (i clic per nome).
        b = OverlayNumeri(scadenza_s=60)
        prima = win32gui.GetForegroundWindow()
        b.evidenzia(c, (c[0] + 40, c[1] + 40, c[0] + 140, c[1] + 70), "attesa")
        gira(0.3)
        esiti[-1].update({
            "bolla_visibile": b.isVisible(),
            "bolla_primo_piano_prima": prima,
            "bolla_primo_piano_dopo": win32gui.GetForegroundWindow(),
            "bolla_overlay": int(b.winId()),
            "sotto_la_bolla": win32gui.WindowFromPoint((c[0] + 90, c[1] + 55)),
        })
        b.spegni_evidenza()
        gira(0.4)
        esiti[-1]["bolla_sparita"] = not b.isVisible()
        b.deleteLater()
        gira(0.05)
    print(json.dumps(esiti))
    return 0


if __name__ == "__main__":
    sys.exit(main())
