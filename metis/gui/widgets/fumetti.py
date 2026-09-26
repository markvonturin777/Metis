"""La conversazione a fumetti: la colonna destra dell'Hub.

Metis a sinistra, l'utente a destra, gli eventi di sistema al centro in
piccolo — l'impostazione della reference. I dati vengono da
`ModelloConversazione`, come per il registro della Diagnostica.

DUECENTO FUMETTI, NON DI PIU'
Il modello ne tiene fino a duemila; qui se ne disegnano gli ultimi
duecento. Un widget per messaggio costa poco, ma il ricalcolo del layout a
ogni ridimensionamento cresce con il numero, e NFR-8 non fa eccezioni per
le conversazioni lunghe. Per rileggere tutto c'e' "Esporta".

IL TESTO PASSA DA `metis/gui/testo.py`
Il link di tracciamento da 1500 caratteri esiste ancora: un fumetto non deve
allargare la colonna piu' di quanto facesse la control room.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from metis.gui import tema
from metis.gui.modello_conversazione import SISTEMA, UTENTE, Messaggio, ModelloConversazione
from metis.gui.testo import elastica, per_etichetta

VISIBILI = 200
LARGHEZZA_FUMETTO = 0.86        # frazione della colonna


class Fumetto(QFrame):
    """LA LARGHEZZA SI CALCOLA
    Il testo e' "elastico" (non impone la sua larghezza, vedi `testo.py`), e
    un fumetto elastico in una riga con uno spazio accanto riceve il minimo:
    una parola per riga. Qui la larghezza e' quella del testo su una riga,
    fino al massimo della colonna; oltre, si va a capo."""

    MARGINE = 34                    # 16 + 16 di margini interni, 1 + 1 di bordo

    def __init__(self, m: Messaggio, massimo: int = 360, parent=None):
        super().__init__(parent)
        self.ruolo = m.ruolo
        self._massimo = massimo
        self.setObjectName("fumetto")
        sfondo = tema.FUMETTO_UTENTE if m.ruolo == UTENTE else tema.FUMETTO_METIS
        bordo = tema.ACCENTO_SCURO if m.ruolo == UTENTE else tema.BORDO
        self.setStyleSheet(f"#fumetto {{ background: {sfondo}; border: 1px solid {bordo};"
                           f" border-radius: 14px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 10)
        lay.setSpacing(6)
        self.testo = elastica(QLabel())
        self.testo.setTextFormat(Qt.TextFormat.PlainText)
        self.testo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.testo.setFont(tema.font(tema.FONT_TESTO, 14))
        self.testo.setStyleSheet(f"color: {tema.TESTO};")
        lay.addWidget(self.testo)
        self.piede = QLabel()
        self.piede.setFont(tema.font(tema.FONT_NUMERI, 10))
        self.piede.setStyleSheet(f"color: {tema.TESTO_SECONDARIO};")
        if m.ruolo == UTENTE:
            self.piede.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.piede)
        self.aggiorna(m)

    def aggiorna(self, m: Messaggio) -> None:
        self.testo.setText(per_etichetta(m.testo))
        note = [m.ora.strftime("%H:%M")]
        if m.scritto:
            note.append("scritto")
        if m.sospetto:
            note.append("trascrizione incerta")
        self.piede.setText("  ·  ".join(note))
        self._adatta()

    def imposta_massimo(self, massimo: int) -> None:
        if massimo != self._massimo:
            self._massimo = massimo
            self._adatta()

    def _adatta(self) -> None:
        testo = QFontMetrics(self.testo.font())
        piede = QFontMetrics(self.piede.font())
        righe = self.testo.text().splitlines() or [""]
        su_una_riga = max(testo.horizontalAdvance(r) for r in righe)
        voluta = max(su_una_riga, piede.horizontalAdvance(self.piede.text())) + self.MARGINE + 4
        self.setFixedWidth(max(90, min(self._massimo, voluta)))


class RigaSistema(QLabel):
    """"strumento: open_application" — un evento, non una battuta."""

    def __init__(self, m: Messaggio, parent=None):
        super().__init__(parent)
        elastica(self)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(tema.font(tema.FONT_TESTO, 11))
        self.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; padding: 2px 12px;")
        self.aggiorna(m)

    def aggiorna(self, m: Messaggio) -> None:
        self.setText(per_etichetta(f"{m.testo}  ·  {m.ora.strftime('%H:%M')}"))


class ConversazioneFumetti(QScrollArea):
    def __init__(self, modello: ModelloConversazione, parent=None):
        super().__init__(parent)
        self.modello = modello
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        contenuto = QWidget()
        contenuto.setObjectName("contenutoFumetti")
        contenuto.setStyleSheet("#contenutoFumetti { background: transparent; }")
        self._lista = QVBoxLayout(contenuto)
        self._lista.setContentsMargins(4, 4, 8, 4)
        self._lista.setSpacing(12)
        self.vuoto = QLabel("Premi Ctrl+Alt+M per parlare, oppure scrivi qui sotto.")
        self.vuoto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vuoto.setWordWrap(True)
        self.vuoto.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; padding: 30px 10px;")
        self._lista.addWidget(self.vuoto)
        self._lista.addStretch(1)
        self.setWidget(contenuto)

        self._righe: list[tuple[QWidget, QWidget]] = []   # (contenitore, fumetto)
        self._primo = 0                  # indice nel modello della prima riga disegnata
        self._segui = True
        barra = self.verticalScrollBar()
        barra.valueChanged.connect(self._scorso)
        barra.rangeChanged.connect(self._range)

        modello.aggiunto.connect(self._aggiunto)
        modello.aggiornato.connect(self._aggiornato)
        modello.troncato.connect(self._troncato)
        modello.azzerato.connect(self._azzerato)
        for i in range(len(modello)):
            self._aggiunto(i)

    # -- dal modello -----------------------------------------------------------

    @Slot(int)
    def _aggiunto(self, indice: int) -> None:
        m = self.modello[indice]
        if not self._righe:
            self._primo = indice
        self.vuoto.hide()
        contenitore = QWidget()
        contenitore.setStyleSheet("background: transparent;")
        riga = QHBoxLayout(contenitore)
        riga.setContentsMargins(0, 0, 0, 0)
        if m.ruolo == SISTEMA:
            fumetto = RigaSistema(m)
            riga.addWidget(fumetto)
        else:
            fumetto = Fumetto(m, self._larghezza_massima())
            if m.ruolo == UTENTE:
                riga.addStretch(1)
                riga.addWidget(fumetto)
            else:
                riga.addWidget(fumetto)
                riga.addStretch(1)
        self._lista.insertWidget(self._lista.count() - 1, contenitore)
        self._righe.append((contenitore, fumetto))
        if len(self._righe) > VISIBILI:
            self._togli_prima()

    @Slot(int)
    def _aggiornato(self, indice: int) -> None:
        k = indice - self._primo
        if 0 <= k < len(self._righe):
            self._righe[k][1].aggiorna(self.modello[indice])

    @Slot(int)
    def _troncato(self, quanti: int) -> None:
        # Il modello ha tolto i suoi `quanti` messaggi piu' vecchi: gli indici
        # scorrono all'indietro. Le righe che mostravano quei messaggi (indice
        # diventato negativo) se ne vanno; ogni `_togli_prima` avanza `_primo`.
        self._primo -= quanti
        while self._primo < 0 and self._righe:
            self._togli_prima()
        self._primo = max(self._primo, 0)

    @Slot()
    def _azzerato(self) -> None:
        while self._righe:
            contenitore, _ = self._righe.pop()
            contenitore.deleteLater()
        self._primo = 0
        self.vuoto.show()

    def _togli_prima(self) -> None:
        contenitore, _ = self._righe.pop(0)
        contenitore.deleteLater()
        self._primo += 1

    # -- scroll e larghezza ------------------------------------------------------

    def _larghezza_massima(self) -> int:
        return max(160, int(self.viewport().width() * LARGHEZZA_FUMETTO))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        massimo = self._larghezza_massima()
        for _, fumetto in self._righe:
            if isinstance(fumetto, Fumetto):
                fumetto.imposta_massimo(massimo)

    @Slot(int)
    def _scorso(self, valore: int) -> None:
        # Chi ha scrollato verso l'alto sta rileggendo: non lo si trascina in
        # fondo a ogni frase. Tornato in fondo, si riprende a seguire.
        self._segui = valore >= self.verticalScrollBar().maximum() - 4

    @Slot(int, int)
    def _range(self, _minimo: int, massimo: int) -> None:
        if self._segui:
            self.verticalScrollBar().setValue(massimo)

    def fumetti(self) -> list[QWidget]:
        """Per i test: i fumetti disegnati, nell'ordine."""
        return [f for _, f in self._righe]
