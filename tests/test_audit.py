"""L'audit log e' append-only: e' un requisito di sicurezza, non una
convenzione. Da M2 e' anche il modo in cui NFR-9 viene verificato."""
import re
from pathlib import Path
import pytest
from metis.security.audit import AuditLog, Entry, Outcome, Tier, timed


@pytest.fixture
def log(tmp_path):
    a = AuditLog(tmp_path / "audit.db")
    yield a
    a.close()


def test_registra_e_rilegge(log):
    log.record(Entry("open_application", Tier.T1, {"app": "vscode"}, Outcome.OK))
    r = log.recent()[0]
    assert r["tool"] == "open_application" and r["tier"] == "T1" and r["outcome"] == "ok"


def test_tier_non_valido_rifiutato(log):
    """Lo schema ha un CHECK: un tier inventato non entra."""
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        log._conn.execute(
            "INSERT INTO audit (ts,tool,tier,args_json,outcome) VALUES (?,?,?,?,?)",
            ("2026-01-01", "x", "T9", "{}", "ok"))


def test_esito_non_valido_rifiutato(log):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        log._conn.execute(
            "INSERT INTO audit (ts,tool,tier,args_json,outcome) VALUES (?,?,?,?,?)",
            ("2026-01-01", "x", "T1", "{}", "forse"))


# --- NFR-9: e' la query che chiude M2 e M7 ----------------------------------

def test_nfr9_zero_se_le_t3_sono_confermate(log):
    log.record(Entry("send_email", Tier.T3, {}, Outcome.OK, confirmed=True))
    log.record(Entry("send_email", Tier.T3, {}, Outcome.DENIED, confirmed=False))
    assert log.unconfirmed_t3() == 0


def test_nfr9_rileva_una_t3_non_confermata(log):
    """Il difetto bloccante che la query deve trovare."""
    log.record(Entry("send_email", Tier.T3, {}, Outcome.OK, confirmed=None))
    assert log.unconfirmed_t3() == 1


def test_nfr9_rileva_conferma_negata_ma_eseguita(log):
    log.record(Entry("set_home_device", Tier.T3, {}, Outcome.OK, confirmed=False))
    assert log.unconfirmed_t3() == 1


# --- contesto temporizzato ---------------------------------------------------

def test_timed_registra_la_durata(log):
    with timed(log, "web_search", Tier.T0, {"q": "meteo"}):
        pass
    r = log.recent()[0]
    assert r["outcome"] == "ok" and r["duration_ms"] is not None


def test_timed_registra_l_errore_e_rilancia(log):
    """Uno strumento che fallisce deve comunque lasciare traccia."""
    with pytest.raises(ValueError):
        with timed(log, "move_window", Tier.T1, {"monitor": 9}):
            raise ValueError("monitor inesistente")
    r = log.recent()[0]
    assert r["outcome"] == "error" and "monitor inesistente" in r["detail"]


# --- append-only: verifica per ispezione del sorgente ------------------------

def _sql_eseguite(path: str) -> list[str]:
    """Le stringhe SQL effettivamente passate a execute/executescript.

    Guardare il TESTO del file non va bene: la prima versione di questo test
    cercava le parole nel sorgente e inciampava sulla docstring che spiega la
    regola. Quello che conta e' cosa viene eseguito.
    """
    import ast

    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    costanti = {
        t.id: n.value.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
        for t in n.targets
        if isinstance(t, ast.Name) and isinstance(n.value.value, str)
    }
    out: list[str] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr not in ("execute", "executescript", "executemany"):
            continue
        for a in n.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                out.append(a.value)
            elif isinstance(a, ast.Name) and a.id in costanti:
                out.append(costanti[a.id])
    return out


def test_nessuna_sql_di_modifica_viene_eseguita():
    """Un registro che il codice puo' modificare non e' un registro."""
    sql = _sql_eseguite("metis/security/audit.py")
    assert sql, "nessuna SQL trovata: il test non starebbe verificando nulla"
    for q in sql:
        for verbo in ("UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER"):
            assert not re.search(rf"\b{verbo}\b", q, re.IGNORECASE), (
                f"SQL di modifica: {verbo} in {q[:60]!r}"
            )


def test_il_controllo_rileva_davvero_una_violazione(tmp_path):
    """Meta-test. Una verifica che non sa riconoscere il difetto che cerca
    passa sempre, e da' una falsa sicurezza."""
    finto = tmp_path / "finto.py"
    finto.write_text("conn.execute('UPDATE audit SET outcome=1')", encoding="utf-8")
    sql = _sql_eseguite(str(finto))
    assert any(re.search(r"\bUPDATE\b", q, re.IGNORECASE) for q in sql)


def test_statistiche(log):
    log.record(Entry("a", Tier.T0, {}, Outcome.OK))
    log.record(Entry("b", Tier.T2, {}, Outcome.DENIED, stage="guardie"))
    s = log.stats()
    assert s["totale"] == 2 and s["per_tier"]["T0"] == 1 and s["per_esito"]["denied"] == 1
