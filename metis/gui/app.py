"""Metis con interfaccia grafica.

    python -m metis.gui.app
    python -m metis.gui.app --fullscreen --no-tools

TOPOLOGIA

    thread principale     QApplication, tutti i widget, il misuratore di lag
    thread "nucleo"       audio, macchina a stati, STT, LLM, broker
    thread "telemetria"   psutil 2 Hz, NVML 1 Hz
    thread "meteo"        Open-Meteo ogni 15 minuti (PHASE1)

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

M7 — LA TRAY
Con l'area di notifica disponibile, chiudere una finestra la nasconde e
Metis resta vivo nella tray; si esce solo da "Esci". Senza tray (una sessione
remota, un desktop minimale) resta il comportamento di prima: chiudere
l'ultima finestra e' uscire. Vedi `metis/gui/tray.py`.
"""

from __future__ import annotations

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")

# M7 — prima di tutto il resto, in quest'ordine. La cartella di lavoro, perche'
# il bundle puo' partire da dist\Metis dove config/ non c'e' (`fissa_radice`).
# Poi i flussi: con `pythonw` e con il bundle non c'e' console, e qualunque
# import che scriva su stderr cadrebbe (`garantisci_flussi`).
from metis.core.radice import fissa_radice  # noqa: E402

fissa_radice()

from metis.core.logging import garantisci_flussi  # noqa: E402

garantisci_flussi()

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

from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Signal, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from metis.audio.ptt import (  # noqa: E402
    DEFAULT_HOTKEY,
    DEFAULT_KILL_SWITCH,
    GlobalHotkeys,
)
from metis.core.avvio import Opzioni  # noqa: E402
from metis.core.logging import configure, get_logger  # noqa: E402
from metis.core.risposte import FILLERS  # noqa: E402
from metis.gui.conferma import PonteConferma  # noqa: E402
from metis.gui import impostazioni, tema  # noqa: E402
from metis.gui.fullscreen_view import FullscreenView  # noqa: E402
from metis.gui.hub_view import HubView  # noqa: E402
from metis.gui.lag import MisuratoreLag  # noqa: E402
from metis.gui.minimal_view import MinimalView  # noqa: E402
from metis.gui.modello_conversazione import ModelloConversazione  # noqa: E402
from metis.gui.tray import IconaTray  # noqa: E402
from metis.gui.widgets.conferma import DialogoConferma  # noqa: E402
from metis.gui.widgets.conversazione import Conversazione  # noqa: E402
from metis.gui.widgets.telemetria import Telemetria as CruscottoTelemetria  # noqa: E402
from metis.gui.workers.nucleo import Nucleo  # noqa: E402
from metis.gui.workers.meteo import Meteo as WorkerMeteo  # noqa: E402
from metis.gui.workers.telemetria import Telemetria as WorkerTelemetria  # noqa: E402


class Segnali(QObject):
    """Ponte per chi non e' Qt: il thread delle scorciatoie globali."""

    kill_cambiato = Signal(bool)
    pausa_cambiata = Signal(bool)


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

    def __init__(self, opzioni: Opzioni, fullscreen: bool = False,
                 tray: bool | None = None, config=impostazioni.CONFIG):
        super().__init__()
        self.opzioni = opzioni
        # PHASE1: `config/gui.toml` e il suo locale. Un parametro perche' i
        # test non leggano mai quello vero della macchina.
        self.config = config
        self.preferenze = impostazioni.leggi(config)
        self.log = get_logger()
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setApplicationName("Metis")
        # PHASE1: font, icone e foglio di stile dell'Hub, per tutta l'applicazione.
        self.font_disponibili = tema.applica(self.qt)
        mancanti = [f for f, ok in self.font_disponibili.items() if not ok]
        if mancanti:
            self.log.warning("font mancanti", font=mancanti)

        # --- dati e widget condivisi, posseduti da qui e non dalle viste ---
        # PHASE1: la conversazione e' un modello, disegnato in due modi — a
        # fumetti nell'Hub, come registro nella Diagnostica.
        self.modello = ModelloConversazione(self)
        self.conversazione = Conversazione(self.modello)
        self.cruscotto = CruscottoTelemetria()

        self.minimal = MinimalView()
        self.hub = HubView(self.modello)
        # La control room di PHASE0: da PHASE1 e' la vista "Diagnostica".
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

        # --- PHASE1: thread del meteo ---------------------------------------
        self.worker_meteo = WorkerMeteo(config=config)
        self.thread_meteo = QThread()
        self.thread_meteo.setObjectName("metis-meteo")
        self.worker_meteo.moveToThread(self.thread_meteo)
        self.thread_meteo.started.connect(self.worker_meteo.avvia)

        self.lag = MisuratoreLag()
        self.segnali = Segnali()

        # --- M7: tray ------------------------------------------------------
        # `tray=None` vuol dire "se c'e' l'area di notifica". I test la
        # forzano, in un senso o nell'altro.
        if tray is None:
            tray = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray: IconaTray | None = IconaTray(self) if tray else None
        self._avvisato_tray = False
        self._vista_attiva = "hub" if fullscreen else "minimal"
        if self.tray is not None:
            self.qt.setQuitOnLastWindowClosed(False)
            for vista in (self.minimal, self.hub, self.fullscreen):
                vista.installEventFilter(self)

        self._collega()
        self._scorciatoie()
        self._applica_preferenze(all_avvio=True)

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
        n.voce.connect(self._voce)
        n.contatori.connect(self._contatori)
        # M5 — va solo alla control room: nella vista minimal non c'e' posto
        # per un budget di token, e chi usa Metis in minimal non lo sta
        # guardando per capire perche' ha risposto cosi'.
        n.contesto.connect(self.fullscreen.imposta_contesto)
        self.worker_telemetria.dati.connect(self._risorse)
        self.worker_telemetria.errore.connect(self._errore)
        self.worker_meteo.dati.connect(self.hub.imposta_meteo)

        self.ponte.richiesta.connect(self._mostra_conferma)
        self.ponte.chiusa.connect(self._chiudi_conferma)

        # Questi arrivano dal thread principale: sono i pulsanti.
        for vista in (self.minimal, self.hub, self.fullscreen):
            vista.chiede_ptt.connect(self._ptt)
            vista.chiede_kill.connect(self._kill)
        self.minimal.chiede_fullscreen.connect(self.mostra_hub)
        self.fullscreen.chiede_minimal.connect(self.mostra_minimal)
        self.fullscreen.chiede_hub.connect(self.mostra_hub)
        self.hub.chiede_minimal.connect(self.mostra_minimal)
        self.hub.chiede_diagnostica.connect(self.mostra_fullscreen)
        self.hub.chiede_testo.connect(self._testo)
        self.hub.chiede_pulisci.connect(self._pulisci)
        self.hub.chiede_muto.connect(self._muto)
        self.hub.chiede_impostazioni.connect(self._impostazioni)

        for vista in (self.minimal, self.hub, self.fullscreen):
            self.segnali.kill_cambiato.connect(vista.imposta_kill)
        self.segnali.pausa_cambiata.connect(self.hub.imposta_pausa)
        self.segnali.pausa_cambiata.connect(self.minimal.imposta_pausa)
        self.lag.freeze.connect(self._freeze)

        if self.tray is not None:
            t = self.tray
            t.chiede_minimal.connect(self.mostra_minimal)
            t.chiede_hub.connect(self.mostra_hub)
            t.chiede_fullscreen.connect(self.mostra_fullscreen)
            t.chiede_kill.connect(self._kill)
            t.chiede_pausa.connect(self._pausa)
            t.chiede_uscita.connect(self.esci)
            t.cliccata.connect(self.riporta)
            self.segnali.kill_cambiato.connect(t.imposta_kill)
            self.segnali.pausa_cambiata.connect(t.imposta_pausa)

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
        self.hub.imposta_stato(a)
        self.fullscreen.imposta_stato(a)
        if self.tray is not None:
            self.tray.imposta_stato(a)

    @Slot(str, bool)
    def _trascritto(self, testo: str, sospetto: bool) -> None:
        self.conversazione.utente(testo, sospetto)
        self.minimal.imposta_ultima(testo)
        self.fullscreen.imposta_corrente(testo)

    @Slot(str)
    def _dice(self, testo: str) -> None:
        self.fullscreen.imposta_corrente(testo)
        # PHASE1 — "Verifico." si dice mentre si cerca, e basta: nel fumetto
        # sembrava l'inizio della risposta ("Verifico. Per addestrare...").
        # Lo stato lo dice gia' la pillola, "sta cercando in rete".
        if testo in FILLERS:
            return
        self.conversazione.metis(testo)

    @Slot(dict)
    def _turno(self, m: dict) -> None:
        self.cruscotto.aggiorna_turno(m)
        # Le frasi di questo turno sono un fumetto solo: da qui si chiude.
        self.modello.chiudi_turno()
        if m.get("strumento"):
            self.conversazione.sistema(f"strumento: {m['strumento']}")

    @Slot(float, float)
    def _livello(self, rms: float, picco: float) -> None:
        self.minimal.vu.campiona(rms, picco)
        self.fullscreen.vu.campiona(rms, picco)
        self.hub.nucleo.campiona_microfono(rms)
        self.minimal.nucleo.campiona_microfono(rms)

    @Slot(float)
    def _voce(self, db: float) -> None:
        # PHASE1 — l'onda del nucleo in PARLATO segue la voce, dal player.
        self.hub.nucleo.campiona_voce(db)
        self.minimal.nucleo.campiona_voce(db)

    @Slot(dict)
    def _risorse(self, d: dict) -> None:
        self.cruscotto.aggiorna_risorse(d)
        self.hub.sistema.aggiorna(d)
        self.hub.sessione.aggiorna_risorse(d)

    @Slot(str)
    def _errore(self, testo: str) -> None:
        # Il testo arriva gia' in persona dalla matrice degli errori: niente
        # prefisso "errore:", che lo farebbe sembrare un messaggio di sistema.
        self.conversazione.sistema(testo)

    @Slot(float)
    def _freeze(self, ms: float) -> None:
        # M7: con la fase, perche' NFR-8 si giudica sull'esercizio e la
        # verifica (tests/nfr) legge il log, non il riassunto a video.
        self.log.warning("freeze interfaccia", ms=round(ms), fase=self.lag.fase)

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
        self.hub.imposta_pronto()

    @Slot(dict)
    def _contatori(self, d: dict) -> None:
        self.segnali.kill_cambiato.emit(bool(d.get("kill_switch")))
        self.hub.sessione.aggiorna_contatori(d)

    @Slot()
    def _kill(self) -> None:
        sospeso = self.nucleo.kill_switch()
        self.segnali.kill_cambiato.emit(sospeso)

    @Slot()
    def _pausa(self) -> None:
        # Chiamata diretta, come il PTT: il thread del nucleo e' occupato dal
        # ciclo audio e uno slot in coda non partirebbe mai.
        in_pausa = self.nucleo.pausa()
        self.segnali.pausa_cambiata.emit(in_pausa)
        self.conversazione.sistema("Ascolto in pausa." if in_pausa
                                   else "Ascolto ripreso.")

    # -- PHASE1: i comandi dell'Hub ---------------------------------------

    @Slot(str)
    def _testo(self, testo: str) -> None:
        """Il fumetto dell'utente compare solo se il turno e' partito, e solo
        allora il campo si svuota: un messaggio rifiutato resta dov'e'."""
        if self.nucleo.testo(testo):
            self.modello.utente(testo, scritto=True)
            self.minimal.imposta_ultima(testo)
            self.hub.testo_accettato()
        elif self.nucleo.sistema is None:
            self.modello.sistema("Metis si sta ancora avviando: il messaggio è rimasto nel campo.")
        else:
            self.modello.sistema("Metis sta lavorando: il messaggio è rimasto nel campo.")

    @Slot()
    def _pulisci(self) -> None:
        if self.nucleo.azzera():
            self.modello.azzera()
            self.modello.sistema("Conversazione cancellata: Metis riparte da zero.")
        else:
            self.modello.sistema("Non posso pulire adesso: c'è un turno in corso.")

    @Slot(bool)
    def _muto(self, attivo: bool) -> None:
        self.nucleo.muto(attivo)
        self.modello.sistema("Voce disattivata: le risposte restano scritte." if attivo
                             else "Voce riattivata.")

    # -- PHASE1: impostazioni ---------------------------------------------

    @Slot()
    def _impostazioni(self) -> None:
        dialogo = impostazioni.DialogoImpostazioni(self.preferenze, parent=self.hub)
        if dialogo.exec():
            self.salva_preferenze(dialogo.preferenze())

    def salva_preferenze(self, pref: impostazioni.Preferenze) -> None:
        """Separata dal dialogo: i test la chiamano senza aprire niente."""
        try:
            citta_cambiata = impostazioni.salva(pref, self.config)
        except OSError as exc:
            self.log.warning("impostazioni non salvate", errore=str(exc))
            self.modello.sistema("Non riesco a salvare le impostazioni: il file non si scrive.")
            return
        self.preferenze = pref
        self._applica_preferenze()
        if citta_cambiata:
            # La geocodifica la fa il worker, sul suo thread: vedi
            # `metis/gui/impostazioni.py`.
            self.worker_meteo.ricarica()

    def _applica_preferenze(self, all_avvio: bool = False) -> None:
        """Le animazioni valgono subito; il muto solo all'avvio, perche' e'
        una preferenza di partenza e non deve spegnere la voce a meta'
        conversazione."""
        attive = not self.preferenze.riduci_animazioni
        self.hub.nucleo.imposta_animazioni(attive)
        self.minimal.nucleo.imposta_animazioni(attive)
        if all_avvio and self.preferenze.muto_avvio:
            self.hub.b_voce.setChecked(True)

    def vista_iniziale(self, fullscreen: bool, diagnostica: bool) -> tuple[bool, bool]:
        """La riga di comando vince; senza, decidono le impostazioni."""
        if fullscreen or diagnostica:
            return fullscreen, diagnostica
        v = self.preferenze.vista_avvio
        return v == "hub", v == "diagnostica"

    @Slot(str, str, dict, float)
    def _mostra_conferma(self, strumento: str, tier: str, argomenti: dict,
                         timeout_s: float) -> None:
        genitore = next((v for v in (self.hub, self.fullscreen) if v.isVisible()),
                        self.minimal)
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

    def _viste(self) -> dict:
        return {"minimal": self.minimal, "hub": self.hub, "fullscreen": self.fullscreen}

    def _mostra(self, nome: str) -> None:
        """Una vista alla volta. Le altre si nascondono, non si distruggono:
        e' il principio di M3, e con tre viste vale ancora di piu'."""
        self._vista_attiva = nome
        for altro, vista in self._viste().items():
            if altro != nome:
                vista.hide()
        vista = self._viste()[nome]
        vista.show()
        vista.raise_()

    @Slot()
    def mostra_minimal(self) -> None:
        self._mostra("minimal")

    @Slot()
    def mostra_hub(self) -> None:
        self._mostra("hub")

    @Slot()
    def mostra_fullscreen(self) -> None:
        """La Diagnostica: il nome resta quello di M3, usato da tray e test."""
        self._mostra("fullscreen")

    @Slot()
    def riporta(self) -> None:
        """Clic sull'icona: torna l'ultima vista usata, in primo piano."""
        vista = self._viste()[self._vista_attiva]
        if vista.isVisible() and not vista.isMinimized():
            vista.raise_()
            vista.activateWindow()
            return
        self._mostra(self._vista_attiva)
        vista.showNormal()
        vista.activateWindow()

    def eventFilter(self, oggetto, evento) -> bool:
        # La X di una vista con la tray presente: la finestra si nasconde (lo
        # fa Qt, qui si lascia passare l'evento) e la prima volta si avvisa,
        # perche' un programma che "non si chiude" sembra un programma rotto.
        if (evento.type() == QEvent.Type.Close and self.tray is not None
                and not self._avvisato_tray):
            self._avvisato_tray = True
            self.tray.avvisa("Resto nell'area di notifica. Per uscire: Esci, "
                             "dal menu dell'icona.")
        return False

    @Slot()
    def esci(self) -> None:
        """L'unica uscita con la tray presente. Passa da `aboutToQuit`, cioe'
        da `chiudi`: vedi la nota in testa a `tray.py`."""
        self.qt.quit()

    # -- ciclo di vita -----------------------------------------------------

    def esegui(self, fullscreen: bool = False, diagnostica: bool = False) -> int:
        if diagnostica:
            self.mostra_fullscreen()
        elif fullscreen:
            self.mostra_hub()
        else:
            self.mostra_minimal()
        self.lag.avvia()
        self.thread_nucleo.start()
        self.thread_telemetria.start()
        self.thread_meteo.start()
        self.hotkeys.start()
        if self.tray is not None:
            self.tray.mostra()
        self.qt.aboutToQuit.connect(self.chiudi)
        codice = self.qt.exec()
        print("\n  " + self.lag.riassunto())
        # PHASE1 — quanto e' durato l'uso, nel log: i blocchi si registravano,
        # la durata no, e NFR-8 chiede "0 blocchi in 30 minuti".
        s = self.lag.stats("esercizio")
        self.log.info("sessione interfaccia",
                      esercizio_s=round(s.get("campioni", 0) * self.lag.intervallo_ms / 1000),
                      **{k: v for k, v in s.items() if k != "campioni"})
        return codice

    def chiudi(self) -> None:
        # L'icona per prima: se resta, Windows la lascia nell'area di notifica
        # finche' il mouse non ci passa sopra — un fantasma che sembra Metis
        # ancora vivo.
        if self.tray is not None:
            self.tray.nascondi()
        self.lag.ferma()
        self.hotkeys.stop()
        self.minimal.salva_posizione()
        self.worker_telemetria.ferma()
        self.worker_meteo.ferma()
        self.nucleo.ferma()
        # Il ciclo audio esce entro ~250 ms; si concede il doppio prima di
        # smettere di aspettarlo. Un'applicazione che non si chiude e' un
        # difetto quanto una che si blocca.
        self.thread_nucleo.quit()
        if not self.thread_nucleo.wait(3000):
            # PHASE1 — chiuso durante l'avvio: il caricamento dei modelli non
            # si interrompe a meta'. Finito quello il nucleo esce da solo (vedi
            # `Nucleo.ferma`); non aspettarlo vorrebbe dire distruggere un
            # thread vivo, cioe' `abort()`.
            self.log.info("chiusura durante l'avvio: si aspetta il nucleo")
            self.thread_nucleo.wait(60_000)
        self.thread_telemetria.quit()
        self.thread_telemetria.wait(2000)
        # Il meteo puo' essere dentro una richiesta: il timeout e' 4 s, e
        # l'attesa lo copre. Succede solo chiudendo in quel mezzo secondo
        # ogni quarto d'ora.
        self.thread_meteo.quit()
        self.thread_meteo.wait(4500)
        self.nucleo.chiudi()


def main() -> int:
    ap = argparse.ArgumentParser(description="Metis — interfaccia grafica")
    ap.add_argument("--fullscreen", action="store_true",
                    help="parte dall'Hub invece che dall'overlay")
    ap.add_argument("--diagnostica", action="store_true",
                    help="parte dalla vista Diagnostica (la control room di PHASE0)")
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

    fullscreen, diagnostica = app.vista_iniziale(args.fullscreen, args.diagnostica)
    return app.esegui(fullscreen=fullscreen, diagnostica=diagnostica)


if __name__ == "__main__":
    sys.exit(main())
