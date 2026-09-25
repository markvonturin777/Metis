"""Quanto cresce il TTFT al crescere del contesto?
Il benchmark principale usa prompt minimi: NFR-2 chiede <400 ms a 2k token."""
import time
import ollama

FILLER = ("Nota di contesto operativo numero {i}: il sistema ha registrato "
          "un evento di telemetria con valori nella norma e nessuna anomalia. ")

def build(target_tokens: int) -> str:
    # ~20 token per nota -> approssimazione sufficiente per lo sweep
    n = max(1, target_tokens // 20)
    return "".join(FILLER.format(i=i) for i in range(n))

def measure(ctx_tokens: int, runs: int = 3) -> tuple[float, int]:
    ttfts = []
    for _ in range(runs):
        msgs = [
            {"role": "system", "content": "Sei Metis. Rispondi in italiano, una frase."},
            {"role": "user", "content": build(ctx_tokens)
             + "\n\nDomanda: quanti eventi ho elencato, all'incirca?"},
        ]
        t0 = time.perf_counter(); ttft = None; ptokens = 0
        for ch in ollama.chat(model="qwen3:8b", messages=msgs, stream=True,
                              think=False, options={"num_ctx": 8192, "temperature": 0.3}):
            if ch.get("message", {}).get("content"):
                if ttft is None:
                    ttft = time.perf_counter() - t0
            if ch.get("done"):
                ptokens = ch.get("prompt_eval_count", 0)
        ttfts.append(ttft * 1000)
    return sum(ttfts) / len(ttfts), ptokens

print(f"{'prompt reale':>14} | {'TTFT medio':>11} | esito NFR-2")
print("-" * 46)
for target in (100, 500, 2000, 4000):
    ttft, ptok = measure(target)
    flag = "OK" if ttft < 400 else "SFORA"
    print(f"{ptok:>10} tok | {ttft:>8.0f} ms | {flag}")
