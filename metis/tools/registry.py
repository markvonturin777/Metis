"""Registro degli strumenti: una lista sola, usata per due cose.

Da qui esce sia lo schema JSON che si passa a Ollama, sia la tabella che il
broker consulta per decidere. Gli strumenti che il modello puo' nominare e
quelli che il broker accetta sono quindi la stessa lista **per costruzione**,
non per disciplina: non esiste il caso in cui qualcuno aggiunge uno strumento
al prompt e si dimentica della policy, perche' sono la stessa riga.

GLI HANDLER SONO PRIVATI
Ogni handler si chiama con l'underscore davanti e viene registrato dal
decoratore. Non e' una convenzione estetica: durante lo sviluppo la tentazione
di chiamare `apri_vscode()` direttamente per provare e' fortissima, e ogni
chiamata diretta e' un percorso che salta la validazione, le guardie, la
conferma e il log. `test_nessun_handler_chiamato_fuori_dal_broker` scandaglia
il sorgente con l'AST e fallisce se succede.

PERCHE' UNA CLASSE E NON UN DIZIONARIO GLOBALE
Perche' i test devono poter costruire un registro proprio con strumenti finti.
Con un solo globale, o si sporcano i test con gli strumenti veri, o si sporca
il registro vero con quelli finti. Entrambe finiscono male.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Union

from pydantic import BaseModel, Field, TypeAdapter

from metis.llm.schemas import nome_strumento
from metis.security.audit import Tier
from metis.security.guards import Guard


class Rifiuto(Exception):
    """Lo strumento poteva agire e ha scelto di non farlo.

    Serve una via separata dall'eccezione normale perche' i due casi vanno
    letti in modo diverso nell'audit log. "Playwright e' esploso" e' un
    guasto: qualcosa nel codice o nell'ambiente non va, e va sistemato.
    "Non ho trovato nessun link che si chiami Contatti" non e' un guasto: e'
    il comportamento corretto, ed e' *preferibile* a un clic a caso in mezzo
    allo schermo.

    Il broker traduce questa eccezione in `DENIED` invece che in `ERROR`,
    cosi' la distinzione resta anche nel log e nella frase pronunciata. Non
    e' una scorciatoia per saltare controlli: si arriva qui solo dopo che
    tutti gli stadi hanno detto sì, e l'unico effetto e' non fare niente.
    """


@dataclass(frozen=True)
class ToolSpec:
    name: str
    tier: Tier
    schema: type[BaseModel]
    handler: Callable[[BaseModel], Any]
    guards: tuple[Guard, ...] = ()
    # Il perimetro di uno strumento si definisce quando si costruisce il
    # broker; la capacita' puo' arrivare dopo. Gli strumenti T2 sono
    # registrati in M2 con le loro guardie ma senza corpo: cosi' le guardie
    # sono verificate ora, e in M4 si aggiunge solo l'handler.
    implemented: bool = True
    descrizione: str = ""
    # M6 — la conferma puo' essere richiesta anche sotto T3. Serve a
    # `schedule_reminder`: e' T1, reversibile, ma il piano vuole che
    # l'interpretazione della data sia confermata SEMPRE, perche' un
    # promemoria alla settimana sbagliata e' il modo piu' semplice di rendere
    # la funzione inaffidabile. Il campo puo' solo AGGIUNGERE una conferma:
    # non esiste un modo di toglierla a un T3.
    conferma: bool = False
    # M6 — cosa mostrare a chi conferma, al posto degli argomenti grezzi.
    # "quando: 2026-09-24T17:00" e' un dato; "domani, giovedi' 24 settembre,
    # alle 17:00" e' qualcosa a cui si puo' dire di no sapendo perche'.
    # Ritorna {etichetta: testo}. I testi NON si troncano: vedi `presentazione`.
    presenta: Callable[[BaseModel], dict[str, str]] | None = None


class Registry:
    def __init__(self, nome: str = "principale"):
        self.nome = nome
        self._tools: dict[str, ToolSpec] = {}

    # -- registrazione -----------------------------------------------------

    def strumento(self, tier: Tier, schema: type[BaseModel],
                  guards: tuple[Guard, ...] = (), implemented: bool = True,
                  conferma: bool = False,
                  presenta: Callable[[BaseModel], dict[str, str]] | None = None):
        """Decoratore. Il nome viene dal Literal dello schema, non a mano."""

        def deco(fn: Callable[[BaseModel], Any]) -> Callable[[BaseModel], Any]:
            nome = nome_strumento(schema)
            if nome in self._tools:
                raise ValueError(f"strumento gia' registrato: {nome}")
            self._tools[nome] = ToolSpec(
                name=nome, tier=tier, schema=schema, handler=fn,
                guards=tuple(guards), implemented=implemented,
                descrizione=(fn.__doc__ or schema.__doc__ or "").strip().split("\n")[0],
                conferma=conferma, presenta=presenta,
            )
            return fn

        return deco

    # -- consultazione -----------------------------------------------------

    def get(self, nome: str) -> ToolSpec | None:
        return self._tools.get(nome)

    def nomi(self) -> list[str]:
        return sorted(self._tools)

    def disponibili(self) -> list[ToolSpec]:
        """Solo quelli eseguibili davvero: e' cio' che si offre al modello."""
        return [s for s in self._tools.values() if s.implemented]

    def __contains__(self, nome: object) -> bool:
        return nome in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.values())

    # -- validazione e schema per il modello -------------------------------

    def adapter(self) -> TypeAdapter | None:
        """Union discriminata su TUTTI gli strumenti registrati.

        Include anche i non implementati di proposito: cosi' una chiamata a
        `type_text` in M2 viene riconosciuta e rifiutata con "capacita' non
        ancora disponibile", che e' un'informazione, invece che con
        "strumento sconosciuto", che sarebbe una bugia.
        """
        schemi = [s.schema for s in self._tools.values()]
        if not schemi:
            return None
        if len(schemi) == 1:
            return TypeAdapter(schemi[0])
        return TypeAdapter(
            Annotated[Union[tuple(schemi)], Field(discriminator="tool")]
        )

    def json_schema(self) -> dict:
        """Schema da passare a Ollama come `format`. Solo gli implementati:
        offrire al modello uno strumento che non puo' funzionare significa
        provocare fallimenti e insegnargli a ripetere la richiesta."""
        schemi = [s.schema for s in self.disponibili()]
        if not schemi:
            return {}
        if len(schemi) == 1:
            return TypeAdapter(schemi[0]).json_schema()
        return TypeAdapter(
            Annotated[Union[tuple(schemi)], Field(discriminator="tool")]
        ).json_schema()

    def descrizione_per_prompt(self) -> str:
        """Elenco leggibile per il system prompt del tool calling."""
        righe = []
        for s in sorted(self.disponibili(), key=lambda x: (x.tier.value, x.name)):
            righe.append(f"- {s.name} ({s.tier.value}): {s.descrizione}")
        return "\n".join(righe)


def presentazione(spec: ToolSpec, call: BaseModel) -> dict[str, str]:
    """Cosa vede chi conferma: {etichetta: testo}, completo.

    NIENTE TRONCAMENTI (M6)
    Fino a M5 la finestra di conferma tagliava ogni valore a 400 caratteri e
    la console a 200. Con `send_email` vuol dire approvare un'email di cui si
    e' letto l'inizio: il piano chiede il corpo **completo**, perche' la
    conferma di un'azione che non si annulla vale quanto cio' che si e' visto
    prima di darla. La finestra lo mostra in un riquadro che scorre; qui non
    si taglia niente.

    Se lo strumento dichiara `presenta`, si usa quella — e se esplode, si
    ripiega sugli argomenti grezzi invece di mostrare una finestra vuota: una
    conferma senza contenuto non e' un consenso.
    """
    # `getattr` e non l'attributo: chi chiede conferma riceve uno spec che
    # somiglia a un ToolSpec, e una conferma che esplode per un campo
    # mancante si chiude in un rifiuto silenzioso — cioe' in un'azione che
    # l'utente voleva e non vede nemmeno proporre.
    presenta = getattr(spec, "presenta", None)
    if presenta is not None:
        try:
            voci = presenta(call)
            if voci:
                return {str(k): str(v) for k, v in voci.items()}
        except Exception:                          # noqa: BLE001
            pass
    return {k: str(v) for k, v in call.model_dump().items() if k != "tool"}


def serve_conferma(spec: ToolSpec) -> bool:
    """Il tier la impone (T3), oppure lo strumento la chiede comunque."""
    from metis.security.policies import richiede_conferma

    return richiede_conferma(spec.tier) or spec.conferma


# Registro dell'applicazione. Si popola importando i moduli degli strumenti:
# vedi `metis.tools.carica_tutti`.
REGISTRY = Registry()


def carica_tutti() -> Registry:
    """Importa i moduli degli strumenti, che si registrano da soli.

    L'import ha l'effetto collaterale della registrazione, ed e' voluto: e'
    l'unico modo perche' aggiungere un file in `metis/tools/` basti a
    rendere lo strumento noto sia al modello sia al broker.
    """
    from metis.tools import apps, telemetry, windows  # noqa: F401
    from metis.tools import input_sintetico  # noqa: F401
    from metis.tools import esterni  # noqa: F401
    from metis.tools import web  # noqa: F401
    from metis.tools import home_assistant, scheduler  # noqa: F401

    return REGISTRY
