"""I quattro casi anaforici di §4.4, con Qwen vero e gli slot veri.

    python benchmarks/prova_anafora.py
    python benchmarks/prova_anafora.py --giri 3

COSA MISURA
Se "spostalo sull'altro schermo" diventa una tool call con l'argomento
giusto. E' la meta' che dipende dal modello: la meta' che non ne dipende —
gli slot contengono la cosa giusta dopo la prima frase — sta in
`tests/test_slots.py` e gira senza rete.

Tenerle separate serve a sapere, quando un caso non funziona, se il problema
e' che Metis non ha registrato il riferimento o che non ha saputo usarlo.
Sono due difetti diversi e si correggono in due posti diversi.

LA PROVA CHE CONTA E' LA TERZA COLONNA
Non "ha prodotto una tool call" — quella la produce comunque — ma **con
quale argomento**. Un `maximize_window(window="")` dopo "massimizza VS Code"
e' una decisione sbagliata che sembra giusta, e senza controllare gli
argomenti passerebbe.

NESSUNA AZIONE VIENE ESEGUITA
Il banco si ferma alla decisione: gli effetti si provano in
`prova_automazione.py`, contro una cavia. Qui non si tocca nessuna finestra
vera, quindi lo si puo' far girare mentre si lavora.
"""

from __future__ import annotations

import argparse
import sys

from metis.core.router import Router
from metis.llm.toolcall import ToolRouter
from metis.memory.conversation import Memoria
from metis.memory.slots import SLOTS
from metis.tools.registry import carica_tutti

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class Esito:
    """Un finto Result: gli slot vogliono `ok` e `value`, non un broker."""

    def __init__(self, value=None):
        self.ok = True
        self.value = value or {}
        self.tool = None


# Ogni caso: (nome, preparazione degli slot, frase con il pronome,
#             strumento atteso, controllo sull'argomento)
CASI = [
    ("1 · Apri Chrome -> spostalo sull'altro schermo",
     [({"tool": "open_application", "app": "chrome"}, {"app": "chrome"})],
     "spostalo sull'altro schermo",
     "move_window_to_monitor",
     lambda c: "chrome" in (c.get("window") or "").lower()),

    ("2 · Cerca le news sui mercati -> aprimi il primo risultato",
     [({"tool": "web_search", "query": "news mercati"},
       {"query": "news mercati",
        "risultati": [{"url": "https://www.ilsole24ore.com/mercati"}]})],
     "aprimi il primo risultato",
     "open_url",
     lambda c: "ilsole24ore" in (c.get("url") or "")),

    ("3 · Massimizza VS Code -> no, rimpiccioliscila",
     [({"tool": "maximize_window", "window": "Visual Studio Code"},
       {"titolo": "Visual Studio Code", "comando": "massimizza"})],
     "no, rimpiccioliscila",
     ("restore_window", "minimize_window", "resize_window"),
     lambda c: "code" in (c.get("window") or "").lower()),

    ("4 · Cerca X, tre turni di altro, torna su quell'argomento",
     [({"tool": "web_search", "query": "andamento BTP decennale"},
       {"query": "andamento BTP decennale",
        "risultati": [{"url": "https://it.investing.com/btp"}]})],
     "torna su quell'argomento e dimmi le ultime",
     "web_search",
     lambda c: "btp" in (c.get("query") or "").lower()),
]

# I tre turni di mezzo del caso 4: servono a far uscire l'argomento dalla
# finestra recente, che e' il punto del caso.
RUMORE = [
    ("che ore sono?", "Non ho un orologio collegato."),
    ("quanti schermi ho?", "Ha due schermi."),
    ("grazie", "Si figuri."),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--giri", type=int, default=1)
    args = ap.parse_args()

    reg = carica_tutti()
    router = Router(reg, tool_router=ToolRouter(reg))
    router.tool_router.warmup()

    print("=" * 100)
    print("  CASI ANAFORICI §4.4 — il pronome diventa un argomento")
    print("=" * 100)
    print(f"  {args.giri} giri per caso · nessuna azione viene eseguita\n")

    ok_totali = prove = 0
    for nome, preparazione, frase, atteso, controllo in CASI:
        attesi = (atteso,) if isinstance(atteso, str) else atteso
        riusciti = 0
        ultimo = ("", None)
        for _ in range(args.giri):
            SLOTS.reset()
            mem = Memoria(system="")
            for call, valore in preparazione:
                SLOTS.osserva(call, Esito(valore))
                mem.aggiungi("user", "(frase precedente)")
                mem.aggiungi("assistant", "(fatto)")
            if nome.startswith("4"):
                for domanda, risposta in RUMORE:
                    mem.aggiungi("user", domanda)
                    mem.aggiungi("assistant", risposta)

            d = router.decidi(frase, mem.messaggi(), SLOTS.blocco())
            call = d.call or {}
            nome_tool = call.get("tool")
            giusto = nome_tool in attesi and bool(controllo(call))
            riusciti += giusto
            ultimo = (nome_tool or "chat", call)

        ok_totali += riusciti
        prove += args.giri
        segno = "OK " if riusciti == args.giri else ("~~ " if riusciti else "NO ")
        argomenti = ", ".join(f"{k}={v!r}" for k, v in ultimo[1].items()
                              if k != "tool") or "—"
        print(f"  {segno}{nome}")
        print(f"      slot iniettati : {SLOTS.blocco().splitlines()[1:] or '—'}")
        print(f"      atteso         : {'|'.join(attesi)}")
        print(f"      prodotto       : {ultimo[0]}({argomenti[:80]})")
        print(f"      {riusciti}/{args.giri}\n")

    print("  " + "-" * 80)
    print(f"  {ok_totali}/{prove} casi anaforici risolti")
    SLOTS.reset()
    return 0 if ok_totali == prove else 1


if __name__ == "__main__":
    sys.exit(main())
