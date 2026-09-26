"""La conversazione come dati. Le viste la disegnano, questo la tiene.

PERCHE' UN MODELLO, DA PHASE1
In M3 la conversazione era un widget, e le viste se lo passavano: una sola
vista la mostrava. Con PHASE1 la mostrano in due, e in due modi — a fumetti
nell'Hub, come registro nella Diagnostica — e un widget Qt sta in una sola
finestra alla volta. Il principio di M3 resta ("le viste non ricopiano
niente"): i dati stanno qui una volta, e ogni vista si iscrive ai segnali.

LE FRASI DI UN TURNO SONO UN FUMETTO SOLO
Metis parla per frasi, e ogni frase arriva con il segnale `dice` mentre la
si sintetizza. Il registro le mostrava una per riga; i fumetti le riuniscono
finche' il turno non si chiude (`chiudi_turno`, alla fine delle metriche) o
non parla qualcun altro.

UN TETTO, PERCHE' METIS RESTA ACCESO PER GIORNI
Oltre `MASSIMO` messaggi si tolgono i piu' vecchi. Il soak di 72 ore non
deve trovare una lista che cresce: e' la memoria della GUI, non quella di
Metis, che ha il suo riassunto.

Questo modulo non importa `QtWidgets`: vive sul thread principale ma non e'
interfaccia, ed e' provato senza finestre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, Signal

MASSIMO = 2000
TOGLI = 200               # quanti se ne tolgono quando si supera il tetto

UTENTE, METIS, SISTEMA = "utente", "metis", "sistema"


@dataclass
class Messaggio:
    ruolo: str
    testo: str
    ora: datetime = field(default_factory=datetime.now)
    sospetto: bool = False          # trascrizione incerta
    scritto: bool = False           # arrivato dalla tastiera, non dal microfono
    aperto: bool = False            # un turno di Metis ancora in corso


class ModelloConversazione(QObject):
    aggiunto = Signal(int)          # indice del messaggio nuovo
    aggiornato = Signal(int)        # indice del messaggio cambiato (frase aggiunta)
    troncato = Signal(int)          # quanti messaggi vecchi sono stati tolti
    azzerato = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messaggi: list[Messaggio] = []

    # -- lettura -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._messaggi)

    def __getitem__(self, i: int) -> Messaggio:
        return self._messaggi[i]

    @property
    def messaggi(self) -> list[Messaggio]:
        return list(self._messaggi)

    # -- scrittura ---------------------------------------------------------

    def utente(self, testo: str, sospetto: bool = False, scritto: bool = False) -> None:
        self.chiudi_turno()
        if testo.strip():
            self._aggiungi(Messaggio(UTENTE, testo.strip(), sospetto=sospetto, scritto=scritto))

    def metis(self, testo: str) -> None:
        """Una frase. Si unisce al fumetto aperto, se c'e'."""
        testo = testo.strip()
        if not testo:
            return
        if self._messaggi and self._messaggi[-1].ruolo == METIS and self._messaggi[-1].aperto:
            ultimo = self._messaggi[-1]
            ultimo.testo = f"{ultimo.testo} {testo}"
            self.aggiornato.emit(len(self._messaggi) - 1)
            return
        self._aggiungi(Messaggio(METIS, testo, aperto=True))

    def sistema(self, testo: str) -> None:
        """Eventi che non sono parlato: strumenti eseguiti, rifiuti, errori."""
        if testo.strip():
            self._aggiungi(Messaggio(SISTEMA, testo.strip()))

    def chiudi_turno(self) -> None:
        if self._messaggi and self._messaggi[-1].aperto:
            self._messaggi[-1].aperto = False

    def azzera(self) -> None:
        self._messaggi.clear()
        self.azzerato.emit()

    def _aggiungi(self, m: Messaggio) -> None:
        if len(self._messaggi) >= MASSIMO:
            del self._messaggi[:TOGLI]
            self.troncato.emit(TOGLI)
        self._messaggi.append(m)
        self.aggiunto.emit(len(self._messaggi) - 1)

    # -- esporta -----------------------------------------------------------

    def markdown(self, titolo: str = "Conversazione con Metis") -> str:
        """Il testo di "Esporta": Markdown, con gli orari.

        Scrive l'utente, con il suo clic, in un file che sceglie lui. Non e'
        una capacita' di Metis e non contraddice il divieto di accesso al file
        system (specifica §1.2), che riguarda cio' che Metis puo' fare.
        """
        if not self._messaggi:
            return f"# {titolo}\n\n_Nessun messaggio._\n"
        giorno = self._messaggi[0].ora.strftime("%d/%m/%Y")
        righe = [f"# {titolo}", "", f"_{giorno}_", ""]
        for m in self._messaggi:
            ora = m.ora.strftime("%H:%M")
            if m.ruolo == SISTEMA:
                righe.append(f"> {ora} · {m.testo}")
            else:
                chi = "Tu" if m.ruolo == UTENTE else "Metis"
                note = []
                if m.scritto:
                    note.append("scritto")
                if m.sospetto:
                    note.append("trascrizione incerta")
                coda = f" _({', '.join(note)})_" if note else ""
                righe.append(f"**{chi}** · {ora}{coda}  ")
                righe.append(m.testo)
            righe.append("")
        return "\n".join(righe)
