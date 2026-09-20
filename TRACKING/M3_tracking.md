# M3 — Interfaccia Grafica · Tracking

| | |
| :-- | :-- |
| **Stato** | ⬜ Non iniziata |
| **Piano** | [M3_Interfaccia_Grafica.md](../SPECS/plan/M3_Interfaccia_Grafica.md) |
| **Durata prevista** | 10 giorni |
| **Inizio** | — |
| **Fine** | — |
| **Tag** | `m3-gui` |

**Avanzamento:** `░░░░░░░░░░░░░░░░░░░░` 0% — attività 0/32 · criteri di uscita 0/10

> **Obiettivo:** dare a Metis una faccia che non si blocca.
> **Rischio dominante:** il freezing dell'UI. Si comincia dalla concorrenza, non dai widget.

---

## 1. Prerequisiti

- [ ] M2 chiuso, broker testato
- [ ] Macchina a stati con segnali osservabili
- [ ] Audit log popolato
- [ ] `TurnMetrics` prodotte a ogni turno

---

## 2. Attività

### Giorni 1–3 — Topologia dei thread

- [ ] `metis/gui/app.py` con `QApplication`
- [ ] `AudioWorker` — `QObject` + `moveToThread`, **non** sottoclasse di `QThread`
- [ ] `OrchestratorWorker` — idem
- [ ] `TtsWorker` — idem
- [ ] `MetricsWorker` — idem
- [ ] Tutti i segnali definiti e collegati a slot sul thread principale
- [ ] Conferma T3: `QWaitCondition` **con timeout**, mai attesa indefinita
- [ ] Timeout della `QWaitCondition` == timeout del broker, letto dalla stessa config
- [ ] Throttling `token` → flush a 20 Hz
- [ ] Throttling `frame_level` → flush a 15 Hz

### Giorni 4–5 — Modalità Minimal

- [ ] Finestra frameless, always-on-top, `Qt.Tool`, sfondo traslucido
- [ ] Indicatore di stato con la mappa colori completa (7 stati)
- [ ] VU meter del livello audio in ingresso
- [ ] Ultima frase trascritta, una riga troncata
- [ ] Pulsante push-to-talk
- [ ] Indicatore kill switch, visibile solo quando attivo
- [ ] Trascinamento implementato (`mousePressEvent` / `mouseMoveEvent`)
- [ ] Posizione persistita in `config/settings.toml`
- [ ] **Verifica: indicatore leggibile di sbieco e a due metri**

### Giorni 6–8 — Modalità Fullscreen

- [ ] Layout a tre colonne
- [ ] Widget conversazione con **append incrementale**, non ricostruzione
- [ ] Auto-scroll disattivato se l'utente scrolla verso l'alto
- [ ] Parziali Vosk in grigio, finale Whisper in chiaro
- [ ] Dashboard: CPU e RAM a 2 Hz
- [ ] Dashboard: VRAM e temperatura GPU a **1 Hz** (non di più)
- [ ] Dashboard: TTFT, tok/s, latenza p50/p95 su finestra di 50 turni
- [ ] Soglia VRAM 7,5 GB → indicatore rosso + avviso
- [ ] Dialogo conferma T3 con strumento, argomenti **completi** e tier
- [ ] Countdown del timeout visibile
- [ ] **Nessun pulsante di default; focus su "Nega"**
- [ ] Visualizzatore audit log filtrabile per tier ed esito
- [ ] Contenitore vuoto per l'editor comandi custom (riempito in M4)

### Giorni 9–10 — Profiling

- [ ] `QTimer` a 16 ms per rilevare i blocchi dell'event loop
- [ ] 20 turni completi profilati
- [ ] Frame rate misurato durante generazione + telemetria
- [ ] Confronto telemetria vs `nvidia-smi`
- [ ] Passaggio Minimal ↔ Fullscreen testato
- [ ] Verifica per ispezione: nessun accesso a widget da thread secondari

---

## 3. Misure da registrare

| Test | Soglia | Misurato | Esito |
| :-- | :-- | :-- | :-: |
| Blocco massimo event loop | < 100 ms | — | ⬜ |
| Frame rate sotto inferenza | ≥ 30 fps | — | ⬜ |
| Scarto telemetria vs `nvidia-smi` | < 5% | — | ⬜ |
| Latenza di cambio modalità | — | — | ⬜ |

### 3.1 Blocchi rilevati

| # | Durata | Operazione responsabile | Risolto spostando su | Esito |
| :-- | ---: | :-- | :-- | :-: |
| | | | | |

---

## 4. Criteri di uscita

- [ ] **NFR-8:** nessun freeze > 100 ms durante l'inferenza
- [ ] ≥ 30 fps durante generazione con telemetria attiva
- [ ] Nessun accesso ai widget da thread secondari — verificato per ispezione
- [ ] Passaggio Minimal ↔ Fullscreen senza perdita di stato
- [ ] Metriche coincidono con `nvidia-smi` entro il 5%
- [ ] Il dialogo T3 **non** può essere approvato con Invio o Esc
- [ ] Timeout conferma GUI == timeout broker
- [ ] Parziali Vosk e finale Whisper distinguibili a colpo d'occhio
- [ ] Indicatore di stato leggibile a due metri
- [ ] `git tag m3-gui`

---

## 5. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | | | | | |

---

## 6. Diario

### AAAA-MM-GG
-

---

## 7. Note per M4

-
