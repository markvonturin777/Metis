"""Il riassunto conversazionale, con il modello vero.

    python benchmarks/prova_memoria.py

COSA MISURA
Quanto costa un riassunto e cosa conserva. La suite verifica *quando* si
riassume e *cosa non si tocca mai*; quelle sono proprieta' del codice. Se il
riassunto conservi i fatti che servono e' una proprieta' del modello, e si
misura qui.

IL COSTO E' IL NUMERO CHE DECIDE IL PROGETTO
Se un riassunto costasse dieci secondi, la regola "solo in DORMIENTE" non
basterebbe: l'utente che riprende a parlare mentre e' in corso troverebbe il
primo turno rallentato. A due o tre secondi la regola basta, perche' quella e'
la durata di una pausa normale in una conversazione.

I FATTI DA CONSERVARE SONO SCRITTI, NON GIUDICATI
Si costruisce una conversazione che contiene cose precise — un'applicazione,
una finestra, un argomento cercato, un fatto dichiarato dall'utente — e si
verifica quali sopravvivono. Leggere il riassunto e dire "mi sembra buono" non
e' una misura.
"""

from __future__ import annotations

import sys
import time

from metis.llm.client import LlmClient
from metis.llm.grounding import conta_token
from metis.llm.prompts import SYSTEM
from metis.memory.conversation import MAX_TOKEN_RIASSUNTO, Memoria

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Una conversazione con dentro cose che devono sopravvivere.
SCAMBIO = [
    ("apri Visual Studio Code", "Ho aperto Visual Studio Code."),
    ("mettilo sullo schermo di destra", "Spostata sul secondo schermo."),
    ("cerca l'andamento del BTP decennale",
     "Il rendimento e' al tre e settantacinque, secondo Investing.com."),
    ("mi chiamo Marco, ricordatelo", "Annotato."),
    ("che ore sono", "Non ho un orologio collegato."),
    ("apri Chrome", "Ho aperto Chrome."),
    ("raccontami una barzelletta", "Preferisco di no, non sono il mio forte."),
    ("quanti schermi ho", "Ne ha due."),
    ("massimizza Chrome", "Massimizzata."),
    ("grazie", "Si figuri."),
    ("come si chiama la capitale del Giappone", "Tokyo."),
    ("scrivimi una mail di auguri", "Non ho ancora la posta collegata."),
]

# (etichetta, alternative accettabili) — cosa deve sopravvivere al riassunto.
FATTI = [
    ("il nome dell'utente", ("marco",)),
    ("l'app aperta", ("visual studio code", "vs code", "vscode")),
    ("l'argomento cercato", ("btp",)),
    ("lo spostamento di finestra", ("schermo", "monitor", "spostat")),
    ("il secondo browser", ("chrome",)),
]


def main() -> int:
    llm = LlmClient()
    llm.warmup()

    print("=" * 90)
    print("  RIASSUNTO CONVERSAZIONALE — costo e conservazione")
    print("=" * 90)

    mem = Memoria(system=SYSTEM, riassumi=llm.riassumi)
    for domanda, risposta in SCAMBIO:
        mem.aggiungi("user", domanda)
        mem.aggiungi("assistant", risposta)

    prima = len(mem.turni)
    da_condensare = mem.da_condensare()
    print(f"\n  messaggi in memoria      : {prima}")
    print(f"  finestra scorrevole      : {mem.finestra} messaggi")
    print(f"  occupazione del contesto : {mem.occupazione() * 100:.0f}%  "
          f"(soglia di pressione {mem.soglia * 100:.0f}%)")
    print(f"  da condensare            : {da_condensare} messaggi")
    print(f"  serve riassunto          : {mem.serve_riassunto()}")

    t0 = time.perf_counter()
    fatto = mem.compatta()
    ms = (time.perf_counter() - t0) * 1000

    print(f"\n  riassunto eseguito       : {fatto}")
    print(f"  costo                    : {ms:.0f} ms   "
          f"(deve stare nella pausa: < 4000)")
    print(f"  token del riassunto      : {conta_token(mem.riassunto)} / "
          f"{MAX_TOKEN_RIASSUNTO}")
    print(f"  messaggi rimasti         : {len(mem.turni)}")
    print(f"\n  RIASSUNTO:\n  {mem.riassunto}\n")

    print("  " + "-" * 70)
    print("  Al primo giro si condensa solo cio' che e' uscito dalla finestra:")
    print("  i fatti degli ultimi 8 turni sono ancora leggibili per intero e")
    print("  NON devono comparire nel riassunto. 'Chrome' e' uno di quelli.\n")
    b = mem.riassunto.lower()
    conservati = 0
    for etichetta, forme in FATTI:
        c = any(f in b for f in forme)
        conservati += c
        print(f"  {'OK   ' if c else 'nella finestra'} {etichetta}")

    # Il secondo giro: il riassunto precedente deve entrare in quello nuovo,
    # altrimenti la memoria piu' vecchia sparisce invece di condensarsi.
    for i in range(8):
        mem.aggiungi("user", f"altra domanda {i}")
        mem.aggiungi("assistant", f"altra risposta {i}")
    t0 = time.perf_counter()
    mem.compatta()
    ms2 = (time.perf_counter() - t0) * 1000
    b2 = mem.riassunto.lower()
    sopravvive = sum(any(f in b2 for f in forme) for _, forme in FATTI)

    print("\n  " + "-" * 70)
    print(f"  secondo riassunto        : {ms2:.0f} ms")
    print(f"  fatti dopo il primo giro : {conservati}/{len(FATTI)}")
    print(f"  fatti dopo il secondo    : {sopravvive}/{len(FATTI)}   "
          "(la memoria piu' vecchia si condensa, non sparisce)")
    print(f"\n  RIASSUNTO 2:\n  {mem.riassunto}")
    print(f"\n  stats: {mem.stats()}")

    ok = fatto and ms < 4000 and conservati >= 3
    print(f"\n  ESITO: {'utilizzabile' if ok else '!! da rivedere'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
