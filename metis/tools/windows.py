"""T0 e T1 sulle finestre. Leggere, spostare, disporre.

`get_active_window` non serve solo al modello: e' la stessa informazione che
la guardia dell'input sintetico usa per decidere. Tenerla in un posto solo
evita che fra qualche mese esistano due modi di dire "cosa c'e' davanti" che
in un caso limite rispondono diversamente.

PERCHE' `list_windows` NON RESTITUISCE PIU' GLI HANDLE
In M2 li restituiva. Da M4, che e' l'iterazione in cui le finestre si
spostano davvero, sono stati tolti: un handle nell'elenco e' un handle che
il modello puo' copiare nel turno dopo, e — cosa peggiore — un formato che
impara a produrre anche quando non ha un elenco da cui copiarlo. Un intero
inventato e' quasi sempre una finestra vera. Un titolo inventato non e'
niente, e produce un rifiuto. Vedi la nota in testa a `metis/llm/schemas.py`.

TUTTO E' T1, CIOE' REVERSIBILE
Spostare, massimizzare e ridurre a icona si annullano rifacendo il gesto
contrario, e nessuna di queste operazioni tocca un contenuto. Non passano
dalla conferma, passano dall'audit log.
"""

from __future__ import annotations

from metis.llm.schemas import (
    FocusWindow,
    GetActiveWindow,
    ListMonitors,
    ListWindows,
    MaximizeWindow,
    MinimizeWindow,
    MoveWindowToMonitor,
    ResizeWindow,
    RestoreWindow,
)
from metis.security.audit import Tier
from metis.security.guards import finestra_in_primo_piano
from metis.tools import finestre
from metis.tools.display import monitors
from metis.tools.registry import REGISTRY


# --- T0 ----------------------------------------------------------------------

@REGISTRY.strumento(Tier.T0, GetActiveWindow)
def _get_active_window(call: GetActiveWindow) -> dict:
    """Titolo, processo e classe della finestra in primo piano."""
    f = finestra_in_primo_piano()
    return {"titolo": f.titolo, "processo": f.processo, "classe": f.classe}


@REGISTRY.strumento(Tier.T0, ListWindows)
def _list_windows(call: ListWindows) -> dict:
    """Finestre visibili con un titolo."""
    trovate = finestre.elenca()
    return {
        "finestre": [{"titolo": i.titolo[:120], "processo": i.processo,
                      "stato": i.stato} for i in trovate],
        "totale": len(trovate),
        "troncato": len(trovate) >= finestre.MAX_FINESTRE,
    }


@REGISTRY.strumento(Tier.T0, ListMonitors)
def _list_monitors(call: ListMonitors) -> dict:
    """Monitor collegati, da sinistra a destra, con scaling e posizione."""
    ms = monitors()
    return {
        "monitor": [{"indice": m.indice, "larghezza": m.larghezza,
                     "altezza": m.altezza, "scala": round(m.scala, 2),
                     "primario": m.primario, "origine": m.rect[:2]}
                    for m in ms],
        "totale": len(ms),
    }


# --- T1 ----------------------------------------------------------------------

@REGISTRY.strumento(Tier.T1, MoveWindowToMonitor)
def _move_window_to_monitor(call: MoveWindowToMonitor) -> dict:
    """Sposta una finestra su un altro monitor, riscalandola se serve."""
    return finestre.sposta_su_monitor(finestre.risolvi(call.window), call.monitor)


@REGISTRY.strumento(Tier.T1, ResizeWindow)
def _resize_window(call: ResizeWindow) -> dict:
    """Dispone una finestra sul suo monitor: meta' schermo, centrata, piena."""
    return finestre.disponi(finestre.risolvi(call.window), call.disposizione)


@REGISTRY.strumento(Tier.T1, MaximizeWindow)
def _maximize_window(call: MaximizeWindow) -> dict:
    """Massimizza una finestra sul monitor dove si trova."""
    return finestre.mostra(finestre.risolvi(call.window), "massimizza")


@REGISTRY.strumento(Tier.T1, MinimizeWindow)
def _minimize_window(call: MinimizeWindow) -> dict:
    """Riduce a icona una finestra."""
    return finestre.mostra(finestre.risolvi(call.window), "riduci")


@REGISTRY.strumento(Tier.T1, RestoreWindow)
def _restore_window(call: RestoreWindow) -> dict:
    """Riporta una finestra alle dimensioni normali."""
    return finestre.mostra(finestre.risolvi(call.window), "ripristina")


@REGISTRY.strumento(Tier.T1, FocusWindow)
def _focus_window(call: FocusWindow) -> dict:
    """Porta una finestra in primo piano."""
    return finestre.porta_davanti(finestre.risolvi(call.window))
