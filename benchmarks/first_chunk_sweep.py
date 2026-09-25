"""Quanto costa il primo chunk al variare del cap?

Misura lo stadio 'prima frase' (dal primo token al primo chunk pronto), che
in M0 e' l'unico rimasto fuori budget. Non serve il microfono: lo stadio e'
interamente LLM + segmentazione.
"""
import warnings
import numpy as np
warnings.filterwarnings("ignore")
from metis.llm.client import LlmClient  # noqa: E402  (dopo filterwarnings)

SYSTEM = ("Sei Metis, assistente personale. Rispondi in italiano, formale con "
          "ironia discreta. MASSIMO DUE FRASI BREVI.")
# prompt che in sessione hanno prodotto le risposte piu' lunghe
PROMPTS = [
    "A che corrente artistica apparteneva Pollock?",
    "Mi sai dire qualcosa della Bauhaus?",
    "Qual e la distanza tra la Terra e il Sole?",
    "Parlami del Ryzen e di quanto consuma rispetto a Intel.",
    "Sai dirmi una citazione famosa sul tempo?",
]

c = LlmClient()
c.warmup()
print(f"{'first_max_chars':>16} | {'prima_frase p50':>16} | {'p95':>7} | "
      f"{'car p50':>8} | budget 330")
print("-" * 72)

for cap in (30, 45, 60, 90, None):
    lat, lens = [], []
    for p in PROMPTS:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": p}]
        for chunk, gm in c.stream_sentences(msgs, first_max_chars=cap, first_min_chars=12):
            # primo chunk: differenza fra quando e' pronto e il primo token
            lat.append(gm.t_first_sentence_ms - (gm.ttft_ms or 0))
            lens.append(len(chunk))
            break
    p50, p95 = np.percentile(lat, 50), np.percentile(lat, 95)
    flag = "OK" if p50 <= 330 else "!!"
    etichetta = str(cap) if cap else "nessuno"
    print(f"{etichetta:>16} | {flag} {p50:>13.0f} ms | {p95:>4.0f} ms | {np.median(lens):>8.0f}")
