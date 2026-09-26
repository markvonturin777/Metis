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

CON LA CRONOLOGIA (PHASE1)
La prima tabella passa al router la frase e basta. In esercizio il router
riceve anche gli ultimi scambi, e li' c'erano due difetti che da qui non si
potevano vedere: la frase arrivava due volte ("Sai aiutarmi nella
programmazione?" apriva VS Code), e dopo un'azione il modello tendeva a
ripeterla. La seconda tabella rifa' la conversazione del 2026-09-25 con la
cronologia costruita come la costruisce l'orchestratore: frase di adesso
compresa.
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

    # PHASE1 — "come si fa" e' una spiegazione, non una ricerca. Il prompt lo
    # diceva gia', e il modello mandava lo stesso al web "come faccio un
    # chatbot AI": la risposta si reggeva sul blog di chi vende chatbot.
    ("come si fa una carbonara", None, None),
    ("come posso imparare a programmare in python", None, None),
    ("come faccio a fare un sito web", None, None),
    ("che differenza c e tra ram e vram", None, None),
    # E l'altra meta': cio' che cambia nel tempo va ancora cercato.
    ("quanto vale oggi il bitcoin", ["web_search"], None),
    ("ultime notizie su openai", ["web_search"], None),
    ("chi ha vinto ieri la partita della juve", ["web_search"], None),
    ("qual e l ultima versione di python", ["web_search"], None),
]


def _u(t: str) -> dict:
    return {"role": "user", "content": t}


def _a(t: str) -> dict:
    return {"role": "assistant", "content": t}


SALUTO = [{"role": "system", "content": "persona"}, _a("Buon pomeriggio. Sono operativo.")]
DOPO_VSCODE = SALUTO + [_u("Sai aiutarmi nella programmazione?"),
                        _a("Ho aperto Visual Studio Code.")]
DOPO_CHATBOT = DOPO_VSCODE + [
    _u("Come faccio un chatbot AI?"),
    _a("Per creare un chatbot AI si parte dallo scopo, poi si sceglie una piattaforma "
       "e si collegano le fonti di conoscenza.")]
DOPO_LOCALE = DOPO_CHATBOT + [
    _u("ma se io volessi farlo in locale da me?"),
    _a("In locale si puo' usare un modello aperto con Ollama e un'interfaccia sopra.")]
DOPO_CHROME = SALUTO + [_u("apri chrome"), _a("Ho aperto Chrome.")]
SLOT_CHROME = ("[CONTESTO CORRENTE]\nFinestra di riferimento: Nuova scheda - Google Chrome\n"
               "Ultima app aperta: chrome")
SLOT_FONTE = ("[CONTESTO CORRENTE]\nUltimo argomento cercato: prezzo del bitcoin\n"
              "Ultima fonte: https://it.investing.com/crypto/bitcoin")

# (cronologia prima della frase, frase, slot, atteso, controllo). La frase
# si aggiunge in coda alla cronologia, come fa l'orchestratore.
CASI_CONVERSAZIONE = [
    # La conversazione del 2026-09-25: nessuna di queste e' un'azione.
    (SALUTO, "Sai aiutarmi nella programmazione?", "", None, None),
    (DOPO_VSCODE, "Come faccio un chatbot AI?", "", None, None),
    (DOPO_CHATBOT, "ma se io volessi farlo in locale da me?", "", None, None),
    (DOPO_LOCALE, "ma se volessi farlo in locale da me e volessi addestrarlo?", "", None,
     None),
    (DOPO_LOCALE, "Va bene, grazie. Fammi un riassunto della conversazione.", "", None,
     None),
    # E queste si': la cronologia non deve spegnere le richieste vere.
    (DOPO_VSCODE, "aprimi anche chrome", "", ["open_application"],
     lambda c: c[0]["app"] == "chrome"),
    (DOPO_CHROME, "spostala sull altro schermo", SLOT_CHROME, ["move_window_to_monitor"],
     lambda c: "chrome" in c[0]["window"].lower()),
    (SALUTO, "aprimi il primo risultato", SLOT_FONTE, ["open_url"],
     lambda c: "investing" in c[0]["url"]),
    (DOPO_CHATBOT, "che tempo fa domani a Milano", "", ["web_search"], None),
]


def valuta(router, frase, atteso, controllo, giri, storia=None, slot=""):
    esiti = []
    for _ in range(giri):
        t0 = time.perf_counter()
        d = router.decidi(frase, storia, slot) if storia is not None else router.decidi(frase)
        ms = (time.perf_counter() - t0) * 1000
        nomi = [c.get("tool") for c in d.calls]
        if atteso is None:
            giusto = not d.e_strumento
        else:
            giusto = nomi == atteso and (controllo is None
                                         or bool(controllo(list(d.calls))))
        esiti.append((giusto, nomi, ms, d.origine))
    return esiti


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

    casi = [(f, a, c, None, "") for f, a, c in CASI]
    casi += [(f, a, c, storia + [_u(f)], slot) for storia, f, slot, a, c in CASI_CONVERSAZIONE]
    larghezza = max(larghezza, max(len(f) for f, *_ in casi))
    for n, (frase, atteso, controllo, storia, slot) in enumerate(casi):
        if n == len(CASI):
            print("\n  -- con la cronologia --")
        esiti = valuta(router, frase, atteso, controllo, args.giri, storia, slot)
        latenze_llm += [e[2] for e in esiti if e[3] == "llm"]

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
