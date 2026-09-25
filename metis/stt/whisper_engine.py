"""Trascrizione finale con faster-whisper su GPU.

Questo e' lo STT su cui si DECIDE: il testo che esce di qui e' quello che
l'orchestratore interpreta. I parziali live di Vosk, che arriveranno in M3
per la GUI, hanno tutt'altro requisito di accuratezza.

Scelte e motivi:

* `faster-whisper` (CTranslate2) e non `openai-whisper`: 4-5x piu' veloce a
  parita' di modello.
* `language="it"` esplicito. L'autodetect costa tempo e sbaglia proprio dove
  fa piu' male, cioe' sulle frasi brevi da due parole.
* `beam_size=1` (greedy). Su frasi corte la differenza di WER col beam search
  e' trascurabile, il costo in latenza no.
* `vad_filter=False`: il VAD l'abbiamo gia' fatto noi, e farlo due volte
  taglierebbe altre sillabe.
* `condition_on_previous_text=False`: evita che un errore si propaghi al turno
  successivo, che e' il modo tipico in cui Whisper entra in loop.
"""

from __future__ import annotations

import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

_CONFIG = Path("config/stt.toml")


def load_domain_prompt() -> str | None:
    """Vocabolario di dominio da config/stt.toml, se presente."""
    if not _CONFIG.exists():
        return None
    return tomllib.loads(_CONFIG.read_text(encoding="utf-8"))["domain_vocabulary"]["prompt"]


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    avg_logprob: float
    no_speech_prob: float
    audio_s: float
    latency_ms: float

    @property
    def rtf(self) -> float:
        """Real-time factor: < 1 significa piu' veloce del tempo reale."""
        return (self.latency_ms / 1000.0) / self.audio_s if self.audio_s else 0.0

    @property
    def suspect(self) -> bool:
        """Trascrizione da trattare con sospetto.

        Whisper allucina testo plausibile sul silenzio o sul rumore: sono le
        famose 'Sottotitoli a cura di...'. Le due sonde sono complementari:
        no_speech_prob alto dice che non c'era voce, avg_logprob basso dice
        che il modello stesso non ci credeva.
        """
        return self.no_speech_prob > 0.6 or self.avg_logprob < -1.0


class WhisperEngine:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cuda",
        compute_type: str = "int8_float16",
        language: str = "it",
        domain_prompt: str | None = ...,
    ):
        self.model_size = model_size
        self.language = language
        # Il vocabolario di dominio e' attivo PER DEFAULT: senza, 'Metis'
        # diventa 'Mattis'. Passare None per disattivarlo esplicitamente.
        self.domain_prompt = load_domain_prompt() if domain_prompt is ... else domain_prompt
        self.device = device
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._lock = threading.Lock()

    def su_cpu(self) -> bool:
        """M7 — sposta il riconoscimento vocale sul processore. Ritorna True
        se l'ha spostato adesso.

        Si usa quando la memoria grafica finisce: Ollama in OOM, oppure un
        altro processo che si prende la VRAM. Whisper `small` occupa ~0,5 GB
        di VRAM; sul processore trascrive piu' lentamente — un secondo circa
        per frase invece di qualche centinaio di millisecondi — ma trascrive,
        e il modello linguistico, che senza GPU non vivrebbe, resta dov'e'.

        Il nuovo modello si carica PRIMA di rilasciare il vecchio e lo scambio
        avviene sotto lock: una trascrizione in corso finisce sul modello che
        stava usando, invece di trovarsi il pavimento sfilato da sotto.
        """
        if self.device == "cpu":
            return False
        nuovo = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        with self._lock:
            vecchio, self.model, self.device = self.model, nuovo, "cpu"
        del vecchio
        return True

    def warmup(self) -> float:
        """Prima trascrizione: carica i pesi in VRAM e compila i kernel.

        Va fatta all'avvio, non al primo turno dell'utente, altrimenti la
        prima interazione paga secondi che non ricompaiono mai piu'.
        """
        t0 = time.perf_counter()
        self.transcribe(np.zeros(16000, dtype=np.float32))
        return (time.perf_counter() - t0) * 1000.0

    def transcribe(self, pcm: np.ndarray, initial_prompt: str | None = ...) -> Transcript:
        """initial_prompt: vocabolario di dominio come contesto.

        Non vincola l'uscita, ma sposta le probabilita' verso parole che il
        modello non puo' indovinare: nomi propri, prodotti, termini rari.
        Serve soprattutto per 'Metis', che small trascrive come 'Mattis'.
        """
        prompt = self.domain_prompt if initial_prompt is ... else initial_prompt
        t0 = time.perf_counter()
        with self._lock:                # vedi `su_cpu`: lo scambio del modello
            segments, info = self.model.transcribe(
                pcm,
                language=self.language,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
                initial_prompt=prompt,
            )
            # transcribe() e' pigro: il lavoro avviene consumando il generatore.
            segs = list(segments)
        latency = (time.perf_counter() - t0) * 1000.0

        text = " ".join(s.text.strip() for s in segs).strip()
        if segs:
            avg_lp = float(np.mean([s.avg_logprob for s in segs]))
            no_speech = float(np.mean([s.no_speech_prob for s in segs]))
        else:
            avg_lp, no_speech = -10.0, 1.0

        return Transcript(
            text=text,
            language=info.language,
            avg_logprob=avg_lp,
            no_speech_prob=no_speech,
            audio_s=pcm.size / 16000,
            latency_ms=latency,
        )
