"""Metis con interfaccia grafica.

    python -m metis.gui.app
    python -m metis.gui.app --fullscreen --no-tools

TOPOLOGIA

    thread principale     QApplication, tutti i widget, il misuratore di lag
    thread "nucleo"       audio, macchina a stati, STT, LLM, broker
    thread "telemetria"   psutil 2 Hz, NVML 1 Hz

L'unico flusso che torna indietro e' la conferma T3, e passa dal
`PonteConferma`. Tutto il resto va in una direzione sola: il nucleo emette,
l'interfaccia disegna.

LE VISTE NON SI DISTRUGGONO, SI NASCONDONO
Il criterio di uscita chiede che il passaggio Minimal <-> Fullscreen non
perda stato. Il modo per garantirlo non e' ricopiare i dati da una parte
all'altra — quello e' il modo per dimenticarne un pezzo — ma non distruggere
niente: i widget della conversazione e del cruscotto sono gli stessi
oggetti, e le due finestre sono due contenitori che si alternano.

LE SCORCIATOIE GLOBALI ARRIVANO DA UN TERZO THREAD
`pynput` chiama da un thread suo. Quel callback non tocca widget: chiama i
metodi del nucleo, che sono sicuri, e per aggiornare l'interfaccia emette un
segnale come tutti gli altri.
"""

from __future__ import annotations

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")

# PRIMA DI QT, E NON E' UNA PREFERENZA DI STILE.
# Il contesto DPI di un processo si fissa al primo uso e poi non cambia
# piu': se `QApplication` nasce per prima, Windows ha gia' deciso che questo
# processo non sa cos'e' il DPI, e da li' in avanti racconta coordinate
# virtualizzate. Il sintomo sarebbe un clic sistematicamente spostato sul
# monitor secondario e perfetto sul primario, cioe' invisibile a chi prova
# di fretta. L'import sta qui in mezzo apposta, e `metis.tools.display` non
# importa nulla che tocchi il display. Lo verifica
# `test_il_dpi_si_dichiara_prima_di_qt`, leggendo l'ordine nell'AST.
from metis.tools.display import set_dpi_awareness  # noqa: E402

DPI_PER_MONITOR = set_dpi_awareness()

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from metis.audio.ptt import (  # noqa: E402
    DEFAULT_HOTKEY,
    DEFAULT_KILL_SWITCH,
    GlobalHotkeys,
)
from metis.core.avvio import Opzioni  # noqa: E402
from metis.core.logging import configure, get_logger  # noqa: E402
from metis.gui.conferma import PonteConferma  # noqa: E402
from metis.gui.fullscreen_view import FullscreenView  # noqa: E402
from metis.gui.lag import MisuratoreLag  # noqa: E402
from metis.gui.minimal_view import MinimalView  # noqa: E402
from metis.gui.widgets.conferma import DialogoConferma  # noqa: E402
from metis.gui.widgets.conversazione import Conversazione  # noqa: E402
from metis.gui.widgets.telemetria import Telemetria as CruscottoTelemetria  # noqa: E402
from metis.gui.workers.nucleo import Nucleo  # noqa: E402
from metis.gui.workers.telemetria import Telemetria as WorkerTelemetria  # noqa: E402


class Segnali(QObject):
    """Ponte per chi non e' Qt: il thread delle scorciatoie globali."""

    kill_cambiato = Signal(bool)


class Applicazione(QObject):
    """QObject, e non una classe qualunque, per un motivo preciso.

    UNA LAMBDA COLLEGATA A UN SEGNALE GIRA SUL THREAD DI CHI EMETTE
    `signal.connect(lambda: ...)` non ha un oggetto ricevente, quindi Qt non
    sa a chi consegnare e la esegue direttamente, nel thread che ha emesso.
    Con i segnali del nucleo significa toccare i widget dal thread sbagliato:
    esattamente la regola che questo pacchetto esiste per rispettare,
    violata dalla scorciatoia piu' comoda che ci sia.

    Con i metodi di un QObject costruito sul thread principale, Qt conosce il
    ricevente, vede che sta su un altro thread e mette la chiamata in coda.
    Da qui la regola: nessuna lambda sui segnali che arrivano da un worker,
    uno slot vero per ognuno.

    Il difetto e' saltato fuori da un test nato per verificare tutt'altro —
    il passaggio fra le due viste — ed e' il motivo per cui adesso ce n'e'
    uno che emette da un thread vero e controlla dove atterra.
    """

    def __init__(self, opzioni: Opzioni, fullscreen: bool = False):
        super().__init__()
        self.opzioni = opzioni
        self.log = get_logger()
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setApplicationName("Metis")

        # --- widget condivisi, posseduti da qui e non dalle viste ---------
        self.conversazione = Conversazione()
        self.cruscotto = CruscottoTelemetria()

        self.minimal = MinimalView()
        self.fullscreen = FullscreenView(self.conversazione, self.cruscotto)
        self._dialogo: DialogoConferma | None = None

        # --- thread del nucleo --------------------------------------------
        self.ponte = PonteConferma()
        self.nucleo = Nucleo(opzioni, self.ponte)
        self.thread_nucleo = QThread()
        self.thread_nucleo.setObjectName("metis-nucleo")
        self.nucleo.moveToThread(self.thread_nucleo)
        self.thread_nucleo.started.connect(self.nucleo.avvia)

        # --- thread della telemetria --------------------------------------
        self.worker_telemetria = WorkerTelemetria()
        self.thread_telemetria = QThread()
        self.thread_telemetria.setObjectName("metis-telemetria")
        self.worker_telemetria.moveToThread(self.thread_telemetria)
        self.thread_telemetria.started.connect(self.worker_telemetria.avvia)

        self.lag = MisuratoreLag()
        self.segnali = Segnali()
        self._collega()
        self._scorciatoie()

    # -- cablaggio dei segnali --------------------------------------------

    def _collega(self) -> None:
        """Ogni segnale che arriva da un worker finisce in uno SLOT di questo
        oggetto. Nessuna lambda: vedi la nota nella docstring della classe."""
        n = self.nucleo

        n.avvio.connect(self._riga_avvio)
        n.pronto.connect(self._pronto)
        n.errore.connect(self._errore)
        n.finito.connect(self._nucleo_finito)
        n.stato.connect(self._stato)
        n.trascritto.connect(self._trascritto)
        n.dice.connect(self._dice)
        n.turno.connect(self._turno)
        n.livello.connect(self._livello)
        n.contatori.connect(self._contatori)
        # M5 — va solo alla control room: nella vista minimal non c'e' posto
        # per un budget di token, e chi usa Metis in minimal non lo sta
        # guardando per capire perche' ha risposto cosi'.
        n.contesto.connect(self.fullscreen.imposta_contesto)
        self.worker_telemetria.dati.connect(self._risorse)
        self.worker_telemetria.errore.connect(self._errore)

        self.ponte.richiesta.connect(self._mostra_conferma)
        self.ponte.chiusa.connect(self._chiudi_conferma)

        # Questi arrivano dal thread principale: sono i pulsanti.
        for vista in (self.minimal, self.fullscreen):
            vista.chiede_ptt.connect(self._ptt)
            vista.chiede_kill.connect(self._kill)
        self.minimal.chiede_fullscreen.connect(self.mostra_fullscreen)
        self.fullscreen.chiede_minimal.connect(self.mostra_minimal)

        self.segnali.kill_cambiato.connect(self.minimal.imposta_kill)
        self.segnali.kill_cambiato.connect(self.fullscreen.imposta_kill)
        self.lag.freeze.connect(self._freeze)

    def _scorciatoie(self) -> None:
        self.hotkeys = GlobalHotkeys()
        # Chiamate dal thread di pynput: toccano il nucleo, che e' sicuro,
        # e per l'interfaccia passano da un segnale come tutti gli altri.
        self.hotkeys.bind(DEFAULT_HOTKEY, self.nucleo.ptt)
        self.hotkeys.bind(DEFAULT_KILL_SWITCH, self._kill)

    # -- slot: tutto quello che arriva dai worker --------------------------

    @Slot(str, str, str)
    def _stato(self, da: str, evento: str, a: str) -> None:
        self.minimal.imposta_stato(a)
        self.fullscreen.imposta_stato(a)

    @Slot(str, bool)
    def _trascritto(self, testo: str, sospetto: bool) -> None:
        self.conversazione.utente(testo, sospetto)
        self.minimal.imposta_ultima(testo)
        self.fullscreen.imposta_corrente(testo)

    @Slot(str)
    def _dice(self, testo: str) -> None:
        self.conversazione.metis(testo)
        self.fullscreen.imposta_corrente(testo)

    @Slot(dict)
    def _turno(self, m: dict) -> None:
        self.cruscotto.aggiorna_turno(m)
        if m.get("strumento"):
            self.conversazione.sistema(f"strumento: {m['strumento']}")

    @Slot(float, float)
    def _livello(self, rms: float, picco: float) -> None:
        self.minimal.vu.campiona(rms, picco)
        self.fullscreen.vu.campiona(rms, picco)

    @Slot(dict)
    def _risorse(self, d: dict) -> None:
        self.cruscotto.aggiorna_risorse(d)

    @Slot(str)
    def _errore(self, testo: str) -> None:
        self.conversazione.sistema(f"errore: {testo}")

    @Slot(float)
    def _freeze(self, ms: float) -> None:
        self.log.warning("freeze interfaccia", ms=round(ms))

    @Slot()
    def _ptt(self) -> None:
        # Chiamata diretta: il ciclo audio tiene occupato il thread del
        # nucleo, quindi uno slot in coda non verrebbe mai eseguito.
        self.nucleo.ptt()

    @Slot(str)
    def _riga_avvio(self, riga: str) -> None:
        self.fullscreen.avvio.setText(riga)
        self.conversazione.sistema(riga)

    @Slot(float)
    def _pronto(self, secondi: float) -> None:
        # Da qui in poi i blocchi contano per NFR-8: il criterio parla di
        # freeze "durante l'inferenza", e caricare tre modelli non lo e'.
        self.lag.cambia_fase("esercizio")
        self.fullscreen.avvio.setText(f"pronto in {secondi:.1f} s")
        self.conversazione.sistema(
            f"pronto in {secondi:.1f} s — {DEFAULT_HOTKEY} per parlare")
        sis = self.nucleo.sistema
        if sis is not None and sis.audit is not None:
            self.fullscreen.audit.collega(sis.audit)
        if sis is not None and sis.router is not None:
            self.fullscreen.collega_comandi(sis.libreria)

    @Slot(dict)
    def _contatori(self, d: dict) -> None:
        self.segnali.kill_cambiato.emit(bool(d.get("kill_switch")))

    @Slot()
    def _kill(self) -> None:
        sospeso = self.nucleo.kill_switch()
        self.segnali.kill_cambiato.emit(sospeso)

    @Slot(str, str, dict, float)
    def _mostra_conferma(self, strumento: str, tier: str, argomenti: dict,
                         timeout_s: float) -> None:
        genitore = self.fullscreen if self.fullscreen.isVisible() else self.minimal
        self._dialogo = DialogoConferma(strumento, tier, argomenti, timeout_s,
                                        parent=genitore)
        self._dialogo.deciso.connect(self.ponte.rispondi)
        self._dialogo.show()
        self._dialogo.raise_()
        self._dialogo.activateWindow()

    @Slot()
    def _chiudi_conferma(self) -> None:
        if self._dialogo is not None:
            self._dialogo.close()
            self._dialogo = None

    @Slot()
    def _nucleo_finito(self) -> None:
        self.conversazione.sistema("nucleo fermo")

    # -- viste -------------------------------------------------------------

    @Slot()
    def mostra_minimal(self) -> None:
        self.fullscreen.hide()
        self.minimal.show()
        self.minimal.raise_()

    @Slot()
    def mostra_fullscreen(self) -> None:
        self.minimal.hide()
        self.fullscreen.show()
        self.fullscreen.raise_()

    # -- ciclo di vita -----------------------------------------------------

    def esegui(self, fullscreen: bool = False) -> int:
        self.mostra_fullscreen() if fullscreen else self.mostra_minimal()
        self.lag.avvia()
        self.thread_nucleo.start()
        self.thread_telemetria.start()
        self.hotkeys.start()
        self.qt.aboutToQuit.connect(self.chiudi)
        codice = self.qt.exec()
        print("\n  " + self.lag.riassunto())
        return codice

    def chiudi(self) -> None:
        self.lag.ferma()
        self.hotkeys.stop()
        self.minimal.salva_posizione()
        self.worker_telemetria.ferma()
        self.nucleo.ferma()
        # Il ciclo audio esce entro ~250 ms; si concede il doppio prima di
        # smettere di aspettarlo. Un'applicazione che non si chiude e' un
        # difetto quanto una che si blocca.
        self.thread_nucleo.quit()
        self.thread_nucleo.wait(3000)
        self.thread_telemetria.quit()
        self.thread_telemetria.wait(2000)
        self.nucleo.chiudi()


def main() -> int:
    ap = argparse.ArgumentParser(description="Metis — interfaccia grafica")
    ap.add_argument("--fullscreen", action="store_true",
                    help="parte dalla control room invece che dall'overlay")
    ap.add_argument("--no-wakeword", dest="wakeword", action="store_false")
    ap.add_argument("--no-tools", dest="tools", action="store_false")
    ap.add_argument("--whisper", default="small")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--minutes", type=float, default=0.0)
    args = ap.parse_args()

    configure(level=args.log_level)
    app = Applicazione(Opzioni.da_args(args), fullscreen=args.fullscreen)

    if args.minutes:
        # Serve alle prove non presidiate: NFR-8 si misura lasciandola
        # lavorare, non guardandola.
        QTimer.singleShot(int(args.minutes * 60_000), app.qt.quit)

    return app.esegui(fullscreen=args.fullscreen)


if __name__ == "__main__":
    sys.exit(main())
