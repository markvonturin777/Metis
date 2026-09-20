# M0 — Walking Skeleton · Tracking

| | |
| :-- | :-- |
| **Stato** | 🔄 In corso |
| **Piano** | [M0_Walking_Skeleton.md](../SPECS/plan/M0_Walking_Skeleton.md) |
| **Durata prevista** | 7 giorni |
| **Inizio** | 2026-09-20 |
| **Fine** | — |
| **Tag** | `m0-skeleton` |

**Avanzamento:** `████░░░░░░░░░░░░░░░░` 24% — attività 9/38 · criteri di uscita 0/8
**Giorno 1 di 7: completato.**

> **Obiettivo:** rispondere con numeri misurati a *sta in 8 GB?* e *risponde in meno di 2 secondi?*

---

## 0. Ricognizione macchina — 2026-09-20

| Voce | Rilevato | Nota |
| :-- | :-- | :-- |
| GPU | RTX 2070 SUPER, **8192 MiB**, driver 581.08 | Conferma il vincolo di §3 della specifica |
| VRAM a riposo | **504 MiB** | Più bassa della stima 0,8–1,5 GB: budget più comodo del previsto |
| Monitor | 2× 1920×1080, DISPLAY2 a X=1920 | **Nessuna coordinata negativa, stessa risoluzione** → il rischio DPI di M4 è molto ridotto |
| Audio | Realtek HD Audio | Da confermare che il microfono sia su questo device |
| VS Code | `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe` | Già in `config/apps.toml` per M2 |
| GitHub Desktop | `%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe` | Idem |
| Git | 2.25.0 | OK |
| Python | **3.12.10** installato | Inizialmente presente solo l'alias Microsoft Store |
| Ollama | **0.34.2** installato, server su :11434 | Nessun account necessario: il sign-in serve solo ai modelli cloud |
| Disco C: | 27 GB → **34,9 GB liberi** dopo pulizia | Rientrato. Venv 1,14 GB + modello 5,2 GB |

---

## 1. Prerequisiti

- [x] Windows aggiornato, driver NVIDIA recenti — driver 581.08
- [x] Python 3.12 installato — 3.12.10
- [x] Git configurato — 2.25.0
- [ ] Microfono e cuffie funzionanti a livello di sistema
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

- [ ] `metis/audio/capture.py` — `InputStream` 16 kHz mono, callback non bloccante
- [ ] `metis/audio/vad.py` — Silero con `min_silence_duration_ms=250`
- [ ] `metis/audio/ptt.py` — hotkey globale `Ctrl+Alt+M`, comportamento **toggle**
- [ ] Segmento di parlato isolato correttamente, con timestamp di fine parlato

### Giorno 3 — Speech-to-Text

- [ ] `metis/stt/whisper_engine.py` con `faster-whisper small`, `int8_float16`, `cuda`
- [ ] `language="it"` esplicito, `beam_size=1`, `vad_filter=False`
- [ ] Latenza STT misurata su 10 frasi
- [ ] VRAM aggiuntiva dello STT misurata
- [ ] Confronto rapido con `base` e `medium` registrato (serve se il budget sfora)

### Giorno 4 — LLM in streaming

- [ ] `metis/llm/client.py` con `stream=True` e **`think=False`**
- [ ] TTFT e tok/s strumentati
- [ ] Segmentazione in frasi con `min_chars` implementata
- [ ] Frasi emesse progressivamente, non a fine generazione

### Giorno 5 — TTS e test di ascolto

- [ ] `metis/tts/kokoro_engine.py`, `lang_code="i"`, su **CPU**
- [ ] Riproduzione con interruzione immediata (`sd.stop()`) funzionante
- [ ] Piper `it_IT` installato per il confronto
- [ ] **10 frasi sintetizzate con entrambi** — tabella §4 compilata
- [ ] Tempo di sintesi del primo chunk misurato

### Giorno 6 — Cucitura della catena

- [ ] `metis/core/skeleton.py` — ciclo completo funzionante
- [ ] `TurnMetrics` definita e scritta su JSONL a ogni turno
- [ ] Conversazione vocale end-to-end riuscita

### Giorno 7 — Misure e decision gate

- [ ] 10 interazioni brevi misurate
- [ ] 10 interazioni medie misurate
- [ ] 72 minuti di inferenza continua per il picco VRAM
- [ ] Confronto 8B vs 4B completato
- [ ] Tabella risultati §3 compilata
- [ ] Ripartizione latenza §3.2 compilata
- [ ] **Decision gate D0 chiuso e scritto nella specifica**

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
| Latenza e2e p50 | < 1,2 s | da misurare al giorno 6 | — | ⬜ |
| Latenza e2e p95 | < 1,8 s | da misurare al giorno 6 | — | ⬜ |
| Qualità italiano | soggettiva | da valutare al giorno 5 | — | ⬜ |

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
| Endpointing VAD | 200–300 ms | — | — |
| STT | 150–350 ms | — | — |
| LLM TTFT | 150–400 ms | — | — |
| Prima frase | ~330 ms | — | — |
| Sintesi TTS | 100–250 ms | — | — |
| Buffer audio | 30–80 ms | — | — |
| **Totale** | **0,97–1,74 s** | — | — |

### 3.3 Budget VRAM reale

| Consumatore | Stimato | Misurato | Delta |
| :-- | ---: | ---: | :-- |
| Desktop Windows baseline | 0,8–1,5 GB | **0,66 GB** | meglio del previsto |
| LLM 8B Q4_K_M + KV cache q8_0 | ~5,1 GB | **5,42 GB** | +0,3 GB |
| STT faster-whisper small | ~0,6 GB | da misurare al giorno 3 | — |
| **Totale con LLM caricato** | 6,5–7,2 GB | **6,08 GB** | — |
| **Totale previsto con STT** | — | **~6,7 GB** | margine ~1,3 GB su 8 |

> Il budget di §3.2 della specifica regge. Kokoro e Silero restano su CPU come previsto, quindi non incidono.

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

## 5. Criteri di uscita

- [ ] Una frase pronunciata riceve una risposta vocale sensata in italiano
- [ ] Latenza e2e misurata su ≥ 20 interazioni
- [ ] Picco VRAM misurato su 72 minuti di inferenza continua
- [ ] Test di ascolto completato, con giudizio scritto
- [ ] Benchmark comparativo 4B vs 8B completato
- [ ] Ripartizione della latenza compilata stadio per stadio
- [ ] **Decision gate D0 chiuso**, decisioni scritte nella specifica
- [ ] `git tag m0-skeleton`

---

## 6. Decision gate D0

| Decisione | Criterio | Esito | Motivo |
| :-- | :-- | :-- | :-- |
| **Modello LLM definitivo** | VRAM ≤ 7,2 GB **e** tok/s ≥ 45 | — | — |
| **Motore TTS definitivo** | Giudizio di ascolto §4 | — | — |
| **Budget di latenza** | p50 < 1,5 s (tolleranza M0) | — | — |

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
