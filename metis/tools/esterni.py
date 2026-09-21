"""T3 — effetti fuori da questa macchina. Capacita' in M6.

Un'azione T3 non si annulla: una email inviata e' inviata. Per questo il
flusso di conferma va esercitato adesso, mentre il broker si costruisce, e
non quando arrivera' il client SMTP — momento in cui la domanda sara' "come
mando la mail" e non "chi ha detto di mandarla".

Registrato senza corpo, `send_email` percorre tutta la catena: policy,
guardie, **conferma obbligatoria**, e si ferma sull'ultimo scalino. E' cio'
che rende verificabile NFR-9 gia' in M2, su uno strumento che non puo' fare
danni mentre lo si prova cinquanta volte di fila.
"""

from __future__ import annotations

from metis.llm.schemas import SendEmail
from metis.security.audit import Tier
from metis.tools.registry import REGISTRY


@REGISTRY.strumento(Tier.T3, SendEmail, implemented=False)
def _send_email(call: SendEmail) -> dict:
    """Invia una email. Conferma obbligatoria. Capacita' in M6."""
    raise NotImplementedError
