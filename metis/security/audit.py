"""Audit log delle azioni — append-only.

Nasce in M1 anche se le azioni arrivano in M2: averlo pronto significa che il
Capability Broker non deve inventarselo di corsa, e che il primo strumento
scritto e' gia' tracciato.

PERCHE' APPEND-ONLY
Un registro di sicurezza che il codice applicativo puo' modificare non e' un
registro di sicurezza. Qui non esistono UPDATE ne' DELETE: l'unica operazione
e' l'inserimento. La verifica `test_nessun_update_o_delete_nel_codice` lo
controlla per ispezione del sorgente, perche' la disciplina si perde in fretta.

E' ANCHE IL MIGLIOR STRUMENTO DI DEBUG DI M2 E M4
Quando un'azione viene rifiutata, la domanda e' sempre "perche'?". Lo stadio
che ha negato, gli argomenti ricevuti e la finestra in primo piano al momento
del rifiuto sono nel registro: senza, si tira a indovinare.

NFR-9 SI VERIFICA CON UNA QUERY SU QUESTA TABELLA
    SELECT COUNT(*) FROM audit
    WHERE tier='T3' AND outcome='ok' AND confirmed IS NOT 1;
Qualunque valore diverso da zero e' un difetto bloccante.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

DB = Path("data/audit.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    turn_id    TEXT,
    tool       TEXT    NOT NULL,
    tier       TEXT    NOT NULL CHECK (tier IN ('T0','T1','T2','T3')),
    args_json  TEXT    NOT NULL,
    confirmed  INTEGER,                       -- NULL se non richiesta
    outcome    TEXT    NOT NULL CHECK (outcome IN ('ok','denied','error')),
    stage      TEXT,                          -- stadio del broker che ha deciso
    detail     TEXT,
    duration_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts   ON audit(ts);
CREATE INDEX IF NOT EXISTS idx_audit_tier ON audit(tier, outcome);
"""


class Tier(str, Enum):
    T0 = "T0"   # sola lettura
    T1 = "T1"   # reversibile
    T2 = "T2"   # input sintetico
    T3 = "T3"   # effetti esterni, conferma obbligatoria


class Outcome(str, Enum):
    OK = "ok"
    DENIED = "denied"
    ERROR = "error"


@dataclass(frozen=True)
class Entry:
    tool: str
    tier: Tier
    args: dict
    outcome: Outcome
    turn_id: str | None = None
    confirmed: bool | None = None
    stage: str | None = None
    detail: str | None = None
    duration_ms: float | None = None


class AuditLog:
    """Scritture serializzate: gli strumenti girano su thread diversi."""

    def __init__(self, path: Path = DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def record(self, e: Entry) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit (ts, turn_id, tool, tier, args_json, confirmed,"
                " outcome, stage, detail, duration_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now().isoformat(timespec="milliseconds"),
                    e.turn_id,
                    e.tool,
                    e.tier.value,
                    json.dumps(e.args, ensure_ascii=False, default=str),
                    None if e.confirmed is None else int(e.confirmed),
                    e.outcome.value,
                    e.stage,
                    e.detail,
                    e.duration_ms,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    # -- interrogazioni ----------------------------------------------------

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            cols = [d[0] for d in self._conn.execute("SELECT * FROM audit LIMIT 0").description]
        return [dict(zip(cols, r)) for r in rows]

    def unconfirmed_t3(self) -> int:
        """NFR-9: azioni T3 eseguite senza conferma. Deve essere sempre 0."""
        with self._lock:
            return int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM audit"
                    " WHERE tier='T3' AND outcome='ok' AND (confirmed IS NULL OR confirmed != 1)"
                ).fetchone()[0]
            )

    def stats(self) -> dict:
        with self._lock:
            tot = self._conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            per_tier = dict(
                self._conn.execute("SELECT tier, COUNT(*) FROM audit GROUP BY tier").fetchall()
            )
            per_out = dict(
                self._conn.execute(
                    "SELECT outcome, COUNT(*) FROM audit GROUP BY outcome"
                ).fetchall()
            )
        return {"totale": tot, "per_tier": per_tier, "per_esito": per_out,
                "t3_non_confermate": self.unconfirmed_t3()}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class timed:
    """Contesto che misura la durata e registra l'esito, anche in caso di errore.

        with timed(audit, "open_application", Tier.T1, {"app": "vscode"}) as t:
            launch("vscode")
    """

    def __init__(self, log: AuditLog, tool: str, tier: Tier, args: dict,
                 turn_id: str | None = None, confirmed: bool | None = None):
        self.log, self.tool, self.tier, self.args = log, tool, tier, args
        self.turn_id, self.confirmed = turn_id, confirmed
        self.detail: str | None = None

    def __enter__(self) -> "timed":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.log.record(Entry(
            tool=self.tool, tier=self.tier, args=self.args,
            outcome=Outcome.ERROR if exc_type else Outcome.OK,
            turn_id=self.turn_id, confirmed=self.confirmed,
            detail=f"{exc_type.__name__}: {exc}" if exc_type else self.detail,
            duration_ms=(time.perf_counter() - self._t0) * 1000,
        ))
        return False        # le eccezioni continuano a propagarsi
