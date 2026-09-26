"""L'overlay dei numeri (PHASE2): un'etichetta numerata su ogni elemento.

LA FINESTRA NON DEVE MAI PRENDERE IL FUOCO
La guardia del clic legge quale finestra e' in primo piano. Se lo fosse
l'overlay, ogni clic verrebbe rifiutato — o peggio, la guardia valuterebbe la
finestra sbagliata. Quindi quattro cose insieme, perche' ognuna da sola ha un
modo di cedere:

    Qt.WindowTransparentForInput     i clic passano sotto
    Qt.WindowDoesNotAcceptFocus      Qt non la attiva
    WA_ShowWithoutActivating         show() diventa SW_SHOWNOACTIVATE
    WS_EX_NOACTIVATE | TRANSPARENT   Windows stesso non la attiva, e non la colpisce

`test_numeri_overlay.py` lo verifica con la finestra in primo piano letta da
Windows, non con le proprieta' di Qt.

PIXEL FISICI E PIXEL DI QT
I rettangoli arrivano da UIA in pixel fisici del desktop; Qt disegna in pixel
logici. Qt 6 tiene l'angolo di ogni schermo in pixel nativi e scala solo
dentro lo schermo, quindi per un punto dello schermo S:

    logico = angolo(S) + (fisico - angolo(S)) / dpr(S)

L'overlay copre la parte visibile della finestra numerata, non lo schermo
intero: una finestra in primo piano grande quanto il monitor e' cio' che
Windows scambia per un'applicazione a tutto schermo.

LE ETICHETTE NON SI SOVRAPPONGONO
`posiziona` prova per ogni elemento qualche posto — l'angolo in alto a
sinistra dentro, sopra, a sinistra, in alto a destra, sotto — e prende il
primo libero dentro l'overlay. Una funzione pura: i test la verificano senza
finestre.

Le etichette si disegnano una volta, alla comparsa: NFR-8 non ha niente da
temere da 99 rettangoli fermi.

LA BOLLA (giorni 11-12)
La stessa finestra disegna la bolla di `evidenza.py`: dove Metis sta per
cliccare, e cosa aspetta di sentirsi confermare. L'unica cosa che si muove
nell'overlay, e si muove poco: un timer a ~60 fps che gira solo finche' la
bolla vive (meno di un secondo, o la durata di una conferma), e che ridisegna
solo il riquadro della bolla, non la finestra intera. Con "riduci animazioni"
il timer non parte: la bolla compare ferma e sparisce.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from metis.gui import evidenza, tema

ALTEZZA = 18               # px logici di un'etichetta
PADDING_X = 5
FONT_PX = 12

Rect = tuple[float, float, float, float]      # left, top, right, bottom


# --- geometria, pura ------------------------------------------------------------

@dataclass(frozen=True)
class Schermo:
    """Dove sta uno schermo, per Windows e per Qt."""

    angolo: tuple[int, int]        # in alto a sinistra, pixel fisici (= nativi in Qt 6)
    dpr: float


def a_logico(p: tuple[float, float], s: Schermo) -> tuple[float, float]:
    ox, oy = s.angolo
    return (ox + (p[0] - ox) / s.dpr, oy + (p[1] - oy) / s.dpr)


def rect_logico(r, s: Schermo) -> Rect:
    l, t = a_logico((r[0], r[1]), s)
    rr, b = a_logico((r[2], r[3]), s)
    return (l, t, rr, b)


def _si_toccano(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _dentro(r: Rect, limiti: Rect) -> Rect:
    w, h = r[2] - r[0], r[3] - r[1]
    x = min(max(r[0], limiti[0]), limiti[2] - w)
    y = min(max(r[1], limiti[1]), limiti[3] - h)
    return (x, y, x + w, y + h)


def posiziona(elementi: list[Rect], larghezze: list[float], altezza: float,
              limiti: Rect) -> list[Rect]:
    """Un rettangolo di etichetta per elemento, dentro i limiti, senza
    sovrapposizioni quando c'e' posto. Stesso ordine degli elementi."""
    fuori: list[Rect] = []
    for (l, t, r, b), w in zip(elementi, larghezze):
        h = altezza
        posti = [(l, t), (l, t - h), (l - w, t), (r - w, t), (l, b - h), (l, b)]
        scelto = None
        for x, y in posti:
            c = _dentro((x, y, x + w, y + h), limiti)
            if not any(_si_toccano(c, g) for g in fuori):
                scelto = c
                break
        if scelto is None:
            # Nessun posto libero vicino: sotto il primo, un gradino alla volta.
            base = _dentro((l, t, l + w, t + h), limiti)
            scelto = base
            for k in range(1, 6):
                c = _dentro((base[0], base[1] + k * h, base[2], base[3] + k * h), limiti)
                if not any(_si_toccano(c, g) for g in fuori):
                    scelto = c
                    break
        fuori.append(scelto)
    return fuori


# --- la finestra ----------------------------------------------------------------

_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000


def _stili_windows(hwnd: int) -> None:
    import ctypes

    u = ctypes.windll.user32
    stile = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    u.SetWindowLongW(hwnd, _GWL_EXSTYLE, stile | _WS_EX_NOACTIVATE | _WS_EX_TRANSPARENT
                     | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST)


def schermo_per(cornice) -> tuple[Schermo, object] | None:
    """Lo schermo di Qt su cui sta la cornice (pixel fisici), e il suo `Schermo`."""
    from metis.tools.display import monitor_di_rect

    m = monitor_di_rect(tuple(int(x) for x in cornice))
    if m is None:
        return None
    for qs in QGuiApplication.screens():
        g = qs.geometry()
        if (g.x(), g.y()) == (m.rect[0], m.rect[1]):
            return Schermo((m.rect[0], m.rect[1]), qs.devicePixelRatio()), qs
    return None


@dataclass
class _Bolla:
    stile: evidenza.Stile
    rect: tuple[float, float, float, float]     # locale, in pixel logici
    t0: float                                   # ms, orologio monotono
    t_clic: float | None = None                 # ms dalla comparsa
    t_spegni: float | None = None


def _adesso_ms() -> float:
    return time.monotonic() * 1000.0


class OverlayNumeri(QWidget):
    """Trasparente, sopra a tutto, mai attiva. Vedi la nota in testa."""

    nascosto = Signal()

    def __init__(self, scadenza_s: float = 60.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metis — numeri")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self._font = tema.font(tema.FONT_NUMERI, FONT_PX, QFont.Weight.Bold)
        self._voci: list[tuple[str, Rect, Rect]] = []     # testo, elemento, etichetta
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(scadenza_s * 1000))
        self._timer.timeout.connect(self.nascondi)
        self._cornice: tuple | None = None
        self._bolla: _Bolla | None = None
        self._animato = True
        self._orologio = QTimer(self)
        self._orologio.setTimerType(Qt.PreciseTimer)
        self._orologio.setInterval(16)
        self._orologio.timeout.connect(self._tic)
        self._riquadro_prima: QRect | None = None
        self.disegni = 0                                   # per i test di NFR-8
        self.tempi_disegno: list[float] = []               # ms per disegno, gli ultimi 2000

    # -- impostazioni ----------------------------------------------------------

    def imposta_animazioni(self, attive: bool) -> None:
        """"Riduci animazioni" (Impostazioni dell'Hub): la bolla ferma, nessun timer."""
        self._animato = bool(attive)
        if not self._animato:
            self._orologio.stop()
            if self._bolla is not None:
                self.update()

    @property
    def animazione_attiva(self) -> bool:
        return self._orologio.isActive()

    @property
    def bolla(self) -> _Bolla | None:
        return self._bolla

    # -- geometria -------------------------------------------------------------

    def _posiziona(self, cornice) -> bool:
        trovato = schermo_per(cornice)
        if trovato is None:
            return False
        s, _ = trovato
        cl, ct, cr, cb = rect_logico(cornice, s)
        self.setGeometry(round(cl), round(ct), max(1, round(cr - cl)), max(1, round(cb - ct)))
        self._cornice = tuple(cornice)
        self._schermo = s
        self._origine = (cl, ct)
        return True

    def _locale(self, r) -> Rect:
        cl, ct = self._origine
        l, t, rr, b = rect_logico(r, self._schermo)
        return (l - cl, t - ct, rr - cl, b - ct)

    def _compari(self) -> None:
        self.winId()                     # crea la finestra nativa prima di show()
        _stili_windows(int(self.winId()))
        if not self.isVisible():
            self.show()
        self.raise_()

    def _chiudi_se_vuota(self) -> None:
        if not self._voci and self._bolla is None and self.isVisible():
            self.hide()

    # -- i numeri, sul thread della GUI -----------------------------------------

    @Slot(object, object)
    def mostra(self, cornice, numerati) -> None:
        """`cornice` e i rettangoli di `numerati` [(n, rect)] in pixel fisici."""
        if not numerati or not self._posiziona(cornice):
            self.nascondi()
            return
        if self._bolla is not None and tuple(cornice) != self._cornice:
            self._bolla = None
        cr, cb = self.width(), self.height()
        fm = QFontMetrics(self._font)
        testi = [str(n) for n, _ in numerati]
        locali = [self._locale(r) for _, r in numerati]
        larghezze = [fm.horizontalAdvance(t) + 2 * PADDING_X for t in testi]
        etichette = posiziona(locali, larghezze, ALTEZZA, (0, 0, cr, cb))
        self._voci = list(zip(testi, locali, etichette))

        self._compari()
        self.update()
        self._timer.start()

    @Slot()
    def nascondi(self) -> None:
        """Toglie i numeri. Se una bolla sta ancora sfumando, la finestra resta
        finche' la bolla non ha finito: il clic e' partito, l'onda si vede."""
        self._timer.stop()
        cerano = bool(self._voci) or self.isVisible()
        self._voci = []
        if self._bolla is None:
            if self.isVisible():
                self.hide()
            if cerano:
                self.nascosto.emit()
        else:
            self.update()
            self.nascosto.emit()

    # -- la bolla, sul thread della GUI -----------------------------------------

    @Slot(object, object, str)
    def evidenzia(self, cornice, rect, stile: str) -> None:
        """La bolla su `rect` (pixel fisici), dentro la finestra `cornice`.

        Se la bolla c'e' gia', con lo stesso stile e non ancora cliccata, si
        sposta e basta: e' il caso del rettangolo riletto un attimo prima del
        clic, a pochi pixel da quello numerato. Non ricomincia l'entrata.
        """
        cornice = tuple(cornice)
        if not self.isVisible() or cornice != self._cornice:
            if self._voci and cornice != self._cornice:
                self._voci = []
                self._timer.stop()
            if not self._posiziona(cornice):
                return
        stile = evidenza.Stile(stile)
        locale = self._locale(rect)
        b = self._bolla
        if b is not None and b.stile is stile and b.t_clic is None and b.t_spegni is None:
            b.rect = locale
        else:
            self._bolla = _Bolla(stile, locale, _adesso_ms())
            if not self._animato and stile is evidenza.Stile.RIFIUTO:
                QTimer.singleShot(int(evidenza.FERMA_RIFIUTO_MS) + 5, self._tic)
        self._compari()
        self._avvia()

    @Slot()
    def clic(self) -> None:
        b = self._bolla
        if b is not None and b.t_clic is None:
            b.t_clic = _adesso_ms() - b.t0
            if not self._animato:
                QTimer.singleShot(int(evidenza.FERMA_DOPO_CLIC_MS) + 5, self._tic)
            self._avvia()

    @Slot()
    def spegni_evidenza(self) -> None:
        b = self._bolla
        if b is not None and b.t_spegni is None:
            b.t_spegni = _adesso_ms() - b.t0
            self._avvia()

    def _avvia(self) -> None:
        if self._animato and not self._orologio.isActive():
            self._orologio.start()
        self._tic()

    def _fotogramma(self) -> evidenza.Fotogramma:
        b = self._bolla
        return evidenza.fotogramma(b.stile, _adesso_ms() - b.t0, evidenza.raggio_per(b.rect),
                                   b.t_clic, b.t_spegni, self._animato)

    @staticmethod
    def _riquadro(b: _Bolla, f: evidenza.Fotogramma) -> QRect:
        cx, cy = evidenza.centro(b.rect)
        m = f.ingombro + 4
        l, t, r, bb = b.rect
        return QRectF(min(cx - m, l - 3), min(cy - m, t - 3),
                      max(cx + m, r + 3) - min(cx - m, l - 3),
                      max(cy + m, bb + 3) - min(cy - m, t - 3)).toAlignedRect()

    @Slot()
    def _tic(self) -> None:
        b = self._bolla
        if b is None:
            self._orologio.stop()
            return
        f = self._fotogramma()
        riquadro = self._riquadro(b, f)
        sporco = riquadro if self._riquadro_prima is None else riquadro.united(self._riquadro_prima)
        if f.finito:
            self._bolla = None
            self._orologio.stop()
            self._riquadro_prima = None
            self.update(sporco)
            self._chiudi_se_vuota()
            return
        self._riquadro_prima = riquadro
        self.update(sporco)

    # -- disegno ---------------------------------------------------------------

    def paintEvent(self, _evento) -> None:
        t0 = time.perf_counter()
        self.disegni += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font)
        contorno = QPen(tema.con_alfa(tema.ACCENTO, 0.45), 1)
        for _, (l, t, r, b), _e in self._voci:
            p.setPen(contorno)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(l + 0.5, t + 0.5, r - l - 1, b - t - 1))
        for testo, _, (l, t, r, b) in self._voci:
            box = QRectF(l, t, r - l, b - t)
            p.setPen(QPen(tema.con_alfa(tema.ACCENTO, 0.9), 1))
            p.setBrush(tema.con_alfa(tema.SFONDO, 0.92))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(tema.con_alfa(tema.ACCENTO, 1.0))
            p.drawText(box, Qt.AlignCenter, testo)
        if self._bolla is not None:
            self._disegna_bolla(p, self._bolla, self._fotogramma())
        p.end()
        self.tempi_disegno.append((time.perf_counter() - t0) * 1000)
        if len(self.tempi_disegno) > 2000:
            del self.tempi_disegno[:1000]

    @staticmethod
    def _disegna_bolla(p: QPainter, b: _Bolla, f: evidenza.Fotogramma) -> None:
        if f.finito or f.alfa <= 0.01 and f.onda_alfa <= 0.01:
            return
        colore = evidenza.colore(b.stile)
        # Sotto ogni tratto colorato, uno piu' largo e scuro: il ciano del tema
        # e' pensato per il fondo dell'Hub, e su una pagina bianca sparirebbe.
        # E' il bordo che hanno i cursori per leggersi su qualunque sfondo.
        ombra = tema.SFONDO
        l, t, r, bb = b.rect
        # Il contorno dice COSA e' stato trovato.
        p.setBrush(Qt.NoBrush)
        cornice = QRectF(l - 2, t - 2, r - l + 4, bb - t + 4)
        p.setPen(QPen(tema.con_alfa(ombra, 0.5 * f.contorno_alfa), 3.5))
        p.drawRoundedRect(cornice, 5, 5)
        p.setPen(QPen(tema.con_alfa(colore, f.contorno_alfa), 1.5))
        p.drawRoundedRect(cornice, 5, 5)
        # La bolla dice DOVE andra' il clic: morbida al centro, un anello sul bordo.
        c = QPointF(*evidenza.centro(b.rect))
        g = QRadialGradient(c, max(1.0, f.raggio))
        g.setColorAt(0.0, tema.con_alfa(colore, 0.34 * f.alfa))
        g.setColorAt(0.7, tema.con_alfa(colore, 0.16 * f.alfa))
        g.setColorAt(1.0, tema.con_alfa(colore, 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, f.raggio, f.raggio)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(tema.con_alfa(ombra, 0.55 * f.alfa), 4.5))
        p.drawEllipse(c, f.raggio, f.raggio)
        p.setPen(QPen(tema.con_alfa(colore, 0.95 * f.alfa), 2))
        p.drawEllipse(c, f.raggio, f.raggio)
        p.setPen(QPen(tema.con_alfa(ombra, 0.6 * f.alfa), 1.5))
        p.setBrush(tema.con_alfa(colore, f.alfa))
        p.drawEllipse(c, 3.0, 3.0)
        if f.onda_alfa > 0.01:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(tema.con_alfa(ombra, 0.5 * f.onda_alfa), 4))
            p.drawEllipse(c, f.onda_raggio, f.onda_raggio)
            p.setPen(QPen(tema.con_alfa(colore, f.onda_alfa), 2))
            p.drawEllipse(c, f.onda_raggio, f.onda_raggio)


class Ponte(QObject):
    """Dal thread del turno all'overlay, sul thread della GUI.

    Gli strumenti chiamano `mostra`, `nascondi`, `evidenzia`, `clic` e
    `spegni_evidenza` dal thread del turno; qui diventano segnali, e Qt li
    consegna in coda, nello stesso ordine, al thread dell'overlay. E' la regola
    di M3: nessun accesso diretto ai widget da un altro thread.
    """

    _mostra = Signal(object, object)
    _nascondi = Signal()
    _evidenzia = Signal(object, object, str)
    _clic = Signal()
    _spegni = Signal()

    def __init__(self, overlay: OverlayNumeri):
        super().__init__()
        self._mostra.connect(overlay.mostra)
        self._nascondi.connect(overlay.nascondi)
        self._evidenzia.connect(overlay.evidenzia)
        self._clic.connect(overlay.clic)
        self._spegni.connect(overlay.spegni_evidenza)

    def mostra(self, cornice, numerati) -> None:
        self._mostra.emit(tuple(cornice), [(n, tuple(r)) for n, r in numerati])

    def nascondi(self) -> None:
        self._nascondi.emit()

    def evidenzia(self, cornice, rect, stile: str) -> None:
        self._evidenzia.emit(tuple(cornice), tuple(rect), str(stile))

    def clic(self) -> None:
        self._clic.emit()

    def spegni_evidenza(self) -> None:
        self._spegni.emit()
