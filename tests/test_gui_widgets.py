"""I widget. Il dialogo di conferma vale piu' di tutti gli altri messi
insieme: e' l'unico punto dell'interfaccia in cui un errore manda una email.
"""
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from metis.gui.lag import MisuratoreLag
from metis.gui.widgets.conferma import DialogoConferma
from metis.gui.widgets.conversazione import Conversazione
from metis.gui.widgets.stato import IndicatoreStato, VuMeter
from metis.gui.widgets.telemetria import Telemetria


@pytest.fixture
def qt(app_qt):
    yield app_qt


ARGOMENTI = {"tool": "send_email", "to": "marco@esempio.it",
             "subject": "Riepilogo", "body": "Testo della email."}


def dialogo(timeout=20.0):
    return DialogoConferma("send_email", "T3", ARGOMENTI, timeout)


# --- dialogo di conferma -----------------------------------------------------

def test_invio_non_approva(qt):
    """Vent'anni di finestre di dialogo hanno insegnato a premere Invio
    prima di leggere. Qui quell'abitudine manderebbe la email."""
    d = dialogo()
    decisioni = []
    d.deciso.connect(decisioni.append)
    d.show()
    for tasto in (Qt.Key_Return, Qt.Key_Enter):
        d.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, tasto, Qt.NoModifier))
    assert decisioni == [], "Invio ha deciso qualcosa"
    d.close()


def test_nessun_pulsante_e_predefinito(qt):
    """Senza questo, Invio attiverebbe il pulsante predefinito anche senza
    passare da keyPressEvent."""
    d = dialogo()
    assert not d.approva.isDefault() and not d.approva.autoDefault()
    assert not d.nega.isDefault() and not d.nega.autoDefault()


def test_il_fuoco_parte_su_nega(qt):
    """Una barra spaziatrice premuta per riflesso deve negare."""
    d = dialogo()
    d.show()
    QApplication.processEvents()
    assert d.focusWidget() is d.nega


def test_esc_nega(qt):
    d = dialogo()
    decisioni = []
    d.deciso.connect(decisioni.append)
    d.show()
    d.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert decisioni == [False]


def test_chiudere_la_finestra_e_un_no(qt):
    """Chiudere non e' 'non ho risposto': e' un rifiuto."""
    d = dialogo()
    decisioni = []
    d.deciso.connect(decisioni.append)
    d.show()
    d.close()
    assert decisioni == [False]


def test_approva_e_nega_emettono(qt):
    for premuto, atteso in ((True, [True]), (False, [False])):
        d = dialogo()
        decisioni = []
        d.deciso.connect(decisioni.append)
        (d.approva if premuto else d.nega).click()
        assert decisioni == atteso


def test_si_decide_una_volta_sola(qt):
    """Due clic rapidi non devono produrre due decisioni."""
    d = dialogo()
    decisioni = []
    d.deciso.connect(decisioni.append)
    d.approva.click()
    d.nega.click()
    assert decisioni == [True]


def test_mostra_gli_argomenti_per_intero(qt):
    """'Metis vuole eseguire send_email' non e' un consenso informato."""
    d = dialogo()
    testo = " ".join(w.text() for w in d.findChildren(type(d.nega).__mro__[1])
                     if hasattr(w, "text"))
    tutto = _tutto_il_testo(d)
    assert "marco@esempio.it" in tutto and "Riepilogo" in tutto
    assert "T3" in tutto and "send_email" in tutto


def test_il_conto_alla_rovescia_scende(qt):
    d = dialogo(timeout=2.0)
    primo = d._conto.text()
    d._tic()
    d._tic()
    d._tic()
    d._tic()
    assert d._conto.text() != primo


def test_allo_scadere_il_dialogo_si_chiude_senza_decidere(qt):
    """Chi aspetta ha il proprio timeout e lo fa scattare da solo: emettere
    anche qui sarebbe una seconda sorgente di verita' sullo stesso fatto."""
    d = dialogo(timeout=0.5)
    decisioni = []
    d.deciso.connect(decisioni.append)
    d.show()
    for _ in range(4):
        d._tic()
    assert decisioni == []
    assert not d.isVisible()


def _tutto_il_testo(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return " ".join(w.text() for w in widget.findChildren(QLabel))


# --- conversazione -----------------------------------------------------------

def test_conversazione_accoda(qt):
    c = Conversazione()
    c.utente("ciao")
    c.metis("buongiorno")
    testo = c.testo.toPlainText()
    assert "ciao" in testo and "buongiorno" in testo


def test_il_parziale_viene_sostituito_dal_finale(qt):
    """Il grigio distingue 'ti sto sentendo' da 'ho capito': se restasse,
    la conversazione mostrerebbe due volte la stessa frase."""
    c = Conversazione()
    c.parziale("che ore s")
    c.utente("che ore sono")
    assert c.testo.toPlainText().count("che ore") == 1


def test_lo_stato_sopravvive_al_cambio_vista(qt):
    """Minimal e Fullscreen sono due proiezioni dello stesso modello."""
    c = Conversazione()
    c.utente("prima")
    c.metis("seconda")
    salvato = c.contenuto()
    c2 = Conversazione()
    c2.ripristina(salvato)
    assert "prima" in c2.testo.toPlainText() and "seconda" in c2.testo.toPlainText()


def test_il_testo_pericoloso_non_rompe_l_html(qt):
    c = Conversazione()
    c.utente("<script>alert(1)</script> & <b>")
    assert "<script>" in c.testo.toPlainText()


# --- telemetria --------------------------------------------------------------

def test_soglia_vram_accende_l_allarme(qt):
    t = Telemetria()
    t.aggiorna_risorse({"cpu": 10, "ram_percento": 20, "vram_gb": 7.8,
                        "vram_totale_gb": 8, "vram_allarme": True})
    assert "ef4444" in t.barre["vram"].styleSheet()


def test_sotto_soglia_resta_verde(qt):
    t = Telemetria()
    t.aggiorna_risorse({"cpu": 10, "ram_percento": 20, "vram_gb": 6.5,
                        "vram_totale_gb": 8, "vram_allarme": False})
    assert "22c55e" in t.barre["vram"].styleSheet()


def test_la_finestra_delle_latenze_scorre(qt):
    """Una media da inizio sessione diventa insensibile proprio quando
    servirebbe vedere un peggioramento."""
    t = Telemetria()
    for _ in range(80):
        t.aggiorna_turno({"totale_ms": 1000, "ttft_ms": 100, "tok_per_s": 60})
    assert len(t.latenze) == 50
    for _ in range(50):
        t.aggiorna_turno({"totale_ms": 3000, "ttft_ms": 100, "tok_per_s": 60})
    assert t.valori["p50"].text().startswith("3.0")


def test_le_latenze_oltre_il_target_si_colorano(qt):
    t = Telemetria()
    for _ in range(10):
        t.aggiorna_turno({"totale_ms": 2500, "ttft_ms": 100, "tok_per_s": 60})
    assert "f59e0b" in t.valori["p50"].styleSheet()


# --- indicatore e VU ---------------------------------------------------------

def test_l_indicatore_parla_italiano(qt):
    i = IndicatoreStato()
    i.imposta("ATTESA_CONFERMA")
    assert i.etichetta.text() == "ASPETTA TE"


def test_il_vu_tiene_il_picco_non_l_ultimo(qt):
    """Con l'ultimo valore, un picco caduto fra due ridisegni sparirebbe e
    il VU mostrerebbe meno di quello che il microfono ha sentito."""
    v = VuMeter()
    v.campiona(-50.0, -40.0)
    v.campiona(-10.0, -8.0)
    v.campiona(-55.0, -50.0)
    assert v._picco_grezzo == pytest.approx(-10.0)


# --- misuratore di lag -------------------------------------------------------

def test_il_misuratore_vede_un_blocco_vero(qt):
    """Se non riconoscesse un blocco costruito apposta, non riconoscerebbe
    nemmeno quelli veri, e NFR-8 passerebbe sempre."""
    m = MisuratoreLag(intervallo_ms=10, soglia_ms=50)
    m.avvia()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.15:
        QApplication.processEvents()
    time.sleep(0.25)                      # blocco simulato: nessun evento
    QApplication.processEvents()
    m.ferma()
    assert m.freeze_count >= 1, m.stats()
    assert m.peggiore > 50


def test_senza_blocchi_in_esercizio_nfr8_e_superato(qt):
    m = MisuratoreLag(intervallo_ms=10, soglia_ms=500)
    m.avvia()
    m.cambia_fase("esercizio")
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.2:
        QApplication.processEvents()
    m.ferma()
    assert "NFR-8 SUPERATO" in m.riassunto()
    assert m.stats("esercizio")["campioni"] > 0


def test_un_blocco_in_avvio_non_fa_fallire_nfr8(qt):
    """Caricare tre modelli blocca una volta sola, e NFR-8 parla di freeze
    "durante l'inferenza". Mescolare le due fasi renderebbe il numero
    inutile in entrambe le direzioni: o si fallisce per un blocco che
    nessuno vive come difetto, o lo si nasconde nella media di mezz'ora.
    """
    m = MisuratoreLag(intervallo_ms=10, soglia_ms=50)
    m.avvia()
    time.sleep(0.2)                       # blocco durante l'avvio
    QApplication.processEvents()
    m.cambia_fase("esercizio")
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.2:
        QApplication.processEvents()
    m.ferma()

    assert m.stats("avvio")["freeze_oltre_soglia"] >= 1
    assert m.stats("esercizio")["freeze_oltre_soglia"] == 0
    r = m.riassunto()
    assert "NFR-8 SUPERATO" in r
    assert "avvio a" in r, "il blocco dell'avvio va riportato, non nascosto"


def test_un_blocco_in_esercizio_fa_fallire_nfr8(qt):
    m = MisuratoreLag(intervallo_ms=10, soglia_ms=50)
    m.avvia()
    m.cambia_fase("esercizio")
    QApplication.processEvents()
    time.sleep(0.2)
    QApplication.processEvents()
    m.ferma()
    assert "NFR-8 FALLITO" in m.riassunto()


def test_nessun_campione_non_esplode(qt):
    assert MisuratoreLag().stats() == {"campioni": 0}


# --- le due viste sono due proiezioni, non due applicazioni -----------------

@pytest.fixture
def applicazione(qt):
    """Costruita senza avviare i thread: qui interessa il cablaggio, non
    il nucleo. Con `tools=False` non tocca ne' Ollama ne' il microfono."""
    from metis.core.avvio import Opzioni
    from metis.gui.app import Applicazione

    a = Applicazione(Opzioni(tools=False, wakeword=False))
    yield a
    a.hotkeys.stop()


def test_il_passaggio_fra_viste_non_perde_la_conversazione(applicazione):
    a = applicazione
    a.conversazione.utente("che ore sono")
    a.conversazione.metis("Sono le undici e dodici.")

    a.mostra_fullscreen()
    assert a.fullscreen.isVisible() and not a.minimal.isVisible()
    a.mostra_minimal()
    assert a.minimal.isVisible() and not a.fullscreen.isVisible()
    a.mostra_fullscreen()

    testo = a.conversazione.testo.toPlainText()
    assert "che ore sono" in testo and "undici e dodici" in testo


def test_il_passaggio_non_perde_le_metriche(applicazione):
    a = applicazione
    for _ in range(5):
        a.cruscotto.aggiorna_turno({"totale_ms": 1100, "ttft_ms": 300, "tok_per_s": 60})
    prima = a.cruscotto.valori["p50"].text()
    a.mostra_fullscreen()
    a.mostra_minimal()
    a.mostra_fullscreen()
    assert a.cruscotto.valori["p50"].text() == prima
    assert len(a.cruscotto.latenze) == 5


def test_i_widget_sono_gli_stessi_oggetti(applicazione):
    """Se fossero due copie, il passaggio sarebbe un riavvio travestito e
    prima o poi qualcuno dimenticherebbe di ricopiare un pezzo."""
    a = applicazione
    assert a.fullscreen.conversazione is a.conversazione
    assert a.fullscreen.telemetria is a.cruscotto


def test_lo_stato_arriva_a_entrambe_le_viste(applicazione):
    a = applicazione
    a.nucleo.stato.emit("IN_ASCOLTO", "PTT", "PARLATO")
    QApplication.processEvents()
    assert a.minimal.indicatore.stato == "PARLATO"
    assert a.fullscreen.indicatore.stato == "PARLATO"


def test_il_kill_switch_si_vede_in_entrambe(applicazione):
    a = applicazione
    a.segnali.kill_cambiato.emit(True)
    QApplication.processEvents()
    assert a.minimal.kill.isVisible() or a.minimal.kill.isVisibleTo(a.minimal)
    a.segnali.kill_cambiato.emit(False)
    QApplication.processEvents()
    assert not a.minimal.kill.isVisibleTo(a.minimal)
