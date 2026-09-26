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
from metis.gui import tema
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
    from PySide6.QtWidgets import QLabel, QPlainTextEdit

    etichette = [w.text() for w in widget.findChildren(QLabel)]
    riquadri = [w.toPlainText() for w in widget.findChildren(QPlainTextEdit)]
    return " ".join(etichette + riquadri)


def test_il_corpo_lungo_si_vede_per_intero(qt):
    """M6: fino a qui il dialogo tagliava ogni valore a 400 caratteri, e la
    sua docstring diceva "argomenti interi". Con l'email vera la differenza
    e' diventata concreta: si approverebbe un messaggio letto a meta'.

    La coda del corpo e' la parte che conta — e' li' che un testo
    "innocuo" per quattrocento caratteri puo' diventare altro."""
    corpo = ("Riga innocua di apertura. " * 40) + "CODA CHE DEVE ESSERE LETTA"
    d = DialogoConferma("send_email", "T3",
                        {"a": "marco@esempio.it", "corpo": corpo}, 20.0)
    assert len(corpo) > 1000
    assert "CODA CHE DEVE ESSERE LETTA" in _tutto_il_testo(d)
    assert d.riquadri, "il corpo lungo non e' finito in un riquadro che scorre"


def test_non_si_dice_non_si_annulla_quando_non_e_vero(qt):
    """Un promemoria T1 chiede conferma della data ma si cancella con una
    frase. Dirgli "NON si annulla" insegnerebbe a non credere all'avviso
    proprio quando e' vero."""
    t1 = _tutto_il_testo(DialogoConferma("schedule_reminder", "T1",
                                         {"quando": "domani"}, 20.0))
    t3 = _tutto_il_testo(DialogoConferma("send_email", "T3", {"a": "x"}, 20.0))
    assert "NON si annulla" not in t1
    assert "NON si annulla" in t3


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
    # PHASE1: il gettone, non il valore — la palette e' cambiata, il rosso no.
    assert tema.ERRORE in t.barre["vram"].styleSheet()


def test_sotto_soglia_resta_verde(qt):
    t = Telemetria()
    t.aggiorna_risorse({"cpu": 10, "ram_percento": 20, "vram_gb": 6.5,
                        "vram_totale_gb": 8, "vram_allarme": False})
    assert tema.OK in t.barre["vram"].styleSheet()


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
    assert tema.ATTENZIONE in t.valori["p50"].styleSheet()


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
def applicazione(qt, crea_applicazione):
    """Costruita senza avviare i thread: qui interessa il cablaggio, non
    il nucleo. Con `tools=False` non tocca ne' Ollama ne' il microfono.
    Smontata da `crea_applicazione`, in conftest.py."""
    return crea_applicazione()


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


# --- M4: l'editor dei comandi custom ----------------------------------------

@pytest.fixture
def editor(qt, tmp_path):
    from metis.gui.widgets.comandi import EditorComandi
    from metis.memory.commands import Libreria
    from metis.tools.registry import carica_tutti

    percorso = tmp_path / "commands.json"
    percorso.write_text('{"comandi": []}', encoding="utf-8")
    lib = Libreria(carica_tutti(), percorso)
    e = EditorComandi(lib)
    yield e, lib, percorso
    e.close()


def _compila(e, ident, frasi, azioni, risposta=""):
    e._nuovo()
    e.campo_id.setText(ident)
    e.campo_frasi.setPlainText(frasi)
    e.campo_azioni.setPlainText(azioni)
    e.campo_risposta.setText(risposta)


def test_l_editor_salva_un_comando_valido(editor):
    e, lib, percorso = editor
    _compila(e, "caffe", "fai il caffe", '[{"tool": "get_telemetry"}]')
    e._salva()
    assert [c.id for c in lib] == ["caffe"]
    assert "caffe" in percorso.read_text(encoding="utf-8")
    assert "Salvato" in e.esito.text()


def test_uno_strumento_inesistente_non_si_salva(editor):
    """Criterio di uscita di M4. L'errore deve comparire NELL'EDITOR: un
    comando rotto scoperto a voce fra tre settimane non si collega piu' al
    momento in cui lo si e' scritto."""
    e, lib, percorso = editor
    prima = percorso.read_text(encoding="utf-8")
    _compila(e, "rotto", "fai la cosa",
             '[{"tool": "delete_file", "path": "C:/"}]')
    e._salva()
    assert len(lib) == 0
    assert percorso.read_text(encoding="utf-8") == prima
    assert "non esiste" in e.esito.text() and "delete_file" in e.esito.text()


def test_argomenti_sbagliati_non_si_salvano(editor):
    e, lib, _ = editor
    _compila(e, "x", "prova",
             '[{"tool": "open_application", "app": "photoshop"}]')
    e._salva()
    assert len(lib) == 0 and "argomenti non validi" in e.esito.text()


def test_json_malformato_lo_dice_invece_di_esplodere(editor):
    e, lib, _ = editor
    _compila(e, "x", "prova", '[{"tool": "get_telemetry"')
    e._salva()
    assert len(lib) == 0 and "JSON" in e.esito.text()


def test_una_azione_sola_senza_parentesi_quadre_viene_accettata(editor):
    """Errore frequente e privo di ambiguita': si accetta e si continua."""
    e, lib, _ = editor
    _compila(e, "x", "prova", '{"tool": "get_telemetry"}')
    e._salva()
    assert len(lib) == 1


def test_il_router_vede_il_comando_senza_riavvio(editor):
    """L'altro criterio di uscita: ricarica a caldo. Nessun segnale, nessun
    riavvio — il router conta le ricariche della libreria."""
    from metis.core.router import Router

    e, lib, _ = editor
    r = Router(lib.registry, libreria=lib, usa_llm=False)
    assert r.fast_path("fai il caffe") is None

    _compila(e, "caffe", "fai il caffe", '[{"tool": "get_telemetry"}]')
    e._salva()
    assert r.fast_path("per favore fai il caffe") is not None


def test_l_elenco_si_aggiorna_dopo_il_salvataggio(editor):
    e, lib, _ = editor
    assert e.elenco.count() == 0
    _compila(e, "uno", "prova uno", '[{"tool": "get_telemetry"}]')
    e._salva()
    assert e.elenco.count() == 1


def test_l_editor_mostra_gli_strumenti_disponibili(editor):
    """Scrivere JSON a memoria e' un'altra cosa."""
    e, lib, _ = editor
    testo = e.strumenti.text()
    assert "click_element" in testo and "T2" in testo
    # Fino a M5 qui si verificava che `send_email` NON comparisse, perche'
    # non aveva un corpo. In M6 l'ha avuto: compare, e compare come T3.
    assert "send_email" in testo and "T3" in testo


# --- M5: il pannello del contesto --------------------------------------------

def _pannello(app_qt):
    from metis.gui.widgets.contesto import PannelloContesto

    return PannelloContesto()


def test_il_pannello_contesto_parte_vuoto_senza_rompersi(app_qt):
    """Si costruisce prima che il sistema esista: all'avvio il nucleo non ha
    ancora una memoria, e il pannello riceve un dizionario vuoto."""
    p = _pannello(app_qt)
    assert "nessun riferimento attivo" in p.slot.text()
    assert "nessuna fonte" in p.fonti.text()


def test_il_pannello_contesto_mostra_le_voci_del_budget(app_qt):
    p = _pannello(app_qt)
    p.aggiorna({"conteggio": {"system": 600, "slot": 40, "riassunto": 0,
                              "turni": 900, "web": 3400, "totale": 4940},
                "slot": "[CONTESTO CORRENTE]\nFinestra di riferimento: Chrome",
                "fonti": ["https://a.it/x", "https://b.it/y"], "riassunti": 2})
    assert "4940" in p.totale.text() and "2 riassunti" in p.totale.text()
    assert "Chrome" in p.slot.text()
    assert "b.it/y" in p.fonti.text() and "https://b.it/y" in p.fonti.toolTip()
    assert "web 3400" in p.legenda.text()


def test_le_voci_a_zero_non_occupano_la_barra(app_qt):
    """Una voce da zero token deve sparire, non diventare una scheggia di un
    pixel che sembra un valore piccolo."""
    p = _pannello(app_qt)
    p.aggiorna({"conteggio": {"system": 600, "slot": 0, "riassunto": 0,
                              "turni": 300, "web": 0, "totale": 900}})
    assert not p._segmenti["web"].isVisibleTo(p)
    assert p._segmenti["system"].isVisibleTo(p)


def test_le_fonti_sono_dichiarate_non_fidate(app_qt):
    """Chi guarda il pannello deve vedere che quel testo non e' di Metis: e'
    l'unica voce del contesto che non ha scritto nessuno di cui ci si fida."""
    p = _pannello(app_qt)
    p.aggiorna({"conteggio": {"totale": 10}, "fonti": ["https://a.it/x"]})
    assert "non fidato" in p.fonti.text()


def test_aggiornare_il_contesto_costa_quasi_niente(app_qt):
    """NFR-8 come test di regressione, non come misura.

    Il pannello si aggiorna due volte al secondo sul thread della GUI, e il
    conteggio dei token gira sul thread del nucleo a ogni blocco audio. Oggi
    e' una divisione su sedici messaggi: 0,14 ms misurati, contro una soglia
    di 100. Il giorno in cui `conta_token` diventasse un tokenizzatore vero —
    che e' l'ottimizzazione ovvia da fare, e quella che rovinerebbe NFR-8 —
    questo test cadrebbe prima che qualcuno se ne accorga usando Metis.
    """
    import time

    from metis.gui.widgets.contesto import PannelloContesto
    from metis.llm.prompts import SYSTEM
    from metis.memory.conversation import Memoria
    from metis.memory.slots import Slots

    mem = Memoria(system=SYSTEM)
    for i in range(40):
        mem.aggiungi("user", f"Domanda {i} " + "x" * 300)
        mem.aggiungi("assistant", f"Risposta {i} " + "y" * 300)
    slots = Slots()
    slots.vista_finestra("Chrome - Investing.com", "chrome.exe", 1)
    p = PannelloContesto()

    peggiore = 0.0
    for _ in range(50):
        t0 = time.perf_counter()
        blocco = slots.blocco()
        p.aggiorna({"conteggio": mem.conteggio(blocco, fonti="f" * 10000)
                    .come_dizionario(),
                    "slot": blocco, "riassunti": 0,
                    "fonti": ["https://a.it/x"]})
        peggiore = max(peggiore, (time.perf_counter() - t0) * 1000)

    assert peggiore < 10.0, f"{peggiore:.1f} ms per aggiornamento: un decimo di NFR-8"


# --- NFR-8: il lavoro DIFFERITO è quello che blocca ---------------------------

def _riempi_audit(path, n=200):
    from metis.security.audit import AuditLog, Entry, Outcome, Tier

    a = AuditLog(path)
    for i in range(n):
        a.record(Entry(tool="move_window_to_monitor", tier=Tier.T0,
                       args={"window": "Chrome"}, outcome=Outcome.OK,
                       stage="esecuzione",
                       detail=f"eseguito, riga numero {i} con un motivo lungo "
                              "quanto quelli veri"))
    return a


def test_la_vista_audit_non_blocca_l_interfaccia(app_qt, tmp_path):
    """La regressione che ha reso la GUI inutilizzabile in M5, in forma di test.

    Due ingredienti, e mancavano tutti e due alla prima versione di questo
    test — che infatti passava sul codice difettoso.

    **`processEvents()`.** Senza, `ricarica()` misura 3 ms e sembra tutto a
    posto: il lavoro vero — la rimisura di ogni colonna provocata da
    `ResizeToContents` a ogni `setItem` — è DIFFERITO all'event loop. Un test
    che non fa girare l'event loop non misura il costo di un widget, misura
    il costo di chiamare un metodo.

    **Non il primo disegno.** Su una tabella vuota riempire 200 righe costa
    11 ms; dal secondo disegno in poi, con le righe già lì da sostituire,
    costa **8 secondi**. Misurare solo il primo giro nasconde esattamente il
    caso che si verifica dal vivo, dove la tabella si ridisegna una volta al
    secondo per tutta la sessione.
    """
    import time

    from metis.gui import tema
    from metis.security.audit import Entry, Outcome, Tier

    from metis.gui.widgets.audit import VistaAudit

    audit = _riempi_audit(tmp_path / "a.db")
    v = VistaAudit(audit)
    # Il foglio di stile fa parte della misura: sotto QStyleSheetStyle ogni
    # calcolo di dimensione costa molto di più, ed è la condizione vera.
    v.setStyleSheet(tema.foglio())   # PHASE1: il foglio di tutta l'app
    v.resize(1200, 300)
    v.show()
    app_qt.processEvents()
    v.ricarica()                      # primo disegno: quello facile
    app_qt.processEvents()

    peggiore = 0.0
    for i in range(3):
        # Una riga nuova a ogni giro: è il caso vero, l'audit log cresce
        # mentre Metis lavora, e ogni riga nuova forza un ridisegno.
        audit.record(Entry(tool="web_search", tier=Tier.T0, args={},
                           outcome=Outcome.OK, stage="esecuzione",
                           detail=f"eseguito {i}"))
        t0 = time.perf_counter()
        v.ricarica()
        app_qt.processEvents()
        peggiore = max(peggiore, (time.perf_counter() - t0) * 1000)

    assert peggiore < 100.0, (
        f"{peggiore:.0f} ms per ridisegnare 200 righe: NFR-8 chiede meno di 100")


def test_la_vista_audit_non_ridisegna_se_non_e_cambiato_niente(app_qt, tmp_path):
    """Il caso normale: il timer batte ogni secondo e l'audit log cresce di
    qualche riga al minuto. Cinquantanove battiti su sessanta non hanno
    niente da fare, e devono costare zero."""
    from metis.gui.widgets.audit import VistaAudit

    a = _riempi_audit(tmp_path / "a.db", n=50)
    v = VistaAudit(a)
    v.show()
    app_qt.processEvents()
    v.ricarica()
    dopo_il_primo = v.ridisegni

    for _ in range(20):
        v.ricarica()
    assert v.ridisegni == dopo_il_primo, "ha ridisegnato senza righe nuove"

    from metis.security.audit import Entry, Outcome, Tier

    a.record(Entry(tool="web_search", tier=Tier.T0, args={},
                   outcome=Outcome.OK, stage="esecuzione", detail="eseguito"))
    v.ricarica()
    assert v.ridisegni == dopo_il_primo + 1, "non ha visto la riga nuova"


def test_il_pannello_contesto_non_blocca_l_interfaccia(app_qt):
    """La stessa misura di `test_aggiornare_il_contesto_costa_quasi_niente`,
    ma con l'event loop che gira. La prima versione di quel test non lo
    faceva, e per questo ha lasciato passare il blocco della vista audit."""
    import time

    from metis.gui import tema
    from metis.gui.widgets.contesto import PannelloContesto
    from metis.llm.prompts import SYSTEM
    from metis.memory.conversation import Memoria
    from metis.memory.slots import Slots

    mem = Memoria(system=SYSTEM)
    for i in range(40):
        mem.aggiungi("user", f"Domanda {i} " + "x" * 300)
        mem.aggiungi("assistant", f"Risposta {i} " + "y" * 300)
    slots = Slots()
    slots.vista_finestra("Chrome - Investing.com", "chrome.exe", 1)

    p = PannelloContesto()
    p.setStyleSheet(tema.foglio())   # PHASE1: il foglio di tutta l'app
    p.resize(400, 300)
    p.show()
    app_qt.processEvents()

    peggiore = 0.0
    for _ in range(30):
        t0 = time.perf_counter()
        blocco = slots.blocco()
        p.aggiorna({"conteggio": mem.conteggio(blocco, fonti="f" * 10000)
                    .come_dizionario(),
                    "slot": blocco, "riassunti": 0,
                    "fonti": ["https://a.it/x"]})
        app_qt.processEvents()
        peggiore = max(peggiore, (time.perf_counter() - t0) * 1000)

    assert peggiore < 100.0, f"{peggiore:.0f} ms per aggiornamento: NFR-8"


# --- M7: testo lungo che allargava la finestra -------------------------------------

LINK_BING = ("https://www.bing.com/aclick?ld=e8" + "7G1qS5Cs3bZcU-1FQBLKqTVUCUwj8UNEw" * 45
             + "&u=aHR0cHM6Ly9jaC5qb29ibGUub3JnL2l0")


def test_url_breve_tiene_dominio_e_inizio():
    from metis.gui.testo import url_breve

    b = url_breve(LINK_BING)
    assert b.startswith("bing.com/aclick?ld=") and b.endswith("…")
    assert len(b) <= 70
    assert url_breve("https://ch.jooble.org/it/") == "ch.jooble.org/it"


def test_le_parole_lunghe_diventano_spezzabili():
    from metis.gui.testo import ZWSP, spezzabile

    s = spezzabile("corto " + "x" * 100)
    assert s.startswith("corto ") and s.count(ZWSP) == 2
    assert spezzabile("niente da spezzare qui") == "niente da spezzare qui"


def test_un_link_enorme_non_allarga_la_control_room(app_qt):
    """Il caso reale: annunci di lavoro cercati dalla control room, un link
    di tracciamento di Bing fra le fonti e negli slot. La finestra si
    allargava oltre lo schermo e la conversazione finiva a una lettera per
    riga. La larghezza minima non deve dipendere dal testo mostrato."""
    from metis.gui.fullscreen_view import FullscreenView
    from metis.gui.widgets.conversazione import Conversazione
    from metis.gui.widgets.telemetria import Telemetria

    v = FullscreenView(Conversazione(), Telemetria())
    v.resize(1400, 900)
    v.show()              # senza show il layout non si ricalcola e il test non vede niente
    try:
        app_qt.processEvents()
        conv = v.conversazione.width()
        v.contesto.aggiorna({"slot": f"[CONTESTO CORRENTE]\nUltima fonte: {LINK_BING}",
                             "fonti": [LINK_BING, "https://ch.jooble.org/it/"]})
        v.imposta_corrente(f"Ecco il link: {LINK_BING}")
        for _ in range(20):
            app_qt.processEvents()
        # Misurato senza la correzione: finestra a 11 767 px, conversazione a 102.
        assert v.width() == 1400
        assert v.conversazione.width() == conv
        assert v.contesto.fonti.toolTip().startswith(LINK_BING)   # l'URL intero c'e' ancora
    finally:
        v.hide()
