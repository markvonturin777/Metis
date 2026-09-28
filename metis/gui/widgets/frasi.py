"""Il pannello delle frasi non capite, nella Diagnostica (PHASE4).

    FRASI NON CAPITE
    3 frasi da rivedere · 7% dei turni non capiti, ultimi 30 giorni
    ×4 mastra in numeria
    ×2 clicca su ottanto uno
    [ Rivedi le frasi… ]

Il dialogo le mostra una per una, con quattro azioni (D-FRASI 5):

- **Crea comando** apre l'editor dei comandi con la frase gia' scritta e, se
  c'e', lo strumento che il modello aveva proposto — senza argomenti;
- **Variante di…** aggiunge la frase a un comando esistente;
- **Segnala** la mette fra quelle da passare a chi sviluppa;
- **Ignora** la toglie dal pannello.

Le frasi con un parametro (un numero, una quantita', un testo) non possono
diventare comandi: per loro ci sono solo *Segnala* e *Ignora*.

Decide sempre l'utente. Questo pannello non aggiunge niente da solo, e ogni
frase nuova passa dalle guardie di `commands.controlla_frasi`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from metis.gui import tema
from metis.gui.testo import per_etichetta
from metis.memory import frasi
from metis.memory.commands import Errore, Libreria, normalizza

_STILE = f"""
QListWidget {{
    background: {tema.SFONDO_ALTO}; border: 1px solid {tema.BORDO};
    border-radius: {tema.RAGGIO_PICCOLO}px; padding: 6px;
    selection-background-color: {tema.ACCENTO_SCURO};
}}
QListWidget::item {{ padding: 6px 4px; }}
"""
_MONO = f"font-family: '{tema.FONT_NUMERI}';"
ANTEPRIMA = 3


def riepilogo(r: frasi.Raccolta) -> str:
    """La riga del pannello: quante frasi, e la misura dell'attrito."""
    if not r.turni:
        return "Nessun turno negli ultimi 30 giorni."
    n = len(r.da_rivedere)
    quante = ("Nessuna frase da rivedere" if n == 0 else
              "1 frase da rivedere" if n == 1 else f"{n} frasi da rivedere")
    return f"{quante} · {r.quota:.0%} dei turni non capiti, ultimi 30 giorni"


def voce(g: frasi.Gruppo, ora: float | None = None) -> str:
    """Una riga del dialogo."""
    return (f"×{g.volte}   «{g.frase}»   —   {frasi.motivo_in_parole(g.motivo)}"
            f"   ·   {frasi.quando_in_parole(g.ultima, ora)}")


def _conosciuta(libreria: Libreria, frase: str) -> bool:
    detto = normalizza(frase)
    return any(detto in c.normalizzate for c in libreria)


class DialogoFrasi(QDialog):
    """Le frasi da rivedere, una alla volta, con le quattro azioni."""

    deciso = Signal()        # una frase ha cambiato stato: il pannello va riletto

    def __init__(self, raccolta: frasi.Raccolta, libreria: Libreria | None,
                 decise: Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metis — frasi non capite")
        self.resize(820, 480)
        self.setStyleSheet(_STILE)
        self.libreria = libreria
        self.decise = decise
        self.gruppi = list(raccolta.da_rivedere)
        self.segnalate = list(raccolta.segnalate)

        # I dialoghi di sistema, sostituibili dai test.
        self.scegli_comando = self._scegli_comando
        self.scegli_file = self._scegli_file
        self.apri_editor = self._apri_editor

        radice = QVBoxLayout(self)
        self.riga = QLabel(riepilogo(raccolta))
        self.riga.setStyleSheet(f"color: {tema.TESTO_SECONDARIO};")
        radice.addWidget(self.riga)

        self.elenco = QListWidget()
        self.elenco.currentRowChanged.connect(self._aggiorna_pulsanti)
        radice.addWidget(self.elenco, 1)

        self.nota = QLabel("")
        self.nota.setWordWrap(True)
        self.nota.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; font-size: 11px;")
        radice.addWidget(self.nota)

        self.esito = QLabel("")
        self.esito.setWordWrap(True)
        radice.addWidget(self.esito)

        azioni = QHBoxLayout()
        self.b_crea = QPushButton("Crea comando…")
        self.b_variante = QPushButton("Variante di…")
        self.b_segnala = QPushButton("Segnala")
        self.b_ignora = QPushButton("Ignora")
        for b, fa in ((self.b_crea, self._crea), (self.b_variante, self._variante),
                      (self.b_segnala, self._segnala), (self.b_ignora, self._ignora)):
            b.clicked.connect(fa)
            azioni.addWidget(b)
        azioni.addStretch(1)
        self.b_esporta = QPushButton("Esporta segnalate…")
        self.b_esporta.clicked.connect(self._esporta)
        azioni.addWidget(self.b_esporta)
        chiudi = QPushButton("Chiudi")
        chiudi.clicked.connect(self.accept)
        azioni.addWidget(chiudi)
        radice.addLayout(azioni)

        self._riempi()

    # -- elenco --------------------------------------------------------------

    def _riempi(self) -> None:
        self.elenco.blockSignals(True)
        self.elenco.clear()
        for g in self.gruppi:
            it = QListWidgetItem(per_etichetta(voce(g)))
            if g.debole:
                it.setForeground(tema.con_alfa(tema.TESTO_SECONDARIO, 1.0))
            self.elenco.addItem(it)
        self.elenco.blockSignals(False)
        if self.gruppi:
            self.elenco.setCurrentRow(0)
        self._aggiorna_pulsanti()

    def corrente(self) -> frasi.Gruppo | None:
        i = self.elenco.currentRow()
        return self.gruppi[i] if 0 <= i < len(self.gruppi) else None

    def _aggiorna_pulsanti(self, *_) -> None:
        g = self.corrente()
        c_e = g is not None
        comandabile = c_e and not g.parametrica and self.libreria is not None
        self.b_crea.setEnabled(comandabile)
        self.b_variante.setEnabled(comandabile and len(self.libreria) > 0)
        self.b_segnala.setEnabled(c_e)
        self.b_ignora.setEnabled(c_e)
        self.b_esporta.setEnabled(bool(self.segnalate))
        if not c_e:
            self.nota.setText("")
        elif g.parametrica:
            self.nota.setText("Questa frase chiede un numero, una quantità o un testo: "
                              "un comando ha azioni fisse e non la può coprire. "
                              "Si segnala, e la si aggiunge alle frasi fisse di Metis.")
        elif g.debole:
            self.nota.setText("Detta due volte di fila dopo una risposta a parole: forse "
                              "la prima volta Metis non ha fatto quello che si voleva.")
        else:
            self.nota.setText("")

    def _esito(self, testo: str, colore: str) -> None:
        self.esito.setStyleSheet(f"color: {colore}; font-size: 12px;")
        self.esito.setText(testo)

    def _decidi(self, g: frasi.Gruppo, stato: str) -> None:
        """Registra, toglie dall'elenco, avvisa chi deve rileggere."""
        frasi.decidi(g.chiave, stato, g.frase, path=self.decise)
        i = self.gruppi.index(g)
        self.gruppi.pop(i)
        if stato == frasi.SEGNALATA:
            self.segnalate.append(g)
        self._riempi()
        if self.gruppi:
            self.elenco.setCurrentRow(min(i, len(self.gruppi) - 1))
        self.deciso.emit()

    # -- le quattro azioni ---------------------------------------------------

    def _crea(self) -> None:
        g = self.corrente()
        if g is None or g.parametrica or self.libreria is None:
            return
        self.apri_editor(g.frase, g.tolta)
        if _conosciuta(self.libreria, g.frase):
            self._decidi(g, frasi.RISOLTA)
            self._esito(f"«{g.frase}» è diventata un comando: vale da adesso.", tema.OK)

    def _variante(self) -> None:
        g = self.corrente()
        if g is None or g.parametrica or self.libreria is None:
            return
        ident = self.scegli_comando([c.id for c in self.libreria])
        if not ident:
            return
        try:
            self.libreria.aggiungi_frase(ident, g.frase)
        except Errore as exc:
            self._esito(str(exc), tema.ERRORE)
            return
        self._decidi(g, frasi.RISOLTA)
        self._esito(f"«{g.frase}» ora attiva '{ident}'.", tema.OK)

    def _segnala(self) -> None:
        g = self.corrente()
        if g is not None:
            self._decidi(g, frasi.SEGNALATA)
            self._esito(f"«{g.frase}» segnalata.", tema.TESTO_SECONDARIO)

    def _ignora(self) -> None:
        g = self.corrente()
        if g is not None:
            self._decidi(g, frasi.IGNORATA)
            self._esito("", tema.TESTO_SECONDARIO)

    def _esporta(self) -> None:
        """Scrive l'utente, con il suo clic, in un file che sceglie lui: come
        "Esporta" di PHASE1, non contraddice §1.2 della specifica."""
        if not self.segnalate:
            return
        percorso = self.scegli_file()
        if not percorso:
            return
        try:
            Path(percorso).write_text(frasi.markdown_segnalate(self.segnalate),
                                      encoding="utf-8")
        except OSError as exc:
            self._esito(f"Non riesco a scrivere il file: {exc.strerror or exc}", tema.ERRORE)
            return
        self._esito(f"{len(self.segnalate)} frasi esportate.", tema.OK)

    # -- i dialoghi di sistema -----------------------------------------------

    def _scegli_comando(self, ids: list[str]) -> str | None:
        ident, ok = QInputDialog.getItem(self, "Variante di…",
                                         "A quale comando aggiungere la frase?", ids, 0, False)
        return ident if ok else None

    def _scegli_file(self) -> str | None:
        percorso, _ = QFileDialog.getSaveFileName(
            self, "Esporta le frasi segnalate", "frasi_segnalate.md", "Markdown (*.md)")
        return percorso or None

    def _apri_editor(self, frase: str, suggerito: str | None) -> None:
        from metis.gui.widgets.comandi import EditorComandi

        editor = EditorComandi(self.libreria, parent=self)
        editor.nuovo_da_frase(frase, suggerito)
        editor.exec()


class PannelloFrasi(QWidget):
    """Il riquadro nella Diagnostica: riepilogo, anteprima e un pulsante."""

    deciso = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.libreria: Libreria | None = None
        self.raccolta = frasi.Raccolta()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.riga = QLabel("—")
        self.riga.setWordWrap(True)
        self.riga.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; font-size: 11px;")
        lay.addWidget(self.riga)

        self.anteprima = QLabel("")
        self.anteprima.setWordWrap(True)
        self.anteprima.setStyleSheet(f"color: {tema.TESTO_SECONDARIO}; font-size: 11px; {_MONO}")
        lay.addWidget(self.anteprima)

        self.bottone = QPushButton("Rivedi le frasi…")
        self.bottone.setEnabled(False)
        self.bottone.setStyleSheet("QPushButton { padding: 6px; font-size: 11px; }")
        self.bottone.clicked.connect(self.apri)
        lay.addWidget(self.bottone)

    def collega(self, libreria: Libreria | None) -> None:
        """Serve per *Crea* e *Variante*; *Segnala* e *Ignora* ne fanno a meno."""
        self.libreria = libreria
        self.aggiorna(self.raccolta)

    def aggiorna(self, raccolta: frasi.Raccolta) -> None:
        self.raccolta = raccolta
        self.riga.setText(riepilogo(raccolta))
        righe = [f"×{g.volte} {g.frase}"[:60] for g in raccolta.da_rivedere[:ANTEPRIMA]]
        resto = len(raccolta.da_rivedere) - len(righe)
        if resto > 0:
            righe.append(f"… e altre {resto}")
        self.anteprima.setText(per_etichetta("\n".join(righe)))
        self.bottone.setEnabled(bool(raccolta.da_rivedere or raccolta.segnalate))

    def apri(self) -> None:
        dialogo = DialogoFrasi(self.raccolta, self.libreria, parent=self)
        dialogo.deciso.connect(self.deciso)
        dialogo.exec()
