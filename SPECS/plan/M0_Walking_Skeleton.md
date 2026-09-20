# M0 — Walking Skeleton

> **Maturità:** P0 Pappagallo · **Durata:** 1 settimana (7 giorni) · **Tag:** `m0-skeleton`

---

## Obiettivo

Rispondere con **numeri misurati** alle due domande che determinano tutto il resto del progetto:

1. **Sta in 8 GB di VRAM?**
2. **Risponde in meno di 2 secondi?**

Tutto il resto di M0 è strumentale a queste due misure. Non si costruisce un assistente in questa settimana: si costruisce **lo strumento che dice se l'assistente è costruibile come specificato**.

---

## Prerequisiti

- [ ] Windows 10/11 aggiornato, driver NVIDIA recenti
- [ ] Python 3.12 installato (`py -3.12 --version`)
- [ ] Git configurato
- [ ] Microfono e cuffie collegati e funzionanti a livello di sistema
- [ ] Almeno 30 GB liberi su disco (modelli + cache)

---

## Deliverable

Uno **script CLI**. Nessuna GUI, nessuno strumento, nessuna wake word, nessuna persona.

```
push-to-talk → microfono → Silero VAD → faster-whisper → Ollama → Kokoro → altoparlanti
```

Più un **report di benchmark** con i numeri reali.

---

## Step operativi

### Giorno 1 — Ambiente e infrastruttura di misura

#### 1.1 Struttura del progetto

```bash
cd C:/Users/Marco/Desktop/Projects/AI/Metis
py -3.12 -m venv .venv
.venv/Scripts/activate
mkdir -p metis/{audio,stt,tts,llm,core} benchmarks config data
```

#### 1.2 `pyproject.toml` minimo per M0

```toml
[project]
name = "metis"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "sounddevice",
    "numpy",
    "silero-vad",
    "faster-whisper",
    "ollama",
    "kokoro",
    "soundfile",
    "pynput",
    "nvidia-ml-py",
    "psutil",
    "structlog",
]
```

> Installare `torch` con CUDA **prima** delle altre dipendenze, altrimenti pip risolve la variante CPU:
> `pip install torch --index-url https://download.pytorch.org/whl/cu121`

#### 1.3 Ollama

```bash
# installare Ollama, poi:
ollama pull qwen3:8b
ollama pull qwen3:4b    # serve per il confronto del giorno 7
```

Variabili d'ambiente da impostare **a livello di sistema** (non solo nella shell), perché Ollama gira come servizio:

| Variabile | Valore | Perché |
| :-- | :-- | :-- |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Mitigazione M2 di §3.3 della specifica: libera 0,3–0,5 GB |
| `OLLAMA_FLASH_ATTENTION` | `1` | Riduce l'occupazione della KV cache |
| `OLLAMA_KEEP_ALIVE` | `-1` | Il modello non si scarica mai |

Riavviare il servizio Ollama dopo averle impostate.

#### 1.4 `benchmarks/vram_latency.py`

Lo strumento di misura. Va scritto **prima** di tutto il resto, perché è ciò che dà la risposta.

Deve misurare, per ogni modello sotto test:

| Metrica | Come |
| :-- | :-- |
| VRAM a riposo | `nvidia_ml_py` prima del caricamento |
| VRAM a modello caricato | dopo la prima inferenza, non dopo il pull |
| VRAM al picco | campionamento a 5 Hz durante 10 generazioni |
| TTFT | timestamp tra invio della richiesta e primo token dello stream |
| tok/s | token generati / tempo di generazione, escluso il TTFT |

```python
# scheletro
import time, threading
import pynvml_like as nvml   # nvidia-ml-py: import pynvml
import ollama

def sample_vram(handle, stop_evt, out):
    while not stop_evt.is_set():
        out.append(nvml.nvmlDeviceGetMemoryInfo(handle).used / 1024**3)
        time.sleep(0.2)

def bench(model: str, prompt: str, n: int = 10):
    # 1. VRAM baseline
    # 2. warm-up: una generazione scartata (carica il modello)
    # 3. thread di campionamento VRAM
    # 4. n generazioni con stream=True, misurando TTFT e tok/s
    # 5. ritorna dict con p50/p95 di TTFT, media tok/s, picco VRAM
    ...
```

Opzioni da passare a Ollama in tutte le misure:

```python
options = {"num_ctx": 8192, "temperature": 0.7, "top_p": 0.9}
ollama.chat(model=model, messages=msgs, stream=True, think=False, options=options)
```

> `think=False` è **obbligatorio**. Senza, si misura la thinking mode e i numeri sono inutilizzabili.

**Output del giorno 1:** una tabella con VRAM e tok/s reali di `qwen3:8b`.

---

### Giorno 2 — Cattura audio, VAD e push-to-talk

#### 2.1 Cattura microfono — `metis/audio/capture.py`

```python
import sounddevice as sd
# 16 kHz, mono, int16 — formato atteso sia da Silero sia da Whisper
SAMPLE_RATE = 16000
BLOCK = 512          # 32 ms a 16 kHz: granularità richiesta da Silero VAD
```

Usare `sd.InputStream` con callback, che scrive in una `queue.Queue`. **Non** bloccare nel callback: qualunque elaborazione pesante va fuori.

#### 2.2 VAD — `metis/audio/vad.py`

`silero-vad` espone `load_silero_vad()` e `VADIterator`. Parametri di partenza:

| Parametro | Valore iniziale | Effetto |
| :-- | :-- | :-- |
| `threshold` | 0.5 | Sensibilità al parlato |
| `min_silence_duration_ms` | **250** | **È il pavimento della latenza.** Vedi §6.2 |
| `speech_pad_ms` | 100 | Evita di tagliare le sillabe iniziali |

Tarare `min_silence_duration_ms` il giorno 7: sotto i 200 ms taglia le pause naturali, sopra i 400 ms l'attesa diventa percepibile.

#### 2.3 Push-to-talk — `metis/audio/ptt.py`

```python
from pynput import keyboard
# Hotkey globale Ctrl+Alt+M
```

Comportamento: **toggle**, non hold. Premere una volta apre l'ascolto, il VAD chiude da solo a fine frase. Tenere premuto per parlare è scomodo e complica il codice senza vantaggi.

**Output del giorno 2:** premendo `Ctrl+Alt+M` e parlando, si ottiene un array numpy con il segmento di parlato isolato, e il timestamp di fine parlato.

---

### Giorno 3 — Speech-to-Text

#### 3.1 `metis/stt/whisper_engine.py`

```python
from faster_whisper import WhisperModel

model = WhisperModel(
    "small",
    device="cuda",
    compute_type="int8_float16",
)

segments, info = model.transcribe(
    audio,                  # np.float32, 16 kHz, normalizzato in [-1, 1]
    language="it",          # NON lasciare autodetect: costa tempo e sbaglia sulle frasi brevi
    beam_size=1,            # greedy: più veloce, differenza di WER trascurabile sul parlato breve
    vad_filter=False,       # il VAD lo abbiamo già fatto noi
    condition_on_previous_text=False,
)
```

#### 3.2 Misure da registrare

| Metrica | Come |
| :-- | :-- |
| Latenza STT | da `t_speech_end` a testo finale disponibile |
| VRAM aggiuntiva | differenza di VRAM prima/dopo il caricamento del modello |

Provare anche `base` e `medium` per avere il confronto pronto in caso di sforamento del budget.

**Output del giorno 3:** trascrizione in console con latenza misurata su 10 frasi.

---

### Giorno 4 — LLM in streaming

#### 4.1 `metis/llm/client.py`

```python
import ollama, time

def stream_reply(messages: list[dict]):
    t0 = time.perf_counter()
    ttft = None
    for chunk in ollama.chat(
        model="qwen3:8b",
        messages=messages,
        stream=True,
        think=False,                       # §7.2 — critico
        options={"num_ctx": 8192, "temperature": 0.7, "top_p": 0.9,
                 "keep_alive": -1},
    ):
        if ttft is None:
            ttft = time.perf_counter() - t0
        yield chunk["message"]["content"]
```

#### 4.2 Segmentazione in frasi per il TTS

La singola ottimizzazione che vale più di tutte le altre messe insieme: **non aspettare la fine della generazione**.

```python
import re
_END = re.compile(r"[.!?…](\s|$)")

def sentences(token_stream, min_chars: int = 25):
    """Emette frasi complete appena disponibili.
    min_chars evita di sintetizzare frammenti come 'Sì.' che rendono
    la prosodia a scatti."""
    buf = ""
    for tok in token_stream:
        buf += tok
        while (m := _END.search(buf)) and m.end() >= min_chars:
            yield buf[:m.end()].strip()
            buf = buf[m.end():]
    if buf.strip():
        yield buf.strip()
```

**Output del giorno 4:** token in console, TTFT e tok/s misurati, frasi emesse progressivamente.

---

### Giorno 5 — Text-to-Speech e test di ascolto

#### 5.1 `metis/tts/kokoro_engine.py`

```python
from kokoro import KPipeline
pipeline = KPipeline(lang_code="i")     # 'i' = italiano
# Voci italiane disponibili: if_sara (f), im_nicola (m)
```

Kokoro gira su **CPU** per decisione di progetto (§3.2): libera 0,4 GB di VRAM e sul 5800X resta ampiamente in tempo reale.

#### 5.2 Test di ascolto — non è un passaggio formale

Il supporto italiano di Kokoro è coperto da meno voci e meno dati rispetto all'inglese. **Va ascoltato, non assunto.** Sintetizzare queste 10 frasi con Kokoro e con Piper `it_IT`, e dare un giudizio esplicito:

| # | Frase di test | Cosa mette alla prova |
| :-- | :-- | :-- |
| 1 | "I sistemi sono perfettamente operativi." | Prosodia dichiarativa neutra |
| 2 | "Ha davvero intenzione di aprire ventisette schede?" | Intonazione interrogativa |
| 3 | "La CPU è al sessantatré per cento, la VRAM a sei virgola due gigabyte." | Numeri e unità |
| 4 | "Aprirò Visual Studio Code e GitHub Desktop." | Nomi propri inglesi in frase italiana |
| 5 | "Informazione non presente nei sistemi." | La frase di rifiuto, che sentirai spesso |
| 6 | "Le danze abbiano inizio non appena lo desidera." | Registro formale, la persona Metis |
| 7 | "Promemoria impostato per domani alle diciassette." | Orari |
| 8 | "Attenzione: la temperatura della GPU ha raggiunto ottantadue gradi." | Urgenza |
| 9 | "Perché no. In fondo è solo il suo computer." | Ironia, pause |
| 10 | "Cerco su investing.com le notizie sui mercati." | Dominio web letto ad alta voce |

Criterio di giudizio: **la frase 5 e la frase 6 sono le decisive.** La prima la sentirai centinaia di volte, la seconda definisce se la persona funziona.

#### 5.3 Riproduzione

`sounddevice.play()` con la possibilità di **interruzione immediata** (`sd.stop()`): serve già da ora, perché il barge-in di M1 si appoggerà a questa.

**Output del giorno 5:** audio in uscita, tempo di sintesi del primo chunk misurato, **giudizio scritto Kokoro vs Piper**.

---

### Giorno 6 — Cucitura della catena

#### 6.1 `metis/core/skeleton.py`

Il ciclo completo, sequenziale, senza macchina a stati (arriva in M1):

```python
while True:
    wait_for_hotkey()                       # ptt
    audio, t_speech_end = record_until_silence()
    text = stt.transcribe(audio)
    reply_stream = llm.stream_reply(history + [{"role":"user","content":text}])
    for sentence in sentences(reply_stream):
        pcm = tts.synth(sentence)
        play(pcm)                            # bloccante in M0
```

#### 6.2 Strumentazione della latenza

Una `dataclass` compilata a ogni interazione, scritta su JSONL. **Questa struttura resta in tutto il progetto.**

```python
@dataclass
class TurnMetrics:
    t_speech_end: float      # riferimento zero
    t_stt_done: float
    t_llm_sent: float
    t_ttft: float
    t_first_sentence: float
    t_first_audio: float     # ← NFR-1 si misura qui
    tokens: int
    tok_per_s: float
    vram_peak_gb: float
```

**Output del giorno 6:** conversazione vocale funzionante, ogni turno produce una riga di metriche.

---

### Giorno 7 — Misure e decision gate

#### 7.1 Campagna di misura

| Test | Ripetizioni | Cosa registrare |
| :-- | ---: | :-- |
| Interazione breve ("che ore sono") | 10 | Latenza end-to-end completa |
| Interazione media (2-3 frasi di risposta) | 10 | Idem + tok/s |
| VRAM sotto carico | 72 min continui | Picco, per NFR-4 |
| Confronto `qwen3:8b` vs `qwen3:4b` | 10 ciascuno | TTFT, tok/s, VRAM, qualità soggettiva in italiano |

#### 7.2 Tabella dei risultati — da compilare

| Metrica | Target | Qwen3 8B | Qwen3 4B | Esito |
| :-- | :-- | :-- | :-- | :-- |
| Picco VRAM | ≤ 7,2 GB | ___ | ___ | ⬜ |
| TTFT p50 | < 400 ms | ___ | ___ | ⬜ |
| tok/s | ≥ 45 | ___ | ___ | ⬜ |
| Latenza e2e p50 | < 1,2 s | ___ | ___ | ⬜ |
| Latenza e2e p95 | < 1,8 s | ___ | ___ | ⬜ |
| Qualità italiano | soggettiva | ___ | ___ | ⬜ |

#### 7.3 Ripartizione della latenza — da compilare

Serve a sapere **dove** intervenire se il totale sfora.

| Stadio | Budget | Misurato | Delta |
| :-- | ---: | ---: | ---: |
| Endpointing VAD | 200–300 ms | ___ | ___ |
| STT | 150–350 ms | ___ | ___ |
| LLM TTFT | 150–400 ms | ___ | ___ |
| Prima frase | ~330 ms | ___ | ___ |
| Sintesi TTS | 100–250 ms | ___ | ___ |
| Buffer audio | 30–80 ms | ___ | ___ |
| **Totale** | **0,97–1,74 s** | ___ | ___ |

---

## 7. Decision gate D0

Le tre decisioni si chiudono qui, con i numeri sopra alla mano.

| Decisione | Criterio | Se il criterio non è soddisfatto |
| :-- | :-- | :-- |
| **Modello LLM definitivo** | VRAM ≤ 7,2 GB **e** tok/s ≥ 45 | Passare a `qwen3:4b` come modello unico, oppure 4B come router + 8B per le risposte |
| **Motore TTS definitivo** | Giudizio di ascolto sulle 10 frasi | Passare a Piper `it_IT`. Non rimandare: il TTS è ovunque nel sistema |
| **Validità del budget di latenza** | p50 < 1,5 s (tolleranza su M0, senza fast-path) | Riaprire §6.2 della specifica **prima** di M1. Leve: STT `base`, VAD a 200 ms, modello 4B |

> **Il gate si chiude scrivendo le decisioni nel §2 changelog della specifica ufficiale**, non lasciandole in testa.

---

## Criteri di uscita

- [ ] Una frase pronunciata riceve una risposta vocale sensata in italiano
- [ ] Latenza end-to-end misurata e registrata su ≥ 20 interazioni
- [ ] Picco VRAM misurato durante 72 minuti di inferenza continua
- [ ] Test di ascolto Kokoro vs Piper completato, con giudizio scritto
- [ ] Benchmark comparativo 4B vs 8B completato
- [ ] Ripartizione della latenza compilata stadio per stadio
- [ ] **Decision gate D0 chiuso**, con le tre decisioni scritte nella specifica
- [ ] `git tag m0-skeleton`

---

## Fuori ambito per M0

Elencato per evitare la tentazione:

| Non si fa | Arriva in |
| :-- | :-- |
| GUI, anche minima | M3 |
| Wake word | M1 |
| Macchina a stati | M1 |
| Qualunque strumento o automazione | M2 |
| System prompt della persona | M5 |
| Memoria conversazionale (basta una lista in RAM) | M5 |
| Gestione errori decente | M7 |
| Barge-in | M1 |

Se in M0 si scrive codice che serve solo a M3, M0 dura due settimane invece di una e le due domande restano senza risposta.

---

## Rischi specifici di M0

| Rischio | Sintomo | Contromisura |
| :-- | :-- | :-- |
| `torch` CPU-only installato per errore | `device="cuda"` fallisce, oppure è lentissimo | Verificare con `torch.cuda.is_available()` prima di procedere |
| Variabili Ollama non lette | VRAM più alta del previsto, KV cache non quantizzata | Impostarle a livello di sistema e riavviare il servizio, non nella shell |
| Thinking mode attiva per dimenticanza | TTFT di 5–20 s, benchmark inutilizzabile | `think=False` in **ogni** chiamata, incluse quelle di benchmark |
| VRAM misurata al pull invece che all'inferenza | Sottostima sistematica | Misurare sempre **dopo** un warm-up di generazione |
| Whisper con autodetect lingua | +200 ms e errori sulle frasi brevi | `language="it"` esplicito |
| Latenza misurata da inizio parlato | Numeri gonfiati e non confrontabili | Il riferimento zero è **la fine** del parlato |

---

## Handoff a M1

M0 consegna:

1. **I numeri.** Il budget di §3.2 e §6.2 della specifica è confermato o corretto.
2. **Le tre decisioni chiuse** di D0.
3. **Il codice riusabile:** `audio/capture.py`, `audio/vad.py`, `audio/ptt.py`, `stt/`, `tts/`, `llm/client.py`, la segmentazione in frasi e la `TurnMetrics`.
4. **Ciò che va buttato:** `core/skeleton.py`, il ciclo sequenziale. In M1 viene sostituito dalla macchina a stati. È codice usa-e-getta *per progetto*, non per sbaglio.
