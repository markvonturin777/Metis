"""PHASE1, giorni 11-12 — Minimal e Diagnostica con il nuovo tema.

Il contenuto delle due viste e' quello di PHASE0, e i suoi test (M3) restano
dove sono. Qui c'e' quello che il restyle ha aggiunto: il nucleo in
miniatura della Minimal, il timer del VU meter che si ferma in tray, il
ritorno all'Hub dalla Diagnostica, i colori degli esiti nell'audit.
"""
import time

from PySide6.QtWidgets import QApplication


def _gira(secondi=0.0):
    fine = time.perf_counter() + secondi
    while True:
        for _ in range(10):
            QApplication.processEvents()
        if time.perf_counter() >= fine:
            return
        time.sleep(0.01)


# --- Minimal ----------------------------------------------------------------------------

def test_la_minimal_ha_il_nucleo_e_lo_stato_ci_arriva(crea_applicazione):
    a = crea_applicazione()
    a.nucleo.stato.emit("IN_ASCOLTO", "PTT", "PARLATO")
    a.segnali.kill_cambiato.emit(True)
    a.segnali.pausa_cambiata.emit(True)
    _gira()
    n = a.minimal.nucleo
    assert n.stato == "PARLATO" and n.kill and n.pausa
    assert a.minimal.indicatore.stato == "PARLATO"        # l'etichetta resta
    assert a.minimal.indicatore.pallino.isHidden()        # il pallino no: c'e' il nucleo
    assert n.width() == 64


def test_i_livelli_arrivano_anche_al_nucleo_della_minimal(crea_applicazione):
    a = crea_applicazione()
    a.nucleo.livello.emit(-23.0, -10.0)
    a.nucleo.voce.emit(-14.0)
    _gira()
    assert a.minimal.nucleo._microfono_db == -23.0
    assert a.minimal.nucleo._voce_db == -14.0


def test_con_la_minimal_nascosta_il_suo_nucleo_non_si_muove(crea_applicazione):
    a = crea_applicazione()
    a.mostra_minimal()
    _gira(0.1)
    assert a.minimal.nucleo.animato()
    a.mostra_hub()
    _gira()
    prima = a.minimal.nucleo.disegni
    _gira(0.2)
    assert not a.minimal.nucleo.animato() and a.minimal.nucleo.disegni == prima


def test_il_nucleo_della_minimal_va_a_20_fotogrammi(app_qt):
    from metis.gui.minimal_view import FPS_NUCLEO, MinimalView

    v = MinimalView()
    try:
        assert v.nucleo._timer.interval() == round(1000 / FPS_NUCLEO) == 50
    finally:
        v.deleteLater()


# --- VU meter ---------------------------------------------------------------------------

def test_il_vu_meter_si_ferma_quando_non_si_vede(app_qt):
    """Batteva 15 volte al secondo anche in tray, da M3."""
    from metis.gui.widgets.stato import VuMeter

    v = VuMeter()
    try:
        assert not v._timer.isActive()             # costruito ma mai mostrato
        v.show()
        _gira()
        assert v._timer.isActive()
        v.hide()
        _gira()
        assert not v._timer.isActive()
    finally:
        v.deleteLater()


def test_cambiando_vista_i_vu_meter_nascosti_si_fermano(crea_applicazione):
    a = crea_applicazione()
    a.mostra_hub()
    _gira()
    assert not a.minimal.vu._timer.isActive()
    assert not a.fullscreen.vu._timer.isActive()
    a.mostra_fullscreen()
    _gira()
    assert a.fullscreen.vu._timer.isActive() and not a.minimal.vu._timer.isActive()


# --- Diagnostica ---------------------------------------------------------------------------

def test_dalla_diagnostica_si_torna_all_hub(crea_applicazione):
    a = crea_applicazione()
    a.mostra_fullscreen()
    _gira()
    a.fullscreen.chiede_hub.emit()
    _gira()
    assert a.hub.isVisible() and not a.fullscreen.isVisible()


def test_gli_esiti_dell_audit_hanno_il_loro_colore(app_qt, tmp_path):
    """I colori c'erano da M3 e non si usavano: la cella era sempre bianca."""
    from metis.gui import tema
    from metis.gui.widgets.audit import VistaAudit
    from metis.security.audit import AuditLog, Entry, Outcome, Tier

    log = AuditLog(tmp_path / "a.db")
    for esito in (Outcome.OK, Outcome.DENIED, Outcome.ERROR):
        log.record(Entry(tool="open_application", tier=Tier.T1, args={},
                         outcome=esito, stage="esecuzione", detail="prova"))
    v = VistaAudit(log)
    try:
        v.ricarica()
        colori = {v.tabella.item(i, 3).text(): v.tabella.item(i, 3).foreground().color().name()
                  for i in range(v.tabella.rowCount())}
        assert colori == {"ok": tema.OK, "denied": tema.ERRORE, "error": tema.ATTENZIONE}
    finally:
        v.deleteLater()


def test_nessun_colore_scritto_a_mano_fuori_dal_tema():
    """Il criterio di uscita, detto in chiaro: l'elenco dei file da
    ridisegnare e' vuoto."""
    from tests.test_tema import DA_RIDISEGNARE, _con_colori

    assert DA_RIDISEGNARE == set() and _con_colori() == set()


def test_il_registro_mostra_anche_i_messaggi_che_c_erano_gia(app_qt):
    """Come i fumetti: una vista costruita dopo non parte vuota."""
    from metis.gui.modello_conversazione import ModelloConversazione
    from metis.gui.widgets.conversazione import Conversazione

    m = ModelloConversazione()
    m.utente("che ore sono?")
    m.metis("Sono le cinque.")
    c = Conversazione(m)
    try:
        testo = c.testo.toPlainText()
        assert "che ore sono?" in testo and "Sono le cinque." in testo
        m.metis("E dieci.")                     # e poi continua come prima
        assert c.testo.toPlainText().count("Sono le cinque.") == 1
        assert "E dieci." in c.testo.toPlainText()
    finally:
        c.deleteLater()


def test_nel_registro_ogni_messaggio_ha_la_sua_riga(app_qt):
    """Da M3 tutto finiva in un paragrafo solo: `insertHtml` fonde il primo
    blocco del frammento con quello in cui cade il cursore."""
    from metis.gui.widgets.conversazione import Conversazione

    c = Conversazione()
    try:
        c.utente("che ore sono?")
        c.metis("Sono le cinque.")
        c.sistema("strumento: get_time")
        assert c.testo.toPlainText().split("\n") == [
            "▸ che ore sono?", "Sono le cinque.", "· strumento: get_time"]
    finally:
        c.deleteLater()


def test_togliere_la_riga_provvisoria_non_cancella_il_resto(app_qt):
    """Con un paragrafo solo, togliere l'ultimo paragrafo voleva dire
    togliere tutta la conversazione."""
    from metis.gui.widgets.conversazione import Conversazione

    c = Conversazione()
    try:
        c.utente("prima domanda")
        c.metis("Prima risposta.")
        c.parziale("seconda dom")
        c.utente("seconda domanda")
        assert c.testo.toPlainText().split("\n") == [
            "▸ prima domanda", "Prima risposta.", "▸ seconda domanda"]
    finally:
        c.deleteLater()
