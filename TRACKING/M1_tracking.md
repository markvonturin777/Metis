# M1 — Fondamenta Vocali · Tracking

| | |
| :-- | :-- |
| **Stato** | ⬜ Non iniziata |
| **Piano** | [M1_Fondamenta_Vocali.md](../SPECS/plan/M1_Fondamenta_Vocali.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | — |
| **Fine** | — |
| **Tag** | `m1-voice` |

**Avanzamento:** `░░░░░░░░░░░░░░░░░░░░` 0% — attività 0/31 · criteri di uscita 0/9

> **Obiettivo:** rendere il sistema capace di stare acceso senza impazzire.

---

## 1. Prerequisiti

- [ ] M0 chiuso, D0 completato
- [ ] Modello LLM e motore TTS definitivi scelti
- [ ] Catena vocale funzionante da push-to-talk
- [ ] Piper installato (serve per i dati sintetici della wake word)

---

## 2. Attività

### Giorni 1–4 — Wake word "Hey Metis"

- [ ] 3.000–5.000 positivi generati con Piper, variando voce, velocità e pitch
- [ ] 500 positivi difficili: "Hey Metis" dentro frasi più lunghe
- [ ] 10.000+ negativi dal dataset openWakeWord
- [ ] **500 negativi mirati** in italiano: "metti", "mettiamo", "ehi", "hey", "Mattia", "amnesie"
- [ ] Augmentation: rumore di fondo a SNR variabile
- [ ] Augmentation: riverbero con RIR sintetiche
- [ ] **Alcune centinaia di campioni registrati con il microfono reale**
- [ ] Training completato
- [ ] `data/wakeword/hey_metis.onnx` esportato
- [ ] `metis/audio/wakeword.py` integrato, gira su CPU
- [ ] Soglia esposta in configurazione

### Giorni 5–6 — Macchina a stati

- [ ] `State` enum con tutti gli 11 stati, inclusi quelli non ancora usati
- [ ] `Event` enum
- [ ] **Tabella `TRANSITIONS` come dato**, non catena di `if`
- [ ] Transizione non prevista → log, **mai** eccezione
- [ ] Timeout per stato implementati (8 s, 30 s, 5 s, 30 s, 20 s)
- [ ] Macchina testabile senza audio, con eventi iniettati
- [ ] Test: 100 eventi casuali fuori sequenza, nessuna eccezione

### Giorno 7 — Anti-eco e barge-in

- [ ] **L1 half-duplex:** nello stato `PARLATO` i frame non arrivano a VAD e STT
- [ ] Stream audio **sempre aperto**, si scartano i frame (nessuna riapertura del device)
- [ ] **L2 barge-in:** il rilevatore wake word riceve i frame anche in `PARLATO`
- [ ] Su barge-in: `tts.stop()` chiamato
- [ ] Su barge-in: **coda TTS svuotata**
- [ ] Su barge-in: **stream LLM annullato**
- [ ] Latenza di interruzione misurata

### Giorno 8 — Osservabilità

- [ ] `structlog` configurato con doppio sink: console + JSONL
- [ ] Campi obbligatori su ogni evento: `ts`, `state`, `event`, `turn_id`, `latency_ms`
- [ ] Ogni transizione di stato produce una riga di log
- [ ] Schema `audit` SQLite creato
- [ ] Audit log append-only: nessun `UPDATE`/`DELETE` nel codice

---

## 3. Misure da registrare

### 3.1 Test obbligatori

| Test | Procedura | Soglia | Misurato | Esito |
| :-- | :-- | :-- | :-- | :-: |
| **NFR-7 auto-inneschi** | 2 h di TTS in loop, microfono aperto, altoparlanti al volume d'uso | **0** | — | ⬜ |
| **NFR-6 falsi risvegli** | 8 h di uso normale: lavoro, musica, video, telefonate | < 1 | — | ⬜ |
| Mancati riconoscimenti | 50 pronunce di "Hey Metis" in condizioni normali | < 10% | — | ⬜ |
| Latenza barge-in | 20 interruzioni misurate | < 200 ms | — | ⬜ |

### 3.2 Taratura della soglia wake word

| Soglia provata | Falsi risvegli / 8 h | Mancati / 50 | Scelta |
| ---: | ---: | ---: | :-: |
| 0.4 | — | — | ⬜ |
| 0.6 | — | — | ⬜ |
| 0.8 | — | — | ⬜ |

**Soglia adottata:** —

### 3.3 Falsi risvegli — cosa li ha provocati

Annotare la causa serve a capire se servono altri negativi mirati.

| # | Data/ora | Cosa stava succedendo | Frase o suono scatenante |
| :-- | :-- | :-- | :-- |
| | | | |

---

## 4. Criteri di uscita

- [ ] **NFR-7:** zero auto-inneschi in 2 h di TTS continuo
- [ ] **NFR-6:** < 1 falso risveglio in 8 h di uso normale
- [ ] Mancato riconoscimento < 10% su 50 tentativi
- [ ] Barge-in entro 200 ms, e **Metis non riprende da solo** dopo l'interruzione
- [ ] Push-to-talk funziona in parallelo alla wake word
- [ ] Ogni transizione di stato tracciata nel log JSONL
- [ ] Macchina a stati sopravvive a 100 eventi fuori sequenza
- [ ] Schema audit log creato e scrivibile
- [ ] `git tag m1-voice`

---

## 5. Decision gate D1

| Decisione | Criterio | Esito | Motivo |
| :-- | :-- | :-- | :-- |
| **Wake word promossa** | Mancati < 10% **e** falsi risvegli < 1/8 h | — | — |

Alternativa in caso di esito negativo: Porcupine con keyword custom. Il push-to-talk copre comunque il caso nel frattempo.

---

## 6. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | | | | | |

---

## 7. Diario

### AAAA-MM-GG
-

---

## 8. Note per M2

-
