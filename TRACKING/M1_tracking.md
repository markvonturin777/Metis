# M1 — Fondamenta Vocali · Tracking

| | |
| :-- | :-- |
| **Stato** | 🔄 In corso |
| **Piano** | [M1_Fondamenta_Vocali.md](../SPECS/plan/M1_Fondamenta_Vocali.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | 2026-09-21 |
| **Fine** | — |
| **Tag** | `m1-voice` |

**Avanzamento:** `██████░░░░░░░░░░░░░░` 30% — attività 7/31 · criteri di uscita 0/9
**Macchina a stati completata** (giorni 5-6 anticipati). Wake word: in attesa del test di pronuncia.

> **Obiettivo:** rendere il sistema capace di stare acceso senza impazzire.

---

## 1. Prerequisiti

- [x] M0 chiuso, D0 completato
- [x] Qwen 3 8B + Piper `it_IT-paola-medium`
- [x] Catena vocale funzionante, 40 turni misurati
- [x] Piper installato + **`en_US-libritts_r-medium`: 904 parlanti** per la varietà

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

- [x] `State` con 11 stati, inclusi quelli che serviranno a M2 e M5
- [x] `Event` con 18 eventi
- [x] **`TRANSITIONS` come dizionario**: 34 transizioni, testabili senza audio
- [x] Transizione non prevista: registrata in `rejected`, stato invariato, mai eccezione
- [x] Timeout per **ogni** stato. `ATTESA_CONFERMA`=20 s, uguale al broker di M2
- [x] Macchina testabile senza audio: **20 test dedicati**
- [x] Test: 100 eventi casuali fuori sequenza, nessuna eccezione

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

## 2-bis. Note di esecuzione - 2026-09-21

### Varietà dei parlanti: risolta

Le due voci italiane di Piper sono a **parlante singolo**: un modello
addestrato solo su quelle riconoscerebbe due timbri e nient'altro.
`en_US-libritts_r-medium` ne ha **904**, ed è la fonte di varietà.

`SynthesisConfig` espone `speaker_id`, `length_scale` (velocità),
`noise_scale` e `noise_w_scale`: tutte le leve necessarie. Costo misurato
**72 ms a campione**, quindi 4000 positivi in ~5 minuti.

### Pronuncia: rischio aperto

Un parlante inglese dice "Metis" come /ˈmiːtɪs/, un italiano /ˈmɛtis/.
Addestrare sui 904 timbri inglesi con la pronuncia sbagliata darebbe un
modello sordo a come l'utente parla davvero.

Generato un set di confronto in `wakeword/pronuncia/` con 5 grafie
alternative - Metis, Mettis, Mehtis, Metiss, Met-iss - da confrontare con le
due voci italiane di riferimento. **In attesa del giudizio di ascolto.**

Piano B se nessuna grafia funziona: ribilanciare verso le voci italiane e
compensare la poca varietà con augmentation più aggressiva, più registrazioni
reali dal Blue Yeti.

### Anticipata la macchina a stati

I giorni 5-6 sono stati fatti prima, perché il training della wake word
dipende da una decisione dell'utente mentre la macchina a stati no.

Due proprietà verificate **da test, non per ispezione**:
- nessuno stato irraggiungibile e nessun vicolo cieco;
- il timeout di `ATTESA_CONFERMA` (20 s) coincide con quello che userà il
  broker in M2. Se divergessero, uno dei due si bloccherebbe.

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
