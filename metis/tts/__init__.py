"""Sintesi vocale. Il backend si sceglie da config/tts.toml."""
from __future__ import annotations

import tomllib

import numpy as np
from pathlib import Path

_CONFIG = Path("config/tts.toml")


def load_config() -> dict:
    if not _CONFIG.exists():
        return {"engine": {"backend": "piper"}, "piper": {"voice": "it_IT-paola-medium"}}
    return tomllib.loads(_CONFIG.read_text(encoding="utf-8"))


def create_engine(backend: str | None = None):
    """Motore TTS configurato. Default: Piper, vedi config/tts.toml."""
    cfg = load_config()
    backend = backend or cfg["engine"]["backend"]

    if backend == "piper":
        from metis.tts.piper_engine import PiperEngine

        p = cfg.get("piper", {})
        return PiperEngine(
            voice=p.get("voice", "it_IT-paola-medium"),
            voices_dir=Path(p.get("voices_dir", "data/piper")),
        )
    if backend == "kokoro":
        from metis.tts.kokoro_engine import KokoroEngine

        k = cfg.get("kokoro", {})
        return KokoroEngine(voice=k.get("voice", "if_sara"), lang_code=k.get("lang_code", "i"))
    raise ValueError(f"backend TTS sconosciuto: {backend}")


# --- M7: la voce che si degrada invece di rompersi ---------------------------

class SintesiRobusta:
    """Piper, poi Kokoro, poi solo testo. Non solleva mai.

    E' la riga "TTS fallito" della matrice degli errori, con una particolarita'
    che la distingue da tutte le altre: qui l'errore NON si puo' dire, perche'
    la voce e' proprio la cosa che si e' rotta. La degradazione quindi e'
    silenziosa e finisce nel log; la frase resta visibile in GUI, dove arriva
    comunque prima della sintesi (`on_dice`).

    LA RISERVA SI CARICA SOLO SE SERVE, E IN SOTTOFONDO (misurato in M7)
    Caricare Kokoro all'avvio "per sicurezza" sarebbe pagare sempre per un
    guasto raro. Ma caricarlo quando serve, dentro il turno, costava **34
    secondi** — il modello si carica e interroga Hugging Face in rete — cioe'
    trentaquattro secondi di silenzio a meta' di una risposta.

    Quindi: al primo fallimento di Piper il caricamento parte su un thread, e
    quella frase resta solo testo in GUI. Dalle frasi successive, appena la
    riserva e' pronta, torna la voce. Se non si carica, si resta al testo
    senza riprovarci a ogni frase.

    IL CAMPIONAMENTO DEVE COINCIDERE
    Il player e' aperto alla frequenza di Piper (22.050 Hz); Kokoro produce a
    24.000. Senza ricampionamento la voce di riserva uscirebbe rallentata e
    piu' grave — il tipo di difetto che sembra un guasto dell'altoparlante.
    """

    def __init__(self, primario, crea_riserva=None, log=None):
        self.primario = primario
        self.sample_rate = primario.sample_rate
        self._crea_riserva = crea_riserva
        self._riserva = None
        self._riserva_tentata = False
        self._log = log
        self.fallimenti = 0
        self.su_riserva = 0
        self.muti = 0

    def warmup(self) -> float:
        return self.primario.warmup()

    def synth(self, testo: str):
        try:
            return self.primario.synth(testo)
        except Exception as exc:                  # noqa: BLE001
            self.fallimenti += 1
            self._scrivi("sintesi primaria fallita", exc)
        riserva = self._carica_riserva()
        if riserva is not None:
            try:
                s = riserva.synth(testo)
                self.su_riserva += 1
                return _Sintesi(_ricampiona(s.pcm, s.sample_rate, self.sample_rate),
                                self.sample_rate, testo)
            except Exception as exc:              # noqa: BLE001
                self._scrivi("sintesi di riserva fallita", exc)
        self.muti += 1
        return _Sintesi(np.zeros(int(self.sample_rate * 0.05), dtype=np.float32),
                        self.sample_rate, testo)

    def _carica_riserva(self):
        """La riserva se e' pronta, altrimenti None — e al primo giro fa
        partire il caricamento su un thread. Non aspetta mai."""
        if self._riserva_tentata or self._crea_riserva is None:
            return self._riserva
        self._riserva_tentata = True

        def carica() -> None:
            try:
                self._riserva = self._crea_riserva()
            except Exception as exc:              # noqa: BLE001
                self._scrivi("voce di riserva non disponibile", exc)

        import threading

        self._caricamento = threading.Thread(target=carica, daemon=True,
                                             name="metis-voce-riserva")
        self._caricamento.start()
        return None

    def _scrivi(self, evento: str, exc: BaseException) -> None:
        if self._log is not None:
            try:
                self._log.warning(evento, errore=f"{type(exc).__name__}: {exc}"[:200])
            except Exception:                      # noqa: BLE001
                pass


class _Sintesi:
    def __init__(self, pcm, sample_rate, text):
        self.pcm, self.sample_rate, self.text = pcm, sample_rate, text


def _ricampiona(pcm, da: int, a: int):
    if da == a or pcm.size == 0:
        return pcm.astype(np.float32, copy=False)
    import soxr

    return soxr.resample(pcm.astype(np.float32), da, a).astype(np.float32)


def crea_robusta(log=None) -> SintesiRobusta:
    """Il motore dell'applicazione: il backend configurato, con il ripiego.

    Se il primario non si costruisce nemmeno — la voce di Piper non e' stata
    scaricata — si prova subito la riserva come primario. Se non c'e'
    nessuna delle due, l'errore sale: un Metis che parte muto senza dirlo e'
    peggio di uno che non parte e dice perche'.
    """
    cfg = load_config()
    configurato = cfg["engine"]["backend"]
    riserva = "kokoro" if configurato == "piper" else "piper"
    try:
        primario = create_engine(configurato)
    except Exception as exc:                      # noqa: BLE001
        if log is not None:
            log.warning("voce configurata non disponibile, uso la riserva",
                        errore=f"{type(exc).__name__}: {exc}"[:200])
        return SintesiRobusta(create_engine(riserva), log=log)
    return SintesiRobusta(primario, crea_riserva=lambda: create_engine(riserva), log=log)
