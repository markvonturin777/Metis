"""Il broker e' l'unico modulo con un requisito di copertura, perche' e'
l'unico il cui fallimento e' pericoloso invece che fastidioso.

I casi che contano davvero sono quelli avversariali: simulano un modello che
prova ad aggirare i vincoli, per allucinazione o perche' qualcuno gliel'ha
suggerito in un testo. Una copertura del 95% raggiunta con soli casi felici
sarebbe il tipo di verifica che passa sempre e non protegge da niente.

Il registro qui e' costruito a mano con strumenti finti: usare quello vero
legherebbe i test all'elenco degli strumenti, che cambia a ogni iterazione,
e renderebbe impossibile provare un T3 che esegue davvero.
"""
from dataclasses import dataclass
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from metis.security.audit import AuditLog, Outcome, Tier
from metis.security.broker import Broker, Result
from metis.security.guards import Finestra, Guard, guardia_combinazione, guardia_finestra
from metis.security.killswitch import KillSwitch
from metis.security.policies import Context
from metis.tools.registry import Registry


# --- strumenti finti ---------------------------------------------------------

class Leggi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["leggi"]


class Apri(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["apri"]
    app: Literal["vscode", "github_desktop"]


class Scrivi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["scrivi"]
    text: str = Field(..., max_length=20)


class Manda(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["manda"]
    to: str = Field(..., max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Sposta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["sposta"]
    monitor: int = Field(..., ge=0, le=3)


class Tasti(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["tasti"]
    keys: list[str] = Field(..., max_length=4)


@dataclass
class Banco:
    broker: Broker
    audit: AuditLog
    kill: KillSwitch
    eseguiti: list
    finestra: list          # finestra[0] e' quella corrente, mutabile nei test


@pytest.fixture
def banco(tmp_path):
    eseguiti: list = []
    finestra = [Finestra("Editor", "Code.exe", "Chrome_WidgetWin_1")]
    reg = Registry("test")

    @reg.strumento(Tier.T0, Leggi)
    def _leggi(call):
        eseguiti.append("leggi")
        return {"valore": 42}

    @reg.strumento(Tier.T1, Apri)
    def _apri(call):
        eseguiti.append(("apri", call.app))
        return {"app": call.app}

    @reg.strumento(Tier.T2, Scrivi, guards=(guardia_finestra(lambda: finestra[0]),))
    def _scrivi(call):
        eseguiti.append(("scrivi", call.text))
        return {"scritto": call.text}

    @reg.strumento(Tier.T2, Tasti, guards=(guardia_combinazione(),))
    def _tasti(call):
        eseguiti.append(("tasti", call.keys))
        return {"premuti": call.keys}

    @reg.strumento(Tier.T3, Manda)
    def _manda(call):
        eseguiti.append(("manda", call.to))
        return {"inviata": call.to}

    @reg.strumento(Tier.T1, Sposta, implemented=False)
    def _sposta(call):
        raise NotImplementedError

    audit = AuditLog(tmp_path / "audit.db")
    kill = KillSwitch()
    yield Banco(Broker(registry=reg, audit=audit, kill=kill, timeout_conferma_s=0.5),
                audit, kill, eseguiti, finestra)
    audit.close()


def si(spec, call):
    return True


def no(spec, call):
    return False


# --- casi positivi -----------------------------------------------------------

def test_t0_passa_e_viene_loggato(banco):
    r = banco.broker.execute('{"tool": "leggi"}', Context(turn_id="t1"))
    assert r.ok and r.value == {"valore": 42}
    riga = banco.audit.recent()[0]
    assert riga["tool"] == "leggi" and riga["outcome"] == "ok" and riga["turn_id"] == "t1"


def test_t1_con_app_in_allowlist(banco):
    r = banco.broker.execute({"tool": "apri", "app": "vscode"})
    assert r.ok and banco.eseguiti == [("apri", "vscode")]


def test_t3_con_conferma_viene_eseguito_e_marcato(banco):
    r = banco.broker.execute({"tool": "manda", "to": "a@b.it"},
                             Context(chiedi_conferma=si))
    assert r.ok and r.confirmed is True
    assert banco.audit.recent()[0]["confirmed"] == 1
    assert banco.audit.unconfirmed_t3() == 0


def test_t2_con_finestra_innocua_passa(banco):
    r = banco.broker.execute({"tool": "scrivi", "text": "ciao"})
    assert r.ok, r.detail


# --- casi negativi -----------------------------------------------------------

def test_json_malformato(banco):
    r = banco.broker.execute("{non json")
    assert r.denied and r.stage == "json"


def test_json_che_non_e_un_oggetto(banco):
    r = banco.broker.execute("[1, 2, 3]")
    assert r.denied and r.stage == "json"


def test_manca_il_campo_tool(banco):
    r = banco.broker.execute('{"app": "vscode"}')
    assert r.denied and r.stage == "registro"


def test_strumento_inesistente(banco):
    r = banco.broker.execute('{"tool": "delete_file", "path": "C:/dati"}')
    assert r.denied and r.stage == "registro" and "delete_file" in r.detail


def test_campo_mancante(banco):
    r = banco.broker.execute('{"tool": "apri"}')
    assert r.denied and r.stage == "schema"


def test_numero_fuori_range(banco):
    r = banco.broker.execute('{"tool": "sposta", "monitor": 99}')
    assert r.denied and r.stage == "schema" and "monitor" in r.detail


def test_stringa_oltre_max_length(banco):
    r = banco.broker.execute({"tool": "scrivi", "text": "x" * 500})
    assert r.denied and r.stage == "schema"


def test_campo_inventato_rifiutato(banco):
    """extra='forbid': un campo in piu' e' un'ipotesi che nessuno ha verificato."""
    r = banco.broker.execute({"tool": "leggi", "forza": "massima"})
    assert r.denied and r.stage == "schema"


def test_t3_con_conferma_negata(banco):
    r = banco.broker.execute({"tool": "manda", "to": "a@b.it"},
                             Context(chiedi_conferma=no))
    assert r.denied and r.stage == "conferma"
    assert banco.eseguiti == []
    assert banco.audit.unconfirmed_t3() == 0


def test_t3_senza_nessuno_che_possa_confermare(banco):
    """Il default sicuro e' il rifiuto, non l'esecuzione."""
    r = banco.broker.execute({"tool": "manda", "to": "a@b.it"}, Context())
    assert r.denied and r.stage == "conferma" and banco.eseguiti == []


def test_t3_con_conferma_scaduta(banco):
    """Vent'anni di dialoghi hanno insegnato a premere Invio: un timeout che
    vale sì e' peggio di nessuna conferma, perche' produce un log che dice
    che l'utente era d'accordo."""
    import time

    def lentissimo(spec, call):
        time.sleep(5)
        return True

    r = banco.broker.execute({"tool": "manda", "to": "a@b.it"},
                             Context(chiedi_conferma=lentissimo))
    assert r.denied and r.stage == "conferma"
    assert banco.eseguiti == []
    assert banco.audit.unconfirmed_t3() == 0


def test_conferma_che_esplode_vale_no(banco):
    def rotta(spec, call):
        raise RuntimeError("dialogo non disponibile")

    r = banco.broker.execute({"tool": "manda", "to": "a@b.it"},
                             Context(chiedi_conferma=rotta))
    assert r.denied and banco.eseguiti == []


def test_kill_switch_sospende_t2(banco):
    banco.kill.sospendi()
    r = banco.broker.execute({"tool": "scrivi", "text": "ciao"})
    assert r.denied and r.stage == "policy" and "kill switch" in r.detail


def test_kill_switch_sospende_t3(banco):
    banco.kill.sospendi()
    r = banco.broker.execute({"tool": "manda", "to": "a@b.it"},
                             Context(chiedi_conferma=si))
    assert r.denied and r.stage == "policy"


def test_kill_switch_non_tocca_t0_e_t1(banco):
    """Se spegnesse tutto la si userebbe di meno, e un interruttore di
    sicurezza che si evita di usare non e' un interruttore di sicurezza."""
    banco.kill.sospendi()
    assert banco.broker.execute('{"tool": "leggi"}').ok
    assert banco.broker.execute({"tool": "apri", "app": "vscode"}).ok


def test_strumento_registrato_ma_senza_capacita(banco):
    r = banco.broker.execute({"tool": "sposta", "monitor": 1})
    assert not r.ok and r.outcome is Outcome.ERROR
    assert "non ancora disponibile" in r.detail


# --- casi avversariali -------------------------------------------------------

def test_app_fuori_dall_enum(banco):
    r = banco.broker.execute('{"tool": "apri", "app": "cmd.exe"}')
    assert r.denied and r.stage == "schema"


def test_traversal_nel_nome_app(banco):
    r = banco.broker.execute(
        '{"tool": "apri", "app": "../../../windows/system32/cmd.exe"}')
    assert r.denied and r.stage == "schema"


def test_scrittura_con_esplora_risorse_davanti(banco):
    """Una battuta di tasti dentro Esplora rinomina o cancella file, senza che
    nessuno strumento abbia mai accettato un percorso."""
    banco.finestra[0] = Finestra("Documenti", "explorer.exe", "CabinetWClass")
    r = banco.broker.execute({"tool": "scrivi", "text": "ciao"})
    assert r.denied and r.stage == "guardie" and "explorer.exe" in r.detail
    assert banco.eseguiti == []


def test_scrittura_in_un_dialogo_di_file(banco):
    banco.finestra[0] = Finestra("Salva con nome", "Code.exe", "#32770")
    r = banco.broker.execute({"tool": "scrivi", "text": "ciao"})
    assert r.denied and r.stage == "guardie"


def test_scrittura_con_finestra_non_identificabile(banco):
    """Non sapere dove si sta scrivendo e' peggio che saperlo male."""
    banco.finestra[0] = Finestra("", "?", "?")
    assert banco.broker.execute({"tool": "scrivi", "text": "x"}).denied


@pytest.mark.parametrize("combo", [
    ["shift", "delete"],
    ["delete", "shift"],            # stesso insieme, ordine diverso
    ["win", "r"],
    ["ctrl", "shift", "enter"],
    ["ctrl", "alt", "delete"],
    ["alt", "f4"],
    ["SHIFT", "Delete"],            # maiuscole
    ["ctrl", "shift", "delete"],    # sovrainsieme di una vietata
])
def test_combinazioni_vietate(banco, combo):
    r = banco.broker.execute({"tool": "tasti", "keys": combo})
    assert r.denied and r.stage == "guardie", f"{combo} e' passata"
    assert banco.eseguiti == []


def test_combinazione_innocua_passa(banco):
    assert banco.broker.execute({"tool": "tasti", "keys": ["ctrl", "c"]}).ok


def test_t2_vietato_dopo_contenuto_web(banco):
    """Una pagina web puo' contenere istruzioni rivolte al modello. Il
    contenuto recuperato e' dato, mai comando."""
    r = banco.broker.execute({"tool": "scrivi", "text": "ciao"},
                             Context(has_untrusted_content=True))
    assert r.denied and r.stage == "policy" and "web" in r.detail


def test_t3_vietato_dopo_contenuto_web(banco):
    r = banco.broker.execute({"tool": "manda", "to": "a@b.it"},
                             Context(has_untrusted_content=True, chiedi_conferma=si))
    assert r.denied and r.stage == "policy"
    assert banco.eseguiti == []


def test_t0_resta_permesso_dopo_contenuto_web(banco):
    """Riassumere una pagina non e' pericoloso. Agire in sua conseguenza sì."""
    assert banco.broker.execute('{"tool": "leggi"}',
                                Context(has_untrusted_content=True)).ok


def test_la_finestra_cambia_fra_autorizzazione_ed_esecuzione(banco):
    """Il rischio piu' subdolo: la guardia passa, l'utente clicca altrove, e
    il testo finisce in una casella di rinomina file."""
    chiamate = {"n": 0}

    def finestra_che_cambia():
        chiamate["n"] += 1
        # innocua al primo controllo, pericolosa al secondo
        return (Finestra("Editor", "Code.exe", "X") if chiamate["n"] == 1
                else Finestra("Documenti", "explorer.exe", "CabinetWClass"))

    reg = Registry("corsa")

    @reg.strumento(Tier.T2, Scrivi, guards=(guardia_finestra(finestra_che_cambia),))
    def _scrivi(call):
        banco.eseguiti.append("NON DOVEVA ESEGUIRE")
        return {}

    b = Broker(registry=reg, audit=banco.audit, kill=banco.kill)
    r = b.execute({"tool": "scrivi", "text": "ciao"})

    assert chiamate["n"] == 2, "la guardia non e' stata rivalutata"
    assert r.denied and r.stage == "guardie_immediate"
    assert banco.eseguiti == []


def test_una_guardia_che_esplode_nega(banco):
    """Deny-by-default vale anche per i difetti del codice di sicurezza."""
    def rotta(call):
        raise RuntimeError("psutil non risponde")

    reg = Registry("rotta")

    @reg.strumento(Tier.T2, Scrivi, guards=(Guard("rotta", rotta),))
    def _scrivi(call):
        return {}

    b = Broker(registry=reg, audit=banco.audit, kill=banco.kill)
    r = b.execute({"tool": "scrivi", "text": "x"})
    assert r.denied and "rotta" in r.detail


# --- proprieta' del broker ---------------------------------------------------

def test_il_broker_non_solleva_mai(banco):
    """Un broker che solleva diventa un broker avvolto in un try/except
    generico, ed e' li' che la sicurezza si perde."""
    veleni = [
        None, 42, 3.14, b"bytes", [], {}, "", "null", "true",
        '{"tool": null}', '{"tool": 123}', '{"tool": {"nested": 1}}',
        '{"tool": "leggi", "extra": ' + '[' * 200 + ']' * 200 + "}",
        "\x00\x01\x02", "{'tool': 'leggi'}",      # apici singoli: non e' JSON
        '{"tool": "' + "x" * 10_000 + '"}',
    ]
    for v in veleni:
        r = banco.broker.execute(v)
        assert isinstance(r, Result), f"non ha ritornato un Result per {v!r:.40}"
        assert not r.ok, f"ha ESEGUITO qualcosa con {v!r:.40}"


def test_un_handler_che_esplode_diventa_un_errore_non_un_crash(banco):
    reg = Registry("esplosiva")

    @reg.strumento(Tier.T0, Leggi)
    def _leggi(call):
        raise ZeroDivisionError("boom")

    b = Broker(registry=reg, audit=banco.audit, kill=banco.kill)
    r = b.execute('{"tool": "leggi"}')
    assert not r.ok and r.outcome is Outcome.ERROR and "ZeroDivisionError" in r.detail


def test_il_fast_path_non_salta_la_validazione(banco):
    """Chi arriva con un modello gia' costruito viene rivalidato comunque:
    non esiste un ingresso privilegiato."""
    class FintoModello(BaseModel):
        tool: str = "apri"
        app: str = "cmd.exe"          # non passerebbe il Literal vero

    r = banco.broker.execute(FintoModello(), Context(origine="fast_path"))
    assert r.denied and r.stage == "schema"


def test_ogni_esito_lascia_una_riga_di_audit(banco):
    prima = len(banco.audit.recent(limit=500))
    banco.broker.execute('{"tool": "leggi"}')
    banco.broker.execute('{"tool": "inesistente"}')
    banco.broker.execute("{rotto")
    banco.broker.execute({"tool": "manda", "to": "a@b.it"}, Context(chiedi_conferma=no))
    assert len(banco.audit.recent(limit=500)) == prima + 4


def test_ogni_rifiuto_dice_perche(banco):
    """Un log che dice solo 'negato' non serve a niente alle undici di sera."""
    for chiamata in ('{"tool": "inesistente"}', '{"tool": "apri"}', "{rotto",
                     '{"tool": "tasti", "keys": ["shift", "delete"]}'):
        r = banco.broker.execute(chiamata)
        assert r.denied and len(r.detail) > 10, f"motivo povero: {r.detail!r}"
        assert banco.audit.recent()[0]["detail"] == r.detail


# --- NFR-9 -------------------------------------------------------------------

def test_nfr9_cinquanta_tentativi_nessuna_t3_non_confermata(banco):
    """Il criterio di uscita di M2, con dentro anche i tentativi avversariali.

    Non basta che i casi felici funzionino: la domanda e' se ESISTE un modo
    di far eseguire una T3 senza un si' esplicito. Ogni scenario dichiara
    cosa si aspetta, cosi' il test fallisce sia se una T3 passa quando non
    deve, sia se smette di passare quando dovrebbe — un broker che nega
    tutto supererebbe NFR-9 ed sarebbe inutile.
    """
    import time

    def lento(spec, call):
        time.sleep(5)
        return True

    def esplode(spec, call):
        raise RuntimeError("dialogo non disponibile")

    # (descrizione, contesto, kill switch attivo, deve eseguire)
    scenari = [
        ("nessuno puo' confermare", Context(), False, False),
        ("conferma negata", Context(chiedi_conferma=no), False, False),
        ("conferma scaduta", Context(chiedi_conferma=lento), False, False),
        ("conferma esplosa", Context(chiedi_conferma=esplode), False, False),
        ("si' ma dopo il web", Context(chiedi_conferma=si, has_untrusted_content=True),
         False, False),
        ("ritorna None", Context(chiedi_conferma=lambda s, c: None), False, False),
        ("si' ma kill switch", Context(chiedi_conferma=si), True, False),
        ("si' per davvero", Context(chiedi_conferma=si), False, True),
        # "si'" e' veritiera in Python, quindi e' una conferma valida quanto
        # True: se un domani il dialogo restituisse stringhe, resta corretto.
        ("verita' ambigua", Context(chiedi_conferma=lambda s, c: "si'"), False, True),
    ]

    attese = eseguite = 0
    for i in range(50):
        nome, ctx, kill, deve = scenari[i % len(scenari)]
        if kill:
            banco.kill.sospendi()
        r = banco.broker.execute({"tool": "manda", "to": f"u{i}@b.it"}, ctx)
        banco.kill.ripristina()
        assert r.ok == deve, f"tentativo {i} ({nome}): ok={r.ok}, atteso {deve} — {r.detail}"
        attese += deve
        eseguite += r.ok

    assert banco.audit.unconfirmed_t3() == 0, "una T3 e' passata senza conferma"
    assert eseguite == attese > 0, "il test non sta provando nulla"

    # E il registro deve raccontarlo: 50 tentativi, tutti tracciati.
    righe = [r for r in banco.audit.recent(limit=200) if r["tool"] == "manda"]
    assert len(righe) == 50
    assert sum(r["outcome"] == "ok" for r in righe) == eseguite


# --- rami di errore del broker stesso ---------------------------------------

def test_il_result_si_legge(banco):
    r = banco.broker.execute('{"tool": "leggi"}')
    assert "leggi" in str(r) and "ok" in str(r)
    r2 = banco.broker.execute('{"tool": "ignoto"}')
    assert "DENIED" in str(r2)


def test_un_difetto_dentro_il_broker_non_esegue_e_non_solleva(banco):
    """L'ultima rete. Se il registro stesso esplode, la risposta e' un
    rifiuto registrato, non un crash di Metis."""
    class RegistroRotto:
        def get(self, nome):
            raise RuntimeError("indice corrotto")

    b = Broker(registry=RegistroRotto(), audit=banco.audit, kill=banco.kill)
    r = b.execute('{"tool": "leggi"}')
    assert not r.ok and r.stage == "broker" and "RuntimeError" in r.detail
    assert banco.audit.recent()[0]["stage"] == "broker"


def test_se_l_audit_non_scrive_lo_dice_ma_risponde(banco):
    """Non poter registrare e' grave e deve vedersi, ma non deve impedire a
    Metis di rispondere: un log rotto non e' un buon motivo per tacere."""
    class AuditRotto:
        def record(self, entry):
            raise OSError("disco pieno")

    b = Broker(registry=banco.broker.registry, audit=AuditRotto(), kill=banco.kill)
    r = b.execute('{"tool": "leggi"}')
    assert r.ok and "AUDIT NON SCRITTO" in r.detail


def test_livello_sconosciuto_viene_rifiutato(banco):
    """Deny-by-default: un enum allargato senza aggiornare le policy non
    deve tradursi in esecuzione."""
    from metis.security.policies import valuta_tier

    assert valuta_tier("T9", Context()) is not None


def test_la_durata_viene_misurata(banco):
    r = banco.broker.execute('{"tool": "leggi"}')
    assert r.duration_ms > 0
    assert banco.audit.recent()[0]["duration_ms"] > 0


def test_molti_errori_di_schema_vengono_riassunti(banco):
    """Il motivo finisce nel prompt di riparazione: deve restare leggibile
    anche quando il modello sbaglia tutto insieme."""
    r = banco.broker.execute({"tool": "manda", "to": "non-una-email",
                              "a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
    assert r.denied and r.stage == "schema"
    assert "e altri" in r.detail and len(r.detail) < 400


# --- M4: uno strumento puo' rifiutare ---------------------------------------

class Prova(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["prova"]


def _con(tier, handler, tmp_path):
    reg = Registry("rifiuti")
    reg.strumento(tier, Prova)(handler)
    return Broker(registry=reg, audit=AuditLog(tmp_path / "r.db"),
                  kill=KillSwitch())


def test_un_rifiuto_dello_strumento_e_denied_non_error(tmp_path):
    """La distinzione fra "rotto" e "non l'ho fatto apposta".

    "Non trovo nessun link che si chiami Contatti" non e' un guasto: e' il
    comportamento corretto, ed e' preferibile a un clic a caso. Se finisse
    nell'audit log accanto agli errori veri, entrambe le categorie
    diventerebbero rumore e chi guarda il log imparerebbe a saltarle.
    """
    from metis.tools.registry import Rifiuto

    def handler(call):
        raise Rifiuto("non trovo nessun elemento che si chiami 'Contatti'")

    r = _con(Tier.T1, handler, tmp_path).execute({"tool": "prova"}, Context())
    assert r.denied and r.outcome is Outcome.DENIED
    assert r.stage == "strumento" and "Contatti" in r.detail


def test_un_errore_vero_resta_un_errore(tmp_path):
    """Il verso opposto: se lo strumento esplode davvero non deve
    travestirsi da rifiuto educato."""
    def handler(call):
        raise RuntimeError("playwright non risponde")

    r = _con(Tier.T1, handler, tmp_path).execute({"tool": "prova"}, Context())
    assert r.outcome is Outcome.ERROR and r.stage == "esecuzione"
    assert "RuntimeError" in r.detail


def test_un_rifiuto_non_e_una_via_per_saltare_i_controlli(tmp_path):
    """`Rifiuto` si solleva dall'handler, cioe' dopo che tutti gli stadi
    hanno detto si'. Su un T3 senza conferma l'handler non viene chiamato
    affatto, e il rifiuto resta quello della conferma."""
    from metis.tools.registry import Rifiuto

    chiamato = []

    def handler(call):
        chiamato.append(1)
        raise Rifiuto("mai arrivato")

    r = _con(Tier.T3, handler, tmp_path).execute({"tool": "prova"}, Context())
    assert r.denied and r.stage == "conferma" and chiamato == []


def test_il_rifiuto_finisce_nell_audit_log_con_il_motivo(tmp_path):
    from metis.tools.registry import Rifiuto

    b = _con(Tier.T1, lambda c: (_ for _ in ()).throw(
        Rifiuto("due finestre si chiamano cosi'")), tmp_path)
    r = b.execute({"tool": "prova"}, Context())
    righe = b.audit.recent(1)
    assert righe and righe[0]["outcome"] == "denied"
    assert "due finestre" in righe[0]["detail"]
    assert r.audit_id is not None
