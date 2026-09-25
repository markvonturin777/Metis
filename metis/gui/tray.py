"""L'icona nella tray: Metis quando nessuna finestra e' aperta.

L'ICONA SI DISEGNA, NON SI CARICA
Un file .ico per stato sarebbero undici file da tenere allineati alla
palette e da ricordarsi di mettere nel bundle di PyInstaller. Disegnata qui,
l'icona prende il colore da `metis.core.palette` — la stessa tabella del
pallino dell'overlay e della console — e non puo' divergere.

TRE INFORMAZIONI IN SEDICI PIXEL
    colore del disco      lo stato della macchina, come l'overlay
    anello rosso          kill switch attivo: T2/T3 sospese
    due barre bianche     ascolto in pausa: il microfono non arriva a nessuno

Anello e barre si sovrappongono al colore invece di sostituirlo: con il kill
switch attivo Metis continua a parlare e ascoltare, e l'icona deve dirlo.

CHIUDERE LA FINESTRA NON E' USCIRE
Con la tray presente, la X nasconde. Si esce solo da "Esci", che passa da
`QApplication.quit` e quindi da `Applicazione.chiudi`: e' l'unico percorso
che ferma i thread, lo scheduler e rilascia il device audio nell'ordine
giusto. Un'uscita che non passasse di li' lascerebbe il microfono occupato
fino al riavvio del PC.

COME GLI ALTRI WIDGET, NON TOCCA IL NUCLEO
Emette segnali e basta. Chi decide cosa fa "Kill switch" e' `Applicazione`,
cosi' la tray, i pulsanti delle viste e la scorciatoia globale passano dallo
stesso slot.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from metis.core.palette import esadecimale, significato

LATO = 64                     # Windows riduce a 16/24/32: si disegna grande
ROSSO_KILL = "#ef4444"


def disegna(stato: str, kill: bool = False, pausa: bool = False,
            lato: int = LATO) -> QPixmap:
    """L'icona per questa combinazione. Funzione pura: la provano i test."""
    pix = QPixmap(lato, lato)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    margine = lato * 0.06
    disco = QRectF(margine, margine, lato - 2 * margine, lato - 2 * margine)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(esadecimale(stato)))
    p.drawEllipse(disco)

    if kill:
        spessore = lato * 0.12
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(ROSSO_KILL), spessore))
        m = margine + spessore / 2
        p.drawEllipse(QRectF(m, m, lato - 2 * m, lato - 2 * m))

    if pausa:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        w, h = lato * 0.12, lato * 0.40
        y = (lato - h) / 2
        p.drawRect(QRectF(lato / 2 - w * 1.5, y, w, h))
        p.drawRect(QRectF(lato / 2 + w * 0.5, y, w, h))

    p.end()
    return pix


def descrizione(stato: str, kill: bool, pausa: bool) -> str:
    """Il tooltip e la prima riga del menu: una frase, non un nome di enum."""
    parti = [f"Metis — {significato(stato)}"]
    if pausa:
        parti.append("ascolto in pausa")
    if kill:
        parti.append("azioni sospese")
    return ", ".join(parti)


class IconaTray(QObject):
    """Il menu della specifica M7 §4.2, in quest'ordine."""

    chiede_minimal = Signal()
    chiede_fullscreen = Signal()
    chiede_kill = Signal()
    chiede_pausa = Signal()
    chiede_uscita = Signal()
    cliccata = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stato = "DORMIENTE"
        self._kill = False
        self._pausa = False

        self.menu = QMenu()
        self.voce_stato = QAction(self.menu)
        self.voce_stato.setEnabled(False)          # si legge, non si clicca
        self.menu.addAction(self.voce_stato)
        self.menu.addSeparator()

        self.voce_minimal = self.menu.addAction("Mostra Minimal")
        self.voce_minimal.triggered.connect(self.chiede_minimal)
        self.voce_fullscreen = self.menu.addAction("Mostra Fullscreen")
        self.voce_fullscreen.triggered.connect(self.chiede_fullscreen)
        self.menu.addSeparator()

        # Checkable, ma la spunta la mette lo stato vero e non il clic: se il
        # nucleo non e' ancora pronto la pausa non attecchisce, e una spunta
        # messa da Qt al clic mentirebbe. Da qui `_rispecchia` dopo ogni clic.
        self.voce_kill = self.menu.addAction("Kill switch")
        self.voce_kill.setCheckable(True)
        self.voce_kill.triggered.connect(self._clic_kill)
        self.voce_pausa = self.menu.addAction("Pausa ascolto")
        self.voce_pausa.setCheckable(True)
        self.voce_pausa.triggered.connect(self._clic_pausa)
        self.menu.addSeparator()

        self.voce_esci = self.menu.addAction("Esci")
        self.voce_esci.triggered.connect(self.chiede_uscita)

        self.icona = QSystemTrayIcon(self)
        self.icona.setContextMenu(self.menu)
        self.icona.activated.connect(self._attivata)
        self._aggiorna()

    # -- ingressi ------------------------------------------------------------

    @Slot(str)
    def imposta_stato(self, stato: str) -> None:
        if stato != self._stato:
            self._stato = stato
            self._aggiorna()

    @Slot(bool)
    def imposta_kill(self, attivo: bool) -> None:
        # Arriva due volte al secondo dai contatori: si ridisegna solo se
        # cambia qualcosa, o l'area di notifica lampeggerebbe.
        if attivo != self._kill:
            self._kill = attivo
            self._aggiorna()
        self.voce_kill.setChecked(self._kill)

    @Slot(bool)
    def imposta_pausa(self, attiva: bool) -> None:
        if attiva != self._pausa:
            self._pausa = attiva
            self._aggiorna()
        self.voce_pausa.setChecked(self._pausa)

    def mostra(self) -> None:
        self.icona.show()

    def nascondi(self) -> None:
        self.icona.hide()

    def avvisa(self, testo: str) -> None:
        self.icona.showMessage("Metis", testo, QSystemTrayIcon.MessageIcon.Information,
                               4000)

    # -- interno -------------------------------------------------------------

    def _aggiorna(self) -> None:
        testo = descrizione(self._stato, self._kill, self._pausa)
        self.icona.setIcon(QIcon(disegna(self._stato, self._kill, self._pausa)))
        self.icona.setToolTip(testo)
        self.voce_stato.setText(testo)
        self.voce_kill.setChecked(self._kill)
        self.voce_pausa.setChecked(self._pausa)

    @Slot()
    def _clic_kill(self) -> None:
        self.voce_kill.setChecked(self._kill)
        self.chiede_kill.emit()

    @Slot()
    def _clic_pausa(self) -> None:
        self.voce_pausa.setChecked(self._pausa)
        self.chiede_pausa.emit()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _attivata(self, motivo) -> None:
        # Il clic sinistro riporta la finestra; il destro apre il menu, e
        # quello lo fa Qt da solo.
        if motivo in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.cliccata.emit()
