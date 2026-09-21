"""T1 — apre un'applicazione dell'allowlist. Reversibile: si chiude.

TRE COSE CHE NON SI FANNO, E PERCHE'

`shell=True` — mai. Con la shell di mezzo, una stringa qualunque
nell'argomento diventa un comando. Qui non arriva nulla di libero, perche' lo
schema accetta solo un `Literal`, ma il giorno in cui qualcuno aggiunge un
parametro la differenza fra lista e shell e' la differenza fra un argomento
strano e una macchina compromessa.

Comando come STRINGA — mai. `Popen("x y")` lo fa interpretare; `Popen(["x",
"y"])` lo passa come due argomenti e basta.

Fallback su PATH — mai. `ALLOWLIST[chiave]` solleva se la chiave non c'e', e
solleva bene: un fallback su un eseguibile trovato nel PATH significherebbe
lanciare qualcosa che nessuno ha messo in questa tabella.
"""

from __future__ import annotations

import subprocess

from metis.llm.schemas import MoveWindowToMonitor, OpenApplication
from metis.security.audit import Tier
from metis.security.guards import ALLOWLIST_APP, guardia_app
from metis.tools.registry import REGISTRY


@REGISTRY.strumento(Tier.T1, OpenApplication, guards=(guardia_app(),))
def _open_application(call: OpenApplication) -> dict:
    """Avvia un'applicazione dell'allowlist."""
    percorso = ALLOWLIST_APP[call.app]        # KeyError -> errore, mai fallback
    proc = subprocess.Popen(
        [str(percorso)],                      # lista, mai stringa
        shell=False,                          # esplicito perche' si veda
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    return {"app": call.app, "pid": proc.pid, "percorso": str(percorso)}


@REGISTRY.strumento(Tier.T1, MoveWindowToMonitor, implemented=False)
def _move_window_to_monitor(call: MoveWindowToMonitor) -> dict:
    """Sposta una finestra su un altro monitor. Capacita' in M4."""
    raise NotImplementedError
