"""I comandi custom: frasi dell'utente legate a sequenze di azioni.

    "inizia a lavorare"  ->  apri VS Code, apri GitHub Desktop
                         ->  "Ambiente di sviluppo pronto."

LE AZIONI SONO TOOL CALL, NON SCRIPT
E' la regola piu' importante del file e vale la pena dire cosa esclude. Un
comando custom NON puo' contenere una riga di shell, un percorso, un pezzo
di Python. Contiene gli stessi oggetti che produce il modello, e ognuno di
essi attraversa il broker per intero: schema, policy, guardie, conferma,
audit. Un comando custom e' quindi una scorciatoia sul *decidere*, mai sul
*permettere* — esattamente come il fast-path.

Se fosse altrimenti, questo file sarebbe il modo piu' comodo per aggirare
tutto M2: un JSON modificabile a mano che esegue cose. Cosi' com'e', il
peggio che ci si puo' scrivere dentro e' una sequenza di azioni che Metis
sapeva gia' fare.

LA VALIDAZIONE AVVIENE AL SALVATAGGIO, NON ALL'USO
Un comando che invoca uno strumento inesistente, o che gli passa un campo
sbagliato, fallirebbe la prima volta che lo si pronuncia — cioe' magari fra
tre settimane, a voce, mentre serve. `valida()` lo rifiuta subito, con il
messaggio di Pydantic, e l'editor in GUI non lascia salvare.

Il caricamento invece e' TOLLERANTE: un comando rotto viene scartato con un
avviso e gli altri restano. Un file di comandi che impedisce l'avvio di
Metis per una virgola sarebbe un pessimo affare.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

PERCORSO = Path("config/commands.json")

_PUNTEGGIATURA = re.compile(r"[^\w\s]", re.UNICODE)
_SPAZI = re.compile(r"\s+")

MAX_AZIONI = 6          # un comando, non un programma


def normalizza(testo: str) -> str:
    """minuscole, senza accenti, senza punteggiatura, spazi compattati.

    E' la forma su cui si confrontano le frasi. Vive qui, e non nel router,
    perche' la usano entrambi e perche' l'editor deve poter avvisare che due
    comandi diversi si attivano con la stessa frase — cosa che si vede solo
    dopo la normalizzazione.
    """
    t = unicodedata.normalize("NFD", testo.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return _SPAZI.sub(" ", _PUNTEGGIATURA.sub(" ", t)).strip()


class Errore(ValueError):
    """Il comando non si puo' salvare. Il messaggio e' per l'utente."""


@dataclass(frozen=True)
class Comando:
    id: str
    frasi: tuple[str, ...]
    azioni: tuple[dict, ...]
    risposta: str | None = None
    normalizzate: tuple[str, ...] = field(default=(), compare=False)

    @property
    def strumenti(self) -> tuple[str, ...]:
        return tuple(a.get("tool", "?") for a in self.azioni)

    def come_dizionario(self) -> dict:
        d = {"id": self.id, "frasi": list(self.frasi),
             "azioni": [dict(a) for a in self.azioni]}
        if self.risposta:
            d["risposta"] = self.risposta
        return d


def _con_normalizzate(c: Comando) -> Comando:
    return Comando(c.id, c.frasi, c.azioni, c.risposta,
                   tuple(normalizza(f) for f in c.frasi))


# --- validazione -------------------------------------------------------------

def valida(dato: dict, registry) -> Comando:
    """Da JSON grezzo a comando, oppure `Errore` con scritto cosa manca.

    Il registro e' un parametro e non un import globale perche' e' cio' che
    rende questo controllo verificabile: nei test si passa un registro con
    strumenti finti, e si puo' descrivere il caso "strumento inesistente"
    senza inventarne uno nel perimetro vero.
    """
    if not isinstance(dato, dict):
        raise Errore("un comando deve essere un oggetto JSON")

    ident = str(dato.get("id") or "").strip()
    if not ident:
        raise Errore("manca l'identificativo del comando")

    frasi = [str(f).strip() for f in dato.get("frasi") or [] if str(f).strip()]
    if not frasi:
        raise Errore(f"'{ident}': serve almeno una frase che lo attivi")
    vuote = [f for f in frasi if not normalizza(f)]
    if vuote:
        raise Errore(f"'{ident}': una frase si riduce a niente una volta "
                     f"tolta la punteggiatura: {vuote[0]!r}")

    azioni = dato.get("azioni") or []
    if not isinstance(azioni, list) or not azioni:
        raise Errore(f"'{ident}': serve almeno un'azione")
    if len(azioni) > MAX_AZIONI:
        raise Errore(f"'{ident}': {len(azioni)} azioni sono troppe "
                     f"(il massimo e' {MAX_AZIONI})")

    pulite: list[dict] = []
    for i, azione in enumerate(azioni, 1):
        if not isinstance(azione, dict):
            raise Errore(f"'{ident}': l'azione {i} non e' un oggetto")
        nome = azione.get("tool")
        spec = registry.get(nome) if isinstance(nome, str) else None
        if spec is None:
            raise Errore(f"'{ident}': l'azione {i} invoca uno strumento che "
                         f"non esiste: {nome!r}")
        if not spec.implemented:
            raise Errore(f"'{ident}': l'azione {i} usa '{nome}', che e' "
                         "registrato ma non ha ancora un corpo")
        try:
            # Lo stesso schema che usera' il broker. Validare con un altro
            # significherebbe poter salvare qualcosa che poi viene rifiutato.
            pulite.append(spec.schema.model_validate(azione).model_dump())
        except Exception as exc:                 # noqa: BLE001
            raise Errore(f"'{ident}': argomenti non validi per '{nome}': "
                         f"{_breve(exc)}") from exc

    risposta = str(dato.get("risposta") or "").strip() or None
    return _con_normalizzate(Comando(ident, tuple(frasi), tuple(pulite), risposta))


def _breve(exc: Exception) -> str:
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return str(exc)[:160]
    pezzi = []
    for err in exc.errors()[:3]:
        campo = ".".join(str(x) for x in err["loc"]) or "(radice)"
        pezzi.append(f"{campo}: {err['msg']}")
    return "; ".join(pezzi)


# --- persistenza -------------------------------------------------------------

def carica(registry, percorso: Path = PERCORSO) -> tuple[list[Comando], list[str]]:
    """Comandi validi e avvisi su quelli scartati. Non solleva mai.

    Un file rotto non deve impedire a Metis di partire: si perde il comando,
    non l'assistente. Gli avvisi risalgono fino alla GUI, che li mostra
    accanto all'elenco.
    """
    if not percorso.exists():
        return [], []
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [], [f"{percorso}: non si legge ({exc})"]

    fuori: list[Comando] = []
    avvisi: list[str] = []
    visti: dict[str, str] = {}
    for grezzo in dati.get("comandi", []):
        try:
            c = valida(grezzo, registry)
        except Errore as exc:
            avvisi.append(str(exc))
            continue
        if any(x.id == c.id for x in fuori):
            avvisi.append(f"'{c.id}': identificativo ripetuto, scartato")
            continue
        for f in c.normalizzate:
            if f in visti:
                avvisi.append(f"la frase '{f}' attiva sia '{visti[f]}' sia "
                              f"'{c.id}': vincera' il primo")
            else:
                visti[f] = c.id
        fuori.append(c)
    return fuori, avvisi


def salva(comandi: list[Comando], percorso: Path = PERCORSO,
          nota: list[str] | None = None) -> None:
    """Riscrive il file intero. La scrittura e' atomica.

    Atomica perche' questo file viene riscritto dalla GUI mentre Metis e'
    in funzione, e un troncamento a meta' salvataggio lascerebbe l'utente
    senza nessun comando e senza capire perche'.
    """
    corpo = {"comandi": [c.come_dizionario() for c in comandi]}
    if nota:
        corpo = {"_nota": nota, **corpo}
    testo = json.dumps(corpo, ensure_ascii=False, indent=2)
    tmp = percorso.with_suffix(percorso.suffix + ".tmp")
    tmp.write_text(testo + "\n", encoding="utf-8")
    tmp.replace(percorso)


# --- la libreria viva --------------------------------------------------------

class Libreria:
    """I comandi in memoria, con ricarica a caldo.

    Il router legge da qui a ogni frase invece di tenersi una copia. Costa
    un accesso a un attributo e regala la ricarica a caldo: quando l'editor
    salva, chi sta parlando con Metis usa gia' i comandi nuovi, senza
    riavviare e senza che nessuno debba propagare niente.
    """

    def __init__(self, registry, percorso: Path = PERCORSO):
        self.registry = registry
        self.percorso = percorso
        self.comandi: list[Comando] = []
        self.avvisi: list[str] = []
        self.ricariche = 0
        self.ricarica()

    def ricarica(self) -> list[str]:
        self.comandi, self.avvisi = carica(self.registry, self.percorso)
        self.ricariche += 1
        return self.avvisi

    # -- modifiche ---------------------------------------------------------

    def _scrivi(self, comandi: list[Comando]) -> None:
        salva(comandi, self.percorso, nota=_NOTA)
        self.ricarica()

    def aggiungi(self, dato: dict) -> Comando:
        c = valida(dato, self.registry)          # solleva Errore se non va
        if any(x.id == c.id for x in self.comandi):
            raise Errore(f"esiste gia' un comando con id '{c.id}'")
        self._scrivi([*self.comandi, c])
        return c

    def modifica(self, ident: str, dato: dict) -> Comando:
        if not any(x.id == ident for x in self.comandi):
            raise Errore(f"non esiste nessun comando con id '{ident}'")
        c = valida(dato, self.registry)
        self._scrivi([c if x.id == ident else x for x in self.comandi])
        return c

    def elimina(self, ident: str) -> None:
        restanti = [x for x in self.comandi if x.id != ident]
        if len(restanti) == len(self.comandi):
            raise Errore(f"non esiste nessun comando con id '{ident}'")
        self._scrivi(restanti)

    # -- lettura -----------------------------------------------------------

    def get(self, ident: str) -> Comando | None:
        return next((c for c in self.comandi if c.id == ident), None)

    def __len__(self) -> int:
        return len(self.comandi)

    def __iter__(self):
        return iter(self.comandi)


_NOTA = [
    "Comandi rapidi: frasi che non passano dall'LLM. 5-30 ms invece di 400+.",
    "Le azioni attraversano comunque TUTTO il broker: validazione, policy,",
    "guardie, conferma, audit. La scorciatoia salta il modello, non i",
    "controlli.",
    "",
    "Le frasi si confrontano normalizzate: minuscole, senza accenti e senza",
    "punteggiatura. 'Apri VS Code!' e 'apri vs code' sono la stessa cosa.",
    "",
    "Questo file lo riscrive l'editor della GUI: i commenti fuori da _nota",
    "andrebbero persi al primo salvataggio.",
]
