"""Il contatore di token, tarato contro il tokenizzatore vero.

    python benchmarks/prova_contesto.py

COSA MISURA
`grounding.conta_token` e' una stima: caratteri diviso una costante. Tutto il
budget di M5 — quante fonti stanno dentro, quando scatta il riassunto — poggia
su quella costante, e una costante sbagliata produce un difetto che non si
vede: il contesto sfora, il modello dimentica l'inizio della conversazione, e
il sintomo e' "ogni tanto si confonde".

Qui si confronta la stima con `prompt_eval_count`, che e' quanti token Ollama
ha davvero messo nel contesto. E' la verita', e costa una chiamata a vuoto.

COSA SIGNIFICA "TARATA BENE"
**Non** che l'errore sia piccolo: che sia sempre dallo stesso lato. Un
contatore che sottostima anche del cinque per cento e' un budget che non
esiste. Il rapporto caratteri/token va quindi tenuto SOTTO il minimo
misurato, non sulla media.
"""

from __future__ import annotations

import sys
from pathlib import Path

import ollama

from metis.llm.grounding import (
    BUDGET,
    CARATTERI_PER_TOKEN,
    COSTO_NON_LETTERA,
    CONTESTO_MAX,
    componi,
    conta_messaggi,
    conta_token,
)
from metis.llm.prompts import SYSTEM
from metis.memory.conversation import Memoria

MODEL = "qwen3:8b"

CARTELLA_CORPUS = Path("tests/fixtures/injection")

# Testi di natura diversa: la densita' di token non e' la stessa su una frase
# parlata, su un articolo e su un blocco con i delimitatori. Tarare solo sul
# secondo darebbe un contatore che sbaglia proprio sul primo, cioe' sulla
# memoria conversazionale.
CAMPIONI: list[tuple[str, str]] = [
    ("parlato breve", "Apri Chrome e mettilo sull'altro schermo."),
    ("parlato medio",
     "Senti, mi sapresti dire com'e' andata la seduta dei mercati europei "
     "ieri? Mi interessa soprattutto il comparto bancario, e se puoi anche "
     "lo spread rispetto ai bund tedeschi."),
    ("risposta di Metis",
     "Milano ha chiuso in rialzo dell'uno virgola due per cento, sostenuta "
     "dalle banche. Lo spread si e' ristretto leggermente."),
    ("system prompt", SYSTEM),
    ("numeri e sigle",
     "BTP 10Y 3,75% · BUND 2,41% · spread 134 bp · FTSE MIB +1,2% · "
     "EUR/USD 1,0842 · VIX 14,3 · Brent 78,45 USD"),
]


def _token_veri(testo: str, client: ollama.Client) -> int:
    """Quanti token entrano davvero nel contesto per questo testo.

    Si misura per DIFFERENZA contro un prompt vuoto: `prompt_eval_count`
    comprende anche i marcatori del template di chat, che non appartengono al
    testo e che falserebbero il rapporto sui campioni corti.
    """
    r = client.chat(model=MODEL, messages=[{"role": "user", "content": testo}],
                    think=False, options={"num_ctx": CONTESTO_MAX,
                                          "num_predict": 1})
    return int(r.get("prompt_eval_count", 0))


def main() -> int:
    client = ollama.Client()
    print("=" * 78)
    print("  CONTATORE DI TOKEN — stima contro prompt_eval_count")
    print("=" * 78)

    # Il costo fisso del template di chat, misurato una volta.
    base = _token_veri("", client)
    print(f"\n  sovrapprezzo del template di chat: {base} token\n")

    print(f"  {'campione':<22} {'car.':>6} {'veri':>6} {'stima':>6} "
          f"{'car/tok':>8} {'margine':>8}")
    print("  " + "-" * 62)

    rapporti = []
    sottostime = 0
    for nome, testo in CAMPIONI:
        veri = max(1, _token_veri(testo, client) - base)
        stima = conta_token(testo)
        rapporto = len(testo) / veri
        rapporti.append(rapporto)
        margine = (stima - veri) / veri * 100
        if stima < veri:
            sottostime += 1
        segno = "  " if stima >= veri else "!!"
        print(f"{segno}{nome:<22} {len(testo):>6} {veri:>6} {stima:>6} "
              f"{rapporto:>8.2f} {margine:>+7.0f}%")

    # Le fonti vere: un blocco con i delimitatori, costruito dal corpus.
    if CARTELLA_CORPUS.exists():
        from metis.tools.web import estrai

        pagine = []
        for f in sorted(CARTELLA_CORPUS.glob("*.html"))[:3]:
            titolo, testo = estrai(f.read_text(encoding="utf-8"))
            pagine.append(_P(f"https://esempio.it/{f.stem}", titolo, testo))
        fonti, _ = componi(pagine)
        blocco = "\n\n".join(x.blocco() for x in fonti)
        veri = max(1, _token_veri(blocco, client) - base)
        stima = conta_token(blocco)
        rapporti.append(len(blocco) / veri)
        if stima < veri:
            sottostime += 1
        segno = "  " if stima >= veri else "!!"
        print(f"{segno}{'3 fonti delimitate':<22} {len(blocco):>6} {veri:>6} "
              f"{stima:>6} {len(blocco) / veri:>8.2f} "
              f"{(stima - veri) / veri * 100:>+7.0f}%")

    minimo = min(rapporti)
    print("\n  " + "-" * 62)
    print(f"  caratteri per token: min {minimo:.2f}  "
          f"medio {sum(rapporti) / len(rapporti):.2f}  max {max(rapporti):.2f}")
    print(f"  costante in uso    : {CARATTERI_PER_TOKEN:.2f} "
          f"piu' {COSTO_NON_LETTERA} per carattere non alfabetico")
    if sottostime == 0:
        print("  ESITO: nessun campione sottostimato. L'errore e' sempre "
              "dallo stesso lato, che e' l'unica cosa che conta.")
    else:
        print(f"  ESITO: !! {sottostime} campioni SOTTOSTIMATI: il budget non "
              "esiste. Alzare COSTO_NON_LETTERA.")

    # --- il caso peggiore: memoria piena piu' tre fonti ---------------------

    print("\n" + "=" * 78)
    print("  IL CASO PEGGIORE — finestra piena, slot pieni, tre fonti")
    print("=" * 78)

    m = Memoria(system=SYSTEM)
    for i in range(30):
        m.aggiungi("user", f"Domanda numero {i} su un argomento qualunque, "
                           "formulata come la direbbe una persona a voce.")
        m.aggiungi("assistant", f"Risposta numero {i}, due frasi brevi come "
                                "prevede la persona. Niente preamboli.")
    slot = ("[CONTESTO CORRENTE]\nFinestra di riferimento: Chrome — "
            "Investing.com (monitor 2)\nUltima app aperta: Visual Studio Code\n"
            "Ultimo argomento cercato: andamento BTP decennale\n"
            "Ultima fonte: https://it.investing.com/rates-bonds/italy-10-year")
    # Fonti VERE, non una stringa di x: una x ripetuta si tokenizza in
    # blocchi enormi e il caso peggiore risulterebbe quattro volte piu'
    # leggero di quello che e'. E' l'errore che ha reso inutile la prima
    # versione di questo banco.
    fonti_blocco = _fonti_di_prova(BUDGET["web"])

    c = m.conteggio(slot, fonti=fonti_blocco)
    messaggi = m.messaggi(slot=slot, domanda=fonti_blocco + "\n\nDomanda: x")
    veri = _token_veri_messaggi(messaggi, client)

    for voce, valore in c.come_dizionario().items():
        print(f"  {voce:<14} {valore}")
    print(f"\n  stimati      {c.totale}")
    print(f"  veri         {veri}")
    print(f"  margine di risposta  {BUDGET['risposta']}")
    print(f"  totale con margine   {veri + BUDGET['risposta']} / {CONTESTO_MAX}")
    esito = veri + BUDGET["risposta"] <= CONTESTO_MAX
    print(f"\n  ESITO: {'entro gli 8k' if esito else '!! SFORA gli 8k'}")
    print(f"  (conta_messaggi sulla sola finestra: {conta_messaggi(m.turni[-16:])})")

    return 0 if esito and sottostime == 0 else 1


def _token_veri_messaggi(messaggi: list[dict], client: ollama.Client) -> int:
    r = client.chat(model=MODEL, messages=messaggi, think=False,
                    options={"num_ctx": CONTESTO_MAX, "num_predict": 1})
    return int(r.get("prompt_eval_count", 0))


def _fonti_di_prova(budget_token: int) -> str:
    """Tre fonti dal corpus, composte entro il budget. Testo vero."""
    from metis.tools.web import estrai

    pagine = []
    for f in sorted(CARTELLA_CORPUS.glob("*.html"))[:3]:
        titolo, testo = estrai(f.read_text(encoding="utf-8"))
        # Le pagine del corpus sono corte: si allungano ripetendole, che e'
        # comunque testo italiano vero e si tokenizza come tale.
        pagine.append(_P(f"https://esempio.it/{f.stem}", titolo, testo * 12))
    fonti, _ = componi(pagine, budget_token)
    return "\n\n".join(x.blocco() for x in fonti)


class _P:
    def __init__(self, url, titolo, testo):
        self.url, self.titolo, self.testo, self.ok = url, titolo, testo, True


if __name__ == "__main__":
    sys.exit(main())
