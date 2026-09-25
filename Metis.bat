@echo off
rem Avvia Metis con l'interfaccia grafica. Doppio clic, oppure da terminale:
rem
rem   Metis.bat                  overlay minimal, nessuna console
rem   Metis.bat --fullscreen     parte dalla control room
rem   Metis.bat --console        tiene aperta questa finestra con i log:
rem                              serve quando qualcosa non parte
rem
rem Le altre opzioni passano a metis.gui.app (--no-tools, --whisper small, ...).
rem Senza --console il log sta in data\logs\metis.jsonl e gli errori
rem imprevisti in data\logs\metis.stderr.log.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Non trovo l'ambiente .venv in %CD%.
    echo Per installarlo: docs\INSTALL.md, paragrafo 2.
    pause
    exit /b 1
)

set "CONSOLE="
set "ARGS="
:argomenti
if "%~1"=="" goto avvia
if /i "%~1"=="--console" (set "CONSOLE=1") else (set "ARGS=%ARGS% %1")
shift
goto argomenti

:avvia
if defined CONSOLE (
    ".venv\Scripts\python.exe" -m metis.gui.app %ARGS%
    pause
) else (
    start "" ".venv\Scripts\pythonw.exe" -m metis.gui.app %ARGS%
)
