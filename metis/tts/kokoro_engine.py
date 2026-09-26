"""Sintesi vocale con Kokoro, su CPU.

PERCHE' SU CPU
Decisione di §3.2 della specifica: Kokoro ha 82M parametri e resta ampiamente
in tempo reale su un 5800X. Tenerlo sulla CPU libera ~0,4 GB di VRAM, che sulla
2070 Super valgono piu' della manciata di millisecondi risparmiati.

RIPRODUZIONE INTERROMPIBILE
`stop()` deve fermare l'audio entro poche decine di ms: e' il presupposto del
barge-in di M1. Non basta smettere di accodare, va svuotata anche la coda di
riproduzione, altrimenti Metis tace un istante e poi riparte da solo — che e'
il bug piu' fastidioso di tutta quella fase.

L'INVILUPPO DELLA VOCE (PHASE1)
L'onda del nucleo nell'Hub segue la voce di Metis, e la legge da qui: il
player riproduce l'audio di qualunque motore, Piper o Kokoro. Il calcolo si
fa all'accodamento, su un array gia' in memoria (un RMS ogni 20 ms); durante
la riproduzione `livello_uscita` guarda solo un indice. Nessun callback
audio, nessun thread in piu'.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

KOKORO_SR = 24_000
VOICES_IT = ("if_sara", "im_nicola")

PASSO_INVILUPPO_S = 0.020
SILENZIO_DB = -120.0


def inviluppo(pcm: np.ndarray, sample_rate: int,
              passo_s: float = PASSO_INVILUPPO_S) -> np.ndarray:
    """Il livello della frase in dBFS, un valore ogni `passo_s`.

    L'ultima finestra, se e' corta, si completa con silenzio: abbassa di poco
    l'ultimo valore, che dura meno di 20 ms.
    """
    n = max(1, int(round(sample_rate * passo_s)))
    if pcm.size == 0:
        return np.zeros(0, np.float32)
    x = np.asarray(pcm, dtype=np.float32).reshape(-1)
    resto = (-x.size) % n
    if resto:
        x = np.concatenate([x, np.zeros(resto, np.float32)])
    rms = np.sqrt(np.mean(np.square(x.reshape(-1, n)), axis=1))
    minimo = 10.0 ** (SILENZIO_DB / 20.0)
    return (20.0 * np.log10(np.maximum(rms, minimo))).astype(np.float32)


@dataclass(frozen=True)
class Synthesis:
    pcm: np.ndarray
    sample_rate: int
    text: str
    latency_ms: float

    @property
    def audio_s(self) -> float:
        return self.pcm.size / self.sample_rate

    @property
    def rtf(self) -> float:
        """Real-time factor. Sotto 1 significa piu' veloce del tempo reale."""
        return (self.latency_ms / 1000.0) / self.audio_s if self.audio_s else 0.0


class KokoroEngine:
    def __init__(self, voice: str = "if_sara", lang_code: str = "i", speed: float = 1.0):
        from kokoro import KPipeline

        self.voice = voice
        self.speed = speed
        self.pipeline = KPipeline(lang_code=lang_code)

    def warmup(self) -> float:
        t0 = time.perf_counter()
        self.synth("Sistemi operativi.")
        return (time.perf_counter() - t0) * 1000.0

    def synth(self, text: str) -> Synthesis:
        t0 = time.perf_counter()
        chunks = [
            audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            for _, _, audio in self.pipeline(text, voice=self.voice, speed=self.speed)
        ]
        pcm = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
        return Synthesis(pcm, KOKORO_SR, text, (time.perf_counter() - t0) * 1000.0)


class Player:
    """Riproduzione su thread, con coda e interruzione immediata."""

    def __init__(self, sample_rate: int = KOKORO_SR):
        self.sample_rate = sample_rate
        self._q: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.speaking = threading.Event()
        # PHASE1 — il pulsante "muto" dell'Hub. Le frasi continuano a passare
        # dalla coda, con i tempi di sempre per la macchina a stati; solo, non
        # suonano. Le risposte restano scritte (D-UI 2).
        self.muto = False
        # Che cosa sta suonando ADESSO. Serve a chi deve attribuire un evento
        # acustico alla frase giusta: la coda tiene due frasi di anticipo,
        # quindi "l'ultima sintetizzata" e' un'etichetta sbagliata.
        self.now_playing = None
        # PHASE1 — (inviluppo, istante di partenza) della frase che suona, o
        # None. Un riferimento solo, scritto da un thread e letto da un altro:
        # chi legge vede la coppia vecchia o quella nuova, mai mezza.
        self._suona: tuple[np.ndarray, float] | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                continue
            pcm, etichetta, livelli = item
            if pcm is None:
                continue
            self.speaking.set()
            self.now_playing = etichetta
            try:
                if not self.muto:
                    self._suona = (livelli, time.perf_counter())
                    sd.play(pcm, self.sample_rate)
                    sd.wait()
            finally:
                self._suona = None
                if self._q.empty():
                    self.speaking.clear()
                    self.now_playing = None

    def enqueue(self, pcm: np.ndarray, etichetta=None) -> None:
        """L'etichetta e' facoltativa: chi deve sapere cosa sta suonando la
        passa, gli altri no."""
        livelli = inviluppo(pcm, self.sample_rate) if pcm is not None else None
        self._q.put((pcm, etichetta, livelli))

    def livello_uscita(self) -> float:
        """Il livello in dBFS di quello che sta suonando adesso.

        `SILENZIO_DB` fra una frase e l'altra, in muto, e dopo `stop()`.
        Chiamabile da qualunque thread: legge un riferimento e un orologio.
        """
        suona = self._suona
        if suona is None:
            return SILENZIO_DB
        livelli, t0 = suona
        i = int((time.perf_counter() - t0) / PASSO_INVILUPPO_S)
        if 0 <= i < livelli.size:
            return float(livelli[i])
        return SILENZIO_DB

    def pending(self) -> int:
        """Frasi ancora in coda. Serve a chi deve tenerla piena."""
        return self._q.qsize()

    def wait_drained(self, timeout: float = 120.0) -> bool:
        """Attende che la coda sia vuota e l'ultima frase finita di suonare.

        Serve a sapere QUANDO Metis ha smesso di parlare: e' il momento in cui
        lo stato torna a IN_ASCOLTO e il microfono riprende. Senza, PLAYBACK_DONE
        scatterebbe mentre gli altoparlanti stanno ancora suonando e i frame
        dell'eco rientrerebbero nel VAD — esattamente il loop che M1 esiste per
        rompere.
        """
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if self._q.empty() and not self.speaking.is_set():
                return True
            time.sleep(0.02)
        return False

    def imposta_muto(self, attivo: bool) -> None:
        """Zittito a meta' frase, la frase si ferma subito; le successive non
        suonano. Non svuota la coda: il turno finisce da solo, in silenzio."""
        self.muto = attivo
        if attivo:
            self._suona = None
            sd.stop()

    def stop(self) -> None:
        """Interruzione immediata: audio fermo E coda svuotata.

        Svuotare la coda e' la meta' che si dimentica. Senza, dopo il barge-in
        Metis riprende a parlare con la frase successiva gia' accodata.
        """
        sd.stop()
        self.now_playing = None
        self._suona = None
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self.speaking.clear()

    def close(self) -> None:
        self._stop.set()
        sd.stop()
        if self._thread:
            self._thread.join(timeout=1.0)
