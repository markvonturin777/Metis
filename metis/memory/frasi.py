"""Le frasi che Metis non ha capito (PHASE4).

    "mastra in numeria"   ->  chiarimento      x4   ieri 19:04
    "chiudi la scheda"    ->  conversazione    x1   26/09 19:12

Ogni frase che non va a buon fine lascia un segno nel suo turno
(`data/logs/turns.jsonl`, chiave `non_capito` in `extra`), e il pannello della
Diagnostica le raccoglie perche' l'utente decida cosa farne: un comando nuovo,
una variante di uno esistente, una segnalazione, niente. Decide l'utente,
mai il modello: e' il principio della fase.

I SEGNALI SI SCRIVONO QUANDO ACCADONO
Il codice sa nel momento giusto che una frase non e' stata capita: quando fa
una domanda di chiarimento, quando toglie un'azione proposta senza verbo,
quando due JSON di fila non sono validi. Ricostruirlo dopo, rileggendo le
risposte nel log, vorrebbe dire indovinare. Per questo i quattro segnali
forti li scrive l'orchestratore, e qui ci sono solo i loro nomi.

COSA NON E' UNA FRASE NON CAPITA
I rifiuti di sicurezza: denylist, kill switch, parole vietate, conferma negata
o scaduta, turni contaminati dal web. Sono comportamenti corretti, e metterli
nel pannello inviterebbe a "risolverli" con un comando, cioe' ad aggirarli
(D-FRASI 2). Nessuno di loro passa da qui.

Lo strumento che non riesce, invece, si': "non trovo l'elemento", "il cursore
non e' in un campo di testo", "quella finestra non c'e' piu'". Quasi sempre
vuol dire che il router ha scelto lo strumento sbagliato, oppure che c'e' un
difetto. La prima versione li contava fra i rifiuti di sicurezza, e nella
prima seduta vera (2026-09-28) sei turni andati male su dieci non arrivavano
al pannello.
"""

from __future__ import annotations

import json
import os
import tomllib
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from metis.memory.commands import normalizza

# I quattro segnali forti (D-FRASI 1), in ordine di precedenza: se un turno
# ne ha piu' d'uno, vale il primo, che e' il piu' informativo.
CHIARIMENTO = "chiarimento"        # Metis ha chiesto di ripetere, con una domanda fissa
AZIONE_TOLTA = "azione_tolta"      # il modello aveva proposto un'azione, il codice l'ha tolta
RIPARAZIONE = "riparazione"        # tool call non valida: due JSON di fila, o rifiutata dal broker agli stadi tecnici
STRUMENTO = "strumento"            # lo strumento non e' riuscito: rifiuto suo, o eccezione
CONVERSAZIONE = "conversazione"    # la conversazione ha detto "non ho capito cosa fare"

SEGNALI = (CHIARIMENTO, AZIONE_TOLTA, RIPARAZIONE, STRUMENTO, CONVERSAZIONE)

# La frase che la persona dice quando le arriva una richiesta d'azione che
# nessuno ha eseguito. Deve coincidere con `metis/llm/prompts/metis_v1.txt`:
# un test lo verifica, perche' riformulare il prompt senza toccare qui
# spegnerebbe il segnale in silenzio.
FRASE_PERSONA = "Non ho capito cosa fare: me lo ripete?"
_NUCLEO_PERSONA = normalizza("non ho capito cosa fare")


def detta_dalla_persona(risposta: str) -> bool:
    """La conversazione ha risposto "non ho capito cosa fare"?

    Si confronta il nucleo della frase, non la frase intera: il modello a
    volte cambia la coda ("me lo ripeta?", "puo' ripetere?"), mai l'inizio.
    """
    return _NUCLEO_PERSONA in normalizza(risposta or "")


# --- il segnale debole ----------------------------------------------------------------

# La stessa frase detta di nuovo entro questi secondi, dopo una risposta a
# parole: la prima volta Metis ha risposto, ma non era quello che si voleva.
# E' l'unico indizio di un fallimento silenzioso, ed e' rumoroso: per questo
# e' debole, e non vale mai dopo uno strumento riuscito ("scorri giu'" detto
# tre volte e' un uso normale) ne' dopo una ricerca web.
RIPETUTA = "ripetuta"
FINESTRA_RIPETIZIONE_S = 30.0

# Gli strumenti che vogliono un numero, una quantita' o un testo detto. Una
# frase che li chiedeva non puo' diventare un comando, che ha azioni fisse:
# legare "ottanto uno" a un clic sull'81 sarebbe sbagliato la prima volta che
# la stessa storpiatura nomina un altro numero (D-FRASI 5). Si segnala.
CON_PARAMETRO = frozenset({"clicca_numero", "scrivi_nel_numero", "type_text",
                           "set_volume", "cambia_volume", "riproduci_youtube",
                           "open_url", "schedule_reminder", "schedule_email",
                           "send_email", "web_search"})


@dataclass(frozen=True)
class Turno:
    """Un turno di `turns.jsonl`, con quel che serve al pannello e niente di piu'."""

    ts: float
    testo: str
    motivo: str | None = None       # uno di SEGNALI, RIPETUTA, o None
    tolta: str | None = None
    strumento: str | None = None
    web: bool = False

    @property
    def chiave(self) -> str:
        return _chiave(self.testo)


# Le frasi di una persona si ripetono moltissimo ("mostra i numeri", "scorri
# giu'"), e `normalizza` e' la parte cara della lettura: su 100 000 turni era
# il 90% del tempo. Misura nel tracking di PHASE4.
_chiave = lru_cache(maxsize=4096)(normalizza)


def turno(riga: dict) -> Turno | None:
    """Da una riga del log a un `Turno`; None se la riga non serve o e' storta."""
    try:
        ts = float(riga["ts"])
    except (KeyError, TypeError, ValueError):
        return None
    testo = riga.get("transcript")
    if not isinstance(testo, str) or not testo.strip():
        return None
    extra = riga.get("extra")
    extra = extra if isinstance(extra, dict) else {}
    motivo = extra.get("non_capito")
    if motivo is None and extra.get("chiarimento") is True:
        motivo = CHIARIMENTO          # i turni di PHASE2, scritti prima di `non_capito`
    tolta = extra.get("tolta")
    strumento = extra.get("tool")
    return Turno(ts=ts, testo=testo.strip(),
                 motivo=motivo if motivo in SEGNALI else None,
                 tolta=tolta if isinstance(tolta, str) else None,
                 strumento=strumento if isinstance(strumento, str) else None,
                 web=bool(extra.get("fonti") or extra.get("untrusted")))


def segna_ripetizioni(turni: list[Turno]) -> list[Turno]:
    """Il segnale debole, sul turno che e' fallito in silenzio: il PRIMO.

    `turni` e' in ordine di tempo. Un turno riceve RIPETUTA se non ha gia' un
    segnale forte, se Metis ha risposto a parole (nessuno strumento, nessuna
    fonte web), e se il turno dopo, entro 30 s, e' la stessa frase.
    """
    fuori = list(turni)
    for i in range(len(fuori) - 1):
        a, b = fuori[i], fuori[i + 1]
        if a.motivo is None and a.strumento is None and not a.web \
                and 0 <= b.ts - a.ts <= FINESTRA_RIPETIZIONE_S and a.chiave == b.chiave:
            fuori[i] = Turno(a.ts, a.testo, RIPETUTA, a.tolta, a.strumento, a.web)
    return fuori


def parametrica(frase: str, tolta: str | None = None) -> bool:
    """La frase chiedeva un numero, una quantita' o un testo?

    Con gli stessi pezzi del percorso rapido: i numeri detti di
    `numeri_parlati`, la dettatura di `frasi_chiuse`. Nessuna seconda
    implementazione che possa divergere.
    """
    from metis.core import frasi_chiuse
    from metis.core.numeri_parlati import numeri_in

    if tolta in CON_PARAMETRO:
        return True
    if any(c.isdigit() for c in frase) or numeri_in(normalizza(frase)):
        return True
    return frasi_chiuse.dettatura(frase) is not None


# --- la lettura -----------------------------------------------------------------------

def righe_dalla_fine(path: Path, blocco: int = 1 << 16) -> Iterator[str]:
    """Le righe di un file dall'ultima alla prima, senza leggerlo tutto.

    `turns.jsonl` cresce senza limite: il pannello guarda solo gli ultimi 30
    giorni, e li trova in fondo. Una riga spezzata a meta' da una scrittura in
    corso arriva storta, e chi legge la scarta.
    """
    try:
        f = path.open("rb")
    except OSError:
        return
    with f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        resto = b""
        while pos > 0:
            passo = min(blocco, pos)
            pos -= passo
            f.seek(pos)
            pezzo = f.read(passo) + resto
            righe = pezzo.split(b"\n")
            resto = righe.pop(0)             # forse incompleta: la completa il blocco prima
            for r in reversed(righe):
                if r.strip():
                    yield r.decode("utf-8", errors="replace")
        if resto.strip():
            yield resto.decode("utf-8", errors="replace")


def leggi_turni(path: Path, dal: float) -> list[Turno]:
    """I turni da `dal` (secondi epoch) in poi, in ordine di tempo.

    Si legge dalla fine e ci si ferma al primo turno piu' vecchio del limite:
    il file e' in sola aggiunta, quindi in ordine. Righe storte saltate, file
    assente = nessun turno. Mai un'eccezione verso chi disegna.
    """
    fuori: list[Turno] = []
    for r in righe_dalla_fine(path):
        try:
            riga = json.loads(r)
        except ValueError:
            continue
        if not isinstance(riga, dict):
            continue
        ts = riga.get("ts")
        if isinstance(ts, (int, float)) and ts < dal:
            break
        t = turno(riga)
        if t is not None:
            fuori.append(t)
    fuori.reverse()
    return fuori


# --- le decisioni dell'utente ----------------------------------------------------------

IGNORATA = "ignorata"      # sparisce dal pannello, per sempre
RISOLTA = "risolta"        # diventata comando o variante: ricompare solo se fallisce DOPO
SEGNALATA = "segnalata"    # per chi sviluppa: va nell'elenco da esportare
STATI = (IGNORATA, RISOLTA, SEGNALATA)

# Letto al momento della chiamata, mai come default di un argomento: la suite
# lo sposta (`tests/conftest.py`), e un default si valuta una volta sola,
# all'import. E' il difetto trovato il giorno 0 in `metrics.LOG`.
DECISE = Path("data/frasi_decise.json")


def carica_decise(path: Path | None = None) -> dict[str, dict]:
    """{chiave normalizzata: {"stato", "quando", "frase"}}. File rotto = vuoto."""
    path = DECISE if path is None else path
    try:
        dati = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(dati, dict):
        return {}
    return {k: v for k, v in dati.items()
            if isinstance(v, dict) and v.get("stato") in STATI}


def decidi(chiave: str, stato: str, frase: str = "", path: Path | None = None,
           ora: float | None = None) -> None:
    """Registra la decisione dell'utente su una frase. Scrittura atomica: un
    file lasciato a meta' da una chiusura improvvisa non deve perdere le altre."""
    path = DECISE if path is None else path
    if stato not in STATI:
        raise ValueError(f"stato sconosciuto: {stato}")
    quando = ora if ora is not None else datetime.now().timestamp()
    decise = carica_decise(path)
    decise[chiave] = {"stato": stato, "frase": frase,
                      "quando": datetime.fromtimestamp(quando).isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(decise, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _quando(decisione: dict) -> float:
    try:
        return datetime.fromisoformat(decisione["quando"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return 0.0


# --- il raggruppamento ----------------------------------------------------------------

@dataclass
class Gruppo:
    """Una frase del pannello: tutte le volte che e' stata detta e non capita."""

    chiave: str
    frase: str                  # l'ultima forma trascritta, com'e' stata detta
    volte: int
    ultima: float
    motivo: str                 # il segnale forte piu' frequente, o RIPETUTA
    tolta: str | None           # lo strumento suggerito (D-FRASI 6), o None
    parametrica: bool

    @property
    def debole(self) -> bool:
        return self.motivo == RIPETUTA


@dataclass
class Raccolta:
    """Cosa il pannello mostra."""

    da_rivedere: list[Gruppo] = field(default_factory=list)
    segnalate: list[Gruppo] = field(default_factory=list)
    turni: int = 0              # turni letti nell'intervallo
    non_capiti: int = 0         # di cui con un segnale FORTE

    @property
    def quota(self) -> float:
        """La misura dell'attrito: la parte dei turni che Metis non ha capito.
        Solo i segnali forti: la ripetizione e' un indizio, non una misura."""
        return self.non_capiti / self.turni if self.turni else 0.0


def _gruppo(chiave: str, turni: list[Turno]) -> Gruppo:
    forti = Counter(t.motivo for t in turni if t.motivo in SEGNALI)
    # A parita' di conteggio vince l'ordine di SEGNALI, che e' la precedenza.
    motivo = (max(forti, key=lambda s: (forti[s], -SEGNALI.index(s)))
              if forti else RIPETUTA)
    ultimo = max(turni, key=lambda t: t.ts)
    tolta = next((t.tolta for t in sorted(turni, key=lambda t: -t.ts) if t.tolta), None)
    return Gruppo(chiave=chiave, frase=ultimo.testo, volte=len(turni), ultima=ultimo.ts,
                  motivo=motivo, tolta=tolta,
                  parametrica=parametrica(ultimo.testo, tolta))


def raggruppa(turni: list[Turno], decise: dict[str, dict] | None = None) -> Raccolta:
    """Dai turni (in ordine di tempo) alla raccolta del pannello.

    Le ripetizioni si segnano qui; poi si raggruppa per frase normalizzata.
    Una frase IGNORATA non torna; una RISOLTA torna solo con i fallimenti
    arrivati dopo la decisione (il comando nuovo non ha funzionato); una
    SEGNALATA va nell'elenco da esportare.
    """
    decise = decise or {}
    turni = segna_ripetizioni(turni)
    per_chiave: dict[str, list[Turno]] = {}
    for t in turni:
        if t.motivo is not None and t.chiave:
            per_chiave.setdefault(t.chiave, []).append(t)

    r = Raccolta(turni=len(turni),
                 non_capiti=sum(1 for t in turni if t.motivo in SEGNALI))
    for chiave, lista in per_chiave.items():
        d = decise.get(chiave)
        stato = d.get("stato") if d else None
        if stato == IGNORATA:
            continue
        if stato == RISOLTA:
            lista = [t for t in lista if t.ts > _quando(d)]
            if not lista:
                continue
        g = _gruppo(chiave, lista)
        (r.segnalate if stato == SEGNALATA else r.da_rivedere).append(g)

    def ordine(g: Gruppo):
        return (g.debole, -g.volte, -g.ultima)

    r.da_rivedere.sort(key=ordine)
    r.segnalate.sort(key=ordine)
    return r


# --- per chi guarda -------------------------------------------------------------------

_MOTIVI_IN_PAROLE = {
    CHIARIMENTO: "ha chiesto di ripetere",
    AZIONE_TOLTA: "azione proposta senza essere chiesta",
    RIPARAZIONE: "decisione non valida",
    STRUMENTO: "lo strumento non è riuscito",
    CONVERSAZIONE: "ha risposto «non ho capito»",
    RIPETUTA: "ripetuta subito (indizio)",
}


def motivo_in_parole(motivo: str) -> str:
    return _MOTIVI_IN_PAROLE.get(motivo, motivo)


def quando_in_parole(ts: float, ora: float | None = None) -> str:
    """ "oggi 19:04", "ieri 19:04", "26/09 19:12"."""
    t = datetime.fromtimestamp(ts)
    oggi = datetime.fromtimestamp(ora if ora is not None else datetime.now().timestamp()).date()
    giorni = (oggi - t.date()).days
    giorno = "oggi" if giorni == 0 else "ieri" if giorni == 1 else t.strftime("%d/%m")
    return f"{giorno} {t:%H:%M}"


def markdown_segnalate(gruppi: list[Gruppo], ora: float | None = None) -> str:
    """Le frasi segnalate, per chi sviluppa: sono quelle che un comando non puo'
    coprire (hanno un numero, una quantita', un testo) e vanno nelle frasi
    chiuse del codice, o nel vocabolario di Whisper."""
    quando = datetime.fromtimestamp(ora if ora is not None else datetime.now().timestamp())
    righe = ["# Metis — frasi segnalate", "",
             f"Esportate il {quando:%d/%m/%Y alle %H:%M}. Frasi che Metis non ha capito e che un",
             "comando rapido non puo' coprire: vanno nelle frasi chiuse (`metis/core/frasi_chiuse.py`)",
             "o nel vocabolario di dominio di Whisper (`config/stt.toml`).", "",
             "| Volte | Frase | Motivo | Strumento proposto | Ultima volta |",
             "| --: | :-- | :-- | :-- | :-- |"]
    for g in gruppi:
        frase = g.frase.replace("|", "\\|")
        righe.append(f"| {g.volte} | {frase} | {motivo_in_parole(g.motivo)} | "
                     f"{g.tolta or '—'} | {quando_in_parole(g.ultima, ora)} |")
    if not gruppi:
        righe.append("| — | nessuna | | | |")
    return "\n".join(righe) + "\n"


# --- l'insieme ------------------------------------------------------------------------

GIORNI = 30
CONFIG = Path("config/gui.toml")


def data_di_partenza(path: Path = CONFIG) -> float | None:
    """`[frasi] dal` di `config/gui.toml`, sovrascritto dal suo `.local`.

    Prima di quell'istante `turns.jsonl` contiene turni finti della suite dei
    test, che non si separano da quelli veri (D-FRASI 4). Assente o storta:
    None, e vale il solo limite dei 30 giorni.
    """
    valore = None
    for p in (path, path.with_name(f"{path.stem}.local{path.suffix}")):
        try:
            with p.open("rb") as f:
                sezione = tomllib.load(f).get("frasi", {})
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if isinstance(sezione, dict) and "dal" in sezione:
            valore = sezione["dal"]
    try:
        return datetime.fromisoformat(str(valore)).timestamp() if valore else None
    except ValueError:
        return None


def raccogli(log: Path | None = None, decise: Path | None = None, config: Path = CONFIG,
             ora: float | None = None, giorni: int = GIORNI) -> Raccolta:
    """Tutto quello che serve al pannello. Da chiamare FUORI dal thread della GUI."""
    if log is None:
        from metis.core import metrics
        log = metrics.LOG                 # letto adesso: la suite lo sposta
    ora = ora if ora is not None else datetime.now().timestamp()
    limite = ora - giorni * 86400
    partenza = data_di_partenza(config)
    if partenza is not None:
        limite = max(limite, partenza)
    return raggruppa(leggi_turni(log, limite), carica_decise(decise))
