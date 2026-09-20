# M7 — Consolidamento V1.0 · Tracking

| | |
| :-- | :-- |
| **Stato** | ⬜ Non iniziata |
| **Piano** | [M7_Consolidamento_V1.md](../SPECS/plan/M7_Consolidamento_V1.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | — |
| **Fine** | — |
| **Tag** | `v1.0` |

**Avanzamento:** `░░░░░░░░░░░░░░░░░░░░` 0% — attività 0/31 · criteri di uscita 0/13

> **Obiettivo:** far vivere Metis nel PC senza sorveglianza.
> **Regola:** in M7 non si aggiungono funzionalità. Ogni idea nuova va nel backlog V1.1.

---

## 1. Prerequisiti

- [ ] M6 chiuso, tutte le decisioni D0–D3 documentate
- [ ] Tutte le funzionalità della specifica implementate
- [ ] Audit log popolato da settimane di uso reale

---

## 2. Attività

### Giorni 1–2 — Gestione degli errori

- [ ] `metis/core/errors.py` con la matrice completa
- [ ] Ollama non raggiungibile → retry 3× con backoff, poi dichiara
- [ ] Ollama in OOM → scarica STT dalla GPU, riprova
- [ ] Microfono scollegato → rileva, attende, GUI in rosso
- [ ] Rete assente → percorso web fallisce, il resto funziona
- [ ] Home Assistant offline → riconnessione con backoff
- [ ] SMTP fallito → **rischedula fra 10 min**, non perde l'email
- [ ] Strumento in eccezione → `Result.error`, mai solleva
- [ ] TTS fallito → fallback Piper, poi solo testo
- [ ] STT vuoto → torna a `IN_ASCOLTO` **in silenzio**
- [ ] VRAM > 7,5 GB → scarica STT, indicatore rosso
- [ ] **Nessun traceback raggiunge l'utente** — verificato

### Giorni 3–4 — Soak test 72 ore

- [ ] `tests/soak/run_soak.py` scritto
- [ ] Interazione sintetica ogni 10 min, mix 40/30/20/10
- [ ] Campionamento a 60 s: RSS, VRAM, handle, thread, code
- [ ] **Soak avviato** (giorno 3, non giorno 7)
- [ ] Iniezione ora 6: Ollama fermo 5 min
- [ ] Iniezione ora 18: rete assente 30 min
- [ ] Iniezione ora 30: microfono scollegato 10 min
- [ ] Iniezione ora 42: Home Assistant fermo
- [ ] Iniezione ora 54: VRAM saturata da altro processo
- [ ] Grafico finale prodotto e analizzato

### Giorni 5–6 — Verifica NFR

- [ ] 100 interazioni **reali** (non sintetiche) per NFR-1 e NFR-2
- [ ] 50 frasi registrate con la tua voce e trascritte a mano per NFR-5
- [ ] Query SQL per NFR-9
- [ ] Tabella §4 compilata con tutte le evidenze

### Giorni 7–8 — Packaging e residenza

- [ ] `metis.spec` in modalità **`onedir`**
- [ ] Modelli esterni al bundle, in `data/`
- [ ] Hidden imports risolti (`comtypes`, backend `sounddevice`, plugin PySide6)
- [ ] **Bundle provato su cartella pulita**, senza venv nel PATH
- [ ] `QSystemTrayIcon` con menu completo
- [ ] Icona che riflette lo stato con i colori di M3
- [ ] Uscita pulita: thread fermati, scheduler chiuso, device audio rilasciato
- [ ] `scripts/install_autostart.ps1` con Utilità di pianificazione
- [ ] Trigger `AtLogOn` con ritardo 60 s, `RestartCount 3`
- [ ] **`RunLevel Limited`** — non amministratore
- [ ] Avvio robusto: sequenza in 6 passi di §4.4
- [ ] Saluto vocale una tantum all'avvio riuscito
- [ ] `docs/INSTALL.md` completo e provato da zero

---

## 3. Soak test — risultati

| Metrica | Inizio | 24 h | 48 h | 72 h | Crescita | Esito |
| :-- | ---: | ---: | ---: | ---: | ---: | :-: |
| RSS | — | — | — | — | — | ⬜ |
| VRAM | — | — | — | — | — | ⬜ |
| Handle | — | — | — | — | — | ⬜ |
| Thread | — | — | — | — | — | ⬜ |
| Latenza p95 | — | — | — | — | — | ⬜ |
| Dimensione code | — | — | — | — | — | ⬜ |

> Valutare la **pendenza**, non il valore finale. Una crescita che si stabilizza dopo poche ore è cache; una lineare è un leak.

**Crash nelle 72 h:** — **Iniezioni gestite correttamente:** __/5

---

## 4. Verifica formale dei 10 NFR

Ogni riga richiede un'evidenza allegata. **Nessuna casella si spunta per convinzione.**

| NFR | Metrica | Target | Misurato | Evidenza | Esito |
| :-- | :-- | :-- | :-- | :-- | :-: |
| 1 | Latenza e2e p50 / p95 | < 1,2 s / < 1,8 s | — / — | 100 interazioni reali | ⬜ |
| 2 | TTFT | < 400 ms | — | stesse 100 interazioni | ⬜ |
| 3 | Throughput | ≥ 45 tok/s | — | metriche Ollama | ⬜ |
| 4 | Picco VRAM | ≤ 7,2 GB | — | soak, 1 Hz × 72 h | ⬜ |
| 5 | WER italiano | < 12% | — | 50 frasi, riferimento manuale | ⬜ |
| 6 | Falsi risvegli | < 1 / 8 h | — | audit log su 72 h | ⬜ |
| 7 | Auto-inneschi da eco | **0** | — | 2 h TTS continuo | ⬜ |
| 8 | Reattività GUI | ≥ 30 fps, no freeze > 100 ms | — | timer durante soak | ⬜ |
| 9 | Azioni T3 non confermate | **0** | — | query SQL | ⬜ |
| 10 | Stabilità | RSS < +10% in 72 h | — | soak | ⬜ |

### 4.1 Se un NFR non passa

| NFR | Leva | Applicata |
| :-- | :-- | :-: |
| 1, 2, 3 | Modello 4B come router; STT `base`; VAD a 200 ms | ⬜ |
| 4 | Contesto a 4k; STT su CPU | ⬜ |
| 5 | Whisper `medium` se la VRAM lo consente | ⬜ |
| 6 | Soglia wake word alzata; ri-addestramento con più negativi | ⬜ |
| **7** | **Bloccante.** Rivedere il gating di M1 | ⬜ |
| 8 | Profilare e spostare l'operazione bloccante sul worker | ⬜ |
| **9** | **Bloccante.** Difetto del broker | ⬜ |
| 10 | Profilare il leak con `tracemalloc` | ⬜ |

---

## 5. Criteri di uscita

- [ ] **Tutti e 10 gli NFR verdi**, con evidenza misurata allegata
- [ ] Soak 72 h completato: nessun crash, crescita RSS < 10%
- [ ] Tutte e 5 le iniezioni di fallimento gestite correttamente
- [ ] Nessuna modalità di errore produce un traceback all'utente
- [ ] Bundle eseguibile su cartella pulita, senza venv nel PATH
- [ ] Avvio automatico funzionante **da PC spento**, verificato con riavvio reale
- [ ] Avvio robusto anche se Ollama parte dopo Metis
- [ ] Metis **non** gira come amministratore
- [ ] Tray icon con stato, kill switch e uscita pulita
- [ ] Uscita pulita: nessun thread orfano, device audio rilasciato
- [ ] `docs/INSTALL.md` provato su installazione da zero
- [ ] **Specifica aggiornata: ogni stima sostituita dal valore misurato**
- [ ] `git tag v1.0`

---

## 6. Chiusura del progetto

- [ ] `git tag v1.0`
- [ ] Specifica ufficiale aggiornata con i numeri veri
- [ ] Tabella di stato in [DASHBOARD.md](DASHBOARD.md) aggiornata
- [ ] Backlog V1.1 consolidato
- [ ] Report di verifica NFR archiviato accanto alla specifica

---

## 7. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | | | | | |

---

## 8. Diario

### AAAA-MM-GG
-

---

## 9. Retrospettiva

<!-- Da compilare a progetto chiuso. Cosa ha funzionato, cosa rifaresti diversamente. -->

**Cosa ha funzionato:**
-

**Cosa rifarei diversamente:**
-

**Stime vs realtà:**

| Iterazione | Prevista | Effettiva | Delta |
| :-- | ---: | ---: | ---: |
| M0 | 7 gg | — | — |
| M1 | 8 gg | — | — |
| M2 | 8 gg | — | — |
| M3 | 10 gg | — | — |
| M4 | 8 gg | — | — |
| M5 | 8 gg | — | — |
| M6 | 8 gg | — | — |
| M7 | 8 gg | — | — |
| **Totale** | **65 gg** | — | — |
