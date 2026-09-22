"""Il percorso web contro la rete vera, dal broker alla risposta fondata.

    python benchmarks/prova_web.py
    python benchmarks/prova_web.py --senza-rete     # la degradazione dichiarata

COSA MISURA
Quattro cose che la suite non puo' misurare perche' dipendono da internet:

    la latenza vera del percorso      1,5-4 s secondo il piano
    quanto testo torna davvero        e quindi se il budget e' tarato giusto
    se le fonti reggono l'estrazione  i siti veri non sono il corpus di prova
    la degradazione                   con la rete staccata, cosa dice Metis

PERCHE' PASSA DAL BROKER E NON DA `web.cerca`
Perche' e' come gira in esercizio. Chiamare `cerca()` direttamente
misurerebbe la libreria; qui si misura il percorso, compresi la validazione
dello schema, l'audit e il `Consulente` che compone entro il budget. Se un
giorno una policy rifiutasse `web_search`, questo banco se ne accorgerebbe e
una prova sulla libreria no.

LA CACHE FALSA LE MISURE, QUINDI SI SVUOTA
La seconda esecuzione di fila sarebbe istantanea e direbbe che il percorso
web costa 40 ms. Si svuota all'inizio, salvo `--con-cache` per quando si sta
lavorando su altro e serve solo che il percorso funzioni.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from metis.llm.grounding import BUDGET, Consulente, conta_token
from metis.security.audit import AuditLog
from metis.security.broker import Broker
from metis.security.policies import Context
from metis.tools import web
from metis.tools.registry import carica_tutti

DOMANDE = [
    "andamento del BTP decennale",
    "ultime notizie sui mercati europei",
    "previsioni meteo Milano domani",
    "quando esce la prossima versione di Python",
    "risultati serie A ultima giornata",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--con-cache", action="store_true",
                    help="non svuota la cache: le misure non valgono")
    ap.add_argument("--senza-rete", action="store_true",
                    help="simula la rete assente e verifica la degradazione")
    args = ap.parse_args()

    reg = carica_tutti()
    broker = Broker(registry=reg, audit=AuditLog())

    def esegui(call: dict, untrusted: bool):
        return broker.execute(call, Context(has_untrusted_content=untrusted))

    consulente = Consulente(esegui)

    if args.senza_rete:
        return _degradazione(consulente)

    if not args.con_cache:
        web.CACHE.svuota()

    print("=" * 84)
    print("  PERCORSO WEB — ricerca, lettura, composizione entro il budget")
    print("=" * 84)
    print(f"  budget fonti: {BUDGET['web']} token · max {web.MAX_FONTI} fonti "
          f"· timeout {web.TIMEOUT_FETCH_S:.0f} s · max {web.MAX_BYTE // 1024} KB\n")
    print(f"  {'domanda':<42} {'fonti':>5} {'token':>6} {'tronc':>6} {'ms':>7}")
    print("  " + "-" * 70)

    tempi, token, ok = [], [], 0
    fallite = []
    for d in DOMANDE:
        t0 = time.perf_counter()
        ctx = consulente.consulta(d)
        ms = (time.perf_counter() - t0) * 1000
        tempi.append(ms)
        if ctx.ok:
            ok += 1
            token.append(ctx.token)
        else:
            fallite.append((d, ctx.motivo))
        segno = "  " if ctx.ok else "NO"
        print(f"{segno}{d:<42} {len(ctx.fonti):>5} {ctx.token:>6} "
              f"{ctx.troncate:>6} {ms:>7.0f}")

    print("\n  " + "-" * 70)
    print(f"  consultazioni riuscite : {ok}/{len(DOMANDE)}")
    if tempi:
        print(f"  latenza                : mediana {statistics.median(tempi):.0f} ms  "
              f"min {min(tempi):.0f}  max {max(tempi):.0f}   (piano: 1500-4000)")
    if token:
        print(f"  token per consultazione: mediana {statistics.median(token):.0f}  "
              f"max {max(token)}   (budget {BUDGET['web']})")
        sforate = [t for t in token if t > BUDGET["web"]]
        print(f"  consultazioni fuori budget: {len(sforate)}")
    s = web.STATO
    print(f"  motori usati           : {', '.join(s.motori) or '—'}")
    print(f"  tentativi falliti      : {s.tentativi_falliti}   "
          f"fallback: {s.fallback_usato}   da cache: {s.da_cache}")
    if s.ultimo_errore:
        print(f"  ultimo errore          : {s.ultimo_errore[:90]}")
    for d, motivo in fallite:
        print(f"  ! {d}: {motivo[:70]}")

    # --- cosa e' arrivato davvero -----------------------------------------

    ultimo = consulente.ultimo
    if ultimo is not None and ultimo.fonti:
        print("\n  " + "-" * 70)
        print("  ULTIMA CONSULTAZIONE — cosa e' finito nel prompt\n")
        for f in ultimo.fonti:
            print(f"   [{f.id}] {f.url[:70]}")
            print(f"       {conta_token(f.testo):>5} token  "
                  f"{len(f.testo):>6} caratteri  "
                  f"{'TRONCATA' if f.testo.endswith('[…]') else ''}")
            print(f"       {f.testo[:150]}...")
        print(f"\n  delimitatori di apertura: "
              f"{ultimo.blocco().count('<<<FONTE_ESTERNA_NON_FIDATA')} "
              f"(atteso {len(ultimo.fonti)})")
        print(f"  delimitatori di chiusura: "
              f"{ultimo.blocco().count('<<<FINE_FONTE_ESTERNA')} "
              f"(atteso {len(ultimo.fonti)})")

    # --- la cache ----------------------------------------------------------

    print("\n  " + "-" * 70)
    t0 = time.perf_counter()
    consulente.consulta(DOMANDE[0])
    ms_cache = (time.perf_counter() - t0) * 1000
    print(f"  stessa domanda, seconda volta: {ms_cache:.0f} ms "
          f"(prima: {tempi[0]:.0f} ms)")

    print(f"\n  audit: {broker.audit.stats()}")
    return 0 if ok == len(DOMANDE) else 1


def _degradazione(consulente: Consulente) -> int:
    """La prova che vale piu' di tutte le altre: cosa succede quando le fonti
    non ci sono. Deve uscire una frase, non una risposta a memoria."""
    import metis.tools.web as w

    print("=" * 84)
    print("  DEGRADAZIONE DICHIARATA — tutti i motori irraggiungibili")
    print("=" * 84)

    def morto(query, n):
        raise RuntimeError("[simulato] rete assente")

    salvati = w.MOTORI
    w.MOTORI = (("ddg", morto), ("brave", morto), ("searxng", morto))
    w.CACHE.svuota()
    try:
        t0 = time.perf_counter()
        ctx = consulente.consulta("quanto rende il btp decennale oggi")
        ms = (time.perf_counter() - t0) * 1000
    finally:
        w.MOTORI = salvati

    print(f"\n  ok            : {ctx.ok}")
    print(f"  fonti         : {len(ctx.fonti)}")
    print(f"  contaminato   : {ctx.contaminato}")
    print(f"  motivo        : {ctx.motivo}")
    print(f"  tempo         : {ms:.0f} ms  (backoff 1+3 s per motore)")
    print(f"  messaggio al modello: {ctx.messaggio('x')[:80]}")

    buono = (not ctx.ok and not ctx.fonti
             and "raggiungibili" in ctx.motivo.lower())
    print(f"\n  ESITO: {'degradazione dichiarata, nessuna fonte inventata'
                        if buono else '!! la degradazione non e dichiarata'}")
    print("  (il turno finisce qui: l'orchestratore non chiama il modello, "
          "vedi `_percorso_web`)")
    return 0 if buono else 1


if __name__ == "__main__":
    sys.exit(main())
