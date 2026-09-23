"""Notifiche desktop di Windows. Non e' uno strumento: e' un'uscita.

Il modello non puo' "mandare una notifica": qui non c'e' nessun
`@REGISTRY.strumento`. Le notifiche le producono i promemoria quando scattano,
le email programmate quando partono, e gli errori che Metis non puo'
pronunciare. Chi decide cosa notificare e' il codice, non una frase.

NON BLOCCA E NON SOLLEVA
`win11toast.toast` resta appesa finche' la notifica non viene chiusa o
cliccata: puo' voler dire minuti. Gira quindi su un thread suo. E una notifica
che non si riesce a mostrare — servizio di notifica spento, sessione remota,
Windows in modalita' "non disturbare" — non deve far fallire il promemoria:
si registra e si prosegue, perche' l'annuncio vocale c'e' comunque.

IL BACKEND SI SOSTITUISCE NEI TEST
La suite non deve riempire di notifiche il desktop di chi la lancia.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

APP_ID = "Metis"


@dataclass
class Notifica:
    titolo: str
    testo: str
    pulsanti: tuple[str, ...] = ()


@dataclass
class Stato:
    mostrate: list[Notifica] = field(default_factory=list)
    fallite: int = 0
    ultimo_errore: str = ""


STATO = Stato()


class NotificaRifiutata(Exception):
    """Windows ha rifiutato la notifica. Non solleva la libreria: lo
    segnala con una callback, vedi `_win11toast`."""


# Codici noti. 0x803E0114 e' quello misurato su questa macchina con le
# notifiche disattivate nelle impostazioni (ToastEnabled = 0).
_HRESULT = {-2143420140: "notifiche disattivate nelle impostazioni di Windows"}


def _win11toast(n: Notifica, su_clic: Callable[[str], None] | None) -> None:
    """IL FALLIMENTO NON E' UN'ECCEZIONE (misurato in M6)
    `win11toast` non solleva quando Windows rifiuta la notifica: chiama
    `on_failed`, che di default e' `print`, e ritorna. La prima versione di
    questo file non passava `on_failed`, quindi una notifica respinta veniva
    contata come MOSTRATA — e un `HResult` stampato su stdout era l'unica
    traccia. Scoperto mandando una notifica vera: sul desktop non e' comparso
    niente, e il contatore diceva 1.
    """
    from win11toast import toast

    esito: dict = {}
    risultato = toast(n.titolo, n.testo, app_id=APP_ID,
                      buttons=list(n.pulsanti) or [], duration="long",
                      on_failed=lambda e: esito.__setitem__("fallita", e),
                      on_dismissed=lambda e: esito.__setitem__("chiusa", e),
                      on_click=lambda e: esito.__setitem__("clic", e))
    if "fallita" in esito:
        codice = _codice(esito["fallita"])
        raise NotificaRifiutata(_HRESULT.get(codice, f"HRESULT {codice}"))
    # `toast` ritorna il dizionario degli argomenti dell'attivazione quando
    # l'utente clicca un pulsante; altrimenti qualcosa che non lo e'.
    if su_clic is not None and isinstance(risultato, dict):
        scelta = risultato.get("arguments", "")
        if scelta:
            su_clic(str(scelta).removeprefix("http:"))


def _codice(errore) -> int | str:
    """L'HRESULT dentro la tupla che win11toast passa a `on_failed`."""
    try:
        valore = errore[0] if isinstance(errore, tuple) else errore
        return int(getattr(valore, "value", valore))
    except (TypeError, ValueError, IndexError):
        return str(errore)[:60]


def abilitate() -> bool | None:
    """Le notifiche sono accese nelle impostazioni di Windows? None = non si
    sa. Sola lettura del registro: Metis non cambia le impostazioni di chi lo
    usa, le riferisce."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\PushNotifications") as k:
            valore, _ = winreg.QueryValueEx(k, "ToastEnabled")
        return bool(valore)
    except OSError:
        return None                                # chiave assente: default acceso


_backend: Callable[[Notifica, Callable[[str], None] | None], None] = _win11toast


def usa_backend(fn) -> None:
    """Solo per i test. `None` ripristina win11toast."""
    global _backend
    _backend = _win11toast if fn is None else fn


def mostra(titolo: str, testo: str, pulsanti: tuple[str, ...] = (),
           su_clic: Callable[[str], None] | None = None,
           attendi: bool = False) -> None:
    """Mostra una notifica. Non blocca, non solleva.

    `su_clic` riceve il testo del pulsante premuto. `attendi` esiste per i
    test, che devono sapere quando la notifica e' stata consegnata.
    """
    n = Notifica(titolo, testo, tuple(pulsanti))

    def lavora() -> None:
        try:
            _backend(n, su_clic)
            STATO.mostrate.append(n)
        except Exception as exc:                  # noqa: BLE001
            STATO.fallite += 1
            STATO.ultimo_errore = f"{type(exc).__name__}: {exc}"[:200]

    if attendi:
        lavora()
        return
    threading.Thread(target=lavora, daemon=True, name="metis-notifica").start()
