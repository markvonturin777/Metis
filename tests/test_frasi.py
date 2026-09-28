"""PHASE4 — le frasi non capite.

Giorno 1: i segnali. Ogni turno che non va a buon fine per un'incomprensione
lascia `non_capito` nel suo `extra`, con il motivo; i rifiuti di sicurezza no.
"""
from pathlib import Path

import pytest

from metis.core.orchestrator import Azioni
from metis.core.risposte import descrivi_sequenza
from metis.core.state_machine import Event
from metis.llm.toolcall import Decisione
from metis.memory import frasi
from metis.security.audit import Outcome
from metis.security.broker import Result
from tests.test_orchestrator import FakeGen, _segmento, make
from tests.test_router import _tool_router


# --- il router dice cosa ha tolto ----------------------------------------------------

def test_il_router_dice_quali_azioni_ha_tolto():
    """Il caso della prova del 2026-09-26: clicca_numero(81) proposto, tolto
    perche' "81" non era stato detto."""
    d = _tool_router([{"tool": "clicca_numero", "numero": 81}]).decidi(
        "clicca su oltra un tunnel")
    assert d.calls == () and d.tolte == ("clicca_numero",)
    assert d.chiarimento                        # e c'e' la domanda di PHASE2


def test_il_router_toglie_l_apertura_senza_verbo():
    d = _tool_router([{"tool": "open_application", "app": "vscode"}]).decidi(
        "sai aiutarmi nella programmazione?")
    assert d.calls == () and d.tolte == ("open_application",)


def test_solo_i_nomi_mai_gli_argomenti():
    """D-FRASI 6: un 81 inventato non si suggerisce a nessuno."""
    d = _tool_router([{"tool": "clicca_numero", "numero": 81}]).decidi("clicca su oltra")
    assert all(isinstance(t, str) for t in d.tolte)
    assert "81" not in repr(d.tolte)


def test_una_decisione_riuscita_non_ha_tolte():
    d = _tool_router([{"tool": "open_application", "app": "vscode"}]).decidi("apri vs code")
    assert d.calls and d.tolte == () and d.riparazione_fallita is False


class _ClientRotto:
    """Il modello che scrive due volte un JSON che lo schema non accetta."""

    def __init__(self):
        self.chiamate = 0

    def chat(self, **kw):
        self.chiamate += 1
        return {"message": {"content": '{"azioni": [{"tool": "non_esiste"}]}'}}


def test_due_json_non_validi_sono_una_riparazione_fallita():
    r = _tool_router([])
    r.client = _ClientRotto()
    d = r.decidi("fai quella cosa")
    assert r.client.chiamate == 2                # un tentativo di riparazione, poi basta
    assert d.calls == () and d.riparazione_fallita is True


# --- i segnali nel turno ---------------------------------------------------------------

def _turno(decisione, esito=None, risposta="risposta finta"):
    """Un turno intero dell'orchestratore; ritorna l'`extra` del turno."""
    o, _ = make(text="una frase qualunque")

    def llm_stream(history, cancel=None, **kw):
        yield risposta, FakeGen(text=risposta)

    o.d.llm_stream = llm_stream
    o.d.azioni = Azioni(decidi=lambda t, s: decisione,
                        esegui=lambda c, u=False: esito,
                        descrivi=descrivi_sequenza,
                        richiede_conferma=lambda c: False)
    visti = []
    o.d.on_turn_end = visti.append
    o.sm.fire(Event.PTT); o.sm.fire(Event.SPEECH_START); o.sm.fire(Event.SPEECH_END)
    o._process(_segmento())
    assert len(visti) == 1, "il turno non si e' chiuso"
    return visti[0].extra


def test_segnale_chiarimento_con_lo_strumento_tolto():
    extra = _turno(Decisione((), chiarimento="Non ho capito il numero: me lo ripete?",
                             tolte=("clicca_numero",)))
    assert extra["non_capito"] == frasi.CHIARIMENTO
    assert extra["tolta"] == "clicca_numero"
    assert extra["chiarimento"] is True          # la chiave di PHASE2 resta


def test_segnale_azione_tolta():
    extra = _turno(Decisione((), tolte=("open_application",)))
    assert extra["non_capito"] == frasi.AZIONE_TOLTA
    assert extra["tolta"] == "open_application"


def test_segnale_riparazione_fallita():
    extra = _turno(Decisione((), riparazione_fallita=True))
    assert extra["non_capito"] == frasi.RIPARAZIONE
    assert "tolta" not in extra


def test_segnale_conversazione_che_non_ha_capito():
    extra = _turno(Decisione(()), risposta=frasi.FRASE_PERSONA)
    assert extra["non_capito"] == frasi.CONVERSAZIONE


def test_una_conversazione_normale_non_e_un_segnale():
    extra = _turno(Decisione(()), risposta="Il cielo e' blu per la diffusione di Rayleigh.")
    assert "non_capito" not in extra


def test_ollama_giu_non_e_una_frase_non_capita():
    """`errore` senza azioni vale anche per l'inferenza irraggiungibile: non
    e' colpa della frase."""
    extra = _turno(Decisione((), errore="ConnectError: connessione rifiutata"))
    assert "non_capito" not in extra


def _risultato(stadio, ok=False):
    esito = Outcome.OK if ok else Outcome.DENIED
    return Result(ok=ok, outcome=esito, stage=stadio, detail="motivo di prova.",
                  tool="open_application")


@pytest.mark.parametrize("stadio", ["json", "registro", "schema"])
def test_una_tool_call_malformata_rifiutata_dal_broker(stadio):
    extra = _turno(Decisione(({"tool": "open_application", "app": "vscode"},)),
                   esito=_risultato(stadio))
    assert extra["non_capito"] == frasi.RIPARAZIONE


@pytest.mark.parametrize("stadio", ["policy", "guardie", "guardie_immediate", "conferma"])
def test_i_rifiuti_di_sicurezza_non_sono_segnali(stadio):
    """D-FRASI 2: denylist, kill switch, vietate, conferma negata sono
    comportamenti corretti. Nel pannello inviterebbero ad aggirarli."""
    extra = _turno(Decisione(({"tool": "open_application", "app": "vscode"},)),
                   esito=_risultato(stadio))
    assert "non_capito" not in extra


def test_lo_strumento_che_non_riesce_e_un_segnale():
    """La prima versione lo contava fra i rifiuti di sicurezza: "quella finestra
    non c'e' piu'" quattro volte di fila, e il pannello non vedeva niente."""
    extra = _turno(Decisione(({"tool": "mostra_numeri"},)), esito=_risultato("strumento"))
    assert extra["non_capito"] == frasi.STRUMENTO


def test_un_eccezione_dello_strumento_e_un_segnale():
    esito = Result(ok=False, outcome=Outcome.ERROR, stage="esecuzione",
                   detail="RuntimeError: boh", tool="mostra_numeri")
    extra = _turno(Decisione(({"tool": "mostra_numeri"},)), esito=esito)
    assert extra["non_capito"] == frasi.STRUMENTO


# --- PHASE4, dalla prima seduta vera: type_text chiede di scrivere -----------------------

@pytest.mark.parametrize("frase,testo,atteso", [
    ("Devi dire grazie.", "grazie", False),                  # la seduta: sarebbe stato scritto
    ("Ma sei rincoglionito?", "Ma sei rincoglionito?", False),
    ("scrivi ciao!", "ciao", True),
    ("digita ciao mondo", "ciao mondo", True),
    ("scrivi qualcosa di bello", "Buongiorno a tutti", False),  # testo non detto
    ("scrivi", "", False),
])
def test_type_text_vuole_il_verbo_e_il_testo_detto(frase, testo, atteso):
    from metis.llm.toolcall import chiesta

    assert chiesta({"tool": "type_text", "text": testo}, frase) is atteso


def test_un_azione_riuscita_non_e_un_segnale():
    extra = _turno(Decisione(({"tool": "open_application", "app": "vscode"},)),
                   esito=_risultato("esecuzione", ok=True))
    assert "non_capito" not in extra


def test_una_decisione_finta_senza_i_campi_nuovi():
    """Un router che non conosce `tolte` (o un mock) non produce segnali."""
    from types import SimpleNamespace

    finta = SimpleNamespace(calls=(), e_strumento=False, chiarimento=None,
                            risposta=None, tolte="non una tupla")
    extra = _turno(finta)
    assert "non_capito" not in extra


# --- la frase della persona -------------------------------------------------------------

def test_la_frase_della_persona_e_quella_del_prompt():
    """Riformulare il prompt senza toccare `frasi.FRASE_PERSONA` spegnerebbe
    il segnale della conversazione in silenzio."""
    prompt = Path("metis/llm/prompts/metis_v1.txt").read_text(encoding="utf-8")
    # Nel prompt la frase va a capo a meta': si confronta a spazi compattati.
    assert frasi.FRASE_PERSONA in " ".join(prompt.split())


@pytest.mark.parametrize("risposta,atteso", [
    ("Non ho capito cosa fare: me lo ripete?", True),
    ("Non ho capito cosa fare: puo' ripetere?", True),
    ("Non ho capito cosa fare.", True),
    ("Non ho capito il numero: me lo ripete?", False),   # e' il chiarimento, non la persona
    ("Ho capito, apro subito.", False),
    ("", False),
])
def test_detta_dalla_persona(risposta, atteso):
    assert frasi.detta_dalla_persona(risposta) is atteso


# === Giorno 2: la lettura ===============================================================

import json  # noqa: E402

from metis.memory.frasi import Turno  # noqa: E402

T0 = 1_790_000_000.0          # un istante qualunque, in secondi epoch


def _riga(ts, testo, **extra):
    return {"turn_id": "x", "ts": ts, "transcript": testo, "reply": "", "extra": extra}


def _scrivi(path, righe):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in righe),
                    encoding="utf-8")
    return path


# La seduta vera del 2026-09-26 (`CONVOS/Metis_20260926_1920.md`), come la
# scriverebbe oggi l'orchestratore.
SEDUTA = [
    _riga(T0 + 0, "Mostra in umere.", tool="mostra_numeri", esito="ok"),
    _riga(T0 + 10, "Torna indietro."),                             # "Indietro.": silenzioso
    _riga(T0 + 20, "clicca su oltra un tunnel.", chiarimento=True,
          non_capito="chiarimento", tolta="clicca_numero"),
    _riga(T0 + 30, "su ottantuna.", non_capito="chiarimento"),
    _riga(T0 + 40, "clicca su ottanto uno.", non_capito="azione_tolta", tolta="clicca_numero"),
    _riga(T0 + 90, "Clicca su oltra un tunnel", non_capito="chiarimento", tolta="clicca_numero"),
    _riga(T0 + 100, "chiudi la prima scheda di chrome", non_capito="conversazione"),
    _riga(T0 + 110, "clicca su 64.", tool="clicca_numero", esito="denied"),   # guardia: non conta
]


# --- righe dalla fine -----------------------------------------------------------------

@pytest.mark.parametrize("blocco", [1, 7, 64, 1 << 16])
def test_righe_dalla_fine_attraverso_i_blocchi(tmp_path, blocco):
    p = tmp_path / "t.jsonl"
    p.write_bytes("uno\ndue\n\ntre è\nquattro".encode("utf-8"))   # ultima senza a capo
    assert list(frasi.righe_dalla_fine(p, blocco)) == ["quattro", "tre è", "due", "uno"]


def test_righe_dalla_fine_file_assente_o_vuoto(tmp_path):
    assert list(frasi.righe_dalla_fine(tmp_path / "manca.jsonl")) == []
    (tmp_path / "vuoto.jsonl").write_bytes(b"")
    assert list(frasi.righe_dalla_fine(tmp_path / "vuoto.jsonl")) == []


# --- leggi_turni ----------------------------------------------------------------------

def test_leggi_turni_si_ferma_al_limite_e_tiene_l_ordine(tmp_path):
    p = _scrivi(tmp_path / "t.jsonl", [_riga(T0 - 100, "vecchio"), *SEDUTA])
    turni = frasi.leggi_turni(p, dal=T0)
    assert [t.testo for t in turni][0] == "Mostra in umere."
    assert "vecchio" not in [t.testo for t in turni]
    assert [t.ts for t in turni] == sorted(t.ts for t in turni)


def test_leggi_turni_salta_le_righe_storte(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"ts": 1790000001, "transcript": "buono", "extra": {}}\n'
                 'non e\' json\n[1, 2]\n{"transcript": "senza ts"}\n'
                 '{"ts": 1790000002, "transcript": "", "extra": {}}\n'
                 '{"ts": 1790000003, "transcript": "a meta', encoding="utf-8")
    assert [t.testo for t in frasi.leggi_turni(p, dal=0)] == ["buono"]


def test_i_turni_di_phase2_valgono_come_chiarimenti():
    t = frasi.turno(_riga(T0, "clicca su oltra", chiarimento=True))
    assert t.motivo == frasi.CHIARIMENTO


def test_un_motivo_sconosciuto_non_e_un_segnale():
    assert frasi.turno(_riga(T0, "x", non_capito="inventato")).motivo is None


# --- la ripetizione ---------------------------------------------------------------------

def _t(ts, testo, **kw):
    return Turno(ts=T0 + ts, testo=testo, **kw)


def test_la_ripetizione_segna_il_primo_turno():
    turni = frasi.segna_ripetizioni([_t(0, "Torna indietro."), _t(8, "torna indietro")])
    assert turni[0].motivo == frasi.RIPETUTA and turni[1].motivo is None


@pytest.mark.parametrize("primo,secondi", [
    (dict(strumento="scroll"), 5),                 # dopo uno strumento: uso normale
    (dict(web=True), 5),                            # dopo una ricerca
    (dict(motivo=frasi.CHIARIMENTO), 5),            # ha gia' un segnale forte
    ({}, 31),                                       # troppo tardi
])
def test_quando_la_ripetizione_non_conta(primo, secondi):
    turni = frasi.segna_ripetizioni([_t(0, "scorri giu", **primo), _t(secondi, "scorri giu")])
    assert turni[0].motivo != frasi.RIPETUTA


def test_frasi_diverse_non_sono_ripetizioni():
    turni = frasi.segna_ripetizioni([_t(0, "su ottantuna"), _t(5, "clicca su ottanto uno")])
    assert all(t.motivo is None for t in turni)


# --- le frasi con parametro -------------------------------------------------------------

@pytest.mark.parametrize("frase,tolta,atteso", [
    ("clicca su ottanto uno", None, True),       # decina storpiata, da numeri_parlati
    ("su ottantuna", None, True),
    ("alza il volume di 20", None, True),
    ("scrivi nel 12: ricette di pasta", None, True),
    ("clicca su oltra un tunnel", "clicca_numero", True),   # lo dice lo strumento tolto
    ("mastra in numeria", None, False),
    ("chiudi la prima scheda di chrome", None, False),
    ("torna indietro", None, False),
])
def test_parametrica(frase, tolta, atteso):
    assert frasi.parametrica(frase, tolta) is atteso


# --- il raggruppamento --------------------------------------------------------------------

def _raccolta(tmp_path, righe=SEDUTA, decise=None):
    return frasi.raggruppa(frasi.leggi_turni(_scrivi(tmp_path / "t.jsonl", righe), 0), decise)


def test_la_seduta_vera_raggruppata(tmp_path):
    r = _raccolta(tmp_path)
    per_frase = {g.chiave: g for g in r.da_rivedere}
    g = per_frase["clicca su oltra un tunnel"]
    assert g.volte == 2 and g.frase == "Clicca su oltra un tunnel"      # l'ultima forma detta
    assert g.motivo == frasi.CHIARIMENTO and g.tolta == "clicca_numero" and g.parametrica
    assert per_frase["chiudi la prima scheda di chrome"].motivo == frasi.CONVERSAZIONE
    assert not per_frase["chiudi la prima scheda di chrome"].parametrica
    assert "clicca su 64" not in per_frase                # rifiuto della guardia: non e' qui
    assert "mostra in umere" not in per_frase             # riuscita


def test_il_fallimento_silenzioso_si_vede_se_ripetuto(tmp_path):
    righe = [_riga(T0, "Torna indietro."), _riga(T0 + 6, "torna indietro")]
    r = _raccolta(tmp_path, righe)
    assert [(g.chiave, g.motivo) for g in r.da_rivedere] == [("torna indietro", frasi.RIPETUTA)]
    assert r.non_capiti == 0                              # debole: non entra nella quota


def test_ordine_prima_i_forti_poi_i_piu_frequenti(tmp_path):
    righe = [_riga(T0, "debole"), _riga(T0 + 1, "debole"),
             _riga(T0 + 100, "una", non_capito="chiarimento"),
             _riga(T0 + 200, "due", non_capito="chiarimento"),
             _riga(T0 + 300, "due", non_capito="chiarimento")]
    assert [g.chiave for g in _raccolta(tmp_path, righe).da_rivedere] == ["due", "una", "debole"]


def test_a_parita_vince_la_precedenza_dei_segnali(tmp_path):
    righe = [_riga(T0, "x", non_capito="conversazione"), _riga(T0 + 100, "x", non_capito="chiarimento")]
    assert _raccolta(tmp_path, righe).da_rivedere[0].motivo == frasi.CHIARIMENTO


def test_la_quota_dei_turni_non_capiti(tmp_path):
    r = _raccolta(tmp_path)
    assert r.turni == len(SEDUTA)
    assert r.non_capiti == 5
    assert r.quota == pytest.approx(5 / 8)
    assert frasi.Raccolta().quota == 0.0


# --- le decisioni -------------------------------------------------------------------------

def test_ignorata_sparisce(tmp_path):
    decise = {"chiudi la prima scheda di chrome": {"stato": "ignorata", "quando": "2020-01-01T00:00:00"}}
    chiavi = [g.chiave for g in _raccolta(tmp_path, decise=decise).da_rivedere]
    assert "chiudi la prima scheda di chrome" not in chiavi


def test_risolta_torna_solo_se_fallisce_dopo(tmp_path):
    dopo = [*SEDUTA, _riga(T0 + 5000, "clicca su oltra un tunnel", non_capito="chiarimento")]
    quando = frasi.datetime.fromtimestamp(T0 + 1000).isoformat()
    decise = {"clicca su oltra un tunnel": {"stato": "risolta", "quando": quando}}
    assert "clicca su oltra un tunnel" not in [
        g.chiave for g in _raccolta(tmp_path, decise=decise).da_rivedere]
    ricomparsa = [g for g in _raccolta(tmp_path, dopo, decise).da_rivedere
                  if g.chiave == "clicca su oltra un tunnel"]
    assert len(ricomparsa) == 1 and ricomparsa[0].volte == 1      # solo il fallimento nuovo


def test_segnalata_va_nell_elenco_da_esportare(tmp_path):
    decise = {"clicca su ottanto uno": {"stato": "segnalata", "quando": "2020-01-01T00:00:00"}}
    r = _raccolta(tmp_path, decise=decise)
    assert [g.chiave for g in r.segnalate] == ["clicca su ottanto uno"]
    assert "clicca su ottanto uno" not in [g.chiave for g in r.da_rivedere]


def test_decidi_scrive_e_rilegge(tmp_path):
    p = tmp_path / "decise.json"
    frasi.decidi("torna indietro", frasi.IGNORATA, "Torna indietro.", path=p, ora=T0)
    frasi.decidi("su ottantuna", frasi.SEGNALATA, "su ottantuna.", path=p, ora=T0)
    d = frasi.carica_decise(p)
    assert d["torna indietro"]["stato"] == "ignorata"
    assert d["su ottantuna"]["frase"] == "su ottantuna."
    assert not (tmp_path / "decise.tmp").exists()


def test_decidi_rifiuta_uno_stato_sconosciuto(tmp_path):
    with pytest.raises(ValueError):
        frasi.decidi("x", "cancellata", path=tmp_path / "d.json")


def test_decise_rotte_valgono_niente(tmp_path):
    p = tmp_path / "d.json"
    p.write_text("{rotto", encoding="utf-8")
    assert frasi.carica_decise(p) == {}
    p.write_text('{"a": {"stato": "boh"}, "b": [1]}', encoding="utf-8")
    assert frasi.carica_decise(p) == {}


# --- la data di partenza e l'insieme -------------------------------------------------------

def test_data_di_partenza_il_locale_vince(tmp_path):
    (tmp_path / "gui.toml").write_text('[frasi]\ndal = "2026-09-28T14:35"\n', encoding="utf-8")
    assert frasi.data_di_partenza(tmp_path / "gui.toml") == \
        frasi.datetime(2026, 9, 28, 14, 35).timestamp()
    (tmp_path / "gui.local.toml").write_text('[frasi]\ndal = "2026-10-01T00:00"\n', encoding="utf-8")
    assert frasi.data_di_partenza(tmp_path / "gui.toml") == \
        frasi.datetime(2026, 10, 1).timestamp()


@pytest.mark.parametrize("contenuto", ["", "[meteo]\ncitta = ''\n", '[frasi]\ndal = "ieri"\n', "rotto ["])
def test_data_di_partenza_assente_o_storta(tmp_path, contenuto):
    (tmp_path / "gui.toml").write_text(contenuto, encoding="utf-8")
    assert frasi.data_di_partenza(tmp_path / "gui.toml") is None


def test_la_data_del_repository_c_e():
    """Il giorno 0 l'ha fissata: senza, il pannello leggerebbe i turni finti."""
    assert frasi.data_di_partenza() is not None


def test_raccogli_rispetta_la_partenza_e_i_trenta_giorni(tmp_path):
    righe = [_riga(T0 - 40 * 86400, "troppo vecchia", non_capito="chiarimento"),
             _riga(T0 - 10 * 86400, "prima della partenza", non_capito="chiarimento"),
             _riga(T0 - 1 * 86400, "buona", non_capito="chiarimento")]
    log = _scrivi(tmp_path / "t.jsonl", righe)
    senza = tmp_path / "nessuna.toml"
    r = frasi.raccogli(log=log, decise=tmp_path / "d.json", config=senza, ora=T0)
    assert [g.chiave for g in r.da_rivedere] == ["buona", "prima della partenza"]
    cfg = tmp_path / "gui.toml"
    partenza = frasi.datetime.fromtimestamp(T0 - 5 * 86400).isoformat(timespec="minutes")
    cfg.write_text(f'[frasi]\ndal = "{partenza}"\n', encoding="utf-8")
    r = frasi.raccogli(log=log, decise=tmp_path / "d.json", config=cfg, ora=T0)
    assert [g.chiave for g in r.da_rivedere] == ["buona"]


# === Giorno 3: le guardie sulle frasi nuove =============================================

from metis.memory.commands import Errore, Libreria  # noqa: E402
from metis.tools.registry import carica_tutti  # noqa: E402

REG = carica_tutti()


def _comando(ident, *frasi_):
    return {"id": ident, "frasi": list(frasi_), "azioni": [{"tool": "get_telemetry"}]}


@pytest.fixture
def lib(tmp_path):
    p = tmp_path / "commands.json"
    p.write_text('{"comandi": []}', encoding="utf-8")
    lib = Libreria(REG, p)
    lib.aggiungi(_comando("scrivania", "prepara la scrivania"))
    return lib


@pytest.mark.parametrize("frase,motivo", [
    ("lavora", "almeno 2 parole"),
    ("per favore lavora", "almeno 2 parole"),            # le cortesie non contano
    ("Metis, bye.", "almeno 2 parole"),                   # la storpiatura della prova
    ("prepara la scrivania", "attiva gia' il comando 'scrivania'"),
    ("Prepara la scrivania!", "attiva gia' il comando 'scrivania'"),   # normalizzata
    ("mostra i numeri", "frase fissa"),
    ("scorri giù", "frase fissa"),
    ("chiudi la prima scheda di chrome", "frase fissa"),  # PHASE2 la conosce gia'
    ("cerca su youtube gatti", "frase fissa"),
    ("scrivi nel 12: ciao", "frase fissa"),
])
def test_le_guardie_rifiutano_con_il_motivo(lib, frase, motivo):
    with pytest.raises(Errore) as e:
        lib.aggiungi(_comando("nuovo", frase))
    assert motivo in str(e.value)


def test_una_frase_buona_passa(lib):
    c = lib.aggiungi(_comando("note", "apri le mie note"))
    assert lib.get("note") == c


def test_un_rifiuto_non_tocca_il_file(lib):
    prima = lib.percorso.read_text(encoding="utf-8")
    with pytest.raises(Errore):
        lib.aggiungi(_comando("nuovo", "apri le mie note", "mostra i numeri"))
    assert lib.percorso.read_text(encoding="utf-8") == prima
    assert lib.get("nuovo") is None


def test_i_comandi_scritti_prima_restano(tmp_path):
    """`carica` non applica le regole nuove: "telemetria" e "si lavora" sono
    in `config/commands.json` da M4."""
    p = tmp_path / "commands.json"
    p.write_text(json.dumps({"comandi": [_comando("t", "telemetria", "si lavora")]}),
                 encoding="utf-8")
    lib = Libreria(REG, p)
    assert lib.avvisi == [] and lib.get("t") is not None
    # e modificarne la risposta resta possibile: le guardie guardano le frasi NUOVE
    lib.modifica("t", {**_comando("t", "telemetria", "si lavora"), "risposta": "Ecco."})
    assert lib.get("t").risposta == "Ecco."


def test_modifica_controlla_solo_le_frasi_nuove(lib):
    with pytest.raises(Errore) as e:
        lib.modifica("scrivania", _comando("scrivania", "prepara la scrivania", "lavora"))
    assert "almeno 2 parole" in str(e.value)


def test_aggiungi_frase_la_variante(lib):
    c = lib.aggiungi_frase("scrivania", "mastra la scrivania")
    assert c.frasi == ("prepara la scrivania", "mastra la scrivania")
    assert lib.get("scrivania").frasi == c.frasi


@pytest.mark.parametrize("ident,frase,motivo", [
    ("scrivania", "prepara la scrivania", "la conosce gia'"),
    ("scrivania", "bye", "almeno 2 parole"),
    ("scrivania", "mostra i numeri", "frase fissa"),
    ("fantasma", "apri le mie note", "non esiste"),
])
def test_aggiungi_frase_rifiuta(lib, ident, frase, motivo):
    with pytest.raises(Errore) as e:
        lib.aggiungi_frase(ident, frase)
    assert motivo in str(e.value)


def test_una_variante_non_puo_essere_la_frase_di_un_altro_comando(lib):
    lib.aggiungi(_comando("note", "apri le mie note"))
    with pytest.raises(Errore) as e:
        lib.aggiungi_frase("scrivania", "apri le mie note")
    assert "'note'" in str(e.value)


# --- i comandi dell'utente non cambiano il banco del router ---------------------------------

def test_i_comandi_non_cambiano_l_esito_delle_frasi_del_banco():
    """D-FRASI 7, la garanzia di PHASE2: una frase di `config/commands.json`
    non deve mai far fare altro a una frase del banco del router. Senza
    modello: e' il percorso rapido, millisecondi."""
    from benchmarks.prova_router import CASI, CASI_CONVERSAZIONE
    from metis.core.router import Router

    comandi = Libreria(REG).comandi                     # il file vero
    router = Router(REG, comandi=comandi, usa_llm=False)
    frasi_del_banco = [(f, atteso) for f, atteso, _ in CASI] + \
                      [(f, atteso) for _, f, _, atteso, _ in CASI_CONVERSAZIONE]
    rubate = []
    for frase, atteso in frasi_del_banco:
        c = router.fast_path(frase)
        if c is not None and list(c.strumenti) != (atteso or []):
            rubate.append(f"{frase!r}: il comando '{c.id}' fa {list(c.strumenti)}, "
                          f"il banco si aspetta {atteso}")
    assert rubate == []


def test_il_controllo_sul_banco_vede_un_comando_che_ruba(tmp_path):
    """Il verso negativo: un comando che si prende "che ore sono" (che il banco
    vuole in conversazione) deve far fallire il controllo di sopra."""
    from benchmarks.prova_router import CASI
    from metis.core.router import Router
    from metis.memory.commands import valida

    ladro = valida(_comando("ladro", "che ore sono"), REG)
    router = Router(REG, comandi=[ladro], usa_llm=False)
    atteso = next(a for f, a, _ in CASI if f == "che ore sono")
    c = router.fast_path("che ore sono")
    assert c is not None and list(c.strumenti) != (atteso or [])


# === Giorni 4–5: l'interfaccia ==========================================================

def _g(frase, volte=1, motivo=frasi.CHIARIMENTO, tolta=None, parametrica=None):
    return frasi.Gruppo(chiave=frasi.normalizza(frase), frase=frase, volte=volte,
                        ultima=T0, motivo=motivo, tolta=tolta,
                        parametrica=frasi.parametrica(frase, tolta)
                        if parametrica is None else parametrica)


def _r(*gruppi, turni=20, non_capiti=3, segnalate=()):
    return frasi.Raccolta(da_rivedere=list(gruppi), segnalate=list(segnalate),
                          turni=turni, non_capiti=non_capiti)


# --- le funzioni per chi guarda -------------------------------------------------------------

def test_quando_in_parole():
    ora = frasi.datetime(2026, 9, 28, 20, 0).timestamp()
    assert frasi.quando_in_parole(frasi.datetime(2026, 9, 28, 19, 4).timestamp(), ora) == "oggi 19:04"
    assert frasi.quando_in_parole(frasi.datetime(2026, 9, 27, 19, 4).timestamp(), ora) == "ieri 19:04"
    assert frasi.quando_in_parole(frasi.datetime(2026, 9, 26, 19, 12).timestamp(), ora) == "26/09 19:12"


def test_ogni_motivo_ha_le_sue_parole():
    for m in (*frasi.SEGNALI, frasi.RIPETUTA):
        assert frasi.motivo_in_parole(m) != m


def test_markdown_delle_segnalate():
    md = frasi.markdown_segnalate([_g("clicca su ottanto uno", 2, frasi.AZIONE_TOLTA, "clicca_numero"),
                                   _g("a | b")], ora=T0)
    assert md.startswith("# Metis — frasi segnalate")
    assert "| 2 | clicca su ottanto uno | azione proposta senza essere chiesta | clicca_numero |" in md
    assert "a \\| b" in md                        # la barra non rompe la tabella
    assert "nessuna" in frasi.markdown_segnalate([], ora=T0)


# --- il worker ------------------------------------------------------------------------------

def test_il_lettore_spedisce_la_raccolta(app_qt, tmp_path):
    from metis.gui.workers.frasi import LettoreFrasi

    log = _scrivi(tmp_path / "t.jsonl", SEDUTA)
    w = LettoreFrasi(config=tmp_path / "nessuna.toml", log=log, decise=tmp_path / "d.json")
    arrivate = []
    w.pronta.connect(arrivate.append)
    w.rileggi()
    assert len(arrivate) == 1 and arrivate[0].turni == len(SEDUTA)


def test_il_lettore_non_esplode_mai(app_qt):
    from metis.gui.workers.frasi import LettoreFrasi

    def rotta(**kw):
        raise RuntimeError("disco sparito")

    w = LettoreFrasi(leggi=rotta)
    arrivate = []
    w.pronta.connect(arrivate.append)
    w.rileggi()
    assert arrivate[0].turni == 0 and arrivate[0].da_rivedere == []


# --- il pannello ----------------------------------------------------------------------------

def test_il_pannello_riassume(app_qt):
    from metis.gui.widgets.frasi import PannelloFrasi

    p = PannelloFrasi()
    assert not p.bottone.isEnabled()
    p.aggiorna(_r(_g("mastra in numeria", 4), _g("uno due"), _g("tre quattro"), _g("cinque sei")))
    assert "4 frasi da rivedere" in p.riga.text() and "15%" in p.riga.text()
    assert "altre 1" in p.anteprima.text()
    assert p.bottone.isEnabled()


@pytest.mark.parametrize("raccolta,atteso", [
    (frasi.Raccolta(), "Nessun turno"),
    (frasi.Raccolta(turni=10), "Nessuna frase da rivedere · 0%"),
    (frasi.Raccolta(da_rivedere=[None], turni=10, non_capiti=1), "1 frase da rivedere · 10%"),
])
def test_il_riepilogo(raccolta, atteso):
    from metis.gui.widgets.frasi import riepilogo

    assert atteso in riepilogo(raccolta)


# --- il dialogo -----------------------------------------------------------------------------

@pytest.fixture
def dialogo(app_qt, lib, tmp_path):
    from metis.gui.widgets.frasi import DialogoFrasi

    def crea(*gruppi, segnalate=()):
        d = DialogoFrasi(_r(*gruppi, segnalate=segnalate), lib, decise=tmp_path / "decise.json")
        d.decisioni = []
        d.deciso.connect(lambda: d.decisioni.append(1))
        return d
    return crea


def test_le_frasi_con_parametro_non_diventano_comandi(dialogo):
    d = dialogo(_g("clicca su ottanto uno", tolta="clicca_numero"))
    assert not d.b_crea.isEnabled() and not d.b_variante.isEnabled()
    assert d.b_segnala.isEnabled() and d.b_ignora.isEnabled()
    assert "numero" in d.nota.text()


def test_una_frase_normale_ha_tutte_le_azioni(dialogo):
    d = dialogo(_g("apri le mie note", motivo=frasi.CONVERSAZIONE))
    assert d.b_crea.isEnabled() and d.b_variante.isEnabled()
    assert not d.b_esporta.isEnabled()                # niente da esportare, ancora


def test_ignora(dialogo, tmp_path):
    d = dialogo(_g("apri le mie note"), _g("uno due"))
    d._ignora()
    assert [g.frase for g in d.gruppi] == ["uno due"]
    assert frasi.carica_decise(tmp_path / "decise.json")["apri le mie note"]["stato"] == "ignorata"
    assert d.decisioni == [1]


def test_segnala_ed_esporta(dialogo, tmp_path):
    d = dialogo(_g("clicca su ottanto uno", 2, tolta="clicca_numero"))
    d._segnala()
    assert d.gruppi == [] and d.b_esporta.isEnabled()
    uscita = tmp_path / "segnalate.md"
    d.scegli_file = lambda: str(uscita)
    d._esporta()
    assert "clicca su ottanto uno" in uscita.read_text(encoding="utf-8")
    assert "esportate" in d.esito.text()


def test_esporta_annullato_non_scrive(dialogo, tmp_path):
    d = dialogo(segnalate=[_g("uno due")])
    d.scegli_file = lambda: None
    d._esporta()
    assert list(tmp_path.glob("*.md")) == []


def test_variante(dialogo, lib, tmp_path):
    d = dialogo(_g("mastra la scrivania"))
    d.scegli_comando = lambda ids: "scrivania"
    d._variante()
    assert "mastra la scrivania" in lib.get("scrivania").frasi
    assert frasi.carica_decise(tmp_path / "decise.json")["mastra la scrivania"]["stato"] == "risolta"
    assert "ora attiva 'scrivania'" in d.esito.text()


def test_variante_rifiutata_dalle_guardie(dialogo, lib, tmp_path):
    """La guardia parla nel dialogo, e la frase resta da rivedere."""
    d = dialogo(_g("prepara la scrivania"))          # la conosce gia'
    d.scegli_comando = lambda ids: "scrivania"
    d._variante()
    assert len(d.gruppi) == 1 and "gia'" in d.esito.text()
    assert frasi.carica_decise(tmp_path / "decise.json") == {}


def test_variante_annullata(dialogo, lib):
    d = dialogo(_g("mastra la scrivania"))
    d.scegli_comando = lambda ids: None
    d._variante()
    assert len(d.gruppi) == 1 and lib.get("scrivania").frasi == ("prepara la scrivania",)


def test_crea_comando(dialogo, lib, tmp_path):
    visti = []

    def editor_finto(frase, suggerito):
        visti.append((frase, suggerito))
        lib.aggiungi({"id": "note", "frasi": [frase], "azioni": [{"tool": "get_telemetry"}]})

    d = dialogo(_g("apri le mie note", tolta="open_application"))
    d.apri_editor = editor_finto
    d._crea()
    assert visti == [("apri le mie note", "open_application")]
    assert d.gruppi == [] and "comando" in d.esito.text()
    assert frasi.carica_decise(tmp_path / "decise.json")["apri le mie note"]["stato"] == "risolta"


def test_crea_comando_chiuso_senza_salvare(dialogo, tmp_path):
    d = dialogo(_g("apri le mie note"))
    d.apri_editor = lambda frase, suggerito: None
    d._crea()
    assert len(d.gruppi) == 1 and frasi.carica_decise(tmp_path / "decise.json") == {}


# --- l'editor precompilato --------------------------------------------------------------------

def test_l_editor_parte_dalla_frase(app_qt, lib):
    from metis.gui.widgets.comandi import EditorComandi

    e = EditorComandi(lib)
    e.nuovo_da_frase("Apri le mie note", "open_application")
    assert e.campo_frasi.toPlainText() == "Apri le mie note"
    assert e.campo_id.text() == "apri_le_mie_note"
    assert json.loads(e.campo_azioni.toPlainText()) == [{"tool": "open_application"}]
    assert "argomenti sono da scrivere" in e.esito.text()
    e._salva()                                   # senza "app" non si salva
    assert lib.get("apri_le_mie_note") is None and "argomenti non validi" in e.esito.text()
    e.close()


def test_l_editor_senza_suggerimento_o_con_uno_che_non_esiste(app_qt, lib):
    from metis.gui.widgets.comandi import EditorComandi

    e = EditorComandi(lib)
    for suggerito in (None, "delete_file"):
        e.nuovo_da_frase("apri le mie note", suggerito)
        assert e.campo_azioni.toPlainText() == "[]"
    e.close()


def test_l_identificativo_non_ripete_quelli_che_ci_sono(app_qt, lib):
    from metis.gui.widgets.comandi import EditorComandi

    e = EditorComandi(lib)
    e.nuovo_da_frase("scrivania!")                   # "scrivania" c'e' gia'
    assert e.campo_id.text() == "scrivania_2"
    e.close()


# --- l'Hub e l'applicazione --------------------------------------------------------------------

def test_il_contatore_della_sessione(app_qt):
    from metis.gui.widgets.sistema import PannelloSessione

    s = PannelloSessione()
    chiesti = []
    s.chiede_frasi.connect(lambda: chiesti.append(1))
    s.imposta_frasi(0)
    assert s.frasi.isHidden()
    s.imposta_frasi(3)
    assert not s.frasi.isHidden() and s.frasi.text() == "3 frasi non capite da rivedere"
    s.imposta_frasi(1)
    assert s.frasi.text() == "1 frase non capita da rivedere"
    s.frasi.click()
    assert chiesti == [1]


def test_l_applicazione_collega_le_frasi(crea_applicazione):
    a = crea_applicazione()
    assert a.thread_frasi.objectName() == "metis-frasi"
    assert a.worker_frasi.config == a.config          # mai il gui.toml vero, nei test
    a._frasi(_r(_g("uno due"), _g("tre quattro")))
    assert "2 frasi da rivedere" in a.fullscreen.frasi.riga.text()
    assert not a.hub.sessione.frasi.isHidden()
    a.hub.sessione.chiede_frasi.emit()
    assert a._vista_attiva == "fullscreen"
