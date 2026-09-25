"""Testo che non deve allargare la finestra.

IL DIFETTO
Una `QLabel` con `wordWrap` va a capo solo sugli spazi. Un URL di 1500
caratteri senza spazi — un link di tracciamento di Bing, per esempio — non ha
dove andare a capo, e la larghezza minima dell'etichetta diventa la sua.
Il layout la rispetta: la colonna "adesso" si allarga, la finestra si
allarga oltre lo schermo, e la conversazione viene schiacciata a una
lettera per riga. Trovato cercando annunci di lavoro dalla control room.

TRE RIMEDI, PERCHE' NE SERVE PIU' DI UNO
    url_breve        chi guarda vuole sapere DA DOVE viene una fonte, non
                     leggerne i parametri: dominio e inizio del percorso.
                     L'URL intero resta nel tooltip.
    spezzabile       per il testo che non si controlla (la risposta del
                     modello, gli slot): uno spazio a larghezza zero ogni
                     40 caratteri nelle parole troppo lunghe, cosi' QLabel
                     trova dove andare a capo.
    elastica         l'etichetta smette di imporre la propria larghezza: la
                     decide il layout, e il testo si adatta a lei.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from PySide6.QtWidgets import QLabel, QSizePolicy

ZWSP = "​"
MAX_PAROLA = 40
MAX_URL = 70

_URL = re.compile(r"https?://\S+")
_PAROLA_LUNGA = re.compile(r"\S{%d,}" % (MAX_PAROLA + 1))


def url_breve(url: str, massimo: int = MAX_URL) -> str:
    """`https://www.bing.com/aclick?ld=e8…` -> `bing.com/aclick…`."""
    try:
        parti = urlsplit(url)
    except ValueError:
        return url[:massimo] + ("…" if len(url) > massimo else "")
    host = parti.netloc.removeprefix("www.")
    if not host:
        return url[:massimo] + ("…" if len(url) > massimo else "")
    resto = parti.path.rstrip("/")
    if parti.query:
        resto += "?" + parti.query
    breve = host + resto
    return breve if len(breve) <= massimo else breve[:massimo - 1] + "…"


def spezzabile(testo: str, ogni: int = MAX_PAROLA) -> str:
    """Le parole oltre `ogni` caratteri ricevono un punto in cui andare a capo."""
    def spezza(m: re.Match) -> str:
        p = m.group(0)
        return ZWSP.join(p[i:i + ogni] for i in range(0, len(p), ogni))
    return _PAROLA_LUNGA.sub(spezza, testo)


def per_etichetta(testo: str) -> str:
    """URL accorciati, poi il resto reso spezzabile. Per il testo libero."""
    return spezzabile(_URL.sub(lambda m: url_breve(m.group(0)), testo))


def elastica(etichetta: QLabel) -> QLabel:
    """A capo, e larghezza decisa dal layout invece che dal testo."""
    etichetta.setWordWrap(True)
    politica = etichetta.sizePolicy()
    politica.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    etichetta.setSizePolicy(politica)
    etichetta.setMinimumWidth(0)
    return etichetta
