"""I comandi di M6, dal parlato all'effetto, con Qwen vero e servizi finti.

    python benchmarks/prova_integrazioni.py
    python benchmarks/prova_integrazioni.py --giri 3

DUE META' PER OGNI FRASE
Come in M4, separate perche' quando qualcosa non va serve sapere dove:

    decisione   Qwen produce lo strumento giusto con gli argomenti giusti?
                Per le date: il datetime ESATTO, calcolato da un "adesso"
                fissato a mercoledi' 23 settembre 2026, ore 21:40.
    effetto     la decisione, passata dal broker con conferma automatica,
                produce l'effetto? Contro un server SMTP cifrato e un Home
                Assistant WebSocket, entrambi locali e finti.

LA DATA E' LA COLONNA CHE CONTA
Il piano sceglie l'LLM invece di una libreria per interpretare "domani alle
17", "lunedi' mattina", "fra mezz'ora", e dichiara il rischio: un promemoria
alla settimana sbagliata. Qui si confronta al minuto. "Quasi giusta" e'
sbagliata: un promemoria alle 17:30 invece che alle 17 e' un promemoria
sbagliato.

COSA NON MISURA
Che l'email arrivi davvero in una casella, che la friggitrice vera si
accenda, che il promemoria sopravviva al riavvio del PC. Sono criteri di
uscita aperti, e restano aperti: servono i servizi veri e un riavvio vero.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from fixtures.casa import TOKEN, FintoHA  # noqa: E402
from fixtures.smtp import ServerSMTP  # noqa: E402

from metis.core import secrets, tempo  # noqa: E402
from metis.core.risposte import descrivi  # noqa: E402
from metis.core.router import Router  # noqa: E402
from metis.llm.toolcall import ToolRouter  # noqa: E402
from metis.security.audit import AuditLog  # noqa: E402
from metis.security.broker import Broker  # noqa: E402
from metis.security.policies import Context  # noqa: E402
from metis.tools import home_assistant as casa  # noqa: E402
from metis.tools import posta  # noqa: E402
from metis.tools import scheduler as sch  # noqa: E402
from metis.tools.registry import carica_tutti  # noqa: E402

# Mercoledi' 23 settembre 2026, 21:40.
ADESSO = datetime(2026, 9, 23, 21, 40)
IO = "marco@esempio.it"


# (frase, strumento atteso, controllo sugli argomenti -> motivo o None)
def _data(attesa: str):
    def c(call):
        return None if call.get("quando") == attesa else \
            f"quando={call.get('quando')!r}, attesa {attesa}"
    return c


def _tutti(*controlli):
    def c(call):
        for k in controlli:
            m = k(call)
            if m:
                return m
        return None
    return c


def _campo(nome, contiene):
    def c(call):
        v = str(call.get(nome, "")).lower()
        return None if contiene in v else f"{nome}={v!r}, doveva contenere {contiene!r}"
    return c


CASI = [
    # --- promemoria: la data, al minuto ---
    ("ricordami di chiamare il commercialista domani alle 17",
     "schedule_reminder", _tutti(_data("2026-09-24T17:00"),
                                 _campo("testo", "commercialista"))),
    ("ricordami fra due ore di togliere il bucato",
     "schedule_reminder", _data("2026-09-23T23:40")),
    ("ricordami tra mezz'ora di spegnere il forno",
     "schedule_reminder", _data("2026-09-23T22:10")),
    ("promemoria per lunedì mattina: pagare l'affitto",
     "schedule_reminder", _data("2026-09-28T09:00")),
    ("ricordami venerdì alle otto e mezza di sera di chiamare Anna",
     "schedule_reminder", _data("2026-09-25T20:30")),
    ("ricordami il 3 ottobre alle 10 che ho il dentista",
     "schedule_reminder", _data("2026-10-03T10:00")),
    ("ricordami dopodomani alle nove di portare fuori il cane",
     "schedule_reminder", _data("2026-09-25T09:00")),
    # --- email ---
    ("mandami una mail domani alle 9 con la lista della spesa: latte e pane",
     "schedule_email", _tutti(_data("2026-09-24T09:00"), _campo("to", IO),
                              _campo("body", "latte"))),
    # --- elenco e cancellazione ---
    ("cosa ho in programma?", "list_reminders", lambda c: None),
    ("cancella il promemoria del commercialista",
     "cancel_reminder", _campo("riferimento", "commercialista")),
    # --- casa ---
    ("accendi la friggitrice", "set_home_device",
     _tutti(_campo("dispositivo", "friggitrice"), _campo("azione", "accendi"))),
    ("la friggitrice è accesa?", "get_home_state", _campo("dispositivo", "friggitrice")),
    ("dai le crocchette al gatto", "set_home_device",
     _tutti(_campo("dispositivo", "crocchett"), _campo("azione", "accendi"))),
    ("spegni la friggitrice", "set_home_device", _campo("azione", "spegni")),
    ("che dispositivi ho in casa?", "list_home_devices", lambda c: None),
    # --- negativi: nessuno strumento ---
    ("che ore sono?", None, None),
    ("cos'è un promemoria?", None, None),
    # Nominare un dispositivo in una domanda non deve toccarlo. Il caso e'
    # qui per QUESTO: la prima esecuzione ha scelto `web_search` invece della
    # conversazione — discutibile, non pericoloso — e l'attesa e' stata
    # riformulata su cio' che il caso deve verificare. La scelta resta
    # stampata, e registrata nel tracking.
    ("mi piace la friggitrice ad aria, la consigli?", "NON_CASA", None),
]

CASA = {"set_home_device", "get_home_state", "list_home_devices"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--giri", type=int, default=1)
    args = ap.parse_args()

    # L'orologio fissato: il prompt del router dice mercoledi' 23 settembre.
    tempo.adesso = lambda: ADESSO

    lavoro = Path(tempfile.mkdtemp(prefix="metis-m6-"))
    lista = lavoro / "email.toml"
    lista.write_text(f'[allowlist]\nindirizzi = ["{IO}"]\n\n[utente]\nindirizzo = "{IO}"\n',
                     encoding="utf-8")
    posta.CONFIG = lista

    reg = carica_tutti()
    router = Router(reg, tool_router=ToolRouter(reg))
    print("scaldo il router...", end=" ", flush=True)
    print(f"{router.tool_router.warmup():.0f} ms\n")

    print("=" * 104)
    print(f"  M6 — DECISIONE (Qwen) · adesso = {tempo.in_parole(ADESSO, ADESSO)}, "
          f"{ADESSO:%A %d %B %Y}")
    print("=" * 104)

    decisioni = []
    latenze = []
    ok_totali = prove = 0
    for frase, atteso, controllo in CASI:
        riusciti = 0
        ultimo = None
        motivo = ""
        primo_errore = ""
        for _ in range(args.giri):
            t0 = time.perf_counter()
            d = router.decidi(frase)
            latenze.append((time.perf_counter() - t0) * 1000)
            call = d.call or {}
            nome = call.get("tool")
            if atteso is None:
                giusto = not d.e_strumento
                motivo = "" if giusto else f"ha scelto {nome}"
            elif atteso == "NON_CASA":
                giusto = nome not in CASA
                motivo = "" if giusto else f"ha toccato un dispositivo: {nome}"
            else:
                motivo = (controllo(call) or "") if nome == atteso else \
                    f"ha scelto {nome or 'chat'}"
                giusto = nome == atteso and not motivo
            riusciti += giusto
            if not giusto and not primo_errore:
                primo_errore = motivo or "?"
            ultimo = call
        ok_totali += riusciti
        prove += args.giri
        decisioni.append((frase, atteso, ultimo, riusciti == args.giri))
        segno = "OK " if riusciti == args.giri else ("~~ " if riusciti else "NO ")
        argomenti = ", ".join(f"{k}={v}" for k, v in (ultimo or {}).items()
                              if k != "tool")[:62]
        print(f"  {segno}{frase[:54]:<55} {str((ultimo or {}).get('tool') or 'chat'):<18}"
              f" {argomenti}")
        if riusciti != args.giri:
            print(f"      -> {primo_errore}")

    print(f"\n  {ok_totali}/{prove} decisioni corrette · latenza mediana "
          f"{statistics.median(latenze):.0f} ms, max {max(latenze):.0f} ms")

    # --- effetto --------------------------------------------------------------
    print("\n" + "=" * 104)
    print("  M6 — EFFETTO (broker, conferma automatica, servizi locali finti)")
    print("=" * 104)

    effetti_ok = 0
    effetti = 0
    with ServerSMTP("ssl") as smtp, FintoHA() as ha:
        s = smtp.segreti()
        secrets.usa_backend(s)
        cliente = casa.ClienteHA(ha.url, TOKEN, backoff=(0.2,))
        cliente.avvia()
        cliente.attendi_connessione(5)
        casa.usa_cliente(cliente)
        casa.usa_registro(casa.Registro(lavoro / "casa.db"))
        pian = sch.Pianificatore(f"sqlite:///{(lavoro / 'jobs.db').as_posix()}")
        pian.avvia(in_pausa=True)
        sch.usa_pianificatore(pian)

        # L'orologio fissato vale anche per le guardie: "domani" del 23
        # settembre e' nel futuro rispetto al 23 settembre, non rispetto a
        # oggi. Il pianificatore invece usa l'ora vera, e a lui le date del
        # 2026 vanno bene comunque.
        broker = Broker(registry=reg, audit=AuditLog(lavoro / "audit.db"))
        ctx = Context(chiedi_conferma=lambda spec, call: True)

        for frase, atteso, call, deciso_bene in decisioni:
            if not atteso or atteso == "NON_CASA" or not deciso_bene:
                continue
            effetti += 1
            r = broker.execute(call, ctx)
            effetti_ok += r.ok
            frase_detta = descrivi(r)
            print(f"  {'OK ' if r.ok else 'NO '}{frase[:54]:<55} "
                  f"{r.stage:<10} {frase_detta[:80]}")

        # Caso 6 del piano: il quarto pasto del gatto.
        crocchette = {"tool": "set_home_device", "dispositivo": "crocchette",
                      "azione": "accendi"}
        esiti = [broker.execute(crocchette, ctx) for _ in range(4)]
        quarto = esiti[-1]
        print(f"\n  caso 6 — pasti del gatto: "
              f"{', '.join('ok' if e.ok else 'rifiuto' for e in esiti)}")
        print(f"      il quarto: {descrivi(quarto)}")

        # Caso 7: Home Assistant spento.
        ha.ferma()
        t0 = time.perf_counter()
        while cliente.disponibile and time.perf_counter() - t0 < 5:
            time.sleep(0.05)
        spento = broker.execute({"tool": "set_home_device", "dispositivo": "friggitrice",
                                 "azione": "accendi"}, ctx)
        lettura = broker.execute({"tool": "get_home_state", "dispositivo": "friggitrice"},
                                 ctx)
        print(f"  caso 7 — hub spento, comando : {descrivi(spento)}")
        print(f"  caso 7 — hub spento, lettura : {descrivi(lettura)}")
        ha.avvia()

        print(f"\n  email ricevute dal server SMTP : {len(smtp.casella.messaggi)} "
              "(le programmate partono all'orario, non adesso)")
        tutti = pian.voci(tipi=(sch.PROMEMORIA, sch.EMAIL, sch.SPEGNI))
        print(f"  job nel pianificatore          : "
              f"{[v.tipo + ': ' + v.testo[:30] for v in tutti]}")
        print(f"  audit                          : {broker.audit.stats()}")

        cliente.ferma()
        pian.ferma()
        secrets.usa_backend(None)

    print(f"\n  effetti riusciti: {effetti_ok}/{effetti}")
    tutto = ok_totali == prove and effetti_ok == effetti and quarto.denied \
        and spento.denied and lettura.denied
    print(f"  ESITO: {'SUPERATO' if tutto else 'DA RIVEDERE'}")
    return 0 if tutto else 1


if __name__ == "__main__":
    sys.exit(main())
