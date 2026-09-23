"""Configura le credenziali di Metis nel Credential Manager di Windows.

    python scripts/setup_secrets.py            chiede le chiavi mancanti
    python scripts/setup_secrets.py --tutte    chiede anche quelle gia' presenti
    python scripts/setup_secrets.py --stato    mostra cosa c'e', senza chiedere
    python scripts/setup_secrets.py --cancella ha_token

Si lancia una volta. I valori finiscono cifrati nel Credential Manager
(Pannello di controllo > Gestione credenziali > Credenziali generiche, voci
"metis") e non vengono mai scritti su file.

Le chiavi segrete si digitano senza eco. Invio a vuoto lascia la chiave com'e':
cosi' si puo' ripassare lo script per aggiungere solo Home Assistant senza
riscrivere la password SMTP.

GMAIL
Serve una **password per app**, non la password dell'account: Account Google
> Sicurezza > Verifica in due passaggi > Password per le app. Host
smtp.gmail.com, porta 465.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metis.core import secrets  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tutte", action="store_true")
    ap.add_argument("--stato", action="store_true")
    ap.add_argument("--cancella", metavar="CHIAVE")
    args = ap.parse_args()

    if args.cancella:
        secrets.cancella(args.cancella)
        print(f"  {args.cancella}: cancellata")
        return 0

    print("=" * 70)
    print("  Credenziali di Metis — Credential Manager di Windows")
    print("=" * 70)
    for chiave, descrizione in secrets.CHIAVI.items():
        print(f"  {chiave:<15} {secrets.mascherato(chiave):<28} {descrizione}")
    if args.stato:
        return 0

    print("\n  Invio a vuoto lascia la chiave com'e'.\n")
    for chiave, descrizione in secrets.CHIAVI.items():
        if secrets.presente(chiave) and not args.tutte:
            continue
        domanda = f"  {chiave} ({descrizione}): "
        try:
            valore = (getpass.getpass(domanda) if chiave in secrets.SEGRETE
                      else input(domanda))
        except (EOFError, KeyboardInterrupt):
            print("\n  interrotto: le chiavi gia' scritte restano")
            return 1
        if valore.strip():
            secrets.set(chiave, valore)
            print(f"  {chiave}: salvata")

    mancanti = secrets.mancanti()
    print("\n  mancanti: " + (", ".join(mancanti) if mancanti else "nessuna"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
