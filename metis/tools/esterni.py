"""T3 — effetti fuori da questa macchina.

Un'azione T3 non si annulla: una email inviata e' inviata. Per questo il
flusso di conferma e' stato esercitato da M2, quando `send_email` era
registrato senza corpo e percorreva tutta la catena fermandosi sull'ultimo
scalino. In M6 l'ultimo scalino c'e': la capacita' e' arrivata, e la catena
e' rimasta quella provata cinquanta volte di fila per NFR-9.

L'invio vero sta in `posta.py`. Qui c'e' solo il perimetro: tier, guardia
sul destinatario, e cosa vede chi conferma.
"""

from __future__ import annotations

from metis.llm.schemas import SendEmail
from metis.security.audit import Tier
from metis.security.guards import Guard
from metis.tools import posta
from metis.tools.registry import REGISTRY

# La guardia sul destinatario. Non immediata: l'allowlist non cambia nei
# millisecondi fra l'autorizzazione e l'invio, e `posta.invia` la ricontrolla
# comunque da sola.
GUARDIA_DESTINATARIO = Guard(
    "destinatario", lambda call: posta.motivo_destinatario(call.to))


def presenta_email(call) -> dict[str, str]:
    """A chi, cosa, e il corpo INTERO. Vedi `registry.presentazione`."""
    return {"a": call.to, "oggetto": call.subject, "corpo": call.body}


@REGISTRY.strumento(Tier.T3, SendEmail, guards=(GUARDIA_DESTINATARIO,),
                    presenta=presenta_email)
def _send_email(call: SendEmail) -> dict:
    """Invia una email a un destinatario autorizzato. Conferma obbligatoria."""
    return posta.invia(call.to, call.subject, call.body)
