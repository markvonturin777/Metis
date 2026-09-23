"""Le notifiche desktop. Nessuna notifica vera: si sostituisce `toast`."""
from __future__ import annotations

import pytest

from metis.tools import notify


@pytest.fixture(autouse=True)
def stato_pulito():
    notify.STATO.mostrate.clear()
    notify.STATO.fallite = 0
    yield
    notify.usa_backend(None)


def test_una_notifica_respinta_non_si_conta_come_mostrata(monkeypatch):
    """Misurato in M6: `win11toast` non solleva quando Windows rifiuta la
    notifica, chiama `on_failed` e ritorna. La prima versione contava come
    mostrata una notifica che sul desktop non era comparsa."""
    import win11toast

    class HResult:
        value = -2143420140

    def toast_respinta(*a, on_failed=print, **k):
        on_failed((HResult(),))
        return None

    monkeypatch.setattr(win11toast, "toast", toast_respinta)
    notify.mostra("t", "x", attendi=True)
    assert notify.STATO.mostrate == []
    assert notify.STATO.fallite == 1
    assert "disattivate" in notify.STATO.ultimo_errore


def test_una_notifica_mostrata_si_conta(monkeypatch):
    import win11toast

    monkeypatch.setattr(win11toast, "toast", lambda *a, **k: None)
    notify.mostra("t", "x", attendi=True)
    assert len(notify.STATO.mostrate) == 1 and notify.STATO.fallite == 0


def test_il_clic_su_un_pulsante_arriva(monkeypatch):
    import win11toast

    monkeypatch.setattr(win11toast, "toast",
                        lambda *a, **k: {"arguments": "http:Fra 10 minuti"})
    scelte = []
    notify.mostra("t", "x", pulsanti=("Fra 10 minuti",), su_clic=scelte.append,
                  attendi=True)
    assert scelte == ["Fra 10 minuti"]


def test_una_notifica_che_esplode_non_solleva():
    def rotto(n, c):
        raise RuntimeError("servizio notifiche giu'")

    notify.usa_backend(rotto)
    notify.mostra("t", "x", attendi=True)      # non solleva
    assert notify.STATO.fallite == 1


def test_l_impostazione_si_legge_senza_errori():
    assert notify.abilitate() in (True, False, None)
