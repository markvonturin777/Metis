"""System prompt versionati, su file e non nel codice.

PERCHE' UN .txt E NON UNA COSTANTE
Perche' la persona si tara provando, e provare significa cambiare una riga e
rilanciare venti interazioni. Con il prompt dentro un modulo Python ogni
taratura e' una modifica al codice, finisce in un diff insieme a cose che
non c'entrano, e la versione precedente si perde. Su file, `metis_v1.txt` e
un eventuale `metis_v2.txt` convivono e si confrontano.

IL NOME HA UN NUMERO PER LO STESSO MOTIVO
Le misure di §4.3 del tracking valgono per una versione precisa del prompt.
Cambiarlo senza cambiare nome renderebbe quei numeri una fotografia di
qualcosa che non esiste piu'.
"""

from __future__ import annotations

from pathlib import Path

CARTELLA = Path(__file__).parent
VERSIONE = "metis_v2"

# Prompt minimo, usato se il file manca. Non e' la persona — e' cio' che
# resta quando la persona non si carica: meglio un assistente spoglio che un
# assistente senza vincoli.
RIPIEGO = ("Sei Metis, un'assistente personale su questo PC. Rispondi in "
           "italiano, dai del lei, parli di te al femminile, al massimo due "
           "frasi brevi. Non inventare fatti. Niente preamboli.")


def carica(nome: str = VERSIONE) -> str:
    f = CARTELLA / f"{nome}.txt"
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return RIPIEGO


SYSTEM = carica()


# PHASE6 — GLI ESEMPI DI TONO RUOTANO (D-CONV 4)
# Un modello da 8B imita gli esempi molto meglio delle regole astratte: e' il
# modo di ottenere il tono di Jarvis. Ma quattro esempi fissi si ricopiavano
# parola per parola ("I sistemi sono operativi e il caffe'…", a 4 saluti su 4).
# Il repertorio sta in `esempi_<versione>.txt`; per ogni domanda ne entrano
# PER_TURNO, scelti a rotazione sul numero della domanda: nessuno e' abbastanza
# frequente da diventare una formula, e un banco resta ripetibile.
PER_TURNO = 3


def esempi(nome: str = VERSIONE) -> list[str]:
    """Le coppie del repertorio, ciascuna "Utente: …\\nMetis: …". Nessun file = nessuna."""
    f = CARTELLA / f"esempi_{nome.split('_')[-1]}.txt"
    try:
        testo = f.read_text(encoding="utf-8")
    except OSError:
        return []
    righe = [r for r in testo.splitlines() if not r.lstrip().startswith("#")]
    return [b.strip() for b in "\n".join(righe).split("\n\n") if b.strip()]


def per_turno(nome: str = VERSIONE, n: int = 0) -> str:
    """Il system prompt per la domanda numero `n`: la persona, piu' tre esempi."""
    base = carica(nome)
    coppie = esempi(nome)
    if not coppie:
        return base
    scelti = [coppie[(n * PER_TURNO + i) % len(coppie)] for i in range(min(PER_TURNO, len(coppie)))]
    return f"{base}\n\n## ESEMPI DI TONO (il tono, non le parole)\n" + "\n\n".join(scelti)
