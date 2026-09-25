# Metis — Dashboard di Avanzamento

> Stato vivo del progetto. Si aggiorna mentre si lavora.
> Riferimento: [Specifica V1.0](../Metis_V1.0_Specifica_Ufficiale.md) · [Piano](../plan/README.md)

**Ultimo aggiornamento:** 2026-09-25 — **M7: codice e strumenti pronti, prove lunghe aperte.** Matrice degli errori, tray, autostart, soak, verifica NFR, bundle provato su cartella pulita. Il soak breve ha trovato un difetto presente da M4 — Ollama ricaricava il modello due volte per turno — e le latenze sono scese da 5,8–15 s a 1,3–2,4 s

---

## Come si usano questi file

| Cartella | Natura | Si modifica |
| :-- | :-- | :-- |
| [`SPECS/PHASE0/plan/`](../plan/) e la [specifica](../Metis_V1.0_Specifica_Ufficiale.md) | Specifica e piano — **come si fa** | Raramente, per decisioni |
| `SPECS/PHASE0/TRACKING/` | Stato — **a che punto sei** | Continuamente |

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
| **M6** | [Integrazioni](M6_tracking.md) | 🔄 | 32/34 | 9/15 | 2026-09-23 | — | `m6-integrations` |
| **M7** | [Consolidamento V1.0](M7_tracking.md) | 🔄 | 30/39 | 5/13 | 2026-09-23 | — | `v1.0` |
| | **Totale** | | **254/273** | **68/87** | | | |

> Oltre a queste ci sono **30 caselle di prerequisito** e **131 esiti di test** nelle tabelle dei singoli file: 531 punti di controllo in totale.

**Iterazione corrente:** **M7 — Consolidamento V1.0, in attesa delle prove lunghe.**
Tutto il codice di M7 è scritto e verificato. Mancano le prove che chiedono
tempo o la voce dell'utente: 72 ore di soak, 100 interazioni reali (NFR-1/2/3),
50 frasi registrate (NFR-5), l'autostart provato con un riavvio vero,
l'installazione da zero con [docs/INSTALL.md](../../../docs/INSTALL.md). I comandi
sono in [M7 §5](M7_tracking.md). **NFR-1 è a rischio** (M7 §4.1).

**M6 in pausa** per scelta: Home Assistant, account SMTP e riavvio vero
rimandati. Gli indirizzi email vanno in `config/email.local.toml`, ignorato
da git — non in `email.toml`, che è nel repository.

**Da sapere prima di usare M6:** le notifiche di Windows sono **disattivate**
per questo account (`ToastEnabled = 0`). Metis lo dice all'avvio; i
promemoria arrivano comunque a voce.

**Rimandato alla v2:** la wake word. Banchi pronti, modello v3 pronto, si
riaccende con `enabled = true` in `config/wakeword.toml`. Vedi §21 della
specifica per cosa non va semplificato nel frattempo.

---

## Requisiti non funzionali — stato vivo

I valori si riempiono man mano. La colonna "misurato" va aggiornata a ogni misura, non solo in M7.

| NFR | Metrica | Target | Misurato | Quando | Esito |
| :-- | :-- | :-- | :-- | :-- | :-: |
| 1 | Latenza e2e p50 / p95 | < 1,2 s / < 1,8 s | **1119 / 1625 ms** in M0, senza router · **1,9–2,3 s** in conversazione nel soak breve di M7, con router | M0 ✅ · M7 ⚠️ | 🟡 |
| 2 | TTFT | < 400 ms | **87 ms** in conversazione · ~330–400 a 2k · 627 a 3,6k | M0 ✅ | 🟡 |
| 3 | Throughput | ≥ 45 tok/s | **67,1 tok/s** · 51–59 nel soak breve di M7 | M0 ✅ | ✅ |
| 4 | Picco VRAM | ≤ 7,2 GB | **6,58 GB** con LLM+STT, soak 72 min | M0 ✅ | ✅ |
| 5 | WER italiano | < 12% | **8,6%** su 10 frasi | M0 parziale | 🟡 |
| 6 | Falsi risvegli | < 1 / 8 h | ⏸️ non applicabile in V1.0: senza wake word non ci sono risvegli | v2 | ⏸️ |
| 7 | Auto-inneschi da eco | **0** | ❌ **57 in 125 min** → D1. Non applicabile in V1.0 | v2 | ⏸️ |
| 8 | Reattività GUI | ≥ 30 fps, no freeze > 100 ms | **62 fps**, 0 blocchi su 2 962 campioni, max **3,0 ms** — dopo la correzione della vista audit (M5 problema 13) | M3 ✅ · M4 ✅ · M5 ✅ | ✅ |
| 9 | Azioni T3 non confermate | **0** | **0** su 50 tentativi (M2) · **0** su 18 giri di injection (M5) · **0** con email e dispositivi reali nel perimetro (M6) | M2 ✅ · M5 ✅ · M6 ✅ | ✅ |
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
| **D3** | Inizio M6 | AEC necessario o superfluo | ✅ **escluso dalla V1.0** — con la wake word in v2 il barge-in è il PTT, che funziona già con gli altoparlanti. Si decide con la wake word | 2026-09-23 |

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
| 2026-09-23 | M6 | AEC **escluso** dalla V1.0 (D3) | Senza wake word il barge-in è il PTT; l'AEC serve solo alla wake word, e si decide con lei in v2 |
| 2026-09-23 | M6 | Il prompt del router porta **calendario e intervalli già calcolati** | Qwen sbagliava 3 date relative su 7 ("lunedì" → sabato): sa leggere, non sa fare l'aritmetica dei giorni |
| 2026-09-23 | M6 | `misfire_grace_time = None`; l'ora di tolleranza separa "in orario" da "in ritardo" | Con 3600 APScheduler scartava in silenzio i promemoria scaduti da più di un'ora. Oltre l'ora: il promemoria arriva dicendolo, l'email **non parte** |
| 2026-09-23 | M6 | La conferma si può **aggiungere** sotto T3 (`ToolSpec.conferma`) | La data di un promemoria T1 va confermata sempre. È un `or`: nessun modo di toglierla a un T3 |
| 2026-09-23 | M6 | Il tier non si abbassa da `home_assistant.toml`; il modello non nomina mai un `entity_id` | Un file che abbassa un tier toglie una conferma con una riga; un `entity_id` libero renderebbe il perimetro quello di Home Assistant |
| 2026-09-23 | M6 | Email solo verso l'allowlist, ricontrollata **all'invio** | Togliere un indirizzo dal file blocca anche le email già programmate verso di lui |
| 2026-09-25 | M7 | **Un** retry verso Ollama, non tre; il recupero lo fa `SALUTE` in sottofondo | Su Windows una connessione rifiutata costa 2,26 s: tre tentativi erano 8 s di silenzio |
| 2026-09-25 | M7 | Una sola finestra di contesto (`NUM_CTX`) per router e conversazione | Con valori diversi Ollama ricarica il modello a ogni cambio: 3,6 s, due volte per turno, da M4 |
| 2026-09-25 | M7 | Con la tray, chiudere la finestra non chiude Metis; la pausa dell'ascolto non si toglie col PTT | L'uscita deve passare da un solo percorso; una pausa che si toglie per sbaglio non è una pausa |
| 2026-09-25 | M7 | Indirizzi email veri in `config/email.local.toml`, ignorato da git | `email.toml` è nel repository: un indirizzo scritto lì è pubblicato al primo push |
| 2026-09-25 | M7 | Il soak sostituisce il microfono, non usa un loopback, e scrive in un log suo | Nessun loopback qui; NFR-1 si misura sulle interazioni reali, non va mescolato con le sintetiche |

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
| 7 | Router e conversazione in parallelo | M7 | La leva più grande su NFR-1 (0,3–0,6 s). Si decide sui numeri delle 100 interazioni reali |
| 8 | "Ricordamelo fra 10 minuti" sulla notifica | M6 | Non verificabile con le notifiche spente su questa macchina |

---

## Cronologia dei tag

| Tag | Data | Nota |
| :-- | :-- | :-- |
| `m0-skeleton` | 2026-09-20 | Walking skeleton: catena vocale completa. NFR-1/2/3/4 verificati, D0 chiuso |
| `m5-knowledge` | 2026-09-22 | Ricerca web fondata, memoria con riassunto, slot anaforici, persona tarata. 0 azioni T2/T3 sui sei payload di injection |
