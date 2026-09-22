# Metis — Dashboard di Avanzamento

> Stato vivo del progetto. Si aggiorna mentre si lavora.
> Riferimento: [Specifica V1.0](../SPECS/Metis_V1.0_Specifica_Ufficiale.md) · [Piano](../SPECS/plan/README.md)

**Ultimo aggiornamento:** 2026-09-22 — **M5 chiusa.** Metis consulta le fonti, ricorda, e rifiuta di agire dopo aver letto una pagina web. Zero azioni T2/T3 sui sei payload di injection, zero falsi rifiuti

---

## Come si usano questi file

| Cartella | Natura | Si modifica |
| :-- | :-- | :-- |
| [`SPECS/`](../SPECS/) | Specifica e piano — **come si fa** | Raramente, per decisioni |
| `TRACKING/` | Stato — **a che punto sei** | Continuamente |

Un file per iterazione. Ogni file ha: prerequisiti, attività spuntabili, misure da registrare, criteri di uscita, decision gate, registro problemi e diario.

**Legenda stato:** ⬜ non iniziata · 🔄 in corso · ✅ completata · ⛔ bloccata · ⏸️ sospesa

---

## Stato generale

| # | Iterazione | Stato | Attività | Criteri uscita | Inizio | Fine | Tag |
| :-- | :-- | :-: | ---: | ---: | :-- | :-- | :-- |
| **M0** | [Walking Skeleton](M0_tracking.md) | ✅ | 38/38 | 8/8 | 2026-09-20 | 2026-09-20 | `m0-skeleton` |
| **M1** | [Fondamenta Vocali](M1_tracking.md) | ✅ | 33/37 | 6/6 | 2026-09-21 | 2026-09-21 | `m1-voice` |
| **M2** | [Capability Broker](M2_tracking.md) | ✅ | 33/33 | 9/10 | 2026-09-21 | 2026-09-21 | `m2-broker` |
| **M3** | [Interfaccia Grafica](M3_tracking.md) | ✅ | 30/32 | 8/10 | 2026-09-21 | 2026-09-21 | `m3-gui` |
| **M4** | [Automazione PC](M4_tracking.md) | ✅ | 28/31 | 10/12 | 2026-09-21 | 2026-09-21 | `m4-automation` |
| **M5** | [Conoscenza](M5_tracking.md) | ✅ | 30/30 | 13/13 | 2026-09-22 | 2026-09-22 | `m5-knowledge` |
| **M6** | [Integrazioni](M6_tracking.md) | ⬜ | 0/34 | 0/15 | — | — | `m6-integrations` |
| **M7** | [Consolidamento V1.0](M7_tracking.md) | ⬜ | 0/44 | 0/13 | — | — | `v1.0` |
| | **Totale** | | **192/278** | **54/87** | | | |

> Oltre a queste ci sono **30 caselle di prerequisito** e **131 esiti di test** nelle tabelle dei singoli file: 531 punti di controllo in totale.

**Iterazione corrente:** **M6 — Integrazioni.** Metis esce dal PC: posta,
scheduler, domotica. È la prima iterazione in cui un'azione ha effetti che non
si annullano riavviando, ed è per questo che M5 doveva chiudere con le difese
contro la prompt injection verificate — non scritte, verificate.

La riga scritta in M2 e mai attivata è entrata in funzione il 22 settembre:
nessuna azione T2 o T3 può nascere da un turno con contenuto web. Non è stato
necessario cambiare `policies.py`, solo alzare la bandiera.

**Rimandato alla v2:** la wake word. Banchi pronti, modello v3 pronto, si
riaccende con `enabled = true` in `config/wakeword.toml`. Vedi §21 della
specifica per cosa non va semplificato nel frattempo.

---

## Requisiti non funzionali — stato vivo

I valori si riempiono man mano. La colonna "misurato" va aggiornata a ogni misura, non solo in M7.

| NFR | Metrica | Target | Misurato | Quando | Esito |
| :-- | :-- | :-- | :-- | :-- | :-: |
| 1 | Latenza e2e p50 / p95 | < 1,2 s / < 1,8 s | **1119 / 1625 ms** | M0 ✅ | ✅ |
| 2 | TTFT | < 400 ms | **87 ms** in conversazione · ~330–400 a 2k · 627 a 3,6k | M0 ✅ | 🟡 |
| 3 | Throughput | ≥ 45 tok/s | **67,1 tok/s** | M0 ✅ | ✅ |
| 4 | Picco VRAM | ≤ 7,2 GB | **6,58 GB** con LLM+STT, soak 72 min | M0 ✅ | ✅ |
| 5 | WER italiano | < 12% | **8,6%** su 10 frasi | M0 parziale | 🟡 |
| 6 | Falsi risvegli | < 1 / 8 h | ⏸️ non applicabile in V1.0: senza wake word non ci sono risvegli | v2 | ⏸️ |
| 7 | Auto-inneschi da eco | **0** | ❌ **57 in 125 min** → D1. Non applicabile in V1.0 | v2 | ⏸️ |
| 8 | Reattività GUI | ≥ 30 fps, no freeze > 100 ms | **62 fps**, 0 blocchi su 2 962 campioni, max **3,0 ms** — dopo la correzione della vista audit (M5 problema 13) | M3 ✅ · M4 ✅ · M5 ✅ | ✅ |
| 9 | Azioni T3 non confermate | **0** | **0** su 50 tentativi (M2) · **0** su 18 giri di injection (M5) | M2 ✅ · M5 ✅ | ✅ |
| 10 | Stabilità 72 h | RSS < +10% | 72 **min**: deriva −0,2 GB | M0 indicativo | 🟡 |

---

## Decision gate

| Gate | Quando | Decisione | Esito | Data |
| :-- | :-- | :-- | :-- | :-- |
| **D0** | Fine M0 | Modello LLM definitivo | ✅ Qwen 3 8B Q4_K_M | 2026-09-20 |
| **D0** | Fine M0 | Motore TTS definitivo | ✅ **Piper paola** (non Kokoro) | 2026-09-20 |
| **D0** | Fine M0 | Budget di latenza confermato | ✅ con riserva sulle frasi lunghe | 2026-09-20 |
| **D1** | Fine M1 | Wake word promossa o sostituita | ⏸️ **rimandata alla v2** — NFR-7 non superato (57 auto-inneschi), v3 promettente ma non verificato. PTT unica via | 2026-09-21 |
| **D2** | Fine M4 | UIA sufficiente o serve OCR | 🔄 **niente OCR per ora**, campione troppo piccolo: serve l'uso | 2026-09-21 |
| **D3** | Inizio M6 | AEC necessario o superfluo | 🔄 orientamento: **serve valutarlo** — uscita su altoparlanti, non cuffie | 2026-09-20 |

---

## Blocchi attivi

| # | Iterazione | Problema | Dal | Impatto | Azione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| — | — | *nessun blocco attivo* | — | — | — |

---

## Decisioni prese — registro

Ogni decisione che si scosta dalla specifica o che chiude un punto aperto va annotata qui, con la data e il motivo. Serve a te fra sei mesi.

| Data | Iterazione | Decisione | Motivo |
| :-- | :-- | :-- | :-- |
| 2026-09-20 | — | Qwen 3 8B come modello primario, 14B esclusa | Vincolo VRAM 8 GB |
| 2026-09-20 | — | Wake word "Hey Metis" | Scelta utente |
| 2026-09-20 | — | Niente AEC nella V1.0: half-duplex + barge-in via wake word | Costo zero, copre il caso d'uso |
| 2026-09-20 | — | Capability Broker T0–T3 al posto del blocco `os`/`shutil` | Il divieto va applicato al registro strumenti |
| 2026-09-20 | — | PySide6 al posto di PyQt6 | Licenza LGPL |
| 2026-09-20 | M0 | torch **CPU-only** invece che CUDA | Nessun componente usa torch per la GPU: Ollama e CTranslate2 hanno runtime propri. ~4 GB risparmiati |
| 2026-09-20 | M0 | `qwen3:4b` **non scaricato** | L'8B passa ogni criterio con margine; il 4B serve solo come piano B |
| 2026-09-20 | M0 | `soxr` aggiunto allo stack | Il Yeti su WASAPI accetta **solo 48 kHz**: decimazione 3:1 obbligatoria |
| 2026-09-22 | M5 | `max_results` **fuori** dallo schema di `web_search` | Il numero di fonti è una decisione di budget del contesto, non una preferenza che il modello debba interpretare |
| 2026-09-22 | M5 | Il contenuto web **non entra** nella memoria conversazionale | Un testo ostile in cronologia insisterebbe su turni che non sono più marcati come contaminati |
| 2026-09-22 | M5 | Un piano che mescola ricerca e azione esegue **solo** la ricerca | L'azione sarebbe decisa da una pagina che ancora non è stata letta |
| 2026-09-22 | M5 | Riassunto con **due soglie**, non solo il 70% del piano | Con 16 messaggi di parlato il 70% non si raggiunge mai: i turni usciti dalla finestra sparivano |
| 2026-09-22 | M5 | Budget del system prompt portato da 600 a **700 token** | Misurati 640 con `prompt_eval_count`: si è allargata la voce invece di accorciare la persona |
| 2026-09-22 | M5 | La pulizia dell'HTML è il **primo** passo dell'estrazione, non il ripiego | `trafilatura` estrae il testo nascosto con i CSS: il payload bianco-su-bianco arrivava al prompt |
| 2026-09-22 | M5 | La vista audit ridisegna solo quando l'audit log cambia, e con colonne `Interactive` | `ResizeToContents` più un timer a 1 Hz bloccavano la GUI per 2,6 s ogni 3. Un test di reattività deve far girare l'event loop e misurare il **secondo** disegno, non il primo |

---

## Backlog V1.1

Le idee che emergono durante lo sviluppo finiscono qui, non nella V1.0. È la contromisura al rischio R8.

| # | Idea | Nata in | Nota |
| :-- | :-- | :-- | :-- |
| 1 | Lettura posta in arrivo | Specifica | Richiede IMAP e modello di privacy diverso |
| 2 | Integrazione calendario | Specifica | — |
| 3 | Memoria a lungo termine | Specifica | — |
| 4 | Modalità analisi profonda con Qwen 30B-A3B su CPU | Specifica | Già progettata in §3.3 |
| 5 | Streaming videocamera in GUI | Specifica | — |
| 6 | Temi e personalizzazione estetica | Specifica | — |

---

## Cronologia dei tag

| Tag | Data | Nota |
| :-- | :-- | :-- |
| `m0-skeleton` | 2026-09-20 | Walking skeleton: catena vocale completa. NFR-1/2/3/4 verificati, D0 chiuso |
| `m5-knowledge` | 2026-09-22 | Ricerca web fondata, memoria con riassunto, slot anaforici, persona tarata. 0 azioni T2/T3 sui sei payload di injection |
