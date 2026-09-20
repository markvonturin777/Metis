"""Rende trovabili le DLL CUDA installate via pip.

PERCHE' SERVE
Abbiamo scelto torch CPU-only (nessun componente del progetto usa torch per la
GPU: ci pensano Ollama e CTranslate2, che hanno runtime propri). Il rovescio
della medaglia e' che cuBLAS e cuDNN, che di solito arrivano dentro torch CUDA,
qui vengono dai pacchetti `nvidia-cublas-cu12` e `nvidia-cudnn-cu12`, che
depositano le DLL in site-packages/nvidia/*/bin.

Da Python 3.8 su Windows il PATH **non** viene piu' consultato per risolvere le
dipendenze delle estensioni native: serve `os.add_dll_directory()`. Senza questa
funzione, faster-whisper fallisce con:

    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

e lo fa alla prima inferenza, non all'import: il costruttore di WhisperModel
riesce e il problema salta fuori solo al primo turno dell'utente.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_registered = False


def register_cuda_dll_dirs() -> list[Path]:
    """Registra le cartelle bin dei pacchetti nvidia-*. Idempotente.

    Servono DUE meccanismi, non uno:

    * `os.add_dll_directory()` copre chi carica con LoadLibraryEx e il flag
      LOAD_LIBRARY_SEARCH_USER_DIRS. E' la via moderna e pulita.
    * L'aggiunta al PATH di processo copre chi usa una LoadLibrary semplice,
      che ignora le directory registrate con AddDllDirectory ma consulta il
      PATH. E' il caso di CTranslate2, che risolve cuBLAS a runtime alla
      prima inferenza: con il solo add_dll_directory fallisce comunque.
    """
    global _registered
    if _registered or sys.platform != "win32":
        return []

    try:
        import nvidia
    except ImportError:
        return []

    added: list[Path] = []
    for pkg_root in map(Path, nvidia.__path__):
        for bin_dir in sorted(pkg_root.glob("*/bin")):
            if any(bin_dir.glob("*.dll")):
                os.add_dll_directory(str(bin_dir))
                added.append(bin_dir)

    if added:
        prefix = os.pathsep.join(str(d) for d in added)
        os.environ["PATH"] = prefix + os.pathsep + os.environ.get("PATH", "")

    _registered = True
    return added
