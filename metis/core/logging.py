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
import os
import sys
import uuid
from pathlib import Path

import structlog

LOG_DIR = Path("data/logs")
JSONL = LOG_DIR / "metis.jsonl"
STDERR = LOG_DIR / "metis.stderr.log"
_configured = False

# I colori stanno in `metis/core/palette.py`, insieme a quelli della GUI.
# Finche' erano due tabelle, "console e interfaccia raccontano la stessa
# storia" era un'intenzione: bastava che qualcuno ne toccasse una. Ora e'
# una tabella sola, e l'ambra del terminale e' lo stesso ambra dell'overlay.
from metis.core.palette import RESET as _RESET  # noqa: E402
from metis.core.palette import ansi as _ansi  # noqa: E402


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

    color = _ansi(state)
    head = f"{ts} {color}{state:<15}{_RESET} {msg}" if state else f"{ts} {msg}"
    if turn:
        head += f" [{turn}]"
    rest = " ".join(f"{k}={v}" for k, v in d.items())
    return f"{head}  {rest}" if rest else head


def garantisci_flussi(stderr_file: Path = STDERR) -> bool:
    """M7 — senza console `sys.stdout` e `sys.stderr` sono None. Li rimpiazza.

    Succede con `pythonw.exe` — quello che usa l'avvio automatico — e con un
    bundle PyInstaller senza console. Trovato provando l'autostart: la prima
    riga di log faceva `TypeError: cannot create weak reference to
    'NoneType'` dentro structlog, e Metis moriva a ogni accesso senza una
    finestra, senza un log, senza niente.

    stdout va nel nulla: la console e' un doppione del JSONL, che resta.
    stderr va su file, perche' e' dove finiscono i traceback che nessuno ha
    previsto — proprio quelli che, senza console, sarebbero invisibili.

    Ritorna True se ha dovuto rimpiazzare qualcosa.
    """
    rimpiazzati = False
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        _anche_il_descrittore(sys.stdout, 1)
        rimpiazzati = True
    if sys.stderr is None:
        try:
            stderr_file.parent.mkdir(parents=True, exist_ok=True)
            sys.stderr = stderr_file.open("a", encoding="utf-8", buffering=1)
        except OSError:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        _anche_il_descrittore(sys.stderr, 2)
        rimpiazzati = True
    return rimpiazzati


def _anche_il_descrittore(f, fd: int) -> None:
    """Il descrittore di sistema, non solo l'oggetto Python.

    Rimpiazzare `sys.stdout` basta a Python, non alle librerie native —
    CTranslate2, onnxruntime, PortAudio — che scrivono direttamente sui
    descrittori 1 e 2. Sotto pythonw quei descrittori non esistono, e il
    runtime C tratta la scrittura come un parametro invalido: il processo
    termina con 0xC0000409, senza traceback. Misurato cosi', con la sola
    correzione Python: GUI avviata, nucleo mai pronto, processo morto.
    """
    try:
        f.flush()
        os.dup2(f.fileno(), fd)
    except (OSError, ValueError):
        pass


def configure(level: str = "INFO", jsonl: bool = True, console: bool = True) -> None:
    """Idempotente: chiamarla piu' volte non duplica i sink."""
    global _configured
    if _configured:
        return
    garantisci_flussi()

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
