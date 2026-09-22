"""L'editor dei comandi custom. Riempie il contenitore predisposto in M3.

COSA RENDE QUESTO EDITOR DIVERSO DA UN BLOCCO NOTE
La validazione contro il registro, al salvataggio. Il pulsante "Salva"
chiede a `memory.commands.valida()` di costruire il comando **con gli stessi
schemi Pydantic che usera' il broker**, e se qualcosa non torna il comando
non entra nel file: resta il messaggio di errore sotto il modulo.

Non e' cortesia verso l'utente. Un comando che invoca uno strumento
inesistente non fallisce quando lo si scrive: fallisce fra tre settimane,
a voce, mentre serve, e in quel momento nessuno ricorda di aver toccato un
JSON. Il criterio di uscita di M4 lo chiede esplicitamente, ed e' uno dei
pochi che si puo' verificare senza microfono.

PERCHE' LE AZIONI SI SCRIVONO IN JSON
Sembra ruvido e invece e' la forma onesta: le azioni *sono* tool call, gli
stessi oggetti che produce il modello, e mostrarle come sono rende
evidente cosa passera' dal broker. Un costruttore a menu nasconderebbe la
cosa che conta — che qui non si scrive uno script, si nominano capacita'
gia' esistenti — e andrebbe riscritto a ogni strumento nuovo.

L'elenco degli strumenti disponibili, con il loro tier, sta sotto il campo:
scrivere JSON a memoria e' un'altra cosa.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from metis.memory.commands import Errore, Libreria

_STILE = """
QDialog, QWidget { background: #0f172a; color: #e2e8f0; }
QLineEdit, QPlainTextEdit, QListWidget {
    background: #0b1220; border: 1px solid #1e293b; border-radius: 4px;
    padding: 6px; selection-background-color: #1d4ed8;
}
QPushButton {
    background: #1e293b; border: none; border-radius: 4px; padding: 7px 14px;
}
QPushButton:hover { background: #334155; }
QPushButton:disabled { color: #475569; }
"""


def _etichetta(testo: str) -> QLabel:
    lab = QLabel(testo)
    lab.setStyleSheet("color: #64748b; font-size: 11px; letter-spacing: 1px;")
    return lab


class EditorComandi(QDialog):
    """Aggiunta, modifica ed eliminazione. Un comando alla volta."""

    cambiato = Signal()

    def __init__(self, libreria: Libreria, parent=None):
        super().__init__(parent)
        self.libreria = libreria
        self.setWindowTitle("Metis — comandi rapidi")
        self.resize(860, 540)
        self.setStyleSheet(_STILE)
        self._id_corrente: str | None = None

        radice = QHBoxLayout(self)
        radice.addWidget(self._colonna_elenco(), 1)
        radice.addWidget(self._colonna_modulo(), 2)
        self._ricarica_elenco()

    # -- costruzione -------------------------------------------------------

    def _colonna_elenco(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_etichetta("COMANDI"))

        self.elenco = QListWidget()
        self.elenco.currentItemChanged.connect(self._seleziona)
        lay.addWidget(self.elenco, 1)

        riga = QHBoxLayout()
        nuovo = QPushButton("Nuovo")
        nuovo.clicked.connect(self._nuovo)
        riga.addWidget(nuovo)
        self.bottone_elimina = QPushButton("Elimina")
        self.bottone_elimina.clicked.connect(self._elimina)
        riga.addWidget(self.bottone_elimina)
        lay.addLayout(riga)

        self.avvisi = QLabel("")
        self.avvisi.setWordWrap(True)
        self.avvisi.setStyleSheet("color: #f59e0b; font-size: 11px;")
        lay.addWidget(self.avvisi)
        return box

    def _colonna_modulo(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)

        lay.addWidget(_etichetta("IDENTIFICATIVO"))
        self.campo_id = QLineEdit()
        self.campo_id.setPlaceholderText("inizia_lavoro")
        lay.addWidget(self.campo_id)

        lay.addWidget(_etichetta("FRASI CHE LO ATTIVANO — UNA PER RIGA"))
        self.campo_frasi = QPlainTextEdit()
        self.campo_frasi.setPlaceholderText("inizia a lavorare\nsi comincia")
        self.campo_frasi.setMaximumHeight(90)
        lay.addWidget(self.campo_frasi)

        lay.addWidget(_etichetta("AZIONI — TOOL CALL IN JSON, IN ORDINE"))
        self.campo_azioni = QPlainTextEdit()
        self.campo_azioni.setPlaceholderText(
            '[{"tool": "open_application", "app": "vscode"}]')
        self.campo_azioni.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(self.campo_azioni, 1)

        self.strumenti = QLabel("")
        self.strumenti.setWordWrap(True)
        self.strumenti.setStyleSheet("color: #475569; font-size: 10px;"
                                     " font-family: Consolas, monospace;")
        self.strumenti.setText("disponibili · " + " · ".join(
            f"{s.name} ({s.tier.value})"
            for s in sorted(self.libreria.registry.disponibili(),
                            key=lambda x: (x.tier.value, x.name))))
        lay.addWidget(self.strumenti)

        lay.addWidget(_etichetta("RISPOSTA PARLATA — FACOLTATIVA"))
        self.campo_risposta = QLineEdit()
        self.campo_risposta.setPlaceholderText(
            "vuoto = Metis descrive da solo cosa ha fatto")
        lay.addWidget(self.campo_risposta)

        self.esito = QLabel("")
        self.esito.setWordWrap(True)
        self.esito.setStyleSheet("color: #ef4444; font-size: 12px;")
        lay.addWidget(self.esito)

        riga = QHBoxLayout()
        riga.addStretch(1)
        chiudi = QPushButton("Chiudi")
        chiudi.clicked.connect(self.accept)
        riga.addWidget(chiudi)
        self.bottone_salva = QPushButton("Salva")
        self.bottone_salva.setDefault(True)
        self.bottone_salva.clicked.connect(self._salva)
        riga.addWidget(self.bottone_salva)
        lay.addLayout(riga)
        return box

    # -- elenco ------------------------------------------------------------

    def _ricarica_elenco(self) -> None:
        self.elenco.blockSignals(True)
        self.elenco.clear()
        for c in self.libreria:
            voce = QListWidgetItem(f"{c.id}   ·   {len(c.azioni)} az.")
            voce.setData(Qt.UserRole, c.id)
            voce.setToolTip("\n".join(c.frasi))
            self.elenco.addItem(voce)
        self.elenco.blockSignals(False)
        self.avvisi.setText("\n".join(self.libreria.avvisi))
        self.bottone_elimina.setEnabled(self._id_corrente is not None)

    def _seleziona(self, voce: QListWidgetItem | None, _prima=None) -> None:
        if voce is None:
            return
        c = self.libreria.get(voce.data(Qt.UserRole))
        if c is None:
            return
        self._id_corrente = c.id
        self.campo_id.setText(c.id)
        self.campo_frasi.setPlainText("\n".join(c.frasi))
        self.campo_azioni.setPlainText(
            json.dumps([dict(a) for a in c.azioni], ensure_ascii=False, indent=2))
        self.campo_risposta.setText(c.risposta or "")
        self.esito.setText("")
        self.bottone_elimina.setEnabled(True)

    def _nuovo(self) -> None:
        self._id_corrente = None
        self.elenco.setCurrentItem(None)
        self.campo_id.clear()
        self.campo_frasi.clear()
        self.campo_azioni.setPlainText("[]")
        self.campo_risposta.clear()
        self.esito.setText("")
        self.bottone_elimina.setEnabled(False)
        self.campo_id.setFocus()

    # -- modifiche ---------------------------------------------------------

    def _dal_modulo(self) -> dict:
        testo = self.campo_azioni.toPlainText().strip() or "[]"
        try:
            azioni = json.loads(testo)
        except ValueError as exc:
            raise Errore(f"le azioni non sono JSON valido: {exc}") from exc
        if isinstance(azioni, dict):
            # Un'azione sola scritta senza parentesi quadre e' un errore cosi'
            # frequente, e cosi' privo di ambiguita', da non meritare un
            # rifiuto: si accetta e si continua.
            azioni = [azioni]
        return {
            "id": self.campo_id.text().strip(),
            "frasi": [r.strip() for r in
                      self.campo_frasi.toPlainText().splitlines() if r.strip()],
            "azioni": azioni,
            "risposta": self.campo_risposta.text().strip(),
        }

    def _salva(self) -> None:
        try:
            dato = self._dal_modulo()
            if self._id_corrente is None:
                c = self.libreria.aggiungi(dato)
            else:
                c = self.libreria.modifica(self._id_corrente, dato)
        except Errore as exc:
            self.esito.setStyleSheet("color: #ef4444; font-size: 12px;")
            self.esito.setText(str(exc))
            return
        self._id_corrente = c.id
        self.esito.setStyleSheet("color: #22c55e; font-size: 12px;")
        self.esito.setText(f"Salvato. '{c.id}' vale da adesso, "
                           "senza riavviare.")
        self._ricarica_elenco()
        self.cambiato.emit()

    def _elimina(self) -> None:
        if self._id_corrente is None:
            return
        conferma = QMessageBox.question(
            self, "Eliminare il comando?",
            f"'{self._id_corrente}' sparisce dal file. Si puo' riscrivere.")
        if conferma is not QMessageBox.Yes:
            return
        try:
            self.libreria.elimina(self._id_corrente)
        except Errore as exc:
            self.esito.setText(str(exc))
            return
        self._nuovo()
        self._ricarica_elenco()
        self.cambiato.emit()


class PannelloComandi(QWidget):
    """Il riquadro nella control room: elenco compatto e un pulsante."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.libreria: Libreria | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.elenco = QLabel("—")
        self.elenco.setWordWrap(True)
        self.elenco.setStyleSheet("color: #64748b; font-size: 11px;"
                                  " font-family: Consolas, monospace;")
        lay.addWidget(self.elenco)

        self.bottone = QPushButton("Modifica comandi…")
        self.bottone.setEnabled(False)
        self.bottone.setStyleSheet(
            "QPushButton { background: #1e293b; border: none;"
            " border-radius: 4px; padding: 6px; font-size: 11px; }"
            "QPushButton:disabled { color: #475569; }")
        self.bottone.clicked.connect(self._apri)
        lay.addWidget(self.bottone)

    def collega(self, libreria: Libreria | None) -> None:
        """La libreria arriva a sistema costruito, cioe' dopo il montaggio
        dell'interfaccia: finche' non c'e', il pulsante resta spento invece
        di aprire un editor vuoto."""
        self.libreria = libreria
        self.bottone.setEnabled(libreria is not None)
        self.aggiorna()

    def aggiorna(self) -> None:
        if self.libreria is None or not len(self.libreria):
            self.elenco.setText("—")
            return
        righe = [f"{c.id:<16} {' · '.join(c.frasi[:2])}"[:64]
                 for c in list(self.libreria)[:8]]
        resto = len(self.libreria) - len(righe)
        if resto > 0:
            righe.append(f"… e altri {resto}")
        self.elenco.setText("\n".join(righe))

    def _apri(self) -> None:
        if self.libreria is None:
            return
        editor = EditorComandi(self.libreria, parent=self)
        editor.cambiato.connect(self.aggiorna)
        editor.exec()
        self.aggiorna()
