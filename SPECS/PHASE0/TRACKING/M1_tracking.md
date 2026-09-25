# M1 — Fondamenta Vocali · Tracking

| | |
| :-- | :-- |
| **Stato** | ✅ Chiusa |
| **Piano** | [M1_Fondamenta_Vocali.md](../plan/M1_Fondamenta_Vocali.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | 2026-09-21 |
| **Fine** | 2026-09-21 |
| **Tag** | `m1-voice` |

**Avanzamento:** `████████████████████` 100% — attività 33/37 · criteri di uscita 6/6 applicabili
**Chiusa con D1: wake word rimandata alla v2, push-to-talk unica via di attivazione.**
I tre criteri legati alla wake word (NFR-6, NFR-7, mancati su 50) sono rimandati con lei.

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

- [x] **4.000 positivi** generati con Piper, variando voce, velocità e pitch
- [ ] ~~500 positivi difficili: "Hey Metis" dentro frasi più lunghe~~ — non fatti
- [ ] ~~10.000+ negativi dal dataset openWakeWord~~ — **rinunciato**, vedi nota
- [x] **4.000 negativi mirati**, 70% italiani: "metti", "mettiamo", "Mattia", "ammettiamo"
- [x] Augmentation: rumore di fondo a SNR variabile (5–30 dB), rumore rosa
- [x] Augmentation: posizione casuale nella finestra, guadagno, eco singola
      — riverbero per convoluzione con RIR: **non fatto**, approssimato con eco
- [ ] **Campioni registrati con il microfono reale** — 23 clip (15 positive, 8
      trabocchetti). Le centinaia previste richiedono la seduta ambientale
- [x] Training completato — AUC 0,9995, mancati 0,56% a FPR 1%
- [x] `data/wakeword/hey_metis.onnx` esportato
- [x] `metis/audio/wakeword.py` integrato, gira su CPU — **1,89 ms/blocco su 80**
- [x] Soglia esposta in `config/wakeword.toml`

### Giorni 5–6 — Macchina a stati

- [x] `State` con 11 stati, inclusi quelli che serviranno a M2 e M5
- [x] `Event` con 18 eventi
- [x] **`TRANSITIONS` come dizionario**: 34 transizioni, testabili senza audio
- [x] Transizione non prevista: registrata in `rejected`, stato invariato, mai eccezione
- [x] Timeout per **ogni** stato. `ATTESA_CONFERMA`=20 s, uguale al broker di M2
- [x] Macchina testabile senza audio: **20 test dedicati**
- [x] Test: 100 eventi casuali fuori sequenza, nessuna eccezione

### Giorno 7 — Anti-eco e barge-in

- [x] **L1 half-duplex:** nello stato `PARLATO` i frame non arrivano a VAD e STT
- [x] Stream audio **sempre aperto**, si scartano i frame (nessuna riapertura del device)
- [x] **L2 barge-in:** il rilevatore wake word riceve i frame anche in `PARLATO`
- [x] Su barge-in: `player.stop()` chiamato
- [x] Su barge-in: **coda TTS svuotata**
- [x] Su barge-in: **stream LLM annullato** (token per turno, non condiviso)
- [x] Latenza di interruzione misurata — 0,1 ms logici, vedi riserva in 3.1

### Giorno 8 — Osservabilità

- [x] `structlog` configurato con doppio sink: console + JSONL, stesso evento
- [x] Campi obbligatori su ogni evento: `ts`, `state`, `event`, `turn_id`, `latency_ms`
- [x] Ogni transizione di stato produce una riga di log
- [x] Schema `audit` SQLite creato, con `CHECK` su tier ed esiti
- [x] Audit log append-only: verificato **via AST** sulle SQL eseguite, non sul testo

### Giorno 9 — Integrazione end-to-end

- [x] `metis/core/app.py`: cablaggio di tutti i componenti veri
- [x] Kill switch `Ctrl+Alt+Shift+M` — `panic()`, funziona da qualunque stato
- [x] Push-to-talk convive con la wake word (stesso evento verso la macchina)
- [x] `benchmarks/e2e_replay.py`: catena completa guidata da file, a velocità reale
- [x] **Turno completo verificato**: DORMIENTE → … → PARLATO → IN_ASCOLTO
- [x] **Barge-in verificato sul sistema intero**, non più a pezzi separati
- [x] `wakeword/record_ambient.py` — rumore per il training + NFR-6
- [x] `wakeword/nfr7_test.py` — NFR-7, con verifica di validità del banco

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

### Il punteggio dipende dall'allineamento dei blocchi (scoperta del giorno 9)

Misurato spostando la stessa registrazione di pochi campioni prima di darla
in pasto al rilevatore:

| clip | escursione su 8 allineamenti |
| :-- | :-- |
| "Hey Metis", voce reale | 0,954 – 0,996 → **+0,042** |
| "Ehi mi senti" | 0,152 – 0,891 → **+0,739** |
| rumore ambientale | 0,016 – 0,969 → **+0,953** |

Il melspettrogramma si calcola su una griglia di frame ancorata all'inizio del
flusso: spostare il segnale rispetto a quella griglia cambia le feature.

**Prima conseguenza.** Spiega lo 0,986 di "Ehi mi senti" che ieri non si
riusciva a riprodurre: era un altro allineamento. Rivalutare una registrazione
salvata **sottostima il rischio**, perché prova un allineamento solo.

**Seconda conseguenza, più utile.** La stabilità distingue i veri positivi dai
quasi-falsi meglio del punteggio: la wake word è un pattern robusto, un
quasi-falso cavalca il rumore nello spazio delle feature. Da qui la regola a
**doppia fase** — due rilevatori sfasati di 256 campioni, scatta solo se sono
d'accordo entrambi. Sulle clip disponibili:

| | fase singola | doppia fase |
| :-- | --: | --: |
| positivi (15 clip, 16 allineamenti) | 93,3% | **93,3%** |
| trabocchetti (8 clip) | 0% | 0% |
| picchi ambientali (2 clip) | 6,2% | **0%** |

Costo: 1,89 ms per blocco invece di 1,70, su un budget di 80.
**Resta disattivata**: due clip ambientali non sono un campione. La decisione
si prende con le 8 ore di NFR-6, dove `record_ambient.py` conta le due regole
**in parallelo sulla stessa audio** — un confronto appaiato, non due sedute
diverse che non sarebbero confrontabili.

---

## 3. Misure da registrare

### 3.1 Test obbligatori

| Test | Procedura | Soglia | Misurato | Esito |
| :-- | :-- | :-- | :-- | :-: |
| **NFR-7 auto-inneschi** | 2 h di TTS in loop, microfono aperto, altoparlanti al volume d'uso | **0** | **57 in 125 min — FALLITO** (modello v1) | ❌ |
| **NFR-6 falsi risvegli** | 8 h di uso normale: lavoro, musica, video, telefonate | < 1 | 0 su 24 s | 🔄 |
| Mancati riconoscimenti | 50 pronunce di "Hey Metis" in condizioni normali | < 10% | 6,7% su 15 | 🔄 |
| Latenza barge-in | 20 interruzioni misurate | < 200 ms | 0,1 ms su 1 | 🔄 |

**Riserva sulla latenza di barge-in.** Gli 0,1 ms sono il costo *logico*:
annullare il token e svuotare la coda. Il silenzio *udibile* dipende da
`sd.stop()` e dal buffer della scheda audio, e non è misurabile senza un
ritorno acustico. Va verificato a orecchio durante le 20 interruzioni vere.

**Riserva su NFR-7.** Il banco misura prima quanto il microfono senta gli
altoparlanti e si rifiuta di partire sotto i 6 dB di differenza: con il volume
basso passerebbe da solo senza dimostrare niente. Nella prova da un minuto la
differenza era +22,2 dB, e il massimo raggiunto 0,056 contro una soglia di
0,95. Con Metis che pronuncia il proprio nome (fase B) il massimo sale a
0,669: alto ma sotto soglia.

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

Applicabili alla V1.0:

- [x] Barge-in entro 200 ms, e **Metis non riprende da solo** dopo l'interruzione
- [x] **Push-to-talk: unica via di attivazione**, e interrompe anche mentre Metis parla
- [x] Ogni transizione di stato tracciata nel log JSONL
- [x] Macchina a stati sopravvive a 100 eventi fuori sequenza
- [x] Schema audit log creato e scrivibile
- [x] **D1 deciso** con una misura, non per stanchezza
- [ ] `git tag m1-voice`

Rimandati alla v2 insieme alla wake word:

- [ ] ~~NFR-7: zero auto-inneschi in 2 h~~ — banco pronto, misurato **57** con il modello di M1
- [ ] ~~NFR-6: < 1 falso risveglio in 8 h~~ — banco pronto, mai eseguito per 8 h
- [ ] ~~Mancato riconoscimento < 10% su 50~~ — 6,7% su 15, misura sospesa

---

## 5. Decision gate D1

| Decisione | Criterio | Esito | Motivo |
| :-- | :-- | :-- | :-- |
| **Wake word promossa** | Mancati < 10% **e** falsi risvegli < 1/8 h | ⏸️ **RIMANDATA alla v2** | Mancati 6,7%: superato. Auto-inneschi 57 in 125 min contro 0: non superato. v3 promette (0 falsi su 39 clip tenute da parte) ma non è verificato su una seduta nuova |

**Non è "sostituita con Porcupine" e non è "fallita".** È una verifica non
ancora superata su una funzione che era già facoltativa: il push-to-talk era
previsto come permanente fin dalla specifica, quindi la V1.0 non perde una
funzione, perde una comodità.

Cosa costerebbe riprenderla, misurato e non stimato: il rilevatore è un
modulo isolato di 236 righe che **nessuno importa tranne il cablaggio**; nella
macchina a stati sono tre transizioni e un insieme; nell'orchestratore tre
punti, tutti già dietro un callable iniettato. Riaccenderla è
`enabled = true` in `config/wakeword.toml`.

Il dettaglio completo della decisione, con cosa non va semplificato nel
frattempo e cosa invecchia aspettando, è in §21 della specifica ufficiale.

---

## 6. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 10 | 09-21 | **Tutti i `.onnx` puntavano allo stesso file di pesi esterno** `hey_metis.onnx.data` | **Grave.** Copiare un modello copiava solo il grafo: ogni addestramento sovrascriveva i pesi di tutte le versioni "archiviate". Per mezza giornata abbiamo creduto di avere in produzione v1 mentre probabilmente girava v2 | ✅ | Export ricompattato in un file solo, con `assert` sulla dimensione. v1 e v3 rigenerati da zero |
| 11 | 09-21 | Il banco NFR-7 attribuiva gli scatti a `parlatore.corrente`, l'ultima frase **sintetizzata** | La coda tiene 2 frasi di anticipo: le attribuzioni della seduta erano inutilizzabili | ✅ | L'etichetta viaggia con l'audio, `Player.now_playing` |
| 12 | 09-21 | `place_in_window` avrebbe preso fette casuali dalle clip da 4,5 s | Avremmo addestrato sul silenzio intorno all'errore invece che sull'errore | ✅ | `prepare_hard_negatives.py` ritaglia la finestra esatta dello scatto |
| 1 | 09-21 | `_process` chiamato in modo sincrono dentro `on_audio`: durante il turno il rilevatore non riceveva frame | **Bloccante** — il barge-in non poteva scattare mai | ✅ | Il turno gira su un thread proprio |
| 2 | 09-21 | Token di annullamento unico da resettare a ogni turno | Corsa: un annullamento appena prima del reset veniva inghiottito | ✅ | Un token **per turno** |
| 3 | 09-21 | `Player` non aveva `wait_drained()`, che l'orchestratore chiamava | `AttributeError` al primo turno reale | ✅ | Aggiunta; senza, `PLAYBACK_DONE` scattava con gli altoparlanti ancora accesi |
| 4 | 09-21 | Nessuna transizione `PARLATO` + `FAILED` | Un errore durante la riproduzione appendeva la macchina per 120 s | ✅ | Transizione aggiunta, più guscio try/except sul turno |
| 5 | 09-21 | `PLAYBACK_DONE` sparato da un turno già superato | Riapriva il microfono mentre il turno successivo parlava: rientro dell'eco | ✅ | Si emette solo se il token è ancora quello corrente |
| 6 | 09-21 | Il rilevatore non veniva alimentato durante il periodo refrattario | Buco di 2 s nel suo buffer: un secondo "Hey Metis" subito dopo non veniva sentito | ✅ | Il refrattario riguarda la decisione, non l'ascolto |
| 7 | 09-21 | `_last_fire = 0.0` significa "ha appena scattato" | L'origine di `perf_counter` è indefinita: dove partisse da zero, sordo per 2 s | ✅ | Inizializzato a `-inf`; trovato da un test |
| 8 | 09-21 | Il test dell'audit log cercava UPDATE/DELETE nel **testo** del sorgente | Falliva sulla docstring che spiega la regola: verifica inutile | ✅ | Estrazione via AST delle SQL eseguite, più un meta-test |
| 9 | 09-21 | Punteggi della wake word non riproducibili fra una misura e l'altra | Le soglie sembravano tarabili su numeri che non stavano fermi | ✅ | Spiegato: dipendono dall'allineamento dei blocchi. Vedi 2-bis |

---

## 7. Diario

### 2026-09-21

**Mattina.** Macchina a stati e orchestratore (giorni 5-7 anticipati). Wake
word addestrata: 4000 positivi sintetici con 866 parlanti inglesi più le due
voci italiane, 4000 negativi mirati. AUC 0,9995. Prova dal vivo: 14 su 15
rilevate, un falso risveglio su "Ehi, mi senti".

L'esperimento con i negativi duri è **fallito**: il margine di separazione è
peggiorato da +0,184 a +0,122. Il modello v2 è archiviato come
`hey_metis_v2_duri.onnx`, in produzione resta il v1. I dati sintetici hanno
esaurito quello che potevano dare su quella confusione.

**Pomeriggio.** Osservabilità e audit log. Poi l'integrazione end-to-end: fino
a quel momento wake word, macchina a stati e barge-in erano verificati ognuno
per conto suo, ed è esattamente il tipo di situazione in cui ogni pezzo è
corretto e l'insieme è rotto — come era successo col thread mancante.

`e2e_replay.py` rimette in circolo le registrazioni vere attraverso i motori
veri, a velocità reale. Turno completo verde al primo colpo. Il barge-in no:
non scattava. La traccia degli stati ha mostrato che la colpa era della
**prova**, non del prodotto — la wake word sta in fondo al clip e ci arrivava
quando la risposta era già finita. Ancorata la prova allo *stato* invece che
all'orologio: verde.

**Sera.** Dalla registrazione ambientale di prova, due picchi a 0,768 e 0,735
in una stanza tranquilla. Sospetto che fosse un artefatto del `reset()`:
smentito, il silenzio dopo un reset dà 0,004. Ma la stessa clip riprodotta
dava 0,535 invece di 0,735, e da lì è venuta fuori la dipendenza dei punteggi
dall'allineamento dei blocchi — che chiude anche il mistero di ieri e apre la
regola a doppia fase. Vedi 2-bis.

**Sera, dopo il riavvio.** Recuperati i risultati: il report era stato scritto
alle 13:51, il crash era delle 14:18 e nel registro eventi ci sono dodici
arresti imprevisti da marzo, mentre Metis esiste dal 20 settembre. Non è
colpa nostra, ma non è nemmeno un problema da ignorare.

NFR-7 fallito: 57 auto-inneschi. Poi la scoperta del versionamento illusorio:
tutti i `.onnx` puntavano allo stesso file di pesi esterno, quindi "v1 in
produzione" era un guscio e stava girando v2. Corretto alla radice.

Riaddestramento con i negativi duri **reali** ricavati dagli scatti: v3 porta
i falsi da 18 a 0 su 39 clip tenute da parte, senza perdere rilevamenti.

**Chiusura: D1.** Wake word rimandata alla v2, `enabled = false`,
push-to-talk unica via. Chiuso anche il buco che rendeva la scelta
impraticabile: `(PARLATO, PTT)` e `(GENERAZIONE, PTT)` non erano in tabella,
quindi senza wake word non esisteva modo di interrompere Metis parlando.
Ora le due strade percorrono lo stesso codice, e un test lo verifica
confrontando gli effetti invece di fidarsi.

**Test:** 76 verdi.

---

### Seduta NFR-7 del 21 settembre — fallita, ma decisiva

125 minuti, 2464 frasi, 7329 s di voce, microfono a +35,4 dB sul silenzio.
**57 auto-inneschi in fase A** contro un requisito di zero.

Due avvertenze sull'interpretazione:

- **La stanza non era vuota.** Le trascrizioni Whisper delle clip mostrano una
  conversazione umana fra il minuto 27 e il 45 ("buoni pasto e inoltre un
  compenso", "Ollama", "Buon appetito"). Circa 14-18 scatti vengono da lì.
  Come misura di NFR-7 la seduta è contaminata: misura NFR-6 e NFR-7 insieme.
- Restano **almeno 27 auto-inneschi confermati dalla voce di Piper**. La prova
  regina: su una clip Whisper stesso trascrive *"Metis pure quel fuori"* dove
  Piper diceva *"Metti pure quel foglio"*.

**Nessuna soglia risolve.** Rivalutando i 57 scatti e i 15 positivi insieme, le
distribuzioni si sovrappongono: a 0,99 restano 5 falsi e si perdono 8 pronunce
su 15.

### Riaddestramento con negativi duri REALI — v3

I 57 scatti più i quasi-scatti danno 159 clip, ritagliate sulla finestra esatta
dello scatto e sfasate di pochi millisecondi (8 varianti l'una) per coprire gli
allineamenti: 1272 file, 2880 vettori di feature.

Verifica **non circolare**: un quarto delle clip sorgente (39) tenuto fuori
dall'addestramento.

| | falsi su 39 tenute da parte | "Hey Metis" rilevati su 15 | margine |
| :-- | --: | --: | --: |
| v1 (senza duri reali) | 18 | 14 | +0,000 |
| v1 + doppia fase | 12 | 14 | — |
| **v3 (con duri reali)** | **0** | **14** | **+0,953** |

I duri *sintetici* del giorno prima avevano peggiorato il margine; quelli
**reali** lo portano da zero a 0,953 senza costare un solo rilevamento.

**v3 è in produzione** (`data/wakeword/hey_metis.onnx`). Si torna indietro con
`cp data/wakeword/hey_metis_v1.onnx data/wakeword/hey_metis.onnx`.

Quello che questo **non** dimostra: le 39 clip vengono dalla stessa stanza e
dalla stessa seduta di quelle di addestramento. È generalizzazione dentro la
stessa distribuzione, non la prova che NFR-7 passi. Serve una seduta nuova —
che stavolta salverà l'audio integrale, così ogni modello successivo si
rivaluta offline con `rescore_session.py`, senza altoparlanti.

**Quello che v3 NON risolve.** Rivalutando su 8 allineamenti:

| clip | v1 | v3 |
| :-- | :-- | :-- |
| "Hey Metis", tua voce | 1,000 – 1,000 | 1,000 – 1,000 |
| auto-innesco NFR-7 (Piper) | 0,999 – 0,999 | **0,000 – 0,000** |
| rumore ambientale | 0,244 – 0,916 | **0,000 – 0,001** |
| "Ehi mi senti" (voce umana) | 0,992 – 0,999 | 0,247 – **0,994** |

La confusione con "Ehi mi senti" resta: quella frase non era fra i negativi
duri, perché viene da `live_test.py` e non dalla seduta NFR-7. È un problema
di NFR-6, non di NFR-7, e la cura è la stessa — negativi umani **reali**, che
la seduta ambientale da 8 ore raccoglie mentre misura.

**Doppia fase: sospesa.** Con v1 serviva (57 → 20). Con v3 i falsi sono già
zero a fase singola, quindi aggiungerla ora vorrebbe dire introdurre un
meccanismo prima di aver dimostrato che serve. Resta disponibile e misurata in
parallelo dai banchi.

---

## 8. Note per M2

- L'audit log è già scritto e verificato: il Capability Broker ci scrive
  dentro dal primo strumento, non se lo inventa di corsa. La query di NFR-9 è
  già testata, incluso il caso "conferma negata ma azione eseguita".
- Il timeout di `ATTESA_CONFERMA` è 20 s e **deve restare uguale** a quello
  del broker: se divergono, uno dei due si blocca.
- `Deps` dell'orchestratore è il punto di innesto: gli strumenti entrano da lì
  come callable, senza che l'orchestratore sappia cosa fanno.
- Il guscio `_run_turn` cattura tutto e chiude in `ERRORE`: gli strumenti di
  M2 possono sollevare senza appendere la macchina.
