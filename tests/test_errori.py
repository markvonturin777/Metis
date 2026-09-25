"""La matrice degli errori di M7: cosa si dice, e cosa si fa, quando qualcosa
si rompe.

Il principio da verificare e' uno solo — nessun traceback raggiunge
l'utente — ma si verifica in tanti posti quanti sono quelli da cui un
traceback potrebbe uscire: la voce, la GUI, lo scheduler.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from metis.core import errors
from metis.core.errors import (
    SALUTE,
    Categoria,
    Esaurito,
    Indisponibile,
    Salute,
    classifica,
    messaggio,
    riprova,
)


@pytest.fixture(autouse=True)
def salute_pulita():
    """SALUTE e' globale: un test che lascia l'inferenza "giu'" farebbe
    fallire tutti quelli dopo, in modo misterioso."""
    for c in Categoria:
        SALUTE.su(c)
    yield
    for c in Categoria:
        SALUTE.su(c)


# --- classificazione: sui tipi VERI -----------------------------------------------

def test_lo_streaming_di_ollama_solleva_httpx_e_si_riconosce():
    """Misurato in M7: in streaming il client di Ollama NON solleva
    `ConnectionError` ma `httpx.ConnectError`. E' il percorso che Metis usa
    sempre, e la prima cosa da riconoscere."""
    import ollama

    c = ollama.Client(host="http://127.0.0.1:1")
    with pytest.raises(Exception) as e:
        list(c.chat(model="qwen3:8b", messages=[{"role": "user", "content": "x"}],
                    stream=True))
    assert type(e.value).__module__.startswith("httpx")
    assert classifica(e.value) is Categoria.INFERENZA


def test_la_chiamata_normale_di_ollama_si_riconosce():
    import ollama

    with pytest.raises(ConnectionError) as e:
        ollama.Client(host="http://127.0.0.1:1").list()
    assert classifica(e.value) is Categoria.INFERENZA


def test_modello_mancante_e_oom():
    import ollama

    manca = ollama.ResponseError("model 'x' not found", 404)
    oom = ollama.ResponseError("CUDA error: out of memory", 500)
    assert classifica(manca) is Categoria.MODELLO_MANCANTE
    assert classifica(oom) is Categoria.INFERENZA_OOM


def test_un_errore_di_programmazione_non_e_un_guasto_di_rete():
    assert classifica(KeyError("x")) is Categoria.SCONOSCIUTO


# --- il principio: mai il testo dell'eccezione ---------------------------------

@pytest.mark.parametrize("exc", [
    ConnectionError("Failed to connect to Ollama. Please check that Ollama..."),
    KeyError("chiave_interna"),
    RuntimeError("Traceback (most recent call last): ..."),
    OSError("[WinError 10061] Impossibile stabilire la connessione"),
])
def test_il_messaggio_non_contiene_mai_l_eccezione(exc):
    frase = messaggio(exc)
    assert frase
    for pezzo in (type(exc).__name__, "Error", "Traceback", "WinError", "Ollama"):
        assert pezzo not in frase, f"{pezzo!r} nella frase per l'utente: {frase}"


def test_ogni_categoria_ha_una_frase_tranne_la_voce():
    """La sintesi e' l'unica senza frase: quando si rompe la voce, non c'e'
    modo di dirlo a voce."""
    for c in Categoria:
        if c is Categoria.SINTESI:
            assert errors.MATRICE[c].messaggio == ""
        else:
            assert errors.MATRICE[c].messaggio, c


def test_esaurito_e_indisponibile_portano_la_categoria():
    assert messaggio(Esaurito(Categoria.POSTA, OSError("x"))) == \
        errors.MATRICE[Categoria.POSTA].messaggio
    assert messaggio(Indisponibile(Categoria.INFERENZA)) == \
        errors.MATRICE[Categoria.INFERENZA].messaggio


# --- riprova --------------------------------------------------------------------------

def test_riprova_la_stessa_categoria_poi_si_arrende():
    tentativi, pause = [], []

    def rotto():
        tentativi.append(1)
        raise ConnectionError("Failed to connect to Ollama")

    with pytest.raises(Esaurito) as e:
        riprova(rotto, Categoria.INFERENZA, attendi=pause.append)
    assert len(tentativi) == errors.MATRICE[Categoria.INFERENZA].tentativi + 1
    assert e.value.categoria is Categoria.INFERENZA


def test_non_riprova_un_errore_di_un_altra_specie():
    """Un KeyError non guarisce aspettando mezzo secondo."""
    tentativi = []

    def rotto():
        tentativi.append(1)
        raise KeyError("x")

    with pytest.raises(KeyError):
        riprova(rotto, Categoria.INFERENZA, attendi=lambda s: None)
    assert tentativi == [1]


def test_riprova_e_riesce():
    n = {"i": 0}

    def a_volte():
        n["i"] += 1
        if n["i"] == 1:
            raise ConnectionError("Failed to connect to Ollama")
        return "ok"

    assert riprova(a_volte, Categoria.INFERENZA, attendi=lambda s: None) == "ok"


# --- salute ------------------------------------------------------------------------------

def test_salute_giu_su_e_richiedi():
    s = Salute()
    s.richiedi(Categoria.INFERENZA)                       # su: non solleva
    s.giu(Categoria.INFERENZA)
    with pytest.raises(Indisponibile):
        s.richiedi(Categoria.INFERENZA)
    s.su(Categoria.INFERENZA)
    s.richiedi(Categoria.INFERENZA)
    assert s.cadute == 1 and s.riprese == 1


def test_la_sonda_rimette_su_il_servizio_quando_torna():
    s = Salute()
    torna = {"si": False}
    s.giu(Categoria.INFERENZA)
    s.sorveglia(Categoria.INFERENZA, lambda: torna["si"], periodo_s=0.05)
    try:
        time.sleep(0.15)
        assert s.e_giu(Categoria.INFERENZA)
        torna["si"] = True
        t0 = time.perf_counter()
        while s.e_giu(Categoria.INFERENZA) and time.perf_counter() - t0 < 2:
            time.sleep(0.02)
        assert not s.e_giu(Categoria.INFERENZA)
    finally:
        s.ferma()


def test_con_l_inferenza_giu_non_si_paga_la_connessione():
    """Il motivo per cui `Salute` esiste: una connessione rifiutata costa
    2,26 s su Windows. Noto come giu', il client rifiuta subito."""
    from metis.llm.client import LlmClient

    c = LlmClient(host="http://127.0.0.1:1")
    SALUTE.giu(Categoria.INFERENZA)
    t0 = time.perf_counter()
    with pytest.raises(Indisponibile):
        list(c.stream_sentences([{"role": "user", "content": "x"}]))
    assert time.perf_counter() - t0 < 0.1


def test_il_router_con_l_inferenza_giu_risponde_subito_conversazione():
    from metis.llm.toolcall import ToolRouter
    from metis.tools.registry import carica_tutti

    r = ToolRouter(carica_tutti(), host="http://127.0.0.1:1")
    SALUTE.giu(Categoria.INFERENZA)
    t0 = time.perf_counter()
    d = r.decidi("che ore sono")
    assert not d.e_strumento and time.perf_counter() - t0 < 0.5


def test_un_fallimento_vero_segna_l_inferenza_giu():
    from metis.llm.client import LlmClient

    c = LlmClient(host="http://127.0.0.1:1")
    c._attendi = lambda s: None
    with pytest.raises(Esaurito):
        list(c.stream_sentences([{"role": "user", "content": "x"}]))
    assert SALUTE.e_giu(Categoria.INFERENZA)
    assert c.fallimenti == 1


def test_oom_sposta_whisper_e_riprova_una_volta():
    """Ollama senza memoria grafica: si chiama `su_oom` e si riprova."""
    import ollama

    from metis.llm.client import LlmClient

    c = LlmClient()
    chiamate = {"n": 0, "oom": 0}

    def apri(msgs):
        chiamate["n"] += 1
        if chiamate["n"] == 1:
            raise ollama.ResponseError("CUDA error: out of memory", 500)
        return iter([{"message": {"content": "Eccomi."}}])

    c._apri_stream = apri
    c.su_oom = lambda: chiamate.__setitem__("oom", chiamate["oom"] + 1)
    frasi = [f for f, _ in c.stream_sentences([{"role": "user", "content": "x"}])]
    assert frasi == ["Eccomi."] and chiamate["oom"] == 1


# --- il turno fallito si dice -------------------------------------------------------

def test_descrivi_non_pronuncia_mai_il_testo_di_un_eccezione():
    from metis.core.risposte import descrivi
    from metis.security.audit import Outcome
    from metis.security.broker import Result

    r = Result(ok=False, outcome=Outcome.ERROR, stage="esecuzione",
               detail="ConnectionRefusedError: [WinError 10061] ...", tool="open_url")
    frase = descrivi(r)
    assert "Error" not in frase and "WinError" not in frase
    assert frase == messaggio(Categoria.STRUMENTO)


def test_descrivi_non_pronuncia_pydantic():
    """"Non lo faccio: to: String should match pattern..." era pronunciato."""
    from metis.core.risposte import descrivi
    from metis.security.audit import Outcome
    from metis.security.broker import Result

    r = Result(ok=False, outcome=Outcome.DENIED, stage="schema",
               detail="to: String should match pattern '^[^@\\s]+@'", tool="send_email")
    assert "pattern" not in descrivi(r) and "String" not in descrivi(r)


# --- il microfono che sparisce e torna ----------------------------------------------

class CatturaFinta:
    """Consegna blocchi finche' `vivo`, poi niente — come un Yeti scollegato."""

    def __init__(self, stato):
        self.stato = stato

    def start(self):
        if not self.stato["collegato"]:
            raise RuntimeError("nessun device di ingresso 'Yeti' su Windows WASAPI")

    def stop(self):
        pass

    def read(self, timeout=0.25):
        if self.stato["collegato"]:
            time.sleep(0.005)
            from metis.audio.capture import Block

            return Block(np.zeros(512, np.float32), -60.0, -60.0)
        time.sleep(min(timeout, 0.02))
        return None


class Orch:
    def __init__(self):
        self.blocchi = 0
        self.tick_n = 0

    def on_audio(self, b):
        self.blocchi += 1

    def tick(self):
        self.tick_n += 1


def _ciclo(stato, eventi, **kw):
    from metis.core.avvio import CicloAudio

    o = Orch()
    c = CicloAudio(o, tick_s=0.02, on_microfono=eventi.append,
                   apri_cattura=lambda: CatturaFinta(stato),
                   silenzio_device_s=0.1, riapertura_s=0.05, **kw)
    return o, c


def test_microfono_assente_all_avvio_non_chiude_metis():
    """Con l'autostart il login arriva prima che Windows abbia enumerato i
    device USB. Fino a M6 Metis si chiudeva."""
    import threading

    stato = {"collegato": False}
    eventi = []
    o, c = _ciclo(stato, eventi)
    t = threading.Thread(target=c.esegui, kwargs={"limite_s": 1.0}, daemon=True)
    t.start()
    time.sleep(0.3)
    assert eventi == [False], "l'assenza non e' stata detta, o detta piu' volte"
    assert o.tick_n > 0, "i timeout non scattano senza microfono"
    stato["collegato"] = True
    t.join(2)
    assert eventi == [False, True]
    assert o.blocchi > 0


def test_microfono_scollegato_mentre_gira_e_ricollegato():
    import threading

    stato = {"collegato": True}
    eventi = []
    o, c = _ciclo(stato, eventi)
    t = threading.Thread(target=c.esegui, kwargs={"limite_s": 1.5}, daemon=True)
    t.start()
    time.sleep(0.2)
    stato["collegato"] = False                     # scollegato
    time.sleep(0.5)
    assert eventi == [True, False]
    stato["collegato"] = True                      # ricollegato
    t.join(3)
    assert eventi == [True, False, True]
    assert c.perdite == 1


# --- la voce di riserva ------------------------------------------------------------------

class VoceRotta:
    sample_rate = 22050

    def synth(self, t):
        raise RuntimeError("sessione onnx persa")

    def warmup(self):
        return 0.0


class VoceBuona:
    def __init__(self, sr=24000):
        self.sample_rate = sr

    def synth(self, t):
        from metis.tts import _Sintesi
        return _Sintesi(np.ones(self.sample_rate, np.float32) * 0.1, self.sample_rate, t)


def test_la_voce_primaria_rotta_non_ferma_il_turno():
    from metis.tts import SintesiRobusta

    r = SintesiRobusta(VoceRotta(), crea_riserva=lambda: VoceBuona())
    prima = r.synth("uno")                        # riserva ancora in caricamento
    assert prima.pcm.size > 0 and r.muti == 1     # silenzio breve, non un buco
    r._caricamento.join(5)
    seconda = r.synth("due")
    # 1 s a 24 kHz ricampionato a 22,05 kHz: la durata resta, i campioni no.
    assert abs(seconda.pcm.size - 22050) < 50
    assert seconda.sample_rate == 22050 and r.su_riserva == 1


def test_senza_riserva_resta_il_testo():
    from metis.tts import SintesiRobusta

    def non_c_e():
        raise ImportError("kokoro non installato")

    r = SintesiRobusta(VoceRotta(), crea_riserva=non_c_e)
    r.synth("uno")
    r._caricamento.join(5)
    r.synth("due")
    assert r.muti == 2 and r.su_riserva == 0


def test_la_riserva_si_prova_una_volta_sola():
    from metis.tts import SintesiRobusta

    tentativi = []

    def non_c_e():
        tentativi.append(1)
        raise ImportError("x")

    r = SintesiRobusta(VoceRotta(), crea_riserva=non_c_e)
    for _ in range(5):
        r.synth("x")
        if getattr(r, "_caricamento", None):
            r._caricamento.join(5)
    assert tentativi == [1]


# --- la posta non si perde ----------------------------------------------------------

@pytest.mark.parametrize("exc,atteso", [
    (ConnectionRefusedError("rifiutata"), True),
    (TimeoutError("timeout"), True),
    ("4xx", True),
    ("5xx", False),
    ("cert", False),
    ("rifiuto", False),
])
def test_quali_errori_smtp_passano_da_soli(exc, atteso):
    import smtplib
    import ssl

    from metis.tools import posta
    from metis.tools.registry import Rifiuto

    e = {"4xx": smtplib.SMTPResponseException(421, b"riprova"),
         "5xx": smtplib.SMTPResponseException(550, b"no"),
         "cert": ssl.SSLCertVerificationError("certificato non valido"),
         "rifiuto": Rifiuto("credenziali")}.get(exc, exc)
    assert posta.transitorio(e) is atteso


def test_un_email_confermata_non_si_perde_se_il_server_non_risponde(tmp_path, monkeypatch):
    from metis.security.audit import AuditLog
    from metis.security.broker import Broker
    from metis.security.policies import Context
    from metis.tools import posta
    from metis.tools import scheduler as sch
    from metis.tools.registry import carica_tutti

    lista = tmp_path / "e.toml"
    lista.write_text('[allowlist]\nindirizzi = ["a@b.it"]\n', encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", lista)

    def giu(*a, **k):
        raise ConnectionRefusedError("server SMTP spento")

    monkeypatch.setattr(posta, "invia", giu)
    p = sch.Pianificatore(f"sqlite:///{(tmp_path / 'j.db').as_posix()}")
    p.avvia(in_pausa=True)
    sch.usa_pianificatore(p)
    try:
        b = Broker(registry=carica_tutti(), audit=AuditLog(tmp_path / "a.db"))
        r = b.execute({"tool": "send_email", "to": "a@b.it", "subject": "s",
                       "body": "b"}, Context(chiedi_conferma=lambda s, c: True))
        assert r.ok and r.value.get("rimandata")
        voci = p.voci()
        assert [v.tipo for v in voci] == [sch.EMAIL]
        from metis.core.risposte import descrivi
        assert descrivi(r) == messaggio(Categoria.POSTA)
    finally:
        p.ferma()
        sch.usa_pianificatore(None)


def test_la_consegna_programmata_rimanda_fino_a_un_ora(tmp_path, monkeypatch):
    from metis.core.avvio import Consegne
    from metis.security.audit import AuditLog
    from metis.tools import notify, posta
    from metis.tools import scheduler as sch

    monkeypatch.setattr(posta, "invia", lambda *a, **k: (_ for _ in ()).throw(
        ConnectionRefusedError("giu")))
    notify.usa_backend(lambda n, c: None)
    p = sch.Pianificatore(f"sqlite:///{(tmp_path / 'j.db').as_posix()}")
    p.avvia(in_pausa=True)
    sch.usa_pianificatore(p)
    annunci = []

    class Orchestratore:
        def annuncia(self, t):
            annunci.append(t)

    try:
        c = Consegne(Orchestratore(), AuditLog(tmp_path / "a.db"))
        dati = {"to": "a@b.it", "subject": "s", "body": "b", "confermata_il": "x"}
        c.email({**dati, "rimandi": 0})
        assert [v.tipo for v in p.voci()] == [sch.EMAIL]
        assert annunci[-1] == messaggio(Categoria.POSTA)

        c.email({**dati, "rimandi": posta.MAX_RIMANDI})   # l'ultimo: si rinuncia
        assert "non e' partita" in annunci[-1]
        assert "ConnectionRefused" not in annunci[-1]
    finally:
        notify.usa_backend(None)
        p.ferma()
        sch.usa_pianificatore(None)


# --- avvio robusto -----------------------------------------------------------------

def test_attendi_ollama_si_arrende_senza_sollevare():
    from metis.core.avvio import attendi_ollama

    class Mai:
        def disponibile(self):
            return False

    righe = []
    finto = {"t": 0.0}

    def attendi(s):
        finto["t"] += s

    import metis.core.avvio as av

    orologio = av.time.perf_counter
    av.time.perf_counter = lambda: finto["t"]
    try:
        assert attendi_ollama(Mai(), righe.append, 20, passo_s=2, attendi=attendi) is False
    finally:
        av.time.perf_counter = orologio
    assert righe and "aspetto" in righe[0]


def test_attendi_ollama_torna_appena_risponde():
    from metis.core.avvio import attendi_ollama

    class AlTerzo:
        n = 0

        def disponibile(self):
            self.n += 1
            return self.n >= 3

    assert attendi_ollama(AlTerzo(), lambda r: None, 60, attendi=lambda s: None)


@pytest.mark.parametrize("ora,apertura", [(8, "Buongiorno"), (15, "Buon pomeriggio"),
                                          (21, "Buonasera"), (2, "Buonasera")])
def test_saluto(ora, apertura):
    from metis.core.avvio import saluto

    assert saluto(ora).startswith(apertura)


def test_sorveglia_vram_sposta_whisper_una_volta():
    from metis.core.avvio import sorveglia_vram
    from metis.tools import notify

    class Stt:
        spostato = 0

        def su_cpu(self):
            self.spostato += 1
            return True

    class Log:
        def warning(self, *a, **k):
            pass

    notify.usa_backend(lambda n, c: None)
    letture = iter([6.0, 7.9, 7.9])
    stt = Stt()
    try:
        sorveglia_vram(stt, Log(), periodo_s=0.01, leggi=lambda: next(letture))
        t0 = time.perf_counter()
        while not stt.spostato and time.perf_counter() - t0 < 2:
            time.sleep(0.01)
        time.sleep(0.05)
    finally:
        notify.usa_backend(None)
    assert stt.spostato == 1


# --- M7: una sola finestra di contesto ------------------------------------------

def test_router_e_conversazione_chiedono_a_ollama_lo_stesso_contesto():
    """Con `num_ctx` diversi Ollama ricarica il modello a ogni cambio: 3,6 s
    misurati, due volte per turno. Il router non lo passava affatto (default
    4096) e la conversazione chiedeva 8192. Qui si catturano le opzioni
    davvero spedite dalle due chiamate e si confrontano."""
    from metis.llm.client import LlmClient
    from metis.llm.toolcall import ToolRouter
    from metis.tools.registry import carica_tutti

    spedite = []

    class ClientFinto:
        def chat(self, **kw):
            spedite.append(kw.get("options", {}))
            if kw.get("stream"):
                return iter([{"message": {"content": "Ciao."}, "done": True}])
            return {"message": {"content": '{"azioni": [{"tool": "nessuno"}]}'}}

    r = ToolRouter(carica_tutti())
    r.client = ClientFinto()
    r.decidi("ciao")
    llm = LlmClient()
    llm.client = ClientFinto()
    list(llm.stream_sentences([{"role": "user", "content": "ciao"}]))

    assert len(spedite) >= 2
    contesti = {o.get("num_ctx") for o in spedite}
    assert contesti == {llm.options["num_ctx"]}, contesti


def test_rete_assente_si_dice_con_la_frase_della_matrice():
    """Tre copie della stessa frase (web, grounding, orchestratore) erano
    rimaste a M5, e nessuna diceva la meta' che la matrice aggiunge: il resto
    di Metis funziona ancora. `Categoria.RETE` non la usava nessuno."""
    from metis.core.errors import Categoria, messaggio
    from metis.llm import grounding
    from metis.tools import web

    frase = messaggio(Categoria.RETE)
    assert web.NON_RAGGIUNGIBILE == grounding.SENZA_FONTI == frase
    assert "sistema" in frase
