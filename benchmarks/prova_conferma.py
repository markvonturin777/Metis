"""Il dialogo di conferma T3, da provare a mano. Nessun modello caricato.

PERCHE' SERVE UN BANCO A PARTE
Il dialogo e' il punto piu' delicato dell'interfaccia — di la' c'e'
un'azione che non si annulla — ma in V1.0 non si riesce a farlo comparire
parlando: l'unico strumento T3 e' `send_email`, che non ha ancora un corpo
e quindi non viene nemmeno offerto al modello. Senza questo banco, l'unico
modo di vederlo sarebbe aspettare M6.

COSA PROVARE, IN ORDINE
  1. Premi INVIO.      Non deve succedere niente. E' la cosa che l'abitudine
                       fa fare per prima, ed e' quella che manderebbe la
                       email.
  2. Premi SPAZIO.     Nega: il fuoco parte sul rifiuto apposta.
  3. Premi ESC.        Nega.
  4. Chiudi la finestra con la X.   Nega: chiudere non e' "non ho risposto".
  5. Non fare niente.  Dopo N secondi si chiude da sola e il broker riceve
                       un rifiuto. Un'attesa che scade in sì sarebbe peggio
                       di nessuna conferma.
  6. Approva.          Solo questo passa.

Il riquadro in basso dice cosa ha ricevuto il broker: e' la risposta vera
che tornerebbe a `Context.chiedi_conferma`, non una simulazione.

    python benchmarks/prova_conferma.py
    python benchmarks/prova_conferma.py --timeout 5
"""

from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from metis.gui.conferma import PonteConferma
from metis.gui.widgets.conferma import DialogoConferma
from metis.security.audit import Tier

ARGOMENTI = {
    "tool": "send_email",
    "to": "marco.rossi@esempio.it",
    "subject": "Riepilogo della settimana",
    "body": "Ciao Marco, in allegato il riepilogo. A lunedi'.",
}


@dataclass
class FintoSpec:
    name: str = "send_email"
    tier: Tier = Tier.T3


class FintaCall:
    def model_dump(self) -> dict:
        return dict(ARGOMENTI)


class Banco(QWidget):
    # Il risultato torna dal thread del finto broker. Serve un SEGNALE, non
    # un QTimer.singleShot con una lambda: quello, senza oggetto di
    # contesto, viene consegnato all'event loop del thread chiamante — che
    # per un thread Python normale non esiste, quindi non arriva mai.
    # E' la stessa trappola delle lambda collegate ai segnali dei worker,
    # in un'altra forma: senza ricevente, Qt non sa dove consegnare.
    risultato = Signal(bool)

    def __init__(self, timeout_s: float):
        super().__init__()
        self.setWindowTitle("Metis — prova del dialogo di conferma")
        self.resize(560, 420)
        self.setStyleSheet("QWidget { background: #0f172a; color: #e2e8f0; }")
        self.timeout_s = timeout_s
        self.ponte = PonteConferma(timeout_s=timeout_s)
        self.ponte.richiesta.connect(self._mostra)
        self.ponte.chiusa.connect(self._chiudi)
        self._dialogo: DialogoConferma | None = None
        self.risultato.connect(self._risultato)

        lay = QVBoxLayout(self)
        intro = QLabel(
            "Il broker chiedera' conferma per un'azione T3.\n\n"
            "Prova, in ordine:  INVIO (non deve fare nulla) · SPAZIO (nega) ·\n"
            "ESC (nega) · la X (nega) · non rispondere (scade in rifiuto) ·\n"
            "Approva (l'unica cosa che passa).")
        intro.setStyleSheet("color: #94a3b8;")
        lay.addWidget(intro)

        b = QPushButton("Chiedi conferma")
        b.setStyleSheet("QPushButton { background: #1e293b; padding: 8px;"
                        " border: none; border-radius: 4px; }")
        b.clicked.connect(self._chiedi)
        lay.addWidget(b)

        self.esito = QTextEdit()
        self.esito.setReadOnly(True)
        self.esito.setStyleSheet(
            "background: #0b1220; border: 1px solid #1e293b;"
            " font-family: Consolas, monospace; font-size: 12px;")
        lay.addWidget(self.esito, 1)
        self._scrivi("pronto. Il timeout e' "
                     f"{timeout_s:.0f} s, lo stesso del broker.")

    # Il broker gira su un thread suo anche qui: e' quello che rende la
    # prova fedele. Su un thread solo non si vedrebbe niente di cio' che il
    # ponte serve a risolvere.
    def _chiedi(self) -> None:
        def lavora() -> None:
            self.risultato.emit(self.ponte.chiedi(FintoSpec(), FintaCall()))

        threading.Thread(target=lavora, daemon=True, name="finto-broker").start()
        self._scrivi("il broker sta aspettando...")

    @Slot(str, str, dict, float)
    def _mostra(self, strumento, tier, argomenti, timeout_s) -> None:
        self._dialogo = DialogoConferma(strumento, tier, argomenti, timeout_s,
                                        parent=self)
        self._dialogo.deciso.connect(self.ponte.rispondi)
        self._dialogo.show()

    @Slot()
    def _chiudi(self) -> None:
        if self._dialogo is not None:
            self._dialogo.close()
            self._dialogo = None

    @Slot(bool)
    def _risultato(self, risposta: bool) -> None:
        if risposta:
            self._scrivi("il broker ha ricevuto SI -> l'azione verrebbe "
                         "eseguita, con confirmed=1 nell'audit log")
        else:
            self._scrivi("il broker ha ricevuto NO -> azione rifiutata allo "
                         "stadio 'conferma', nessun effetto")
        self._scrivi(f"   richieste {self.ponte.richieste} · "
                     f"approvate {self.ponte.approvate} · "
                     f"scadute {self.ponte.scadute}")

    def _scrivi(self, riga: str) -> None:
        self.esito.append(riga)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=None,
                    help="secondi prima del rifiuto implicito (default: quello del broker)")
    args = ap.parse_args()

    from metis.security.policies import CONFERMA_TIMEOUT_S

    app = QApplication(sys.argv)
    b = Banco(args.timeout or CONFERMA_TIMEOUT_S)
    b.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
