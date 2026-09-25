# M7 — Consolidamento V1.0 · Tracking

| | |
| :-- | :-- |
| **Stato** | 🔄 Codice e strumenti pronti — le prove lunghe e quelle con l'utente sono aperte |
| **Piano** | [M7_Consolidamento_V1.md](../plan/M7_Consolidamento_V1.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | dopo il commit di M6 (2026-09-23) |
| **Fine** | — |
| **Tag** | `v1.0` — non ancora: vedi §5 |

**Avanzamento:** `███████████████░░░░░` 77% — attività 30/39 · criteri di uscita 5/13

> **Obiettivo:** far vivere Metis nel PC senza sorveglianza.
> **Regola:** in M7 non si aggiungono funzionalità. Ogni idea nuova va nel backlog V1.1.

Il codice di M7 è tutto scritto e verificato: matrice degli errori, tray,
autostart, soak, verifica NFR, bundle provato su cartella pulita, documentazione. Quello che manca non
si può fare in una sessione di sviluppo: **72 ore di soak**, **100
interazioni reali** con la voce dell'utente, **50 frasi registrate**, un
**riavvio vero** del PC con l'autostart installato, e l'installazione **da
zero** seguendo `docs/INSTALL.md`.

Le prove sul sistema vero (GUI sotto `pythonw`, due soak da 9 minuti, bundle
su cartella pulita) hanno trovato sette difetti, uno grave: §7 #5, presente da M4.

---

## 1. Prerequisiti

- [ ] M6 chiuso — ⏸️ **in pausa per scelta**: Home Assistant, account SMTP e riavvio vero rimandati; si procede con M7
- [x] Tutte le funzionalità della specifica implementate
- [ ] Audit log popolato da settimane di uso reale — no: l'uso reale comincia adesso

---

## 2. Attività

### Giorni 1–2 — Gestione degli errori

- [x] `metis/core/errors.py` con la matrice completa — categorie, strategie, frasi; classificazione sul tipo **vero** (`httpx.ConnectError` in streaming, non `ConnectionError`)
- [x] Ollama non raggiungibile → **1** retry, poi dichiara; il resto lo fa `SALUTE` in sottofondo — §2-bis
- [x] Ollama in OOM → Whisper sulla CPU, un nuovo tentativo
- [x] Microfono scollegato → rileva (3 s senza blocchi), riprova ogni 2 s, lo dice una volta sola e lo ridice quando torna — senza indicatore rosso dedicato, §2-bis
- [x] Rete assente → percorso web degradato con la frase della matrice, il resto funziona
- [x] Home Assistant offline → riconnessione con backoff (da M6, `test_si_riconnette_da_solo`)
- [x] SMTP fallito → **rischedula fra 10 min**, fino a 6 volte; non perde l'email
- [x] Strumento in eccezione → `Result.error`, frase in persona, mai il testo dell'eccezione
- [x] TTS fallito → Kokoro caricato in sottofondo, poi silenzio con il testo in GUI
- [x] STT vuoto → torna a `IN_ASCOLTO` **in silenzio** (da M1)
- [x] VRAM > 7,5 GB → Whisper sulla CPU, notifica; indicatore rosso = barra VRAM del cruscotto
- [x] **Nessun traceback raggiunge l'utente** — tre punti trovati e chiusi, §7 #1

### Giorni 3–4 — Soak test 72 ore

- [x] `tests/soak/run_soak.py` scritto — sistema vero, solo il microfono sostituito
- [x] Interazione sintetica ogni 10 min, mix 40/30/20/10 **esatto** (mazzo mescolato, non estrazioni)
- [x] Campionamento a 60 s: RSS, VRAM (picco a 1 Hz), handle, thread, code, salute
- [ ] **Soak avviato** — ⬜ tocca all'utente: tre giorni di PC acceso. Fatte due prove da 9 minuti
- [ ] Iniezione ora 6: Ollama fermo 5 min — guidata, automatica con `--ollama-auto`
- [ ] Iniezione ora 18: rete assente 30 min — guidata
- [ ] Iniezione ora 30: microfono scollegato 10 min — **automatica**, già riuscita nelle prove brevi
- [ ] Iniezione ora 42: Home Assistant fermo — guidata (HA non ancora disponibile)
- [ ] Iniezione ora 54: VRAM saturata da altro processo — guidata
- [ ] Grafico finale prodotto e analizzato — l'harness lo produce (`grafico.svg`, `rapporto.md`)

### Giorni 5–6 — Verifica NFR

- [ ] 100 interazioni **reali** (non sintetiche) per NFR-1 e NFR-2
- [ ] 50 frasi registrate con la tua voce e trascritte a mano per NFR-5
- [x] Query SQL per NFR-9 — `tests/nfr/verifica_nfr.py`, la query del piano scritta in chiaro
- [ ] Tabella §4 compilata con tutte le evidenze — lo script la compila; mancano i dati

### Giorni 7–8 — Packaging e residenza

- [x] `metis.spec` in modalità **`onedir`**
- [x] Modelli esterni al bundle, in `data/` e nelle cache
- [x] Hidden imports risolti — e due famiglie di DLL che PyInstaller non vede, §3.3
- [x] **Bundle provato su cartella pulita**, senza venv nel PATH — §3.3
- [x] `QSystemTrayIcon` con menu completo — stato, due viste, kill switch, pausa ascolto, esci
- [x] Icona che riflette lo stato con i colori di M3 — disegnata dalla stessa palette
- [x] Uscita pulita: thread fermati, scheduler chiuso, device audio rilasciato — §7 #4
- [x] `scripts/install_autostart.ps1` con Utilità di pianificazione — provato in `-Anteprima`, **non installato**
- [x] Trigger `AtLogOn` con ritardo 60 s, `RestartCount 3`
- [x] **`RunLevel Limited`** — non amministratore; lo script rifiuta la console elevata
- [x] Avvio robusto: sequenza in 6 passi di §4.4
- [x] Saluto vocale una tantum all'avvio riuscito
- [ ] `docs/INSTALL.md` completo e provato da zero — scritto; la prova da zero è dell'utente

---

## 2-bis. Scostamenti dal piano

### Un solo retry verso Ollama, non tre

Misurato: su Windows una connessione rifiutata costa **2,26 s** (4,3 s con
`localhost`), perché lo stack TCP ripete il SYN. Tre tentativi con backoff
facevano **8,16 s** di silenzio prima della frase. Ne resta uno (0,5 s di
attesa), e il resto lo fa `SALUTE`: quando Ollama è segnato giù le chiamate
successive falliscono **subito**, e una sonda ogni 5 s lo riporta su da sola.
Il router, con Ollama giù, passa direttamente alla conversazione, che dice la
frase in persona.

### Il microfono assente non è "GUI in rosso"

Il piano chiede la GUI in rosso. Il pallino dell'overlay è lo **stato della
macchina** e colorarlo per il microfono lo farebbe mentire (Metis è
DORMIENTE, non in errore). Il microfono assente si dice con una riga in
conversazione e una notifica, una volta sola, e di nuovo quando torna.

### La pausa dell'ascolto non si toglie con il PTT

"Pausa ascolto" scarta i frame **prima** di wake word e VAD. Il turno in corso
finisce; poi Metis torna a dormire invece che ad ascoltare. Il push-to-talk
può ancora **zittire** Metis, ma non riapre il microfono: una pausa che si
toglie con un tasto premuto per sbaglio non è una pausa.

### Chiudere la finestra non è uscire

Con la tray presente la X nasconde (con un avviso la prima volta); si esce
da *Esci*, l'unico percorso che passa da `Applicazione.chiudi`. Senza area di
notifica resta il comportamento di prima.

### Il soak non usa un device loopback

Il piano diceva "audio pre-registrato riprodotto su loopback". Qui non c'è un
loopback: la `SorgenteSintetica` sostituisce la cattura e consegna blocchi da
32 ms **a velocità reale**, con le frasi sintetizzate da Piper. Prova la
stessa catena (VAD, endpointing, STT) senza un driver in più. Il resto del
sistema è quello di esercizio.

### Il soak scrive in un log suo

`data/soak/soak_<data>/metis.jsonl`, non `data/logs/metis.jsonl`. NFR-1 si
misura sulle interazioni **reali**: mescolarle con 430 sintetiche lo
falserebbe, ed è proprio il caso contro cui il piano mette in guardia.

---

## 3. Soak test — risultati

### 3.1 Prove brevi (9 minuti, 9 interazioni, iniezioni compresse)

Non sostituiscono le 72 ore: servono a sapere che l'harness funziona e che
il sistema regge l'uso alternato di conversazione, comandi e ricerche. Hanno
trovato §7 #5, #6 e #7.

| | Prima di §7 #5 | Dopo |
| :-- | ---: | ---: |
| Interazioni riuscite | 9/9 | 9/9 |
| Latenza conversazione | 5,8–15,1 s | **1,9–2,3 s** |
| Latenza comandi T1 | 5,8–7,3 s | **1,3–2,4 s** |
| TTFT conversazione | 4,0–4,9 s | **0,2–0,6 s** |
| Throughput nel log | 0,0 (§7 #7) | 51–59 tok/s |
| Timeout di ELABORAZIONE | 1 | 0 |
| Microfono scollegato 12 s | rilevato, ripreso | rilevato, ripreso |
| Picco VRAM | 6,45 GB | 6,51 GB |

### 3.2 Le 72 ore

| Metrica | Inizio | 24 h | 48 h | 72 h | Crescita | Esito |
| :-- | ---: | ---: | ---: | ---: | ---: | :-: |
| RSS | — | — | — | — | — | ⬜ |
| VRAM | — | — | — | — | — | ⬜ |
| Handle | — | — | — | — | — | ⬜ |
| Thread | — | — | — | — | — | ⬜ |
| Latenza p95 | — | — | — | — | — | ⬜ |
| Dimensione code | — | — | — | — | — | ⬜ |

> Valutare la **pendenza**, non il valore finale. L'harness calcola la retta
> dei minimi quadrati **dopo la prima ora** e sotto le 3 ore non dà verdetto.

**Crash nelle 72 h:** — **Iniezioni gestite correttamente:** __/5

```powershell
.venv\Scripts\python.exe tests\soak\run_soak.py --ore 72 --ollama-auto
```

### 3.3 Il bundle

`metis.spec`, onedir, `console=False`. **3,1 GB**, di cui ~2 GB sono cuBLAS e
cuDNN 9: sul sistema c'è solo cuDNN 8, e senza di loro Whisper non parte.
Il resto: torch CPU 315 MB (lo usa il VAD), PySide6, CTranslate2, spaCy e
transformers portati da Kokoro. Tolto `playwright` (103 MB, trascinato da un
hook e non importato da nessuno).

**Prova su cartella pulita:** `dist\Metis` copiato fuori dal repository con
solo `config\` e `data\piper\` accanto, lanciato con un PATH ridotto a
`System32` — niente venv, niente Python, niente CUDA Toolkit.

| Tentativo | Esito |
| :-- | :-- |
| 1 | La GUI parte, dice in persona che qualcosa non va, esce con 0. Nel log: `cublas64_12.dll is not found` — §7 #9 |
| 2 | **Pronto, saluto, uscita con codice 0 in 40 s.** Nessuna riga in `metis.stderr.log` |

La prova copre avvio, caricamento e riscaldamento dei tre modelli (Whisper
trascrive davvero al riscaldamento, quindi cuBLAS è caricato), scheduler,
audit e uscita. Non copre un turno parlato: senza microfono nella prova.

---

## 4. Verifica formale dei 10 NFR

```powershell
.venv\Scripts\python.exe tests\nfr\verifica_nfr.py
```

Lo script **non spunta niente per convinzione**: sotto le 100 interazioni o
sotto le 72 ore di soak scrive "dati insufficienti", non verde.

| NFR | Metrica | Target | Misurato | Evidenza | Esito |
| :-- | :-- | :-- | :-- | :-- | :-: |
| 1 | Latenza e2e p50 / p95 | < 1,2 s / < 1,8 s | — / — | 100 interazioni reali | ⬜ **a rischio**, §4.1 |
| 2 | TTFT | < 400 ms | 0,2–0,6 s nel soak breve | stesse 100 interazioni | ⬜ |
| 3 | Throughput | ≥ 45 tok/s | 51–59 tok/s nel soak breve | metriche Ollama | ⬜ |
| 4 | Picco VRAM | ≤ 7,2 GB | 6,51 GB in 9 min | soak, 1 Hz × 72 h | ⬜ |
| 5 | WER italiano | < 12% | — | 50 frasi, riferimento manuale | ⬜ |
| 6 | Falsi risvegli | < 1 / 8 h | ⏸️ wake word spenta (D1) | — | ⏸️ |
| 7 | Auto-inneschi da eco | **0** | ⏸️ wake word spenta (D1) | — | ⏸️ |
| 8 | Reattività GUI | ≥ 30 fps, no freeze > 100 ms | — | log con `fase` (da M7) | ⬜ |
| 9 | Azioni T3 non confermate | **0** | **0** | query sull'audit | ✅ |
| 10 | Stabilità | RSS < +10% in 72 h | — | soak | ⬜ |

### 4.1 NFR-1 è a rischio, e il motivo si conosce

In M0 NFR-1 era verde (1119 / 1625 ms) su una catena **senza router**. Da M4
ogni turno passa prima dal router — una chiamata al modello in più, 0,3–0,6 s
misurati — e da M5 la persona e gli slot allungano il prompt. Nel soak breve,
corretto §7 #5, la conversazione sta fra **1,9 e 2,3 s** dalla fine del
parlato al primo audio. Sono frasi di Piper e non la voce vera, quindi il
numero non è l'evidenza; ma dice dove guardare. Leve, in ordine di costo:

| Leva | Guadagno atteso | Costo |
| :-- | :-- | :-- |
| Router e conversazione **in parallelo**, si scarta la conversazione se il router sceglie uno strumento | tutto il router, 0,3–0,6 s | una generazione sprecata per i comandi |
| Prefisso del prompt stabile (persona prima, slot dopo) per la cache dei prompt di Ollama | parte del TTFT | riordino del prompt, da riverificare con i banchi M4–M6 |
| Modello 4B come router (leva del piano) | ~metà del router | qualità delle decisioni, da rimisurare |

Nessuna è applicata: in M7 non si aggiungono funzionalità, e la decisione va
presa sui numeri delle 100 interazioni reali.

---

## 5. Criteri di uscita

- [ ] **Tutti e 10 gli NFR verdi**, con evidenza misurata allegata
- [ ] Soak 72 h completato: nessun crash, crescita RSS < 10%
- [ ] Tutte e 5 le iniezioni di fallimento gestite correttamente
- [x] Nessuna modalità di errore produce un traceback all'utente
- [x] Bundle eseguibile su cartella pulita, senza venv nel PATH — §3.3
- [ ] Avvio automatico funzionante **da PC spento**, verificato con riavvio reale
- [x] Avvio robusto anche se Ollama parte dopo Metis — attesa fino a 120 s e sonda di `SALUTE`; provato con i finti, non ancora con Ollama avviato davvero dopo
- [ ] Metis **non** gira come amministratore — garantito dallo script, da verificare sull'attività registrata
- [x] Tray icon con stato, kill switch e uscita pulita
- [x] Uscita pulita: nessun thread orfano, device audio rilasciato
- [ ] `docs/INSTALL.md` provato su installazione da zero
- [ ] **Specifica aggiornata: ogni stima sostituita dal valore misurato**
- [ ] `git tag v1.0`

### Per chiudere i criteri aperti

| Criterio | Chi | Comando / azione |
| :-- | :-- | :-- |
| Soak e iniezioni | utente | `tests\soak\run_soak.py --ore 72 --ollama-auto`, seguendo gli avvisi delle iniezioni guidate |
| NFR-1, 2, 3 | utente | usare Metis: 100 turni veri, poi `tests\nfr\verifica_nfr.py` |
| NFR-5 | utente | 50 frasi con `benchmarks\stt_check.py` e trascrizione a mano |
| Autostart e non-admin | utente | `scripts\install_autostart.ps1`, poi riavvio del PC |
| INSTALL.md da zero | utente | clonare in una cartella nuova e seguire la guida |

---

## 6. Chiusura del progetto

- [ ] `git tag v1.0`
- [ ] Specifica ufficiale aggiornata con i numeri veri
- [x] Tabella di stato in [DASHBOARD.md](DASHBOARD.md) aggiornata
- [ ] Backlog V1.1 consolidato
- [ ] Report di verifica NFR archiviato accanto alla specifica

---

## 7. Registro problemi

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 1 | **Tre punti in cui il testo di un'eccezione arrivava all'utente** | "errore: ConnectionError: …" in GUI; "Non ci sono riuscito: ConnectionError" a voce; Ollama giù a metà turno → ERRORE e Metis **taceva** | Matrice degli errori: frase in persona ovunque, testo tecnico solo nel log. Il turno fallito ora dice la frase e torna ad ascoltare |
| 2 | **Sotto `pythonw` Metis moriva al primo log** | L'autostart usa `pythonw`, che parte con `stdout`/`stderr` a None: `TypeError` dentro structlog, a ogni accesso, senza traccia | `garantisci_flussi`: stdout nel nulla, stderr su `data/logs/metis.stderr.log` |
| 3 | **Corretto il #2, moriva lo stesso (0xC0000409)** | Le librerie native scrivono sui descrittori 1 e 2, che sotto `pythonw` non esistono: il runtime C termina il processo | `dup2` di un file vero sui descrittori. Provato lanciando la GUI vera sotto `pythonw` staccato: pronta, saluto, uscita con codice 0 |
| 4 | Due thread di sorveglianza non si fermavano | VRAM: `while True: time.sleep(10)`. Salute: `ferma()` non aspettava, e un `NameError` in `ferma` restava nascosto da `Sistema.chiudi`, che inghiotte le eccezioni | `Event.wait` e `join` con limite; trovato dal test che conta i thread `metis-*` dopo `chiudi` |
| 5 | **Router e conversazione chiedevano a Ollama contesti diversi** | 4096 (default) contro 8192: Ollama **ricaricava il modello due volte per turno**, 3,6 s ciascuna. Latenze di 5,8–15 s, un comando di telemetria andato in timeout di ELABORAZIONE. Presente **da M4**: ogni banco misurava un percorso solo | `NUM_CTX` unico in `client.py`, usato dal router; un test cattura le opzioni spedite davvero. Latenze a 1,3–2,4 s |
| 6 | `web_fetch` in errore su pagine vere (ilmeteo.it) | Elementi invisibili annidati: distrutto il genitore, il figlio restava nella lista di `find_all` e `.get` sollevava. Presente da M5 | Si saltano i nodi già distrutti; test con l'annidamento |
| 7 | `tok_per_s` mai copiato nelle metriche del turno | Il cruscotto mostrava 0 tok/s da M1; NFR-3 non si leggeva dal log | Copiato insieme ai token |
| 8 | Tre copie della frase "fonti non raggiungibili", nessuna era quella della matrice | `Categoria.RETE` definita e mai usata | Una frase sola, dalla matrice |
| 9 | **Il bundle non trovava cuBLAS** | `nvidia` è un namespace package: nel bundle `import nvidia` fallisce, le cartelle delle DLL non si registravano, e le DLL non erano nemmeno raccolte. Whisper non partiva | Lo spec copia `nvidia/*/bin` in `_internal`, `cuda_libs` le cerca lì quando è congelato |
| 10 | La DLL di `uiautomation` non era nel bundle | Caricata con ctypes da `uiautomation/bin`: PyInstaller la segnala e non la prende. L'automazione delle finestre di M4 non sarebbe partita | Aggiunta esplicitamente nello spec |
| 11 | **Un link lungo allargava la control room oltre lo schermo** | Trovato dall'utente cercando annunci di lavoro: un link di tracciamento di Bing (~1500 caratteri, senza spazi) fra fonti e slot. Una `QLabel` va a capo solo sugli spazi: finestra da 1400 a 11 767 px, conversazione da 665 a 102 px | `metis/gui/testo.py`: URL mostrati come dominio + inizio (intero nel tooltip), parole lunghe spezzabili, etichette che non impongono la larghezza. Test a finestra visibile: senza `show()` il layout non si ricalcola e il difetto non si vede |

---

## 8. Diario

### Giorni 1–2 (dopo M6)
- Matrice degli errori e le sue conseguenze: `SALUTE`, retry misurato, Whisper sulla CPU (libera 0,28 GB, la trascrizione passa da 0,5 a 1,7 s per frase), Kokoro di riserva caricato in sottofondo (sincrono costava 34 s), email rimandate.
- Avvio robusto: Ollama atteso fino a 120 s, microfono atteso senza uscire, saluto.

### 2026-09-25
- Tray: icona disegnata dalla palette, pausa dell'ascolto nell'orchestratore, uscita solo da *Esci*.
- Autostart: script con anteprima, non installato. Provandolo sotto `pythonw` sono emersi §7 #2 e #3.
- Soak e verifica NFR: harness sul sistema vero; due prove da 9 minuti. La prima ha trovato §7 #5, il più grave di M7 — e il motivo per cui il soak va fatto con il sistema intero e non con i pezzi.
- Bundle PyInstaller: la prima prova su cartella pulita ha trovato §7 #9 e #10; la seconda parte e saluta. `docs/INSTALL.md`, override locale della posta (`config/email.local.toml`, ignorato da git).

---

## 9. Retrospettiva

<!-- Da compilare a progetto chiuso. Cosa ha funzionato, cosa rifaresti diversamente. -->

**Cosa ha funzionato:**
-

**Cosa rifarei diversamente:**
- Un banco end-to-end con router **e** conversazione alternati dall'M4 in poi avrebbe trovato §7 #5 tre iterazioni prima.

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
