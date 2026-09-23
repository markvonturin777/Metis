"""Un server SMTP vero, locale, cifrato con un certificato di prova.

PERCHE' NON UN FINTO `smtplib`
Un `smtplib` sostituito con un oggetto che registra le chiamate dice che il
codice ha chiamato `login` e `send_message`. Non dice che la conversazione
SMTP e' valida, che la cifratura e' davvero negoziata, che il messaggio
arriva intero dall'altra parte. Questo server si', ed e' quello che si puo'
fare senza un account di posta vero.

IL CERTIFICATO E' DI PROVA, LA VERIFICA NO
`trustme` crea una CA che esiste solo per la durata del test e le fa firmare
un certificato per 127.0.0.1. Il client la considera fidata tramite il
contesto SSL passato a `posta.invia` — non spegnendo la verifica. Un test che
passasse con `check_hostname=False` proverebbe un client che in esercizio
non esiste.
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass, field

UTENTE = "metis@esempio.it"
PASSWORD = "password-di-prova-per-app"


def porta_libera() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Ricevuto:
    mittente: str
    destinatari: list[str]
    dati: bytes
    cifrato: bool
    autenticato_come: str | None


@dataclass
class Casella:
    messaggi: list[Ricevuto] = field(default_factory=list)

    async def handle_DATA(self, server, session, envelope):
        self.messaggi.append(Ricevuto(
            mittente=envelope.mail_from,
            destinatari=list(envelope.rcpt_tos),
            dati=envelope.content,
            # Dal trasporto e non da `session.ssl`: quest'ultimo aiosmtpd lo
            # imposta solo dopo uno STARTTLS, e con il TLS implicito direbbe
            # "in chiaro" su una connessione cifrata.
            cifrato=server.transport.get_extra_info("ssl_object") is not None,
            autenticato_come=(session.auth_data.login.decode()
                              if session.auth_data else None),
        ))
        return "250 OK"


def _autentica(server, session, envelope, mechanism, auth_data):
    from aiosmtpd.smtp import AuthResult

    ok = (getattr(auth_data, "login", b"") == UTENTE.encode()
          and getattr(auth_data, "password", b"") == PASSWORD.encode())
    return AuthResult(success=ok, handled=False, auth_data=auth_data if ok else None)


class ServerSMTP:
    """Da usare come context manager. `modo` e' "ssl" oppure "starttls"."""

    def __init__(self, modo: str = "ssl"):
        import trustme

        self.modo = modo
        self.ca = trustme.CA()
        cert = self.ca.issue_cert("127.0.0.1", "localhost")
        self.ctx_server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        cert.configure_cert(self.ctx_server)
        # Il contesto del CLIENTE: quello di sistema, con verifica attiva,
        # a cui si aggiunge la CA di prova. Nient'altro cambia.
        self.ctx_client = ssl.create_default_context()
        self.ca.configure_trust(self.ctx_client)
        self.casella = Casella()
        self.porta = porta_libera()
        self._controller = None

    def __enter__(self) -> "ServerSMTP":
        from aiosmtpd.controller import Controller

        # `auth_require_tls` guarda solo lo STARTTLS: con il TLS implicito
        # aiosmtpd non si accorge di essere cifrato e non offrirebbe AUTH. La
        # cifratura del modo "ssl" la verifica il test, su `session.ssl`.
        comuni = dict(handler=self.casella, hostname="127.0.0.1", port=self.porta,
                      authenticator=_autentica,
                      auth_require_tls=(self.modo == "starttls"))
        if self.modo == "ssl":
            self._controller = Controller(
                ssl_context=self.ctx_server,
                server_hostname="127.0.0.1", **comuni)
        else:
            self._controller = Controller(
                tls_context=self.ctx_server, require_starttls=True,
                server_hostname="127.0.0.1", **comuni)
        self._controller.start()
        return self

    def __exit__(self, *_):
        self._controller.stop()

    def segreti(self, **sovrascrivi) -> dict[str, str]:
        """Il dizionario da passare a `secrets.usa_backend`."""
        return {"smtp_host": "127.0.0.1", "smtp_port": str(self.porta),
                "smtp_user": UTENTE, "smtp_password": PASSWORD, **sovrascrivi}
