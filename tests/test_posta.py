"""La posta, contro un server SMTP vero e cifrato in locale.

Vedi `tests/fixtures/smtp.py` sul perche' non un `smtplib` finto: qui si
verifica che la cifratura sia negoziata davvero e che il messaggio arrivi
intero dall'altra parte, non che il codice abbia chiamato i metodi giusti.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.smtp import PASSWORD, UTENTE, ServerSMTP  # noqa: E402

from metis.core import secrets  # noqa: E402
from metis.security.audit import AuditLog  # noqa: E402
from metis.security.broker import Broker  # noqa: E402
from metis.security.policies import Context  # noqa: E402
from metis.tools import posta  # noqa: E402
from metis.tools.registry import Rifiuto, carica_tutti  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

REG = carica_tutti()
DEST = "marco@esempio.it"


@pytest.fixture
def lista(tmp_path, monkeypatch):
    f = tmp_path / "email.toml"
    f.write_text(f'[allowlist]\nindirizzi = ["{DEST}", "Anna@Esempio.IT"]\n',
                 encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", f)
    return f


@pytest.fixture
def ssl_server():
    with ServerSMTP("ssl") as s:
        secrets.usa_backend(s.segreti())
        yield s
    secrets.usa_backend(None)


# --- l'invio vero --------------------------------------------------------------

def test_invio_con_ssl_implicito(lista, ssl_server):
    r = posta.invia(DEST, "Lista della spesa", "latte\npane",
                    contesto_ssl=ssl_server.ctx_client)
    m = ssl_server.casella.messaggi[-1]
    assert m.cifrato, "il messaggio e' passato in chiaro"
    assert m.autenticato_come == UTENTE
    assert m.destinatari == [DEST]
    assert b"Lista della spesa" in m.dati and b"latte" in m.dati
    assert r["to"] == DEST and r["caratteri"] == len("latte\npane")


def test_invio_con_starttls(lista, monkeypatch):
    with ServerSMTP("starttls") as s:
        monkeypatch.setattr(posta, "PORTA_STARTTLS", s.porta)
        secrets.usa_backend(s.segreti())
        try:
            posta.invia(DEST, "Prova", "corpo", contesto_ssl=s.ctx_client)
        finally:
            secrets.usa_backend(None)
        assert s.casella.messaggi[-1].cifrato


def test_la_verifica_del_certificato_resta_accesa(lista, ssl_server):
    """Senza la CA di prova, il certificato del server locale non e' fidato
    e l'invio deve fallire. Se passasse, vorrebbe dire che la verifica e'
    spenta — e in esercizio si manderebbe la password a chiunque risponda."""
    import ssl

    with pytest.raises(ssl.SSLError):
        posta.invia(DEST, "x", "y")        # contesto di sistema, senza la CA
    assert ssl_server.casella.messaggi == []


def test_il_corpo_arriva_intero(lista, ssl_server):
    corpo = "riga\n" * 800
    posta.invia(DEST, "Lunga", corpo, contesto_ssl=ssl_server.ctx_client)
    assert ssl_server.casella.messaggi[-1].dati.count(b"riga") == 800


# --- i rifiuti ------------------------------------------------------------------

def test_destinatario_fuori_allowlist(lista, ssl_server):
    with pytest.raises(Rifiuto) as e:
        posta.invia("sconosciuto@esempio.it", "x", "y",
                    contesto_ssl=ssl_server.ctx_client)
    assert "autorizzati" in str(e.value)
    assert ssl_server.casella.messaggi == [], "e' partita comunque"


def test_l_allowlist_non_distingue_le_maiuscole(lista):
    assert posta.motivo_destinatario("anna@esempio.it") is None
    assert posta.motivo_destinatario("MARCO@esempio.it") is None


def test_niente_caratteri_jolly(tmp_path, monkeypatch):
    """Un "*@gmail.com" sarebbe un'allowlist di un miliardo di persone."""
    f = tmp_path / "e.toml"
    f.write_text('[allowlist]\nindirizzi = ["*@esempio.it"]\n', encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", f)
    assert posta.motivo_destinatario("chiunque@esempio.it") is not None


def test_allowlist_vuota_o_illeggibile_e_nessun_destinatario(tmp_path, monkeypatch):
    f = tmp_path / "e.toml"
    f.write_text("questo non e' toml [[[", encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", f)
    assert posta.allowlist() == frozenset()
    assert "nessun destinatario" in posta.motivo_destinatario(DEST)


def test_l_allowlist_del_repository_e_vuota():
    """Il repository non autorizza nessuno: gli indirizzi li aggiunge chi
    usa Metis, sulla propria macchina."""
    assert posta.allowlist(Path("config/email.toml")) == frozenset()


def test_posta_non_configurata(lista):
    secrets.usa_backend({})
    try:
        with pytest.raises(Rifiuto) as e:
            posta.invia(DEST, "x", "y")
        assert "smtp_host" in str(e.value)
    finally:
        secrets.usa_backend(None)


def test_credenziali_sbagliate(lista, ssl_server):
    secrets.usa_backend(ssl_server.segreti(smtp_password="sbagliata"))
    with pytest.raises(Rifiuto) as e:
        posta.invia(DEST, "x", "y", contesto_ssl=ssl_server.ctx_client)
    assert "credenziali" in str(e.value)
    assert PASSWORD not in str(e.value)


# --- attraverso il broker -------------------------------------------------------

def test_send_email_senza_conferma_non_parte(tmp_path, lista, ssl_server):
    b = Broker(registry=REG, audit=AuditLog(tmp_path / "a.db"))
    r = b.execute({"tool": "send_email", "to": DEST, "subject": "s", "body": "b"},
                  Context())
    assert r.denied and r.stage == "conferma"
    assert ssl_server.casella.messaggi == []


def test_chi_conferma_vede_il_corpo_intero(tmp_path, lista):
    """Il criterio di uscita: la conferma mostra il corpo COMPLETO."""
    from metis.tools.registry import presentazione

    corpo = "inizio " + ("parte centrale " * 200) + "FINE DEL MESSAGGIO"
    visti = []
    b = Broker(registry=REG, audit=AuditLog(tmp_path / "a.db"))
    b.execute({"tool": "send_email", "to": DEST, "subject": "s", "body": corpo},
              Context(chiedi_conferma=lambda s, c: visti.append(presentazione(s, c))
                      or False))
    assert visti[0]["corpo"] == corpo


def test_la_console_mostra_il_corpo_intero(capsys, monkeypatch):
    from metis.security import conferma

    monkeypatch.setattr("builtins.input", lambda *_: "n")
    spec = REG.get("send_email")
    call = spec.schema.model_validate(
        {"tool": "send_email", "to": DEST, "subject": "s",
         "body": "x" * 600 + " CODA"})
    conferma.conferma_console(spec, call)
    assert "CODA" in capsys.readouterr().out


def test_nell_audit_il_corpo_e_troncato(tmp_path, lista):
    """Il log dice chi ha mandato cosa a chi; non e' un archivio di posta."""
    import json

    corpo = "y" * 3000
    b = Broker(registry=REG, audit=AuditLog(tmp_path / "a.db"))
    b.execute({"tool": "send_email", "to": DEST, "subject": "Oggetto", "body": corpo},
              Context())
    args = json.loads(b.audit.recent(1)[0]["args_json"])
    assert args["to"] == DEST and args["subject"] == "Oggetto"
    assert len(args["body"]) < 300 and "3000 caratteri" in args["body"]


def test_l_indirizzo_dell_utente_non_autorizza_da_solo(tmp_path, monkeypatch):
    """Configurare il proprio indirizzo dice a chi scrivere "mandami", non
    apre la posta verso di lui: deve comparire anche nell'allowlist."""
    f = tmp_path / "e.toml"
    f.write_text('[allowlist]\nindirizzi = []\n\n[utente]\nindirizzo = "io@esempio.it"\n',
                 encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", f)
    assert posta.indirizzo_utente() == "io@esempio.it"
    assert posta.motivo_destinatario("io@esempio.it") is not None


def test_il_router_sa_chi_e_me(tmp_path, monkeypatch):
    from metis.llm.toolcall import ToolRouter

    f = tmp_path / "e.toml"
    f.write_text('[utente]\nindirizzo = "io@esempio.it"\n', encoding="utf-8")
    monkeypatch.setattr(posta, "CONFIG", f)
    r = ToolRouter.__new__(ToolRouter)
    r.registry = REG
    assert "io@esempio.it" in r._prompt()
