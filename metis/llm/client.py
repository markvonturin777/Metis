"""Client Ollama in streaming, con segmentazione in frasi e annullamento.

TRE SCELTE VINCOLANTI

1. `think=False` sempre sul percorso vocale. Qwen 3 e' un modello ibrido con
   reasoning: in thinking mode produce centinaia di token di ragionamento prima
   della risposta, e il TTFT passa da ~150 ms a 5-20 secondi. Misurato in M0
   giorno 1: e' la differenza fra un assistente e una sala d'attesa.

2. Streaming FRASE PER FRASE, non a risposta completa. E' l'ottimizzazione che
   vale piu' di tutte le altre messe insieme: il TTS comincia a parlare quando
   la prima frase e' pronta, non quando il modello ha finito.

3. Annullamento cooperativo. Serve gia' da ora anche se il barge-in arriva in
   M1: un generatore che non si puo' fermare a meta' e' una riscrittura, non
   un'aggiunta.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import ollama

MODEL = "qwen3:8b"

# Fine frase: punteggiatura forte seguita da spazio o fine stringa.
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
# Il lookahead su \s impedisce di spezzare i decimali: "6.58 GB" resta intero.

_WS = re.compile(r"\s+")


def _clean(chunk: str) -> str:
    """Spazi interni normalizzati.

    Il modello inserisce a capo dentro le risposte elencate; passati cosi'
    come sono al TTS diventano pause innaturali a meta' chunk.
    """
    return _WS.sub(" ", chunk).strip()


@dataclass
class GenMetrics:
    t_start: float = 0.0
    ttft_ms: float | None = None
    t_first_sentence_ms: float | None = None
    tokens: int = 0
    total_ms: float = 0.0
    cancelled: bool = False
    sentences: list[str] = field(default_factory=list)

    @property
    def tok_per_s(self) -> float:
        gen_s = (self.total_ms - (self.ttft_ms or 0)) / 1000.0
        return self.tokens / gen_s if gen_s > 0 else 0.0

    @property
    def text(self) -> str:
        return " ".join(self.sentences)


class CancelToken:
    """Segnale di annullamento condiviso fra thread."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def split_sentences(buf: str, min_chars: int = 25) -> tuple[list[str], str]:
    """Estrae dal buffer i chunk pronti per il TTS, restituisce (chunk, resto).

    `min_chars` evita di sintetizzare frammenti come "Sì." o "Certo.": un
    chunk troppo corto produce una prosodia a scatti, perche' il modello di
    sintesi non ha contesto sufficiente per l'intonazione.

    ATTENZIONE ALLA SEMANTICA (corretta il 2026-09-20)
    La prima versione si FERMAVA quando una frase era piu' corta di min_chars.
    Sbagliato: su "Domanda? Risposta! Terza frase molto lunga." non emetteva
    nulla, perche' la prima frase e' di 8 caratteri, e tutto il testo restava
    in buffer fino a fine generazione — annullando il vantaggio dello
    streaming proprio quando il modello risponde a frasi brevi.

    Ora le frasi corte si ACCUMULANO: si estende il chunk attraverso i confini
    di frase finche' non raggiunge min_chars. Ogni chunk emesso e' quindi
    lungo abbastanza, e nessun testo resta indietro.
    """
    out: list[str] = []
    while True:
        end = next(
            (m.end() for m in _SENTENCE_END.finditer(buf) if m.end() >= min_chars),
            None,
        )
        if end is None:
            break
        out.append(_clean(buf[:end]))
        buf = buf[end:].lstrip()
    return out, buf


class LlmClient:
    def __init__(
        self,
        model: str = MODEL,
        host: str = "http://127.0.0.1:11434",
        num_ctx: int = 8192,
        temperature: float = 0.7,
    ):
        self.model = model
        self.client = ollama.Client(host=host)
        self.options = {"num_ctx": num_ctx, "temperature": temperature, "top_p": 0.9}

    def warmup(self) -> float:
        """Carica il modello in VRAM. Misurato in M0: 58 s a freddo.

        Va fatto all'avvio, mai al primo turno dell'utente.
        """
        t0 = time.perf_counter()
        for _ in self._raw_stream([{"role": "user", "content": "Ciao."}]):
            pass
        return (time.perf_counter() - t0) * 1000.0

    def _raw_stream(self, messages: list[dict]) -> Iterator[str]:
        try:
            stream = self.client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                think=False,
                options=self.options,
            )
        except TypeError:
            # Client piu' vecchio: nessun parametro `think`, si ripiega sulla
            # direttiva testuale che Qwen 3 riconosce.
            msgs = [dict(m) for m in messages]
            msgs[-1]["content"] += " /no_think"
            stream = self.client.chat(
                model=self.model, messages=msgs, stream=True, options=self.options
            )

        for chunk in stream:
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                yield piece

    def stream_sentences(
        self,
        messages: list[dict],
        cancel: CancelToken | None = None,
        min_chars: int = 25,
    ) -> Iterator[tuple[str, GenMetrics]]:
        """Emette una frase alla volta, appena e' completa.

        Il chiamante riceve anche le metriche vive: servono alla GUI di M3 e
        al calcolo della latenza end-to-end.
        """
        m = GenMetrics(t_start=time.perf_counter())
        buf = ""

        for piece in self._raw_stream(messages):
            if cancel is not None and cancel.cancelled:
                m.cancelled = True
                break

            if m.ttft_ms is None:
                m.ttft_ms = (time.perf_counter() - m.t_start) * 1000.0
            m.tokens += 1
            buf += piece

            done, buf = split_sentences(buf, min_chars)
            for s in done:
                if m.t_first_sentence_ms is None:
                    m.t_first_sentence_ms = (time.perf_counter() - m.t_start) * 1000.0
                m.sentences.append(s)
                yield s, m

        # coda: l'ultima frase spesso non ha punteggiatura finale
        rest = _clean(buf)
        if rest and not m.cancelled:
            if m.t_first_sentence_ms is None:
                m.t_first_sentence_ms = (time.perf_counter() - m.t_start) * 1000.0
            m.sentences.append(rest)
            yield rest, m

        m.total_ms = (time.perf_counter() - m.t_start) * 1000.0
