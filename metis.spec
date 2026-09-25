# -*- mode: python ; coding: utf-8 -*-
"""Il bundle di Metis. PyInstaller, modalita' ONEDIR.

    .venv\\Scripts\\python.exe -m PyInstaller metis.spec --noconfirm

Risultato: dist\\Metis\\Metis.exe con le sue librerie accanto.

ONEDIR, NON ONEFILE
Onefile estrae tutto in una cartella temporanea a ogni avvio: con torch,
PySide6 e CTranslate2 sono centinaia di MB da scompattare, 10-30 s prima che
Metis esista. Onedir parte subito.

I MODELLI RESTANO FUORI
Voci Piper in data\\piper, Whisper nella cache di Hugging Face, il modello
linguistico in Ollama. Aggiornarli non deve voler dire ricompilare, e il
bundle non deve pesare 3 GB in piu'. Metis li trova perche' parte dalla
radice del progetto: vedi `metis/core/radice.py`.

GLI IMPORT CHE PYINSTALLER NON VEDE
Tre famiglie, tutte trovate provando il bundle e non leggendo:

    per nome        pynput sceglie il backend a runtime (_win32);
                    sqlalchemy il dialetto dal prefisso "sqlite:///"
    entry point     APScheduler cerca trigger, jobstore ed executor fra i
                    metadati installati; keyring fa lo stesso con i backend.
                    Senza i metadati copiati il bundle parte e poi, al primo
                    promemoria, "trigger 'date' not found".
    file di dati    Silero (il VAD), gli asset di faster-whisper, i dati di
                    espeak-ng dentro piper, le impostazioni di trafilatura e
                    le stoplist di justext.
"""

import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# --- DLL che PyInstaller non vede -------------------------------------------------
# Trovate con la prova su cartella pulita, non leggendo:
#
#   CUDA        cuBLAS e cuDNN 9 arrivano dai pacchetti pip `nvidia-*` e si
#               caricano a runtime alla prima trascrizione. Sul sistema c'e' solo
#               cuDNN 8, quindi vanno nel bundle: ~2 GB, il grosso del peso.
#               `metis/core/cuda_libs.py` le cerca in `_internal/nvidia/*/bin`.
#   uiautomation carica la sua DLL con ctypes da `uiautomation/bin`: senza,
#               l'automazione delle finestre di M4 non parte.
binaries = []
for radice in importlib.util.find_spec("nvidia").submodule_search_locations:
    for cartella in sorted(Path(radice).glob("*/bin")):
        for dll in cartella.glob("*.dll"):
            if dll.name != "nvblas64_12.dll":          # BLAS su CPU: non serve
                binaries.append((str(dll), f"nvidia/{cartella.parent.name}/bin"))
_uia = Path(importlib.util.find_spec("uiautomation").origin).parent / "bin"
binaries += [(str(d), "uiautomation/bin") for d in _uia.glob("*.dll")]

datas = []
for pacchetto in ("silero_vad", "faster_whisper", "piper", "trafilatura", "justext",
                  "openwakeword", "courlan", "htmldate", "dateparser", "tld"):
    datas += collect_data_files(pacchetto)
for pacchetto in ("apscheduler", "keyring", "sqlalchemy", "ddgs", "trafilatura",
                  "faster_whisper", "ctranslate2", "onnxruntime"):
    datas += copy_metadata(pacchetto)

hiddenimports = [
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "sqlalchemy.dialects.sqlite",
    "keyring.backends.Windows",
    "comtypes.stream",
    "win11toast",
]
hiddenimports += collect_submodules("apscheduler")
hiddenimports += collect_submodules("metis")

a = Analysis(
    ["metis/gui/app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Strumenti di sviluppo e addestramento che il venv contiene ma Metis
    # non usa: tenerli fuori risparmia centinaia di MB.
    excludes=["pytest", "ruff", "aiosmtpd", "trustme", "IPython", "jupyter",
              "matplotlib", "tensorboard", "torchmetrics", "PyInstaller",
              # Trascinato da un hook, non importato da nessuno: 103 MB.
              "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Metis",
    debug=False,
    strip=False,
    upx=False,                 # UPX su DLL CUDA e Qt: avvio piu' lento, antivirus nervosi
    console=False,             # nessuna finestra nera: vedi garantisci_flussi
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Metis",
)
