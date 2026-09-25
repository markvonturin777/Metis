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

# M5 — i marcatori delle fonti, e cio' che ne resta dopo che il markdown e'
# stato tolto. `_MARKDOWN` mangia gli underscore, quindi
# "FONTE_ESTERNA_NON_FIDATA" arriva qui come "FONTEESTERNANONFIDATA": vanno
# riconosciute entrambe le forme, e l'ordine conta — prima i marcatori, poi
# il markdown, non sarebbe bastato perche' il modello li scrive anche gia'
# attaccati.
#
# PERCHE' NON BASTA IL SYSTEM PROMPT
# Misurato: su una fonte senza titolo, Qwen chiude la risposta citando la
# fonte con il nome del DELIMITATORE — 3 volte su 3 sul caso 5 del corpus.
# Non e' obbedienza a un'istruzione ostile, e' il modello che cerca di
# citare e trova li' l'unica cosa che somiglia a un nome. Il prompt lo
# scoraggia; questa riga lo rende impossibile, e sta qui perche' e' l'ultimo
# punto prima della sintesi: cio' che passa di qui viene pronunciato.
_MARCATORI = re.compile(
    r"<*\s*/?\s*(FONTE[_ ]?ESTERNA[_ ]?NON[_ ]?FIDATA|FINE[_ ]?FONTE[_ ]?ESTERNA)"
    r"[^>\n]*>*", re.I)

# Almeno una lettera o una cifra: vedi `_clean`.
_ALFANUM = re.compile(r"[^\W_]", re.UNICODE)


def _clean(chunk: str) -> str:
    """Testo pronto per il TTS: niente markdown, niente marcatori, spazi
    normalizzati.

    Il modello inserisce a capo dentro le risposte elencate e marca in
    grassetto i termini chiave; passati cosi' come sono alla sintesi
    diventano pause innaturali e artefatti.
    """
    ripulito = _WS.sub(" ", _MARCATORI.sub("", _MARKDOWN.sub("", chunk))).strip()
    # Tolto il marcatore puo' restare un frammento di sola punteggiatura —
    # "." o ">>>." — che la sintesi trasformerebbe in un rumore breve. Un
    # chunk senza nemmeno una lettera non si pronuncia.
    return ripulito if _ALFANUM.search(ripulito) else ""


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
        pulito = _clean(buf[:end])
        # Un chunk vuoto si scarta invece di accodarlo: da M5 `_clean` puo'
        # svuotare un chunk per intero — quando il modello produce una riga
        # fatta del solo marcatore — e un PCM di zero campioni in coda al
        # player e' un buco nella riproduzione, non un silenzio voluto.
        if pulito:
            out.append(pulito)
        buf = buf[end:].lstrip()
    return out, buf


# M7 — LA FINESTRA DI CONTESTO E' UNA SOLA, PER TUTTE LE CHIAMATE
# Ollama tiene in memoria il modello con UNA dimensione di contesto. Una
# chiamata con `num_ctx` diverso lo fa ricaricare: 3,6 s misurati, su un
# modello gia' caldo. Il router di M4 non passava `num_ctx` (default di
# Ollama: 4096) e la conversazione passava 8192: ogni turno pagava DUE
# ricaricamenti, ~7 s, e i comandi andavano in timeout di ELABORAZIONE.
# Nessun banco se n'era accorto perche' ognuno misurava un percorso solo —
# il router con il router, la conversazione con la conversazione. L'ha
# trovato il soak, che li alterna come l'uso vero. Da qui la costante unica,
# importata da `toolcall.py`, e un test che le confronta.
NUM_CTX = 8192


class LlmClient:
    def __init__(
        self,
        model: str = MODEL,
        host: str = "http://127.0.0.1:11434",
        num_ctx: int = NUM_CTX,
        temperature: float = 0.7,
    ):
        self.model = model
        self.host = host
        self.client = ollama.Client(host=host)
        self.options = {"num_ctx": num_ctx, "temperature": temperature, "top_p": 0.9}
        # M7 — chi libera memoria grafica quando Ollama la esaurisce. Lo
        # imposta chi costruisce il sistema, che sa che esiste Whisper.
        self.su_oom = None
        self.fallimenti = 0
        self._attendi = time.sleep            # i test lo sostituiscono

    def disponibile(self, timeout: float = 2.0) -> bool:
        """Ollama risponde? Per l'avvio robusto: non carica niente."""
        try:
            ollama.Client(host=self.host, timeout=timeout).list()
            return True
        except Exception:                          # noqa: BLE001
            return False

    def warmup(self) -> float:
        """Carica il modello in VRAM. Misurato in M0: 58 s a freddo.

        Va fatto all'avvio, mai al primo turno dell'utente.

        M7: apre lo stream direttamente, senza `_raw_stream`. Il riscaldamento
        si usa anche quando Ollama TORNA dopo essere stato giu' — la sonda di
        `errors.SALUTE` lo chiama proprio in quel momento — e passare da
        `_raw_stream` vorrebbe dire trovarsi rifiutati perche' il servizio
        risulta ancora giu'. Solleva se Ollama non risponde.
        """
        t0 = time.perf_counter()
        for _ in self._apri_stream([{"role": "user", "content": "Ciao."}]):
            pass
        return (time.perf_counter() - t0) * 1000.0

    def riassumi(self, prompt: str, max_token: int = 300,
                 temperatura: float = 0.1) -> str:
        """Una generazione non in streaming, fredda e corta. Per la memoria.

        Non passa da `stream_sentences` per tre motivi, tutti e tre il
        contrario di quello che serve sul percorso vocale: non c'e' nessuno
        che ascolta, quindi lo streaming non guadagna niente; la segmentazione
        in frasi rovinerebbe un testo che va conservato intero; e la
        temperatura dev'essere 0,1, non 0,7 — un riassunto diverso a ogni
        esecuzione renderebbe la memoria una cosa che non si puo' verificare.

        `num_predict` e' un tetto duro. Il prompt chiede 120 parole, ma un
        modello da 8B davanti a una conversazione lunga tende a riassumere
        tutto con cura, e il riassunto diventerebbe il problema che doveva
        risolvere.
        """
        try:
            r = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False, think=False,
                options={**self.options, "temperature": temperatura,
                         "top_p": 0.9, "num_predict": max_token},
            )
            return (r.get("message", {}).get("content", "") or "").strip()
        except Exception:                          # noqa: BLE001
            # La memoria resta grande. E' un problema minore di un thread che
            # muore: vedi `Memoria.compatta`.
            return ""

    def _apri_stream(self, messages: list[dict]):
        try:
            return self.client.chat(
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
            return self.client.chat(
                model=self.model, messages=msgs, stream=True, options=self.options
            )

    def _raw_stream(self, messages: list[dict]) -> Iterator[str]:
        """I pezzi del testo generato. Riprova PRIMA del primo token.

        M7 — LA CONNESSIONE AVVIENE AL PRIMO `next()`
        In streaming `chat()` ritorna subito un generatore, e l'errore di
        connessione arriva solo quando lo si legge. Per questo si riprova
        l'apertura PIU' la lettura del primo pezzo, insieme: riprovare solo
        `chat()` non riproverebbe niente.

        Dopo il primo token non si riprova: il TTS ha gia' cominciato a
        parlare, e ripartire da capo ripeterebbe la meta' gia' detta.

        Memoria grafica esaurita: si chiama `su_oom` — che sposta il
        riconoscimento vocale sul processore — e si riprova una volta.
        """
        from metis.core.errors import SALUTE, Categoria, Esaurito, classifica, riprova

        # Noto come giu': non si prova nemmeno. Vedi `errors.Salute`.
        SALUTE.richiedi(Categoria.INFERENZA)
        oom_gestito = False

        def apri():
            nonlocal oom_gestito
            try:
                it = iter(self._apri_stream(messages))
                return it, next(it, None)
            except Exception as exc:              # noqa: BLE001
                if (classifica(exc) is Categoria.INFERENZA_OOM
                        and self.su_oom is not None and not oom_gestito):
                    oom_gestito = True
                    self.su_oom()
                    it = iter(self._apri_stream(messages))
                    return it, next(it, None)
                raise

        try:
            it, primo = riprova(apri, Categoria.INFERENZA, attendi=self._attendi)
        except Esaurito:
            self.fallimenti += 1
            SALUTE.giu(Categoria.INFERENZA)
            raise
        SALUTE.su(Categoria.INFERENZA)
        for chunk in ([primo] if primo is not None else []):
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                yield piece
        for chunk in it:
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
