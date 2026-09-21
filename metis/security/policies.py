"""Politiche per livello di capacita'. Cosa vale per TUTTI gli strumenti di
un certo tier, indipendentemente da cosa facciano.

    T0  sola lettura            passa sempre, log leggero
    T1  reversibile             passa, log completo
    T2  input sintetico         kill switch + guardie, log con la finestra
    T3  effetti esterni         conferma SEMPRE, timeout = rifiuto

LA REGOLA SUL CONTENUTO WEB SI SCRIVE ORA, NON IN M5
Nessuna azione T2 o T3 puo' originare da un turno che contiene contenuto
appena recuperato dal web. Il modulo web arriva in M5: la regola si scrive
adesso perche' aggiungerla dopo significa dimenticarla, e perche' il campo
`has_untrusted_content` deve esistere nel contesto fin dal primo giorno —
altrimenti in M5 ci si trova a doverlo infilare in una firma gia' usata da
tutti gli strumenti.

Il motivo e' che una pagina web puo' contenere istruzioni rivolte al modello.
Il contenuto recuperato e' DATO, mai comando: un riassunto non e' pericoloso,
una email inviata a seguito di quel riassunto lo e'.

IL TIMEOUT DELLA CONFERMA E' UN RIFIUTO
Vent'anni di finestre di dialogo hanno insegnato a premere Invio. Una
conferma che scade in "sì" e' peggio di nessuna conferma, perche' produce
un audit log che dice che l'utente aveva acconsentito.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metis.security.audit import Tier
from metis.security.killswitch import KILL_SWITCH, KillSwitch

# Deve coincidere con il timeout di ATTESA_CONFERMA nella macchina a stati:
# se divergessero, uno dei due resterebbe appeso ad aspettare l'altro.
CONFERMA_TIMEOUT_S = 20.0

# I livelli che richiedono il consenso esplicito dell'utente. E' un insieme e
# non un `if tier == T3` perche' e' un dato di politica: se un domani anche
# una parte di T2 dovesse chiederlo, si cambia qui e basta.
RICHIEDE_CONFERMA: frozenset[Tier] = frozenset({Tier.T3})

# I livelli vietati quando nel turno e' entrato contenuto web non fidato.
VIETATI_DOPO_WEB: frozenset[Tier] = frozenset({Tier.T2, Tier.T3})


@dataclass
class Context:
    """Cosa il broker sa del turno in cui la chiamata e' nata.

    Non e' un contenitore di comodo: ogni campo qui dentro e' un fatto da cui
    dipende una decisione di sicurezza, e passarlo esplicitamente impedisce
    che qualcuno lo deduca da uno stato globale che nel frattempo e'
    cambiato.
    """

    turn_id: str | None = None

    # True se nel turno e' stato inserito testo recuperato dal web. In M2 e'
    # sempre False perche' il recupero non esiste ancora; in M5 diventa vero
    # e questa riga comincia a rifiutare cose.
    has_untrusted_content: bool = False

    # Come si chiede conferma. In M2 e' la console, in M3 una finestra.
    # Il default e' None e significa "nessuno puo' confermare", quindi ogni
    # T3 viene rifiutato: il default sicuro e' il rifiuto.
    chiedi_conferma: object = None

    # Da dove arriva la chiamata: "llm" o "fast_path". Solo per il log; il
    # fast-path non gode di alcuno sconto.
    origine: str = "llm"

    extra: dict = field(default_factory=dict)


def valuta_tier(tier: Tier, ctx: Context,
                kill: KillSwitch | None = None) -> str | None:
    """Motivo del rifiuto per politica di livello, oppure None.

    Deny-by-default: un tier sconosciuto non passa. Un `KeyError` o un enum
    allargato senza aggiornare qui non devono tradursi in esecuzione.
    """
    if tier not in (Tier.T0, Tier.T1, Tier.T2, Tier.T3):
        return f"livello sconosciuto: {tier!r}"

    ks = KILL_SWITCH if kill is None else kill
    motivo = ks.blocca(tier)
    if motivo is not None:
        return motivo

    if ctx.has_untrusted_content and tier in VIETATI_DOPO_WEB:
        return (f"{tier.value} non ammesso in un turno con contenuto web: "
                "il testo recuperato e' un dato, non un comando")

    return None


def richiede_conferma(tier: Tier) -> bool:
    return tier in RICHIEDE_CONFERMA
