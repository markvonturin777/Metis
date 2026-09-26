"""Un colore per stato, per la console e per la GUI.

Il commento in `logging.py` diceva "lo stesso codice della GUI di M3, cosi'
console e interfaccia raccontano la stessa storia". Finche' esistevano due
tabelle quella frase era un'intenzione. Ora e' una tabella sola: chi guarda
l'overlay e chi legge il terminale vedono lo stesso ambra nello stesso
momento, e non c'e' modo che divergano.

I colori vanno scelti perche' si distinguano **di sbieco e a due metri**,
che e' il caso d'uso vero di un overlay in un angolo dello schermo. Da qui
la scelta di non usare sfumature vicine: grigio, blu, ambra, verde,
fucsia e rosso si riconoscono anche con la coda dell'occhio.

PHASE1 — TONALITA' PIU' ACCESE, E "ASPETTA TE" NON E' PIU' ARANCIONE
Il fondo dell'Hub e' quasi nero (#060a0f), e i toni di PHASE0 ci si
spegnevano sopra: si e' passati alle varianti "400", piu' luminose. E
misurando le tonalita' e' saltato fuori un difetto che c'era gia':
l'arancione di ATTESA_CONFERMA stava a 11 gradi dall'ambra di "sta pensando"
e a 27 dal rosso dell'errore. Proprio lo stato che chiede all'utente di
intervenire era il piu' facile da confondere. Ora e' fucsia, lontano almeno
30 gradi da ogni altro stato che conta: lo verifica `tests/test_tema.py`.
"""

from __future__ import annotations

# stato -> (esadecimale per Qt, codice ANSI per il terminale, cosa significa)
STATI: dict[str, tuple[str, str, str]] = {
    "DORMIENTE":       ("#64748b", "\033[90m", "non sta ascoltando"),
    "IN_ASCOLTO":      ("#60a5fa", "\033[94m", "sveglio, in attesa"),
    "TRASCRIZIONE":    ("#38bdf8", "\033[96m", "ti sta sentendo"),
    "ELABORAZIONE":    ("#fbbf24", "\033[93m", "sta pensando"),
    "GENERAZIONE":     ("#fbbf24", "\033[93m", "sta pensando"),
    "RICERCA_WEB":     ("#a78bfa", "\033[95m", "sta cercando in rete"),
    "ESECUZIONE":      ("#a78bfa", "\033[95m", "sta agendo"),
    "ATTESA_CONFERMA": ("#e879f9", "\033[95;1m", "ASPETTA TE"),
    "PARLATO":         ("#34d399", "\033[92m", "sta parlando"),
    "INTERROTTO":      ("#f87171", "\033[91m", "interrotto"),
    "ERRORE":          ("#f87171", "\033[91m", "qualcosa non va"),
}

RESET = "\033[0m"
_IGNOTO = ("#64748b", "", "?")


def esadecimale(stato: str) -> str:
    return STATI.get(stato, _IGNOTO)[0]


def ansi(stato: str) -> str:
    return STATI.get(stato, _IGNOTO)[1]


def significato(stato: str) -> str:
    """Cosa vuol dire per chi guarda, non per chi ha scritto il codice."""
    return STATI.get(stato, _IGNOTO)[2]
