# M0 — Walking Skeleton · Tracking

| | |
| :-- | :-- |
| **Stato** | ✅ **Completata** |
| **Piano** | [M0_Walking_Skeleton.md](../SPECS/plan/M0_Walking_Skeleton.md) |
| **Durata prevista** | 7 giorni |
| **Inizio** | 2026-09-20 |
| **Fine** | 2026-09-20 |
| **Tag** | `m0-skeleton` |

**Avanzamento:** `████████████████████` 100% — attività 38/38 · criteri di uscita 8/8
**M0 COMPLETATA.** Resta solo `git tag m0-skeleton`.

> **Obiettivo:** rispondere con numeri misurati a *sta in 8 GB?* e *risponde in meno di 2 secondi?*

---

## 0. Ricognizione macchina — 2026-09-20

| Voce | Rilevato | Nota |
| :-- | :-- | :-- |
| GPU | RTX 2070 SUPER, **8192 MiB**, driver 581.08 | Conferma il vincolo di §3 della specifica |
| VRAM a riposo | **504 MiB** | Più bassa della stima 0,8–1,5 GB: budget più comodo del previsto |
| Monitor | 2× 1920×1080, DISPLAY2 a X=1920 | **Nessuna coordinata negativa, stessa risoluzione** → il rischio DPI di M4 è molto ridotto |
| Microfono | **Blue Yeti Classic** su WASAPI, **solo 48 kHz**, 2 ch, latenza 3 ms | Resampling 3:1 a carico nostro: `soxr` |
| Uscita audio | **altoparlanti** — default: VG258QM via NVIDIA HD Audio | ⚠️ Altoparlanti + microfono aperto: **D3 si orienta verso AEC in M6** |
| VS Code | `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe` | Già in `config/apps.toml` per M2 |
| GitHub Desktop | `%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe` | Idem |
| Git | 2.25.0 | OK |
| Python | **3.12.10** installato | Inizialmente presente solo l'alias Microsoft Store |
| Ollama | **0.34.2** installato, server su :11434 | Nessun account necessario: il sign-in serve solo ai modelli cloud |
| Disco C: | 27 GB → **34,9 GB liberi** dopo pulizia | Rientrato. Venv 1,14 GB + modello 5,2 GB |

---

## 0-bis. Taratura audio — 2026-09-20

Blue Yeti Classic, cardioide, altoparlanti del monitor.

| Metrica | Valore | Nota |
| :-- | ---: | :-- |
| Rumore di fondo | **-86,4 dBFS** | Stanza molto silenziosa |
| Voce rms p95 | -22,3 dBFS | Dopo riduzione del guadagno |
| Picco | **-9,6 dBFS** | In finestra obiettivo -12…-6 |
| Margine clipping | 9,6 dB | Era 2,7: guadagno abbassato |
| **SNR** | **55,4 dB** | Eccellente |
| Blocchi persi | **0** | Il resampling nel callback regge |
| **Endpointing VAD** | **264 ms** σ 14 | Teorico 282. Pavimento della latenza |

> **Due errori di misura corretti oggi**, entrambi miei e dello stesso tipo — una
> costante scelta a caso al posto di un valore derivato dai dati:
> 1. Livello voce come mediana su tutta la finestra → misurava le pause. Ora media
>    sui soli blocchi attivi, con soglia adattiva ancorata anche al livello del parlato.
> 2. Fine parlato via soglia `rms > -55 dBFS` → dispersione endpointing 90-390 ms.
>    Ora probabilità di Silero per blocco: dispersione 14 ms.

---

## 1. Prerequisiti

- [x] Windows aggiornato, driver NVIDIA recenti — driver 581.08
- [x] Python 3.12 installato — 3.12.10
- [x] Git configurato — 2.25.0
- [x] Microfono funzionante — Blue Yeti tarato, SNR 55,4 dB. *Altoparlanti, non cuffie: vedi D3*
- [x] ≥ 30 GB liberi su disco — 34,9 GB dopo pulizia

---

## 2. Attività

### Giorno 1 — Ambiente e infrastruttura di misura

- [x] venv creato e attivo — 1,14 GB
- [x] `pyproject.toml` con le dipendenze M0 — *solo le dipendenze di M0, le altre si aggiungono iterazione per iterazione*
- [x] Impalcatura creata: `metis/{core,audio,stt,tts,llm}`, `benchmarks/`, `config/`, `data/`, `.gitignore`
- [x] `torch` installato — **CPU-only 2.9.1+cpu**: nulla nel nostro stack usa torch per la GPU, risparmiati ~4 GB
- [x] ~~`torch.cuda.is_available()`~~ — **non applicabile**: la GPU la usano Ollama e CTranslate2, non torch
- [x] Ollama installato, `qwen3:8b` scaricato — *4B rimandato: l'8B passa tutto con margine*
- [x] Variabili impostate e **verificate nel log del server**: `FLASH_ATTENTION:true`, `KV_CACHE_TYPE:q8_0`, `KEEP_ALIVE:infinito`
- [x] Servizio Ollama riavviato dopo le variabili
- [x] `benchmarks/vram_latency.py` scritto — *da verificare all'esecuzione*
- [x] Prima misura VRAM + tok/s di `qwen3:8b` registrata

### Giorno 2 — Cattura audio, VAD, push-to-talk

- [x] `metis/audio/capture.py` — WASAPI 48 kHz → mono → soxr 3:1 → blocchi da 512. **0 blocchi persi** su 3 prove
- [x] `metis/audio/vad.py` — Silero **a chiamata diretta**, non `VADIterator`: isteresi 0,50/0,35, scarto frasi < 200 ms
- [x] `metis/audio/ptt.py` — `Ctrl+Alt+M` toggle, verificata in esecuzione
- [x] Segmento isolato con **due** timestamp: `t_speech_end` (zero per NFR-1) e `t_endpoint`

### Giorno 3 — Speech-to-Text

- [x] `metis/stt/whisper_engine.py` — `small`, `int8_float16`, `cuda`. Serve `metis/core/cuda_libs.py`: torch CPU non porta cuBLAS/cuDNN
- [x] `language="it"`, `beam_size=1`, `vad_filter=False`, `condition_on_previous_text=False`
- [x] Latenza STT su 10 frasi reali: **205 ms** medi, p95 253 (budget 150–350)
- [x] VRAM STT: **+0,39 GB** (stimata 0,6). **Totale LLM+STT: 6,58 GB**, margine 1,4
- [x] `medium` **non necessario**: `small` + vocabolario di dominio sta gia' sotto target

### Giorno 4 — LLM in streaming

- [x] `metis/llm/client.py` — streaming, `think=False`, annullamento cooperativo per il barge-in di M1
- [x] TTFT e tok/s strumentati in `GenMetrics`
- [x] Segmentazione in frasi — **9 test in `tests/test_split_sentences.py`**
- [x] Frasi progressive: prima frase a 668 ms invece di 1555 (−887 ms)

### Giorno 5 — TTS e test di ascolto

- [x] Kokoro scritto e misurato — **scartato**: 858 ms medi contro un budget di 250
- [x] `Player` con coda e `stop()` che svuota **anche la coda**, non solo l'audio
- [x] Piper installato, 2 voci italiane — **`it_IT-paola-medium` scelta**
- [x] 40 campioni generati in `data/tts_compare/`, 10 frasi × 4 voci
- [x] Sintesi primo chunk: **96 ms p50** (Piper). Kokoro era 858

### Giorno 6 — Cucitura della catena

- [x] `metis/core/skeleton.py` — catena completa, 10 turni reali
- [x] `TurnMetrics` in `metis/core/metrics.py`, JSONL in `data/logs/turns.jsonl`
- [x] **Conversazione vocale end-to-end riuscita**

### Giorno 7 — Misure e decision gate

- [x] 10 interazioni reali misurate
- [x] 11 interazioni lunghe misurate (fino a 8,7 s di audio)
- [x] 72 minuti di campionamento continuo: **picco 6,58 GB**, deriva −0,225 GB, 0 superamenti
- [x] ~~Confronto 8B vs 4B~~ — non necessario, l'8B supera ogni criterio
- [x] Tabella risultati §3 compilata
- [x] Ripartizione latenza §3.2 compilata
- [x] **Decision gate D0 chiuso e scritto nella specifica**

---

## 3. Misure da registrare

### 3.1 Risultati per modello

Misurato il 2026-09-20, 10 run, `num_ctx=8192`, KV cache `q8_0`, flash attention on.
Dettaglio: `benchmarks/results/bench_20260920_180904.json`

| Metrica | Target | Qwen3 8B | Qwen3 4B | Esito |
| :-- | :-- | :-- | :-- | :-: |
| Picco VRAM | ≤ 7,2 GB | **6,08 GB** | non scaricato | ✅ |
| TTFT p50 (prompt breve) | < 400 ms | **33 ms** | — | ✅ |
| TTFT p95 (prompt breve) | — | 47 ms | — | ✅ |
| tok/s | ≥ 45 | **67,1** | — | ✅ |
| Temp GPU max | — | 54 °C | — | ✅ |
| Caricamento a freddo | — | 57,8 s | — | ℹ️ rilevante per M7 |
| Latenza e2e p50 | < 1,2 s | **1119 ms** su 40 turni | — | ✅ |
| Latenza e2e p95 | < 1,8 s | **1625 ms** | — | ✅ |
| Qualità italiano | soggettiva | buona in conversazione; allucina sui fatti | — | 🟡 |

> **Qwen3 4B non è stato scaricato.** L'8B passa tutti i criteri con ampio margine: il confronto serve solo se qualcosa peggiora. Risparmiati 2,6 GB.

### 3.1-bis TTFT al crescere del contesto — `benchmarks/ctx_sweep.py`

Il benchmark principale usa prompt da ~50 token, dove il TTFT è quasi nullo.
NFR-2 parla di contesto ≤ 2k, quindi serviva lo sweep.

| Prompt reale | TTFT medio | NFR-2 (< 400 ms) |
| ---: | ---: | :-: |
| 228 tok | 83 ms | ✅ |
| 943 tok | 159 ms | ✅ |
| 3.643 tok | 627 ms | ❌ |
| 7.343 tok | 854 ms | ❌ |

**Velocità di prefill ricavata: ~5.800 tok/s.** A 2k token il TTFT si colloca intorno ai 330–400 ms: NFR-2 è rispettato al limite, e la soglia "≤ 2k" nella sua formulazione si rivela ben scelta.

**Conseguenza di progetto:** il percorso conversazionale (contesto breve) sta largamente dentro il budget. Il percorso RAG di M5, che il §10.3 della specifica prevede fino a ~3.500 token di contenuto web, paga **~600 ms di TTFT** — ma è interamente assorbito dal filler vocale, che copre già 1,5–4 s di rete. Il progetto regge; da verificare di nuovo in M5 con il contesto reale.

### 3.2 Ripartizione della latenza

Serve a sapere **dove** intervenire se il totale sfora.

| Stadio | Budget | Misurato | Delta |
| :-- | ---: | ---: | ---: |
| Endpointing VAD | 200–300 ms | **264 ms** (p95 284, σ 14) | ✅ in budget |
| STT | 150–350 ms | **205 ms** (p95 253) | ✅ in budget |
| LLM TTFT | 150–400 ms | **84 ms** (p95 99) | ✅ |
| Prima frase | ~330 ms | **275 ms** (p95 458) | ✅ p50 |
| Sintesi TTS | 100–250 ms | **96 ms** (p95 184) | ✅ |
| Buffer audio | 30–80 ms | incluso nel totale | — |
| **TOTALE (NFR-1)** | p50 < 1,2 s | **p50 924 ms · p95 1285 ms** | ✅ |

### 3.3 Budget VRAM reale

| Consumatore | Stimato | Misurato | Delta |
| :-- | ---: | ---: | :-- |
| Desktop Windows baseline | 0,8–1,5 GB | **0,66 GB** | meglio del previsto |
| LLM 8B Q4_K_M + KV cache q8_0 | ~5,1 GB | **5,42 GB** | +0,3 GB |
| STT faster-whisper small | ~0,6 GB | **0,39 GB** | meglio del previsto |
| **Totale con LLM caricato** | 6,5–7,2 GB | **6,08 GB** | — |
| **Totale misurato LLM + STT** | ~6,7 GB | **6,58 GB** | ✅ margine 1,4 GB su 8 |

> Il budget di §3.2 della specifica regge. Kokoro e Silero restano su CPU come previsto, quindi non incidono.

---

## 3-ter. STT — corpus reale, 10 frasi (2026-09-20)

Corpus in `data/corpus/`: WAV + riferimento. Riutilizzabile senza rifare le
registrazioni, e base di partenza per le 50 frasi che NFR-5 chiede in M7.

| Configurazione | WER | Errori | STT medio | p95 |
| :-- | ---: | ---: | ---: | ---: |
| `small` baseline | 11,4 % | 6/70 | 207 ms | 261 ms |
| **`small` + vocabolario dominio** | **8,6 %** | **6/70** | **205 ms** | **253 ms** |
| `medium` | non provato — non serve | | | |

**Decisione:** `small` + `initial_prompt` di dominio, in `config/stt.toml`.

### Errori residui — tutti dello stesso tipo

| Atteso | Ottenuto | Natura |
| :-- | :-- | :-- |
| "Aprimi le news" | "Apri mille news" | confine di parola |
| "Apri Visual Studio" | "Apreviso studio" | confine di parola + termine inglese |
| **"No, annulla"** | **"No, nulla"** | ⚠️ **vedi nota** |

> **Due correzioni di misura, di nuovo.**
> 1. Il WER contava `diciassette → 17` come errore. Non lo e': Whisper normalizza
>    i numeri in cifre e per un assistente vocale le forme sono equivalenti.
>    Corretto in `metis/stt/metrics.py` con `num2words`. Da 14,3% a 11,4%.
> 2. `diff_words` confrontava posizione per posizione: su una frase con 2 errori
>    ne mostrava 7, perche' dopo una cancellazione tutto slitta. Ora ricostruisce
>    l'allineamento dalla matrice di Levenshtein.

> ⚠️ **NOTA PER M2 — "annulla" → "nulla".** E' l'errore piu' pericoloso del
> corpus: un comando di annullamento che non viene riconosciuto come tale,
> proprio nel momento in cui l'utente sta cercando di fermare qualcosa. Il
> fast-path dei comandi di stop/annulla deve tollerare l'errore di una parola,
> non fare confronto esatto.

> ℹ️ **Il vocabolario di dominio ha risolto "Metis" → "Mattis".** Whisper
> sbagliava il nome dell'assistente. Ora e' attivo per default e va esteso
> ogni volta che emerge un termine ricorrente sbagliato.

---

## 4. Test di ascolto TTS

Giudizio su ogni frase: ✅ buona · 🟡 accettabile · ❌ inutilizzabile

| # | Frase | Kokoro | Piper | Note |
| :-- | :-- | :-: | :-: | :-- |
| 1 | "I sistemi sono perfettamente operativi." | — | — | |
| 2 | "Ha davvero intenzione di aprire ventisette schede?" | — | — | |
| 3 | "La CPU è al sessantatré per cento, la VRAM a sei virgola due gigabyte." | — | — | |
| 4 | "Aprirò Visual Studio Code e GitHub Desktop." | — | — | |
| 5 | **"Informazione non presente nei sistemi."** | — | — | *decisiva: la sentirai spesso* |
| 6 | **"Le danze abbiano inizio non appena lo desidera."** | — | — | *decisiva: definisce la persona* |
| 7 | "Promemoria impostato per domani alle diciassette." | — | — | |
| 8 | "Attenzione: la temperatura della GPU ha raggiunto ottantadue gradi." | — | — | |
| 9 | "Perché no. In fondo è solo il suo computer." | — | — | |
| 10 | "Cerco su investing.com le notizie sui mercati." | — | — | |

**Verdetto:** —

---

## 4-bis. Conversazione reale — 10 turni (2026-09-20)

### Latenza: NFR-1 rispettato

| Stadio | p50 | p95 | Budget | |
| :-- | ---: | ---: | :-- | :-: |
| Endpointing | 255 ms | 260 ms | 200–300 | ✅ |
| STT | 209 ms | 369 ms | 150–350 | ✅ p50 |
| LLM TTFT | **84 ms** | 99 ms | 150–400 | ✅ molto sotto |
| Prima frase | 275 ms | 458 ms | 0–330 | ✅ p50 |
| TTS | 96 ms | 184 ms | 100–250 | ✅ |
| **TOTALE** | **924 ms** | **1285 ms** | < 1200 / < 1800 | ✅ |

VRAM a fine sessione: **6,50 GB**.

### Difetti di qualità osservati — input per M2 e M5

Il giorno 6 doveva misurare la latenza, e l'ha fatto. Ma la conversazione ha
esposto, su dieci turni, esattamente i problemi che le iterazioni successive
devono risolvere. Vale la pena averne l'evidenza registrata.

| # | Osservato | Dove si risolve |
| :-- | :-- | :-- |
| 1 | **"La RTX 3080 costa intorno ai 500-600 euro"** — prezzo inventato con piena sicurezza | **M5** grounding: è il caso da manuale di §5.1 |
| 2 | **"La GPU? Se non la usi è probabilmente a 30°C"** — inventa invece di dire che non può saperlo | **M2** strumento T0 `get_telemetry`: la risposta diventa un fatto |
| 3 | **"Che ore sono?" → "Le ore sono quelle che ti sei svegliato"** | M2 (strumento) + M5 (direttiva di incertezza) |
| 4 | **Ripetizione verbatim**: al turno 7 ha ripetuto parola per parola la risposta del turno 6 | **M5** memoria conversazionale |
| 5 | Dà del **"tu"**, non del "lei" | **M5** system prompt definitivo (qui è la versione ridotta dello scheletro) |
| 6 | Si definisce **"fatta di codice"** — genere della persona non deciso | **M5** — decisione aperta |
| 7 | "finché non si stanchi" — errore di concordanza | Intrinseco all'8B, tollerabile |

> **Nota.** I punti 1 e 2 non sono difetti dell'implementazione: sono il
> comportamento atteso di un LLM senza strumenti e senza grounding. Averli
> visti al giorno 6 con esempi concreti vale più di qualunque descrizione
> astratta nella specifica.

> ✅ **Lo STT ha retto bene sul parlato spontaneo**, inclusa una frase di 20
> parole. Nessuna trascrizione scartata come sospetta su 10 turni.

---

## 4-ter. Aggregato su 21 turni reali — il quadro vero

| Stadio | p50 | p95 | max | Budget | |
| :-- | ---: | ---: | ---: | :-- | :-: |
| Endpointing | 260 | 290 | 292 | 300 | ✅ |
| STT | 259 | **459** | 500 | 350 | 🟡 p95 sfora |
| LLM TTFT | 86 | 101 | 102 | 400 | ✅ |
| Prima frase | 311 | **497** | 623 | 330 | 🟡 p95 sfora |
| TTS | 135 | 227 | 240 | 250 | ✅ |
| **TOTALE** | **1086** | **1336** | 1721 | <1200 / <1800 | ✅ |

### ⚠️ La latenza dipende quasi linearmente dalla lunghezza del parlato

Correlazione durata-audio / latenza-STT: **+0,95**.

| Frasi | p50 totale |
| :-- | ---: |
| Corte (≤ 4,4 s) | **789 ms** |
| Lunghe (> 4,4 s) | **1251 ms** |
| **Costo della lunghezza** | **+462 ms** |

**Il budget di §6.2 della specifica era tarato implicitamente sui comandi
brevi.** Nella conversazione reale le frasi lunghe sfondano da sole il target
p50. L'aggregato resta dentro solo perché mescola i due regimi.

**Proposta per M1 — STT speculativo.** Oggi i 260 ms di endpointing e i 259 di
STT sono *sequenziali*: si attende la conferma del silenzio, poi si trascrive.
Ma quando il silenzio comincia l'audio è già completo: si può avviare la
trascrizione al primo blocco di silenzio e annullarla se il parlato riprende.
Recupera fino a ~250 ms su ogni turno, e riporta anche le frasi lunghe sotto
il target. Va nella macchina a stati di M1, non qui.

### Difetti osservati — sessione 2

| # | Osservato | Dove si risolve |
| :-- | :-- | :-- |
| 8 | **Il VAD ha tagliato una frase a metà**: *"Perfetto. Mi sai spiegare…"* chiusa dopo "Perfetto", e Metis ha risposto al frammento | **M1** — `min_silence_ms=250` è troppo aggressivo per le pause di riflessione. Va tarato con più dati |
| 9 | **"VS Code originariamente sviluppato da GitHub"** — falso: è Microsoft dal 2015. La confusione nasce da Electron, che sì viene da GitHub | **M5** grounding |
| 10 | STT degrada sul parlato lungo e complesso (*"ma viso studio code adesso partiene a Microsoft Machila creato prima"*) | Intrinseco a `small`; l'LLM ha comunque recuperato l'intento |
| 11 | Segmento trascritto come `'.'` e **scartato correttamente** dal filtro `suspect` | ✅ funziona |
| 12 | **"Non posso aprire o spostare finestre"** — ha rifiutato l'azione invece di fingere | ✅ buon segno per M5 |

---

## 4-quater. Terza sessione — 30 turni totali

| Stadio | p50 | p95 | Budget | |
| :-- | ---: | ---: | :-- | :-: |
| Endpointing | 260 | 290 | 300 | ✅ |
| STT | 263 | 437 | 350 | 🟡 p95 |
| LLM TTFT | 87 | 105 | 400 | ✅ |
| Prima frase | **343** | 631 | 330 | ❌ **sfora** |
| TTS | 145 | 294 | 250 | 🟡 p95 |
| **TOTALE** | **1119** | **1625** | <1200 / <1800 | ✅ |

NFR-1 resta rispettato sull'aggregato, ma la terza sessione da sola stava a
**p50 1334 ms**, fuori target. Due difetti trovati, entrambi corretti.

### Difetto A — markdown inviato al TTS

In **4 turni su 30** il modello ha prodotto grassetto sul canale vocale:
`"La **Bauhaus** fu..."`, `"corrente dell'**astrattismo**"`. Gli asterischi
finivano dritti in Piper. Corretto in `_clean()`: markdown rimosso all'ultimo
punto prima della sintesi.

### Difetto B — il primo chunk aspettava frasi intere

`prima_frase` misura il tempo dal primo token al primo chunk completo. Con
risposte da 130-220 caratteri in una sola frase, si aspettava tutta la frase:
**706 ms nel caso peggiore**, contro un budget di 330.

Corretto con `max_chars=90` in `split_sentences`: oltre quella soglia il chunk
si spezza a un confine secondario — virgola, punto e virgola, trattino. Il
valore non è arbitrario, si ricava dalla velocità misurata: 67 tok/s ≈ 270
caratteri al secondo, quindi 330 ms di budget valgono ~90 caratteri.

Effetto atteso: la frase su Pollock passa da 489 a ~219 ms di attesa.
**Da riverificare con una sessione dopo la correzione.**

### Difetti di qualità — sessione 3, il quadro peggiore finora

| # | Osservato | Nota |
| :-- | :-- | :-- |
| 13 | **"Lucello si chiama *Lucio* in italiano"** — confabulazione totale su uno STT sbagliato (*"l'uccello di Harry Potter"* → *"lucello"*) | Il modello ha inventato un nome invece di chiedere |
| 14 | **"fare balle brucia"** → ha risposto con *"bruciatore a legna"* | Idem: input incomprensibile, risposta sicura di sé |
| 15 | **"destrare"** (per "addestrare") → *"la destra è un po' più divertente"* | Idem |
| 16 | **Persona alla deriva**: *"io sono un gatto che ha imparato a parlare"* | System prompt ridotto dello scheletro |
| 17 | Riferimento a Harry Potter (il bezoar) non riconosciuto | Atteso da un 8B |

> 🔴 **IL PATTERN PIÙ IMPORTANTE DI M0.** Quando lo STT sbaglia, il modello
> **non chiede chiarimenti: confabula con sicurezza**. Tre casi su dieci in
> questa sessione. Eppure il segnale per accorgersene ce l'abbiamo già:
> `Transcript.avg_logprob` e `no_speech_prob` sono calcolati e inutilizzati.
>
> **Azione per M5:** percorso "non ho capito, ripeta" attivato dalla confidenza
> dello STT, non dal contenuto. Ed esporre `avg_logprob` in `TurnMetrics`, che
> oggi non lo registra.

---

## 4-quinquies. Quarta sessione e chiusura degli stadi

40 turni reali in log. Aggregato finale **prima** delle ultime correzioni:
p50 **1119 ms**, p95 **1541 ms** — NFR-1 rispettato.

### Difetto C — il cap era sul budget, non sotto

Dopo la correzione B lo stadio `prima_frase` restava a 391 ms. Il motivo e'
aritmetico e me l'ero perso: **generare 90 caratteri a ~230 car/s costa gia'
333 ms**. Avevo messo il cap *esattamente sul budget* invece che sotto.

Il primo chunk ha ora soglie proprie (`first_max_chars=45`), perche' e' l'unico
che determina quando Metis comincia a parlare: i successivi sono coperti dalla
riproduzione del precedente.

Verificato con `benchmarks/first_chunk_sweep.py`, senza microfono — lo stadio
e' interamente LLM + segmentazione:

| Cap | prima_frase p50 | Caratteri |
| --: | --: | --: |
| nessuno | 446 ms ❌ | 105 |
| 90 | 324 ms | 75 |
| **45 — scelto** | **181 ms** ✅ | 38 |
| 30 | 121 ms | 23 |

**Proiezione:** p50 totale da 1125 a ~830 ms, perche' scende anche il TTS.
Conferma end-to-end rimandata alla prima sessione di M1.

### Difetto D — bug nello scheletro

`min_chars=... if first else ...` era valutato **una sola volta** alla creazione
del generatore, quindi il ramo non aveva alcun effetto. Le soglie del primo
chunk sono state spostate dentro `stream_sentences`, dove lo stato e' noto.

### Qualita' — sessione 4

La persona funziona meglio: *"La differenza e'... astronomica."* e' arguzia
riuscita. Ma le confabulazioni continuano, e una merita di essere registrata:

> **"La forza non e' un dono, ma una scelta." — Gandalf**
>
> Citazione **inventata di sana pianta**, attribuita a un personaggio reale,
> con tanto di virgolette. E' il caso peggiore per un assistente: forma
> perfettamente credibile, contenuto falso. Nessun grounding web la
> intercetterebbe se non cercasse *apposta* di verificarla.

Altre: *"La Fashion Week si tiene sempre in autunno"* (ce ne sono almeno due
l'anno), *"Gnocchi fatti a mano, pasta frolla..."* (la pasta frolla non c'entra).

---

## 5. Criteri di uscita

- [x] Una frase pronunciata riceve una risposta vocale sensata in italiano
- [x] Latenza e2e misurata su **40 interazioni reali** in 4 sessioni
- [x] Picco VRAM su 72 min: **6,58 GB** — NFR-4 rispettato con 1,4 GB di margine
- [x] Test di ascolto completato: **Piper paola** scelta
- [x] ~~Benchmark 4B vs 8B~~ — **non necessario**: l'8B passa tutto con margine
- [x] Ripartizione della latenza compilata stadio per stadio
- [x] **Decision gate D0 chiuso**, decisioni scritte nella specifica
- [ ] `git tag m0-skeleton`

---

## 6. Decision gate D0

| Decisione | Criterio | Esito | Motivo |
| :-- | :-- | :-- | :-- |
| **Modello LLM definitivo** | VRAM ≤ 7,2 GB **e** tok/s ≥ 45 | ✅ **Qwen 3 8B Q4_K_M** | 6,58 GB e 67,1 tok/s: entrambi con margine |
| **Motore TTS definitivo** | Giudizio di ascolto §4 | ✅ **Piper `it_IT-paola-medium`** | 102 ms contro gli 858 di Kokoro |
| **Budget di latenza** | p50 < 1,5 s (tolleranza M0) | ✅ **confermato** | p50 1119 ms su 40 turni, ~830 atteso dopo le correzioni |

Se un criterio non passa, la leva è in [M0 §7](../SPECS/plan/M0_Walking_Skeleton.md#7-decision-gate-d0).

---

## 7. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | | | | | |

---

## 8. Diario

<!-- Una voce per giornata di lavoro. Breve. Serve a ricostruire il perché delle decisioni. -->

### AAAA-MM-GG
-

---

## 9. Note per M1

<!-- Cose scoperte in M0 che cambiano il lavoro di M1 -->

-
