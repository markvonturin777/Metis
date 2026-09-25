"""Invio della posta. Il livello sotto `send_email` e `schedule_email`.

PERCHE' NON SI CHIAMA `email.py`
Il piano lo chiamava cosi'. Un modulo `email` dentro un pacchetto e' a un
`sys.path` sbagliato di distanza dall'oscurare il modulo `email` della
libreria standard — quello che `smtplib` usa per costruire i messaggi. Il
sintomo sarebbe un `ImportError` dentro `smtplib`, lontanissimo dalla causa.

QUI NON C'E' NESSUNO STRUMENTO
Come `finestre.py` in M4: funzioni normali, usate dall'handler di
`send_email` (via broker, con conferma) e dal job di `schedule_email` quando
scatta (confermato alla creazione). Nessuna delle due vie salta l'allowlist,
perche' l'allowlist e' controllata QUI dentro oltre che dalla guardia.

TRE VINCOLI, NESSUNO NEGOZIABILE

    cifratura      SSL implicito, oppure STARTTLS sulla 587. Mai in chiaro:
                   non esiste un ramo che parli SMTP senza TLS.
    credenziali    dal Credential Manager. Mancanti = rifiuto, non default.
    destinatari    solo `config/email.toml` (e il suo `.local`, sotto). Il
                   controllo si rifa' all'invio, quindi togliere un indirizzo
                   blocca anche le email gia' programmate verso di lui.

M7 — GLI INDIRIZZI VERI STANNO IN `config/email.local.toml`
`email.toml` e' nel repository, e il repository non deve contenere
l'indirizzo di nessuno: scriverlo li' vuol dire pubblicarlo al primo push.
Accanto c'e' `email.local.toml`, stesso formato, ignorato da git. Gli
indirizzi dei due file si UNISCONO; per "me" vince il locale. Il locale puo'
solo aggiungere destinatari, mai toglierli: un file locale illeggibile
lascia l'allowlist del repository, cioe' vuota.
"""

from __future__ import annotations

import smtplib
import ssl
import time
import tomllib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from metis.core import secrets
from metis.tools.registry import Rifiuto

CONFIG = Path("config/email.toml")
TIMEOUT_S = 15.0

# La porta del STARTTLS. Tutte le altre usano SSL implicito. Una costante e
# non un confronto sparso nel codice: i test la spostano su una porta libera.
PORTA_STARTTLS = 587


def locale_di(path: Path) -> Path:
    """`config/email.toml` -> `config/email.local.toml`. Derivato, non
    fisso: i test che spostano CONFIG in una cartella temporanea si portano
    dietro anche il locale, e non leggono quello vero della macchina."""
    return path.with_name(f"{path.stem}.local{path.suffix}")


def _leggi(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        # Illeggibile = vuoto. Deny-by-default.
        return {}


def _file(path: Path | None) -> list[Path]:
    """Con un percorso esplicito, quello solo. Altrimenti il file del
    repository e il suo locale."""
    return [path] if path is not None else [CONFIG, locale_di(CONFIG)]


def allowlist(path: Path | None = None) -> frozenset[str]:
    """Gli indirizzi ammessi. Si rilegge a ogni chiamata: il file e' piccolo,
    e togliere un indirizzo deve avere effetto subito, senza riavviare."""
    voci = []
    for f in _file(path):
        voci += _leggi(f).get("allowlist", {}).get("indirizzi", [])
    return frozenset(str(v).strip().lower() for v in voci if str(v).strip())


def indirizzo_utente(path: Path | None = None) -> str:
    """Chi e' "me" in "mandami una mail". Stringa vuota se non configurato.

    NON autorizza: l'indirizzo deve comparire anche nell'allowlist. Sono due
    domande diverse — a chi scrivere, e se si puo' — e fonderle vorrebbe dire
    che configurare il proprio indirizzo apre la posta verso di lui senza che
    nessuno l'abbia deciso esplicitamente.
    """
    for f in reversed(_file(path)):          # il locale per primo
        io = str(_leggi(f).get("utente", {}).get("indirizzo", "")).strip()
        if io:
            return io
    return ""


def motivo_destinatario(to: str, path: Path | None = None) -> str | None:
    """Perche' questo destinatario non va bene, oppure None. Per la guardia."""
    ammessi = allowlist(path)
    if not ammessi:
        return ("non ho nessun destinatario autorizzato: si aggiungono in "
                "config/email.toml")
    if to.strip().lower() not in ammessi:
        return f"{to} non e' fra i destinatari autorizzati"
    return None


# M7 — quante volte si rimanda un invio fallito, e di quanto. Sei volte dieci
# minuti: un'ora. Oltre, il problema non e' passeggero e va detto.
RIMANDO_MIN = 10
MAX_RIMANDI = 6


def transitorio(exc: BaseException) -> bool:
    """L'errore passera' da solo? Decide se rimandare l'invio o rinunciare.

    Si' per la rete e per i codici 4xx (il server dice "riprova piu' tardi").
    No per cio' che non cambia aspettando: credenziali e destinatari
    respinti — gia' `Rifiuto` —, i 5xx, e il certificato che non si verifica.
    Rimandare questi ultimi vorrebbe dire presentare sei volte le stesse
    credenziali sbagliate, e al sesto tentativo molti server bloccano
    l'account.
    """
    if isinstance(exc, Rifiuto):
        return False
    if isinstance(exc, ssl.SSLCertVerificationError):
        return False
    if isinstance(exc, smtplib.SMTPResponseException):
        return 400 <= exc.smtp_code < 500
    if isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return True
    return isinstance(exc, (OSError, TimeoutError))


def componi(mittente: str, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = mittente
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="metis.local")
    msg.set_content(body)
    return msg


def invia(to: str, subject: str, body: str,
          contesto_ssl: ssl.SSLContext | None = None,
          config: Path | None = None) -> dict:
    """Spedisce. Ritorna un riassunto per l'audit; solleva `Rifiuto` o un
    errore.

    La distinzione e' quella di tutto il progetto: `Rifiuto` quando Metis
    sceglie di non farlo (destinatario non ammesso, posta non configurata,
    credenziali respinte), un'eccezione quando qualcosa si e' rotto (rete
    giu', server che non risponde).

    `contesto_ssl` esiste per i test, che parlano con un server locale dal
    certificato di prova. In esercizio e' quello di sistema, con verifica del
    certificato e del nome host: non esiste un modo di spegnerla.
    """
    motivo = motivo_destinatario(to, config)
    if motivo is not None:
        raise Rifiuto(f"Non la mando: {motivo}.")

    try:
        host = secrets.get("smtp_host")
        porta = int(secrets.get("smtp_port"))
        utente = secrets.get("smtp_user")
        password = secrets.get("smtp_password")
    except secrets.SecretMissing as e:
        raise Rifiuto(f"La posta non e' configurata: manca {e.chiave}.") from None
    except ValueError:
        raise Rifiuto("La porta SMTP configurata non e' un numero.") from None

    ctx = contesto_ssl or ssl.create_default_context()
    msg = componi(utente, to, subject, body)
    t0 = time.perf_counter()
    try:
        if porta == PORTA_STARTTLS:
            with smtplib.SMTP(host, porta, timeout=TIMEOUT_S) as s:
                s.ehlo()
                # `starttls` solleva se il server non lo offre: e' proprio il
                # comportamento voluto. Un server senza STARTTLS sulla 587
                # riceverebbe la password in chiaro.
                s.starttls(context=ctx)
                s.ehlo()
                s.login(utente, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, porta, context=ctx, timeout=TIMEOUT_S) as s:
                s.login(utente, password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise Rifiuto("Il server di posta ha rifiutato le credenziali.") from None
    except smtplib.SMTPRecipientsRefused:
        raise Rifiuto(f"Il server di posta ha rifiutato il destinatario {to}.") from None

    return {"to": to, "subject": subject, "caratteri": len(body),
            "message_id": msg["Message-ID"],
            "ms": round((time.perf_counter() - t0) * 1000)}
