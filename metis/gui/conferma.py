"""Conferma T3 fra due thread: il broker chiede, l'utente risponde.

IL PROBLEMA
Il broker gira sul thread del nucleo e deve sapere se puo' procedere. La
risposta la da' una persona, che clicca su un thread diverso — quello della
GUI. Il worker non puo' aprire un dialogo (i widget si toccano solo dal
thread principale) e non puo' nemmeno restare a girare a vuoto aspettando.

LA SOLUZIONE, E IL SUO INSIDIO
`QWaitCondition` con timeout. L'insidio e' il **risveglio perduto**: se
l'utente e' fulmineo e risponde fra l'emit del segnale e l'inizio
dell'attesa, il `wakeAll` arriva quando nessuno sta ancora aspettando, e il
worker si mette in attesa di qualcosa che e' gia' successo — cioe' si blocca
per tutto il timeout su un'azione gia' approvata.

Da qui il flag `_risposto`, controllato sotto mutex prima di attendere. E'
il motivo per cui l'emit avviene FUORI dal lock e l'attesa dentro.

IL TIMEOUT E' UN RIFIUTO, E VALE PER TUTTI
Vent'anni di finestre di dialogo hanno insegnato a premere Invio prima di
leggere. Qui il tempo che scade significa no, e il valore e' lo stesso del
broker, letto dalla stessa costante: due timeout diversi vorrebbero dire che
uno dei due aspetta l'altro.
"""

from __future__ import annotations

from PySide6.QtCore import QMutex, QObject, QWaitCondition, Signal, Slot

from metis.security.policies import CONFERMA_TIMEOUT_S


class PonteConferma(QObject):
    """Vive sul thread della GUI, viene interrogato da quello del nucleo."""

    # (nome strumento, livello, argomenti, secondi di timeout)
    richiesta = Signal(str, str, dict, float)
    chiusa = Signal()               # il dialogo puo' sparire

    def __init__(self, timeout_s: float = CONFERMA_TIMEOUT_S, parent=None):
        super().__init__(parent)
        self.timeout_s = timeout_s
        self._mutex = QMutex()
        self._attesa = QWaitCondition()
        self._decisione = False
        self._risposto = False
        self.richieste = 0
        self.approvate = 0
        self.scadute = 0

    # -- lato nucleo (thread del worker) -----------------------------------

    def chiedi(self, spec, call) -> bool:
        """Blocca il thread chiamante finche' l'utente decide o scade.

        E' la funzione che si passa a `Context.chiedi_conferma`. Ritorna
        True solo su un sì esplicito arrivato in tempo.
        """
        self._mutex.lock()
        self._decisione = False
        self._risposto = False
        self.richieste += 1
        self._mutex.unlock()

        # Fuori dal lock: con una connessione in coda l'emit ritorna subito,
        # ma se un giorno qualcuno chiamasse `chiedi` dal thread della GUI la
        # connessione sarebbe diretta e lo slot girerebbe qui dentro. Con il
        # mutex preso sarebbe un blocco permanente.
        self.richiesta.emit(spec.name, spec.tier.value, call.model_dump(),
                            self.timeout_s)

        self._mutex.lock()
        try:
            if not self._risposto:
                self._attesa.wait(self._mutex, int(self.timeout_s * 1000))
            if not self._risposto:
                self.scadute += 1
                return False
            if self._decisione:
                self.approvate += 1
            return self._decisione
        finally:
            self._mutex.unlock()
            self.chiusa.emit()

    # -- lato GUI (thread principale) --------------------------------------

    @Slot(bool)
    def rispondi(self, approvato: bool) -> None:
        """La decisione dell'utente. Chiamata dal thread della GUI."""
        self._mutex.lock()
        self._decisione = bool(approvato)
        self._risposto = True
        self._attesa.wakeAll()
        self._mutex.unlock()

    @Slot()
    def annulla(self) -> None:
        """Alla chiusura: chi sta aspettando riceve un no e puo' uscire.

        Senza, spegnere Metis mentre c'e' una conferma aperta lascerebbe il
        thread del nucleo fermo per venti secondi e la finestra non si
        chiuderebbe.
        """
        self.rispondi(False)
