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
VERSIONE = "metis_v1"

# Prompt minimo, usato se il file manca. Non e' la persona — e' cio' che
# resta quando la persona non si carica: meglio un assistente spoglio che un
# assistente senza vincoli.
RIPIEGO = ("Sei Metis, assistente personale su questo PC. Rispondi in "
           "italiano, dai del lei, al massimo due frasi brevi. Non inventare "
           "fatti. Niente preamboli.")


def carica(nome: str = VERSIONE) -> str:
    f = CARTELLA / f"{nome}.txt"
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return RIPIEGO


SYSTEM = carica()
