"""Il nucleo al centro dell'Hub: dice lo stato di Metis di sbieco e a due metri.

IL COLORE E' DELLO STATO, NON DELLA CORNICE
Gli anelli prendono il colore da `metis/core/palette.py`, la tabella della
tray e del terminale. La reference e' tutta ciano; qui il ciano e' della
cornice, e il nucleo cambia colore quando Metis cambia stato. E' il pallino
di M3, ingrandito.

UNO STATO, UN MOVIMENTO
Il colore basta a chi guarda dritto; il movimento serve a chi guarda di
sbieco, e a chi distingue male i colori:

    DORMIENTE                   respiro lento, 4 s
    IN_ASCOLTO, TRASCRIZIONE    le barre e gli anelli seguono il microfono
    ELABORAZIONE, GENERAZIONE   un arco che ruota, le barre in sequenza
    RICERCA_WEB, ESECUZIONE     segmenti che ruotano, in due versi
    ATTESA_CONFERMA             l'anello esterno pulsa
    PARLATO                     l'onda segue la voce di Metis, dal player
    INTERROTTO, ERRORE          un lampo che si allarga, anche dopo lo stato
    pausa                       fermo, spento, due barre

IL BAGLIORE E' DISEGNATO, NON UN EFFETTO
Un `QGraphicsDropShadowEffect` su un widget che si anima ridisegna fuori
schermo tutto il widget a ogni fotogramma. Il bagliore qui e' un gradiente
radiale nello stesso `paintEvent`: un'operazione, nessun buffer in piu'.

IN TRAY NON SI MUOVE NIENTE
Il timer dei fotogrammi gira solo con il widget visibile: si ferma con
`hideEvent`, che Qt manda anche quando la finestra si riduce a icona. Metis
resta in tray per 72 ore, e un'animazione che nessuno vede e' CPU sprecata.
Anche fermo quando non c'e' niente da muovere (la pausa) o quando le
animazioni sono spente dalle impostazioni.

I livelli arrivano ~31 volte al secondo dal thread del nucleo, attraverso
`Applicazione`: qui si salvano e basta. Li legge il fotogramma successivo.
"""

from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from metis.core.palette import esadecimale
from metis.gui import tema

FPS = 30
PERIODO_RESPIRO_S = 4.0
PERIODO_PULSAZIONE_S = 1.2
DURATA_LAMPO_S = 0.7
DURATA_SFUMATURA_S = 0.25
# Il livello in dBFS diventa un'ampiezza 0..1, con due scale.
# Microfono (misure di M0): stanza silenziosa -86, voce di chi parla p95 -22.
# Il fondo della scala sta 30 dB sopra il silenzio: a stanza muta le barre
# stanno ferme. Con musica negli altoparlanti (-66 di mediana, picchi a -40,
# misurato il 2026-09-25) si muovono sui picchi: il microfono la sente, e il
# VAD pure.
# Voce di Metis, letta dal player e non dal microfono: mediana -20, p95 -11.
# Con una scala sola l'onda di PARLATO stava sopra il 60% nel 97% dei
# fotogrammi: sempre alta, non seguiva le parole.
SCALA_MICROFONO = (-55.0, -20.0)
SCALA_VOCE = (-38.0, -8.0)
SILENZIO_DB = -120.0
# Costanti di tempo della media esponenziale: sale in fretta, scende piano.
# Un'onda che segue il livello istantaneo trema.
SALITA_S, DISCESA_S = 0.05, 0.22

ASCOLTO = frozenset({"IN_ASCOLTO", "TRASCRIZIONE"})
PENSA = frozenset({"ELABORAZIONE", "GENERAZIONE"})
AGISCE = frozenset({"RICERCA_WEB", "ESECUZIONE"})
LAMPO = frozenset({"INTERROTTO", "ERRORE"})

# L'onda di PARLATO: frequenza (cicli sulla larghezza), velocita' (rad/s),
# ampiezza relativa, opacita', spessore.
CURVE = ((1.3, 3.1, 1.00, 0.95, 2.4),
         (2.1, -4.3, 0.70, 0.60, 1.7),
         (2.9, 5.7, 0.48, 0.42, 1.3),
         (0.9, -2.2, 0.34, 0.30, 1.1))
PUNTI_ONDA = 28


def normalizza(db: float, scala: tuple[float, float]) -> float:
    basso, alto = scala
    return max(0.0, min(1.0, (db - basso) / (alto - basso)))


def mescola(a: QColor, b: QColor, f: float) -> QColor:
    f = max(0.0, min(1.0, f))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * f,
                           a.greenF() + (b.greenF() - a.greenF()) * f,
                           a.blueF() + (b.blueF() - a.blueF()) * f)


def alfa(c: QColor, a: float) -> QColor:
    k = QColor(c)
    k.setAlphaF(max(0.0, min(1.0, a)))
    return k


class Nucleo(QWidget):
    def __init__(self, lato: int = 340, fps: int = FPS, parent=None):
        super().__init__(parent)
        self.stato = "DORMIENTE"
        self.kill = False
        self.pausa = False
        self.animazioni = True
        self._lato = lato
        self.setMinimumSize(96, 96)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._orologio = time.perf_counter
        self._t0 = self._orologio()
        self._ultimo_fotogramma = self._t0
        self._microfono_db = SILENZIO_DB
        self._voce_db = SILENZIO_DB
        self.livello = 0.0                     # l'ampiezza smussata, 0..1
        self._colore = QColor(self.colore())
        self._colore_prima = QColor(self._colore)
        self._t_colore = -math.inf
        self._lampo: tuple[float, QColor] | None = None

        # Per i test e per la misura del giorno 7.
        self.disegni = 0
        self.tempi_ms: deque[float] = deque(maxlen=900)

        self._visibile = False
        self._timer = QTimer(self)
        # Preciso: il timer predefinito su Windows ha la grana di 15,6 ms, e
        # 33 ms diventano ora 31, ora 47 — un'onda che scatta.
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(round(1000 / fps))
        self._timer.timeout.connect(self._fotogramma)

    def sizeHint(self) -> QSize:
        return QSize(self._lato, self._lato)

    # -- ingressi ------------------------------------------------------------

    def imposta_stato(self, stato: str) -> None:
        if stato == self.stato:
            return
        self.stato = stato
        if stato in LAMPO:
            self._lampo = (self._orologio(), QColor(esadecimale(stato)))
        self._nuovo_colore()

    def imposta_kill(self, attivo: bool) -> None:
        if attivo != self.kill:
            self.kill = attivo
            self.update()

    def imposta_pausa(self, attiva: bool) -> None:
        if attiva != self.pausa:
            self.pausa = attiva
            self._nuovo_colore()

    def imposta_animazioni(self, attive: bool) -> None:
        """"Riduci animazioni" delle impostazioni: il nucleo resta fermo, e
        dice lo stato con il colore e la forma."""
        self.animazioni = attive
        self._aggiorna_timer()
        self.update()

    def campiona_microfono(self, rms_db: float) -> None:
        self._microfono_db = rms_db

    def campiona_voce(self, db: float) -> None:
        self._voce_db = db

    def colore(self) -> str:
        # In pausa il nucleo e' "spento" qualunque cosa accada: il colore di
        # DORMIENTE, come l'icona della tray.
        return esadecimale("DORMIENTE" if self.pausa else self.stato)

    def animato(self) -> bool:
        """Il timer dei fotogrammi gira? Per i test e per la tray."""
        return self._timer.isActive()

    def p95_ms(self) -> float:
        if not self.tempi_ms:
            return 0.0
        v = sorted(self.tempi_ms)
        return v[min(len(v) - 1, int(0.95 * len(v)))]

    def _nuovo_colore(self) -> None:
        # Si parte dal colore disegnato adesso, anche a meta' sfumatura:
        # due cambi di stato ravvicinati non fanno saltare il colore.
        self._colore_prima = self._colore_corrente(self._orologio())
        self._colore = QColor(self.colore())
        self._t_colore = self._orologio()
        self._aggiorna_timer()
        self.update()

    # -- il tempo ----------------------------------------------------------------

    def _deve_animare(self) -> bool:
        if not self._visibile or not self.animazioni:
            return False
        # In pausa non si muove niente, tranne un lampo gia' partito.
        return not self.pausa or self._lampo_attivo(self._orologio())

    def _aggiorna_timer(self) -> None:
        if self._deve_animare():
            if not self._timer.isActive():
                self._ultimo_fotogramma = self._orologio()
                self._timer.start()
        else:
            self._timer.stop()

    def _fotogramma(self) -> None:
        if self.window().isMinimized():
            # Di solito ci pensa hideEvent; questa e' la cintura.
            self._timer.stop()
            return
        ora = self._orologio()
        dt = max(0.0, ora - self._ultimo_fotogramma)
        self._ultimo_fotogramma = ora
        if self.pausa:
            obiettivo = 0.0
        elif self.stato in ASCOLTO:
            obiettivo = normalizza(self._microfono_db, SCALA_MICROFONO)
        elif self.stato == "PARLATO":
            obiettivo = normalizza(self._voce_db, SCALA_VOCE)
        else:
            obiettivo = 0.0
        tau = SALITA_S if obiettivo > self.livello else DISCESA_S
        self.livello += (obiettivo - self.livello) * (1.0 - math.exp(-dt / tau))
        if self.pausa and not self._lampo_attivo(ora):
            self._timer.stop()
        self.update()

    def _lampo_attivo(self, ora: float) -> bool:
        return self._lampo is not None and ora - self._lampo[0] < DURATA_LAMPO_S

    def _colore_corrente(self, ora: float) -> QColor:
        if not self.animazioni:
            return QColor(self._colore)
        return mescola(self._colore_prima, self._colore,
                       (ora - self._t_colore) / DURATA_SFUMATURA_S)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._visibile = True
        self._aggiorna_timer()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._visibile = False
        self._timer.stop()

    # -- disegno -----------------------------------------------------------------

    def paintEvent(self, _) -> None:
        inizio = time.perf_counter()
        self.disegni += 1
        ora = self._orologio()
        t = ora - self._t0 if self.animazioni else 0.0
        livello = self.livello if self.animazioni else 0.0
        colore = self._colore_corrente(ora)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lato = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        r = lato / 2 - max(3.0, lato * 0.018)
        spessore = max(1.0, lato / 170)          # 2 px a 340, 1 px in miniatura
        attivo = not self.pausa

        respiro = 0.5 - 0.5 * math.cos(2 * math.pi * t / PERIODO_RESPIRO_S)
        pulsazione = 0.5 - 0.5 * math.cos(2 * math.pi * t / PERIODO_PULSAZIONE_S)

        # bagliore
        intensita = 0.18
        if attivo and self.stato == "DORMIENTE":
            intensita = 0.12 + 0.10 * respiro
        elif attivo and self.stato == "ATTESA_CONFERMA":
            intensita = 0.16 + 0.22 * pulsazione
        elif attivo and (self.stato in ASCOLTO or self.stato == "PARLATO"):
            intensita = 0.16 + 0.22 * livello
        alone = QRadialGradient(c, r)
        alone.setColorAt(0.0, alfa(colore, intensita))
        alone.setColorAt(0.55, alfa(colore, intensita * 0.35))
        alone.setColorAt(1.0, alfa(colore, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alone)
        p.drawEllipse(c, r, r)

        # anelli
        p.setBrush(Qt.BrushStyle.NoBrush)
        esterno_a, esterno_s = 0.45, spessore
        if attivo and self.stato == "ATTESA_CONFERMA":
            esterno_a, esterno_s = 0.45 + 0.50 * pulsazione, spessore * (1 + 1.5 * pulsazione)
        p.setPen(QPen(alfa(colore, esterno_a), esterno_s))
        p.drawEllipse(c, r, r)
        dilata = 0.05 * livello if attivo and self.stato in ASCOLTO else 0.0
        for frazione, a, s in ((0.84, 0.30, 0.6), (0.78, 0.22, 0.5)):
            p.setPen(QPen(alfa(colore, a + 1.6 * dilata), spessore * s))
            p.drawEllipse(c, r * (frazione + dilata), r * (frazione + dilata))

        if attivo and self.stato in PENSA:
            self._arco_rotante(p, c, r * 0.92, colore, t, spessore)
        elif attivo and self.stato in AGISCE:
            self._segmenti(p, c, r, colore, t, spessore)

        # disco interno
        ri = r * 0.60
        disco = QRadialGradient(c, ri)
        disco.setColorAt(0.0, alfa(colore, 0.30))
        disco.setColorAt(1.0, QColor(tema.PANNELLO_TESTATA))
        p.setBrush(disco)
        p.setPen(QPen(alfa(colore, 0.70), spessore))
        p.drawEllipse(c, ri, ri)

        # il segno al centro
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alfa(colore, 1.0))
        if self.pausa:
            w, h = ri * 0.14, ri * 0.55
            p.drawRoundedRect(QRectF(c.x() - w * 1.6, c.y() - h / 2, w, h), 2, 2)
            p.drawRoundedRect(QRectF(c.x() + w * 0.6, c.y() - h / 2, w, h), 2, 2)
        elif self.stato == "PARLATO":
            self._onda(p, c, ri, colore, t, livello, spessore)
        else:
            self._barre(p, c, ri, t, livello, respiro)

        # il lampo di INTERROTTO ed ERRORE, che dura oltre lo stato
        if self._lampo is not None and self.animazioni:
            eta = (ora - self._lampo[0]) / DURATA_LAMPO_S
            if eta < 1.0:
                raggio = ri + (r * 1.02 - ri) * eta
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(alfa(self._lampo[1], 0.9 * (1 - eta)), spessore * 2))
                p.drawEllipse(c, raggio, raggio)
            else:
                self._lampo = None

        if self.kill:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(tema.ERRORE), spessore * 2))
            p.drawEllipse(c, r - spessore, r - spessore)
        p.end()
        self.tempi_ms.append((time.perf_counter() - inizio) * 1000.0)

    def _barre(self, p: QPainter, c: QPointF, ri: float, t: float,
               livello: float, respiro: float) -> None:
        """I cinque punti della reference. Respirano in DORMIENTE, ballano con
        il microfono in ascolto, si inseguono mentre Metis pensa."""
        passo, d = ri * 0.17, ri * 0.09
        attivo = self.animazioni
        for k, i in enumerate(range(-2, 3)):
            base = d * (2.2 if i == 0 else 1.6 if abs(i) == 1 else 1.0)
            if self.stato == "DORMIENTE":
                altezza = base * (1 + 0.12 * respiro)
            elif self.stato in ASCOLTO:
                vibra = 0.6 + 0.4 * abs(math.sin(t * 7.0 + k * 1.3)) if attivo else 1.0
                altezza = base + ri * 0.55 * livello * vibra * (1.0 - 0.18 * abs(i))
            elif self.stato in PENSA and attivo:
                onda = max(0.0, math.sin(2 * math.pi * 1.1 * t - k * 0.7)) ** 2
                altezza = base * (1 + 1.4 * onda)
            else:
                altezza = base
            barra = QRectF(c.x() + i * passo - d / 2, c.y() - altezza / 2, d, altezza)
            p.drawRoundedRect(barra, d / 2, d / 2)

    def _onda(self, p: QPainter, c: QPointF, ri: float, colore: QColor, t: float,
              livello: float, spessore: float) -> None:
        """PARLATO: curve di Bezier con fasi diverse, l'ampiezza dalla voce.
        Un filo d'onda anche fra una parola e l'altra: piatta sembrerebbe
        ferma, cioe' un altro stato."""
        larghezza = ri * 1.64
        ampiezza = ri * (0.05 + 0.42 * livello)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for frequenza, velocita, relativa, opacita, s in CURVE:
            punti = []
            for n in range(PUNTI_ONDA + 1):
                u = n / PUNTI_ONDA * 2 - 1                  # -1..1
                finestra = (1 - u * u) ** 2                 # agli estremi, zero
                y = math.sin(math.pi * frequenza * u + velocita * t)
                punti.append(QPointF(c.x() + u * larghezza / 2,
                                     c.y() - ampiezza * relativa * finestra * y))
            cammino = QPainterPath(punti[0])
            for a, b in zip(punti[1:-1], punti[2:]):
                cammino.quadTo(a, (a + b) / 2)
            cammino.lineTo(punti[-1])
            p.setPen(QPen(alfa(colore, opacita), spessore * s, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawPath(cammino)

    def _arco_rotante(self, p: QPainter, c: QPointF, raggio: float, colore: QColor,
                      t: float, spessore: float) -> None:
        """ELABORAZIONE e GENERAZIONE: un arco con una scia."""
        rett = QRectF(c.x() - raggio, c.y() - raggio, 2 * raggio, 2 * raggio)
        inizio = -(t * 225.0) % 360.0 if self.animazioni else 90.0
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, a in enumerate((0.95, 0.45, 0.2)):
            p.setPen(QPen(alfa(colore, a), spessore * 1.6, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawArc(rett, round((inizio + 24 * k) * 16), round(46 * 16))

    def _segmenti(self, p: QPainter, c: QPointF, r: float, colore: QColor, t: float,
                  spessore: float) -> None:
        """RICERCA_WEB ed ESECUZIONE: tre segmenti fuori, sei dentro, in versi
        opposti. Diverso dall'arco del "sta pensando" anche senza colori."""
        p.setBrush(Qt.BrushStyle.NoBrush)
        giro = t * 140.0 if self.animazioni else 0.0
        for raggio, quanti, ampiezza, verso, a in ((r * 0.92, 3, 34, -1, 0.9),
                                                  (r * 0.70, 6, 16, 1, 0.6)):
            rett = QRectF(c.x() - raggio, c.y() - raggio, 2 * raggio, 2 * raggio)
            p.setPen(QPen(alfa(colore, a), spessore * 1.6, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.FlatCap))
            for k in range(quanti):
                inizio = (verso * giro + k * 360.0 / quanti) % 360.0
                p.drawArc(rett, round(inizio * 16), round(ampiezza * 16))
