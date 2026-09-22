"""I criteri di uscita di M5, dal parlato alla risposta fondata.

    python benchmarks/prova_conoscenza.py
    python benchmarks/prova_conoscenza.py --senza-rete

COSA MISURA
Le cinque righe di accettazione del piano, ognuna con il suo esito:

    1  "cerca le ultime novita' su X"   -> risposta fondata, con la fonte
    2  fatto posteriore all'addestramento -> CERCA, non risponde a memoria
    3  domanda senza risposta disponibile -> lo dichiara
    4  ricerca fallita                  -> dichiarata, mai sostituita
    5  il contesto non supera mai gli 8k -> contato a ogni turno

E' il banco piu' lento di M5 — ricerca vera, lettura vera, generazione vera —
e per questo e' l'unico che dice se M5 funziona davvero. Gli altri provano un
pezzo per volta.

LA RIGA 2 E' QUELLA CHE VALE
Un assistente che risponde a memoria su un fatto recente e' peggio di uno che
non risponde: sbaglia con sicurezza, e chi ascolta non ha modo di accorgersene.
La colonna "percorso" dice se il turno e' passato dalle fonti o dai pesi, ed e'
la prima cosa da guardare quando una risposta sembra strana.

IL CONTESTO SI MISURA DAVVERO
Non con la stima di `conta_token`, che potrebbe sbagliare proprio nel caso
peggiore: con `prompt_eval_count` restituito da Ollama, che e' quanti token
sono entrati nel contesto. La colonna "ctx" e' quella, non una previsione.
"""

from __future__ import annotations

import argparse
import sys
import time

import ollama

from metis.core.router import Router
from metis.llm.grounding import BUDGET, CONTESTO_MAX, Consulente
from metis.llm.prompts import SYSTEM
from metis.llm.toolcall import ToolRouter
from metis.memory.conversation import Memoria
from metis.memory.slots import SLOTS
from metis.security.audit import AuditLog
from metis.security.broker import Broker
from metis.security.policies import Context
from metis.tools import web
from metis.tools.registry import carica_tutti

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "qwen3:8b"
RIFIUTO = "informazione non presente nei sistemi"

# Altri modi in cui Metis dichiara di non avere il dato. La frase esatta e'
# quella che il prompt chiede, ma il criterio del piano e' "non inventare",
# non "recitare": una risposta che dice chiaramente di non avere il dato
# soddisfa il criterio anche con parole sue. Si contano separate, perche' la
# differenza fra le due e' proprio la misura di quanto la direttiva tiene.
ALTRE_DICHIARAZIONI = (
    "non ho accesso", "non dispongo", "non posso sapere", "non fornisce",
    "non contengono", "non e' presente", "non è presente", "non risulta",
    "non ho dati", "non sono disponibili",
)

# (domanda, percorso atteso, nota)
#   "web"       deve consultare le fonti
#   "memoria"   deve rispondere da se', senza cercare
#   "dichiara"  qualunque percorso, purche' NON inventi: la riga 3 del piano.
#               Cercare e poi dire "le fonti non lo dicono" e' un esito
#               corretto quanto dirlo subito — anzi, e' il piu' diligente.
DOMANDE = [
    # 1 — la frase di accettazione del piano
    ("cerca le ultime novita' sui mercati europei", "web", "riga 1"),
    # 2 — fatti che nessun modello puo' sapere a memoria
    ("che tempo fara' domani a Milano?", "web", "riga 2"),
    ("quanto rende il BTP decennale adesso?", "web", "riga 2"),
    ("qual e' l'ultima versione stabile di Python?", "web", "riga 2"),
    # 3 — cose che sa, e su cui NON deve cercare
    ("cos'e' un BTP?", "memoria", "non deve cercare"),
    ("spiegami la differenza fra RAM e VRAM", "memoria", "non deve cercare"),
    # 4 — una domanda a cui NON esiste risposta perche' riguarda un fatto
    # che Metis non ha modo di conoscere. Non una domanda sulla privacy: a
    # quella il modello risponde "non posso accedere a dati personali", che
    # e' un rifiuto giusto ma di un'altra specie, e misurerebbe un'altra cosa.
    #
    # DUE E NON UNA, e in fondo alla sequenza di proposito. In isolamento
    # Qwen usa la frase esatta 4 volte su 5; dopo sei turni di conversazione
    # la direttiva si annacqua e il modello passa a parole sue ("non ho
    # accesso a..."). E' una proprieta' che si vede solo in sequenza, e
    # misurarla con una domanda sola la nasconderebbe meta' delle volte.
    ("a che ora ho spento il computer martedi' scorso?",
     "dichiara", "riga 3: non deve inventare un orario"),
    # La domanda dev'essere senza risposta DAVVERO. "Quanti abitanti ha
    # Roccafluvione" sembrava buona e non lo era: il web lo sa, Metis e'
    # andato a cercarlo e ha risposto 1.840 citando la fonte — cioe' si e'
    # comportato benissimo, e il banco lo segnava come fallito. Una domanda a
    # cui il web risponde non misura la riga 3, misura la riga 2.
    ("quante volte ho aperto Chrome questa settimana?",
     "dichiara", "riga 3: non deve inventare un numero"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--senza-rete", action="store_true")
    ap.add_argument("--con-cache", action="store_true")
    args = ap.parse_args()

    reg = carica_tutti()
    broker = Broker(registry=reg, audit=AuditLog())
    router = Router(reg, tool_router=ToolRouter(reg))
    client = ollama.Client()

    def esegui(call: dict, untrusted: bool):
        return broker.execute(call, Context(has_untrusted_content=untrusted))

    consulente = Consulente(esegui)
    mem = Memoria(system=SYSTEM)
    SLOTS.reset()

    if args.senza_rete:
        _stacca()
    elif not args.con_cache:
        web.CACHE.svuota()

    router.tool_router.warmup()

    print("=" * 104)
    print("  CRITERI DI USCITA M5 — conoscenza, dal parlato alla risposta")
    print("=" * 104)
    print(f"  rete: {'STACCATA (simulata)' if args.senza_rete else 'vera'}   "
          f"budget fonti {BUDGET['web']} token   contesto {CONTESTO_MAX}\n")

    giusti = 0
    ctx_max = 0
    frasi_esatte = dichiarazioni = 0
    for domanda, atteso, nota in DOMANDE:
        t0 = time.perf_counter()
        mem.aggiungi("user", domanda)
        slot = SLOTS.blocco()

        d = router.decidi(domanda, mem.messaggi(), slot)
        query = next((c.get("query") for c in d.calls
                      if c.get("tool") == "web_search"), None)

        fonti = []
        degradata = False
        if query:
            percorso = "web"
            ctx = consulente.consulta(query)
            if ctx.ok:
                messaggi = mem.messaggi(slot=slot, domanda=ctx.messaggio(domanda))
                fonti = ctx.citazioni()
            else:
                # DEGRADAZIONE: il modello non viene interpellato. Vedi
                # `Orchestrator._percorso_web`.
                degradata = True
                messaggi = None
                risposta = ctx.motivo
        else:
            percorso = "memoria"
            messaggi = mem.messaggi(slot=slot)

        token_ctx = 0
        if messaggi is not None:
            r = client.chat(model=MODEL, messages=messaggi, think=False,
                            options={"num_ctx": CONTESTO_MAX, "temperature": 0.7})
            risposta = (r["message"]["content"] or "").strip()
            token_ctx = int(r.get("prompt_eval_count", 0))
            ctx_max = max(ctx_max, token_ctx)

        mem.aggiungi("assistant", risposta)
        for c in d.calls:
            SLOTS.osserva(c, _finto_ok(c, fonti))
        ms = (time.perf_counter() - t0) * 1000

        b = risposta.lower()
        esatta = RIFIUTO in b
        dichiara = esatta or any(x in b for x in ALTRE_DICHIARAZIONI)
        if atteso == "dichiara":
            giusto = dichiara
            frasi_esatte += int(esatta)
            dichiarazioni += 1
        else:
            giusto = percorso == atteso
        giusti += giusto

        segno = "OK " if giusto else "NO "
        print(f"  {segno}{domanda}")
        print(f"      atteso {atteso:<9} percorso {percorso:<8} "
              f"ctx {token_ctx:>5}  {ms:>6.0f} ms  · {nota}")
        if degradata:
            print("      DEGRADATA: il modello non e' stato interpellato")
        if fonti:
            print(f"      fonti: {', '.join(f[:48] for f in fonti)}")
        print(f"      {risposta[:200]}")
        cita = any(_dominio(f) in risposta.lower() for f in fonti)
        if fonti:
            print(f"      cita la fonte: {'sì' if cita else 'NO'}")
        print()

    print("  " + "-" * 90)
    print(f"  criteri soddisfatti    : {giusti}/{len(DOMANDE)}")
    if dichiarazioni:
        print(f"  frase esatta del prompt: {frasi_esatte}/{dichiarazioni}"
              "   (le altre dichiarano con parole proprie: il criterio e'"
              " 'non inventare', ed e' soddisfatto)")
    print(f"  contesto massimo reale : {ctx_max} / {CONTESTO_MAX} token "
          f"({'entro' if ctx_max <= CONTESTO_MAX else '!! SFORA'})")
    print(f"  memoria                : {mem.stats()}")
    print(f"  occupazione finale     : {mem.occupazione(SLOTS.blocco()) * 100:.0f}%")
    print(f"  audit                  : {broker.audit.stats()}")
    if args.senza_rete:
        print("\n  Con la rete staccata, i turni 'web' devono essere tutti "
              "DEGRADATI: nessuna risposta a memoria travestita da fonte.")
    SLOTS.reset()
    return 0 if giusti == len(DOMANDE) and ctx_max <= CONTESTO_MAX else 1


def _stacca() -> None:
    def morto(query, n):
        raise RuntimeError("[simulato] rete assente")

    web.MOTORI = (("ddg", morto),)
    web.CACHE.svuota()


def _finto_ok(call: dict, fonti: list[str]):
    class R:
        ok = True
        tool = call.get("tool")
        value = {"query": call.get("query", ""),
                 "risultati": [{"url": u} for u in fonti]}
    return R()


def _dominio(url: str) -> str:
    """Il nome con cui la fonte verrebbe pronunciata: "euronews", non
    "it.euronews.com". Metis cita "secondo Euronews", e un confronto sul
    dominio intero direbbe che non ha citato nulla."""
    if "//" not in url:
        return url.lower()
    host = url.split("/")[2].lower()
    pezzi = [p for p in host.split(".")
             if p not in ("www", "it", "com", "org", "net", "eu", "io")]
    return pezzi[-1] if pezzi else host


if __name__ == "__main__":
    sys.exit(main())
