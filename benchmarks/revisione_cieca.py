"""La revisione alla cieca della persona (PHASE6, giorno 7).

    python benchmarks/revisione_cieca.py
    python benchmarks/revisione_cieca.py --persone metis_v1 metis_v2

Dieci frasi; a ciascuna rispondono le due persone. Le venti risposte arrivano
mescolate e senza nome: per ognuna un voto da 1 a 5 (Invio = salta). Solo
alla fine lo script dice quale era quale, e le medie.

Il tono di Jarvis non lo misura nessun banco: lo decide chi ci parla. Il
criterio del piano e' "v2 preferita, media >= 3,5".
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from metis.llm import prompts  # noqa: E402
from metis.llm.client import LlmClient  # noqa: E402

FRASI = [
    "Ciao Metis.", "Come stai oggi?", "Quali cose sai fare?", "Sei inutile, lo sai?",
    "Che ne pensi del lunedì mattina?", "Ho sbagliato di nuovo il codice, non funziona niente.",
    "Raccontami qualcosa di interessante.", "Mi consigli un film per stasera?",
    "Sono stanco morto.", "Grazie, per ora basta.",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persone", nargs=2, default=["metis_v1", "metis_v2"])
    ap.add_argument("--seme", type=int, default=None)
    args = ap.parse_args()

    llm = LlmClient()
    print("Genero le risposte (circa un minuto)...")
    risposte = []
    for i, f in enumerate(FRASI):
        for nome in args.persone:
            sistema = prompts.per_turno(nome, i)
            r = " ".join(c for c, _ in llm.stream_sentences(
                [{"role": "system", "content": sistema}, {"role": "user", "content": f}]))
            risposte.append({"frase": f, "persona": nome, "risposta": r})

    random.Random(args.seme).shuffle(risposte)
    print("\nPer ogni risposta: un voto da 1 (pessima) a 5 (proprio Jarvis). Invio = salta.\n")
    for n, r in enumerate(risposte, 1):
        print(f"[{n}/{len(risposte)}]  Lei: {r['frase']}")
        print(f"          Metis: {r['risposta']}")
        while True:
            v = input("          voto> ").strip()
            if v == "":
                r["voto"] = None
                break
            if v in {"1", "2", "3", "4", "5"}:
                r["voto"] = int(v)
                break
            print("          (da 1 a 5, o Invio)")
        print()

    print("=" * 70)
    for nome in args.persone:
        voti = [r["voto"] for r in risposte if r["persona"] == nome and r["voto"]]
        media = sum(voti) / len(voti) if voti else 0.0
        print(f"  {nome}: media {media:.2f} su {len(voti)} voti")
    uscita = Path("benchmarks/results") / f"revisione_cieca_{time.strftime('%Y%m%d_%H%M')}.json"
    uscita.parent.mkdir(parents=True, exist_ok=True)
    uscita.write_text(json.dumps(risposte, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  risposte e voti in {uscita}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
