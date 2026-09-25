"""M7 — avvio automatico: lo script e le condizioni in cui Metis parte da solo.

Lo script non si installa nei test: registrerebbe un'attivita' vera nella
macchina di chi li lancia. Si prova in `-Anteprima`, che costruisce gli
stessi oggetti dell'Utilita' di pianificazione e li descrive invece di
registrarli — cioe' si verifica cio' che Windows riceverebbe, non il testo
dello script.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/install_autostart.ps1")

solo_windows = pytest.mark.skipif(sys.platform != "win32", reason="Utilita' di pianificazione")


def _anteprima(*argomenti: str) -> dict[str, str]:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(SCRIPT), "-Anteprima", *argomenti],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return dict(riga.split("=", 1) for riga in r.stdout.splitlines() if "=" in riga)


@solo_windows
def test_l_attivita_e_quella_del_piano():
    a = _anteprima()
    assert a["Ritardo"] == "PT60S"              # dopo Ollama e la rete
    assert a["RestartCount"] == "3"
    assert a["RestartInterval"] == "PT1M"
    assert a["MultipleInstances"] == "IgnoreNew"  # mai due Metis sullo stesso microfono


@solo_windows
def test_mai_amministratore():
    assert _anteprima()["RunLevel"] == "Limited"


@solo_windows
def test_nessun_limite_di_durata():
    """Il default dell'Utilita' di pianificazione e' 72 ore: esattamente la
    durata del soak test. Senza questa riga Metis verrebbe ucciso al terzo
    giorno, e sembrerebbe un crash."""
    assert _anteprima()["ExecutionTimeLimit"] == "PT0S"


@solo_windows
def test_parte_dalla_radice_del_progetto_senza_console():
    """config\\ e data\\ sono relativi: dalla cartella di default
    (System32) Metis non troverebbe niente."""
    a = _anteprima()
    assert Path(a["Cartella"]).resolve() == Path.cwd().resolve()
    if a["Argomenti"]:                          # dal venv, non dal bundle
        assert a["Esegui"].lower().endswith("pythonw.exe")
        assert a["Argomenti"] == "-m metis.gui.app"


@solo_windows
def test_un_eseguibile_inesistente_e_un_errore_non_un_attivita_rotta(tmp_path):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(SCRIPT), "-Anteprima", "-Eseguibile", str(tmp_path / "manca.exe")],
        capture_output=True, text=True, timeout=60)
    assert r.returncode != 0


def test_il_testo_non_chiede_mai_privilegi_elevati():
    testo = SCRIPT.read_text(encoding="utf-8")
    assert "Highest" not in testo
    assert "-RunLevel Limited" in testo


# --- senza console ------------------------------------------------------------

def test_senza_console_i_flussi_vengono_rimpiazzati(monkeypatch, tmp_path):
    """`pythonw.exe` — l'avvio automatico — parte con stdout e stderr None.
    Prima di questa correzione la prima riga di log sollevava TypeError
    dentro structlog, e Metis moriva a ogni accesso senza lasciare traccia."""
    from metis.core.logging import garantisci_flussi

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    file_err = tmp_path / "logs" / "metis.stderr.log"
    assert garantisci_flussi(file_err) is True
    try:
        print("va nel nulla")
        sys.stderr.write("Traceback: questo deve restare\n")
        sys.stderr.flush()
    finally:
        sys.stdout.close()
        sys.stderr.close()
    assert "questo deve restare" in file_err.read_text(encoding="utf-8")


def test_structlog_riceve_un_file_vero(monkeypatch, tmp_path):
    """Il sintomo originale: `PrintLoggerFactory(file=sys.stdout)` con stdout
    None. structlog ripiega allora sullo stdout catturato al SUO import, che
    sotto pythonw e' None anche lui — qui non si puo' riprodurre, perche'
    structlog e' gia' importato con una console. Si verifica il contratto:
    dopo `garantisci_flussi` il file passato e' un file vero, e ci si scrive.
    """
    import structlog

    from metis.core.logging import garantisci_flussi

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    garantisci_flussi(tmp_path / "e.log")
    try:
        assert sys.stdout is not None
        structlog.PrintLoggerFactory(file=sys.stdout)().msg("ok")
    finally:
        sys.stdout.close()
        sys.stderr.close()


def test_anche_le_librerie_native_trovano_dove_scrivere(tmp_path):
    """Il secondo difetto, trovato lanciando la GUI vera sotto pythonw: con
    la sola correzione Python il processo moriva comunque (0xC0000409),
    perche' CTranslate2 & co. scrivono sui descrittori 1 e 2, non su
    `sys.stderr`. Qui si chiudono davvero i descrittori, in un interprete a
    parte, e si scrive con `os.write` — come fa una libreria C.

    I descrittori chiusi si riempiono subito con un file civetta: altrimenti
    il sistema riassegnerebbe 1 e 2 ai primi file aperti da
    `garantisci_flussi`, e il test passerebbe per coincidenza (e' successo:
    la prima versione non si accorgeva di un `dup2` tolto)."""
    file_err = tmp_path / "metis.stderr.log"
    civetta = tmp_path / "civetta.txt"
    codice = f"""
import os, sys
sys.stdout = sys.stderr = None
os.close(1); os.close(2)
c1 = os.open(r"{civetta}", os.O_WRONLY | os.O_CREAT)
c2 = os.open(r"{civetta}", os.O_WRONLY | os.O_CREAT)
assert (c1, c2) == (1, 2), (c1, c2)
from metis.core.logging import garantisci_flussi
from pathlib import Path
garantisci_flussi(Path(r"{file_err}"))
os.write(2, b"scritto dal nativo")
os.write(1, b"nel nulla")
"""
    r = subprocess.run([sys.executable, "-c", codice], timeout=60,
                       capture_output=True)
    assert r.returncode == 0, r.stderr
    assert "scritto dal nativo" in file_err.read_text(encoding="utf-8")


def test_con_la_console_non_si_tocca_niente(tmp_path):
    from metis.core.logging import garantisci_flussi

    prima = (sys.stdout, sys.stderr)
    assert garantisci_flussi(tmp_path / "e.log") is False
    assert (sys.stdout, sys.stderr) == prima


def test_la_gui_fissa_radice_e_flussi_prima_di_ogni_altro_import():
    """In `metis.gui.app` le due chiamate stanno prima di Qt e di tutto il
    resto: un import che scrivesse su stderr, o su data/, prima di loro
    cadrebbe o scriverebbe nel posto sbagliato."""
    import ast

    albero = ast.parse(Path("metis/gui/app.py").read_text(encoding="utf-8"))
    preliminari = {"metis.core.radice", "metis.core.logging"}
    altri_import = [n.lineno for n in albero.body
                    if isinstance(n, ast.ImportFrom) and n.module
                    and n.module.startswith(("metis", "PySide6"))
                    and n.module not in preliminari]

    def riga(nome):
        return next(n.lineno for n in albero.body
                    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and getattr(n.value.func, "id", "") == nome)

    assert riga("fissa_radice") < riga("garantisci_flussi") < min(altri_import)


# --- cartella di lavoro del bundle -----------------------------------------------

@pytest.fixture
def cwd_ripristinata():
    import os

    prima = os.getcwd()
    yield
    os.chdir(prima)


def test_da_sorgente_la_cartella_di_lavoro_non_cambia(monkeypatch, cwd_ripristinata):
    import os

    from metis.core.radice import fissa_radice

    monkeypatch.delenv("METIS_HOME", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    prima = os.getcwd()
    assert fissa_radice() is None
    assert os.getcwd() == prima


def test_il_bundle_dentro_il_repository_trova_la_radice(monkeypatch, tmp_path,
                                                         cwd_ripristinata):
    """dist/Metis/Metis.exe: config/ sta due livelli sopra."""
    import os

    from metis.core.radice import fissa_radice

    (tmp_path / "config").mkdir()
    exe = tmp_path / "dist" / "Metis" / "Metis.exe"
    exe.parent.mkdir(parents=True)
    exe.touch()
    monkeypatch.delenv("METIS_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    os.chdir(exe.parent)
    assert fissa_radice() == tmp_path
    assert Path.cwd().resolve() == tmp_path.resolve()


def test_config_accanto_all_eseguibile_vince_sui_due_livelli(monkeypatch, tmp_path,
                                                              cwd_ripristinata):
    from metis.core.radice import fissa_radice

    exe = tmp_path / "a" / "b" / "Metis.exe"
    exe.parent.mkdir(parents=True)
    (exe.parent / "config").mkdir()
    (tmp_path / "config").mkdir()
    monkeypatch.delenv("METIS_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert fissa_radice() == exe.parent.resolve()


def test_metis_home_vince_su_tutto(monkeypatch, tmp_path, cwd_ripristinata):
    from metis.core.radice import fissa_radice

    casa = tmp_path / "casa"
    (casa / "config").mkdir(parents=True)
    monkeypatch.setenv("METIS_HOME", str(casa))
    assert fissa_radice() == casa


# --- DLL CUDA nel bundle -----------------------------------------------------------

def test_nel_bundle_le_dll_cuda_si_cercano_in_meipass(monkeypatch, tmp_path):
    """Nel bundle `import nvidia` fallisce: le DLL stanno in
    `_internal/nvidia/*/bin`. Senza questo ramo: "cublas64_12.dll is not
    found" alla prova su cartella pulita."""
    from metis.core import cuda_libs

    bin_dir = tmp_path / "nvidia" / "cublas" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "cublas64_12.dll").touch()
    registrate = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(cuda_libs, "_registered", False)
    monkeypatch.setattr(cuda_libs.os, "add_dll_directory", registrate.append, raising=False)
    monkeypatch.setattr(cuda_libs.sys, "platform", "win32")
    monkeypatch.setenv("PATH", "")
    assert cuda_libs.register_cuda_dll_dirs() == [bin_dir]
    assert registrate == [str(bin_dir)]
    assert str(bin_dir) in cuda_libs.os.environ["PATH"]
