"""Capability Broker — l'unico modo in cui Metis agisce sul mondo.

Un solo punto di ingresso: `Broker.execute`. Se ce ne fossero due, uno dei
due non sarebbe controllato, e sarebbe quello usato di fretta un martedi'
sera per provare una cosa.

GLI STADI

    1 json        il testo si decodifica?
    2 registro    lo strumento esiste?
    3 schema      gli argomenti sono validi per QUELLO strumento?
    4 policy      il livello e' ammesso adesso? (kill switch, contenuto web)
    5 guardie     i controlli specifici di questo strumento passano?
    6 conferma    se T3: l'utente ha detto sì, esplicitamente?
    7 esecuzione  guardie immediate rivalutate, poi l'handler
    8 audit       sempre, in ogni esito

Uno stadio in piu' compare solo nei rifiuti: `strumento`. E' l'handler che,
pur autorizzato, non ha trovato cosa fare — il link che non esiste, la
finestra che non c'e'. Vedi `Rifiuto` nel registro.

SCOSTAMENTO DAL PIANO, VOLUTO
Il piano metteva la validazione Pydantic prima del lookup nel registro. Con
una union discriminata, pero', una chiamata a `delete_file` fallirebbe come
errore di discriminatore: un blocco di testo illeggibile che dice "nessun
membro corrisponde". Cercando prima nel registro il rifiuto diventa
"strumento sconosciuto: delete_file", e la validazione successiva usa lo
schema di QUEL solo strumento, quindi anche i suoi errori parlano di campi
veri. Stessa sicurezza, diagnostica utilizzabile. Gli stadi hanno un nome e
non un numero proprio perche' il loro ordine e' una scelta rivedibile.

DENY-BY-DEFAULT
Ogni stadio deve dire sì esplicitamente. Un `KeyError`, un enum allargato
senza aggiornare le policy, un'eccezione dentro una guardia: nessuno di
questi si traduce in esecuzione. Il ramo `except` finale rifiuta.

IL BROKER NON SOLLEVA MAI
Ritorna un `Result`. Una tool call malformata non deve fermare Metis: il
modello ne produrra' un'altra, e nel frattempo l'assistente continua a
parlare. Un broker che solleva diventa un broker che qualcuno avvolge in un
try/except generico, ed e' li' che la sicurezza si perde.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from metis.security.audit import AuditLog, Entry, Outcome, Tier
from metis.security.killswitch import KILL_SWITCH, KillSwitch
from metis.security.policies import (
    CONFERMA_TIMEOUT_S,
    Context,
    richiede_conferma,
    valuta_tier,
)
from metis.tools.registry import Registry, Rifiuto, ToolSpec


@dataclass(frozen=True)
class Result:
    ok: bool
    outcome: Outcome
    stage: str
    detail: str
    value: Any = None
    tool: str | None = None
    tier: Tier | None = None
    confirmed: bool | None = None
    duration_ms: float = 0.0
    audit_id: int | None = None

    @property
    def denied(self) -> bool:
        return self.outcome is Outcome.DENIED

    def __str__(self) -> str:
        segno = "ok" if self.ok else self.outcome.value.upper()
        return f"[{segno}] {self.tool or '?'} @{self.stage}: {self.detail}"


@dataclass
class Broker:
    registry: Registry
    audit: AuditLog
    kill: KillSwitch = field(default_factory=lambda: KILL_SWITCH)
    timeout_conferma_s: float = CONFERMA_TIMEOUT_S

    # -- ingresso unico ----------------------------------------------------

    def execute(self, raw: str | dict | BaseModel, ctx: Context | None = None) -> Result:
        """Valida, autorizza, esegue e registra. Non solleva mai.

        `raw` puo' essere testo JSON del modello, un dizionario, o un modello
        gia' costruito dal fast-path. In tutti e tre i casi viene **ridotto a
        dizionario e rivalidato**: non esiste un ingresso che salti uno
        stadio, nemmeno per chi arriva con un oggetto gia' tipizzato.
        """
        ctx = ctx or Context()
        t0 = time.perf_counter()
        try:
            return self._esegui(raw, ctx, t0)
        except Exception as exc:                  # noqa: BLE001 - ultima rete
            # Se si arriva qui c'e' un difetto nel broker stesso. Si rifiuta,
            # si registra, e Metis continua a funzionare.
            return self._chiudi(None, None, {}, ctx, Outcome.ERROR, "broker",
                                f"eccezione non prevista: {type(exc).__name__}: {exc}",
                                t0, None, None)

    # -- la sequenza -------------------------------------------------------

    def _esegui(self, raw, ctx: Context, t0: float) -> Result:
        # --- 1. json ------------------------------------------------------
        if isinstance(raw, BaseModel):
            dati = raw.model_dump()
        elif isinstance(raw, dict):
            dati = dict(raw)
        else:
            try:
                dati = json.loads(raw)
            except (TypeError, ValueError) as e:
                return self._chiudi(None, None, {}, ctx, Outcome.DENIED, "json",
                                    f"JSON non decodificabile: {e}", t0, None, None)
            if not isinstance(dati, dict):
                return self._chiudi(None, None, {}, ctx, Outcome.DENIED, "json",
                                    f"atteso un oggetto, ricevuto {type(dati).__name__}",
                                    t0, None, None)

        # --- 2. registro --------------------------------------------------
        nome = dati.get("tool")
        if not isinstance(nome, str) or not nome:
            return self._chiudi(None, None, dati, ctx, Outcome.DENIED, "registro",
                                "manca il campo 'tool'", t0, None, None)
        spec = self.registry.get(nome)
        if spec is None:
            return self._chiudi(nome, None, dati, ctx, Outcome.DENIED, "registro",
                                f"strumento sconosciuto: {nome}", t0, None, None)

        # --- 3. schema ----------------------------------------------------
        try:
            call = spec.schema.model_validate(dati)
        except ValidationError as e:
            return self._chiudi(nome, spec.tier, dati, ctx, Outcome.DENIED, "schema",
                                _riassumi(e), t0, None, None)

        args = call.model_dump()

        # --- 4. policy di livello -----------------------------------------
        motivo = valuta_tier(spec.tier, ctx, self.kill)
        if motivo is not None:
            return self._chiudi(nome, spec.tier, args, ctx, Outcome.DENIED,
                                "policy", motivo, t0, None, None)

        # --- 5. guardie ----------------------------------------------------
        motivo = self._guardie(spec, call)
        if motivo is not None:
            return self._chiudi(nome, spec.tier, args, ctx, Outcome.DENIED,
                                "guardie", motivo, t0, None, None)

        # --- 6. conferma ----------------------------------------------------
        # Il tier la impone; `spec.conferma` puo' aggiungerla sotto T3 (M6,
        # la data di un promemoria) ma mai toglierla: e' un `or`.
        confirmed: bool | None = None
        if richiede_conferma(spec.tier) or spec.conferma:
            confirmed = self._conferma(spec, call, ctx)
            if not confirmed:
                return self._chiudi(nome, spec.tier, args, ctx, Outcome.DENIED,
                                    "conferma",
                                    "conferma negata o scaduta", t0, confirmed, None)

        # --- 7. esecuzione --------------------------------------------------
        if not spec.implemented:
            return self._chiudi(nome, spec.tier, args, ctx, Outcome.ERROR,
                                "esecuzione",
                                f"capacita' non ancora disponibile: {nome}",
                                t0, confirmed, None)

        # Le guardie marcate `immediato` si rivalutano ADESSO. Fra lo stadio 5
        # e questa riga sono passati i millisecondi della conferma e del log,
        # e la finestra in primo piano puo' essere cambiata. Rifarlo qui, in
        # un punto solo, protegge anche gli strumenti che verranno scritti in
        # M4 da chi non conosce questa nota.
        motivo = self._guardie(spec, call, solo_immediate=True)
        if motivo is not None:
            return self._chiudi(nome, spec.tier, args, ctx, Outcome.DENIED,
                                "guardie_immediate",
                                f"{motivo} (cambiata dopo l'autorizzazione)",
                                t0, confirmed, None)

        try:
            valore = spec.handler(call)
        except Rifiuto as r:
            # Lo strumento ha scelto di non agire: non e' un guasto. Vedi la
            # nota su `Rifiuto` nel registro — la distinzione fra "rotto" e
            # "non l'ho fatto apposta" deve sopravvivere fino all'audit log.
            return self._chiudi(nome, spec.tier, args, ctx, Outcome.DENIED,
                                "strumento", str(r), t0, confirmed, None)
        except Exception as exc:                  # noqa: BLE001
            return self._chiudi(nome, spec.tier, args, ctx, Outcome.ERROR,
                                "esecuzione",
                                f"{type(exc).__name__}: {exc}", t0, confirmed, None)

        return self._chiudi(nome, spec.tier, args, ctx, Outcome.OK, "esecuzione",
                            "eseguito", t0, confirmed, valore)

    # -- pezzi -------------------------------------------------------------

    def _guardie(self, spec: ToolSpec, call: BaseModel,
                 solo_immediate: bool = False) -> str | None:
        for g in spec.guards:
            if solo_immediate and not g.immediato:
                continue
            try:
                motivo = g.controlla(call)
            except Exception as exc:              # noqa: BLE001
                # Una guardia che esplode non sa dire di sì. Deny-by-default
                # significa anche questo.
                return f"guardia {g.nome} fallita: {type(exc).__name__}: {exc}"
            if motivo is not None:
                return motivo
        return None

    def _conferma(self, spec: ToolSpec, call: BaseModel, ctx: Context) -> bool:
        """True solo se l'utente ha detto sì entro il timeout.

        Il default e' NO in tre casi diversi: nessuno puo' confermare, la
        conferma e' scaduta, la conferma e' esplosa. Tutti e tre devono
        portare allo stesso posto, perche' un'azione irreversibile eseguita
        per un difetto del meccanismo di conferma e' il difetto peggiore che
        questo progetto possa avere.
        """
        chiedi = ctx.chiedi_conferma
        if chiedi is None:
            return False

        esito: list[bool] = []

        def lavora() -> None:
            try:
                esito.append(bool(chiedi(spec, call)))
            except Exception:                     # noqa: BLE001
                esito.append(False)

        t = threading.Thread(target=lavora, daemon=True, name="metis-conferma")
        t.start()
        t.join(timeout=self.timeout_conferma_s)
        # Se il thread e' ancora vivo, l'utente non ha risposto in tempo. La
        # sua eventuale risposta tardiva finisce in `esito` e viene ignorata:
        # abbiamo gia' deciso, e cambiare idea dopo sarebbe una corsa.
        if t.is_alive() or not esito:
            return False
        return esito[0]

    def _chiudi(self, tool, tier, args, ctx, outcome, stage, detail,
                t0, confirmed, valore) -> Result:
        durata = (time.perf_counter() - t0) * 1000.0
        audit_id = None
        try:
            audit_id = self.audit.record(Entry(
                tool=tool or "?", tier=tier or Tier.T0, args=args,
                outcome=outcome, turn_id=ctx.turn_id, confirmed=confirmed,
                stage=stage, detail=detail, duration_ms=durata,
            ))
        except Exception:                         # noqa: BLE001
            # Non poter scrivere il log non deve impedire di rispondere, ma
            # e' un difetto grave: resta nel Result perche' si veda.
            detail = f"{detail} [AUDIT NON SCRITTO]"
        return Result(
            ok=outcome is Outcome.OK, outcome=outcome, stage=stage, detail=detail,
            value=valore, tool=tool, tier=tier, confirmed=confirmed,
            duration_ms=durata, audit_id=audit_id,
        )


def _riassumi(e: ValidationError) -> str:
    """Errori Pydantic in una riga leggibile, e reiniettabile nel prompt."""
    pezzi = []
    for err in e.errors()[:4]:
        campo = ".".join(str(x) for x in err["loc"]) or "(radice)"
        pezzi.append(f"{campo}: {err['msg']}")
    if len(e.errors()) > 4:
        pezzi.append(f"... e altri {len(e.errors()) - 4}")
    return "; ".join(pezzi)
