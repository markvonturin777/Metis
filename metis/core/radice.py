"""La cartella di lavoro di Metis: dove stanno `config/` e `data/`.

Tutto il progetto usa percorsi relativi — `config/email.toml`,
`data/audit.db`, `data/piper` — e fino a M6 bastava, perche' Metis si
lanciava sempre dalla radice del repository. Con il bundle di PyInstaller
non e' piu' vero: un doppio clic su `dist\\Metis\\Metis.exe` parte con la
cartella di lavoro in `dist\\Metis`, dove `config/` non c'e'.

Si sceglie la prima di queste che contiene `config/`:

    METIS_HOME                  se impostata: vince su tutto
    la cartella dell'eseguibile un'installazione con config/ accanto all'exe
    due livelli sopra           dist\\Metis\\Metis.exe dentro il repository

Da sorgente (non congelato) non si tocca niente: la cartella di lavoro e'
quella da cui si e' lanciato, come sempre.

Questo modulo non importa nulla oltre la libreria standard: si chiama in
testa a `metis.gui.app`, prima di qualunque cosa scriva su disco.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def candidati() -> list[Path]:
    fuori: list[Path] = []
    if os.environ.get("METIS_HOME"):
        fuori.append(Path(os.environ["METIS_HOME"]))
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        fuori += [exe, exe.parent.parent]
    return fuori


def fissa_radice() -> Path | None:
    """Sposta la cartella di lavoro sulla radice trovata. None se nessuna."""
    for c in candidati():
        if (c / "config").is_dir():
            os.chdir(c)
            return c
    return None
