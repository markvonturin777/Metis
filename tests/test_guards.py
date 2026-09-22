"""Le guardie, isolate dal broker.

Qui si verifica che ognuna risponda alla propria domanda e che risponda con
un MOTIVO: un rifiuto senza spiegazione arriva nell'audit log come "negato" e
alle undici di sera non dice niente a nessuno.
"""
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel

from metis.llm.schemas import OpenApplication
from metis.security.guards import (
    DENY_COMBINAZIONI,
    Finestra,
    carica_allowlist,
    finestra_in_primo_piano,
    guardia_app,
    guardia_combinazione,
    guardia_finestra,
)


class Tasti(BaseModel):
    tool: Literal["tasti"] = "tasti"
    keys: list[str]


class App(BaseModel):
    tool: Literal["app"] = "app"
    app: str


class Vuoto(BaseModel):
    tool: Literal["vuoto"] = "vuoto"


# --- guardia della finestra --------------------------------------------------

def con(finestra: Finestra):
    return guardia_finestra(lambda: finestra)


def test_finestra_innocua_passa():
    g = con(Finestra("progetto - Visual Studio Code", "Code.exe", "Chrome_WidgetWin_1"))
    assert g.controlla(Vuoto()) is None


@pytest.mark.parametrize("processo", [
    "explorer.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "WindowsTerminal.exe", "regedit.exe", "taskmgr.exe", "consent.exe",
])
def test_processi_vietati(processo):
    g = con(Finestra("x", processo, "X"))
    motivo = g.controlla(Vuoto())
    assert motivo is not None and processo in motivo


@pytest.mark.parametrize("classe", ["#32770", "Shell_TrayWnd", "Progman"])
def test_classi_vietate(classe):
    g = con(Finestra("Salva con nome", "Code.exe", classe))
    assert g.controlla(Vuoto()) is not None


def test_finestra_non_identificabile_viene_rifiutata():
    """Non sapere dove si scrive e' peggio che saperlo male."""
    assert con(Finestra("", "?", "?")).controlla(Vuoto()) is not None


def test_la_guardia_della_finestra_e_immediata():
    assert con(Finestra("x", "Code.exe", "Y")).immediato is True


def test_la_guardia_rilegge_ogni_volta():
    """Se memorizzasse il risultato, la rivalutazione prima dell'esecuzione
    non servirebbe a niente."""
    stato = [Finestra("x", "Code.exe", "Y")]
    g = guardia_finestra(lambda: stato[0])
    assert g.controlla(Vuoto()) is None
    stato[0] = Finestra("x", "explorer.exe", "Y")
    assert g.controlla(Vuoto()) is not None


def test_leggere_la_finestra_vera_non_solleva_mai():
    """Una guardia che esplode bloccherebbe Metis: un fallimento nel LEGGERE
    lo stato deve tradursi in rifiuto, non in crash."""
    f = finestra_in_primo_piano()
    assert isinstance(f, Finestra)
    assert isinstance(f.titolo, str) and isinstance(f.processo, str)


# --- guardia delle combinazioni ----------------------------------------------

@pytest.mark.parametrize("combo", [list(c) for c in DENY_COMBINAZIONI])
def test_tutte_le_combinazioni_della_denylist_sono_rifiutate(combo):
    """Scorre la lista vera: se qualcuno ne aggiunge una senza un test, e'
    coperta lo stesso."""
    assert guardia_combinazione().controlla(Tasti(keys=combo)) is not None


def test_l_ordine_dei_tasti_non_aggira_la_denylist():
    g = guardia_combinazione()
    assert g.controlla(Tasti(keys=["shift", "delete"])) is not None
    assert g.controlla(Tasti(keys=["delete", "shift"])) is not None


def test_le_maiuscole_non_aggirano_la_denylist():
    assert guardia_combinazione().controlla(Tasti(keys=["SHIFT", "DELETE"])) is not None


def test_un_sovrainsieme_di_una_combinazione_vietata_e_vietato():
    """Premere shift+delete insieme ad altro preme comunque shift+delete."""
    g = guardia_combinazione()
    assert g.controlla(Tasti(keys=["ctrl", "shift", "delete"])) is not None


@pytest.mark.parametrize("combo", [["ctrl", "c"], ["ctrl", "v"], ["alt", "tab"],
                                   ["ctrl", "s"], ["enter"], ["f5"]])
def test_combinazioni_innocue_passano(combo):
    """Una guardia che nega tutto e' sicura e inutile."""
    assert guardia_combinazione().controlla(Tasti(keys=combo)) is None


def test_strumento_senza_tasti_non_disturba_la_guardia():
    assert guardia_combinazione().controlla(Vuoto()) is None


# --- allowlist applicazioni --------------------------------------------------

def test_app_non_in_allowlist():
    g = guardia_app({"vscode": Path("C:/x/Code.exe")})
    motivo = g.controlla(App(app="cmd.exe"))
    assert motivo is not None and "allowlist" in motivo


def test_percorso_relativo_rifiutato(tmp_path):
    g = guardia_app({"x": Path("relativo/app.exe")})
    assert "non assoluto" in g.controlla(App(app="x"))


def test_eseguibile_assente_rifiutato():
    g = guardia_app({"x": Path("C:/non/esiste/mai/app.exe")})
    assert "assente" in g.controlla(App(app="x"))


def test_eseguibile_presente_passa(tmp_path):
    finto = tmp_path / "app.exe"
    finto.write_bytes(b"MZ")
    assert guardia_app({"x": finto}).controlla(App(app="x")) is None


def test_allowlist_reale_si_carica():
    tabella = carica_allowlist()
    assert tabella, "config/apps.toml non contiene applicazioni"
    for chiave, voce in tabella.items():
        assert voce.percorso.is_absolute(), f"{chiave}: percorso non assoluto"


def test_gli_argomenti_vivono_nella_allowlist_non_nello_schema():
    """Il flag di debug di Chrome e' una proprieta' della macchina.

    Se finisse in un campo dello schema, il modello potrebbe scegliere gli
    argomenti con cui si avvia un eseguibile — che e' una riga di comando
    libera con qualche passaggio in mezzo, cioe' il contrario di
    un'allowlist. Qui si verifica che stia dove deve stare.
    """
    voce = carica_allowlist().get("chrome")
    assert voce is not None, "chrome manca dall'allowlist: serve a M4"
    assert any("remote-debugging-port" in a for a in voce.args), (
        "senza il flag, Playwright non puo' collegarsi alla sessione reale")
    campi = set(OpenApplication.model_fields)
    assert "args" not in campi and campi == {"tool", "app"}


def test_allowlist_da_file_mancante_e_vuota():
    """Meglio nessuna app che un errore all'avvio."""
    assert carica_allowlist(Path("config/non_esiste.toml")) == {}


def test_se_le_api_di_windows_falliscono_la_finestra_e_ignota(monkeypatch):
    """Su un sistema senza pywin32, o se l'API fallisce, si deve ottenere una
    finestra 'ignota' — che la guardia poi rifiuta — e non un'eccezione."""
    import builtins

    vero_import = builtins.__import__

    def import_rotto(nome, *a, **kw):
        if nome.startswith("win32"):
            raise ImportError("pywin32 assente")
        return vero_import(nome, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", import_rotto)
    f = finestra_in_primo_piano()
    assert f.processo == "?"
    assert guardia_finestra().controlla(Vuoto()) is not None


def test_nessuna_finestra_in_primo_piano(monkeypatch):
    """Succede durante il cambio di sessione o con lo schermo bloccato."""
    import sys
    import types

    finto = types.ModuleType("win32gui")
    finto.GetForegroundWindow = lambda: 0
    monkeypatch.setitem(sys.modules, "win32gui", finto)
    assert finestra_in_primo_piano().processo == "?"


def test_processo_non_interrogabile(monkeypatch):
    """La finestra c'e' ma il processo e' gia' morto, o e' di un altro utente
    e psutil non puo' leggerlo. Si sa dov'e' la finestra, non di chi e': la
    guardia deve comunque rifiutare."""
    import sys
    import types

    gui = types.ModuleType("win32gui")
    gui.GetForegroundWindow = lambda: 123
    gui.GetWindowText = lambda h: "Qualcosa"
    gui.GetClassName = lambda h: "ClasseX"
    proc = types.ModuleType("win32process")
    proc.GetWindowThreadProcessId = lambda h: (0, 999999)
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", proc)

    f = finestra_in_primo_piano()
    assert f.titolo == "Qualcosa" and f.processo == "?"
    assert guardia_finestra(lambda: f).controlla(Vuoto()) is not None


# --- M4: la finestra di Metis stesso -----------------------------------------

def test_metis_non_scrive_dentro_se_stesso():
    """Succede quando l'utente clicca sull'overlay e poi detta: il fuoco e'
    sul pannello, e i tasti finirebbero li'. Non e' pericoloso, e'
    insensato — ma un rifiuto che spiega vale piu' di venti caratteri
    consegnati a una finestra che non li aspetta."""
    import os

    g = con(Finestra("Metis", "python.exe", "Qt5152QWindowIcon", os.getpid()))
    motivo = g.controlla(Vuoto())
    assert motivo is not None and "ci sono io" in motivo


def test_un_altro_processo_python_non_viene_scambiato_per_metis():
    """Il confronto e' sul PID e non sul nome: "python.exe" e' anche
    qualunque altro script aperto sul desktop."""
    import os

    g = con(Finestra("script altrui", "python.exe", "X", os.getpid() + 1))
    assert g.controlla(Vuoto()) is None


def test_la_finestra_letta_dal_sistema_porta_il_pid():
    f = finestra_in_primo_piano()
    assert isinstance(f.pid, int)
