# M3 — Interfaccia Grafica · Tracking

| | |
| :-- | :-- |
| **Stato** | ✅ Chiusa |
| **Piano** | [M3_Interfaccia_Grafica.md](../plan/M3_Interfaccia_Grafica.md) |
| **Durata prevista** | 10 giorni |
| **Inizio** | 2026-09-21 |
| **Fine** | 2026-09-21 |
| **Tag** | `m3-gui` |

**Avanzamento:** `███████████████████░` 94% — attività 30/32 · criteri di uscita 8/10
Restano `git tag m3-gui` e due verifiche che non si automatizzano.

> **Obiettivo:** dare a Metis una faccia che non si blocca.
> **Rischio dominante:** il freezing dell'UI. Si comincia dalla concorrenza, non dai widget.

---

## 1. Prerequisiti

- [x] M2 chiuso, broker testato
- [x] Macchina a stati con segnali osservabili
- [x] Audit log popolato
- [x] `TurnMetrics` prodotte a ogni turno

---

## 2. Attività

### Giorni 1–3 — Topologia dei thread

- [x] `metis/gui/app.py` con `QApplication`
- [x] **`Nucleo`** — `QObject` + `moveToThread`. Accorpa audio, macchina a
      stati e TTS: vedi lo scostamento in §4-bis
- [ ] ~~`AudioWorker` separato~~ — accorpato nel `Nucleo`
- [ ] ~~`TtsWorker` separato~~ — accorpato nel `Nucleo`
- [x] `Telemetria` — `QObject` + `moveToThread`
- [x] Tutti i segnali collegati a **slot veri** sul thread principale
- [x] Conferma T3: `QWaitCondition` **con timeout**, mai attesa indefinita
- [x] Timeout della `QWaitCondition` == timeout del broker, stessa costante
- [x] ~~Throttling `token`~~ — non serve: l'orchestratore emette frasi, non token
- [x] Throttling del livello audio → 31 Hz in ingresso, ridisegno a 15 Hz

### Giorni 4–5 — Modalità Minimal

- [x] Finestra frameless, always-on-top, `Qt.Tool`, sfondo traslucido
- [x] Indicatore di stato con la mappa colori completa — **11 stati**, in
      `metis/core/palette.py`, la stessa tabella dei colori del terminale
- [x] VU meter del livello audio in ingresso
- [x] Ultima frase trascritta, una riga troncata
- [x] Pulsante push-to-talk
- [x] Indicatore kill switch, visibile solo quando attivo
- [x] Trascinamento implementato (`mousePressEvent` / `mouseMoveEvent`)
- [x] Posizione persistita in `config/settings.toml`
- [ ] **Verifica: indicatore leggibile di sbieco e a due metri** — si fa
      con gli occhi, non con un test

### Giorni 6–8 — Modalità Fullscreen

- [x] Layout a tre colonne, con divisori regolabili
- [x] Widget conversazione con **append incrementale**, non ricostruzione
- [x] Auto-scroll disattivato se l'utente scrolla verso l'alto
- [x] Meccanismo dei parziali in grigio pronto e testato — ma **nessuna
      sorgente di parziali esiste ancora**: Vosk arriva in M5
- [x] Dashboard: CPU e RAM a 2 Hz
- [x] Dashboard: VRAM e temperatura GPU a **1 Hz**
- [x] Dashboard: TTFT, tok/s, latenza p50/p95 su finestra di 50 turni
- [x] Soglia VRAM 7,5 GB → indicatore rosso
- [x] Dialogo conferma T3 con strumento, argomenti **completi** e tier
- [x] Countdown del timeout visibile
- [x] **Nessun pulsante di default; focus su "Nega"**
- [x] Visualizzatore audit log filtrabile per tier ed esito
- [x] Contenitore dei comandi rapidi (in M4 diventa un editor)

### Giorni 9–10 — Profiling

- [x] `QTimer` a 16 ms per rilevare i blocchi dell'event loop
- [x] Sessioni misurate: 3778 e 6773 campioni in esercizio
- [x] Frame rate misurato durante generazione + telemetria
- [x] Confronto telemetria vs `nvidia-smi`
- [x] Passaggio Minimal ↔ Fullscreen testato
- [x] ~~Verifica per ispezione~~: **quattro test automatici**, fra cui uno
      che emette da un thread vero e controlla dove atterra lo slot

---

## 3. Misure da registrare

| Test | Soglia | Misurato | Esito |
| :-- | :-- | :-- | :-: |
| Blocco massimo event loop, **in esercizio** | < 100 ms | **3,7 ms** su 3778 campioni | ✅ |
| Ritardo p95 in esercizio | — | **0,78 ms** | ✅ |
| Frame rate sotto inferenza | ≥ 30 fps | **62 fps** | ✅ |
| Scarto telemetria vs `nvidia-smi`, VRAM | < 5% | **3,6%** | ✅ |
| Scarto telemetria vs `nvidia-smi`, GPU % e temperatura | < 5% | **0,0%** | ✅ |
| Blocco massimo **all'avvio** | — | 2098 ms, una volta sola, a 3,8 s | 🟡 |

Lo scarto del 3,6% sulla VRAM è un offset sistematico di `nvidia-smi`, che
esclude una parte della memoria riservata: sono ~203 MB fissi, non un errore
che cresce col carico.

### 3.1 Blocchi rilevati

| # | Durata | Operazione responsabile | Dove | Esito |
| :-- | ---: | :-- | :-- | :-: |
| 1 | 2098 ms | Caricamento di Whisper, Qwen e Piper: sono import e inizializzazioni Python, che tengono il GIL anche girando su un altro thread | avvio, a 3,8 s | 🟡 accettato |

**Perché accettato e non risolto.** NFR-8 parla di blocchi "durante
l'inferenza". A 3,8 secondi dall'avvio la finestra mostra le righe di
caricamento e non c'è niente con cui interagire. Spostare gli import
altrove sposterebbe il blocco, non lo toglierebbe: il GIL è di Python, non
di Qt. Resta riportato in ogni riassunto, separato dalla fase d'uso, invece
di essere annegato in una media di mezz'ora.

---

## 4. Criteri di uscita

- [x] **NFR-8:** nessun freeze > 100 ms durante l'inferenza — **0 su 3778 campioni**
- [x] ≥ 30 fps durante generazione con telemetria attiva — **62 fps**
- [x] Nessun accesso ai widget da thread secondari — **test automatici**
- [x] Passaggio Minimal ↔ Fullscreen senza perdita di stato
- [x] Metriche coincidono con `nvidia-smi` entro il 5% — **3,6% al massimo**
- [x] Il dialogo T3 **non** può essere approvato con Invio o Esc
- [x] Timeout conferma GUI == timeout broker — stessa costante, verificato
- [ ] Parziali e finale distinguibili — meccanismo pronto e testato, ma la
      **sorgente dei parziali non esiste fino a M5**
- [ ] Indicatore di stato leggibile a due metri — da verificare a occhio
- [ ] `git tag m3-gui`

---

## 4-bis. Scostamenti dal piano

### Un solo worker per il nucleo, non tre

Il piano prevedeva `AudioWorker`, `OrchestratorWorker` e `TtsWorker`
separati. Sono diventati un `Nucleo` solo, perché da M1 audio, macchina a
stati e riproduzione **sono già una pipeline unica**: il ciclo audio chiama
l'orchestratore, che chiama il player. Spezzarli in tre thread avrebbe
significato tre code di messaggi fra pezzi che si parlano a ogni blocco da
32 ms, per ottenere la stessa cosa con più punti in cui perdere un evento.

Il vincolo vero del piano — nessun lavoro pesante sul thread della GUI — è
rispettato: il nucleo sta su un thread suo e la telemetria su un altro.

### Niente throttling dei token

Il piano prevedeva un buffer a 20 Hz sullo streaming dei token. Non serve:
l'orchestratore non emette token, emette **frasi già pronte per il TTS** —
è la segmentazione di M0, quella che fa parlare Metis prima che la risposta
sia finita. Arrivano due o tre volte per turno, non sessanta al secondo.

### La lettura dell'audit log avviene dal thread della GUI

È l'unica eccezione alla regola "i thread non si toccano", ed è ammessa
perché `AuditLog` è thread-safe per progetto fin da M1: lock interno e
connessione con `check_same_thread=False`. Spedire una copia via segnale
non aggiungerebbe sicurezza e aggiungerebbe una seconda verità.

---

## 5. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | | | | | |

---

## 6. Diario

### 2026-09-21

Dieci giorni di piano in una sessione, dopo M2.

**Prima il refactor.** Da qui in poi esistono due modi di avviare Metis, e
due cablaggi separati sarebbero divergiti in silenzio — nel punto in cui non
ci si può permettere di divergere, la sicurezza. Il sistema si costruisce
ora in `metis/core/avvio.py`, una volta sola; console e GUI scelgono solo
come riportare l'avanzamento e come chiedere conferma.

Nello stesso spirito, i colori di stato sono finiti in
`metis/core/palette.py`. Il commento in `logging.py` diceva da M1 "lo stesso
codice della GUI di M3": finché erano due tabelle era un'intenzione.

**Il ponte della conferma.** Scritto per primo perché è il punto in cui un
difetto blocca Metis invece di dare fastidio. Il caso che conta è il
**risveglio perduto**: l'utente risponde fra l'emit e l'inizio dell'attesa,
il `wakeAll` arriva quando nessuno aspetta ancora, e il nucleo resta fermo
venti secondi su un'azione già approvata. Si forza con una connessione
diretta, ed è verde.

**Il difetto trovato da un test nato per altro.** Un test sul passaggio fra
le viste ha mostrato uno stato che non arrivava. Causa:
`signal.connect(lambda: ...)` non ha un oggetto ricevente, quindi Qt esegue
la lambda **nel thread che emette** — cioè tutte le lambda collegate ai
segnali del nucleo avrebbero toccato i widget dal thread sbagliato. La
regola che tutto M3 esiste per rispettare, violata dalla scorciatoia più
comoda che ci sia, e invisibile finché il carico è leggero.

`Applicazione` è diventata un `QObject` e ogni segnale dei worker ha il suo
slot vero. Poi due test nuovi: uno emette da un `QThread` vero e verifica
dove atterra, l'altro scandaglia il sorgente con l'AST e fallisce se
ricompare una lambda su un segnale di worker.

**Un terzo caso dello stesso errore.** Il test che verificava "solo app.py
monta i thread" cercava la parola `moveToThread` nel **testo** e inciampava
nella docstring che spiega il pattern — identico all'errore del test
dell'audit log a M1. Riscritto con l'AST: contano le chiamate eseguite, non
le parole scritte. È la terza volta che succede in questo progetto; la
lezione è che qualunque verifica basata su `in sorgente` è sospetta.

**NFR-8.** Alla prima misura diceva FALLITO per **un** blocco da 2,1 s, con
p95 a 0,77 ms e 62 fps. Reinterpretare il criterio per farlo passare sarebbe
stato disonesto; misurare le due fasi separate è la cosa giusta, perché
"durante l'inferenza" e "mentre carica tre modelli" sono due domande
diverse. In esercizio: **max 3,7 ms, zero blocchi, 62 fps**.

**Test:** 309 verdi.

---

## 7. Note per M4

**Quello che M3 consegna:**

- **Visibilità.** Il debug dell'automazione si fa guardando l'audit log in
  finestra, filtrabile per tier ed esito, non aprendo SQLite.
- **Il flusso di conferma completo**, dal broker al pulsante. Ogni T3 di M4
  lo attraversa senza che ci sia altro da scrivere.
- **La misura di reattività come test di regressione.** Se M4 mette una
  chiamata bloccante sul thread della GUI — e con l'automazione la
  tentazione ci sarà — il riassunto di NFR-8 lo dice subito e dice a che
  secondo.

**Tre trappole da non ripetere:**

1. **Mai una lambda su un segnale che arriva da un worker.** Gira sul thread
   di chi emette. C'è un test che lo impedisce, ma vale sapere perché.
2. **Gli slot in coda verso il nucleo non vengono eseguiti** mentre il ciclo
   audio gira: quel thread non processa eventi. I comandi verso il nucleo si
   chiamano direttamente, ed è sicuro perché l'orchestratore ha i lock dal
   primo giorno.
3. **Il corpo di uno strumento T2 non deve ricontrollare la finestra.** Lo fa
   già il broker con le guardie immediate, in un punto solo.

-
