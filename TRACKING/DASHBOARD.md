# Metis — Dashboard di Avanzamento

> Stato vivo del progetto. Si aggiorna mentre si lavora.
> Riferimento: [Specifica V1.0](../SPECS/Metis_V1.0_Specifica_Ufficiale.md) · [Piano](../SPECS/plan/README.md)

**Ultimo aggiornamento:** 2026-09-20 — M0 giorno 1 chiuso

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
| **M0** | [Walking Skeleton](M0_tracking.md) | 🔄 | 9/38 | 0/8 | 2026-09-20 | — | `m0-skeleton` |
| **M1** | [Fondamenta Vocali](M1_tracking.md) | ⬜ | 0/30 | 0/9 | — | — | `m1-voice` |
| **M2** | [Capability Broker](M2_tracking.md) | ⬜ | 0/36 | 0/10 | — | — | `m2-broker` |
| **M3** | [Interfaccia Grafica](M3_tracking.md) | ⬜ | 0/38 | 0/10 | — | — | `m3-gui` |
| **M4** | [Automazione PC](M4_tracking.md) | ⬜ | 0/31 | 0/12 | — | — | `m4-automation` |
| **M5** | [Conoscenza](M5_tracking.md) | ⬜ | 0/30 | 0/13 | — | — | `m5-knowledge` |
| **M6** | [Integrazioni](M6_tracking.md) | ⬜ | 0/34 | 0/15 | — | — | `m6-integrations` |
| **M7** | [Consolidamento V1.0](M7_tracking.md) | ⬜ | 0/44 | 0/13 | — | — | `v1.0` |
| | **Totale** | | **9/281** | **0/90** | | | |

> Oltre a queste ci sono **30 caselle di prerequisito** e **131 esiti di test** nelle tabelle dei singoli file: 531 punti di controllo in totale.

**Iterazione corrente:** M0 · **Prossima attività:** giorno 2 — cattura audio, VAD, push-to-talk

---

## Requisiti non funzionali — stato vivo

I valori si riempiono man mano. La colonna "misurato" va aggiornata a ogni misura, non solo in M7.

| NFR | Metrica | Target | Misurato | Quando | Esito |
| :-- | :-- | :-- | :-- | :-- | :-: |
| 1 | Latenza e2e p50 / p95 | < 1,2 s / < 1,8 s | — / — | M0, M7 | ⬜ |
| 2 | TTFT | < 400 ms | **33 ms** prompt breve · ~330–400 ms a 2k · 627 ms a 3,6k | M0 ✅ | 🟡 |
| 3 | Throughput | ≥ 45 tok/s | **67,1 tok/s** | M0 ✅ | ✅ |
| 4 | Picco VRAM | ≤ 7,2 GB | **6,08 GB** senza STT | M0 ✅ | ✅ |
| 5 | WER italiano | < 12% | — | M7 | ⬜ |
| 6 | Falsi risvegli | < 1 / 8 h | — | M1, M7 | ⬜ |
| 7 | Auto-inneschi da eco | **0** | — | M1, M7 | ⬜ |
| 8 | Reattività GUI | ≥ 30 fps, no freeze > 100 ms | — | M3, M4, M7 | ⬜ |
| 9 | Azioni T3 non confermate | **0** | — | M2, M7 | ⬜ |
| 10 | Stabilità 72 h | RSS < +10% | — | M7 | ⬜ |

---

## Decision gate

| Gate | Quando | Decisione | Esito | Data |
| :-- | :-- | :-- | :-- | :-- |
| **D0** | Fine M0 | Modello LLM definitivo | — | — |
| **D0** | Fine M0 | Motore TTS definitivo | — | — |
| **D0** | Fine M0 | Budget di latenza confermato | — | — |
| **D1** | Fine M1 | Wake word promossa o sostituita | — | — |
| **D2** | Fine M4 | UIA sufficiente o serve OCR | — | — |
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
| — | — | — |
