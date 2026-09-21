"""Decidere se una frase e' una richiesta di azione, e quale.

UNA SOLA CHIAMATA, NON DUE
La tentazione e' chiedere prima "e' un comando?" e poi "quale comando?".
Sono due round trip, due occasioni di sbagliare e il doppio della latenza.
Qui l'alternativa "nessuno strumento" e' **un membro della union**: il
modello sceglie fra gli strumenti disponibili e quella, con output
strutturato, in una chiamata sola. Rispondere a parole e' una scelta
esplicita come le altre, non l'assenza di scelta.

L'OUTPUT STRUTTURATO NON BASTA
`format=schema` vincola la GRAMMATICA, non il senso: il modello produrra'
sempre un JSON valido per lo schema, e potra' comunque scegliere lo
strumento sbagliato o un'applicazione che non c'entra. Per questo il broker
rivalida tutto: qui si guadagna che il JSON arriva sempre ben formato, non
che sia giusto.

UN SOLO TENTATIVO DI RIPARAZIONE
Se la validazione fallisce si reinietta l'errore Pydantic e si riprova una
volta. Poi si rinuncia. Un secondo tentativo alla cieca non serve: se il
modello sbaglia due volte non sta sbagliando la sintassi, sta sbagliando
l'intento, e insistere produce solo latenza.

TEMPERATURA BASSA
0,15 contro lo 0,7 della conversazione. Qui non serve varieta': serve che la
stessa frase produca sempre la stessa azione, perche' un assistente che a
volte apre VS Code e a volte no e' peggio di uno che non lo apre mai.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Annotated, Literal, Union

import ollama
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from metis.tools.registry import Registry

MODEL = "qwen3:8b"
TEMPERATURA = 0.15

PROMPT = """Sei il router di Metis, un assistente vocale su questo PC.
Ricevi cio' che l'utente ha detto e scegli UNA cosa da fare.

Strumenti disponibili:
{strumenti}

Regole:
- Se la richiesta corrisponde chiaramente a uno strumento, usalo.
- Altrimenti usa "nessuno_strumento": conversazione, domande, saluti,
  richieste che nessuno strumento sopra puo' soddisfare.
- Nel dubbio scegli "nessuno_strumento". Rispondere a parole non fa danni,
  agire quando non era richiesto sì.
- Non inventare strumenti e non inventare argomenti."""


class NessunoStrumento(BaseModel):
    """Nessuna azione: si risponde a parole."""

    model_config = ConfigDict(extra="forbid")
    tool: Literal["nessuno_strumento"]


@dataclass
class Decisione:
    """Cosa fare, e quanto e' costato deciderlo."""

    call: dict | None                 # None = conversazione
    origine: str                      # "llm" | "fast_path"
    latenza_ms: float = 0.0
    riparazioni: int = 0
    errore: str | None = None

    @property
    def e_strumento(self) -> bool:
        return self.call is not None


class ToolRouter:
    def __init__(self, registry: Registry, model: str = MODEL,
                 host: str = "http://127.0.0.1:11434"):
        self.registry = registry
        self.model = model
        self.client = ollama.Client(host=host)

    def _union(self):
        schemi = [s.schema for s in self.registry.disponibili()]
        schemi.append(NessunoStrumento)
        return TypeAdapter(
            Annotated[Union[tuple(schemi)], Field(discriminator="tool")]
        )

    def _prompt(self) -> str:
        return PROMPT.format(strumenti=self.registry.descrizione_per_prompt())

    def warmup(self) -> float:
        """Prima decisione a vuoto. Misurata: 3823 ms a freddo, ~250 a caldo.

        Ollama compila la grammatica dell'output strutturato alla prima
        richiesta con quello schema. E' la stessa lezione di M0 sul
        caricamento dei modelli: il costo esiste, si paga una volta, e non
        deve pagarlo il primo turno dell'utente.
        """
        t0 = time.perf_counter()
        self.decidi("ciao")
        return _ms(t0)

    def decidi(self, testo: str, storia: list[dict] | None = None) -> Decisione:
        """Ritorna la tool call da dare al broker, oppure None per la chat."""
        t0 = time.perf_counter()
        adapter = self._union()
        schema = adapter.json_schema()

        messaggi = [{"role": "system", "content": self._prompt()}]
        # Solo gli ultimi scambi: il router decide su cio' che e' stato detto
        # adesso, e un contesto lungo aumenta la latenza senza aiutare.
        if storia:
            messaggi += storia[-4:]
        messaggi.append({"role": "user", "content": testo})

        riparazioni = 0
        ultimo_errore: str | None = None

        for tentativo in (1, 2):
            try:
                risposta = self.client.chat(
                    model=self.model, messages=messaggi, format=schema,
                    think=False, options={"temperature": TEMPERATURA},
                )
                grezzo = risposta["message"]["content"]
            except Exception as exc:              # noqa: BLE001
                # Ollama giu' o modello assente: si degrada in conversazione,
                # che e' il comportamento innocuo.
                return Decisione(None, "llm", _ms(t0), riparazioni,
                                 f"{type(exc).__name__}: {exc}")

            try:
                scelta = adapter.validate_python(json.loads(grezzo))
            except (ValidationError, ValueError) as exc:
                ultimo_errore = str(exc)[:300]
                if tentativo == 2:
                    break
                riparazioni += 1
                messaggi.append({"role": "assistant", "content": grezzo})
                messaggi.append({"role": "user", "content":
                                 "Quel JSON non e' valido: " + ultimo_errore +
                                 " Riprova rispettando lo schema."})
                continue

            if isinstance(scelta, NessunoStrumento):
                return Decisione(None, "llm", _ms(t0), riparazioni)
            return Decisione(scelta.model_dump(), "llm", _ms(t0), riparazioni)

        # Due tentativi falliti: si risponde a parole. Deny-by-default anche
        # qui — nel dubbio non si agisce.
        return Decisione(None, "llm", _ms(t0), riparazioni, ultimo_errore)


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0
