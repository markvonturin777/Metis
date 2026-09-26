"""T1 — un video di YouTube da una frase sola (PHASE2, livello B).

    "mettimi su YouTube un video rilassante"
        -> riproduci_youtube(query="video rilassante")
        -> primo risultato: un id di 11 caratteri
        -> Chrome su https://www.youtube.com/watch?v=<id>

DAL WEB ESCE UN ID, NIENT'ALTRO
Il testo di una pagina di risultati e' scritto da sconosciuti come quello di
qualunque altra pagina. Qui se ne tiene una cosa sola: l'id del video, che
passa da un'espressione regolare (`ID`) e con cui l'indirizzo si ricostruisce
da zero. Un link che non e' un video di YouTube non diventa un id, e quindi
non si apre: nemmeno un risultato ostile puo' mandare Chrome altrove.

Il titolo si legge, ma va solo nell'Hub, come riga di sistema (`per_hub`).
Non entra nella frase pronunciata, ne' negli slot, ne' nella memoria: il
modello non lo vede mai, ed e' per questo che il turno non diventa
"contaminato" come quello di una ricerca (M5).

DUE MOTORI, IN QUEST'ORDINE
La pagina dei risultati di YouTube stessa: e' la classifica che vedrebbe
l'utente cercando a mano, e non ha il limite di frequenza di DuckDuckGo. Se
YouTube risponde con la pagina del consenso o cambia forma, la ricerca video
di ddgs. Entrambi misurati il 2026-09-26: circa un secondo.

LIMITE DICHIARATO
Il video lo sceglie il motore, non Metis. E se Chrome non lo fa partire da
solo dipende dalla sua politica sulla riproduzione automatica con l'audio:
si dice "ho aperto", non "sta suonando".
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from metis.llm.schemas import RiproduciYoutube
from metis.security.audit import Tier
from metis.tools.apps import apri_nel_browser
from metis.tools.registry import REGISTRY, Rifiuto

ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_VIDEO = "https://www.youtube.com/watch?v={}"
TIMEOUT_S = 5.0
MAX_TITOLO = 100

# Da un link a un id. Solo le tre forme di un video: youtube.com/watch,
# m.youtube.com/watch, youtu.be. Le playlist, i canali, gli short e tutto il
# resto non corrispondono e si scartano.
_DA_LINK = re.compile(
    r"^https?://(?:(?:www\.|m\.)?youtube\.com/watch\?(?:[^#\s]*&)?v=|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?:[&?#][^\s]*)?$")

# Nella pagina dei risultati, i video veri sono `videoRenderer`. Gli annunci
# hanno altri nomi (`adSlotRenderer`, `promotedVideoRenderer`) e non
# corrispondono.
_RENDERER = re.compile(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"')
_TITOLO = re.compile(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.){0,400})"')

_INTESTAZIONI = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/154.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
}
# Senza, dall'Italia YouTube risponde con la pagina del consenso ai cookie.
_CONSENSO = {"SOCS": "CAI"}


@dataclass(frozen=True)
class Video:
    id: str
    titolo: str = ""

    @property
    def url(self) -> str:
        return URL_VIDEO.format(self.id)


def id_da_link(link: str) -> str | None:
    m = _DA_LINK.match((link or "").strip())
    return m.group(1) if m else None


def _pulisci_titolo(t: str) -> str:
    """Una riga di testo semplice, corta. Resta dato: va solo all'Hub."""
    t = "".join(c for c in (t or "") if c.isprintable())
    t = " ".join(t.split())
    return t[:MAX_TITOLO]


# --- motori ------------------------------------------------------------------

def da_youtube(query: str) -> list[Video]:
    import httpx

    r = httpx.get("https://www.youtube.com/results",
                  params={"search_query": query, "hl": "it"},
                  headers=_INTESTAZIONI, cookies=_CONSENSO,
                  timeout=TIMEOUT_S, follow_redirects=True)
    if r.status_code != 200 or r.url.host != "www.youtube.com":
        # La pagina del consenso sta su consent.youtube.com: non e' un
        # errore da mostrare, e' un motore che stavolta non serve.
        return []
    return da_pagina(r.text)


def da_pagina(html: str) -> list[Video]:
    """I video della pagina dei risultati, in ordine. Separata per i test."""
    fuori: list[Video] = []
    for m in _RENDERER.finditer(html):
        titolo = ""
        t = _TITOLO.search(html, m.end(), m.end() + 4000)
        if t:
            try:
                titolo = json.loads(f'"{t.group(1)}"')
            except ValueError:
                titolo = ""
        fuori.append(Video(m.group(1), _pulisci_titolo(titolo)))
    return fuori


def da_ddgs(query: str) -> list[Video]:
    from ddgs import DDGS

    grezzi = DDGS().videos(query, region="it-it", max_results=5) or []
    fuori = []
    for g in grezzi:
        vid = id_da_link(g.get("content") or "")
        if vid:
            fuori.append(Video(vid, _pulisci_titolo(g.get("title") or "")))
    return fuori


MOTORI: tuple[Callable[[str], list[Video]], ...] = (da_youtube, da_ddgs)


def primo_video(query: str,
                motori: tuple[Callable[[str], list[Video]], ...] | None = None) -> Video:
    """Il primo video valido fra i risultati del primo motore che ne ha.

    Un motore che esplode e' un motore che stavolta non c'e': si passa al
    successivo. Solo se nessuno trova niente si rifiuta, dicendolo.
    """
    for motore in (MOTORI if motori is None else motori):
        try:
            candidati = motore(query)
        except Exception:                          # noqa: BLE001
            continue
        for v in candidati:
            # Anche un id che arriva gia' "pulito" dal motore si riverifica:
            # la regola e' una, e vale nel punto in cui si apre.
            if isinstance(v, Video) and ID.match(v.id):
                return v
    raise Rifiuto("non ho trovato un video su YouTube per questa ricerca")


@REGISTRY.strumento(Tier.T1, RiproduciYoutube)
def _riproduci_youtube(call: RiproduciYoutube) -> dict:
    """Apre su YouTube il primo video per una ricerca."""
    v = primo_video(call.query)
    pid = apri_nel_browser(v.url)
    return {"query": call.query, "url": v.url, "pid": pid,
            # Solo per l'Hub: vedi la nota in testa al modulo.
            "per_hub": f"YouTube: {v.titolo}" if v.titolo else "YouTube: video aperto"}
