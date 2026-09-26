"""PHASE1 — il nucleo animato e l'onda che segue la voce.

Che sia bello lo dice l'utente guardando `benchmarks/gui_screenshot.py
--nucleo`. Qui si prova quello che guardando non si vede:

- con la finestra nascosta il nucleo non si ridisegna nemmeno una volta
  (72 ore in tray);
- l'onda segue la voce di Metis letta dal player, non il motore e non il
  microfono;
- il microfono muove il nucleo solo quando Metis ascolta davvero.
"""
import time

import numpy as np
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from metis.core.palette import esadecimale
from metis.tts import kokoro_engine as k


def _gira(secondi=0.0, n=10):
    fine = time.perf_counter() + secondi
    while True:
        for _ in range(n):
            QApplication.processEvents()
        if time.perf_counter() >= fine:
            return
        time.sleep(0.01)


# --- l'inviluppo della voce --------------------------------------------------------------

def _silenzio_tono_silenzio(sr, secondi=0.3, ampiezza=0.5):
    n = int(sr * secondi)
    t = np.arange(n) / sr
    tono = (ampiezza * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    zeri = np.zeros(n, np.float32)
    return np.concatenate([zeri, tono, zeri])


def test_l_inviluppo_segue_il_segnale():
    sr = 16000
    livelli = k.inviluppo(_silenzio_tono_silenzio(sr), sr)
    assert livelli.size == 45                        # 0,9 s a passi di 20 ms
    assert np.all(livelli[:15] == k.SILENZIO_DB)
    atteso = 20 * np.log10(0.5 / np.sqrt(2))         # RMS di un seno: -9 dBFS
    assert np.allclose(livelli[16:29], atteso, atol=0.3)
    assert np.all(livelli[31:] == k.SILENZIO_DB)


def test_l_inviluppo_di_una_frase_vuota_e_vuoto():
    assert k.inviluppo(np.zeros(0, np.float32), 22050).size == 0


def test_l_ultima_finestra_corta_non_si_perde():
    livelli = k.inviluppo(np.full(330, 0.5, np.float32), 16000)   # 20 ms + 10 di resto
    assert livelli.size == 2 and livelli[1] < livelli[0]


class SdCronometrato:
    """`sounddevice` finto che impiega il tempo vero della frase: il livello
    si legge DURANTE la riproduzione, come nell'applicazione."""

    def __init__(self, sr):
        self.sr = sr
        self.durata = 0.0
        self.fermato = False

    def play(self, pcm, sr):
        self.durata = pcm.size / sr
        self.fermato = False

    def wait(self):
        fine = time.perf_counter() + self.durata
        while time.perf_counter() < fine and not self.fermato:
            time.sleep(0.002)

    def stop(self):
        self.fermato = True


@pytest.fixture
def player(monkeypatch):
    sr = 16000
    monkeypatch.setattr(k, "sd", SdCronometrato(sr))
    p = k.Player(sample_rate=sr)
    p.start()
    yield p
    p.close()


def _leggi_a(p, t0, istante):
    while time.perf_counter() - t0 < istante:
        time.sleep(0.002)
    return p.livello_uscita()


def test_durante_la_riproduzione_il_livello_segue_la_frase(player):
    """Il test del piano: silenzio, tono, silenzio. Si legge a meta' di ogni
    tratto, con 150 ms di margine per lo scheduler."""
    assert player.livello_uscita() == k.SILENZIO_DB          # niente in coda
    player.enqueue(_silenzio_tono_silenzio(16000))
    while not player.speaking.is_set():
        time.sleep(0.001)
    t0 = time.perf_counter()
    letti = [_leggi_a(player, t0, s) for s in (0.15, 0.45, 0.75)]
    assert letti[0] == k.SILENZIO_DB
    assert -10.0 < letti[1] < -8.0
    assert letti[2] == k.SILENZIO_DB
    assert player.wait_drained(timeout=3.0)
    assert player.livello_uscita() == k.SILENZIO_DB


def test_dopo_lo_stop_il_livello_e_silenzio(player):
    player.enqueue(np.full(16000, 0.5, np.float32))
    while player.livello_uscita() == k.SILENZIO_DB:
        time.sleep(0.001)
    player.stop()
    assert player.livello_uscita() == k.SILENZIO_DB


def test_in_muto_l_onda_non_si_muove(player):
    """Muto vuol dire che non suona niente: un'onda che si muove direbbe
    il contrario."""
    player.imposta_muto(True)
    player.enqueue(np.full(16000, 0.5, np.float32))
    for _ in range(20):
        assert player.livello_uscita() == k.SILENZIO_DB
        time.sleep(0.005)


def test_zittito_a_meta_frase_l_onda_si_ferma(player):
    player.enqueue(np.full(16000, 0.5, np.float32))
    while player.livello_uscita() == k.SILENZIO_DB:
        time.sleep(0.001)
    player.imposta_muto(True)
    assert player.livello_uscita() == k.SILENZIO_DB


# --- il worker: dal player al segnale ----------------------------------------------------

def test_il_worker_spedisce_la_voce_solo_mentre_parla():
    from metis.core.avvio import Opzioni
    from metis.gui.workers.nucleo import Nucleo

    letture = iter([k.SILENZIO_DB, k.SILENZIO_DB, -20.0, -18.0, k.SILENZIO_DB,
                    k.SILENZIO_DB, k.SILENZIO_DB])

    class Player:
        def livello_uscita(self):
            return next(letture)

    class Sistema:
        player = Player()

    n = Nucleo(Opzioni(tools=False, wakeword=False))
    n.sistema = Sistema()
    spediti = []
    n.voce.connect(spediti.append)
    for _ in range(7):
        n._voce()
    # A riposo niente; poi la frase, e un solo silenzio per chiudere.
    assert spediti == [-20.0, -18.0, k.SILENZIO_DB]


def test_il_worker_senza_sistema_non_spedisce_niente():
    from metis.core.avvio import Opzioni
    from metis.gui.workers.nucleo import Nucleo

    n = Nucleo(Opzioni(tools=False, wakeword=False))
    spediti = []
    n.voce.connect(spediti.append)
    n._voce()
    assert spediti == []


# --- il widget --------------------------------------------------------------------------

class Orologio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def nucleo(app_qt):
    from metis.gui.widgets.nucleo import Nucleo

    n = Nucleo()
    n.resize(340, 340)
    yield n
    n.hide()
    n.deleteLater()


def _fotogrammi(n, orologio, secondi, fps=30):
    for _ in range(int(secondi * fps)):
        orologio.t += 1 / fps
        n._fotogramma()


def test_visibile_si_anima_nascosto_no(nucleo):
    nucleo.show()
    _gira(0.2)
    assert nucleo.animato() and nucleo.disegni > 0


def test_nascosto_zero_ridisegni(nucleo):
    """Il criterio di uscita: con la finestra nascosta, nemmeno un ridisegno.
    Anche se intanto arrivano stati e livelli, come in esercizio."""
    nucleo.show()
    _gira(0.1)
    nucleo.hide()
    _gira()
    prima = nucleo.disegni
    for stato in ("IN_ASCOLTO", "ELABORAZIONE", "PARLATO", "INTERROTTO", "DORMIENTE"):
        nucleo.imposta_stato(stato)
        nucleo.campiona_microfono(-15.0)
        nucleo.campiona_voce(-15.0)
        _gira(0.06)
    nucleo.imposta_kill(True)
    nucleo.imposta_pausa(True)
    nucleo.imposta_pausa(False)
    _gira(0.1)
    assert not nucleo.animato()
    assert nucleo.disegni == prima


def test_ridotta_a_icona_non_si_anima(nucleo):
    """Qt manda un hideEvent "spontaneo" quando la finestra va a icona; qui
    lo si manda a mano, perche' la piattaforma offscreen non ha icone."""
    from PySide6.QtGui import QHideEvent, QShowEvent

    nucleo.show()
    _gira(0.05)
    QApplication.sendEvent(nucleo, QHideEvent())
    assert not nucleo.animato()
    QApplication.sendEvent(nucleo, QShowEvent())
    assert nucleo.animato()


def test_in_pausa_si_ferma_e_riparte(nucleo):
    nucleo.show()
    _gira(0.05)
    nucleo.imposta_pausa(True)
    assert not nucleo.animato()
    nucleo.imposta_pausa(False)
    assert nucleo.animato()


def test_un_lampo_in_pausa_finisce_poi_si_ferma(nucleo):
    orologio = Orologio()
    nucleo._orologio = orologio
    nucleo.show()
    nucleo.imposta_pausa(True)
    nucleo.imposta_stato("ERRORE")
    assert nucleo.animato()                   # il lampo si vede anche in pausa
    _fotogrammi(nucleo, orologio, 1.0)
    assert not nucleo.animato()


def test_riduci_animazioni_ferma_il_timer_ma_non_lo_stato(nucleo):
    nucleo.show()
    _gira(0.05)
    nucleo.imposta_animazioni(False)
    assert not nucleo.animato()
    nucleo.imposta_stato("ATTESA_CONFERMA")
    assert not nucleo.animato()
    _gira()
    assert nucleo.colore() == esadecimale("ATTESA_CONFERMA")
    nucleo.imposta_animazioni(True)
    assert nucleo.animato()


def test_in_parlato_l_ampiezza_segue_la_voce(nucleo):
    orologio = Orologio()
    nucleo._orologio = orologio
    nucleo.imposta_stato("PARLATO")
    nucleo.campiona_voce(-10.0)
    nucleo.campiona_microfono(-60.0)
    _fotogrammi(nucleo, orologio, 0.3)
    assert nucleo.livello > 0.8
    nucleo.campiona_voce(k.SILENZIO_DB)
    _fotogrammi(nucleo, orologio, 0.1)
    alto = nucleo.livello
    _fotogrammi(nucleo, orologio, 1.0)
    # Scende piano (non trema), ma scende.
    assert 0.2 < alto < 0.8 and nucleo.livello < 0.02


def test_il_microfono_muove_il_nucleo_solo_in_ascolto(nucleo):
    """In DORMIENTE Metis non ascolta: un nucleo che balla con la voce di chi
    e' nella stanza direbbe il falso."""
    orologio = Orologio()
    nucleo._orologio = orologio
    nucleo.campiona_microfono(-15.0)
    for stato in ("DORMIENTE", "ELABORAZIONE", "PARLATO", "ATTESA_CONFERMA"):
        nucleo.imposta_stato(stato)
        _fotogrammi(nucleo, orologio, 0.3)
        assert nucleo.livello < 0.01, stato
    nucleo.imposta_stato("IN_ASCOLTO")
    _fotogrammi(nucleo, orologio, 0.3)
    assert nucleo.livello > 0.8


def test_in_pausa_il_microfono_non_conta(nucleo):
    orologio = Orologio()
    nucleo._orologio = orologio
    nucleo.imposta_stato("IN_ASCOLTO")
    nucleo.imposta_pausa(True)
    nucleo.campiona_microfono(-15.0)
    _fotogrammi(nucleo, orologio, 0.3)
    assert nucleo.livello < 0.01


def test_il_lampo_dura_oltre_lo_stato(nucleo):
    """INTERROTTO dura pochi millisecondi: senza il lampo, non lo vedrebbe
    nessuno."""
    orologio = Orologio()
    nucleo._orologio = orologio
    nucleo.imposta_stato("INTERROTTO")
    nucleo.imposta_stato("IN_ASCOLTO")
    assert nucleo._lampo_attivo(orologio.t)
    assert nucleo._lampo[1].name() == esadecimale("INTERROTTO")
    orologio.t += 0.8
    assert not nucleo._lampo_attivo(orologio.t)


def test_il_colore_sfuma_ma_arriva(nucleo):
    orologio = Orologio()
    nucleo._orologio = orologio
    nucleo.imposta_stato("PARLATO")
    orologio.t += 1.0
    nucleo.imposta_stato("ERRORE")
    assert nucleo._colore_corrente(orologio.t).name() == esadecimale("PARLATO")
    orologio.t += 0.3
    assert nucleo._colore_corrente(orologio.t).name() == esadecimale("ERRORE")


def test_due_cambi_ravvicinati_non_fanno_saltare_il_colore(nucleo):
    orologio = Orologio()
    nucleo._orologio = orologio
    nucleo.imposta_stato("PARLATO")
    orologio.t += 1.0
    nucleo.imposta_stato("ERRORE")
    orologio.t += 0.1                               # a meta' sfumatura
    a_meta = nucleo._colore_corrente(orologio.t).name()
    nucleo.imposta_stato("IN_ASCOLTO")
    assert nucleo._colore_corrente(orologio.t).name() == a_meta


@pytest.mark.parametrize("lato", [64, 96, 340, 440])
def test_si_disegna_in_ogni_stato_e_misura(nucleo, lato):
    """Ogni stato, con pausa, kill switch e animazioni ridotte, grande e in
    miniatura (la Minimal lo usera' a 64 px)."""
    nucleo.setMinimumSize(1, 1)
    nucleo.resize(lato, lato)
    nucleo.campiona_microfono(-20.0)
    nucleo.campiona_voce(-20.0)
    nucleo.livello = 0.7
    stati = ("DORMIENTE", "IN_ASCOLTO", "TRASCRIZIONE", "ELABORAZIONE", "GENERAZIONE",
             "RICERCA_WEB", "ESECUZIONE", "ATTESA_CONFERMA", "PARLATO", "INTERROTTO",
             "ERRORE")
    prima = nucleo.disegni
    for animazioni in (True, False):
        nucleo.imposta_animazioni(animazioni)
        for kill, pausa in ((False, False), (True, False), (False, True)):
            nucleo.imposta_kill(kill)
            nucleo.imposta_pausa(pausa)
            for stato in stati:
                nucleo.imposta_stato(stato)
                assert not nucleo.grab().isNull()
    assert nucleo.disegni - prima == 2 * 3 * len(stati)
    assert len(nucleo.tempi_ms) > 0 and nucleo.p95_ms() > 0


# --- nell'Hub e nell'applicazione ------------------------------------------------------

def test_il_nucleo_cresce_con_la_finestra(app_qt):
    from metis.gui.hub_view import NUCLEO_MAX, NUCLEO_MIN, HubView
    from metis.gui.modello_conversazione import ModelloConversazione

    h = HubView(ModelloConversazione())
    try:
        lati = []
        for w, a in ((1000, 660), (1280, 720), (1920, 1080), (2560, 1440)):
            h.resize(w, a)
            h.show()
            _gira()
            lati.append(h.nucleo.width())
            assert h.nucleo.width() == h.nucleo.height()
        assert lati == sorted(lati)
        assert NUCLEO_MIN <= lati[0] and lati[-1] == NUCLEO_MAX
        assert lati[1] == int(720 * 0.40)
    finally:
        h.hide()
        h.deleteLater()


def test_i_livelli_arrivano_al_nucleo_dell_hub(crea_applicazione):
    a = crea_applicazione()
    a.nucleo.livello.emit(-21.0, -9.0)
    a.nucleo.voce.emit(-17.0)
    _gira()
    assert a.hub.nucleo._microfono_db == -21.0
    assert a.hub.nucleo._voce_db == -17.0


def test_cambiando_vista_il_nucleo_dell_hub_si_ferma(crea_applicazione):
    a = crea_applicazione()
    a.mostra_hub()
    _gira(0.1)
    assert a.hub.nucleo.animato()
    a.mostra_minimal()
    _gira()
    prima = a.hub.nucleo.disegni
    _gira(0.2)
    assert not a.hub.nucleo.animato() and a.hub.nucleo.disegni == prima
    a.mostra_fullscreen()
    _gira()
    assert not a.hub.nucleo.animato()
    a.mostra_hub()
    _gira()
    assert a.hub.nucleo.animato()


def test_evento_di_uscita_non_lascia_timer(app_qt):
    """Distrutto il widget, il timer va con lui: niente callback su un
    oggetto morto."""
    from metis.gui.widgets.nucleo import Nucleo

    n = Nucleo()
    n.show()
    _gira(0.05)
    timer = n._timer
    n.deleteLater()
    app_qt.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    _gira(0.05)
    import shiboken6

    assert not shiboken6.isValid(timer)
