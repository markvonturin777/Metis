"""Logging strutturato — M1 giorno 8.

DUE SINK, PERCHE' SERVONO DUE COSE DIVERSE
Durante lo sviluppo serve leggere a colpo d'occhio cosa sta succedendo; per
diagnosticare serve poter interrogare migliaia di eventi. Un solo formato non
fa entrambe le cose: console leggibile e JSONL su file.

PERCHE' NON `print`
L'interazione vocale e' una scatola nera: quando Metis non risponde, o
risponde quando non doveva, l'unico modo di capire cosa sia successo e'
ricostruire la sequenza di stati con i tempi. In M0 questo e' costato ore di
supposizioni; da qui ogni transizione lascia una riga.

NOTA SU structlog
`event` e' la chiave riservata del messaggio: il primo argomento posizionale
finisce li'. Si scrive quindi `log.info("wake_word", state=...)`, non
`log.info("transizione", event="wake_word")` — il secondo solleva TypeError.

Da M2 lo stesso impianto serve al Capability Broker, dove il log non e' un
aiuto al debug ma parte del meccanismo di sicurezza.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import structlog

LOG_DIR = Path("data/logs")
JSONL = LOG_DIR / "metis.jsonl"
_configured = False

# Colori per stato: lo stesso codice della GUI di M3, cosi' console e
# interfaccia raccontano la stessa storia.
_STATE_COLOR = {
    "DORMIENTE": "\033[90m", "IN_ASCOLTO": "\033[94m", "TRASCRIZIONE": "\033[96m",
    "ELABORAZIONE": "\033[93m", "GENERAZIONE": "\033[93m", "RICERCA_WEB": "\033[95m",
    "ESECUZIONE": "\033[95m", "ATTESA_CONFERMA": "\033[33m", "PARLATO": "\033[92m",
    "INTERROTTO": "\033[91m", "ERRORE": "\033[91m",
}
_RESET = "\033[0m"


class _JsonlSink:
    """Scrive ogni evento su file in JSON, poi lascia passare il dizionario.

    E' un processore, non un handler: cosi' console e file vedono esattamente
    lo stesso evento e non c'e' modo che divergano.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8", buffering=1)

    def __call__(self, logger, name, event_dict):
        self._f.write(json.dumps(event_dict, ensure_ascii=False, default=str) + "\n")
        return event_dict


def _console(logger, name, event_dict):
    """Riga compatta. Lo stato e' la prima cosa che si cerca quando si indaga."""
    d = dict(event_dict)
    ts = str(d.pop("timestamp", ""))[11:23]
    msg = d.pop("event", "")
    state = d.pop("state", "")
    turn = d.pop("turn_id", None)
    d.pop("level", None)
    d.pop("logger", None)

    color = _STATE_COLOR.get(state, "")
    head = f"{ts} {color}{state:<15}{_RESET} {msg}" if state else f"{ts} {msg}"
    if turn:
        head += f" [{turn}]"
    rest = " ".join(f"{k}={v}" for k, v in d.items())
    return f"{head}  {rest}" if rest else head


def configure(level: str = "INFO", jsonl: bool = True, console: bool = True) -> None:
    """Idempotente: chiamarla piu' volte non duplica i sink."""
    global _configured
    if _configured:
        return

    procs = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
    ]
    if jsonl:
        procs.append(_JsonlSink(JSONL))
    procs.append(_console if console else structlog.processors.JSONRenderer())

    structlog.configure(
        processors=procs,
        wrapper_class=structlog.make_filtering_bound_logger(
            {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(**ctx):
    configure()
    return structlog.get_logger().bind(**ctx)


def new_turn_id() -> str:
    return uuid.uuid4().hex[:8]


def bind_turn(turn_id: str) -> None:
    """Lega il turno al contesto: tutti gli eventi successivi lo riportano
    senza doverlo passare a mano in ogni chiamata."""
    structlog.contextvars.bind_contextvars(turn_id=turn_id)


def clear_turn() -> None:
    structlog.contextvars.clear_contextvars()


def log_transition(log, tr) -> None:
    """Osservatore da passare a StateMachine(on_transition=...)."""
    log.info("transizione", state=tr.to.name, da=tr.frm.name, evento=tr.event.name)
