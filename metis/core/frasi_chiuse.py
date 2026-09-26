"""Frasi chiuse con un parametro: riconosciute senza il modello (PHASE2).

    "cerca su youtube ricette di pasta"   ->  open_url(.../results?search_query=ricette+di+pasta)
    "mettimi su youtube un video relax"   ->  riproduci_youtube(query="video relax")
    "clicca il 7", "clicca sul sette"     ->  clicca_numero(numero=7)
    "mostra i numeri" / "nascondi i numeri" / "scorri giu'"

PERCHE' NON BASTANO I COMANDI RAPIDI
Un comando rapido e' una frase fissa. Queste hanno un pezzo che cambia — cosa
cercare — e il pezzo va copiato, non interpretato. Il modello da 8 miliardi,
qui, sbagliava in modo stabile: "cerca su YouTube X" diventava `web_search`
tre volte su tre, con la regola scritta nel prompt. Un'espressione regolare
non ha bisogno di regole.

LA PORTA E' STRETTA DI PROPOSITO
Ogni frase qui dentro deve contenere letteralmente la parola che la
giustifica ("youtube"). Una frase che non la contiene passa al router, che e'
li' per le formulazioni libere. Un'espressione regolare che prova a capire
l'italiano diventa un secondo modello, peggiore del primo.

CIO' CHE ESCE E' MATERIALE PER IL BROKER
Come per i comandi rapidi: la scorciatoia salta il modello, non i controlli.
Le chiamate prodotte qui attraversano validazione, policy, guardie, conferma
e audit come tutte le altre. Il `pattern` di `OpenUrl` e il limite di 120
caratteri di `RiproduciYoutube` valgono anche per loro.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote_plus

# Le parole che si tolgono ai bordi della frase prima del confronto. Sono le
# cortesie del router, meno quelle che alla fine possono appartenere a cio'
# che si cerca.
_TOLTE_IN_TESTA = frozenset({
    "per", "favore", "perfavore", "cortesemente", "gentilmente", "prego",
    "metis", "puoi", "potresti", "ok", "okay", "ehi", "hey", "ciao", "senti",
    "dai", "allora", "adesso", "ora", "subito", "e", "si",
})
_TOLTE_IN_CODA = frozenset({"per", "favore", "perfavore", "grazie", "mille",
                            "metis", "prego", "ok", "okay"})

# In testa a cio' che si cerca: "un video" -> "video".
_ARTICOLI = re.compile(
    r"^(?:(?:un po|un poco) (?:di |d )?|(?:un|una|uno|il|lo|la|l|i|gli|le|del|dello|"
    r"della|dei|degli|delle|qualche) )+")

# "apri chrome e ..." davanti non cambia la richiesta: Chrome si apre comunque.
_PRIMA = r"(?:(?:ri)?apri(?:mi)? (?:google )?(?:chrome|il browser) e (?:poi )?)?"

_CERCA = re.compile(
    rf"^{_PRIMA}(?:mi )?cerca(?:mi)? (?:su youtube (?P<a>.+)|(?P<b>.+) su youtube)$")

_METTI = re.compile(
    rf"^{_PRIMA}(?:mi )?(?:mettimi|metti|mettici|riproduci|riproducimi|"
    r"fammi sentire|fammi vedere|fammi ascoltare|fai partire|fammi partire)"
    r"(?: su)? (?:youtube (?P<a>.+)|(?P<b>.+) su youtube)$"
    r"|"
    rf"^{_PRIMA}(?:ri)?apri(?:mi)? youtube (?:su|con) (?P<c>.+)$")

MAX_QUERY = 120

# PHASE2, i numeri. "clicca il 7" non ha niente da interpretare: un verbo, un
# articolo o una preposizione, un numero. Il numero si legge con
# `numeri_parlati.numero`, che accetta cifre e parole fino a 99.
_CLICCA = re.compile(
    r"^(?:clicca(?:mi)?|click|clic|premi|seleziona|apri(?:mi)?) "
    r"(?:(?:su|sul|sullo|sulla|il|lo|la|l|al|numero|n) )*(?P<n>\w+(?: (?:e )?\w+)?)$")
_MOSTRA = re.compile(
    r"^(?:mostra(?:mi)?|fammi vedere|fai vedere|metti|visualizza|dammi|numera) "
    r"(?:i |tutti i )?numeri$")
_NASCONDI = re.compile(r"^(?:nascondi|togli|leva|chiudi|spegni) (?:i )?numeri$")
_SCORRI = re.compile(r"^scorri (?:in |verso )?(?P<v>giu|su|basso|alto)$")


def _ritaglia(parole: list[str]) -> list[str]:
    while parole and parole[0] in _TOLTE_IN_TESTA:
        parole = parole[1:]
    while parole and parole[-1] in _TOLTE_IN_CODA:
        parole = parole[:-1]
    return parole


def _cosa(m: re.Match) -> str | None:
    q = next((g for g in m.groups() if g), "") or ""
    q = _ARTICOLI.sub("", q.strip()).strip()
    if len(q) < 2 or "youtube" in q.split():
        return None
    return q[:MAX_QUERY]


def _cerca_youtube(m: re.Match) -> tuple[dict, ...] | None:
    q = _cosa(m)
    if q is None:
        return None
    return ({"tool": "open_url",
             "url": "https://www.youtube.com/results?search_query=" + quote_plus(q)},)


def _riproduci_youtube(m: re.Match) -> tuple[dict, ...] | None:
    q = _cosa(m)
    if q is None:
        return None
    return ({"tool": "riproduci_youtube", "query": q},)


def _clicca_numero(m: re.Match) -> tuple[dict, ...] | None:
    from metis.core.numeri_parlati import numero

    n = numero(m.group("n"))
    return ({"tool": "clicca_numero", "numero": n},) if n is not None else None


def _scorri(m: re.Match) -> tuple[dict, ...]:
    verso = "giu" if m.group("v") in ("giu", "basso") else "su"
    return ({"tool": "scroll", "verso": verso},)


# (espressione, costruttore). In ordine: vince la prima che produce qualcosa.
FRASI: tuple[tuple[re.Pattern, Callable[[re.Match], tuple[dict, ...] | None]], ...] = (
    (_MOSTRA, lambda m: ({"tool": "mostra_numeri"},)),
    (_NASCONDI, lambda m: ({"tool": "nascondi_numeri"},)),
    (_CLICCA, _clicca_numero),
    (_SCORRI, _scorri),
    (_CERCA, _cerca_youtube),
    (_METTI, _riproduci_youtube),
)


def riconosci(detto: str) -> tuple[dict, ...] | None:
    """Le chiamate per una frase gia' normalizzata, oppure None."""
    testo = " ".join(_ritaglia(detto.split()))
    if not testo:
        return None
    for espressione, costruisci in FRASI:
        m = espressione.match(testo)
        if m is not None:
            chiamate = costruisci(m)
            if chiamate:
                return chiamate
    return None
