"""L'Hub: la vista di tutti i giorni. PHASE1, vedi SPECS/PHASE1/Piano_Interfaccia_Hub.md.

    intestazione   nome, salute, orologio, meteo, kill switch, altre viste
    sinistra       sistema, meteo, fotocamera, sessione
    centro         il nucleo, lo stato in parole, la barra dei controlli
    destra         la conversazione a fumetti e il campo di testo

COME LE ALTRE VISTE, NON TOCCA IL NUCLEO
Emette segnali e basta: `Applicazione` decide cosa fare di "parla",
"scrivi", "pulisci". Cosi' il pulsante del microfono, la scorciatoia globale
e la tray passano dallo stesso slot, come in M3.

L'OROLOGIO SI FERMA IN TRAY
Un `QTimer` a 1 Hz che gira per 72 ore con la finestra nascosta non costa
quasi niente, ma e' lo stesso errore di un'animazione che gira in tray. La
regola e' una: con la vista nascosta, niente timer.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from metis.core.palette import esadecimale, significato
from metis.gui import tema
from metis.gui.componenti import Pannello, Pillola, PulsanteIcona
from metis.gui.modello_conversazione import ModelloConversazione
from metis.gui.widgets.fumetti import ConversazioneFumetti
from metis.gui.widgets.meteo import PannelloMeteo
from metis.gui.widgets.nucleo import Nucleo
from metis.gui.widgets.sistema import PannelloSegnaposto, PannelloSessione, PannelloSistema

LARGHEZZA_SINISTRA = 340
LARGHEZZA_DESTRA = 420
SOGLIA_COLONNA_SINISTRA = 1280     # sotto, la colonna sinistra si nasconde
NUCLEO_MIN, NUCLEO_MAX = 200, 440    # lato del nucleo: il 40% dell'altezza, fra questi
SUGGERIMENTO_KILL = "Kill switch: sospende le azioni sul PC (Ctrl+Alt+Shift+M)"

# Stati in cui un messaggio scritto non parte: vedi `Orchestrator.on_testo`.
OCCUPATO = frozenset({"TRASCRIZIONE", "ELABORAZIONE", "ESECUZIONE", "ATTESA_CONFERMA",
                      "INTERROTTO", "ERRORE"})

GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre")


def data_in_parole(t: datetime) -> str:
    """"giovedì 25 settembre": senza `locale`, che su Windows dipende da come
    e' configurata la macchina e cambierebbe la lingua della GUI."""
    return f"{GIORNI[t.weekday()]} {t.day} {MESI[t.month - 1]}"


class HubView(QWidget):
    chiede_ptt = Signal()
    chiede_kill = Signal()
    chiede_minimal = Signal()
    chiede_diagnostica = Signal()
    chiede_testo = Signal(str)
    chiede_pulisci = Signal()
    chiede_muto = Signal(bool)
    chiede_impostazioni = Signal()

    def __init__(self, modello: ModelloConversazione, parent=None):
        super().__init__(parent)
        self.modello = modello
        self.setWindowTitle("Metis")
        self.setObjectName("hub")
        self.resize(1480, 900)
        self.setMinimumSize(1000, 660)
        self.stato = "DORMIENTE"
        self.pronto = False
        self._kill = False

        radice = QVBoxLayout(self)
        radice.setContentsMargins(0, 0, 0, 0)
        radice.setSpacing(0)
        radice.addWidget(self._intestazione())

        corpo = QHBoxLayout()
        corpo.setContentsMargins(20, 20, 20, 20)
        corpo.setSpacing(20)
        self.sinistra = self._colonna_sinistra()
        corpo.addWidget(self.sinistra)
        corpo.addLayout(self._colonna_centrale(), 1)
        corpo.addWidget(self._colonna_destra())
        radice.addLayout(corpo, 1)

        self._orologio = QTimer(self)
        self._orologio.setInterval(1000)
        self._orologio.timeout.connect(self._aggiorna_ora)
        self._aggiorna_ora()
        self._aggiorna_invio()

    # -- costruzione -------------------------------------------------------------

    def _intestazione(self) -> QWidget:
        barra = QFrame()
        barra.setObjectName("intestazione")
        barra.setFixedHeight(66)
        barra.setStyleSheet(f"#intestazione {{ background: {tema.SFONDO_ALTO};"
                            f" border: none; border-bottom: 1px solid {tema.BORDO}; }}")
        riga = QHBoxLayout(barra)
        riga.setContentsMargins(22, 0, 16, 0)
        riga.setSpacing(14)

        nome = QLabel("M.E.T.I.S")
        nome.setFont(tema.font(tema.FONT_TITOLI, 21, QFont.Weight.Bold))
        nome.setStyleSheet(f"color: {tema.ACCENTO};")
        riga.addWidget(nome)
        self.salute = Pillola("Avvio in corso", tema.ATTENZIONE, px=11)
        riga.addWidget(self.salute)
        riga.addStretch(1)

        scatola = QFrame()
        scatola.setObjectName("scatolaOra")
        scatola.setStyleSheet(f"#scatolaOra {{ background: {tema.PANNELLO}; border: 1px solid"
                              f" {tema.BORDO}; border-radius: {tema.RAGGIO_PICCOLO}px; }}")
        dentro = QHBoxLayout(scatola)
        dentro.setContentsMargins(14, 7, 16, 7)
        dentro.setSpacing(10)
        icona = QLabel()
        icona.setPixmap(tema.pixmap_icona("clock", tema.TESTO_TENUE, 16, self.devicePixelRatioF()))
        self.ora = QLabel("--:--:--")
        self.ora.setFont(tema.font(tema.FONT_NUMERI, 16))
        self.ora.setStyleSheet(f"color: {tema.TESTO};")
        separatore = QLabel("|")
        separatore.setStyleSheet(f"color: {tema.BORDO_FORTE};")
        self.data = QLabel("")
        self.data.setFont(tema.font(tema.FONT_TESTO, 14))
        self.data.setStyleSheet(f"color: {tema.TESTO};")
        for w in (icona, self.ora, separatore, self.data):
            dentro.addWidget(w)
        riga.addWidget(scatola, 0, Qt.AlignmentFlag.AlignVCenter)
        riga.addStretch(1)

        self.meteo_icona = QLabel()
        self.meteo_icona.hide()
        riga.addWidget(self.meteo_icona)
        self.meteo_breve = QLabel("")
        self.meteo_breve.setFont(tema.font(tema.FONT_NUMERI, 14))
        self.meteo_breve.setStyleSheet(f"color: {tema.TESTO};")
        self.meteo_breve.hide()
        riga.addWidget(self.meteo_breve)
        riga.addSpacing(6)

        self.b_kill = PulsanteIcona("shield", SUGGERIMENTO_KILL, lato=40)
        self.b_kill.clicked.connect(self.chiede_kill)
        self.b_diagnostica = PulsanteIcona("activity", "Diagnostica: audit, contesto, latenze",
                                           lato=40)
        self.b_diagnostica.clicked.connect(self.chiede_diagnostica)
        self.b_minimal = PulsanteIcona("minimize-2", "Vista compatta", lato=40)
        self.b_minimal.clicked.connect(self.chiede_minimal)
        self.b_impostazioni = PulsanteIcona("settings", "Impostazioni", lato=40)
        self.b_impostazioni.clicked.connect(self.chiede_impostazioni)
        for b in (self.b_kill, self.b_diagnostica, self.b_minimal, self.b_impostazioni):
            riga.addWidget(b)
        return barra

    def _colonna_sinistra(self) -> QWidget:
        """Scorrevole in verticale: i quattro pannelli chiedono ~780 px, e a
        1280x720 venivano schiacciati — barre sovrapposte, tessere collassate.
        Meglio una barra di scorrimento che un pannello illeggibile."""
        box = QWidget()
        box.setObjectName("colonnaSinistra")
        box.setStyleSheet("#colonnaSinistra { background: transparent; }")
        scorri = QScrollArea()
        scorri.setWidget(box)
        scorri.setWidgetResizable(True)
        scorri.setFrameShape(QFrame.Shape.NoFrame)
        scorri.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scorri.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scorri.setFixedWidth(LARGHEZZA_SINISTRA + 12)      # spazio per la barra
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(16)
        self.sistema = PannelloSistema()
        self.meteo = PannelloMeteo()
        # D-UI 1: nessuna sorgente per ora. Il pannello c'e', il contenuto no.
        self.fotocamera = PannelloSegnaposto("Fotocamera", "camera", "camera-off",
                                             "Nessuna fotocamera collegata.")
        self.sessione = PannelloSessione()
        for w in (self.sistema, self.meteo, self.fotocamera, self.sessione):
            lay.addWidget(w)
        lay.addStretch(1)
        return scorri

    def _colonna_centrale(self) -> QVBoxLayout:
        lay = QVBoxLayout()
        lay.setSpacing(14)
        lay.addStretch(2)
        self.nucleo = Nucleo()
        lay.addWidget(self.nucleo, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(18)
        nome = QLabel("M.E.T.I.S")
        nome.setFont(tema.font(tema.FONT_TITOLI, 26, QFont.Weight.Bold))
        nome.setStyleSheet(f"color: {tema.TESTO};")
        lay.addWidget(nome, 0, Qt.AlignmentFlag.AlignHCenter)
        self.pillola_stato = Pillola(significato("DORMIENTE"), esadecimale("DORMIENTE"), px=14)
        lay.addWidget(self.pillola_stato, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(3)

        controlli = QHBoxLayout()
        controlli.setSpacing(18)
        controlli.addStretch(1)
        self.b_camera = PulsanteIcona("camera-off", "Fotocamera: non ancora collegata")
        self.b_camera.setEnabled(False)
        self.b_microfono = PulsanteIcona("mic", "Parla (Ctrl+Alt+M)")
        self.b_microfono.clicked.connect(self.chiede_ptt)
        self.b_tastiera = PulsanteIcona("keyboard", "Scrivi un messaggio")
        self.b_tastiera.clicked.connect(self._alla_tastiera)
        self.b_voce = PulsanteIcona("volume-2", "Voce di Metis: attiva")
        self.b_voce.setCheckable(True)
        self.b_voce.toggled.connect(self._voce)
        for b in (self.b_camera, self.b_microfono, self.b_tastiera, self.b_voce):
            controlli.addWidget(b)
        controlli.addStretch(1)
        lay.addLayout(controlli)
        return lay

    def _colonna_destra(self) -> QWidget:
        self.pannello_conv = Pannello("Conversazione", "message-square")
        self.pannello_conv.setFixedWidth(LARGHEZZA_DESTRA)
        self.b_pulisci = self.pannello_conv.aggiungi_azione(
            PulsanteIcona("trash", "Pulisci: cancella la conversazione e la memoria di Metis",
                          lato=30))
        self.b_pulisci.clicked.connect(self._chiedi_pulisci)
        self.b_esporta = self.pannello_conv.aggiungi_azione(
            PulsanteIcona("download", "Esporta la conversazione in Markdown", lato=30))
        self.b_esporta.clicked.connect(self._esporta)

        self.fumetti = ConversazioneFumetti(self.modello)
        self.pannello_conv.corpo.addWidget(self.fumetti, 1)

        riga = QHBoxLayout()
        riga.setSpacing(8)
        self.campo = QLineEdit()
        self.campo.setPlaceholderText("Scrivi un messaggio…")
        self.campo.setFixedHeight(44)
        self.campo.returnPressed.connect(self._invia)
        self.campo.textChanged.connect(self._aggiorna_invio)
        self.b_invia = PulsanteIcona("send", "Invia", lato=44)
        self.b_invia.clicked.connect(self._invia)
        riga.addWidget(self.campo, 1)
        riga.addWidget(self.b_invia)
        self.pannello_conv.corpo.addLayout(riga)
        return self.pannello_conv

    # -- ingressi da Applicazione ------------------------------------------------

    @Slot(str)
    def imposta_stato(self, stato: str) -> None:
        self.stato = stato
        self.nucleo.imposta_stato(stato)
        self._aggiorna_pillola()
        self._aggiorna_invio()

    def _aggiorna_pillola(self) -> None:
        # In pausa il nucleo e' spento ma il turno in corso finisce comunque:
        # la pillola dice entrambe le cose, invece di contraddire il nucleo.
        testo = significato(self.stato)
        if self.nucleo.pausa:
            testo += "  ·  ascolto in pausa"
        self.pillola_stato.imposta(testo, esadecimale(self.stato))

    @Slot(dict)
    def imposta_meteo(self, d: dict) -> None:
        """Dal worker del meteo, attraverso `Applicazione`: pannello e
        intestazione insieme, cosi' non possono dire due cose diverse."""
        self.meteo.aggiorna(d)
        breve = self.meteo.breve()
        self.meteo_breve.setText(breve)
        self.meteo_breve.setVisible(bool(breve))
        self.meteo_icona.setVisible(bool(breve))
        if breve:
            self.meteo_icona.setPixmap(tema.pixmap_icona(
                self.meteo.icona_nome or "cloud", tema.TESTO_TENUE, 18,
                self.devicePixelRatioF()))

    @Slot(bool)
    def imposta_kill(self, attivo: bool) -> None:
        self.nucleo.imposta_kill(attivo)
        self.b_kill.imposta_icona("shield-alert" if attivo else "shield",
                                  tema.ERRORE if attivo else tema.ACCENTO)
        self.b_kill.setToolTip("Kill switch ATTIVO: azioni sospese. Clic per riattivarle."
                               if attivo else SUGGERIMENTO_KILL)
        self._aggiorna_salute(kill=attivo)

    @Slot(bool)
    def imposta_pausa(self, attiva: bool) -> None:
        self.nucleo.imposta_pausa(attiva)
        self._aggiorna_pillola()
        self.b_microfono.imposta_icona("mic-off" if attiva else "mic",
                                       tema.ATTENZIONE if attiva else tema.ACCENTO)
        self.b_microfono.setToolTip("Ascolto in pausa: il push-to-talk interrompe Metis ma non "
                                    "riapre il microfono" if attiva else "Parla (Ctrl+Alt+M)")

    @Slot()
    def imposta_pronto(self) -> None:
        self.pronto = True
        self._aggiorna_salute()
        self._aggiorna_invio()

    def _aggiorna_salute(self, kill: bool | None = None) -> None:
        if kill is not None:
            self._kill = kill
        if self._kill:
            self.salute.imposta("Azioni sospese", tema.ERRORE)
        elif self.pronto:
            self.salute.imposta("Operativo", tema.OK)
        else:
            self.salute.imposta("Avvio in corso", tema.ATTENZIONE)

    # -- campo di testo --------------------------------------------------------------

    def _aggiorna_invio(self) -> None:
        libero = self.pronto and self.stato not in OCCUPATO
        self.b_invia.setEnabled(libero and bool(self.campo.text().strip()))
        if not self.pronto:
            self.campo.setPlaceholderText("Metis si sta avviando…")
        elif not libero:
            self.campo.setPlaceholderText("Un momento: Metis sta lavorando…")
        else:
            self.campo.setPlaceholderText("Scrivi un messaggio…")

    @Slot()
    def _invia(self) -> None:
        testo = self.campo.text().strip()
        if not testo or not self.b_invia.isEnabled():
            return
        self.chiede_testo.emit(testo)

    def testo_accettato(self) -> None:
        """Chiamata da `Applicazione` quando il turno e' partito: solo allora il
        campo si svuota. Un messaggio rifiutato resta dov'e', da rimandare."""
        self.campo.clear()

    @Slot()
    def _alla_tastiera(self) -> None:
        self.campo.setFocus(Qt.FocusReason.ShortcutFocusReason)

    @Slot(bool)
    def _voce(self, muta: bool) -> None:
        self.b_voce.imposta_icona("volume-x" if muta else "volume-2",
                                  tema.ATTENZIONE if muta else tema.ACCENTO)
        self.b_voce.setToolTip("Voce di Metis: disattivata, le risposte restano scritte"
                               if muta else "Voce di Metis: attiva")
        self.chiede_muto.emit(muta)

    # -- pulisci ed esporta ----------------------------------------------------------

    @Slot()
    def _chiedi_pulisci(self) -> None:
        domanda = QMessageBox(self)
        domanda.setWindowTitle("Pulisci la conversazione")
        domanda.setText("Cancello la conversazione e la memoria che Metis ne ha?")
        domanda.setInformativeText("Metis non ricorderà più di cosa avete parlato. "
                                   "I promemoria e l'audit restano.")
        si = domanda.addButton("Pulisci", QMessageBox.ButtonRole.DestructiveRole)
        no = domanda.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        # Come nel dialogo T3: Invio per riflesso non cancella niente.
        domanda.setDefaultButton(no)
        domanda.exec()
        if domanda.clickedButton() is si:
            self.chiede_pulisci.emit()

    @Slot()
    def _esporta(self) -> None:
        nome = f"Metis_{datetime.now():%Y%m%d_%H%M}.md"
        percorso, _ = QFileDialog.getSaveFileName(
            self, "Esporta la conversazione", str(Path.home() / "Documents" / nome),
            "Markdown (*.md)")
        if percorso:
            self.esporta_in(Path(percorso))

    def esporta_in(self, percorso: Path) -> None:
        percorso.write_text(self.modello.markdown(), encoding="utf-8")

    # -- orologio e visibilita' ---------------------------------------------------------

    def _aggiorna_ora(self) -> None:
        adesso = datetime.now()
        self.ora.setText(adesso.strftime("%H:%M:%S"))
        self.data.setText(data_in_parole(adesso))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._aggiorna_ora()
        self._orologio.start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._orologio.stop()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # Sotto i 1280 px la colonna sinistra lascia il posto: conversazione
        # e nucleo contano di piu' dei grafici.
        sinistra = self.width() >= SOGLIA_COLONNA_SINISTRA
        self.sinistra.setVisible(sinistra)
        # Il nucleo cresce con la finestra: a 1080p e' grande come nella
        # reference, a 720 lascia spazio al nome e ai controlli.
        centro = self.width() - 40 - 20 - LARGHEZZA_DESTRA
        if sinistra:
            centro -= self.sinistra.width() + 20
        lato = int(max(NUCLEO_MIN, min(NUCLEO_MAX, self.height() * 0.40, centro * 0.85)))
        self.nucleo.setFixedSize(lato, lato)
