"""La qualità della conversazione, misurata (PHASE6).

    python benchmarks/prova_conversazione.py                  # la persona in uso, 3 giri
    python benchmarks/prova_conversazione.py --prompt metis_v1 --giri 1
    python benchmarks/prova_conversazione.py --solo replay

PERCHE' QUESTO BANCO
Dopo la prima seduta vera di PHASE4 (2026-09-28) l'utente: "mi sembra di
parlare con la prima versione di GPT, a volte ignora la mia richiesta". Non
era il riconoscimento vocale (37 trascrizioni giuste su 40). Rigiocando le
frasi contro Qwen, con la cronologia che Metis aveva in quel momento, il
modello ricopiava le risposte precedenti ("Quali azioni puoi fare?" -> "Lei
non ha chiesto niente."). Questo banco rifa' quella prova, sempre uguale, e la
estende.

TRE PARTI
  replay    i 12 turni di conversazione della seduta, ciascuno con la sua
            cronologia vera (`tests/fixtures/seduta_20260928.json`)
  frasi     20 frasi di conversazione, senza cronologia
  azioni    4 richieste d'azione che il router non ha capito, arrivate alla
            conversazione dopo una storia di esiti: la misura di PHASE2
            ("Cliccato l'ottantuno" senza aver cliccato niente)

LE MISURE, UNA PER RISPOSTA
  ripete     la risposta e' (quasi) uguale a una risposta precedente della
             cronologia                                         target 0
  lei        il tic: "Buongiorno, lei?", "Lei e' qui?"          target <= 1/20
  tu         da' del tu                                         target 0
  ripiego    "non ho capito cosa fare" fuori posto              target 0
  nega       nega capacita' che ha ("non ho accesso a internet") target 0
  lunga      oltre tre frasi                                    target < 10%
  dichiara   (solo "azioni") dice di aver agito                 target 0
  copia      ricopia un esempio della persona (6 parole di fila) target 0
  signore    quante volte usa "signore" (informativo: non a ogni frase)

COSA NON MISURA
Se il tono e' quello di Jarvis. Quello lo decide chi ci parla: la revisione
alla cieca del giorno 7.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from metis.llm import prompts  # noqa: E402
from metis.llm.client import LlmClient  # noqa: E402
from metis.memory.commands import normalizza  # noqa: E402
from metis.memory.conversation import AZIONE, PAROLE, Memoria  # noqa: E402

SEDUTA = Path("tests/fixtures/seduta_20260928.json")
RISULTATI = Path("benchmarks/results")
# Il contesto che c'era, piu' o meno, durante la seduta: Chrome davanti.
SLOT = ("[CONTESTO CORRENTE]\nFinestra di riferimento: YouTube - Google Chrome\n"
        "Ultima app aperta: chrome")


# --- le due cose che PHASE6 cambia: stanno qui, e solo qui --------------------------

def persona(nome: str, turno: int) -> str:
    """Il system prompt per il turno `turno`. Da D-CONV 4 gli esempi ruotano
    col turno: se il modulo dei prompt lo sa fare, lo fa lui."""
    per_turno = getattr(prompts, "per_turno", None)
    return per_turno(nome, turno) if per_turno else prompts.carica(nome)


# `--cronologia vecchia` rifa' la memoria di prima di PHASE6 (tutto nella
# cronologia, nessuna origine), per confrontare alla pari.
CRONOLOGIA = {"modo": "conversazione", "finestra": None}


def aggiungi(mem: Memoria, t: dict) -> None:
    """Un turno della seduta nella memoria, come lo scrive l'orchestratore:
    da PHASE6 i comandi, i loro esiti e i chiarimenti sono AZIONE."""
    origine = AZIONE if (t.get("strumento") or t.get("chiarimento")) else PAROLE
    if CRONOLOGIA["modo"] == "vecchia":
        origine = PAROLE
    mem.aggiungi("user", t["detto"], origine)
    if t.get("risposta"):
        mem.aggiungi("assistant", t["risposta"], origine)


def messaggi(mem: Memoria) -> list[dict]:
    """Cio' che riceve il modello di conversazione."""
    per = "tutto" if CRONOLOGIA["modo"] == "vecchia" else "conversazione"
    return mem.messaggi(slot=SLOT, per=per)


# --- le misure ------------------------------------------------------------------------

LEI = re.compile(r"^\s*(?:buongiorno|buonasera|ciao|salve)?[,.]?\s*lei\b(?!\s+(?:ha|mi|puo))"
                 r"|^\s*(?:buongiorno|buonasera|ciao|salve)[,.]?\s*lei\s*\?", re.I)
TU = re.compile(r"\b(?:puoi|dimmi|hai bisogno|ti serve|ti posso|scusami|scusa|fammi sapere|tuo|tua)\b", re.I)
RIPIEGO = re.compile(r"non ho capito cosa fare", re.I)
NEGA = re.compile(r"non ho accesso (?:a|ad) internet|non (?:posso|so) cercare|non cerco sul web"
                  r"|non posso (?:aprire|cliccare)|non ho accesso alle applicazioni", re.I)
# La stessa espressione della guardia dell'orchestratore (D-CONV 5): il banco dice
# quante risposte la guardia sostituirebbe.
from metis.core.risposte import DICHIARA_AZIONE as DICHIARA  # noqa: E402
SIGNORE = re.compile(r"\bsignore\b", re.I)
FRASE = re.compile(r"[.!?…]+(?=\s|$)")


def coppie(msgs: list[dict]) -> list[tuple[str, str]]:
    """(domanda, risposta) della cronologia: ogni risposta con la frase che l'ha chiesta."""
    fuori, domanda = [], ""
    for m in msgs:
        if m["role"] == "user":
            domanda = m["content"]
        elif m["role"] == "assistant":
            fuori.append((domanda, m["content"]))
    return fuori


def ripete(risposta: str, precedenti: list[tuple[str, str]], detto: str = "") -> bool:
    """Quasi uguale a una risposta precedente data a una domanda DIVERSA. La stessa
    domanda ripetuta ("come stai messo a benzina?" due volte) puo' avere la
    stessa risposta: e' la risposta giusta, non una copia."""
    r, d = normalizza(risposta), normalizza(detto)
    return any(r and normalizza(dom) != d and SequenceMatcher(None, r, normalizza(ris)).ratio() >= 0.8
               for dom, ris in precedenti)


def copia(risposta: str, esempi: list[str], n: int = 6) -> bool:
    parole = normalizza(risposta).split()
    pezzi = {" ".join(parole[i:i + n]) for i in range(len(parole) - n + 1)}
    return any(p in normalizza(e) for p in pezzi for e in esempi)


def esempi_della_persona(nome: str) -> list[str]:
    """Le frasi di Metis negli esempi di tono: dal file del repertorio (D-CONV 4)
    o dalla sezione ESEMPI del prompt."""
    testi = []
    rep = Path(prompts.CARTELLA) / f"esempi_{nome.split('_')[-1]}.txt"
    for sorgente in ([rep.read_text(encoding="utf-8")] if rep.exists() else []) + [prompts.carica(nome)]:
        testi += [r.split(":", 1)[1].strip() for r in sorgente.splitlines()
                  if r.strip().lower().startswith("metis:")]
    return testi


def misura(risposta: str, precedenti: list[tuple[str, str]], esempi: list[str],
           detto: str = "") -> dict:
    return {"ripete": ripete(risposta, precedenti, detto),
            "lei": bool(LEI.search(risposta)),
            "tu": bool(TU.search(risposta)),
            "ripiego": bool(RIPIEGO.search(risposta)),
            "nega": bool(NEGA.search(risposta)),
            "lunga": len(FRASE.findall(risposta)) > 3,
            "dichiara": bool(DICHIARA.search(risposta)),
            "copia": copia(risposta, esempi),
            "signore": bool(SIGNORE.search(risposta))}


# --- le tre parti ---------------------------------------------------------------------

FRASI = [
    "Ciao.", "Hey Metis.", "Come stai?", "Quali azioni puoi fare?", "Puoi cercare sul web?",
    "Ma sei rincoglionito?", "Sei arrabbiata?", "Che ne pensi del lunedì mattina?",
    "Ho sbagliato di nuovo il codice, non funziona niente.", "Raccontami qualcosa di interessante.",
    "Chi sei?", "Mi consigli un film per stasera?", "Sei più intelligente di me?",
    "Qual è il tuo colore preferito?", "Dimmi una battuta.", "Perché il cielo è blu?",
    "Oggi sono stanco morto.", "Mi fai un complimento?", "Grazie, per ora basta.", "Buonanotte.",
]

STORIA_AZIONI = [("mostra i numeri", "Ecco 71 numeri."), ("clicca il 58", "Cliccato il 58."),
                 ("torna indietro", "Fatto."), ("mostra i numeri", "Ecco 78 numeri.")]
AZIONI = ["su ottantuna", "clicca su ottanto uno", "mastra in numeria", "chiudi la prima scheda di chrome"]


def chiedi(llm: LlmClient, msgs: list[dict]) -> str:
    """Come `Orchestrator._genera`: la guardia contro le copie sulla prima frase
    (si rigenera con la sola domanda) e il "signore" dosato. Stesse funzioni."""
    from metis.core.risposte import dosa_signore, ripete_precedente, solo_domanda

    precedenti = [m["content"] for m in msgs if m["role"] == "assistant"]
    pezzi = [c for c, _ in llm.stream_sentences(msgs)]
    if GUARDIE["attive"] and pezzi and precedenti and ripete_precedente(pezzi[0], precedenti):
        pezzi = [c for c, _ in llm.stream_sentences(solo_domanda(msgs))]
    if GUARDIE["attive"]:
        pezzi = [dosa_signore(p, precedenti) for p in pezzi]
    return " ".join(pezzi)


# `--senza-guardie`: il modello nudo, per sapere quanto fanno le guardie.
GUARDIE = {"attive": True}


def replay(llm, nome, giri, esempi):
    """La seduta rigiocata dall'inizio alla fine, un giro alla volta.

    I turni di comando entrano in memoria con il loro esito vero; i turni di
    conversazione li risponde il modello in prova, e la SUA risposta entra
    nella cronologia dei turni dopo. La prima versione rigiocava ogni turno
    con la cronologia originale, cioe' con le risposte sbagliate di allora
    ("Lei ha aperto Chrome."): misurava quanto il modello ricopia una
    cronologia gia' rovinata, non come sarebbe andata la seduta.
    """
    turni = json.loads(SEDUTA.read_text(encoding="utf-8"))["turni"]
    fuori = []
    for g in range(giri):
        mem = Memoria(system=persona(nome, 0))
        if CRONOLOGIA["finestra"]:
            mem.finestra_conversazione = CRONOLOGIA["finestra"]
        for i, t in enumerate(turni):
            if t["strumento"] or t["web"] or t["chiarimento"]:
                aggiungi(mem, t)
                continue
            mem.system = persona(nome, i + g * len(turni))
            mem.aggiungi("user", t["detto"])
            msgs = messaggi(mem)
            precedenti = coppie(msgs)
            r = chiedi(llm, msgs)
            mem.aggiungi("assistant", r)
            fuori.append({"parte": "replay", "detto": t["detto"], "risposta": r,
                          "allora": t["risposta"], **misura(r, precedenti, esempi, t["detto"])})
    return fuori


def frasi(llm, nome, giri, esempi):
    fuori = []
    for i, f in enumerate(FRASI):
        for g in range(giri):
            msgs = [{"role": "system", "content": persona(nome, i + g * len(FRASI))},
                    {"role": "user", "content": f}]
            r = chiedi(llm, msgs)
            fuori.append({"parte": "frasi", "detto": f, "risposta": r, **misura(r, [], esempi)})
    return fuori


def azioni(llm, nome, giri, esempi):
    fuori = []
    for i, f in enumerate(AZIONI):
        for g in range(giri):
            mem = Memoria(system=persona(nome, i))
            origine = PAROLE if CRONOLOGIA["modo"] == "vecchia" else AZIONE
            for detto, risposta in STORIA_AZIONI:
                mem.aggiungi("user", detto, origine)
                mem.aggiungi("assistant", risposta, origine)
            mem.aggiungi("user", f)
            msgs = messaggi(mem)
            r = chiedi(llm, msgs)
            precedenti = coppie(msgs)
            fuori.append({"parte": "azioni", "detto": f, "risposta": r, **misura(r, precedenti, esempi, f)})
    return fuori


# --- il riassunto -----------------------------------------------------------------------

TARGET = {"ripete": 0, "lei": 0.05, "tu": 0, "ripiego": 0, "nega": 0, "lunga": 0.10,
          "dichiara": 0, "copia": 0, "signore": 0.30}
# Le sigle della colonna di sinistra, una per misura.
SIGLE = {"ripete": "Rp", "lei": "Le", "tu": "Tu", "ripiego": "Ri", "nega": "Ne",
         "lunga": "Lu", "dichiara": "Di", "copia": "Co", "signore": "Si"}
# Nella parte "azioni" chiedere di ripetere e' la risposta giusta (la frase
# non e' stata capita): li' il ripiego non e' un errore.
VOLUTO = {("azioni", "ripiego")}


def tabella(righe: list[dict]) -> str:
    out = [f"  {'misura':10} {'replay':>9} {'frasi':>9} {'azioni':>9}   target"]
    for m in TARGET:
        celle = []
        for parte in ("replay", "frasi", "azioni"):
            rr = [r for r in righe if r["parte"] == parte]
            cella = f"{sum(r[m] for r in rr)}/{len(rr)}" if rr else "—"
            celle.append(f"({cella})" if (parte, m) in VOLUTO else cella)
        t = TARGET.get(m)
        bersaglio = "info" if t is None else ("0" if t == 0 else f"<= {t:.0%}")
        out.append(f"  {m:10} {celle[0]:>9} {celle[1]:>9} {celle[2]:>9}   {bersaglio}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default=prompts.VERSIONE)
    ap.add_argument("--giri", type=int, default=3)
    ap.add_argument("--solo", choices=("replay", "frasi", "azioni"))
    ap.add_argument("--finestra", type=int, help="messaggi nella finestra (D-CONV 2)")
    ap.add_argument("--senza-guardie", action="store_true",
                    help="senza la guardia contro le copie e il signore dosato")
    ap.add_argument("--opzioni", default="", help='opzioni di Ollama in JSON, es. {"presence_penalty": 1.5}')
    ap.add_argument("--cronologia", choices=("conversazione", "vecchia"), default="conversazione",
                    help="vecchia = la memoria di prima di PHASE6, per il confronto")
    args = ap.parse_args()
    CRONOLOGIA["modo"] = args.cronologia
    CRONOLOGIA["finestra"] = args.finestra
    GUARDIE["attive"] = not args.senza_guardie

    llm = LlmClient()
    if args.opzioni:
        llm.options.update(json.loads(args.opzioni))
    esempi = esempi_della_persona(args.prompt)
    righe = []
    t0 = time.time()
    for nome, parte in (("replay", replay), ("frasi", frasi), ("azioni", azioni)):
        if args.solo and args.solo != nome:
            continue
        righe += parte(llm, args.prompt, args.giri, esempi)

    print("=" * 100)
    print(f"  CONVERSAZIONE — persona {args.prompt} · cronologia {args.cronologia} · "
          f"{args.giri} giri · {len(righe)} risposte")
    print("=" * 100)
    for r in righe:
        segni = " ".join(SIGLE[k] for k in TARGET if r[k] and (r["parte"], k) not in VOLUTO)
        print(f"  [{segni:8}] {r['parte']:6} {r['detto'][:36]:36} | {r['risposta'][:150]}")
    print()
    print(tabella(righe))
    print("  (tra parentesi: voluto, non conta)   sigle: " +
          " ".join(f"{v}={k}" for k, v in SIGLE.items()))

    RISULTATI.mkdir(parents=True, exist_ok=True)
    uscita = RISULTATI / (f"conversazione_{args.prompt}_{args.cronologia}_"
                          f"{time.strftime('%Y%m%d_%H%M')}.json")
    uscita.write_text(json.dumps({"prompt": args.prompt, "cronologia": args.cronologia,
                                  "giri": args.giri, "righe": righe,
                                  "secondi": round(time.time() - t0)},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  risposte in {uscita}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
