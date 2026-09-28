"""PHASE2, dopo le prove (2026-09-28) — musica, volume, browser, video.

Tre proprieta'. Le frasi chiuse producono chiamate valide per lo schema, e
solo per le frasi giuste ("ferma" da solo non inverte la musica). I tasti
multimediali e il volume sono T1 (D-NAV 8). I comandi del video partono solo
con YouTube davanti e mai con il fuoco in un campo di testo, dove le lettere
si scriverebbero (D-NAV 9).
"""
import pytest

from metis.core.frasi_chiuse import riconosci
from metis.core.risposte import descrivi_sequenza
from metis.core.router import normalizza
from metis.security import guards
from metis.security.audit import AuditLog, Outcome, Tier
from metis.security.broker import Broker, Result
from metis.security.policies import Context
from metis.tools import cliccabili, finestre, media, sendinput
from metis.tools.registry import carica_tutti

REG = carica_tutti()


def _r(frase):
    return riconosci(normalizza(frase))


@pytest.mark.parametrize("frase,atteso", [
    ("metti in pausa il video", [("tasto_multimediale", {"tasto": "play_pausa"})]),
    ("Pausa.", [("tasto_multimediale", {"tasto": "play_pausa"})]),
    ("riprendi la musica", [("tasto_multimediale", {"tasto": "play_pausa"})]),
    ("ferma il video", [("tasto_multimediale", {"tasto": "play_pausa"})]),
    ("brano successivo", [("tasto_multimediale", {"tasto": "successivo"})]),
    ("prossima canzone", [("tasto_multimediale", {"tasto": "successivo"})]),
    ("video successivo", [("tasto_multimediale", {"tasto": "successivo"})]),
    ("canzone precedente", [("tasto_multimediale", {"tasto": "precedente"})]),
    ("alza il volume", [("cambia_volume", {"verso": "su", "passo": 10})]),
    ("abbassa il volume di venti", [("cambia_volume", {"verso": "giu", "passo": 20})]),
    ("volume al 30", [("set_volume", {"livello": 30})]),
    ("metti il volume a metà", [("set_volume", {"livello": 50})]),
    ("volume al massimo", [("set_volume", {"livello": 100})]),
    ("muto", [("imposta_muto", {"muto": True})]),
    ("togli l'audio", [("imposta_muto", {"muto": True})]),
    ("togli il muto", [("imposta_muto", {"muto": False})]),
    ("ricarica la pagina", [("press_hotkey", {"keys": ["f5"]})]),
    ("scheda successiva", [("press_hotkey", {"keys": ["ctrl", "tab"]})]),
    ("scheda precedente", [("press_hotkey", {"keys": ["ctrl", "shift", "tab"]})]),
    ("vai alla seconda scheda", [("press_hotkey", {"keys": ["ctrl", "2"]})]),
    ("ingrandisci la pagina", [("press_hotkey", {"keys": ["ctrl", "plus"]})]),
    ("zoom indietro", [("press_hotkey", {"keys": ["ctrl", "minus"]})]),
    ("zoom normale", [("press_hotkey", {"keys": ["ctrl", "0"]})]),
    ("avanti di 10 secondi", [("comando_video", {"comando": "avanti"})]),
    ("torna indietro di trenta secondi", [("comando_video", {"comando": "indietro"})] * 3),
    ("indietro di 5 secondi", [("comando_video", {"comando": "indietro_poco"})]),
    ("avanti di un minuto", [("comando_video", {"comando": "avanti"})] * 6),
    ("schermo intero", [("comando_video", {"comando": "schermo_intero"})]),
    ("esci dallo schermo intero", [("comando_video", {"comando": "schermo_intero"})]),
    ("attiva i sottotitoli", [("comando_video", {"comando": "sottotitoli"})]),
])
def test_le_frasi(frase, atteso):
    calls = _r(frase)
    assert calls is not None, frase
    assert [(c["tool"], {k: v for k, v in c.items() if k != "tool"}) for c in calls] == atteso
    for c in calls:
        REG.get(c["tool"]).schema.model_validate(c)


@pytest.mark.parametrize("frase", [
    "ferma", "ingrandisci", "che volume ho", "volume al 150", "il volume e' alto?",
    "torna indietro",            # e' il browser, non il video
    "questa canzone e' bella", "sottotitoli in inglese per favore del film",
])
def test_queste_no(frase):
    calls = _r(frase) or ()
    assert all(c["tool"] not in ("tasto_multimediale", "set_volume", "cambia_volume",
                                 "imposta_muto", "comando_video") for c in calls), frase


def test_tier_d_nav_8_e_9():
    for nome in ("tasto_multimediale", "set_volume", "cambia_volume", "imposta_muto"):
        assert REG.get(nome).tier is Tier.T1, nome
    spec = REG.get("comando_video")
    assert spec.tier is Tier.T2 and any(g.nome == "finestra" for g in spec.guards)


# --- volume e tasti, attraverso il broker ------------------------------------------

@pytest.fixture
def broker(tmp_path):
    return Broker(registry=REG, audit=AuditLog(tmp_path / "a.db"))


@pytest.fixture
def audio_finto(monkeypatch):
    stato = {"livello": 40, "muto": False}
    monkeypatch.setattr(media, "livello", lambda: stato["livello"])

    def imposta(p):
        stato["livello"] = max(0, min(100, int(p)))
        return stato["livello"]
    monkeypatch.setattr(media, "imposta_livello", imposta)
    monkeypatch.setattr(media, "imposta_muto_audio", lambda a: stato.update(muto=a))
    return stato


def test_alza_abbassa_e_resta_fra_0_e_100(broker, audio_finto):
    su = {"tool": "cambia_volume", "verso": "su", "passo": 50}
    assert broker.execute(su, Context()).value["livello"] == 90
    assert broker.execute(su, Context()).value["livello"] == 100
    r = broker.execute({"tool": "set_volume", "livello": 30}, Context())
    assert r.ok and audio_finto["livello"] == 30 and descrivi_sequenza([r]) == "Volume al 30."


def test_muto(broker, audio_finto):
    r = broker.execute({"tool": "imposta_muto", "muto": True}, Context())
    assert r.ok and audio_finto["muto"] is True
    assert descrivi_sequenza([r]) == "Audio disattivato."


def test_senza_uscita_audio_e_un_rifiuto(broker, monkeypatch):
    def rotto():
        raise OSError("niente")
    monkeypatch.setattr(media, "livello", rotto)
    r = broker.execute({"tool": "set_volume", "livello": 30}, Context())
    assert r.outcome is Outcome.DENIED and "audio" in r.detail


def test_il_tasto_multimediale_non_dice_cio_che_non_sa(broker, monkeypatch):
    premuti = []
    monkeypatch.setattr(sendinput, "multimediale", premuti.append)
    r = broker.execute({"tool": "tasto_multimediale", "tasto": "play_pausa"}, Context())
    assert r.ok and premuti == ["play_pausa"]
    assert descrivi_sequenza([r]) == "Fatto."           # non "In pausa": e' un interruttore


def test_il_volume_vero_si_legge_e_si_riscrive_uguale():
    """Sul dispositivo vero, senza cambiarlo: le interfacce COM hanno l'ordine
    dei metodi giusto, o qui si leggerebbe spazzatura."""
    try:
        prima = media.livello()
    except Exception as exc:                               # noqa: BLE001
        pytest.skip(f"nessuna uscita audio: {exc}")
    assert 0 <= prima <= 100
    assert media.imposta_livello(prima) == prima and media.livello() == prima
    assert media.muto() in (True, False)


# --- il video --------------------------------------------------------------------------

@pytest.fixture
def video(monkeypatch):
    import win32gui

    stato = {"titolo": "Pasta alla gricia - YouTube - Google Chrome", "scrivibile": False,
             "premuti": []}
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(finestre, "info", lambda h: finestre.Info(
        7, stato["titolo"], "chrome.exe", "Chrome_WidgetWin_1", (0, 0, 100, 100), "normale"))
    monkeypatch.setattr(cliccabili, "fuoco", lambda: cliccabili.Fuoco(
        50004 if stato["scrivibile"] else 50030, "Cerca", (0, 0, 1, 1), stato["scrivibile"]))
    monkeypatch.setattr(sendinput, "combinazione", stato["premuti"].append)
    monkeypatch.setattr(guards, "finestra_in_primo_piano",
                        lambda: guards.Finestra("YouTube", "chrome.exe", "c", 999999))
    return stato


def test_avanti_di_dieci_secondi(broker, video):
    r = broker.execute({"tool": "comando_video", "comando": "avanti"}, Context())
    assert r.ok and video["premuti"] == [["l"]] and descrivi_sequenza([r]) == "Avanti."


def test_con_il_fuoco_in_un_campo_non_si_preme_niente(broker, video):
    """Una "f" nella casella di ricerca non mette lo schermo intero: la scrive."""
    video["scrivibile"] = True
    r = broker.execute({"tool": "comando_video", "comando": "schermo_intero"}, Context())
    assert r.denied and "campo di testo" in r.detail and video["premuti"] == []


def test_senza_youtube_davanti_non_si_preme_niente(broker, video):
    video["titolo"] = "Documento - Word"
    r = broker.execute({"tool": "comando_video", "comando": "avanti"}, Context())
    assert r.denied and video["premuti"] == []


def test_dopo_il_web_niente_comandi_al_video(broker, video):
    r = broker.execute({"tool": "comando_video", "comando": "avanti"},
                       Context(has_untrusted_content=True))
    assert r.denied and r.stage == "policy"


@pytest.mark.parametrize("tasti,frase", [
    ("f5", "Ricarico."), ("ctrl+tab", "Scheda successiva."), ("ctrl+plus", "Più grande."),
    ("ctrl+0", "Zoom normale."),
])
def test_le_frasi_dei_tasti_del_browser(tasti, frase):
    r = Result(True, Outcome.OK, "esecuzione", "eseguito", value={"tasti": tasti},
               tool="press_hotkey")
    assert descrivi_sequenza([r]) == frase


@pytest.mark.parametrize("frase,passa", [
    ("muto", True), ("togli l'audio", True), ("silenzio per favore", True),
    ("togli il muto", True), ("riattiva l'audio", True),
    ("la musica e' troppo forte", False), ("fermati un attimo con la musica", False),
])
def test_il_muto_dal_modello_chiede_una_parola_di_muto(frase, passa):
    from metis.llm.toolcall import chiesta

    assert chiesta({"tool": "imposta_muto", "muto": True}, frase) is passa


def test_che_volume_ho(broker, audio_finto):
    from metis.core.router import Router

    d = Router(REG, comandi=[], usa_llm=False).decidi("Che volume ho adesso?")
    assert d.calls == ({"tool": "leggi_volume"},)
    r = broker.execute(d.calls[0], Context())
    assert r.ok and REG.get("leggi_volume").tier is Tier.T0
    assert descrivi_sequenza([r]) == "Il volume è al 40."


def test_gli_strumenti_nuovi_non_si_offrono_al_modello():
    """Con loro nel prompt, "qual e' l'ultima versione di Python" andava sul web
    3 volte su 8 invece di 8 su 8. Si raggiungono con le frasi chiuse."""
    nuovi = {"tasto_multimediale", "leggi_volume", "set_volume", "cambia_volume",
             "imposta_muto", "comando_video", "scrivi_nel_numero"}
    offerti = {s.name for s in REG.per_il_modello()}
    assert not nuovi & offerti
    assert nuovi <= {s.name for s in REG.disponibili()}
    assert "cambia_volume" not in REG.descrizione_per_prompt()
    import json
    assert "cambia_volume" not in json.dumps(REG.json_schema())


@pytest.mark.parametrize("frase,atteso", [
    ("abbassa un pochino l'audio", ("cambia_volume", "giu")),
    ("alza un po' la musica", ("cambia_volume", "su")),
    ("abbassa", ("cambia_volume", "giu")),
    ("salta questa canzone", ("tasto_multimediale", "successivo")),
    ("salta", ("tasto_multimediale", "successivo")),
])
def test_le_frasi_piu_larghe(frase, atteso):
    (c,) = _r(frase)
    assert (c["tool"], c.get("verso") or c.get("tasto")) == atteso


@pytest.mark.parametrize("frase,passa", [
    ("accendi la friggitrice", True), ("spegni la friggitrice", True),
    ("dai le crocchette al gatto", True), ("attiva il distributore", True),
    ("la musica e' troppo forte", False), ("mi piace la friggitrice, la consigli?", False),
])
def test_i_dispositivi_di_casa_dal_modello_chiedono_un_verbo(frase, passa):
    from metis.llm.toolcall import chiesta

    a = {"tool": "set_home_device", "dispositivo": "friggitrice", "azione": "accendi"}
    assert chiesta(a, frase) is passa
