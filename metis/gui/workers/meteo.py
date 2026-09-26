"""Il meteo dell'Hub, da Open-Meteo, su un thread suo. PHASE1, D-UI 5.

NESSUN ACCOUNT, NESSUNA CHIAVE
Open-Meteo risponde senza registrazione. Dal PC escono le coordinate, ogni
15 minuti, e una volta sola il nome della citta' per trovarle. La citta' sta
in `config/gui.local.toml`, ignorato da git come `email.local.toml`.

NON E' UNO STRUMENTO DI METIS (D-UI 6)
Il modello non lo vede e non lo chiama: e' un pannello, come la telemetria.
"Che tempo fa?" resta una ricerca web finche' non si decide altrimenti.

SENZA RETE
Si mostra l'ultimo dato con la sua ora ("dato delle 14:30"), finche' ha meno
di tre ore; poi una frase in persona. Mai un traceback, mai un'attesa sul
thread della GUI: la rete si tocca solo qui, e chi disegna riceve un
dizionario. Il timeout e' corto (4 s) anche per un motivo di chiusura:
all'uscita l'applicazione aspetta questo thread, e una richiesta appesa non
deve trattenere Metis.

LA CACHE SOPRAVVIVE AL RIAVVIO
`data/meteo.json`: l'ultima lettura e le coordinate trovate. All'avvio si
mostra subito quella, con la sua ora, poi si chiede il dato nuovo.

Questo modulo non importa `QtWidgets`: vedi `tests/test_gui_thread.py`.
"""

from __future__ import annotations

import json
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

INTERVALLO_S = 15 * 60
RITENTA_S = 2 * 60              # dopo un fallimento, prima del giro normale
TIMEOUT_S = 4.0
VECCHIO_S = 3 * 3600            # oltre, il dato non si mostra piu'
PASSO_ATTESA_S = 0.25           # ogni quanto l'attesa guarda se deve uscire

CONFIG = Path("config/gui.toml")
CACHE = Path("data/meteo.json")
URL_METEO = "https://api.open-meteo.com/v1/forecast"
URL_GEO = "https://geocoding-api.open-meteo.com/v1/search"
CAMPI = ("temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,"
         "wind_speed_10m,is_day")

DA_IMPOSTARE = "Imposti la città nelle impostazioni."
SENZA_RETE = "Il servizio meteo non risponde. Riprovo fra qualche minuto."

# Codici WMO, come li usa Open-Meteo: descrizione e icona di giorno.
CODICI: dict[int, tuple[str, str]] = {
    0: ("sereno", "sun"),
    1: ("poco nuvoloso", "cloud-sun"),
    2: ("parzialmente nuvoloso", "cloud-sun"),
    3: ("coperto", "cloud"),
    45: ("nebbia", "cloud-fog"),
    48: ("nebbia con brina", "cloud-fog"),
    51: ("pioviggine leggera", "cloud-drizzle"),
    53: ("pioviggine", "cloud-drizzle"),
    55: ("pioviggine intensa", "cloud-drizzle"),
    56: ("pioviggine gelata", "cloud-drizzle"),
    57: ("pioviggine gelata intensa", "cloud-drizzle"),
    61: ("pioggia debole", "cloud-rain"),
    63: ("pioggia", "cloud-rain"),
    65: ("pioggia forte", "cloud-rain"),
    66: ("pioggia gelata", "cloud-rain"),
    67: ("pioggia gelata forte", "cloud-rain"),
    71: ("neve debole", "cloud-snow"),
    73: ("neve", "cloud-snow"),
    75: ("neve forte", "cloud-snow"),
    77: ("nevischio", "cloud-snow"),
    80: ("rovesci deboli", "cloud-rain"),
    81: ("rovesci", "cloud-rain"),
    82: ("rovesci violenti", "cloud-rain"),
    85: ("rovesci di neve", "cloud-snow"),
    86: ("forti rovesci di neve", "cloud-snow"),
    95: ("temporale", "cloud-lightning"),
    96: ("temporale con grandine", "cloud-lightning"),
    99: ("temporale con grandine forte", "cloud-lightning"),
}
NOTTE = {"sun": "moon", "cloud-sun": "cloud-moon"}


def descrivi(codice: int, giorno: bool = True) -> tuple[str, str]:
    """(descrizione, icona). Un codice sconosciuto non rompe il pannello."""
    descrizione, icona = CODICI.get(int(codice), ("", "cloud"))
    return descrizione, icona if giorno else NOTTE.get(icona, icona)


@dataclass(frozen=True)
class Posizione:
    citta: str
    latitudine: float
    longitudine: float


# --- configurazione ----------------------------------------------------------------

def _locale(path: Path) -> Path:
    """`gui.toml` -> `gui.local.toml`, come per la posta: derivato, cosi' i
    test che spostano la configurazione si portano dietro anche il locale."""
    return path.with_name(f"{path.stem}.local{path.suffix}")


def _sezione(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return dict(tomllib.load(f).get("meteo", {}))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def leggi_config(path: Path = CONFIG) -> dict:
    """La sezione [meteo]: quella del repository, sovrascritta dal locale."""
    cfg = {**_sezione(path), **_sezione(_locale(path))}
    citta = str(cfg.get("citta", "") or "").strip()
    try:
        lat = float(cfg["latitudine"])
        lon = float(cfg["longitudine"])
        coordinate = (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None
    except (KeyError, TypeError, ValueError):
        coordinate = None
    return {"citta": citta, "coordinate": coordinate}


# --- rete ---------------------------------------------------------------------------

def _get(url: str, params: dict):
    import httpx

    return httpx.get(url, params=params, timeout=TIMEOUT_S)


def geocodifica(citta: str, get=_get) -> Posizione | None:
    """Il nome in coordinate. None se Open-Meteo non la conosce; solleva se
    la rete non risponde (e' un'altra cosa, e si dice in un altro modo)."""
    r = get(URL_GEO, {"name": citta, "count": 1, "language": "it", "format": "json"})
    r.raise_for_status()
    risultati = r.json().get("results") or []
    if not risultati:
        return None
    primo = risultati[0]
    return Posizione(str(primo.get("name") or citta), float(primo["latitude"]),
                     float(primo["longitude"]))


def leggi(pos: Posizione, get=_get) -> dict:
    """La lettura attuale. Solleva se la rete o la risposta non vanno."""
    r = get(URL_METEO, {"latitude": pos.latitudine, "longitude": pos.longitudine,
                        "current": CAMPI, "timezone": "auto", "wind_speed_unit": "kmh"})
    r.raise_for_status()
    c = r.json()["current"]
    return {"temperatura": float(c["temperature_2m"]),
            "percepita": float(c["apparent_temperature"]),
            "umidita": int(round(float(c["relative_humidity_2m"]))),
            "vento_kmh": float(c["wind_speed_10m"]),
            "codice": int(c["weather_code"]),
            "giorno": bool(c.get("is_day", 1))}


# --- cache --------------------------------------------------------------------------

class Cache:
    """Un file JSON: {"posizione": {...}, "lettura": {...}, "quando": epoch}."""

    def __init__(self, path: Path = CACHE):
        self.path = Path(path)

    def carica(self) -> dict:
        try:
            dati = json.loads(self.path.read_text(encoding="utf-8"))
            return dati if isinstance(dati, dict) else {}
        except (OSError, ValueError):
            return {}

    def salva(self, dati: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            provvisorio = self.path.with_suffix(".tmp")
            provvisorio.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
            provvisorio.replace(self.path)
        except OSError:
            pass            # una cache che non si scrive non ferma il pannello


# --- per la vista ---------------------------------------------------------------------

def per_la_vista(stato: str, messaggio: str = "", citta: str = "",
                 lettura: dict | None = None, quando: float | None = None) -> dict:
    """Il dizionario che attraversa i thread. Solo tipi semplici."""
    d = {"stato": stato, "messaggio": messaggio, "citta": citta}
    if lettura:
        descrizione, icona = descrivi(lettura.get("codice", -1), lettura.get("giorno", True))
        d.update(lettura, descrizione=descrizione, icona=icona)
    if quando is not None:
        d["ora"] = datetime.fromtimestamp(quando).strftime("%H:%M")
    return d


# --- il worker ------------------------------------------------------------------------

class Meteo(QObject):
    """Un giro ogni 15 minuti; due dopo un fallimento. Emette, non disegna."""

    dati = Signal(dict)

    def __init__(self, config: Path = CONFIG, cache: Path = CACHE, get=_get,
                 adesso=time.time, dormi=time.sleep, parent=None):
        super().__init__(parent)
        self.config = Path(config)
        self.cache = Cache(cache)
        self.get = get
        self.adesso = adesso
        self.dormi = dormi
        self._ferma = False
        self._subito = False
        self.giri = 0

    # -- sul thread del meteo ----------------------------------------------------------

    @Slot()
    def avvia(self) -> None:
        self._mostra_cache()
        while not self._ferma:
            attesa = self.giro()
            self._aspetta(attesa)

    def giro(self) -> float:
        """Un aggiornamento. Ritorna i secondi da aspettare prima del prossimo."""
        self.giri += 1
        self._subito = False
        cfg = leggi_config(self.config)
        memoria = self.cache.carica()
        try:
            pos = self._posizione(cfg, memoria)
        except Exception:                     # noqa: BLE001
            self._senza_rete(memoria)
            return RITENTA_S
        if pos is None:
            messaggio = (f"Non trovo la città «{cfg['citta']}»." if cfg["citta"]
                         else DA_IMPOSTARE)
            self.dati.emit(per_la_vista("da_impostare", messaggio))
            return INTERVALLO_S
        try:
            lettura = leggi(pos, self.get)
        except Exception:                     # noqa: BLE001
            # Rete giu', DNS, 500, JSON diverso: per il pannello e' la stessa
            # cosa, e il dettaglio non serve a chi guarda.
            self._senza_rete(memoria, pos)
            return RITENTA_S
        quando = self.adesso()
        # `citta_chiesta` resta: senza, la geocodifica si rifarebbe a ogni giro.
        self.cache.salva({"posizione": {**asdict(pos), "citta_chiesta": cfg["citta"]},
                          "lettura": lettura, "quando": quando})
        self.dati.emit(per_la_vista("ok", citta=pos.citta, lettura=lettura, quando=quando))
        return INTERVALLO_S

    def _posizione(self, cfg: dict, memoria: dict) -> Posizione | None:
        if cfg["coordinate"] is not None:
            return Posizione(cfg["citta"], *cfg["coordinate"])
        if not cfg["citta"]:
            return None
        # Solo il nome: la geocodifica si fa una volta, e il risultato si
        # tiene nella cache finche' la citta' non cambia.
        vecchia = memoria.get("posizione") or {}
        if str(vecchia.get("citta_chiesta", "")).casefold() == cfg["citta"].casefold():
            try:
                return Posizione(vecchia["citta"], float(vecchia["latitudine"]),
                                 float(vecchia["longitudine"]))
            except (KeyError, TypeError, ValueError):
                pass
        pos = geocodifica(cfg["citta"], self.get)
        if pos is not None:
            self.cache.salva({**memoria, "posizione": {**asdict(pos),
                                                       "citta_chiesta": cfg["citta"]}})
        return pos

    def _senza_rete(self, memoria: dict, pos: Posizione | None = None) -> None:
        lettura, quando = memoria.get("lettura"), memoria.get("quando")
        citta = (pos.citta if pos else "") or (memoria.get("posizione") or {}).get("citta", "")
        if lettura and isinstance(quando, (int, float)) and self.adesso() - quando < VECCHIO_S:
            self.dati.emit(per_la_vista("vecchio", SENZA_RETE, citta, lettura, quando))
        else:
            self.dati.emit(per_la_vista("assente", SENZA_RETE, citta))

    def _mostra_cache(self) -> None:
        """All'avvio, prima di qualunque rete: l'ultima lettura, se e' recente.
        E' "ok": "aggiornato alle 14:30" e' vero anche per un dato in cache."""
        memoria = self.cache.carica()
        lettura, quando = memoria.get("lettura"), memoria.get("quando")
        if lettura and isinstance(quando, (int, float)) and self.adesso() - quando < VECCHIO_S:
            citta = (memoria.get("posizione") or {}).get("citta", "")
            self.dati.emit(per_la_vista("ok", "", citta, lettura, quando))

    def _aspetta(self, secondi: float) -> None:
        fine = self.adesso() + secondi
        while not self._ferma and not self._subito and self.adesso() < fine:
            self.dormi(PASSO_ATTESA_S)

    # -- chiamabili dal thread della GUI -------------------------------------------------

    def ricarica(self) -> None:
        """Le impostazioni sono cambiate: il giro successivo parte subito."""
        self._subito = True

    def ferma(self) -> None:
        self._ferma = True
