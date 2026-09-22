"""Le frasi di accettazione di M4, dal parlato alla tool call.

    python benchmarks/prova_router.py
    python benchmarks/prova_router.py --giri 3

COSA MISURA
Se Qwen, davanti alla frase che l'utente direbbe, produce la chiamata
giusta. Non e' un test della suite e non lo diventera': dipende da un
modello che gira in un altro processo, e un test che a volte fallisce
perche' Ollama era occupato insegna a ignorare i test.

Il banco si ferma un passo prima del broker: qui interessa la DECISIONE,
non l'effetto. Gli effetti li verifica `prova_automazione.py`, contro una
cavia, senza modello di mezzo. Separarli serve a sapere, quando qualcosa
non funziona, da che parte guardare.

I CASI NEGATIVI CONTANO QUANTO GLI ALTRI
Un router che trasforma in azioni anche "che ore sono" e' peggio di uno
lento: la regola del progetto e' che nel dubbio si risponde a parole,
perche' parlare non fa danni e agire sì. Le ultime righe della tabella
sono frasi che NON devono produrre niente.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from metis.core.router import Router
from metis.llm.toolcall import ToolRouter
from metis.memory.commands import Libreria
from metis.tools.registry import carica_tutti

# (frase, atteso). L'atteso e' la sequenza di strumenti; None = conversazione.
# I controlli sugli argomenti sono funzioni perche' su alcuni campi conta il
# valore — "a destra" deve diventare destra — e su altri no.
CASI = [
    # I sei dell'accettazione, nell'ordine del piano.
    ("inizia a lavorare",
     ["open_application", "open_application"], None),
    ("sposta questa finestra sullo schermo a destra",
     ["move_window_to_monitor"],
     lambda c: c[0]["monitor"] in ("destra", "altro") and c[0]["window"] == ""),
    ("clicca sul link contatti",
     ["click_element"],
     lambda c: "contatt" in c[0]["elemento"].lower()),
    ("aprimi le news dei mercati",
     ["open_url"], lambda c: "investing" in c[0]["url"]),
    ("massimizza chrome",
     ["maximize_window"], lambda c: "chrome" in c[0]["window"].lower()),
    ("metti chrome sull altro schermo e massimizzala",
     ["move_window_to_monitor", "maximize_window"],
     lambda c: c[0]["monitor"] in ("altro", "destra", "sinistra")),

    # Variazioni: le stesse intenzioni dette in altro modo.
    ("fammi partire l editor di codice", ["open_application"],
     lambda c: c[0]["app"] == "vscode"),
    ("porta questa finestra sull altro monitor", ["move_window_to_monitor"], None),
    ("riduci a icona questa finestra", ["minimize_window"], None),
    ("metti questa finestra a meta schermo a sinistra", ["resize_window"],
     lambda c: c[0]["disposizione"] == "meta_sinistra"),
    ("quanti schermi ho collegati", ["list_monitors"], None),
    # "digita" e non "scrivi": misurato, `scrivi ciao mondo` finisce
    # sistematicamente in conversazione. E' l'ambiguita' dell'italiano —
    # "scrivi" vale anche per "dimmelo per iscritto" — e la regola del
    # progetto in quel caso e' non agire. Basta "digita", oppure "scrivi
    # X nella finestra".
    ("digita ciao mondo", ["type_text"], lambda c: "ciao" in c[0]["text"].lower()),

    # Nel dubbio non si agisce.
    ("che ore sono", None, None),
    ("raccontami una barzelletta", None, None),
    ("come stai oggi", None, None),
    ("cosa ne pensi di questo progetto", None, None),
    ("spiegami come funziona il wake word", None, None),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--giri", type=int, default=1,
                    help="ripeti ogni frase N volte: la ripetibilita' conta "
                         "quanto la correttezza")
    args = ap.parse_args()

    reg = carica_tutti()
    lib = Libreria(reg)
    tr = ToolRouter(reg)
    router = Router(reg, libreria=lib, tool_router=tr)

    print(f"strumenti offerti: {len(reg.disponibili())} · "
          f"comandi rapidi: {len(lib)}")
    if lib.avvisi:
        print("avvisi:", "; ".join(lib.avvisi))
    print(f"scaldo il router... {tr.warmup():.0f} ms\n")

    larghezza = max(len(f) for f, _, _ in CASI)
    ok_totali = 0
    prove = 0
    latenze_llm = []
    righe_sbagliate = []

    for frase, atteso, controllo in CASI:
        esiti = []
        for _ in range(args.giri):
            t0 = time.perf_counter()
            d = router.decidi(frase)
            ms = (time.perf_counter() - t0) * 1000
            if d.origine == "llm":
                latenze_llm.append(ms)

            nomi = [c.get("tool") for c in d.calls]
            if atteso is None:
                giusto = not d.e_strumento
            else:
                giusto = nomi == atteso and (controllo is None
                                             or bool(controllo(list(d.calls))))
            esiti.append((giusto, nomi, ms, d.origine))

        riusciti = sum(e[0] for e in esiti)
        ok_totali += riusciti
        prove += args.giri
        ultimo = esiti[-1]
        segno = "OK " if riusciti == args.giri else (
            "~~ " if riusciti else "NO ")
        atteso_txt = "chat" if atteso is None else "+".join(atteso)
        avuto = "chat" if not ultimo[1] else "+".join(str(n) for n in ultimo[1])
        print(f"  {segno} {frase:<{larghezza}}  {ultimo[3]:<9} "
              f"{ultimo[2]:>6.0f} ms  atteso {atteso_txt:<38} "
              f"{'' if riusciti == args.giri else 'avuto ' + avuto}")
        if riusciti != args.giri:
            righe_sbagliate.append((frase, atteso_txt, avuto))

    print(f"\n  {ok_totali}/{prove} decisioni corrette"
          + (f" ({args.giri} giri per frase)" if args.giri > 1 else ""))
    if latenze_llm:
        print(f"  latenza LLM: mediana {statistics.median(latenze_llm):.0f} ms, "
              f"max {max(latenze_llm):.0f} ms, {len(latenze_llm)} chiamate")
    s = router.stats()
    print(f"  comandi rapidi usati {s['fast_path']}, LLM {s['llm']}")
    return 0 if ok_totali == prove else 1


if __name__ == "__main__":
    sys.exit(main())
