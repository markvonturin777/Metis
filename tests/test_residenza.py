"""M7 — Metis residente: pausa dell'ascolto, tray, uscita pulita.

Tre cose che dal vivo si provano male. La pausa perche' il suo difetto e'
silenzioso (un microfono che ascolta quando non dovrebbe non fa rumore). La
tray perche' e' un pezzo di Windows che nei test non si vede. L'uscita
pulita perche' un thread orfano non da' errori: tiene occupato il device
audio e lo si scopre al riavvio successivo.
"""
import threading
import time

import numpy as np
import pytest

from metis.core.state_machine import Event, State
from tests.test_orchestrator import blocco, make


# --- pausa dell'ascolto ------------------------------------------------------

def test_in_pausa_nessun_frame_arriva_alla_wake_word_ne_al_vad():
    """Il cuore della pausa: e' "sospende wake word e VAD", tutti e due."""
    chiamate = {"n": 0}
    o, _ = make()
    o.d.wakeword = lambda pcm: chiamate.__setitem__("n", chiamate["n"] + 1) or False
    o.pausa(True)
    for _ in range(40):
        o.on_audio(blocco())
    assert chiamate["n"] == 0
    assert o.counters.frames_to_vad == 0
    assert o.counters.frames_in_pausa == 40


def test_la_wake_word_in_pausa_non_sveglia():
    o, _ = make(wake_on_call=1)
    o.pausa(True)
    o.on_audio(blocco())
    assert o.sm.state is State.DORMIENTE


def test_la_pausa_chiude_un_ascolto_aperto_passando_dalla_tabella():
    """Da IN_ASCOLTO a DORMIENTE con una transizione vera, non con `reset`:
    la GUI e la tray imparano lo stato solo dalle transizioni."""
    viste = []
    o, _ = make()
    o.sm._on_transition = lambda tr: viste.append(tr.to)
    o.sm.fire(Event.PTT)
    o.pausa(True)
    assert o.sm.state is State.DORMIENTE
    assert viste[-1] is State.DORMIENTE


def test_la_pausa_chiude_anche_una_trascrizione_a_meta():
    o, _ = make()
    o.sm.fire(Event.PTT)
    o.sm.fire(Event.SPEECH_START)
    o.pausa(True)
    assert o.sm.state is State.DORMIENTE


def test_in_pausa_il_ptt_non_riapre_il_microfono():
    o, _ = make()
    o.pausa(True)
    o.on_ptt()
    assert o.sm.state is State.DORMIENTE


def test_in_pausa_il_ptt_zittisce_ancora_metis():
    """Il PTT resta il modo di interrompere una risposta: la pausa toglie le
    orecchie, non il modo di far tacere."""
    o, player = make()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    o.pausa(True)                     # a turno in corso: la risposta continua
    assert o.sm.state is State.PARLATO
    player.queue.extend([1, 2])
    o.on_ptt()
    assert player.stopped >= 1 and not player.queue
    o.tick()                          # e poi non si resta ad ascoltare
    assert o.sm.state is State.DORMIENTE


def test_finito_il_turno_in_pausa_si_torna_a_dormire():
    o, _ = make()
    for ev in (Event.WAKE_WORD, Event.SPEECH_START, Event.SPEECH_END,
               Event.INTENT_CHAT, Event.FIRST_AUDIO):
        o.sm.fire(ev)
    o.pausa(True)
    o.sm.fire(Event.PLAYBACK_DONE)    # -> IN_ASCOLTO, il follow-up
    assert o.sm.state is State.IN_ASCOLTO
    o.tick()
    assert o.sm.state is State.DORMIENTE


def test_ripresa_l_ascolto_torna_normale():
    o, _ = make(wake_on_call=1)
    o.pausa(True)
    o.pausa(False)
    o.on_audio(blocco())
    assert o.sm.state is State.IN_ASCOLTO


# --- icona -------------------------------------------------------------------

def _pixel(pix, x, y) -> str:
    return pix.toImage().pixelColor(x, y).name()


def test_l_icona_ha_il_colore_dello_stato(app_qt):
    from metis.core.palette import esadecimale
    from metis.gui.tray import disegna

    for stato in ("DORMIENTE", "IN_ASCOLTO", "ELABORAZIONE", "PARLATO",
                  "ATTESA_CONFERMA", "ERRORE"):
        assert _pixel(disegna(stato), 32, 32) == esadecimale(stato), stato


def test_il_kill_switch_aggiunge_un_anello_rosso_e_lascia_lo_stato(app_qt):
    from metis.core.palette import esadecimale
    from metis.gui.tray import ROSSO_KILL, disegna

    pix = disegna("PARLATO", kill=True)
    assert _pixel(pix, 32, 7) == ROSSO_KILL            # sull'anello
    assert _pixel(pix, 32, 32) == esadecimale("PARLATO")
    assert _pixel(disegna("PARLATO"), 32, 7) != ROSSO_KILL


def test_la_pausa_disegna_due_barre(app_qt):
    from metis.gui.tray import disegna

    pix = disegna("DORMIENTE", pausa=True)
    assert _pixel(pix, 26, 32) == "#ffffff"            # barra sinistra
    assert _pixel(pix, 38, 32) == "#ffffff"            # barra destra
    assert _pixel(pix, 32, 32) != "#ffffff"            # in mezzo, il colore


def test_la_descrizione_e_una_frase():
    from metis.gui.tray import descrizione

    assert descrizione("PARLATO", False, False) == "Metis — sta parlando"
    d = descrizione("DORMIENTE", kill=True, pausa=True)
    assert "pausa" in d and "sospese" in d
    assert "DORMIENTE" not in d


# --- menu --------------------------------------------------------------------

def test_il_menu_e_quello_della_specifica(app_qt):
    from metis.gui.tray import IconaTray

    t = IconaTray()
    voci = [a.text() for a in t.menu.actions() if not a.isSeparator()]
    # PHASE1: tre viste. "Fullscreen" e' diventata "Diagnostica".
    assert voci[1:] == ["Mostra Minimal", "Mostra Hub", "Mostra Diagnostica", "Kill switch",
                        "Pausa ascolto", "Esci"]
    assert voci[0].startswith("Metis — ")
    assert not t.voce_stato.isEnabled()


def test_la_spunta_la_mette_lo_stato_vero_non_il_clic(app_qt):
    """Clic su "Pausa ascolto" con il nucleo non ancora pronto: la pausa
    non attecchisce, e la spunta non deve comparire."""
    from metis.gui.tray import IconaTray

    t = IconaTray()
    chieste = []
    t.chiede_pausa.connect(lambda: chieste.append("pausa"))
    t.chiede_kill.connect(lambda: chieste.append("kill"))
    t.voce_pausa.trigger()
    t.voce_kill.trigger()
    assert chieste == ["pausa", "kill"]
    assert not t.voce_pausa.isChecked() and not t.voce_kill.isChecked()
    t.imposta_pausa(True)
    t.imposta_kill(True)
    assert t.voce_pausa.isChecked() and t.voce_kill.isChecked()
    assert "pausa" in t.icona.toolTip()


def test_lo_stato_arriva_al_tooltip(app_qt):
    from metis.gui.tray import IconaTray

    t = IconaTray()
    t.imposta_stato("ATTESA_CONFERMA")
    assert t.icona.toolTip() == "Metis — ASPETTA TE"
    assert t.voce_stato.text() == "Metis — ASPETTA TE"


# --- cablaggio in Applicazione ----------------------------------------------

class _OrchFinto:
    def __init__(self):
        self.in_pausa = False
        self.panici = 0

    def pausa(self, attiva):
        self.in_pausa = attiva

    def panic(self):
        self.panici += 1


class _SistemaFinto:
    def __init__(self):
        self.orchestrator = _OrchFinto()


@pytest.fixture
def app_con_tray(crea_applicazione):
    return crea_applicazione(tray=True)


def _gira(app_qt, n=20):
    for _ in range(n):
        app_qt.processEvents()


def test_pausa_dalla_tray_arriva_al_nucleo_e_torna_come_spunta(app_qt, app_con_tray):
    app = app_con_tray
    app.nucleo.sistema = _SistemaFinto()
    app.tray.voce_pausa.trigger()
    _gira(app_qt)
    assert app.nucleo.sistema.orchestrator.in_pausa
    assert app.tray.voce_pausa.isChecked()
    app.tray.voce_pausa.trigger()
    _gira(app_qt)
    assert not app.nucleo.sistema.orchestrator.in_pausa
    assert not app.tray.voce_pausa.isChecked()


def test_kill_switch_dalla_tray_passa_dallo_stesso_slot_dei_pulsanti(app_qt, app_con_tray):
    from metis.security.killswitch import KILL_SWITCH

    app = app_con_tray
    app.nucleo.sistema = _SistemaFinto()
    prima = KILL_SWITCH.attivo
    try:
        app.tray.voce_kill.trigger()
        _gira(app_qt)
        assert KILL_SWITCH.attivo is not prima
        assert app.nucleo.sistema.orchestrator.panici == 1     # e zittisce
        assert app.tray.voce_kill.isChecked() is KILL_SWITCH.attivo
        # e l'indicatore dell'overlay dice la stessa cosa dell'icona
        assert (not app.minimal.kill.isHidden()) is KILL_SWITCH.attivo
    finally:
        if KILL_SWITCH.attivo is not prima:
            KILL_SWITCH.commuta()


def test_lo_stato_della_macchina_arriva_all_icona(app_qt, app_con_tray):
    app = app_con_tray
    app._stato("DORMIENTE", "WAKE_WORD", "IN_ASCOLTO")
    assert app.tray.icona.toolTip() == "Metis — sveglio, in attesa"


def test_con_la_tray_chiudere_la_finestra_non_e_uscire(app_qt, app_con_tray):
    app = app_con_tray
    assert not app.qt.quitOnLastWindowClosed()
    avvisi = []
    app.tray.avvisa = avvisi.append
    app.mostra_minimal()
    app.minimal.close()
    app.fullscreen.close()
    _gira(app_qt)
    assert not app.minimal.isVisible()
    assert len(avvisi) == 1                 # una volta sola, non a ogni X


def test_esci_passa_da_quit(app_qt, app_con_tray):
    """"Esci" deve passare da `QApplication.quit`, cioe' da `aboutToQuit`,
    cioe' da `chiudi`: l'unico percorso che rilascia il microfono."""
    app = app_con_tray
    chiamate = []

    class QtFinto:
        def quit(self):
            chiamate.append("quit")

        def setQuitOnLastWindowClosed(self, v):
            pass

    vero = app.qt
    app.qt = QtFinto()
    try:
        app.tray.voce_esci.trigger()
    finally:
        app.qt = vero
    assert chiamate == ["quit"]


def test_il_clic_sull_icona_riporta_l_ultima_vista(app_qt, app_con_tray):
    app = app_con_tray
    app.mostra_fullscreen()
    app.fullscreen.hide()
    app.tray.cliccata.emit()
    _gira(app_qt)
    assert app.fullscreen.isVisible() and not app.minimal.isVisible()


def test_senza_tray_si_esce_chiudendo_come_prima(crea_applicazione):
    app = crea_applicazione(tray=False)
    assert app.tray is None
    assert app.qt.quitOnLastWindowClosed()


# --- uscita pulita -----------------------------------------------------------

def _vivi(prefisso="metis-") -> list[str]:
    return [t.name for t in threading.enumerate()
            if t.name.startswith(prefisso) and t.is_alive()]


def test_la_sorveglianza_della_vram_si_ferma_subito():
    """Prima era `while True: time.sleep(10)`: all'uscita il thread restava
    vivo fino a dieci secondi, e non c'era modo di fermarlo."""
    from metis.core.avvio import sorveglia_vram

    class Stt:
        def su_cpu(self):
            return False

    s = sorveglia_vram(Stt(), None, periodo_s=30.0, leggi=lambda: 1.0)
    time.sleep(0.05)
    assert s.thread.is_alive()
    t0 = time.perf_counter()
    s.ferma()
    assert not s.thread.is_alive()
    assert time.perf_counter() - t0 < 1.0


def test_sistema_chiudi_non_lascia_thread_metis():
    """Scheduler, casa, VRAM, salute: dopo `chiudi`, nessun thread `metis-*`.

    Il pianificatore e la casa sono finti — hanno i loro test in M6 — ma il
    sorvegliante della VRAM e la salute sono quelli veri, con i loro thread.
    """
    from metis.core.avvio import Sistema, sorveglia_vram
    from metis.core.errors import SALUTE, Categoria

    class Finto:
        fermato = False

        def ferma(self):
            self.fermato = True

    class Stt:
        def su_cpu(self):
            return False

    pian, casa = Finto(), Finto()
    vram = sorveglia_vram(Stt(), None, periodo_s=30.0, leggi=lambda: 1.0)
    SALUTE.sorveglia(Categoria.INFERENZA, lambda: False, periodo_s=30.0)
    time.sleep(0.05)
    assert {"metis-vram", "metis-salute"} <= set(_vivi())

    Sistema(orchestrator=None, player=None, pianificatore=pian, casa=casa,
            vram=vram).chiudi()

    assert pian.fermato and casa.fermato
    assert not ({"metis-vram", "metis-salute"} & set(_vivi()))


def test_il_ciclo_audio_rilascia_il_device_uscendo():
    """Il criterio "device audio rilasciato": `stop` sulla cattura, anche se
    il ciclo esce per `ferma` e non per il limite di tempo."""
    from metis.core.avvio import CicloAudio
    from metis.audio.capture import Block

    class Cattura:
        fermata = False

        def start(self):
            pass

        def stop(self):
            self.fermata = True

        def read(self, timeout=None):
            time.sleep(0.01)
            return Block(np.zeros(512, np.float32), -60.0, -60.0)

    class Orch:
        def on_audio(self, b):
            pass

        def tick(self):
            pass

    cattura = Cattura()
    ciclo = CicloAudio(Orch(), apri_cattura=lambda: cattura)
    t = threading.Thread(target=ciclo.esegui, daemon=True)
    t.start()
    time.sleep(0.1)
    ciclo.ferma()
    t.join(2.0)
    assert not t.is_alive()
    assert cattura.fermata


# --- PHASE1: chiudere durante l'avvio ------------------------------------------------------

def test_chiuso_durante_l_avvio_il_ciclo_audio_non_parte(monkeypatch):
    """Chiudendo Metis mentre caricava i modelli, `ferma()` trovava il ciclo
    ancora da creare e la richiesta andava persa: il ciclo partiva, non si
    fermava piu', e all'uscita Qt distruggeva un thread vivo (0xC0000409)."""
    from metis.core.avvio import Opzioni
    from metis.gui.workers import nucleo as modulo

    n = modulo.Nucleo(Opzioni(tools=False, wakeword=False))
    eseguiti, finiti = [], []
    n.finito.connect(lambda: finiti.append(1))

    class Sistema:
        avvio_s = 1.0
        orchestrator = object()

    def costruisci(*a, **kw):
        n.ferma()                         # l'utente chiude mentre si caricano i modelli
        return Sistema()

    class Ciclo:
        def __init__(self, *a, **kw):
            pass

        def esegui(self, **kw):
            eseguiti.append(1)

        def ferma(self):
            pass

    monkeypatch.setattr(modulo, "costruisci_sistema", costruisci)
    monkeypatch.setattr(modulo, "CicloAudio", Ciclo)
    n.avvia()
    assert eseguiti == [] and finiti == [1]


def test_una_ferma_prima_di_esegui_non_si_perde():
    """`esegui` azzerava il flag all'ingresso: una `ferma()` arrivata fra la
    costruzione del ciclo e il suo avvio non contava."""
    import time

    from metis.core.avvio import CicloAudio

    class Orch:
        def on_audio(self, b):
            pass

        def tick(self):
            pass

    class Cattura:
        def start(self):
            pass

        def stop(self):
            pass

        def read(self, timeout=0.25):
            time.sleep(0.01)
            return None

    c = CicloAudio(Orch(), apri_cattura=Cattura)
    c.ferma()
    t0 = time.perf_counter()
    c.esegui(limite_s=5)
    assert time.perf_counter() - t0 < 1.0
