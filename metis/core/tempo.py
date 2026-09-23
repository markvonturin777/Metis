"""Date: validarle, e dirle in italiano.

L'INTERPRETAZIONE LA FA IL MODELLO, LA VERIFICA IL CODICE
"Domani alle 17", "fra due ore", "lunedi' mattina": il piano sceglie di far
interpretare la frase all'LLM, che produce un ISO 8601 dentro lo schema della
tool call. E' la scelta giusta per la copertura del parlato e sbagliata per
la fiducia, quindi si paga con due controlli che il modello non puo' saltare:

    la data e' nel futuro ed entro un anno     guardia del broker
    l'utente l'ha sentita e l'ha confermata    conferma prima di schedulare

IL MODELLO DEVE SAPERE CHE GIORNO E'
Sembra ovvio e non lo e': un LLM non ha un orologio. Senza la riga
`contesto_temporale()` nel prompt del router, "domani" e' il giorno dopo la
data di addestramento. Si inietta a ogni decisione.

PERCHE' ORA LOCALE E NON UTC
Perche' "alle 17" detto a voce e' l'ora sul muro. Le date si scambiano senza
fuso — `2026-09-24T17:00` — e il fuso lo aggiunge lo scheduler, una volta
sola, con quello del sistema. Il cambio dell'ora legale lo gestisce il fuso,
non questo file.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# Il formato che il modello deve produrre. Minuti, non secondi: a voce nessuno
# dice i secondi, e un campo in piu' e' un posto in piu' dove sbagliare.
FORMATO = "%Y-%m-%dT%H:%M"
PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"

# "Nel futuro" con un margine: un promemoria per fra venti secondi e' quasi
# certamente un'ora interpretata male, non una richiesta.
ANTICIPO_MINIMO = timedelta(minutes=1)
ORIZZONTE_MASSIMO = timedelta(days=365)

GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato",
          "domenica")
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")

_ISO = re.compile(PATTERN)


def adesso() -> datetime:
    """L'ora locale, senza fuso. Una funzione e non `datetime.now()` sparso
    nel codice: i test la sostituiscono."""
    return datetime.now().replace(second=0, microsecond=0)


def interpreta(iso: str) -> datetime:
    """Da stringa della tool call a datetime. Solleva ValueError."""
    if not _ISO.match(iso or ""):
        raise ValueError(f"data non nel formato {FORMATO}: {iso!r}")
    return datetime.strptime(iso, FORMATO)


def motivo_rifiuto(iso: str, rif: datetime | None = None) -> str | None:
    """Perche' questa data non va bene, oppure None. Per la guardia.

    I motivi sono frasi da pronunciare: finiscono nella voce di Metis tramite
    `risposte.descrivi`.
    """
    rif = rif or adesso()
    try:
        quando = interpreta(iso)
    except ValueError:
        return "non ho capito quando"
    if quando < rif + ANTICIPO_MINIMO:
        return f"{in_parole(quando, rif)} e' gia' passato"
    if quando > rif + ORIZZONTE_MASSIMO:
        return "e' oltre un anno da oggi: non schedulo cosi' lontano"
    return None


def in_parole(quando: datetime, rif: datetime | None = None) -> str:
    """"domani, giovedì 24 settembre, alle 17:00".

    Il giorno della settimana c'e' SEMPRE, anche quando c'e' gia' "domani":
    e' il pezzo che permette all'utente di accorgersi che il modello ha
    capito male. "Domani, sabato" detto di mercoledi' suona sbagliato subito;
    "domani" da solo no.
    """
    rif = rif or adesso()
    giorni = (quando.date() - rif.date()).days
    data = f"{GIORNI[quando.weekday()]} {quando.day} {MESI[quando.month - 1]}"
    if quando.year != rif.year:
        data += f" {quando.year}"
    ora = f"alle {quando:%H:%M}"
    if giorni == 0:
        return f"oggi {ora}"
    if giorni == 1:
        return f"domani, {data}, {ora}"
    if giorni == 2:
        return f"dopodomani, {data}, {ora}"
    return f"{data}, {ora}"


def contesto_temporale(rif: datetime | None = None) -> str:
    """Le righe che dicono al router che giorno e' oggi, e i prossimi sette.

    Senza la prima, "domani" non ha senso per un modello che non ha un
    orologio.

    IL CALENDARIO SI LEGGE, NON SI CALCOLA (misurato in M6)
    Con la sola riga [ADESSO], Qwen 3 8B sbagliava 3 date relative su 7:
    "lunedi' mattina" detto di mercoledi' diventava SABATO, "venerdi'"
    diventava giovedi', "tra mezz'ora" diventava un'ora. Tutte e tre passavano
    la guardia — sono nel futuro, entro un anno — e l'unica rete sarebbe
    stata l'utente che sente "sabato" nella domanda di conferma.

    Il modello sa leggere, non sa fare l'aritmetica dei giorni della
    settimana. Quindi non gliela si chiede: le prossime sette date sono
    scritte, e "lunedi'" si copia da una riga invece di ricavarlo da un
    calcolo modulo 7. Costa una sessantina di token.
    """
    #
    # OGGI STA NEL CALENDARIO, E IL GIORNO CHE SI RIPETE E' "PROSSIMO"
    # La prima versione elencava i sette giorni DOPO oggi. Risultato: di
    # mercoledi', "fra due ore" diventava mercoledi' PROSSIMO — il modello
    # cercava "mercoledi'" nel calendario e trovava il 30. Correggere un
    # errore di calcolo introducendo un errore di lettura: il calendario deve
    # dire qual e' oggi, e il giorno della settimana che torna fra sette
    # giorni deve chiamarsi diversamente.
    rif = rif or adesso()
    righe = [f"[ADESSO] {GIORNI[rif.weekday()]} {rif.day} "
             f"{MESI[rif.month - 1]} {rif.year}, ore {rif:%H:%M} "
             f"(formato date per gli strumenti: {rif:%Y-%m-%dT%H:%M})",
             "[CALENDARIO] per un giorno della settimana COPIA la data da qui, "
             "non calcolarla. Per \"fra N minuti/ore\" parti da OGGI:",
             f"  OGGI {GIORNI[rif.weekday()]} = {rif:%Y-%m-%d}"]
    for n in range(1, 8):
        g = rif + timedelta(days=n)
        giorno = GIORNI[g.weekday()]
        if n == 7:
            giorno = f"{giorno} della settimana prossima"
        nome = {1: "domani", 2: "dopodomani"}.get(n, "")
        righe.append(f"  {giorno} = {g:%Y-%m-%d}" + (f" ({nome})" if nome else ""))

    # GLI INTERVALLI SI LEGGONO, COME I GIORNI (misurato in M6)
    # Con il solo calendario "fra due ore" veniva giusto e "tra mezz'ora" no:
    # alle 21:40, 3 giri su 3 davano 22:40. Sommare ore non scavalca niente;
    # sommare 30 minuti a 21:40 scavalca l'ora, ed e' li' che il modello
    # sbaglia. Stessa cura del calendario: il risultato scritto, da copiare.
    righe.append("[INTERVALLI] \"fra ...\" a partire da adesso, gia' calcolati:")
    for etichetta, minuti in (("fra 10 minuti", 10), ("fra un quarto d'ora", 15),
                              ("fra 20 minuti", 20), ("fra mezz'ora", 30),
                              ("fra 45 minuti", 45), ("fra un'ora", 60),
                              ("fra un'ora e mezza", 90), ("fra due ore", 120),
                              ("fra tre ore", 180)):
        righe.append(f"  {etichetta} = {rif + timedelta(minutes=minuti):%Y-%m-%dT%H:%M}")
    return "\n".join(righe)
