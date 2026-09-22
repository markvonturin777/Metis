"""T1 — apre applicazioni e pagine web. Reversibile: si chiudono.

TRE COSE CHE NON SI FANNO, E PERCHE'

`shell=True` — mai. Con la shell di mezzo, una stringa qualunque
nell'argomento diventa un comando. Qui non arriva nulla di libero, perche' lo
schema accetta solo un `Literal`, ma il giorno in cui qualcuno aggiunge un
parametro la differenza fra lista e shell e' la differenza fra un argomento
strano e una macchina compromessa.

Comando come STRINGA — mai. `Popen("x y")` lo fa interpretare; `Popen(["x",
"y"])` lo passa come due argomenti e basta.

Fallback su PATH — mai. `ALLOWLIST_APP[chiave]` solleva se la chiave non c'e', e
solleva bene: un fallback su un eseguibile trovato nel PATH significherebbe
lanciare qualcosa che nessuno ha messo in questa tabella.

PERCHE' `open_url` NON USA `os.startfile`
Sarebbe una riga sola e aprirebbe il browser predefinito. Farebbe pero' due
cose che qui non vanno bene. La prima: `startfile` non apre URL, apre
*qualunque cosa* secondo le associazioni di Windows, e l'unica ragione per
cui oggi non aprirebbe un file e' il `pattern` dello schema — una barriera
sola, nel posto piu' lontano dall'azione. La seconda: il browser
predefinito, aperto cosi', non ha la porta di debug, e Playwright piu' tardi
non potrebbe collegarsi alla sessione vera. Passando dall'allowlist si
ottengono entrambe le cose: l'eseguibile e' quello scritto nel TOML, e gli
argomenti sono quelli che servono a M4.
"""

from __future__ import annotations

import subprocess

from metis.llm.schemas import OpenApplication, OpenUrl
from metis.security.audit import Tier
from metis.security.guards import ALLOWLIST_APP, VoceApp, guardia_app
from metis.tools.registry import REGISTRY, Rifiuto

BROWSER = "chrome"


def _avvia(voce: VoceApp, extra: tuple[str, ...] = ()) -> int:
    proc = subprocess.Popen(
        [str(voce.percorso), *voce.args, *extra],   # lista, mai stringa
        shell=False,                                # esplicito perche' si veda
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    return proc.pid


@REGISTRY.strumento(Tier.T1, OpenApplication, guards=(guardia_app(),))
def _open_application(call: OpenApplication) -> dict:
    """Avvia un'applicazione dell'allowlist."""
    voce = ALLOWLIST_APP[call.app]            # KeyError -> errore, mai fallback
    return {"app": call.app, "pid": _avvia(voce),
            "percorso": str(voce.percorso)}


@REGISTRY.strumento(Tier.T1, OpenUrl)
def _open_url(call: OpenUrl) -> dict:
    """Apre un indirizzo web in Chrome."""
    voce = ALLOWLIST_APP.get(BROWSER)
    if voce is None or not voce.percorso.exists():
        raise Rifiuto("non ho un browser nell'allowlist: "
                      "aggiungi la voce chrome in config/apps.toml")
    # L'URL e' gia' passato dal `pattern` dello schema, quindi comincia per
    # http:// o https:// e non contiene spazi: non puo' essere letto da
    # Chrome come un flag, e non puo' nominare un file locale.
    return {"url": call.url, "pid": _avvia(voce, (call.url,))}
