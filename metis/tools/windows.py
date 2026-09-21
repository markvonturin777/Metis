"""T0 — finestre aperte e finestra attiva. Sola lettura.

`get_active_window` non serve solo al modello: e' la stessa informazione che
la guardia dell'input sintetico usa per decidere. Tenerla in un posto solo
evita che fra qualche mese esistano due modi di dire "cosa c'e' davanti" che
in un caso limite rispondono diversamente.
"""

from __future__ import annotations

from metis.llm.schemas import GetActiveWindow, ListWindows
from metis.security.audit import Tier
from metis.security.guards import finestra_in_primo_piano
from metis.tools.registry import REGISTRY

MAX_FINESTRE = 40          # niente elenchi sterminati nel contesto del modello


@REGISTRY.strumento(Tier.T0, GetActiveWindow)
def _get_active_window(call: GetActiveWindow) -> dict:
    """Titolo, processo e classe della finestra in primo piano."""
    f = finestra_in_primo_piano()
    return {"titolo": f.titolo, "processo": f.processo, "classe": f.classe}


@REGISTRY.strumento(Tier.T0, ListWindows)
def _list_windows(call: ListWindows) -> dict:
    """Finestre visibili con un titolo."""
    import win32gui

    trovate: list[dict] = []

    def visita(hwnd: int, _) -> None:
        if len(trovate) >= MAX_FINESTRE:
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        titolo = win32gui.GetWindowText(hwnd)
        if not titolo.strip():
            return
        trovate.append({"id": hwnd, "titolo": titolo[:120]})

    win32gui.EnumWindows(visita, None)
    return {"finestre": trovate, "totale": len(trovate),
            "troncato": len(trovate) >= MAX_FINESTRE}
