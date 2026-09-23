"""I segreti: niente default, niente in chiaro nel repository.

Nessun test tocca il Credential Manager vero: la suite gira con un
dizionario al suo posto, e lo rimette com'era alla fine.
"""
from __future__ import annotations

import re
import subprocess

import pytest

from metis.core import secrets


@pytest.fixture
def cassaforte():
    dati: dict[str, str] = {}
    secrets.usa_backend(dati)
    yield dati
    secrets.usa_backend(None)


def test_una_chiave_mancante_solleva(cassaforte):
    """Il difetto peggiore di M6 sarebbe un default silenzioso: un'email che
    "parte" verso un server che non esiste, e un audit che dice ok."""
    with pytest.raises(secrets.SecretMissing) as e:
        secrets.get("smtp_host")
    assert e.value.chiave == "smtp_host"
    assert "setup_secrets" in str(e.value)


def test_una_chiave_vuota_e_una_chiave_mancante(cassaforte):
    cassaforte["smtp_host"] = "   "
    with pytest.raises(secrets.SecretMissing):
        secrets.get("smtp_host")


def test_non_si_scrive_un_valore_vuoto(cassaforte):
    with pytest.raises(ValueError):
        secrets.set("ha_token", "")


def test_scrittura_e_lettura(cassaforte):
    secrets.set("ha_url", "  ws://casa:8123/api/websocket ")
    assert secrets.get("ha_url") == "ws://casa:8123/api/websocket"
    assert secrets.presente("ha_url")


def test_un_backend_che_esplode_e_una_chiave_mancante(cassaforte, monkeypatch):
    """Il Credential Manager che non risponde non deve diventare un crash a
    meta' di un invio: e' una credenziale che non c'e'."""
    def esplode(chiave):
        raise OSError("Credential Manager non disponibile")

    monkeypatch.setattr(secrets._backend, "get", esplode)
    with pytest.raises(secrets.SecretMissing):
        secrets.get("smtp_password")


def test_i_segreti_non_si_mostrano_nella_diagnosi(cassaforte):
    cassaforte.update({"smtp_password": "segretissima", "smtp_host": "smtp.x.it"})
    assert "segretissima" not in secrets.mascherato("smtp_password")
    assert secrets.mascherato("smtp_host") == "smtp.x.it"


def test_mancanti(cassaforte):
    cassaforte["smtp_host"] = "smtp.x.it"
    m = secrets.mancanti(["smtp_host", "smtp_port"])
    assert m == ["smtp_port"]


# --- il criterio di uscita: nessuna credenziale nel repository ----------------

# Un'assegnazione a un valore letterale di almeno otto caratteri, accanto a una
# parola che sa di credenziale. Non prende "password per app" in un commento,
# prende `smtp_password = "abcd1234"`.
_SOSPETTA = re.compile(
    r"""(password|passwd|token|api[_-]?key|secret)\w*["']?\s*[:=]\s*["']([^"'\s]{8,})["']""",
    re.I)

# Valori di prova dichiarati come tali nei test e nelle fixture: sono finti per
# costruzione e servono a far girare la suite.
_DI_PROVA = {"password-di-prova-per-app", "token-di-prova", "segretissima",
             "token-sbagliato"}


def test_nessuna_credenziale_nel_repository():
    """Il criterio di uscita "verificato con git grep", in forma eseguibile.

    Si scorrono i file TRACCIATI da git — quelli che finirebbero in un push —
    cercando assegnazioni di valori letterali a campi che sanno di
    credenziale. Una lista di controllo spuntata una volta protegge fino al
    primo commit distratto; questo test protegge a ogni esecuzione.
    """
    try:
        tracciati = subprocess.run(["git", "ls-files"], capture_output=True,
                                   text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git non disponibile")

    colpevoli = []
    for f in tracciati:
        if not f.endswith((".py", ".toml", ".json", ".md", ".txt", ".ini", ".cfg")):
            continue
        try:
            testo = open(f, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        for m in _SOSPETTA.finditer(testo):
            if m.group(2) not in _DI_PROVA:
                colpevoli.append(f"{f}: {m.group(0)[:60]}")
    assert not colpevoli, "credenziali in chiaro: " + "; ".join(colpevoli)


def test_il_controllo_sulle_credenziali_ne_riconosce_una():
    """Meta-test: una verifica che non sa vedere il difetto passa sempre."""
    assert _SOSPETTA.search('smtp_password = "abcd1234efgh"')
    assert _SOSPETTA.search('"ha_token": "eyJhbGciOiJIUzI1NiJ9"')
    assert not _SOSPETTA.search("# serve una password per app, non quella dell'account")
