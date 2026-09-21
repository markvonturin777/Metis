"""Misura i blocchi dell'event loop. E' la verifica di NFR-8.

IL METODO
Un `QTimer` a 16 ms — il ritmo di 60 fotogrammi al secondo — che a ogni
scatto confronta l'istante in cui e' arrivato con quello in cui era atteso.
La differenza e' il tempo in cui l'event loop **non stava girando**, cioe'
esattamente quello che l'utente percepisce come scatto.

E' semplice al punto da sembrare insufficiente, e invece e' la misura
giusta: non stima la fluidita', misura l'unica cosa che la rovina. Un
profiler direbbe dove si e' speso il tempo; questo dice se l'interfaccia ha
smesso di rispondere, che e' la domanda di NFR-8.

PERCHE' RESTA ACCESO ANCHE DOPO M3
Perche' diventa un test di regressione. Se in M4 qualcuno mette una
chiamata bloccante sul thread della GUI — e in M4, con l'automazione, la
tentazione ci sara' — il numero peggiora subito e si sa dove guardare.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

INTERVALLO_MS = 16          # 60 fps
SOGLIA_FREEZE_MS = 100.0    # NFR-8


class MisuratoreLag(QObject):
    """Vive sul thread principale: e' quello che deve restare reattivo."""

    freeze = Signal(float)          # un blocco oltre soglia, in ms

    def __init__(self, intervallo_ms: int = INTERVALLO_MS,
                 soglia_ms: float = SOGLIA_FREEZE_MS, parent=None):
        super().__init__(parent)
        self.intervallo_ms = intervallo_ms
        self.soglia_ms = soglia_ms
        self.ritardi: list[float] = []
        self.freeze_count = 0
        self.peggiore = 0.0
        self._atteso = 0.0
        # NFR-8 parla di blocchi "durante l'inferenza". L'avvio carica tre
        # modelli e blocca una volta sola, e mescolare le due fasi
        # renderebbe il numero inutile in entrambe le direzioni: o si
        # fallisce per un blocco che nessuno vive come difetto, o lo si
        # nasconde nella media di mezz'ora. Si misurano separate.
        self.fase = "avvio"
        self.per_fase: dict[str, list[float]] = {}
        self.blocchi: list[tuple[str, float, float]] = []   # fase, t, ms
        self._t0 = 0.0
        self._timer = QTimer(self)
        # Timer preciso: quello predefinito ha una tolleranza del 5%,
        # che a 16 ms sono 0,8 ms di rumore su una misura che cerca
        # scostamenti veri.
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._scatto)

    def avvia(self) -> None:
        self.ritardi.clear()
        self.per_fase.clear()
        self.blocchi.clear()
        self.freeze_count = 0
        self.peggiore = 0.0
        self._t0 = time.perf_counter()
        self._atteso = self._t0 + self.intervallo_ms / 1000.0
        self._timer.start(self.intervallo_ms)

    def cambia_fase(self, nome: str) -> None:
        """L'applicazione dichiara quando finisce l'avvio e comincia l'uso."""
        self.fase = nome

    def ferma(self) -> None:
        self._timer.stop()

    def _scatto(self) -> None:
        ora = time.perf_counter()
        ritardo_ms = (ora - self._atteso) * 1000.0
        self._atteso = ora + self.intervallo_ms / 1000.0
        if ritardo_ms < 0:
            ritardo_ms = 0.0
        self.ritardi.append(ritardo_ms)
        self.per_fase.setdefault(self.fase, []).append(ritardo_ms)
        if ritardo_ms > self.peggiore:
            self.peggiore = ritardo_ms
        if ritardo_ms > self.soglia_ms:
            self.freeze_count += 1
            self.blocchi.append((self.fase, ora - self._t0, ritardo_ms))
            self.freeze.emit(ritardo_ms)

    # -- lettura -----------------------------------------------------------

    def stats(self, fase: str | None = None) -> dict:
        campioni = self.ritardi if fase is None else self.per_fase.get(fase, [])
        if not campioni:
            return {"campioni": 0}
        import numpy as np

        v = np.array(campioni)
        # Il fotogramma dura intervallo + ritardo: e' il fps che si vede,
        # non quello che il timer avrebbe voluto.
        fps = 1000.0 / (self.intervallo_ms + float(np.percentile(v, 50)))
        blocchi = [b for b in self.blocchi if fase is None or b[0] == fase]
        return {
            "campioni": len(v),
            "ritardo_p50_ms": round(float(np.percentile(v, 50)), 2),
            "ritardo_p95_ms": round(float(np.percentile(v, 95)), 2),
            "ritardo_max_ms": round(float(v.max()), 1),
            "freeze_oltre_soglia": len(blocchi),
            "fps_stimati": round(fps, 1),
        }

    def riassunto(self) -> str:
        """NFR-8 si giudica sulla fase d'uso. L'avvio si riporta, non si nasconde."""
        righe = []
        for fase in self.per_fase:
            s = self.stats(fase)
            righe.append(
                f"  {fase:<10} {s['campioni']:>6} campioni · "
                f"p50 {s['ritardo_p50_ms']:>6.2f} ms · p95 {s['ritardo_p95_ms']:>6.2f} ms · "
                f"max {s['ritardo_max_ms']:>7.1f} ms · "
                f"{s['freeze_oltre_soglia']} oltre {self.soglia_ms:.0f} ms · "
                f"~{s['fps_stimati']:.0f} fps")

        uso = self.stats("esercizio")
        if not uso.get("campioni"):
            testa = "NFR-8 non misurabile: nessun campione in esercizio"
        else:
            esito = "SUPERATO" if uso["freeze_oltre_soglia"] == 0 else "FALLITO"
            testa = (f"NFR-8 {esito} — in esercizio {uso['freeze_oltre_soglia']} "
                     f"blocchi oltre {self.soglia_ms:.0f} ms, ~{uso['fps_stimati']:.0f} fps")

        dettaglio = ""
        if self.blocchi:
            dettaglio = "\n  blocchi: " + ", ".join(
                f"{f} a {t:.1f}s ({ms:.0f} ms)" for f, t, ms in self.blocchi)
        return testa + "\n" + "\n".join(righe) + dettaglio
