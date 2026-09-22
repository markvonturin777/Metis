"""Trovare un elemento dentro un'applicazione nativa, via UI Automation.

LA REGOLA CHE GOVERNA QUESTO FILE
Nessuna ricerca approssimata. Esatto, poi per sottostringa, poi per
`AutomationId`. Se i candidati restano piu' di uno, si **rifiuta**.

Sembra una scelta timida ed e' il contrario. Un match sbagliato non lascia
tracce riconoscibili: Metis dice "fatto", il clic e' partito, e l'utente
scopre piu' tardi di aver premuto "Elimina" invece di "Elenco". Il rifiuto
invece e' immediato, spiega cosa ha trovato, e costa una frase. Il piano lo
diceva in una riga — "in caso di dubbio, rifiuto" — e qui e' la sola cosa
che tiene onesto il resto di M4.

Per lo stesso motivo non esiste un parametro con delle coordinate. Il
modello dice *cosa* premere; *dove* si trovi lo scopre l'albero di UIA.

LA PROFONDITA' E' LIMITATA, E SERVE
L'albero di UIA di un'applicazione moderna e' enorme: una finestra di
Electron ha migliaia di nodi, e visitarli tutti costa secondi. Si scende
fino a `PROFONDITA_MAX` in ampiezza, che copre le barre, i menu e il
contenuto principale; cio' che sta piu' in fondo, in pratica, non e' quello
che l'utente sta nominando a voce.

GLI ELEMENTI FUORI SCHERMO SI SCARTANO
`IsOffscreen` e' vero per le voci di un menu chiuso, per le schede non
attive, per tutto cio' che esiste nell'albero ma non e' visibile. Cliccare
al centro del loro rettangolo significa cliccare da qualche altra parte.
Scartarli non e' un filtro di comodo: e' la differenza fra "non l'ho
trovato" e "ho cliccato su qualcos'altro".
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass

from metis.tools.registry import Rifiuto

PROFONDITA_MAX = 12
NODI_MAX = 4000            # rete di sicurezza: alberi patologici
TIMEOUT_S = 2.0

# Dai nomi del `Literal` TipoElemento ai ControlType di UIA. Piu' di uno per
# voce dove Windows usa tipi diversi per la stessa cosa: un pulsante con un
# menu a tendina e' uno SplitButton, ma chi parla dice "pulsante".
TIPI = {
    "pulsante": ("ButtonControl", "SplitButtonControl"),
    "link": ("HyperlinkControl", "TextControl"),
    "casella_di_testo": ("EditControl", "DocumentControl", "ComboBoxControl"),
    "voce_di_menu": ("MenuItemControl",),
    "casella_di_spunta": ("CheckBoxControl", "RadioButtonControl"),
    "scheda": ("TabItemControl",),
    "elemento_lista": ("ListItemControl", "TreeItemControl", "DataItemControl"),
}


@dataclass(frozen=True)
class Elemento:
    nome: str
    tipo: str
    rect: tuple[int, int, int, int]

    @property
    def centro(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)


def _piatto(testo: str) -> str:
    """minuscole, senza accenti, senza scorciatoie: "&Salva" -> "salva"."""
    t = unicodedata.normalize("NFD", (testo or "").replace("&", "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


def _visita(radice, profondita: int):
    """Percorso in AMPIEZZA, non in profondita'.

    In ampiezza i primi nodi restituiti sono quelli vicini alla finestra —
    barre, pulsanti principali — che sono anche i piu' probabili. In
    profondita' si scenderebbe subito dentro il primo pannello e si
    spenderebbe il budget di nodi in un ramo solo.
    """
    livello = [(radice, 0)]
    visti = 0
    while livello and visti < NODI_MAX:
        nodo, d = livello.pop(0)
        visti += 1
        if d > 0:
            yield nodo
        if d < profondita:
            try:
                for figlio in nodo.GetChildren():
                    livello.append((figlio, d + 1))
            except Exception:                  # noqa: BLE001
                continue


def candidati(hwnd: int, nome: str, tipo: str = "qualsiasi",
              profondita: int = PROFONDITA_MAX) -> list[Elemento]:
    """Tutti gli elementi visibili il cui nome contiene quello cercato."""
    import uiautomation as auto

    cercato = _piatto(nome)
    ammessi = TIPI.get(tipo)
    t0 = time.perf_counter()
    trovati: list[Elemento] = []

    radice = auto.ControlFromHandle(hwnd)
    if radice is None:
        raise Rifiuto("non riesco a ispezionare quella finestra")

    for nodo in _visita(radice, profondita):
        if time.perf_counter() - t0 > TIMEOUT_S:
            break
        try:
            if nodo.IsOffscreen:
                continue
            etichetta = nodo.Name or ""
            if not etichetta:
                continue
            if ammessi is not None and nodo.ControlTypeName not in ammessi:
                continue
            if cercato not in _piatto(etichetta):
                continue
            r = nodo.BoundingRectangle
            if r.width() <= 0 or r.height() <= 0:
                continue
            trovati.append(Elemento(etichetta, nodo.ControlTypeName,
                                    (r.left, r.top, r.right, r.bottom)))
        except Exception:                      # noqa: BLE001
            continue
    return trovati


def scegli(trovati: list[Elemento], nome: str) -> Elemento:
    """Da un elenco di candidati a uno solo, o a un rifiuto.

    Prima gli esatti. Se e' uno solo, quello. Se sono piu' di uno — due
    pulsanti "Apri" in due pannelli diversi — non si sceglie: non c'e' modo
    di sapere quale intendesse l'utente, e il costo dell'errore e' un clic
    su una cosa sbagliata.
    """
    if not trovati:
        raise Rifiuto(f"non trovo nessun elemento che si chiami '{nome}'")

    cercato = _piatto(nome)
    esatti = [e for e in trovati if _piatto(e.nome) == cercato]
    gruppo = esatti or trovati

    if len(gruppo) == 1:
        return gruppo[0]

    etichette = ", ".join(f'"{e.nome[:40]}"' for e in gruppo[:4])
    raise Rifiuto(f"ci sono {len(gruppo)} elementi che corrispondono a "
                  f"'{nome}': {etichette}. Dimmi quale")


def trova(hwnd: int, nome: str, tipo: str = "qualsiasi") -> Elemento:
    """La funzione che usano gli strumenti. Ritorna, oppure solleva `Rifiuto`."""
    return scegli(candidati(hwnd, nome, tipo), nome)
