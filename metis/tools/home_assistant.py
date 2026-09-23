"""Home Assistant: i dispositivi di casa. La prima volta che Metis tocca il
mondo fisico.

WEBSOCKET, NON REST
Una connessione sola, aperta all'avvio e tenuta viva. Home Assistant spinge
ogni cambio di stato (`state_changed`) e qui si tiene una cache: "la
friggitrice e' accesa?" si risponde senza un giro di rete, e lo slot
`ultimo_dispositivo` si popola con uno stato vero.

LA CACHE NON SOPRAVVIVE ALLA DISCONNESSIONE
E' la regola che conta di piu' in questo file. Quando la connessione cade,
la cache si svuota — non si "tiene l'ultimo stato noto". Una friggitrice
accesa da qualcun altro mentre la connessione era giu' risulterebbe spenta,
e Metis lo direbbe con sicurezza. Il piano lo chiama "stato memorizzato
spacciato per attuale": e' il difetto peggiore che questo modulo possa avere,
e l'unico modo di non averlo e' non ricordare.

Quindi: connesso = stato vero; disconnesso = "l'hub domotico non risponde",
detto prima ancora di chiedere conferma.

IL PERIMETRO E' IL FILE DI CONFIGURAZIONE
Il modello nomina un dispositivo per nome; il nome si risolve contro
`config/home_assistant.toml`, e solo li'. Nessuno strumento accetta un
`entity_id`. Vedi la nota in testa a `schemas.py`.

I LIMITI SONO GUARDIE, NON BUONE INTENZIONI

    max_erogazioni_giorno   contate in `data/casa.db`: sopravvivono al
                            riavvio, altrimenti riavviare Metis azzererebbe il
                            limite del gatto
    max_durata_min          all'accensione si programma lo spegnimento come
                            job PERSISTENTE: se Metis si riavvia con la
                            friggitrice accesa, lo spegnimento scatta lo stesso

Lo spegnimento di sicurezza non passa dal broker e non chiede conferma. E'
l'unica azione su un dispositivo che Metis fa da solo, ed e' voluto: riduce
il rischio invece di aumentarlo, e chiedere "posso spegnere la friggitrice
accesa da un'ora?" a un utente che non c'e' vorrebbe dire lasciarla accesa.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from metis.llm.schemas import GetHomeState, ListHomeDevices, SetHomeDevice
from metis.security.audit import Tier
from metis.security.guards import Guard
from metis.tools.registry import REGISTRY, Rifiuto

CONFIG = Path("config/home_assistant.toml")
DB = Path("data/casa.db")

TIMEOUT_CHIAMATA_S = 5.0
BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0)   # si ferma sull'ultimo, non si arrende

NON_RISPONDE = "L'hub domotico non risponde. Provo a riconnettermi."
NON_CONFIGURATO = ("L'hub domotico non e' configurato: mancano indirizzo e "
                   "token, si impostano con scripts/setup_secrets.py.")


# --- configurazione -------------------------------------------------------------

@dataclass(frozen=True)
class Dispositivo:
    chiave: str
    entity_id: str
    nome: str
    alias: tuple[str, ...] = ()
    scrivibile: bool = True
    max_durata_min: int | None = None
    max_erogazioni_giorno: int | None = None

    @property
    def dominio(self) -> str:
        return self.entity_id.split(".", 1)[0]


def carica(path: Path | None = None) -> tuple[dict[str, Dispositivo], list[str]]:
    """Dispositivi validi e avvisi su quelli scartati. Non solleva.

    Un'entita' con un campo sbagliato si scarta e si dice perche', invece di
    far fallire l'avvio: una riga storta nel file non deve spegnere tutta la
    domotica.
    """
    try:
        dati = tomllib.loads((path or CONFIG).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, [f"config illeggibile: {exc}"]

    out: dict[str, Dispositivo] = {}
    avvisi: list[str] = []
    for chiave, e in (dati.get("entities") or {}).items():
        eid = str(e.get("entity_id", ""))
        if "." not in eid:
            avvisi.append(f"{chiave}: entity_id mancante o malformato")
            continue
        # Il tier non si abbassa dal file: vedi il commento in testa al TOML.
        for campo in ("tier", "tier_scrittura"):
            if campo in e and str(e[campo]) != "T3":
                avvisi.append(f"{chiave}: {campo}={e[campo]} ignorato, le "
                              "scritture sono sempre T3")
        if "tier_lettura" in e and str(e["tier_lettura"]) != "T0":
            avvisi.append(f"{chiave}: tier_lettura={e['tier_lettura']} "
                          "ignorato, le letture sono T0")
        try:
            durata = e.get("max_durata_min")
            erog = e.get("max_erogazioni_giorno")
            d = Dispositivo(
                chiave=chiave, entity_id=eid,
                nome=str(e.get("nome", chiave)),
                alias=tuple(str(a) for a in e.get("alias", [])),
                scrivibile=bool(e.get("scrivibile", True)),
                max_durata_min=int(durata) if durata is not None else None,
                max_erogazioni_giorno=int(erog) if erog is not None else None,
            )
        except (TypeError, ValueError) as exc:
            avvisi.append(f"{chiave}: {exc}")
            continue
        if (d.max_durata_min is not None and d.max_durata_min <= 0) or \
                (d.max_erogazioni_giorno is not None and d.max_erogazioni_giorno < 0):
            avvisi.append(f"{chiave}: un limite dev'essere positivo")
            continue
        out[chiave] = d
    return out, avvisi


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.casefold())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def risolvi(nome: str, dispositivi: dict[str, Dispositivo] | None = None) -> Dispositivo:
    """Da nome detto a dispositivo configurato. Esatto, poi contenuto; piu'
    di uno o nessuno: `Rifiuto`. La stessa regola delle finestre in M4."""
    disp = dispositivi if dispositivi is not None else carica()[0]
    detto = _norm(nome)
    nomi = {d.chiave: {_norm(x) for x in (d.chiave, d.nome, *d.alias)}
            for d in disp.values()}

    esatti = [disp[k] for k, forme in nomi.items() if detto in forme]
    if len(esatti) == 1:
        return esatti[0]
    trovati = esatti or [disp[k] for k, forme in nomi.items()
                         if any(f in detto or detto in f for f in forme)]
    if not trovati:
        raise Rifiuto(f"Non conosco nessun dispositivo chiamato \"{nome}\".")
    if len(trovati) > 1:
        raise Rifiuto("Potrebbe essere " + " oppure ".join(d.nome for d in trovati)
                      + ": mi dica quale.")
    return trovati[0]


# --- registro delle erogazioni -------------------------------------------------

class Registro:
    """Le accensioni dei dispositivi con un limite giornaliero. Su SQLite:
    riavviare Metis non deve azzerare il conto."""

    def __init__(self, path: Path | str = DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS accensioni "
                      "(chiave TEXT, giorno TEXT, quando TEXT)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    def oggi(self, chiave: str, giorno: str | None = None) -> int:
        giorno = giorno or datetime.now().strftime("%Y-%m-%d")
        with self._lock, self._conn() as c:
            return int(c.execute(
                "SELECT COUNT(*) FROM accensioni WHERE chiave=? AND giorno=?",
                (chiave, giorno)).fetchone()[0])

    def registra(self, chiave: str) -> None:
        ora = datetime.now()
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO accensioni VALUES (?,?,?)",
                      (chiave, ora.strftime("%Y-%m-%d"),
                       ora.isoformat(timespec="seconds")))


_registro: Registro | None = None


def registro() -> Registro:
    global _registro
    if _registro is None:
        _registro = Registro()
    return _registro


def usa_registro(r: Registro | None) -> None:
    global _registro
    _registro = r


# --- il client WebSocket ---------------------------------------------------------

class ClienteHA:
    """Connessione persistente a Home Assistant, su un thread con il suo loop.

    Il resto di Metis e' sincrono e non deve sapere che qui c'e' asyncio: le
    chiamate attraversano il confine con `run_coroutine_threadsafe` e tornano
    con un timeout. Un Home Assistant che non risponde costa cinque secondi e
    un rifiuto, mai un thread appeso.
    """

    def __init__(self, url: str, token: str, backoff: tuple[float, ...] = BACKOFF_S):
        self.url = url
        self._token = token
        self.backoff = backoff
        self._stati: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._connesso = threading.Event()
        self._ferma = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._prossimo_id = 1
        self._in_attesa: dict[int, asyncio.Future] = {}
        self._thread: threading.Thread | None = None
        self.connessioni = 0
        self.disconnessioni = 0
        self.ultimo_errore = ""

    # -- ciclo di vita --

    def avvia(self) -> None:
        self._ferma = False
        self._thread = threading.Thread(target=self._esegui, daemon=True,
                                        name="metis-home-assistant")
        self._thread.start()

    def ferma(self) -> None:
        self._ferma = True
        loop = self._loop
        if loop is not None and loop.is_running() and self._ws is not None:
            asyncio.run_coroutine_threadsafe(self._ws.close(), loop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def attendi_connessione(self, timeout: float = 5.0) -> bool:
        return self._connesso.wait(timeout)

    @property
    def disponibile(self) -> bool:
        return self._connesso.is_set()

    # -- letture: dalla cache, e solo se connessi --

    def stato(self, entity_id: str) -> dict | None:
        """Lo stato ATTUALE, oppure `Rifiuto` se non si puo' sapere.

        None significa "connessi, ma Home Assistant non conosce questa
        entita'" — un errore di configurazione, non un guasto di rete.
        """
        if not self.disponibile:
            raise Rifiuto(NON_RISPONDE)
        with self._lock:
            s = self._stati.get(entity_id)
            return dict(s) if s is not None else None

    # -- scritture --

    def chiama(self, dominio: str, servizio: str, entity_id: str,
               timeout: float = TIMEOUT_CHIAMATA_S) -> dict:
        if not self.disponibile or self._loop is None:
            raise Rifiuto(NON_RISPONDE)
        messaggio = {"type": "call_service", "domain": dominio,
                     "service": servizio, "target": {"entity_id": entity_id}}
        fut = asyncio.run_coroutine_threadsafe(self._richiesta(messaggio), self._loop)
        try:
            risposta = fut.result(timeout=timeout)
        except Exception as exc:                  # noqa: BLE001
            fut.cancel()
            raise Rifiuto(f"L'hub domotico non ha confermato il comando "
                          f"({type(exc).__name__}).") from None
        if not risposta.get("success", False):
            err = (risposta.get("error") or {}).get("message", "errore sconosciuto")
            raise Rifiuto(f"Home Assistant ha rifiutato il comando: {err}.")
        return risposta

    # -- dentro il thread --

    def _esegui(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._ciclo())
        finally:
            self._loop.close()
            self._loop = None

    async def _ciclo(self) -> None:
        import websockets

        tentativo = 0
        while not self._ferma:
            try:
                async with websockets.connect(self.url, open_timeout=5,
                                              max_size=8 * 1024 * 1024) as ws:
                    self._ws = ws
                    await self._autentica(ws)
                    await self._carica_stati(ws)
                    await self._sottoscrivi(ws)
                    self.connessioni += 1
                    tentativo = 0
                    self._connesso.set()
                    await self._ascolta(ws)
            except Exception as exc:              # noqa: BLE001
                self.ultimo_errore = f"{type(exc).__name__}: {exc}"[:200]
            finally:
                self._perdi_connessione()
            if self._ferma:
                break
            await asyncio.sleep(self.backoff[min(tentativo, len(self.backoff) - 1)])
            tentativo += 1

    def _perdi_connessione(self) -> None:
        """La regola del modulo: disconnesso = NESSUNO stato. Vedi la nota in
        testa."""
        if self._connesso.is_set():
            self.disconnessioni += 1
        self._connesso.clear()
        self._ws = None
        with self._lock:
            self._stati.clear()
        for f in self._in_attesa.values():
            if not f.done():
                f.set_exception(ConnectionError("connessione persa"))
        self._in_attesa.clear()

    async def _autentica(self, ws) -> None:
        benvenuto = json.loads(await ws.recv())
        if benvenuto.get("type") != "auth_required":
            raise ConnectionError(f"risposta inattesa: {benvenuto.get('type')}")
        await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
        esito = json.loads(await ws.recv())
        if esito.get("type") != "auth_ok":
            # Un token sbagliato non si risolve riprovando: si continua a
            # riprovare lo stesso, con il backoff, perche' il token si puo'
            # correggere con lo script di setup senza riavviare Metis — ma
            # l'errore resta leggibile nella diagnosi.
            raise PermissionError("token rifiutato da Home Assistant")

    def _nuovo_id(self) -> int:
        i = self._prossimo_id
        self._prossimo_id += 1
        return i

    async def _carica_stati(self, ws) -> None:
        mid = self._nuovo_id()
        await ws.send(json.dumps({"id": mid, "type": "get_states"}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == mid and m.get("type") == "result":
                with self._lock:
                    self._stati = {s["entity_id"]: s for s in (m.get("result") or [])}
                return

    async def _sottoscrivi(self, ws) -> None:
        mid = self._nuovo_id()
        await ws.send(json.dumps({"id": mid, "type": "subscribe_events",
                                  "event_type": "state_changed"}))

    async def _richiesta(self, messaggio: dict) -> dict:
        ws = self._ws
        if ws is None:
            raise ConnectionError("non connesso")
        mid = self._nuovo_id()
        fut = asyncio.get_running_loop().create_future()
        self._in_attesa[mid] = fut
        await ws.send(json.dumps({"id": mid, **messaggio}))
        return await fut

    async def _ascolta(self, ws) -> None:
        async for grezzo in ws:
            m = json.loads(grezzo)
            if m.get("type") == "result":
                fut = self._in_attesa.pop(m.get("id"), None)
                if fut is not None and not fut.done():
                    fut.set_result(m)
            elif m.get("type") == "event":
                dati = (m.get("event") or {}).get("data") or {}
                nuovo = dati.get("new_state")
                eid = dati.get("entity_id")
                if eid:
                    with self._lock:
                        if nuovo is None:
                            self._stati.pop(eid, None)
                        else:
                            self._stati[eid] = nuovo
            if self._ferma:
                break


_cliente: ClienteHA | None = None


def cliente() -> ClienteHA:
    """Il client dell'applicazione, oppure `Rifiuto` se non e' configurato."""
    if _cliente is None:
        raise Rifiuto(NON_CONFIGURATO)
    return _cliente


def usa_cliente(c: ClienteHA | None) -> None:
    global _cliente
    _cliente = c


def avvia_da_segreti() -> ClienteHA | None:
    """All'avvio di Metis. Senza credenziali non parte, e gli strumenti lo
    dicono: niente default, niente "homeassistant.local" indovinato."""
    from metis.core import secrets

    try:
        url, token = secrets.get("ha_url"), secrets.get("ha_token")
    except secrets.SecretMissing:
        return None
    c = ClienteHA(url, token)
    c.avvia()
    usa_cliente(c)
    return c


# --- guardie ---------------------------------------------------------------------

def _guardia_dispositivo(call) -> str | None:
    """Il nome deve risolversi PRIMA della conferma: chiedere all'utente di
    approvare l'accensione di un dispositivo che non esiste insegna a
    premere Approva senza leggere."""
    try:
        d = risolvi(call.dispositivo)
    except Rifiuto as r:
        return str(r).rstrip(".")
    if getattr(call, "azione", None) is not None and not d.scrivibile:
        return f"{d.nome} e' configurato in sola lettura"
    return None


def _guardia_hub(call) -> str | None:
    """Hub giu' si dice subito, non dopo aver chiesto conferma."""
    try:
        c = cliente()
    except Rifiuto as r:
        return str(r).rstrip(".")
    return None if c.disponibile else NON_RISPONDE.rstrip(".")


def _guardia_erogazioni(call) -> str | None:
    if call.azione != "accendi":
        return None
    try:
        d = risolvi(call.dispositivo)
    except Rifiuto:
        return None                               # ci pensa l'altra guardia
    if d.max_erogazioni_giorno is None:
        return None
    fatte = registro().oggi(d.chiave)
    if fatte >= d.max_erogazioni_giorno:
        return (f"{d.nome}: oggi e' gia' stato attivato {fatte} volte, il "
                f"limite e' {d.max_erogazioni_giorno}")
    return None


GUARDIA_DISPOSITIVO = Guard("dispositivo", _guardia_dispositivo)
# Immediata: fra la conferma e il comando possono passare venti secondi, e
# la connessione puo' essere caduta nel frattempo.
GUARDIA_HUB = Guard("hub", _guardia_hub, immediato=True)
# Immediata anche questa: due conferme aperte in parallelo non devono
# superare il limite insieme.
GUARDIA_EROGAZIONI = Guard("erogazioni", _guardia_erogazioni, immediato=True)


def presenta_comando(call: SetHomeDevice) -> dict[str, str]:
    d = risolvi(call.dispositivo)
    voci = {"dispositivo": d.nome, "azione": call.azione}
    if call.azione == "accendi" and d.max_durata_min:
        voci["limite"] = f"si spegnerà automaticamente dopo {d.max_durata_min} minuti"
    if call.azione == "accendi" and d.max_erogazioni_giorno is not None:
        fatte = registro().oggi(d.chiave)
        voci["oggi"] = (f"{fatte} su {d.max_erogazioni_giorno} consentite, "
                        f"questa sarebbe la {fatte + 1}ª")
    return voci


# --- strumenti -------------------------------------------------------------------

ACCESO = {"on", "open", "playing", "recording", "streaming", "idle"}


def _descrivi_stato(d: Dispositivo, s: dict | None) -> dict:
    if s is None:
        return {"nome": d.nome, "chiave": d.chiave, "stato": "sconosciuto",
                "noto": False}
    return {"nome": d.nome, "chiave": d.chiave, "stato": s.get("state", "?"),
            "acceso": s.get("state") in ACCESO, "noto": True,
            "dal": s.get("last_changed", "")}


@REGISTRY.strumento(Tier.T0, GetHomeState, guards=(GUARDIA_DISPOSITIVO,))
def _get_home_state(call: GetHomeState) -> dict:
    """Stato attuale di un dispositivo di casa."""
    d = risolvi(call.dispositivo)
    s = cliente().stato(d.entity_id)
    if s is None:
        raise Rifiuto(f"Home Assistant non conosce {d.entity_id}: "
                      "va controllata la configurazione.")
    return _descrivi_stato(d, s)


@REGISTRY.strumento(Tier.T0, ListHomeDevices)
def _list_home_devices(call: ListHomeDevices) -> dict:
    """Elenca i dispositivi di casa configurati, con lo stato se noto."""
    dispositivi, _ = carica()
    try:
        c = cliente()
        connesso = c.disponibile
    except Rifiuto:
        c, connesso = None, False
    voci = []
    for d in dispositivi.values():
        s = c.stato(d.entity_id) if connesso and c is not None else None
        voci.append(_descrivi_stato(d, s))
    return {"totale": len(voci), "connesso": connesso, "dispositivi": voci}


@REGISTRY.strumento(Tier.T3, SetHomeDevice,
                    guards=(GUARDIA_DISPOSITIVO, GUARDIA_HUB, GUARDIA_EROGAZIONI),
                    presenta=presenta_comando)
def _set_home_device(call: SetHomeDevice) -> dict:
    """Accende o spegne un dispositivo di casa. Conferma obbligatoria."""
    d = risolvi(call.dispositivo)
    servizio = "turn_on" if call.azione == "accendi" else "turn_off"
    cliente().chiama(d.dominio, servizio, d.entity_id)

    fuori = {"nome": d.nome, "chiave": d.chiave, "azione": call.azione}
    if call.azione == "accendi":
        if d.max_erogazioni_giorno is not None:
            registro().registra(d.chiave)
            fuori["oggi"] = registro().oggi(d.chiave)
            fuori["limite_giorno"] = d.max_erogazioni_giorno
        if d.max_durata_min:
            from metis.tools.scheduler import pianificatore

            quando = datetime.now().replace(microsecond=0) + timedelta(
                minutes=d.max_durata_min)
            try:
                pianificatore().spegnimento(d.chiave, quando)
                fuori["spegnimento"] = quando.strftime("%H:%M")
            except Rifiuto:
                # Il limite di sicurezza non si puo' programmare: la
                # friggitrice e' gia' accesa, e va detto. Spegnerla subito
                # sarebbe annullare cio' che l'utente ha appena confermato.
                fuori["spegnimento"] = None
    return fuori


def spegni_per_sicurezza(dati: dict) -> dict:
    """La consegna dei job di tipo "spegni". Vedi la nota in testa: e'
    l'unica azione che Metis fa da solo su un dispositivo, e riduce il
    rischio invece di aumentarlo."""
    dispositivi, _ = carica()
    d = dispositivi.get(dati.get("dispositivo", ""))
    if d is None:
        return {"esito": "sconosciuto", "dispositivo": dati.get("dispositivo")}
    t0 = time.perf_counter()
    tentativo = int(dati.get("tentativo", 0))
    try:
        cliente().chiama(d.dominio, "turn_off", d.entity_id)
        return {"esito": "spento", "nome": d.nome, "chiave": d.chiave,
                "tentativo": tentativo,
                "ms": round((time.perf_counter() - t0) * 1000)}
    except Rifiuto as r:
        motivo = str(r)

    # NON RIUSCITO: SI RIPROVA, NON SI RINUNCIA
    # Il job scatta una volta sola. Se all'ora prevista l'hub era giu', senza
    # questo blocco la friggitrice restava accesa per sempre, con il limite di
    # sicurezza "eseguito" nell'elenco dei job. Si riprogramma fra un minuto,
    # per mezz'ora; chi consegna lo notifica a ogni tentativo fallito.
    riprova = tentativo < TENTATIVI_SPEGNIMENTO
    if riprova:
        from metis.tools.scheduler import pianificatore

        try:
            pianificatore().spegnimento(
                d.chiave, datetime.now().replace(microsecond=0) + timedelta(minutes=1),
                tentativo=tentativo + 1)
        except Rifiuto:
            riprova = False
    return {"esito": "non riuscito", "motivo": motivo, "nome": d.nome,
            "chiave": d.chiave, "tentativo": tentativo, "riprova": riprova,
            "ms": round((time.perf_counter() - t0) * 1000)}


TENTATIVI_SPEGNIMENTO = 30
