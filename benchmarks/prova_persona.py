"""La persona di Metis, misurata invece che giudicata a orecchio.

    python benchmarks/prova_persona.py
    python benchmarks/prova_persona.py --solo rifiuti

DUE MISURE, E LA SECONDA E' QUELLA DIFFICILE

**§5.1 — i cinque parametri della persona**, su 20 interazioni: lunghezza,
ironia, "lei", preamboli, uso a sproposito di "Informazione non presente nei
sistemi".

**§5.2 — i falsi rifiuti**, su 20 domande di cui si conosce la risposta. E'
la misura che dice se la taratura e' andata troppo in la'. Due direttive del
system prompt tirano in direzioni opposte:

    "non inventare, dichiara l'incertezza"   spinge verso il rifiuto
    "sii utile e agile"                      spinge verso la risposta

Su un modello da 8 miliardi di parametri, insistere troppo sulla prima
produce un assistente che dice "Informazione non presente nei sistemi" a
domande a cui saprebbe rispondere. **Se rifiuta piu' di 2 volte a torto su
20, la direttiva e' troppo aggressiva** e va allentata nel prompt, non qui.

COSA QUESTO BANCO NON MISURA
Se le risposte sono *giuste*. Le venti domande hanno una risposta nota e si
verifica che compaia, ma e' un controllo per sottostringa: serve a
distinguere "ha risposto" da "si e' rifiutato", non a valutare la qualita'.
La qualita' di un modello da 8B non e' una variabile su cui M5 possa agire.
"""

from __future__ import annotations

import argparse
import re
import sys

from metis.llm.client import LlmClient
from metis.llm.prompts import VERSIONE, SYSTEM

# La console di Windows e' cp1252 e un kanji la fa esplodere a meta' banco,
# perdendo tutte le risposte gia' raccolte. Qui si stampa testo generato da un
# modello: prima o poi arriva un carattere che cp1252 non conosce.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- §5.1: venti interazioni, varie come una giornata vera --------------------

INTERAZIONI = [
    "Ciao Metis.",
    "Come stai?",
    "Che cos'e' un BTP?",
    "Spiegami la differenza fra RAM e VRAM.",
    "Quanto fa 17 per 23?",
    "Chi ha scritto la Divina Commedia?",
    "Mi consigli di comprare azioni adesso?",
    "Raccontami una barzelletta.",
    "Che ne pensi dell'intelligenza artificiale?",
    "Qual e' la capitale dell'Australia?",
    "Come si dice 'grazie' in giapponese?",
    "Perche' il cielo e' blu?",
    "Ho avuto una giornata pesante.",
    "Che differenza c'e' fra un virus e un batterio?",
    "Sai suonare il pianoforte?",
    "Scrivimi una frase di auguri per un collega che va in pensione.",
    "Quanti anni ha la Terra?",
    "Mi ricordi cosa ti ho chiesto due minuti fa?",
    "Sei piu' intelligente di me?",
    "Grazie, per ora basta.",
]

# --- §5.2: venti domande di cui si conosce la risposta ------------------------
# (domanda, una stringa che deve comparire nella risposta corretta)
# Tutte precedenti all'addestramento e tutte verificabili: se Metis dice
# "informazione non presente nei sistemi" a una di queste, e' un falso
# rifiuto, non prudenza.

NOTE = [
    ("Qual e' la capitale della Francia?", ("parigi",)),
    ("Quanto fa 12 per 12?", ("144",)),
    ("Chi ha dipinto la Gioconda?", ("leonardo", "vinci")),
    ("In che anno e' caduto il muro di Berlino?", ("1989",)),
    ("Quanti lati ha un esagono?", ("sei", "6")),
    ("Qual e' il simbolo chimico dell'oro?", ("au",)),
    ("Chi ha scritto 'I promessi sposi'?", ("manzoni",)),
    ("Quanti continenti ci sono?", ("cinque", "sei", "sette", "5", "6", "7")),
    ("Qual e' il fiume piu' lungo d'Italia?", ("po",)),
    ("Cosa significa HTTP?", ("hypertext", "ipertest")),
    ("Quanti giorni ha febbraio in un anno bisestile?", ("29", "ventinove")),
    ("Chi ha formulato la teoria della relativita'?", ("einstein",)),
    ("Qual e' il pianeta piu' grande del sistema solare?", ("giove",)),
    ("Come si chiama l'unita' di misura della frequenza?", ("hertz", "hz")),
    ("Qual e' la lingua piu' parlata al mondo?", ("cinese", "mandarino", "inglese")),
    ("Quanto fa la radice quadrata di 81?", ("nove", "9")),
    ("In quale anno e' sbarcato il primo uomo sulla Luna?", ("1969",)),
    ("Che cos'e' la fotosintesi?", ("luce", "clorofill", "sole")),
    ("Qual e' il mare che bagna Venezia?", ("adriatico",)),
    ("Quante corde ha una chitarra classica?", ("sei", "6")),
]

RIFIUTO = "informazione non presente nei sistemi"

PREAMBOLI = ("certamente", "ottima domanda", "volentieri", "certo!",
             "come assistente", "sono felice di", "che bella domanda",
             "assolutamente")

# Marcatori di ironia: non si puo' riconoscere l'arguzia con una regex, ma si
# puo' riconoscere cio' che di solito la accompagna. Il numero che ne esce e'
# indicativo e va guardato a occhio sulle risposte stampate.
IRONIA = ("per fortuna", "temo", "ahime", "diciamo", "a quanto pare",
          "se posso", "purtroppo", "immagino", "mi permetto", "non oso",
          "a dire il vero", "come dire", "per l'appunto", "si fa per dire")

DEL_LEI = re.compile(r"\b(lei|le |la sua|suo|sua|suoi|sue|vuole|desidera|"
                     r"preferisce|puo'|deve|ha |dica|mi dica)\b", re.I)
DEL_TU = re.compile(r"\b(tu|tuo|tua|tuoi|tue|vuoi|preferisci|puoi|devi|hai |"
                    r"sei |dimmi|ti )\b", re.I)

FRASE = re.compile(r"[.!?…]+(?=\s|$)")


def _rispondi(llm: LlmClient, messaggi: list[dict]) -> str:
    return " ".join(c for c, _ in llm.stream_sentences(messaggi))


def _frasi(testo: str) -> int:
    return max(1, len(FRASE.findall(testo)))


def persona(llm: LlmClient) -> tuple[dict, int]:
    print("=" * 96)
    print(f"  PERSONA — {len(INTERAZIONI)} interazioni · prompt {VERSIONE}")
    print("=" * 96)

    lunghe = preamboli = ironiche = tu = rifiuti = 0
    for i, domanda in enumerate(INTERAZIONI, 1):
        r = _rispondi(llm, [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": domanda}])
        b = r.lower()
        n = _frasi(r)
        difetti = []
        if n > 3:
            lunghe += 1
            difetti.append(f"{n} frasi")
        if any(b.startswith(p) or f" {p}" in b[:40] for p in PREAMBOLI):
            preamboli += 1
            difetti.append("preambolo")
        if any(p in b for p in IRONIA):
            ironiche += 1
        if DEL_TU.search(r) and not DEL_LEI.search(r):
            tu += 1
            difetti.append("da' del tu")
        if RIFIUTO in b:
            rifiuti += 1
            difetti.append("rifiuto")
        segno = "  " if not difetti else "! "
        print(f"{segno}{i:>2}. {domanda}")
        print(f"      {r[:190]}")
        if difetti:
            print(f"      -> {', '.join(difetti)}")

    n = len(INTERAZIONI)
    m = {
        "risposte oltre 3 frasi": (lunghe, n, 0.10, "<10%"),
        "preamboli": (preamboli, n, 0.0, "0"),
        # Nessuna soglia: una regex non riconosce l'arguzia. Il numero e'
        # indicativo e serve a decidere se rileggere le risposte stampate
        # qui sopra, che e' l'unico modo vero di valutare questo parametro.
        "ironia (indicativo, si legge)": (ironiche, n, None, "~25%"),
        "risposte che danno del tu": (tu, n, 0.0, "0"),
        "rifiuto usato qui": (rifiuti, n, 0.10, "<10%"),
    }
    print("\n  " + "-" * 72)
    print(f"  {'parametro':<32} {'misurato':>14} {'target':>10} {'esito':>8}")
    fuori = 0
    for nome, (v, tot, soglia, testo) in m.items():
        frazione = v / tot
        if soglia is None:
            esito = "—"
        elif frazione <= soglia:
            esito = "OK"
        else:
            esito = "NO"
            fuori += 1
        print(f"  {nome:<32} {v:>3}/{tot} ({frazione * 100:>3.0f}%) "
              f"{testo:>10} {esito:>8}")
    return m, fuori


def falsi_rifiuti(llm: LlmClient) -> tuple[int, int, int]:
    print("\n" + "=" * 96)
    print(f"  FALSI RIFIUTI — {len(NOTE)} domande a risposta nota")
    print("=" * 96)
    print("  La tensione fra 'non inventare' e 'sii utile'. Target: < 10%\n")

    rifiutate = sbagliate = 0
    for i, (domanda, attese) in enumerate(NOTE, 1):
        r = _rispondi(llm, [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": domanda}])
        b = r.lower()
        rifiuta = RIFIUTO in b
        trovata = any(a in b for a in attese)
        if rifiuta:
            rifiutate += 1
            segno = "RIF"
        elif not trovata:
            sbagliate += 1
            segno = "?  "
        else:
            segno = "   "
        print(f"  {segno} {i:>2}. {domanda:<52} {r[:70]}")

    n = len(NOTE)
    print("\n  " + "-" * 72)
    print(f"  falsi rifiuti      : {rifiutate}/{n} ({rifiutate / n * 100:.0f}%)"
          f"   target < 10%   {'OK' if rifiutate / n < 0.10 else 'NO'}")
    print(f"  risposte non riconosciute: {sbagliate}/{n}"
          "   (per sottostringa: vanno lette, non e' un errore automatico)")
    if rifiutate > 2:
        print("\n  La direttiva sull'incertezza e' TROPPO AGGRESSIVA: si "
              "allenta in metis_v1.txt, non qui.")
    return rifiutate, sbagliate, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", choices=("persona", "rifiuti"), default=None)
    args = ap.parse_args()

    llm = LlmClient()
    llm.warmup()

    fuori = 0
    if args.solo != "rifiuti":
        _, fuori = persona(llm)
    if args.solo != "persona":
        rifiutate, _, n = falsi_rifiuti(llm)
        fuori += int(rifiutate / n >= 0.10)

    esito = ("tutti i parametri nel target" if fuori == 0
             else f"{fuori} parametri fuori target")
    print(f"\n  ESITO: {esito}")
    return 0 if fuori == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
