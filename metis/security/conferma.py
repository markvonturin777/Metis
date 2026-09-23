"""Conferma delle azioni T3. In M2 da console, in M3 diventa una finestra.

COSA DEVE VEDERE CHI CONFERMA
Non "Metis vuole eseguire send_email". Chi conferma deve poter dire di no
sapendo cosa sta per succedere, quindi si mostrano gli argomenti veri, il
livello e il fatto che l'azione non si annulla. Una conferma che non dice
cosa si sta confermando e' un pulsante, non un consenso.

IL DEFAULT E' NO, IN OGNI MODO POSSIBILE
Invio a vuoto: no. Risposta incomprensibile: no. Flusso di input chiuso —
succede quando Metis gira senza console: no. Timeout: lo gestisce il broker,
ed e' no. Non esiste una via che porti a sì senza che qualcuno l'abbia
scritto.

PERCHE' NON "PREMI INVIO PER CONFERMARE"
Vent'anni di finestre di dialogo hanno insegnato a premere Invio prima di
leggere. Qui serve una "s" battuta apposta.
"""

from __future__ import annotations

import sys

SI = frozenset({"s", "si", "sì", "y", "yes", "ok", "conferma"})


def conferma_console(spec, call) -> bool:
    """Chiede conferma sul terminale. Ritorna True solo su un sì esplicito.

    M6: i valori non si troncano piu'. Vedi `registry.presentazione`: si
    conferma cio' che si e' letto, e un corpo di email tagliato a 200
    caratteri e' un'email approvata a meta'.
    """
    from metis.tools.registry import presentazione

    avviso = ("azione NON annullabile" if spec.tier.value == "T3"
              else "controlla che sia quello che intendevi")
    righe = [
        "",
        "  " + "=" * 58,
        f"  CONFERMA RICHIESTA — {spec.tier.value}: {avviso}",
        "  " + "=" * 58,
        f"  strumento : {spec.name}",
    ]
    for campo, testo in presentazione(spec, call).items():
        prima, *resto = testo.splitlines() or [""]
        righe.append(f"  {campo:<10}: {prima}")
        righe.extend(f"  {'':<10}  {r}" for r in resto)
    righe.append("  " + "-" * 58)
    print("\n".join(righe))

    try:
        risposta = input("  Confermi? scrivi 's' per sì, qualunque altra cosa e' no: ")
    except (EOFError, OSError):
        # Nessuna console: non c'e' nessuno che possa acconsentire.
        print("  nessun terminale disponibile: rifiutata")
        return False

    ok = risposta.strip().lower() in SI
    print("  confermata\n" if ok else "  rifiutata\n")
    return ok


def conferma_automatica_no(spec, call) -> bool:
    """Rifiuta sempre. E' il default quando nessuno puo' confermare, ed e'
    anche cio' che si usa nelle prove automatiche perche' una T3 non parta
    per sbaglio."""
    return False


def scegli_conferma(interattivo: bool | None = None):
    """La console vera se c'e' un terminale, altrimenti il rifiuto."""
    if interattivo is None:
        interattivo = sys.stdin is not None and sys.stdin.isatty()
    return conferma_console if interattivo else conferma_automatica_no
