"""PHASE1 — l'Hub: modello della conversazione, fumetti, vista, comandi.

L'aspetto si guarda con `benchmarks/gui_screenshot.py`. Qui si prova il
comportamento che guardando non si vede: le frasi che diventano un fumetto
solo, il campo che non si svuota se il messaggio non e' partito, i timer che
si fermano in tray, la conferma di "Pulisci" che non parte con Invio.
"""
from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from metis.gui.modello_conversazione import MASSIMO, METIS, SISTEMA, UTENTE, ModelloConversazione
from tests.test_gui_widgets import LINK_BING


@pytest.fixture
def modello(app_qt):
    return ModelloConversazione()


def _gira(n=10):
    for _ in range(n):
        QApplication.processEvents()


# --- il modello ----------------------------------------------------------------------

def test_le_frasi_di_un_turno_sono_un_messaggio_solo(modello):
    modello.utente("che tempo fa?")
    modello.metis("Coperto e 18 gradi.")
    modello.metis("In serata pioggia.")
    assert [m.ruolo for m in modello.messaggi] == [UTENTE, METIS]
    assert modello[1].testo == "Coperto e 18 gradi. In serata pioggia."


def test_chiuso_il_turno_la_frase_dopo_e_un_messaggio_nuovo(modello):
    modello.metis("Primo turno.")
    modello.chiudi_turno()
    modello.metis("Un annuncio: promemoria.")
    assert len(modello) == 2


def test_parlare_chiude_il_turno_di_metis(modello):
    modello.metis("Risposta.")
    modello.utente("e poi?")
    modello.metis("Altra risposta.")
    assert [m.ruolo for m in modello.messaggi] == [METIS, UTENTE, METIS]


def test_i_segnali_dicono_cosa_e_cambiato(modello):
    aggiunti, aggiornati = [], []
    modello.aggiunto.connect(aggiunti.append)
    modello.aggiornato.connect(aggiornati.append)
    modello.metis("uno.")
    modello.metis("due.")
    assert aggiunti == [0] and aggiornati == [0]


def test_oltre_il_tetto_si_tolgono_i_piu_vecchi(modello):
    """Metis resta acceso per giorni: la lista della GUI non deve crescere
    per sempre."""
    tolti = []
    modello.troncato.connect(tolti.append)
    for i in range(MASSIMO + 5):
        modello.sistema(f"evento {i}")
    assert len(modello) <= MASSIMO and tolti
    assert modello[len(modello) - 1].testo == f"evento {MASSIMO + 4}"


def test_il_markdown_ha_chi_quando_e_come(modello):
    modello.utente("apri code", scritto=True)
    modello.metis("Fatto.")
    modello.utente("che ore sno", sospetto=True)
    modello.sistema("strumento: open_application")
    md = modello.markdown()
    assert md.startswith("# Conversazione con Metis")
    assert "**Tu**" in md and "**Metis**" in md and "_(scritto)_" in md
    assert "trascrizione incerta" in md and "> " in md
    assert datetime.now().strftime("%H:") in md


def test_azzera_svuota_e_avvisa(modello):
    azzerati = []
    modello.azzerato.connect(lambda: azzerati.append(1))
    modello.utente("x")
    modello.azzera()
    assert len(modello) == 0 and azzerati == [1]


# --- il registro della Diagnostica, sullo stesso modello ---------------------------

def test_il_registro_mostra_ogni_frase_una_volta(app_qt, modello):
    from metis.gui.widgets.conversazione import Conversazione

    reg = Conversazione(modello)
    modello.utente("che tempo fa?")
    modello.metis("Coperto.")
    modello.metis("Pioggia in serata.")
    testo = reg.testo.toPlainText()
    assert testo.count("Coperto.") == 1 and testo.count("Pioggia in serata.") == 1


def test_registro_e_fumetti_vedono_lo_stesso_modello(app_qt, modello):
    from metis.gui.widgets.conversazione import Conversazione
    from metis.gui.widgets.fumetti import ConversazioneFumetti

    reg = Conversazione(modello)
    fum = ConversazioneFumetti(modello)
    reg.utente("scritto dal registro")          # l'API di M3 scrive nel modello
    assert len(fum.fumetti()) == 1
    modello.azzera()
    assert reg.testo.toPlainText().strip() == "" and fum.fumetti() == []


# --- i fumetti -------------------------------------------------------------------------

def test_un_fumetto_per_turno_e_uno_per_utente(app_qt, modello):
    from metis.gui.widgets.fumetti import ConversazioneFumetti, Fumetto, RigaSistema

    fum = ConversazioneFumetti(modello)
    modello.utente("ciao")
    modello.metis("Buongiorno.")
    modello.metis("Come posso aiutarla?")
    modello.chiudi_turno()
    modello.sistema("strumento: web_search")
    tipi = [type(f) for f in fum.fumetti()]
    assert tipi == [Fumetto, Fumetto, RigaSistema]
    assert "Come posso aiutarla?" in fum.fumetti()[1].testo.text()


def test_si_disegnano_solo_gli_ultimi(app_qt, modello, monkeypatch):
    from metis.gui.widgets import fumetti as f

    monkeypatch.setattr(f, "VISIBILI", 5)
    fum = f.ConversazioneFumetti(modello)
    for i in range(12):
        modello.sistema(f"evento {i}")
    visti = fum.fumetti()
    assert len(visti) == 5 and "evento 11" in visti[-1].text()
    modello.metis("frase")                      # l'indice resta allineato dopo i tagli
    modello.metis("seconda")
    assert "seconda" in fum.fumetti()[-1].testo.text()


def test_i_tagli_del_modello_non_disallineano_i_fumetti(app_qt, modello, monkeypatch):
    from metis.gui import modello_conversazione as mc
    from metis.gui.widgets.fumetti import ConversazioneFumetti

    monkeypatch.setattr(mc, "MASSIMO", 10)
    monkeypatch.setattr(mc, "TOGLI", 4)
    fum = ConversazioneFumetti(modello)
    for i in range(10):
        modello.sistema(f"e{i}")
    modello.metis("aperto")                     # fa scattare il taglio
    modello.metis("e continua")                 # aggiorna l'ultimo: indice spostato di 4
    assert "e continua" in fum.fumetti()[-1].testo.text()


def test_il_fumetto_si_allarga_col_testo_fino_al_massimo(app_qt, modello):
    """Il primo disegno: una parola per riga, perche' il testo elastico non
    chiedeva spazio. Ora la larghezza e' quella del testo, fino al massimo."""
    from metis.gui.widgets.fumetti import Fumetto

    modello.metis("Fatto.")
    corto = Fumetto(modello[0], 360)
    modello.chiudi_turno()
    modello.metis("Secondo MeteoAM, oggi a Milano cielo coperto e 18 gradi, piogge in serata.")
    lungo = Fumetto(modello[1], 360)
    assert corto.width() < 150
    assert lungo.width() == 360
    lungo.imposta_massimo(300)
    assert lungo.width() == 300


# --- la vista ---------------------------------------------------------------------------

@pytest.fixture
def hub(app_qt, modello):
    from metis.gui.hub_view import HubView

    h = HubView(modello)
    yield h
    h.hide()
    h.deleteLater()


def test_prima_di_essere_pronto_non_si_scrive(hub):
    hub.campo.setText("ciao")
    assert not hub.b_invia.isEnabled()
    assert "avviando" in hub.campo.placeholderText()
    hub.imposta_pronto()
    assert hub.b_invia.isEnabled()


@pytest.mark.parametrize("stato", ["ELABORAZIONE", "ESECUZIONE", "ATTESA_CONFERMA"])
def test_a_turno_in_corso_l_invio_si_spegne(hub, stato):
    hub.imposta_pronto()
    hub.campo.setText("ciao")
    hub.imposta_stato(stato)
    assert not hub.b_invia.isEnabled()
    hub.imposta_stato("IN_ASCOLTO")
    assert hub.b_invia.isEnabled()


def test_mentre_parla_si_puo_scrivere(hub):
    """Scrivere mentre parla lo interrompe, come il push-to-talk."""
    hub.imposta_pronto()
    hub.campo.setText("basta")
    hub.imposta_stato("PARLATO")
    assert hub.b_invia.isEnabled()


def test_invio_emette_e_il_campo_si_svuota_solo_se_accettato(hub):
    chieste = []
    hub.chiede_testo.connect(chieste.append)
    hub.imposta_pronto()
    hub.campo.setText("  apri code  ")
    hub.campo.returnPressed.emit()
    assert chieste == ["apri code"]
    assert hub.campo.text() == "  apri code  "          # non ancora accettato
    hub.testo_accettato()
    assert hub.campo.text() == ""


def test_pulisci_chiede_conferma_e_invio_non_conferma(hub, monkeypatch):
    """Come nel dialogo T3: il pulsante predefinito e' quello innocuo."""
    visti = {}

    def exec_finto(self):
        visti["predefinito"] = self.defaultButton().text()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", exec_finto)
    chieste = []
    hub.chiede_pulisci.connect(lambda: chieste.append(1))
    hub._chiedi_pulisci()
    assert visti["predefinito"] == "Annulla"
    assert chieste == []                                 # nessun clic: niente pulizia


def test_esporta_scrive_il_markdown(hub, modello, tmp_path):
    modello.utente("ciao")
    modello.metis("Buongiorno.")
    percorso = tmp_path / "conv.md"
    hub.esporta_in(percorso)
    testo = percorso.read_text(encoding="utf-8")
    assert "**Tu**" in testo and "Buongiorno." in testo


def test_kill_switch_e_pausa_si_vedono(hub):
    hub.imposta_pronto()
    hub.imposta_kill(True)
    assert hub.salute.testo == "Azioni sospese" and hub.nucleo.kill
    assert hub.b_kill.nome_icona == "shield-alert"
    hub.imposta_kill(False)
    assert hub.salute.testo == "Operativo"
    hub.imposta_stato("PARLATO")
    hub.imposta_pausa(True)
    assert "ascolto in pausa" in hub.pillola_stato.testo
    assert hub.b_microfono.nome_icona == "mic-off"


def test_il_nucleo_prende_il_colore_dello_stato(hub):
    from metis.core.palette import esadecimale

    hub.imposta_stato("ATTESA_CONFERMA")
    assert hub.nucleo.colore() == esadecimale("ATTESA_CONFERMA")
    hub.imposta_pausa(True)
    assert hub.nucleo.colore() == esadecimale("DORMIENTE")


def test_gli_orologi_si_fermano_in_tray(hub):
    """In residenza per giorni: con la finestra nascosta, niente timer."""
    hub.show()
    _gira()
    assert hub._orologio.isActive() and hub.sessione._orologio.isActive()
    hub.hide()
    _gira()
    assert not hub._orologio.isActive() and not hub.sessione._orologio.isActive()


def test_sotto_i_1280_px_la_colonna_sinistra_lascia_il_posto(hub):
    hub.resize(1600, 900)
    hub.show()
    _gira()
    assert hub.sinistra.isVisible()
    hub.resize(1180, 800)
    _gira()
    assert not hub.sinistra.isVisible()


def test_un_link_enorme_non_allarga_l_hub(hub, modello):
    """Lo stesso difetto della control room di PHASE0, sul fumetto."""
    hub.resize(1500, 900)
    hub.show()
    _gira()
    destra = hub.pannello_conv.width()
    modello.metis(f"Ecco il link: {LINK_BING}")
    _gira(20)
    assert hub.width() == 1500 and hub.pannello_conv.width() == destra


def test_la_data_e_in_italiano_senza_locale():
    from metis.gui.hub_view import data_in_parole

    assert data_in_parole(datetime(2026, 9, 25)) == "venerdì 25 settembre"


# --- il cablaggio in Applicazione ---------------------------------------------------------

def test_un_messaggio_accettato_diventa_un_fumetto_scritto(crea_applicazione):
    a = crea_applicazione()
    a.nucleo.testo = lambda t: True
    a.hub.campo.setText("apri code")
    a._testo("apri code")
    ultimo = a.modello[len(a.modello) - 1]
    assert ultimo.ruolo == UTENTE and ultimo.scritto
    assert a.hub.campo.text() == ""


def test_un_messaggio_rifiutato_resta_nel_campo(crea_applicazione):
    a = crea_applicazione()
    a.nucleo.testo = lambda t: False
    a.hub.campo.setText("apri code")
    a._testo("apri code")
    assert a.hub.campo.text() == "apri code"
    assert a.modello[len(a.modello) - 1].ruolo == SISTEMA


def test_pulisci_riuscito_svuota_la_conversazione(crea_applicazione):
    a = crea_applicazione()
    a.modello.utente("qualcosa")
    a.nucleo.azzera = lambda: True
    a._pulisci()
    assert [m.ruolo for m in a.modello.messaggi] == [SISTEMA]


def test_pulisci_rifiutato_non_tocca_niente(crea_applicazione):
    a = crea_applicazione()
    a.modello.utente("qualcosa")
    a.nucleo.azzera = lambda: False
    a._pulisci()
    assert a.modello[0].testo == "qualcosa"


def test_le_tre_viste_una_alla_volta(crea_applicazione):
    a = crea_applicazione()
    for mostra, visibile in ((a.mostra_hub, a.hub), (a.mostra_fullscreen, a.fullscreen),
                             (a.mostra_minimal, a.minimal)):
        mostra()
        _gira()
        assert [v.isVisible() for v in (a.minimal, a.hub, a.fullscreen)].count(True) == 1
        assert visibile.isVisible()


def test_l_overlay_si_espande_nell_hub(crea_applicazione):
    a = crea_applicazione()
    a.mostra_minimal()
    a.minimal.chiede_fullscreen.emit()
    _gira()
    assert a.hub.isVisible()


def test_lo_stato_arriva_all_hub(crea_applicazione):
    a = crea_applicazione()
    a.nucleo.stato.emit("IN_ASCOLTO", "PTT", "PARLATO")
    _gira()
    assert a.hub.stato == "PARLATO" and a.hub.nucleo.stato == "PARLATO"


# --- il muto -----------------------------------------------------------------------------

def test_muto_il_player_non_suona_ma_la_coda_scorre(monkeypatch):
    import numpy as np

    from metis.tts import kokoro_engine as k

    suonati, fermati = [], []

    class Sd:
        def play(self, pcm, sr):
            suonati.append(len(pcm))

        def wait(self):
            pass

        def stop(self):
            fermati.append(1)
    monkeypatch.setattr(k, "sd", Sd())
    p = k.Player(sample_rate=16000)
    p.start()
    try:
        p.imposta_muto(True)
        assert fermati == [1]                 # zittito a meta' frase: si ferma subito
        p.enqueue(np.zeros(160, np.float32))
        assert p.wait_drained(timeout=2.0)    # la macchina a stati non resta appesa
        assert suonati == []
        p.imposta_muto(False)
        p.enqueue(np.zeros(160, np.float32))
        assert p.wait_drained(timeout=2.0)
        assert suonati == [160]
    finally:
        p.close()


def test_il_muto_chiesto_prima_dell_avvio_vale_dopo():
    from metis.core.avvio import Opzioni
    from metis.gui.workers.nucleo import Nucleo

    n = Nucleo(Opzioni(tools=False, wakeword=False))
    n.muto(True)

    class Player:
        muto = False

        def imposta_muto(self, v):
            self.muto = v

    class Sistema:
        player = Player()
    n.sistema = Sistema()
    n._applica_muto()
    assert n.sistema.player.muto is True


def test_azzera_dal_nucleo_pulisce_anche_gli_slot():
    from metis.core.avvio import Opzioni
    from metis.gui.workers.nucleo import Nucleo
    from metis.memory.slots import SLOTS

    class Orch:
        def azzera_conversazione(self):
            return True

    class Sistema:
        orchestrator = Orch()
    n = Nucleo(Opzioni(tools=False, wakeword=False))
    n.sistema = Sistema()
    SLOTS.ultimo_argomento_cercato = "lavori in Svizzera"
    try:
        assert n.azzera() is True
        assert SLOTS.ultimo_argomento_cercato is None
    finally:
        SLOTS.reset()


def test_le_frasi_d_attesa_non_entrano_nella_conversazione(crea_applicazione):
    """"Verifico." si dice mentre si cerca; nel fumetto sembrava l'inizio
    della risposta: "Verifico. Per addestrare un modello...". Visto in
    esercizio il 2026-09-25."""
    from metis.core.risposte import FILLERS

    a = crea_applicazione()
    a.nucleo.dice.emit(FILLERS[1])
    _gira()
    assert len(a.modello) == 0
    assert a.fullscreen.corrente.text() == FILLERS[1]     # "sta dicendo", in Diagnostica
    a.nucleo.dice.emit("Per addestrare un modello servono dati.")
    _gira()
    assert [m.testo for m in a.modello.messaggi] == ["Per addestrare un modello servono dati."]
