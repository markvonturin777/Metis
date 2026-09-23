"""Segreti: credenziali SMTP, token di Home Assistant, chiavi API.

STANNO NEL CREDENTIAL MANAGER DI WINDOWS, NON SU FILE
`keyring` su Windows scrive nel Credential Manager, cifrato con DPAPI e legato
all'utente di Windows. Un file `.env` o un `secrets.toml` sarebbe un file di
testo a un `git add -A` di distanza dal repository: il `.gitignore` li elenca
per prudenza, ma il modo giusto e' che non esistano.

Si scrivono una volta con `scripts/setup_secrets.py` e da li' in poi si
leggono soltanto.

NESSUN DEFAULT, NESSUN RIPIEGO SILENZIOSO
`get()` solleva `SecretMissing` se la chiave non c'e'. Mai una stringa vuota,
mai un valore di prova, mai "localhost" al posto dell'host SMTP. Un default
silenzioso produce il difetto peggiore di questa iterazione: un'email che
"parte" verso un server che non esiste, un audit log che dice ok, e l'utente
che scopre tre giorni dopo che il promemoria per il commercialista non e' mai
arrivato.

Chi puo' fare a meno di un segreto — il motore di ricerca di ripiego, per
esempio — cattura `SecretMissing` e lo dichiara. E' una scelta scritta nel
chiamante, non un comportamento nascosto qui dentro.

IL BACKEND E' SOSTITUIBILE
Solo per i test: la suite non deve leggere ne' scrivere il Credential Manager
vero di chi la lancia. `usa_backend()` mette al suo posto un dizionario.
"""

from __future__ import annotations

from collections.abc import MutableMapping

SERVICE = "metis"

# Le chiavi conosciute, con cosa contengono. Serve allo script di setup e a
# `mancanti()`; una chiave fuori da questo elenco si legge lo stesso, ma chi
# la aggiunge dovrebbe aggiungerla qui.
CHIAVI: dict[str, str] = {
    "smtp_host": "server SMTP, es. smtp.gmail.com",
    "smtp_port": "465 (SSL) oppure 587 (STARTTLS)",
    "smtp_user": "indirizzo email: e' anche il mittente",
    "smtp_password": "password per app, NON la password dell'account",
    "ha_url": "Home Assistant, es. ws://homeassistant.local:8123/api/websocket",
    "ha_token": "long-lived access token di Home Assistant",
    "brave_api_key": "chiave Brave Search, facoltativa: ripiego della ricerca",
}

# Le chiavi che sono segrete davvero, e che quindi non si stampano mai. Le
# altre (host, porta, utente) si possono mostrare nella diagnosi.
SEGRETE = frozenset({"smtp_password", "ha_token", "brave_api_key"})


class SecretMissing(Exception):
    """Una credenziale richiesta non e' stata configurata."""

    def __init__(self, chiave: str):
        self.chiave = chiave
        super().__init__(
            f"credenziale mancante: {chiave} — si configura con "
            "`python scripts/setup_secrets.py`")


class _Keyring:
    """Il backend vero: il Credential Manager, via keyring."""

    def get(self, chiave: str) -> str | None:
        import keyring

        return keyring.get_password(SERVICE, chiave)

    def set(self, chiave: str, valore: str) -> None:
        import keyring

        keyring.set_password(SERVICE, chiave, valore)

    def delete(self, chiave: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(SERVICE, chiave)
        except PasswordDeleteError:
            pass


class _Dizionario:
    """Il backend dei test."""

    def __init__(self, dati: MutableMapping[str, str]):
        self.dati = dati

    def get(self, chiave: str) -> str | None:
        return self.dati.get(chiave)

    def set(self, chiave: str, valore: str) -> None:
        self.dati[chiave] = valore

    def delete(self, chiave: str) -> None:
        self.dati.pop(chiave, None)


_backend: _Keyring | _Dizionario = _Keyring()


def usa_backend(dati: MutableMapping[str, str] | None) -> None:
    """Solo per i test. `None` ripristina il Credential Manager vero."""
    global _backend
    _backend = _Keyring() if dati is None else _Dizionario(dati)


# --- lettura e scrittura ------------------------------------------------------

def get(chiave: str) -> str:
    """Il valore, oppure `SecretMissing`. Mai un default.

    Anche una stringa vuota conta come mancante: un campo lasciato vuoto nello
    script di setup e' un errore di configurazione, non un valore.
    """
    try:
        v = _backend.get(chiave)
    except Exception as exc:                      # noqa: BLE001
        # Il Credential Manager non risponde: e' mancante a tutti gli effetti,
        # e il motivo resta nel messaggio.
        raise SecretMissing(chiave) from exc
    if v is None or not v.strip():
        raise SecretMissing(chiave)
    return v


def presente(chiave: str) -> bool:
    try:
        get(chiave)
        return True
    except SecretMissing:
        return False


def set(chiave: str, valore: str) -> None:        # noqa: A001 - e' l'API di keyring
    if not valore or not valore.strip():
        raise ValueError(f"{chiave}: un valore vuoto non e' una credenziale")
    _backend.set(chiave, valore.strip())


def cancella(chiave: str) -> None:
    _backend.delete(chiave)


def mancanti(chiavi: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Quali delle chiavi indicate non sono configurate. Per la diagnosi."""
    return [k for k in (chiavi or list(CHIAVI)) if not presente(k)]


def mascherato(chiave: str) -> str:
    """Il valore da mostrare in una diagnosi: in chiaro se non e' segreto,
    altrimenti solo che c'e'."""
    if not presente(chiave):
        return "— mancante"
    if chiave in SEGRETE:
        return "•••••• (configurata)"
    return get(chiave)
