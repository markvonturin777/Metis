"""PHASE1, giorni 9-10 — il meteo dell'Hub (D-UI 5).

Nessun test tocca la rete: Open-Meteo e' finto, e risponde, sbaglia o tace a
comando. Si prova quello che conta per chi lo usa: senza rete il pannello
dice l'ora del dato o una frase, mai un errore; la citta' si geocodifica una
volta; dal PC escono solo le coordinate.
"""
import json

import pytest
from PySide6.QtWidgets import QApplication

from metis.gui.workers import meteo as m


class Risposta:
    def __init__(self, dati, codice=200):
        self.dati = dati
        self.codice = codice

    def raise_for_status(self):
        if self.codice >= 400:
            raise RuntimeError(f"HTTP {self.codice}")

    def json(self):
        return self.dati


CORRENTE = {"current": {"time": "2026-09-25T20:45", "temperature_2m": 18.3,
                        "relative_humidity_2m": 70, "apparent_temperature": 17.9,
                        "weather_code": 3, "wind_speed_10m": 7.2, "is_day": 1}}
MILANO = {"results": [{"name": "Milano", "latitude": 45.46427, "longitude": 9.18951,
                       "country": "Italia"}]}


class OpenMeteoFinto:
    """Registra ogni richiesta; `giu` simula la rete assente."""

    def __init__(self, geo=MILANO, corrente=CORRENTE):
        self.geo = geo
        self.corrente = corrente
        self.giu = False
        self.richieste: list[tuple[str, dict]] = []

    def __call__(self, url, params):
        self.richieste.append((url, dict(params)))
        if self.giu:
            raise ConnectionError("rete assente")
        return Risposta(self.geo if url == m.URL_GEO else self.corrente)

    def quante(self, url):
        return sum(1 for u, _ in self.richieste if u == url)


class Orologio:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def cartella(tmp_path):
    (tmp_path / "gui.toml").write_text('[meteo]\ncitta = ""\n', encoding="utf-8")
    return tmp_path


def _locale(cartella, testo):
    (cartella / "gui.local.toml").write_text(testo, encoding="utf-8")


def _worker(cartella, rete=None, orologio=None):
    w = m.Meteo(config=cartella / "gui.toml", cache=cartella / "meteo.json",
                get=rete or OpenMeteoFinto(), adesso=orologio or Orologio(),
                dormi=lambda s: None)
    emessi = []
    w.dati.connect(emessi.append)
    return w, emessi


# --- codici e configurazione ---------------------------------------------------------

def test_ogni_codice_ha_un_icona_che_esiste(app_qt):
    from metis.gui import tema

    disponibili = tema.icone_disponibili()
    for codice in m.CODICI:
        for giorno in (True, False):
            descrizione, icona = m.descrivi(codice, giorno)
            assert descrizione and icona in disponibili, (codice, icona)


def test_di_notte_il_sole_diventa_luna():
    assert m.descrivi(0, giorno=False) == ("sereno", "moon")
    assert m.descrivi(2, giorno=False)[1] == "cloud-moon"
    assert m.descrivi(63, giorno=False)[1] == "cloud-rain"


def test_un_codice_sconosciuto_non_rompe_niente():
    assert m.descrivi(42) == ("", "cloud")


def test_il_locale_sostituisce_il_repository(cartella):
    assert m.leggi_config(cartella / "gui.toml") == {"citta": "", "coordinate": None}
    _locale(cartella, '[meteo]\ncitta = "Torino"\nlatitudine = 45.07\nlongitudine = 7.69\n')
    assert m.leggi_config(cartella / "gui.toml") == {"citta": "Torino",
                                                     "coordinate": (45.07, 7.69)}


@pytest.mark.parametrize("righe", [
    'latitudine = "boh"\nlongitudine = 9',
    "latitudine = 145.0\nlongitudine = 9.0",
    "latitudine = 45.0",
])
def test_coordinate_sbagliate_si_ignorano(cartella, righe):
    _locale(cartella, f'[meteo]\ncitta = "Milano"\n{righe}\n')
    assert m.leggi_config(cartella / "gui.toml") == {"citta": "Milano", "coordinate": None}


def test_un_file_illeggibile_vale_come_assente(cartella):
    _locale(cartella, "[meteo\ncitta = ")
    assert m.leggi_config(cartella / "gui.toml")["citta"] == ""


# --- rete ---------------------------------------------------------------------------------

def test_geocodifica():
    pos = m.geocodifica("milano", OpenMeteoFinto())
    assert pos == m.Posizione("Milano", 45.46427, 9.18951)
    assert m.geocodifica("xyzzy", OpenMeteoFinto(geo={"generationtime_ms": 0.1})) is None


def test_la_lettura_si_traduce():
    pos = m.Posizione("Milano", 45.46, 9.19)
    assert m.leggi(pos, OpenMeteoFinto()) == {
        "temperatura": 18.3, "percepita": 17.9, "umidita": 70, "vento_kmh": 7.2,
        "codice": 3, "giorno": True}


def test_una_risposta_diversa_solleva_invece_di_inventare():
    with pytest.raises(KeyError):
        m.leggi(m.Posizione("x", 1, 2), OpenMeteoFinto(corrente={"errore": True}))


def test_dal_pc_escono_solo_le_coordinate(cartella):
    """La citta' va una volta alla geocodifica; alle previsioni, solo
    latitudine e longitudine. Nessun altro indirizzo."""
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    rete = OpenMeteoFinto()
    w, _ = _worker(cartella, rete)
    w.giro()
    w.giro()
    assert {u for u, _ in rete.richieste} == {m.URL_GEO, m.URL_METEO}
    assert all(u.startswith("https://") for u, _ in rete.richieste)
    for url, params in rete.richieste:
        if url == m.URL_METEO:
            assert set(params) == {"latitude", "longitude", "current", "timezone",
                                   "wind_speed_unit"}
            assert "Milano" not in json.dumps(params)


# --- il worker ------------------------------------------------------------------------------

def test_senza_citta_lo_dice_e_non_chiama_la_rete(cartella):
    rete = OpenMeteoFinto()
    w, emessi = _worker(cartella, rete)
    assert w.giro() == m.INTERVALLO_S
    assert emessi == [{"stato": "da_impostare", "messaggio": m.DA_IMPOSTARE, "citta": ""}]
    assert rete.richieste == []


def test_una_citta_che_non_esiste(cartella):
    _locale(cartella, '[meteo]\ncitta = "Xyzzy"\n')
    w, emessi = _worker(cartella, OpenMeteoFinto(geo={}))
    w.giro()
    assert emessi[-1]["stato"] == "da_impostare"
    assert "Xyzzy" in emessi[-1]["messaggio"]


def test_con_le_coordinate_non_si_geocodifica(cartella):
    _locale(cartella, '[meteo]\ncitta = "Casa"\nlatitudine = 45.0\nlongitudine = 9.0\n')
    rete = OpenMeteoFinto()
    w, emessi = _worker(cartella, rete)
    w.giro()
    assert rete.quante(m.URL_GEO) == 0
    assert emessi[-1]["citta"] == "Casa" and emessi[-1]["stato"] == "ok"


def test_un_giro_riuscito(cartella):
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    orologio = Orologio()
    w, emessi = _worker(cartella, orologio=orologio)
    assert w.giro() == m.INTERVALLO_S
    d = emessi[-1]
    assert d["stato"] == "ok" and d["citta"] == "Milano"
    assert d["temperatura"] == 18.3 and d["descrizione"] == "coperto" and d["icona"] == "cloud"
    assert d["ora"] and len(d["ora"]) == 5
    salvato = json.loads((cartella / "meteo.json").read_text(encoding="utf-8"))
    assert salvato["quando"] == orologio.t and salvato["lettura"]["codice"] == 3


def test_la_citta_si_geocodifica_una_volta_sola(cartella):
    """Anche fra un riavvio e l'altro: le coordinate trovate stanno in cache."""
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    rete = OpenMeteoFinto()
    for _ in range(2):                      # due avvii, due giri ciascuno
        w, _ = _worker(cartella, rete)
        w.giro()
        w.giro()
    assert rete.quante(m.URL_GEO) == 1 and rete.quante(m.URL_METEO) == 4


def test_cambiata_la_citta_si_geocodifica_di_nuovo(cartella):
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    rete = OpenMeteoFinto()
    w, _ = _worker(cartella, rete)
    w.giro()
    _locale(cartella, '[meteo]\ncitta = "Torino"\n')
    w.giro()
    assert rete.quante(m.URL_GEO) == 2


def test_senza_rete_il_dato_recente_resta_con_la_sua_ora(cartella):
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    rete, orologio = OpenMeteoFinto(), Orologio()
    w, emessi = _worker(cartella, rete, orologio)
    w.giro()
    ora_del_dato = emessi[-1]["ora"]
    rete.giu = True
    orologio.t += 2 * 3600
    assert w.giro() == m.RITENTA_S
    d = emessi[-1]
    assert d["stato"] == "vecchio" and d["temperatura"] == 18.3
    assert d["ora"] == ora_del_dato and d["messaggio"] == m.SENZA_RETE


def test_senza_rete_un_dato_troppo_vecchio_non_si_mostra(cartella):
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    rete, orologio = OpenMeteoFinto(), Orologio()
    w, emessi = _worker(cartella, rete, orologio)
    w.giro()
    rete.giu = True
    orologio.t += 4 * 3600
    w.giro()
    assert emessi[-1]["stato"] == "assente" and "temperatura" not in emessi[-1]
    assert emessi[-1]["messaggio"] == m.SENZA_RETE


def test_senza_rete_e_senza_nessun_dato(cartella):
    """Anche la geocodifica ha bisogno della rete: al primo avvio senza
    connessione fallisce quella, e il pannello dice la stessa frase."""
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    rete = OpenMeteoFinto()
    rete.giu = True
    w, emessi = _worker(cartella, rete)
    assert w.giro() == m.RITENTA_S
    assert emessi == [{"stato": "assente", "messaggio": m.SENZA_RETE, "citta": ""}]


@pytest.mark.parametrize("guasto", [ValueError("json"), KeyError("current"),
                                    RuntimeError("HTTP 500"), TimeoutError()])
def test_nessun_guasto_esce_dal_worker(cartella, guasto):
    _locale(cartella, '[meteo]\ncitta = "Casa"\nlatitudine = 45.0\nlongitudine = 9.0\n')

    def rotta(url, params):
        raise guasto
    w, emessi = _worker(cartella, rotta)
    w.giro()
    assert emessi[-1]["stato"] == "assente"


def test_all_avvio_si_mostra_subito_la_cache(cartella):
    """Prima di qualunque rete: chi apre l'Hub vede il dato dell'ultima volta."""
    _locale(cartella, '[meteo]\ncitta = "Milano"\n')
    orologio = Orologio()
    w, _ = _worker(cartella, orologio=orologio)
    w.giro()
    orologio.t += 600
    rete = OpenMeteoFinto()
    w2, emessi = _worker(cartella, rete, orologio)
    w2._mostra_cache()
    assert emessi[0]["stato"] == "ok" and emessi[0]["temperatura"] == 18.3
    assert rete.richieste == []


def test_una_cache_rovinata_si_ignora(cartella):
    (cartella / "meteo.json").write_text("{non json", encoding="utf-8")
    w, emessi = _worker(cartella)
    w._mostra_cache()
    assert emessi == []
    w.giro()                                # e il giro va avanti
    assert emessi[-1]["stato"] == "da_impostare"


def test_ferma_esce_dall_attesa(cartella):
    w, _ = _worker(cartella)
    passi = []

    def dormi(s):
        passi.append(s)
        if len(passi) == 3:
            w.ferma()
    w.dormi = dormi
    w.adesso = Orologio()
    w.avvia()                               # ritorna: altrimenti il test non finisce
    assert w.giri == 1 and len(passi) == 3


def test_ricarica_fa_partire_subito_il_giro(cartella):
    w, _ = _worker(cartella)
    passi = []

    def dormi(s):
        passi.append(s)
        if len(passi) == 2:
            w.ricarica()
        if len(passi) == 5:
            w.ferma()
    w.dormi = dormi
    w.avvia()
    assert w.giri == 2


# --- il pannello e l'Hub ------------------------------------------------------------------

@pytest.fixture
def pannello(app_qt):
    from metis.gui.widgets.meteo import PannelloMeteo

    p = PannelloMeteo()
    yield p
    p.deleteLater()


OK = m.per_la_vista("ok", citta="Milano", quando=1_800_000_000.0,
                    lettura={"temperatura": 18.3, "percepita": 17.9, "umidita": 70,
                             "vento_kmh": 7.2, "codice": 61, "giorno": True})


def test_il_pannello_mostra_i_dati(pannello):
    pannello.aggiorna(OK)
    assert not pannello.box_dati.isHidden() and pannello.box_avviso.isHidden()
    assert pannello.temperatura.text() == "18,3°C"
    assert pannello.descrizione.text() == "Pioggia debole"
    assert pannello.icona_nome == "cloud-rain"
    assert pannello.umidita.valore.text() == "70%"
    assert pannello.vento.valore.text() == "7 km/h"
    assert pannello.percepita.valore.text() == "17,9°C"
    assert pannello.piede.text() == f"aggiornato alle {OK['ora']}"
    assert pannello.breve() == "18°  Milano"


def test_il_dato_vecchio_dice_di_quando_e(pannello):
    pannello.aggiorna({**OK, "stato": "vecchio", "messaggio": m.SENZA_RETE})
    assert pannello.piede.text() == f"dato delle {OK['ora']} · la rete non risponde"
    assert pannello.temperatura.text() == "18,3°C"


@pytest.mark.parametrize("stato,messaggio", [("assente", m.SENZA_RETE),
                                             ("da_impostare", m.DA_IMPOSTARE)])
def test_senza_dati_una_frase_al_posto_dei_numeri(pannello, stato, messaggio):
    pannello.aggiorna(OK)
    pannello.aggiorna(m.per_la_vista(stato, messaggio))
    assert pannello.box_dati.isHidden() and not pannello.box_avviso.isHidden()
    assert pannello.avviso.text() == messaggio
    assert pannello.breve() == ""


def test_l_intestazione_segue_il_pannello(app_qt):
    from metis.gui.hub_view import HubView
    from metis.gui.modello_conversazione import ModelloConversazione

    h = HubView(ModelloConversazione())
    try:
        assert h.meteo_breve.isHidden()
        h.imposta_meteo(OK)
        assert h.meteo_breve.text() == "18°  Milano" and not h.meteo_breve.isHidden()
        h.imposta_meteo(m.per_la_vista("assente", m.SENZA_RETE))
        assert h.meteo_breve.isHidden() and h.meteo_icona.isHidden()
    finally:
        h.deleteLater()


def test_il_meteo_arriva_all_hub(crea_applicazione):
    a = crea_applicazione()
    a.worker_meteo.dati.emit(OK)
    for _ in range(5):
        QApplication.processEvents()
    assert a.hub.meteo.stato == "ok" and a.hub.meteo_breve.text() == "18°  Milano"
    assert a.thread_meteo.objectName() == "metis-meteo"
