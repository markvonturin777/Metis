"""La conversazione, in append incrementale.

NON SI RICOSTRUISCE IL DOCUMENTO A OGNI TOKEN
Riscrivere l'intero `QTextEdit` a ogni frase costa, e soprattutto fa saltare
lo scroll: chi sta rileggendo una risposta di due minuti fa se la vede
strappare via. Si accoda al cursore in fondo, e basta.

L'AUTO-SCROLL SI SPEGNE DA SOLO
Se l'utente ha scrollato verso l'alto sta leggendo qualcosa, e trascinarlo
in fondo a ogni frase nuova e' il modo piu' rapido di rendere inutile un
registro. Si riattiva da solo quando torna in fondo.

PERCHE' I COLORI E NON LE ETICHETTE
"Utente:" e "Metis:" ripetuti cinquanta volte occupano spazio e si leggono
male di sfuggita. Il colore si distingue senza leggere.
"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

COLORE_UTENTE = "#93c5fd"
COLORE_METIS = "#e2e8f0"
COLORE_SISTEMA = "#f59e0b"
COLORE_PARZIALE = "#64748b"


class Conversazione(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.testo = QTextEdit(self)
        self.testo.setReadOnly(True)
        self.testo.setStyleSheet(
            "QTextEdit { background: #0f172a; color: #e2e8f0; border: none;"
            " font-size: 14px; padding: 8px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.testo)
        self._riga_parziale = False

    # -- stato dello scroll ------------------------------------------------

    def _in_fondo(self) -> bool:
        barra = self.testo.verticalScrollBar()
        return barra.value() >= barra.maximum() - 4

    def _accoda(self, html: str) -> None:
        seguire = self._in_fondo()
        cur = self.testo.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.insertHtml(html)
        if seguire:
            barra = self.testo.verticalScrollBar()
            barra.setValue(barra.maximum())

    # -- contenuti ---------------------------------------------------------

    @Slot(str, bool)
    def utente(self, testo: str, sospetto: bool = False) -> None:
        self._togli_parziale()
        if not testo.strip():
            return
        nota = "  <i>(trascrizione incerta)</i>" if sospetto else ""
        self._accoda(f'<div style="color:{COLORE_UTENTE}; margin-top:10px;">'
                     f'▸ {_esc(testo)}{nota}</div>')

    @Slot(str)
    def metis(self, testo: str) -> None:
        self._togli_parziale()
        if not testo.strip():
            return
        self._accoda(f'<div style="color:{COLORE_METIS}; margin-left:14px;">'
                     f'{_esc(testo)}</div>')

    @Slot(str)
    def sistema(self, testo: str) -> None:
        """Eventi che non sono parlato: strumenti eseguiti, rifiuti, errori."""
        self._togli_parziale()
        self._accoda(f'<div style="color:{COLORE_SISTEMA}; margin-left:14px;'
                     f' font-size:12px;">· {_esc(testo)}</div>')

    @Slot(str)
    def parziale(self, testo: str) -> None:
        """Riga grigia che mostra "ti sto sentendo", sostituita dal finale.

        Il grigio distingue a colpo d'occhio cio' che Metis crede di aver
        sentito da cio' che ha capito. In M5, quando arrivera' il
        riconoscimento parziale in tempo reale, sara' questa riga a muoversi.
        """
        self._togli_parziale()
        if not testo.strip():
            return
        self._accoda(f'<div style="color:{COLORE_PARZIALE}; font-style:italic;"'
                     f' id="parziale">▸ {_esc(testo)}…</div>')
        self._riga_parziale = True

    def _togli_parziale(self) -> None:
        if not self._riga_parziale:
            return
        cur = self.testo.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.select(QTextCursor.BlockUnderCursor)
        cur.removeSelectedText()
        self._riga_parziale = False

    def pulisci(self) -> None:
        self.testo.clear()
        self._riga_parziale = False

    def contenuto(self) -> str:
        """Serve al passaggio Minimal <-> Fullscreen: le due viste sono due
        proiezioni dello stesso modello, non due applicazioni."""
        return self.testo.toHtml()

    def ripristina(self, html: str) -> None:
        self.testo.setHtml(html)
        barra = self.testo.verticalScrollBar()
        barra.setValue(barra.maximum())


def _esc(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
