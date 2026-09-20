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

# Confini secondari, per spezzare una frase troppo lunga senza aspettarne la fine.
_SOFT_BREAK = re.compile(r"[,;:—–](?=\s)")

# Il modello produce markdown anche sul canale vocale: "**astrattismo**".
# Osservato in 4 turni su 30 durante M0: gli asterischi finiscono dritti nel
# TTS. Vanno rimossi qui, perche' e' l'ultimo punto prima della sintesi.
_MARKDOWN = re.compile(r"(\*{1,3}|_{1,3}|`{1,3}|~~)")


def _clean(chunk: str) -> str:
    """Testo pronto per il TTS: niente markdown, spazi normalizzati.

    Il modello inserisce a capo dentro le risposte elencate e marca in
    grassetto i termini chiave; passati cosi' come sono alla sintesi
    diventano pause innaturali e artefatti.
    """
    return _WS.sub(" ", _MARKDOWN.sub("", chunk)).strip()


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


def split_sentences(
    buf: str, min_chars: int = 25, max_chars: int | None = None
) -> tuple[list[str], str]:
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

    `max_chars` LIMITA IL CASO OPPOSTO (aggiunto il 2026-09-20)
    Se il modello scrive una frase di 190 caratteri, aspettarne la fine costa
    700 ms: misurato, e' quanto ha sforato lo stadio 'prima frase' rispetto al
    budget di 330. Oltre max_chars si spezza a un confine secondario — virgola,
    punto e virgola, trattino. Il valore giusto si ricava dalla velocita'
    misurata: a 67 tok/s sono circa 270 caratteri al secondo, quindi 330 ms di
    budget valgono ~90 caratteri.
    """
    out: list[str] = []
    while True:
        end = next(
            (m.end() for m in _SENTENCE_END.finditer(buf) if m.end() >= min_chars),
            None,
        )
        # La fine frase non basta: puo' esistere ma essere troppo lontana.
        # Il caso che costa latenza e' proprio quello — una frase di 190
        # caratteri ha il suo punto, ma aspettarlo vale 700 ms.
        too_far = end is None or end > max_chars if max_chars is not None else False
        if too_far and len(buf) >= max_chars:
            soft = next(
                (
                    m.end()
                    for m in reversed(list(_SOFT_BREAK.finditer(buf[:max_chars])))
                    if m.end() >= min_chars
                ),
                None,
            )
            if soft is None:
                cut = buf.rfind(" ", min_chars, max_chars)
                soft = cut if cut > 0 else None
            if soft is not None:
                end = soft
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
        max_chars: int | None = 120,
        first_min_chars: int = 12,
        first_max_chars: int | None = 45,
    ) -> Iterator[tuple[str, GenMetrics]]:
        """Emette un chunk alla volta, appena e' pronto.

        IL PRIMO CHUNK HA SOGLIE PIU' STRETTE (2026-09-20)
        Il primo chunk determina da solo quando Metis comincia a parlare; i
        successivi sono coperti dalla riproduzione di quello precedente. Con
        soglie uniche a 90 caratteri lo stadio 'prima frase' restava a 391 ms
        contro un budget di 330 — inevitabile, perche' generare 90 caratteri a
        270 car/s costa gia' 333 ms. Il cap va messo SOTTO il budget, non sopra.

        Con 45 caratteri il primo chunk esce in ~167 ms. La prosodia di quel
        primo frammento e' un po' piu' secca: e' un prezzo che vale la pena.

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

            is_first = not m.sentences
            done, buf = split_sentences(
                buf,
                first_min_chars if is_first else min_chars,
                first_max_chars if is_first else max_chars,
            )
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
