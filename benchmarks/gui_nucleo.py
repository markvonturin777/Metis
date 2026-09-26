"""PHASE1, giorno 7 — quanto costa il nucleo animato.

    python benchmarks/gui_nucleo.py                  # 1920x1080, 30 fps
    python benchmarks/gui_nucleo.py --fps 60
    python benchmarks/gui_nucleo.py --secondi 10     # per stato

Apre l'Hub vero, sulla piattaforma vera (non offscreen: e' il disegno di
Windows che si misura), e lo porta in ogni stato con livelli finti che si
muovono come una voce. Misura:

- il tempo di `paintEvent` del nucleo, p50/p95/max per stato — il criterio
  del piano e' p95 < 4 ms a 1080p, altrimenti `QOpenGLWidget`;
- i fotogrammi al secondo davvero disegnati;
- la CPU del processo, con l'Hub visibile a riposo e in PARLATO;
- il `MisuratoreLag`, lo stesso di NFR-8.

Il risultato va in `benchmarks/results/gui_nucleo_<data>.json`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import psutil  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from benchmarks.gui_screenshot import TELEMETRIA, conversazione_finta  # noqa: E402
from metis.gui import tema  # noqa: E402
from metis.gui.hub_view import HubView  # noqa: E402
from metis.gui.lag import MisuratoreLag  # noqa: E402

STATI = ("DORMIENTE", "IN_ASCOLTO", "ELABORAZIONE", "RICERCA_WEB", "ATTESA_CONFERMA",
         "PARLATO")
SOGLIA_P95_MS = 4.0


def aspetta(app: QApplication, secondi: float) -> None:
    """Un event loop vero, fermo fra un evento e l'altro: un ciclo con
    `processEvents` girerebbe a vuoto e la CPU misurata sarebbe la sua."""
    ciclo = QEventLoop()
    QTimer.singleShot(round(secondi * 1000), ciclo.quit)
    ciclo.exec()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--larghezza", type=int, default=1920)
    ap.add_argument("--altezza", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--secondi", type=float, default=8.0, help="per stato")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    tema.applica(app)
    hub = HubView(conversazione_finta())
    hub.resize(args.larghezza, args.altezza)
    hub.imposta_pronto()
    hub.sistema.aggiorna(TELEMETRIA)
    hub.show()
    n = hub.nucleo
    n._timer.setInterval(round(1000 / args.fps))

    # Livelli finti a 31 Hz, come dal thread del nucleo: una voce che sale e
    # scende tre volte al secondo, con pause fra le "parole".
    t0 = time.perf_counter()

    def livelli() -> None:
        t = time.perf_counter() - t0
        parola = math.sin(2 * math.pi * 1.5 * t)
        db = -14.0 - 10.0 * abs(math.sin(2 * math.pi * 3.1 * t)) if parola > -0.3 else -90.0
        n.campiona_microfono(db - 6.0)
        n.campiona_voce(db)

    sorgente = QTimer()
    sorgente.timeout.connect(livelli)
    sorgente.start(32)

    lag = MisuratoreLag()
    lag.avvia()
    lag.cambia_fase("esercizio")
    processo = psutil.Process()
    aspetta(app, 1.0)
    print(f"nucleo {n.width()}x{n.height()} px, finestra {hub.width()}x{hub.height()}, "
          f"{args.fps} fps, {args.secondi:.0f} s per stato\n")

    risultati: dict = {"data": datetime.now().isoformat(timespec="seconds"),
                       "finestra": [hub.width(), hub.height()],
                       "nucleo_px": n.width(), "fps_voluti": args.fps, "stati": {}}
    tutti: list[float] = []
    for stato in STATI:
        hub.imposta_stato(stato)
        aspetta(app, 0.5)
        n.tempi_ms.clear()
        disegni = n.disegni
        processo.cpu_percent(None)
        inizio = time.perf_counter()
        aspetta(app, args.secondi)
        durata = time.perf_counter() - inizio
        cpu = processo.cpu_percent(None)
        v = np.array(n.tempi_ms)
        tutti.extend(n.tempi_ms)
        r = {"p50_ms": round(float(np.percentile(v, 50)), 3),
             "p95_ms": round(float(np.percentile(v, 95)), 3),
             "max_ms": round(float(v.max()), 3),
             "fps": round((n.disegni - disegni) / durata, 1),
             "cpu_percento": round(cpu, 1)}
        risultati["stati"][stato] = r
        print(f"  {stato:<16} p50 {r['p50_ms']:5.2f} ms · p95 {r['p95_ms']:5.2f} ms · "
              f"max {r['max_ms']:6.2f} ms · {r['fps']:5.1f} fps · CPU {r['cpu_percento']:5.1f}%")

    # Con l'Hub nascosto: il riferimento per la residenza in tray.
    hub.hide()
    aspetta(app, 0.5)
    disegni = n.disegni
    processo.cpu_percent(None)
    aspetta(app, args.secondi)
    risultati["nascosto"] = {"disegni": n.disegni - disegni,
                             "cpu_percento": round(processo.cpu_percent(None), 1)}
    print(f"  {'(nascosto)':<16} {risultati['nascosto']['disegni']} disegni · "
          f"CPU {risultati['nascosto']['cpu_percento']:5.1f}%")

    lag.ferma()
    v = np.array(tutti)
    p95 = float(np.percentile(v, 95))
    risultati["complessivo"] = {"p95_ms": round(p95, 3), "campioni": len(v),
                                "superato": p95 < SOGLIA_P95_MS,
                                "lag": lag.stats("esercizio")}
    print(f"\ndisegno del nucleo p95 {p95:.2f} ms su {len(v)} fotogrammi: "
          f"{'SOTTO' if p95 < SOGLIA_P95_MS else 'SOPRA'} la soglia di {SOGLIA_P95_MS} ms")
    print(lag.riassunto())

    uscita = Path("benchmarks/results") / f"gui_nucleo_{datetime.now():%Y%m%d_%H%M}.json"
    uscita.parent.mkdir(parents=True, exist_ok=True)
    uscita.write_text(json.dumps(risultati, indent=2, ensure_ascii=False), encoding="utf-8")
    print(uscita)
    return 0


if __name__ == "__main__":
    sys.exit(main())
