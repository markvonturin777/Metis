"""Rilevatore della wake word "Hey Metis".

Gira su CPU, sempre attivo, anche mentre Metis parla: e' il livello L2 della
strategia anti-eco, cioe' il barge-in. Costa 1,70 ms per blocco contro un
budget di 80: lo si puo' tenere acceso senza pensarci.

IL FPR SINTETICO NON PREDICE I FALSI RISVEGLI (nota importante)
Il modello e' stato validato con un tasso di falsi positivi dello 0% su 40
clip negativi, e sembra un ottimo risultato. Non lo e', perche' la domanda e'
mal posta: in esecuzione il rilevatore valuta un blocco ogni 32 ms, cioe'
**900.000 volte in 8 ore**. Per rispettare NFR-6 — meno di un falso risveglio
ogni 8 ore — servirebbe un FPR inferiore allo 0,00011%, mentre un set di
validazione da 4800 negativi ha una risoluzione minima dello 0,021%: due
ordini di grandezza sopra.

Conseguenze pratiche:
  * la soglia di default e' **alta** (0,95), non quella "ottima" da curva ROC;
  * serve la **conferma su piu' blocchi consecutivi**, che abbatte i falsi
    positivi isolati senza toccare la sensibilita' alle frasi vere;
  * il valore definitivo si tara **dal vivo**, con le 8 ore di NFR-6, non sui
    dati sintetici.

IL PUNTEGGIO DIPENDE DA DOVE CADONO I CONFINI DEI BLOCCHI (2026-09-21)
Misurato: lo stesso audio, spostato di 64 campioni — quattro millisecondi —
cambia punteggio in modo drastico. Il melspettrogramma viene calcolato su una
griglia di frame ancorata all'inizio del flusso; spostare il segnale rispetto
a quella griglia produce feature diverse.

    clip                    escursione su 8 allineamenti
    "Hey Metis", voce vera  0,954 - 0,996      +0,042
    "Ehi mi senti"          0,152 - 0,891      +0,739
    rumore ambientale       0,016 - 0,969      +0,953

Due conseguenze, e la seconda e' un'opportunita':

1. Un punteggio letto una volta sola NON e' riproducibile, e rivalutare una
   registrazione salvata sottostima il rischio. E' la spiegazione dello 0,986
   di ieri che non si riusciva a ottenere di nuovo: era un altro allineamento.
   Chi rivaluta clip offline deve spazzolare gli allineamenti e prendere il
   massimo.

2. La STABILITA' rispetto all'allineamento distingue i veri positivi dai
   quasi-falsi meglio del punteggio stesso: la wake word vera e' un pattern
   robusto, un quasi-falso cavalca il rumore nello spazio delle feature. Da
   qui la regola a DOPPIA FASE: due rilevatori sfasati di 256 campioni,
   scatta solo se sono d'accordo entrambi. Sulle clip registrate finora non
   costa nulla sui positivi (93,3% in entrambi i casi) e azzera i picchi
   ambientali (6,2% -> 0%). Costa 1,7 ms in piu' per blocco su 80 di budget.
   Resta DISATTIVATA di default: due clip ambientali non sono un campione, e
   la decisione si prende con le 8 ore di NFR-6, dove `record_ambient.py`
   misura le due regole in parallelo.
"""

from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_MODEL = Path("data/wakeword/hey_metis.onnx")
_CONFIG = Path("config/wakeword.toml")


@dataclass
class WakeWordConfig:
    model_path: Path = DEFAULT_MODEL
    threshold: float = 0.95
    consecutive: int = 2          # blocchi consecutivi sopra soglia
    refractory_s: float = 2.0     # silenzio imposto dopo un rilevamento
    enabled: bool = True
    dual_phase: bool = False      # richiede l'accordo delle due fasi

    @classmethod
    def load(cls) -> "WakeWordConfig":
        if not _CONFIG.exists():
            return cls()
        c = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))["wakeword"]
        return cls(
            model_path=Path(c.get("model_path", DEFAULT_MODEL)),
            threshold=float(c.get("threshold", 0.95)),
            consecutive=int(c.get("consecutive", 2)),
            refractory_s=float(c.get("refractory_s", 2.0)),
            enabled=bool(c.get("enabled", True)),
            dual_phase=bool(c.get("dual_phase", False)),
        )


class Confirmer:
    """Conferma su blocchi consecutivi, piu' periodo refrattario.

    Vive fuori dal rilevatore perche' i banchi di prova devono poter
    contare cosa avrebbe fatto una REGOLA DIVERSA sulla stessa audio. Con la
    logica scritta dentro `feed`, il banco se ne riscriverebbe una copia, e
    una copia che diverge fa misurare una cosa per un'altra.
    """

    def __init__(self, threshold: float, consecutive: int, refractory_s: float):
        self.threshold = threshold
        self.consecutive = consecutive
        self.refractory_s = refractory_s
        self._above = 0
        # "mai scattato", non "scattato all'istante zero": l'origine di
        # perf_counter e' indefinita per contratto, e con 0.0 il rilevatore
        # nascerebbe dentro il proprio periodo refrattario.
        self._last_fire = float("-inf")

    def reset(self) -> None:
        self._above = 0

    def feed(self, score: float, now: float) -> bool:
        if now - self._last_fire < self.refractory_s:
            self._above = 0
            return False
        if score >= self.threshold:
            self._above += 1
            if self._above >= self.consecutive:
                self._above = 0
                self._last_fire = now
                return True
        else:
            self._above = 0
        return False


class WakeWordDetector:
    """Consuma blocchi da 512 campioni float32 a 16 kHz, come da capture.py.

    openWakeWord bufferizza internamente, quindi la dimensione del blocco non
    deve coincidere con la sua finestra da 1280: verificato.
    """

    def __init__(self, cfg: WakeWordConfig | None = None):
        from openwakeword.model import Model

        self.cfg = cfg or WakeWordConfig.load()
        if not self.cfg.model_path.exists():
            raise FileNotFoundError(
                f"modello wake word assente: {self.cfg.model_path}\n"
                "Addestralo con: python wakeword/train_model.py"
            )
        self.model = Model(
            wakeword_models=[str(self.cfg.model_path)], inference_framework="onnx"
        )
        self.name = next(iter(self.model.models))
        # Seconda fase, sfasata di mezzo blocco. Si calcola SEMPRE, anche con
        # la regola disattivata: serve a misurare le due regole in parallelo
        # durante M1, e costa 1,7 ms. Dopo D1, se la doppia fase non viene
        # adottata, questo ramo si toglie.
        self.model_b = Model(
            wakeword_models=[str(self.cfg.model_path)], inference_framework="onnx"
        )
        self._coda = np.zeros(256, dtype=np.float32)
        self._conf = Confirmer(self.cfg.threshold, self.cfg.consecutive,
                               self.cfg.refractory_s)
        self.last_score = 0.0          # quello che decide, secondo la regola
        self.last_score_a = 0.0        # fase 0
        self.last_score_b = 0.0        # fase 256
        self.scores: list[float] = []      # per la taratura dal vivo
        self.scores_dual: list[float] = []

    # Compatibilita': i banchi di prova azzerano il refrattario fra un
    # tentativo e l'altro.
    @property
    def _last_fire(self) -> float:
        return self._conf._last_fire

    @_last_fire.setter
    def _last_fire(self, v: float) -> None:
        self._conf._last_fire = v

    def reset(self) -> None:
        self.model.reset()
        self.model_b.reset()
        self._coda = np.zeros(256, dtype=np.float32)
        self._conf.reset()

    def feed(self, pcm: np.ndarray) -> bool:
        """True quando la wake word e' confermata.

        La conferma richiede `consecutive` blocchi sopra soglia: un picco
        isolato — un colpo di tastiera, una sillaba fortunata — non basta.
        Dopo un rilevamento c'e' un periodo refrattario, altrimenti la stessa
        pronuncia ne genererebbe diversi di fila.

        Espone `last_score_a` e `last_score_b`, le due fasi: servono ai banchi
        di prova per contare in parallelo cosa avrebbe fatto la regola a
        doppia fase sulla stessa audio.
        """
        if not self.cfg.enabled:
            return False

        # Il modello viene alimentato SEMPRE, anche durante il periodo
        # refrattario. La versione precedente usciva subito e gli lasciava un
        # buco di due secondi nel buffer: alla ripresa le feature scavalcavano
        # una discontinuita', e un secondo "Hey Metis" detto subito dopo il
        # primo non veniva sentito. Il refrattario riguarda la DECISIONE, non
        # l'ascolto; costa 1,9 ms su 80 di budget.
        now = time.perf_counter()
        i16 = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16)
        self.last_score_a = max(self.model.predict(i16).values())

        # Fase sfasata: mezzo blocco indietro rispetto alla prima.
        sfasato = np.concatenate((self._coda, pcm[:256]))
        self._coda = pcm[256:].copy()
        i16b = (np.clip(sfasato, -1.0, 1.0) * 32767).astype(np.int16)
        self.last_score_b = max(self.model_b.predict(i16b).values())

        # Con la doppia fase decide la piu' bassa: un pattern vero e' robusto
        # allo spostamento, un quasi-falso no.
        self.last_score = (min(self.last_score_a, self.last_score_b)
                           if self.cfg.dual_phase else self.last_score_a)
        self.scores.append(self.last_score_a)
        self.scores_dual.append(min(self.last_score_a, self.last_score_b))

        if self._conf.feed(self.last_score, now):
            self.reset()
            return True
        return False

    def stats(self) -> dict:
        s = np.array(self.scores) if self.scores else np.zeros(1)
        d = np.array(self.scores_dual) if self.scores_dual else np.zeros(1)
        return {
            "blocchi": len(self.scores),
            "p50": float(np.percentile(s, 50)),
            "p99": float(np.percentile(s, 99)),
            "max": float(s.max()),
            "sopra_soglia": int((s >= self.cfg.threshold).sum()),
            # La stessa audio letta con l'altra regola: e' il confronto
            # appaiato che serve a decidere, e costa solo tenerne il conto.
            "dual_max": float(d.max()),
            "dual_sopra_soglia": int((d >= self.cfg.threshold).sum()),
        }
