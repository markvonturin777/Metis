"""La conversazione come registro: la vista della Diagnostica.

PHASE1: I DATI STANNO NEL MODELLO
Questo widget non tiene piu' la conversazione: la disegna da
`metis/gui/modello_conversazione.py`, come fanno i fumetti dell'Hub. I
metodi `utente`, `metis`, `sistema` restano, e scrivono nel modello: chi li
chiamava continua a farlo, e l'altra vista se ne accorge da sola.

NON SI RICOSTRUISCE IL DOCUMENTO A OGNI TOKEN
Riscrivere l'intero `QTextEdit` a ogni frase costa, e soprattutto fa saltare
lo scroll: chi sta rileggendo una risposta di due minuti fa se la vede
strappare via. Si accoda al cursore in fondo, e basta. Per questo il
registro tiene il conto di quanto di ogni messaggio ha gia' mostrato: una
frase nuova di Metis diventa una riga nuova, come prima.

L'AUTO-SCROLL SI SPEGNE DA SOLO
Se l'utente ha scrollato verso l'alto sta leggendo qualcosa, e trascinarlo
in fondo a ogni frase nuova e' il modo piu' rapido di rendere inutile un
registro. Si riattiva da solo quando torna in fondo.

UNA RIGA E' UN PARAGRAFO VERO (PHASE1)
Da M3 ogni riga era un `<div>` inserito con `insertHtml`, e Qt fonde il
primo blocco di un frammento con il paragrafo in cui cade il cursore: tutta
la conversazione finiva in un paragrafo solo, un messaggio attaccato
all'altro. E `_togli_parziale`, che cancella l'ultimo paragrafo, avrebbe
cancellato tutto. Ora ogni riga apre il suo blocco, con i margini nel
formato del blocco e il colore nel testo.

PERCHE' I COLORI E NON LE ETICHETTE
"Utente:" e "Metis:" ripetuti cinquanta volte occupano spazio e si leggono
male di sfuggita. Il colore si distingue senza leggere.
"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtGui import QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from metis.gui import tema
from metis.gui.modello_conversazione import METIS, SISTEMA, UTENTE, ModelloConversazione

COLORE_UTENTE = tema.ACCENTO
COLORE_METIS = tema.TESTO
COLORE_SISTEMA = tema.ATTENZIONE
COLORE_PARZIALE = tema.TESTO_SECONDARIO


class Conversazione(QWidget):
    def __init__(self, modello: ModelloConversazione | None = None, parent=None):
        super().__init__(parent)
        self.modello = modello if modello is not None else ModelloConversazione(self)
        self.testo = QTextEdit(self)
        self.testo.setReadOnly(True)
        self.testo.setStyleSheet(
            f"QTextEdit {{ background: {tema.PANNELLO}; color: {tema.TESTO}; border: none;"
            " font-size: 14px; padding: 8px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.testo)
        self._riga_parziale = False
        # Quanto di ogni messaggio e' gia' nel registro, per id dell'oggetto:
        # gli indici scorrono quando il modello toglie i messaggi vecchi.
        self._mostrato: dict[int, int] = {}

        self.modello.aggiunto.connect(self._nuovo)
        self.modello.aggiornato.connect(self._mostra)
        self.modello.troncato.connect(self._potato)
        self.modello.azzerato.connect(self._azzerato)
        # Quello che il modello ha gia', come fanno i fumetti: due viste dello
        # stesso modello non possono raccontare due storie diverse.
        for i in range(len(self.modello)):
            self._nuovo(i)

    # -- scrittura: passa dal modello ------------------------------------------

    @Slot(str, bool)
    def utente(self, testo: str, sospetto: bool = False) -> None:
        self._togli_parziale()
        self.modello.utente(testo, sospetto)

    @Slot(str)
    def metis(self, testo: str) -> None:
        self._togli_parziale()
        self.modello.metis(testo)

    @Slot(str)
    def sistema(self, testo: str) -> None:
        """Eventi che non sono parlato: strumenti eseguiti, rifiuti, errori."""
        self._togli_parziale()
        self.modello.sistema(testo)

    # -- disegno: dal modello --------------------------------------------------

    @Slot(int)
    def _nuovo(self, indice: int) -> None:
        # Un messaggio nuovo parte da zero anche se Python ha riusato l'id di
        # uno gia' potato: altrimenti se ne perderebbe l'inizio.
        self._mostrato[id(self.modello[indice])] = 0
        self._mostra(indice)

    @Slot(int)
    def _potato(self, _quanti: int) -> None:
        vivi = {id(m) for m in self.modello.messaggi}
        self._mostrato = {k: v for k, v in self._mostrato.items() if k in vivi}

    @Slot(int)
    def _mostra(self, indice: int) -> None:
        m = self.modello[indice]
        gia = self._mostrato.get(id(m), 0)
        nuovo = m.testo[gia:].strip()
        self._mostrato[id(m)] = len(m.testo)
        if not nuovo:
            return
        self._togli_parziale()
        if m.ruolo == UTENTE:
            nota = "  <i>(trascrizione incerta)</i>" if m.sospetto else ""
            nota += "  <i>(scritto)</i>" if m.scritto else ""
            self._accoda(f'<span style="color:{COLORE_UTENTE};">'
                         f'▸ {_esc(nuovo)}{nota}</span>', sopra=10)
        elif m.ruolo == METIS:
            self._accoda(f'<span style="color:{COLORE_METIS};">{_esc(nuovo)}</span>',
                         sinistra=14)
        elif m.ruolo == SISTEMA:
            self._accoda(f'<span style="color:{COLORE_SISTEMA}; font-size:12px;">'
                         f'· {_esc(nuovo)}</span>', sinistra=14)

    @Slot()
    def _azzerato(self) -> None:
        self.testo.clear()
        self._mostrato.clear()
        self._riga_parziale = False

    # -- stato dello scroll ------------------------------------------------

    def _in_fondo(self) -> bool:
        barra = self.testo.verticalScrollBar()
        return barra.value() >= barra.maximum() - 4

    def _accoda(self, html: str, sinistra: int = 0, sopra: int = 0) -> None:
        """Una riga: un blocco nuovo, poi il testo dentro."""
        seguire = self._in_fondo()
        cur = self.testo.textCursor()
        cur.movePosition(QTextCursor.End)
        blocco = QTextBlockFormat()
        blocco.setLeftMargin(sinistra)
        blocco.setTopMargin(sopra)
        if self.testo.document().isEmpty():
            cur.setBlockFormat(blocco)
        else:
            cur.insertBlock(blocco, QTextCharFormat())
        cur.insertHtml(html)
        if seguire:
            barra = self.testo.verticalScrollBar()
            barra.setValue(barra.maximum())

    # -- la riga provvisoria -------------------------------------------------

    @Slot(str)
    def parziale(self, testo: str) -> None:
        """Riga grigia che mostra "ti sto sentendo", sostituita dal finale.

        Sta solo nel registro e non nel modello: non e' un messaggio, e
        l'esportazione non deve contenerla.
        """
        self._togli_parziale()
        if not testo.strip():
            return
        self._accoda(f'<span style="color:{COLORE_PARZIALE}; font-style:italic;">'
                     f'▸ {_esc(testo)}…</span>')
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
        self.modello.azzera()

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
