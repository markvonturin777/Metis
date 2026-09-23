"""Promemoria ed email programmate. Il primo stato di Metis che sopravvive al
riavvio.

IL REQUISITO CHE DETERMINA TUTTO
Un promemoria per domani alle 17 non serve se il PC si riavvia stasera e lo
dimentica. Il jobstore predefinito di APScheduler vive in memoria, quindi
questo modulo esiste soprattutto per una riga: `SQLAlchemyJobStore` su
`data/jobs.db`. E per una seconda:

    misfire_grace_time = 3600   PC spento all'ora prevista, riacceso entro
                                un'ora: il promemoria scatta alla riaccensione
    coalesce = True             un recupero solo, non uno per ogni occorrenza
                                persa mentre il PC era spento

Senza la prima, il job scade in silenzio. E' il difetto che si scopre solo
quando serviva.

M6 — OLTRE L'ORA, IL PIANO LO PERDEVA LO STESSO (misurato)
Con `misfire_grace_time = 3600`, un promemoria scaduto da DUE ore quando il
PC si riaccende viene scartato da APScheduler con una riga di log e nient'
altro. E' il rischio che il piano nomina — "scadono silenziosamente" —
spostato un'ora piu' in la'. Un'email delle 9, PC acceso alle 11: sparita.

Qui la tolleranza passa a `None` — APScheduler non scarta mai — e l'ora di
grazia diventa la soglia fra IN ORARIO e IN RITARDO, decisa da `_scatta`:

    promemoria in ritardo   arriva lo stesso, dicendo per quando era
    email in ritardo        NON parte: l'utente ha confermato l'invio alle
                            9, non alle 14. Lo si dice, e decide lui

`GRAZIA_S` resta 3600 perche' e' ancora il numero del piano: cambia cosa
succede oltre, non dove sta il confine.

I JOB NON CONOSCONO METIS
Un job persistito e' un riferimento testuale a una funzione —
`metis.tools.scheduler:_scatta` — piu' argomenti che si possono serializzare.
Non puo' contenere il TTS, la GUI o il broker: fra la programmazione e
l'esecuzione c'e' magari un riavvio, e quegli oggetti non esistono piu'.

Quando scatta, `_scatta` consegna il lavoro a chi si e' registrato con
`imposta_consegna()`: l'applicazione, al suo avvio. Se scatta prima che
l'applicazione abbia finito di caricare i modelli — succede proprio con i
promemoria recuperati dopo un riavvio — il lavoro aspetta in coda e parte
alla registrazione. Per questo lo scheduler si avvia DOPO le consegne.

LE EMAIL PROGRAMMATE SONO CONFERMATE ALLA CREAZIONE
E' una decisione del piano: chiedere conferma alle 9 di domani presuppone che
l'utente sia li' alle 9, e allora la schedulazione non serviva. Il broker
chiede conferma quando la richiesta nasce, con destinatario, oggetto, corpo
intero e orario; all'invio `posta.invia` ricontrolla l'allowlist, cosi' un
indirizzo tolto dal file blocca anche le email gia' in coda.

I PROMEMORIA SI CANCELLANO PER TESTO, NON PER ID
Stessa scelta delle finestre in M4, stessa ragione: un id inventato potrebbe
esistere, un pezzo di testo inventato no. Due corrispondenze: rifiuto.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from metis.core import tempo
from metis.llm.schemas import (
    CancelReminder,
    ListReminders,
    ScheduleEmail,
    ScheduleReminder,
)
from metis.security.audit import Tier
from metis.security.guards import Guard
from metis.tools.registry import REGISTRY, Rifiuto

DB = Path("data/jobs.db")
GRAZIA_S = 3600

FUNZIONE = "metis.tools.scheduler:_scatta"

# Tipi di job. "spegni" e' il limite di sicurezza dei dispositivi di casa:
# non compare nell'elenco e non si cancella a voce — togliere un limite di
# sicurezza con uno strumento T1 sarebbe un modo di spegnere una guardia
# parlando.
PROMEMORIA, EMAIL, SPEGNI = "promemoria", "email", "spegni"
VISIBILI = (PROMEMORIA, EMAIL)


@dataclass(frozen=True)
class Voce:
    id: str
    tipo: str
    testo: str
    quando: datetime

    def come_dizionario(self, rif: datetime | None = None) -> dict:
        return {"id": self.id, "tipo": self.tipo, "testo": self.testo,
                "quando": self.quando.strftime(tempo.FORMATO),
                "in_parole": tempo.in_parole(self.quando, rif)}


# --- consegna: il ponte fra il job persistito e l'applicazione viva ----------

_consegne: dict[str, Callable[[dict], None]] = {}
_in_attesa: list[tuple[str, dict]] = []
_lock_consegne = threading.Lock()


def imposta_consegna(tipo: str, fn: Callable[[dict], None] | None) -> None:
    """Chi riceve i job di questo tipo quando scattano. Chiamata all'avvio.

    I job scattati prima della registrazione — tipicamente quelli recuperati
    dopo un riavvio, che partono appena lo scheduler si avvia — vengono
    consegnati adesso, in ordine.
    """
    with _lock_consegne:
        if fn is None:
            _consegne.pop(tipo, None)
            return
        _consegne[tipo] = fn
        arretrati = [d for t, d in _in_attesa if t == tipo]
        _in_attesa[:] = [(t, d) for t, d in _in_attesa if t != tipo]
    for dati in arretrati:
        _consegna_sicura(fn, dati)


def _scatta(tipo: str, **dati) -> None:
    """Il punto d'ingresso di OGNI job. Riferito per nome da `data/jobs.db`.

    Il nome e la firma sono un contratto con i job gia' salvati: cambiarli
    significa che i promemoria programmati prima dell'aggiornamento non
    scattano piu'. `test_la_funzione_dei_job_non_cambia_nome` lo sorveglia.
    """
    dati = {"tipo": tipo, **dati}
    # Quanto e' in ritardo. Oltre GRAZIA_S la consegna lo sa e si comporta
    # di conseguenza: vedi la nota "oltre l'ora" in testa al modulo.
    try:
        previsto = datetime.strptime(dati.get("previsto", ""), tempo.FORMATO)
        dati["ritardo_s"] = max(0, int((datetime.now() - previsto).total_seconds()))
    except ValueError:
        dati["ritardo_s"] = 0
    dati["in_ritardo"] = dati["ritardo_s"] > GRAZIA_S
    with _lock_consegne:
        fn = _consegne.get(tipo)
        if fn is None:
            _in_attesa.append((tipo, dati))
            return
    _consegna_sicura(fn, dati)


def _consegna_sicura(fn: Callable[[dict], None], dati: dict) -> None:
    """Un'eccezione nella consegna non deve fermare lo scheduler: gli altri
    promemoria devono scattare lo stesso."""
    try:
        fn(dati)
    except Exception:                              # noqa: BLE001
        with _lock_consegne:
            STATO_CONSEGNE["fallite"] += 1


STATO_CONSEGNE = {"fallite": 0}


# --- il pianificatore --------------------------------------------------------

def _classe_scheduler():
    """BackgroundScheduler con una corsa in meno. Costruita qui dentro perche'
    importare APScheduler a livello di modulo costerebbe all'avvio di chiunque
    importi questo file, compresa la suite.

    LA CORSA (trovata provando il riavvio, M6)
    `shutdown()` porta lo stato a "fermo", chiude gli esecutori e sveglia il
    thread dello scheduler. Quel thread, svegliato, processa ancora una volta
    i job scaduti — con gli esecutori gia' chiusi: `RuntimeError`, poi
    `JobLookupError`, e il thread muore con uno stack trace nel log. Il job
    non si perde, perche' resta in `jobs.db`; ma alla chiusura di Metis con un
    promemoria in scadenza lo si vedrebbe, e un log che mostra eccezioni a
    ogni chiusura insegna a non leggere il log.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.schedulers.base import STATE_STOPPED

    class Scheduler(BackgroundScheduler):
        def _process_jobs(self):
            if self.state == STATE_STOPPED:
                return None
            return super()._process_jobs()

    return Scheduler


class Pianificatore:
    """APScheduler con il jobstore su SQLite. Una sola istanza nell'app."""

    def __init__(self, url: str | None = None):
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from tzlocal import get_localzone

        BackgroundScheduler = _classe_scheduler()

        if url is None:
            DB.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{DB.as_posix()}"
        self.url = url
        self.s = BackgroundScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=url)},
            # `None`: APScheduler non scarta MAI un job in ritardo. Il ritardo
            # lo giudica `_scatta`, contro GRAZIA_S. Vedi la nota in testa.
            job_defaults={"misfire_grace_time": None, "coalesce": True,
                          "max_instances": 1},
            timezone=get_localzone(),
        )

    # -- ciclo di vita --

    def avvia(self, in_pausa: bool = False) -> None:
        if not self.s.running:
            self.s.start(paused=in_pausa)

    def ferma(self) -> None:
        if self.s.running:
            self.s.shutdown(wait=False)

    @property
    def attivo(self) -> bool:
        return self.s.running

    def _richiedi_attivo(self) -> None:
        """Prima di `start()` APScheduler non ha ancora aperto `jobs.db`:
        `get_jobs()` ritorna una lista vuota e `add_job()` tiene il job in
        memoria finche' qualcuno non avvia.

        La lista vuota e' il problema. "Non ha promemoria" detto quando la
        verita' e' "non so guardare" e' la stessa bugia che in M5 si e' evitata
        sulla ricerca web: si trasforma in un rifiuto dichiarato. Scoperto
        provando il riavvio: la seconda istanza, prima di avviarsi, diceva
        che non c'era niente.
        """
        if not self.s.running:
            raise Rifiuto("Il pianificatore non e' attivo: non posso leggere "
                          "ne' programmare promemoria.")

    # -- programmazione --

    def _aggiungi(self, tipo: str, testo: str, quando: datetime, **dati) -> Voce:
        self._richiedi_attivo()
        jid = f"{tipo}-{uuid.uuid4().hex[:8]}"
        self.s.add_job(FUNZIONE, trigger="date", run_date=quando, id=jid,
                       name=testo[:200],
                       kwargs={"tipo": tipo, "id": jid, "testo": testo,
                               "previsto": quando.strftime(tempo.FORMATO), **dati},
                       replace_existing=False)
        return Voce(jid, tipo, testo, quando)

    def promemoria(self, testo: str, quando: datetime) -> Voce:
        return self._aggiungi(PROMEMORIA, testo, quando)

    def email(self, to: str, subject: str, body: str, quando: datetime) -> Voce:
        return self._aggiungi(EMAIL, subject, quando, to=to, subject=subject,
                              body=body, confermata_il=tempo.adesso()
                              .strftime(tempo.FORMATO))

    def spegnimento(self, dispositivo: str, quando: datetime,
                    tentativo: int = 0) -> Voce:
        """Il limite di durata di un dispositivo di casa. Sostituisce quello
        precedente dello stesso dispositivo: riaccendere la friggitrice fa
        ripartire il conto, non ne aggiunge un secondo.

        `tentativo` conta le riprogrammazioni dopo uno spegnimento fallito:
        vedi `home_assistant.spegni_per_sicurezza`."""
        self._richiedi_attivo()
        for j in self.s.get_jobs():
            if j.kwargs.get("tipo") == SPEGNI and j.kwargs.get("dispositivo") == dispositivo:
                j.remove()
        return self._aggiungi(SPEGNI, f"spegnimento di sicurezza: {dispositivo}",
                              quando, dispositivo=dispositivo, tentativo=tentativo)

    # -- consultazione --

    def voci(self, tipi: tuple[str, ...] = VISIBILI) -> list[Voce]:
        self._richiedi_attivo()
        out = []
        for j in self.s.get_jobs():
            tipo = j.kwargs.get("tipo")
            if tipo not in tipi:
                continue
            quando = _ora_del_job(j)
            if quando is None:
                continue
            out.append(Voce(j.id, tipo, j.kwargs.get("testo", j.name), quando))
        return sorted(out, key=lambda v: v.quando)

    def trova(self, riferimento: str) -> Voce:
        """Una voce per testo. Nessuna, o piu' di una: `Rifiuto`.

        PER PAROLE, NON PER FRASE (misurato in M6)
        La prima versione cercava il riferimento intero come sottostringa.
        Qwen, davanti a "cancella il promemoria del commercialista", scriveva
        `riferimento="promemoria del commercialista"`, e il promemoria si
        chiamava "chiamare il commercialista": nessuna corrispondenza,
        rifiuto, e l'utente non capiva perche'.

        Adesso contano le parole che portano significato — si tolgono gli
        articoli, le preposizioni e "promemoria" stesso — e una voce
        corrisponde se le contiene TUTTE. Tutte e non una: "chiamare Luca"
        non deve cancellare "chiamare Anna" perche' condividono "chiamare".
        """
        parole = _parole(riferimento)
        if not parole:
            raise Rifiuto("Mi dica di quale promemoria si tratta.")
        trovate = [v for v in self.voci() if parole <= _parole(v.testo)]
        if not trovate:
            raise Rifiuto(f"Non trovo nessun promemoria che parli di "
                          f"\"{riferimento}\".")
        if len(trovate) > 1:
            elenco = ", ".join(f"\"{v.testo}\"" for v in trovate[:3])
            raise Rifiuto(f"Ne trovo {len(trovate)}: {elenco}. Quale dei due?"
                          if len(trovate) == 2 else
                          f"Ne trovo {len(trovate)}: {elenco}. Mi dica quale.")
        return trovate[0]

    def cancella(self, jid: str) -> None:
        self.s.remove_job(jid)


# Le parole che non distinguono un promemoria da un altro.
_VUOTE = frozenset("""
    il lo la i gli le l un uno una di del dello della dei degli delle d a al
    allo alla ai agli alle da dal dalla in nel nella per con su che e o
    promemoria promemorie email mail messaggio quello quella
""".split())


def _parole(testo: str) -> set[str]:
    import unicodedata

    s = unicodedata.normalize("NFD", testo.casefold())
    s = "".join(c if c.isalnum() else " " for c in s if not unicodedata.combining(c))
    return {p for p in s.split() if p not in _VUOTE and len(p) > 1}


def _ora_del_job(job) -> datetime | None:
    """L'ora prevista, senza fuso. Prima dell'avvio APScheduler non ha ancora
    calcolato `next_run_time`: si legge dal trigger."""
    quando = getattr(job, "next_run_time", None) or getattr(job.trigger, "run_date", None)
    if quando is None:
        return None
    return quando.replace(tzinfo=None) if quando.tzinfo else quando


# L'istanza dell'applicazione. Pigra: importare questo modulo — lo fa
# `carica_tutti` — non deve aprire un database.
_pianificatore: Pianificatore | None = None
_lock_istanza = threading.Lock()


def pianificatore() -> Pianificatore:
    global _pianificatore
    with _lock_istanza:
        if _pianificatore is None:
            _pianificatore = Pianificatore()
        return _pianificatore


def usa_pianificatore(p: Pianificatore | None) -> None:
    """Solo per i test."""
    global _pianificatore
    with _lock_istanza:
        _pianificatore = p


# --- guardie e presentazione ---------------------------------------------------

GUARDIA_QUANDO = Guard("quando", lambda call: tempo.motivo_rifiuto(call.quando))


def _guardia_destinatario(call) -> str | None:
    from metis.tools import posta

    return posta.motivo_destinatario(call.to)


GUARDIA_DESTINATARIO = Guard("destinatario", _guardia_destinatario)


def presenta_promemoria(call: ScheduleReminder) -> dict[str, str]:
    return {"promemoria": call.testo,
            "quando": tempo.in_parole(tempo.interpreta(call.quando))}


def presenta_email_programmata(call: ScheduleEmail) -> dict[str, str]:
    return {"a": call.to, "oggetto": call.subject,
            "invio": tempo.in_parole(tempo.interpreta(call.quando)),
            "corpo": call.body}


# --- strumenti -----------------------------------------------------------------

@REGISTRY.strumento(Tier.T1, ScheduleReminder, guards=(GUARDIA_QUANDO,),
                    conferma=True, presenta=presenta_promemoria)
def _schedule_reminder(call: ScheduleReminder) -> dict:
    """Programma un promemoria. Sopravvive al riavvio del PC."""
    v = pianificatore().promemoria(call.testo, tempo.interpreta(call.quando))
    return v.come_dizionario()


@REGISTRY.strumento(Tier.T3, ScheduleEmail,
                    guards=(GUARDIA_QUANDO, GUARDIA_DESTINATARIO),
                    presenta=presenta_email_programmata)
def _schedule_email(call: ScheduleEmail) -> dict:
    """Programma l'invio di una email. Conferma alla creazione."""
    v = pianificatore().email(call.to, call.subject, call.body,
                              tempo.interpreta(call.quando))
    return {**v.come_dizionario(), "to": call.to}


@REGISTRY.strumento(Tier.T0, ListReminders)
def _list_reminders(call: ListReminders) -> dict:
    """Elenca promemoria ed email programmate."""
    voci = pianificatore().voci()
    return {"totale": len(voci), "voci": [v.come_dizionario() for v in voci]}


@REGISTRY.strumento(Tier.T1, CancelReminder)
def _cancel_reminder(call: CancelReminder) -> dict:
    """Cancella un promemoria o un'email programmata, indicata per testo."""
    p = pianificatore()
    v = p.trova(call.riferimento)
    p.cancella(v.id)
    return v.come_dizionario()
