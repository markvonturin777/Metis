"""Il promemoria sopravvive al riavvio? Due PROCESSI, non due oggetti.

    python benchmarks/prova_riavvio.py

COSA FA
    1. un processo programma quattro promemoria e un'email, poi termina
    2. si aspetta che due di quegli orari passino, con nessun processo vivo
    3. un secondo processo, che non ha niente in memoria del primo, riapre
       `jobs.db` e riferisce cosa trova e cosa scatta

La suite lo simula con due pianificatori nello stesso processo; qui i due
non condividono nemmeno l'interprete Python. E' il passo intermedio fra la
suite e il riavvio vero del PC, che resta un criterio di uscita da fare a
mano: spegnere il computer e' l'unico modo di sapere che cosa fa Windows ai
processi e ai file aperti quando si spegne.

I quattro promemoria coprono i quattro casi che contano:

    in orario, ancora futuro        deve restare in coda
    scaduto 3 s fa, a PC spento     deve scattare alla riaccensione
    scaduto 2 ore fa                deve scattare DICENDO il ritardo
    email scaduta 2 ore fa          NON deve partire, e deve dirlo
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]

PROGRAMMA = r"""
import sys
from datetime import datetime, timedelta
sys.path.insert(0, sys.argv[2])
from metis.tools import scheduler as sch
url = f"sqlite:///{sys.argv[1]}"
p = sch.Pianificatore(url)
p.avvia(in_pausa=True)
ora = datetime.now().replace(microsecond=0)
p.promemoria("domani: chiamare il commercialista", (ora + timedelta(days=1)).replace(second=0))
p.promemoria("fra tre secondi: prendere le medicine", ora + timedelta(seconds=3))
p.promemoria("due ore fa: stendere il bucato", (ora - timedelta(hours=2)).replace(second=0))
p.email("marco@esempio.it", "due ore fa: lista della spesa", "latte",
        (ora - timedelta(hours=2)).replace(second=0))
print(len(p.voci()))
p.ferma()
"""

RIAPERTURA = r"""
import json, sys, time
sys.path.insert(0, sys.argv[2])
from metis.tools import scheduler as sch
ricevuti = []
for tipo in (sch.PROMEMORIA, sch.EMAIL):
    sch.imposta_consegna(tipo, lambda d: ricevuti.append(
        {"tipo": d["tipo"], "testo": d["testo"], "in_ritardo": d["in_ritardo"],
         "ritardo_min": d["ritardo_s"] // 60}))
p = sch.Pianificatore(f"sqlite:///{sys.argv[1]}")
p.avvia()
time.sleep(3)
rimasti = [v.testo for v in p.voci()]
p.ferma()
print(json.dumps({"scattati": ricevuti, "rimasti": rimasti}))
"""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = Path(tempfile.mkdtemp(prefix="metis-riavvio-")) / "jobs.db"

    print("=" * 84)
    print("  RIAVVIO — due processi che condividono solo data/jobs.db")
    print("=" * 84)

    a = subprocess.run([sys.executable, "-W", "ignore", "-c", PROGRAMMA,
                        db.as_posix(), str(RADICE)],
                       capture_output=True, text=True, timeout=60)
    if a.returncode != 0:
        print(a.stderr[-800:])
        return 1
    print(f"\n  processo 1: programmati {a.stdout.strip()} elementi, poi terminato")

    print("  nessun processo vivo per 5 secondi...", flush=True)
    time.sleep(5)

    b = subprocess.run([sys.executable, "-W", "ignore", "-c", RIAPERTURA,
                        db.as_posix(), str(RADICE)],
                       capture_output=True, text=True, timeout=60)
    if b.returncode != 0:
        print(b.stderr[-800:])
        return 1
    esito = json.loads(b.stdout.strip().splitlines()[-1])
    rumore = [r for r in b.stderr.splitlines() if "Error" in r or "Traceback" in r]

    print("\n  processo 2, riaperto dopo il 'riavvio':")
    for s in esito["scattati"]:
        stato = f"IN RITARDO di {s['ritardo_min']} min" if s["in_ritardo"] \
            else f"in orario (ritardo {s['ritardo_min']} min)"
        print(f"    scattato  {s['tipo']:<11} {s['testo']:<42} {stato}")
    for t in esito["rimasti"]:
        print(f"    in coda   {t}")
    print(f"    errori nel log del processo 2: {len(rumore)}")

    per_testo = {s["testo"]: s for s in esito["scattati"]}
    medicine = per_testo.get("fra tre secondi: prendere le medicine")
    bucato = per_testo.get("due ore fa: stendere il bucato")
    email = per_testo.get("due ore fa: lista della spesa")
    controlli = {
        "il futuro resta in coda":
            esito["rimasti"] == ["domani: chiamare il commercialista"],
        "lo scaduto a PC spento scatta, in orario":
            medicine is not None and not medicine["in_ritardo"],
        "lo scaduto da ore scatta, IN RITARDO":
            bucato is not None and bucato["in_ritardo"],
        "l'email scaduta da ore arriva alla consegna come in ritardo":
            email is not None and email["in_ritardo"],
        "nessun errore nel log": not rumore,
    }
    print()
    for nome, ok in controlli.items():
        print(f"  {'OK ' if ok else 'NO '} {nome}")
    print("\n  (che l'email in ritardo NON parta lo decide la consegna: "
          "tests/test_scheduler.py::test_un_email_in_ritardo_non_parte)")
    tutto = all(controlli.values())
    print(f"\n  ESITO: {'SUPERATO' if tutto else 'DA RIVEDERE'} — il riavvio del PC "
          "vero resta da fare a mano")
    return 0 if tutto else 1


if __name__ == "__main__":
    sys.exit(main())
