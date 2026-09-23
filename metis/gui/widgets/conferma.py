"""Il dialogo di conferma T3.

E' l'unico punto dell'interfaccia in cui un errore ha conseguenze: di la'
c'e' un'azione che non si annulla. Tutto il resto della GUI puo' sbagliare
e produrre fastidio; qui produce una email partita.

TRE SCELTE CONTRO L'ABITUDINE

**Nessun pulsante predefinito.** Invio non approva. Non approva nemmeno
quando il fuoco e' su "Approva": `setAutoDefault(False)` su entrambi, e
`keyPressEvent` intercetta Invio e lo ignora. Vent'anni di finestre di
dialogo hanno insegnato a premere Invio prima di leggere, e qui quella
abitudine costerebbe.

**Il fuoco parte su "Nega".** Se qualcuno preme la barra spaziatrice per
riflesso, nega.

**Si mostrano gli argomenti interi, non un riassunto.** Chi conferma deve
poter dire di no sapendo cosa sta per succedere. "Metis vuole eseguire
send_email" non e' un consenso informato: serve vedere a chi.

M6: fino a qui questa riga diceva "interi" e il codice tagliava a 400
caratteri. Con l'email arrivata in M6 la differenza e' diventata concreta —
approvare un messaggio di cui si e' letto l'inizio — e il taglio e' sparito:
i testi lunghi o su piu' righe vanno in un riquadro che scorre, per intero.

Il conto alla rovescia non e' decorazione: dice che l'attesa finisce, e
finisce con un rifiuto.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from metis.core.palette import esadecimale

# Oltre questa lunghezza, o con un a capo dentro, il valore va in un riquadro
# che scorre invece che in un'etichetta. NON e' un taglio: si vede tutto.
SOGLIA_RIQUADRO = 160


class DialogoConferma(QDialog):
    """Ritorna la decisione via segnale, non via `exec()`.

    Il segnale serve perche' chi aspetta e' un altro thread: il dialogo non
    sa nulla del ponte, si limita a dire cosa ha deciso l'utente.
    """

    deciso = Signal(bool)

    def __init__(self, strumento: str, tier: str, argomenti: dict,
                 timeout_s: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metis — conferma richiesta")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._rimasti = float(timeout_s)
        self._risposto = False

        colore = esadecimale("ATTESA_CONFERMA")
        radice = QVBoxLayout(self)

        # "NON si annulla" solo quando e' vero. Da M6 la conferma si chiede
        # anche per un promemoria T1, che si cancella con una frase: dirgli
        # "non si annulla" insegnerebbe a non credere all'avviso quando conta.
        avviso = ("questa azione NON si annulla" if tier == "T3"
                  else "controlla che sia quello che intendevi")
        testa = QLabel(f"{tier} — {avviso}")
        f = QFont()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        testa.setFont(f)
        testa.setStyleSheet(f"color: {colore};")
        radice.addWidget(testa)

        nome = QLabel(strumento)
        nome.setStyleSheet("font-family: Consolas, monospace; font-size: 15px;")
        radice.addWidget(nome)

        modulo = QFormLayout()
        modulo.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self.riquadri: list[QPlainTextEdit] = []
        for campo, valore in argomenti.items():
            if campo == "tool":
                continue
            testo = str(valore)
            if len(testo) > SOGLIA_RIQUADRO or "\n" in testo:
                v = QPlainTextEdit(testo)
                v.setReadOnly(True)
                v.setMinimumHeight(120)
                self.riquadri.append(v)
            else:
                v = QLabel(testo)
                v.setWordWrap(True)
                v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            modulo.addRow(f"{campo}:", v)
        radice.addLayout(modulo)

        self._conto = QLabel()
        self._conto.setStyleSheet("color: #94a3b8;")
        radice.addWidget(self._conto)

        pulsanti = QHBoxLayout()
        pulsanti.addStretch(1)

        self.nega = QPushButton("Nega")
        self.approva = QPushButton("Approva")
        for b in (self.nega, self.approva):
            # Nessun pulsante predefinito: senza questo, Invio approverebbe.
            b.setAutoDefault(False)
            b.setDefault(False)
        self.approva.setStyleSheet(
            f"QPushButton {{ color: white; background: {colore}; "
            "padding: 6px 18px; border-radius: 4px; }}")
        self.nega.setStyleSheet("QPushButton { padding: 6px 18px; }")

        self.nega.clicked.connect(lambda: self._decidi(False))
        self.approva.clicked.connect(lambda: self._decidi(True))
        pulsanti.addWidget(self.nega)
        pulsanti.addWidget(self.approva)
        radice.addLayout(pulsanti)

        # Il fuoco sul rifiuto: la barra spaziatrice premuta per riflesso nega.
        self.nega.setFocus()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tic)
        self._timer.start(250)
        self._aggiorna_conto()

    # -- tempo -------------------------------------------------------------

    def _tic(self) -> None:
        self._rimasti -= 0.25
        if self._rimasti <= 0:
            # Non emette nulla: chi aspetta ha il proprio timeout e lo fara'
            # scattare da solo. Emettere qui sarebbe una seconda sorgente di
            # verita' sullo stesso fatto.
            self._timer.stop()
            self.reject()
            return
        self._aggiorna_conto()

    def _aggiorna_conto(self) -> None:
        self._conto.setText(
            f"Se non rispondi entro {self._rimasti:.0f} s l'azione viene rifiutata."
        )

    # -- decisione ---------------------------------------------------------

    def _decidi(self, approvato: bool) -> None:
        if self._risposto:
            return
        self._risposto = True
        self._timer.stop()
        self.deciso.emit(approvato)
        self.accept() if approvato else self.reject()

    def keyPressEvent(self, event) -> None:
        """Invio non fa niente. Esc nega, che e' sicuro."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        if event.key() == Qt.Key_Escape:
            self._decidi(False)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        """Chiudere la finestra e' un no, non un'assenza di risposta."""
        if not self._risposto:
            self._decidi(False)
        super().closeEvent(event)
