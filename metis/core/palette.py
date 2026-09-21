"""Un colore per stato, per la console e per la GUI.

Il commento in `logging.py` diceva "lo stesso codice della GUI di M3, cosi'
console e interfaccia raccontano la stessa storia". Finche' esistevano due
tabelle quella frase era un'intenzione. Ora e' una tabella sola: chi guarda
l'overlay e chi legge il terminale vedono lo stesso ambra nello stesso
momento, e non c'e' modo che divergano.

I colori vanno scelti perche' si distinguano **di sbieco e a due metri**,
che e' il caso d'uso vero di un overlay in un angolo dello schermo. Da qui
la scelta di non usare sfumature vicine: grigio, blu, ambra, verde,
arancione e rosso si riconoscono anche con la coda dell'occhio.
"""

from __future__ import annotations

# stato -> (esadecimale per Qt, codice ANSI per il terminale, cosa significa)
STATI: dict[str, tuple[str, str, str]] = {
    "DORMIENTE":       ("#5a6472", "\033[90m", "non sta ascoltando"),
    "IN_ASCOLTO":      ("#3b82f6", "\033[94m", "sveglio, in attesa"),
    "TRASCRIZIONE":    ("#38bdf8", "\033[96m", "ti sta sentendo"),
    "ELABORAZIONE":    ("#f59e0b", "\033[93m", "sta pensando"),
    "GENERAZIONE":     ("#f59e0b", "\033[93m", "sta pensando"),
    "RICERCA_WEB":     ("#a855f7", "\033[95m", "sta cercando in rete"),
    "ESECUZIONE":      ("#a855f7", "\033[95m", "sta agendo"),
    "ATTESA_CONFERMA": ("#fb923c", "\033[33m", "ASPETTA TE"),
    "PARLATO":         ("#22c55e", "\033[92m", "sta parlando"),
    "INTERROTTO":      ("#ef4444", "\033[91m", "interrotto"),
    "ERRORE":          ("#ef4444", "\033[91m", "qualcosa non va"),
}

RESET = "\033[0m"
_IGNOTO = ("#5a6472", "", "?")


def esadecimale(stato: str) -> str:
    return STATI.get(stato, _IGNOTO)[0]


def ansi(stato: str) -> str:
    return STATI.get(stato, _IGNOTO)[1]


def significato(stato: str) -> str:
    """Cosa vuol dire per chi guarda, non per chi ha scritto il codice."""
    return STATI.get(stato, _IGNOTO)[2]
