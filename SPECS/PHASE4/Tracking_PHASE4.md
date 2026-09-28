# PHASE4 — Imparare dall'uso ("frasi non capite") · Tracking

| | |
| :-- | :-- |
| **Stato** | 🟡 Codice, banchi, prova vera e documenti fatti (2026-09-28); restano la seconda misura della quota, il bundle e il tag |
| **Piano** | [Piano_Frasi_Non_Capite.md](Piano_Frasi_Non_Capite.md) |
| **Ramo** | `svil/phase4`, da `svil/phase2` (commit `25338f6`; PHASE2 non ha ancora il tag) |
| **Inizio** | 2026-09-28 |
| **Tag** | `p4-frasi`, a fine fase |

**Avanzamento:** giorni 0–7/8 · criteri di uscita 10/14

---

## 0. Prerequisiti

- [ ] PHASE2 chiusa (`p2-navigazione`) — si parte comunque dal suo ultimo stato: le frasi chiuse sono stabili
- [x] Correzione del giorno 0 (§2)
- [x] Decisioni D-FRASI chiuse: tutte come da raccomandazione (utente, 2026-09-28)
- [x] Ramo `svil/phase4`

---

## 1. Decisioni

| # | Decisione | Stato |
| :-- | :-- | :-- |
| D-FRASI 1 | Quattro segnali forti scritti dal codice, la ripetizione entro 30 s come segnale debole | ✅, con una precisazione (§2bis) |
| D-FRASI 2 | Rifiuti di sicurezza esclusi | ✅ |
| D-FRASI 3 | Si legge da `turns.jsonl`; decisioni in `data/frasi_decise.json` | ✅ |
| D-FRASI 4 | Lo storico parte dalla correzione: `[frasi] dal = "2026-09-28T14:35"` in `config/gui.toml` | ✅ |
| D-FRASI 5 | Crea, Variante, Segnala, Ignora; le frasi con parametro solo Segnala e Ignora | ✅ |
| D-FRASI 6 | Suggerito lo strumento, mai gli argomenti | ✅ |
| D-FRASI 7 | Guardie: due parole, non già riconosciuta, nessuna collisione, test sul banco | ✅ |
| D-FRASI 8 | Pannello nella Diagnostica, contatore nella Sessione dell'Hub | ✅ |
| D-FRASI 9 | Ultimi 30 giorni | ✅ |

---

## 2. Fatto

### Giorno 0 — Pulizia del log ✅ (tranne la misura di partenza, utente)

- [x] **Il difetto era più largo del previsto.** `TurnMetrics.append_to_log(path=LOG)`: il percorso era il *default dell'argomento*, valutato all'import, quindi spostare `metrics.LOG` non sarebbe servito a niente. Ora si legge al momento della scrittura (`metis/core/metrics.py`)
- [x] `tests/conftest.py` sposta `metrics.LOG` nella cartella temporanea dei test, accanto a `metis.jsonl`
- [x] **Anche il soak** (`tests/soak/run_soak.py`) spostava solo `metis.jsonl`: le sue interazioni sintetiche sarebbero finite nel `turns.jsonl` vero, contro la decisione di M7 di non mescolarle con quelle reali. Ora vanno nella cartella del soak
- [x] Due test in `tests/test_nfr.py`, accanto a quello di PHASE1: la suite non scrive nei turni veri; il percorso spostato si rispetta. Mutazione (percorso vecchio): entrambi falliscono
- [x] `[frasi] dal` in `config/gui.toml`, con il perché nel commento
- [x] Verifica: suite intera, `data/logs/turns.jsonl` identico al byte prima e dopo (937 606)
- [ ] **Misura di partenza (utente)**: una seduta vera di 20 minuti; poi la quota dei turni non capiti si legge dal pannello o con `python -c "from metis.memory import frasi; r = frasi.raccogli(); print(r.non_capiti, r.turni, r.quota)"`

### Giorno 1 — I segnali ✅

- [x] `Decisione.tolte` (solo i nomi degli strumenti tolti da `chiesta`) e `Decisione.riparazione_fallita` (due JSON non validi di fila), in `metis/llm/toolcall.py`
- [x] `metis/memory/frasi.py`: nomi dei segnali in ordine di precedenza, `FRASE_PERSONA`, `detta_dalla_persona`
- [x] Orchestratore: `extra["non_capito"]` con il motivo e `extra["tolta"]` con il primo strumento tolto, in tre punti (chiarimento, conversazione, strumento rifiutato agli stadi tecnici). La chiave `chiarimento` di PHASE2 resta
- [x] `risposte.STADI_TECNICI` reso pubblico: la stessa definizione per la frase all'utente e per il segnale
- [x] Una decisione finta (mock, `SimpleNamespace`) non produce segnali: conta solo una tupla vera
- [x] 27 test in `tests/test_frasi.py`: un turno intero dell'orchestratore per segnale; i rifiuti `policy`, `guardie`, `conferma`, `strumento` **non** sono segnali; Ollama giù non è una frase non capita; la frase della persona coincide con quella del prompt
- [x] Mutazioni: **6 su 6** prese (rifiuti di sicurezza contati, decisione finta presa per buona, argomenti nel suggerimento, riparazione non segnata, persona ignorata, chiarimento non segnato)

### Giorno 2 — La lettura ✅

- [x] `righe_dalla_fine`: il file letto dalla fine a blocchi, senza caricarlo tutto
- [x] `leggi_turni`: si ferma al limite, righe storte saltate, file assente = niente, mai un'eccezione
- [x] Ripetizione (segnale debole), frasi con parametro (`numeri_parlati`, dettatura, strumento tolto), raggruppamento per forma normalizzata, precedenza fra segnali a parità di conteggio, ordine (forti prima, poi per frequenza)
- [x] Decisioni: ignorata (sparisce), risolta (torna solo con i fallimenti dopo la decisione), segnalata (elenco da esportare); scrittura atomica
- [x] `data_di_partenza` con il `.local` che vince; `raccogli` = il tutto, con il limite dei 30 giorni e la partenza
- [x] I turni di PHASE2 con la sola chiave `chiarimento` valgono come chiarimenti
- [x] 41 test in più, con le frasi vere di `CONVOS/Metis_20260926_1920.md`
- [x] Misura: 100 000 righe in 0,64 s (§4)

### Giorno 3 — Le guardie ✅

- [x] `commands.controlla_frasi`: almeno due parole oltre le cortesie; non già riconosciuta da un altro comando (chiedendolo al `Router` stesso) né dalle frasi fisse (`frasi_chiuse.riconosci` con i numeri a schermo, `dettatura`). Motivo sempre in parole
- [x] Applicata solo alle frasi **nuove**: in `aggiungi`, in `modifica` (solo le frasi che il comando non aveva) e in `aggiungi_frase` (nuovo, la variante). `carica` non scarta niente: in `config/commands.json` ci sono tre frasi corte scritte in M4 ("telemetria", "si lavora", "si comincia")
- [x] Test di non collisione con **tutte le frasi del banco del router** (`CASI` e `CASI_CONVERSAZIONE`), sul `config/commands.json` vero, senza modello; più il verso negativo (un comando che si prende "che ore sono" fa fallire il controllo)
- [x] 30 test in più; mutazioni **6 su 6** prese
- [x] Un test di M4 cambiato di proposito (`test_gui_widgets.py`): usava la frase di una parola "prova" per verificare le parentesi quadre attorno all'azione; ora "fai la prova"

### Giorni 4–5 — L'interfaccia ✅ (tranne la revisione delle catture, utente)

- [x] `metis/gui/workers/frasi.py`: `LettoreFrasi` su un thread suo (`metis-frasi`), senza timer: rilegge all'avvio, a fine turno, dopo una decisione. Mai un'eccezione verso la GUI
- [x] `metis/gui/widgets/frasi.py`: `PannelloFrasi` nella colonna "ADESSO" della Diagnostica, sotto i comandi rapidi (riepilogo con la quota, anteprima di tre, pulsante); `DialogoFrasi` con le quattro azioni. Le frasi con parametro hanno solo *Segnala* e *Ignora*, con la spiegazione; la ripetizione (debole) è in grigio, con la sua nota
- [x] *Crea*: `EditorComandi.nuovo_da_frase` (frase, identificativo unico, strumento suggerito **senza argomenti**, avviso); la frase diventa "risolta" solo se il comando c'è davvero dopo la chiusura dell'editor
- [x] *Variante*: scelta del comando, `Libreria.aggiungi_frase`; il rifiuto delle guardie resta nel dialogo e la frase resta da rivedere
- [x] *Esporta segnalate*: Markdown in un file scelto dall'utente (`frasi.markdown_segnalate`)
- [x] Contatore nella Sessione dell'Hub ("3 frasi non capite da rivedere"), nascosto a zero; il clic porta alla Diagnostica
- [x] `DECISE` letto alla chiamata (lo stesso difetto del giorno 0, in `frasi.py` stesso) e spostato da `conftest.py`: nessun test tocca le decisioni vere
- [x] Catture: `python benchmarks/gui_screenshot.py --frasi` → `data/catture/frasi_*.png` (pannello, dialogo, frase con parametro, frase debole, editor precompilato, contatore dell'Hub)
- [x] 46 test in più; mutazioni **6 su 6** prese
- [ ] **Revisione delle catture (utente)**

---

## 2bis. Scostamenti dal piano

### La ripetizione segna il turno di prima

D-FRASI 1 diceva "la stessa frase ripetuta entro 30 s dopo un turno non riuscito". Un turno già
non riuscito, però, ha il suo segnale forte: la ripetizione non aggiungerebbe niente. Serve a vedere
il fallimento **silenzioso**, cioè il turno che è sembrato andare bene e non era quello che si voleva
("Torna indietro." → "Indietro.", nessuno strumento: prova del 2026-09-26). Il segnale debole va quindi
sul **primo** dei due turni, e solo se Metis aveva risposto a parole: non dopo uno strumento riuscito
("scorri giù" tre volte è un uso normale), non dopo una ricerca web, non su un turno che ha già un
segnale forte.

### La guardia "collisione" coincide con "già riconosciuta"

D-FRASI 7 ne elencava tre: due parole, non già riconosciuta, nessuna collisione per contenimento.
Leggendo il router si vede che la terza è già dentro la seconda: il percorso rapido ammette attorno a
una frase **solo cortesie** (PHASE2) e prova **prima le frasi più lunghe** (M4). Una frase nuova non può
quindi scattare dentro la frase di un altro comando; resta solo l'uguaglianza, che la seconda guardia
controlla chiedendo al `Router` stesso. Il rischio di "rubare" le frasi, descritto nel piano, era più
piccolo del previsto: il test sulle frasi del banco resta, come rete.

### Le frasi del banco restano nel banco

Il piano le spostava in `tests/fixtures/frasi_router.json`. Accanto a ogni frase però c'è un controllo
sugli argomenti scritto come funzione (`lambda c: c[0]["numero"] == 7`), che in un JSON non entra. Il
test importa `CASI` da `benchmarks/prova_router.py`: una fonte sola, nessuna copia.

### Il rifiuto del broker agli stadi tecnici conta come "riparazione"

Il piano elencava la riparazione fallita del router. Il suo gemello è la tool call malformata che il
broker rifiuta agli stadi `json`, `registro`, `schema` ("Non ho capito la richiesta abbastanza bene per
agire"): stesso difetto, un passo più in là. Stesso segnale.

---

## 3. Registro problemi

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 1 | **Suite e soak scrivevano turni finti in `data/logs/turns.jsonl`** | Presente **da M0** (il file) e da M7 (il soak). ~40 turni finti a ogni esecuzione della suite; il pannello li avrebbe proposti come frasi da imparare. Non si separano più da quelli veri | Percorso letto alla scrittura, spostato da suite e soak; data di partenza del pannello (D-FRASI 4); due test |
| 2 | La frase della persona va a capo a metà nel prompt | Il test "la frase coincide con il prompt" falliva pur essendo giusta | Confronto a spazi compattati |
| 3 | La lettura di 100 000 turni prendeva 1,38 s | Oltre il secondo del piano | `normalizza` memorizzata (`lru_cache`): era il 90% del tempo. 0,64 s |
| 4 | Una prova di mutazione ha scritto 2 righe nel `turns.jsonl` vero | Col codice vecchio il percorso non si sposta: è proprio il difetto che la mutazione rimette | Righe riconosciute (`turn_id` "suite" e "t") e tolte; file tornato a 937 606 byte |
| 6 | **I rifiuti dello stadio `strumento` trattati come rifiuti di sicurezza** | Trovato nella prima seduta vera: sei turni andati male su dieci non arrivavano al pannello, e la quota (2,5%) sottostimava l'attrito | Quinto segnale forte, `STRUMENTO`: rifiuto dello strumento o sua eccezione (stadi `strumento`, `esecuzione`). I rifiuti di sicurezza (`policy`, `guardie`, `guardie_immediate`, `conferma`) restano fuori. Due test, una mutazione |
| 7 | **`type_text` dal modello senza un verbo** ("Devi dire grazie" → scrivere "grazie") | Presente da PHASE2: con il fuoco in un campo, Metis avrebbe scritto un pezzo di una frase qualunque | Verbo di scrittura **e** testo detto (`toolcall.chiesta`); sei casi, compresi quelli della seduta; mutazione presa |
| 8 | "ma stra minumere" non era "mostra i numeri" | Segnalata dall'utente dal pannello: il router proponeva un video | Il verbo spezzato e la "mi" davanti a "numere" in `frasi_chiuse._MOSTRA`; falsi positivi provati ("ma stasera…", "mostra minuti"); mutazione presa |
| 5 | `frasi.DECISE` come default di un argomento | Lo stesso difetto del #1, scritto il giorno 2: un test dell'applicazione che arrivasse a una decisione avrebbe scritto nel `data/frasi_decise.json` vero | Letto alla chiamata, spostato da `conftest.py`. Verificato: dopo la suite il file vero non esiste |

---

## 4. Misure

| Cosa | Valore |
| :-- | :-- |
| Suite, inizio fase | 1522 passati, 30 saltati |
| Suite, fine giorno 1 | 1551 passati, 30 saltati |
| Suite, fine giorni 4–5 | **1640 passati**, 30 saltati (sempre gli stessi: i casi T0/T1 del test di injection, esclusi di proposito) |
| Mutazioni, giorni 1–5 | **18 su 18** prese |
| Banchi del modello, 3 giri, dopo i giorni 0–5 | router **165/165** (mediana 475 ms), anafora **12/12**, injection **0/18** T2/T3 ostili e 0 eseguite, integrazioni **15/15** effetti, esito superato |
| Suite, chiusura (con #6–#8) | **1652 passati**, 30 saltati; mutazioni della chiusura 3 su 3 |
| Banchi, chiusura (router, injection, anafora) | router **165/165**, injection 0 eseguite, anafora **12/12** |
| `turns.jsonl` prima e dopo la suite | 937 606 byte, invariato |
| Lettura e raggruppamento, 100 000 righe (36 MB), cache fredda | 1,38 s → **0,64 s** |
| Stesso, ultimi 30 giorni di uso intenso (6 480 turni) | 0,09 s |
| Log vero dalla data di partenza | 0 turni (corretto: la partenza è di oggi) |
| Log vero senza data di partenza, 30 giorni | 2 282 turni: 507 "ciao" ripetuti e "clicca su oltra un tunnel", tutti dei test — la ragione di D-FRASI 4 |

---

## 4bis. La prima seduta vera (2026-09-28, 16:04–16:14)

40 turni, a voce, fra prove e chiacchiere. Il pannello dice **1 frase non capita su 40 (2,5%)**, più
una ripetizione. Rileggendo il log a mano i turni andati male sono **una decina**: i segnali ne vedono
una piccola parte.

| Turno | Cosa è successo | Visto dal pannello? |
| :-- | :-- | :-- |
| "ma stra minumere." | Il router propone `riproduci_youtube`, il codice lo toglie: "Non ho capito cosa fare" | ✅ azione tolta (segnalata ed esportata dall'utente) |
| "Come stai messo a benzina?" ×2 | Risposta a parole, poi ripetuta | ✅ ripetuta (debole) |
| "bravissimo, hai schippato una pubblicità su youtube." | Il router propone `click_element("pubblicità")` su un complimento; lo strumento non trova niente | ❌ rifiuto allo stadio `strumento` |
| "Devi dire grazie.", "Ma sei rincoglionito?", "Scrivi sul 42." | Il router propone `type_text`; lo salva solo il controllo "il cursore non è in un campo di testo" | ❌ idem |
| "scrivi." | `mostra_numeri` | ❌ azione riuscita, ma non chiesta |
| "mostra i numeri." ×3, "mastra i numeri." | "Quella finestra non c'è più" quattro volte: la finestra di riferimento è quella vecchia | ❌ rifiuto allo stadio `strumento` |
| "Cerca sul web.", "Ora cercano sul web?" | "Non ho accesso a Internet": falso | ❌ conversazione sbagliata, non riconoscibile |
| "apricrom e metti in video di youtube." | Parte un video cercando "apricrom e metti in video di youtube" | ❌ azione riuscita, sbagliata |
| "cazioni poi fare." | "Lei non ha chiesto niente." | ❌ trascrizione storpiata, riformulata a parole diverse |

**Il difetto di questa fase.** D-FRASI 2 esclude i rifiuti di *sicurezza* (denylist, kill switch,
vietate, conferma negata, turni contaminati). Nell'implementazione ho messo fra questi anche lo stadio
`strumento`, che non lo è: è lo strumento che non riesce ("non trovo l'elemento", "non sei in un campo
di testo", "la finestra non c'è più"), cioè quasi sempre uno strumento sbagliato scelto dal router, o un
difetto. Sei dei turni qui sopra sarebbero stati visti. Da correggere (§3 #6).

**Difetti trovati fuori da questa fase:**

1. ✅ **`type_text` dal modello non chiedeva un verbo** — corretto qui (§3 #7)
2. **La finestra di riferimento non si aggiorna nei turni senza tasto.** Si cattura al push-to-talk; nei
   turni degli 8 s dopo una risposta resta quella di prima, anche se è stata chiusa → **PHASE5**, dove
   la sessione lo renderebbe molto più frequente
3. **"Non ho accesso a Internet"**: la persona non sa di poter cercare → **PHASE6** (qualità della
   conversazione)
4. **`click_element` dal modello senza un verbo di clic** ("hai schippato una pubblicità") → **PHASE6**
5. ✅ "ma stra minumere" — corretto qui (§3 #8)

**E un problema più grande, emerso subito dopo** (l'utente: "mi sembra di parlare con la prima
versione di GPT, ignora la mia richiesta"): rigiocate contro Qwen, le frasi della seduta mostrano che
con la cronologia il modello **ripete le risposte precedenti** invece di rispondere ("Quali azioni puoi
fare?" → "Lei non ha chiesto niente."), non sa cosa sa fare, dice il ripiego "non ho capito" a caso, e
ha il tic del "lei". Non è il riconoscimento vocale (37/40 trascrizioni giuste). Diventa **PHASE6**, da
fare prima di PHASE5.

---

## 5. Da fare (utente)

1. ~~Misura di partenza~~ — fatta con la seduta del 2026-09-28 (§4bis): prove, non 20 minuti d'uso
2. ~~Le catture del pannello~~ — approvate (2026-09-28)
3. ~~La prova vera del giorno 7~~ — fatta: "ue figa" (variante di `elenco_monitor`) e "come stai messo a
   benzina?" (variante di `apri_chrome`) funzionano alla prima. Le decisioni registrate mostrano solo
   *Segnala* ed *Esporta* usati dal pannello

---

## 6. Criteri di uscita

- [x] La suite non scrive più in `data/logs/turns.jsonl`, verificato da un test
- [x] I quattro segnali forti finiscono nel turno; i rifiuti di sicurezza no, verificato da un test
- [x] Il pannello mostra le frasi raggruppate e contate, la quota dei turni non capiti e le quattro azioni
- [x] Le frasi con un parametro hanno solo *Segnala* e *Ignora*
- [x] *Crea* e *Variante* passano dall'editor e dalla validazione di sempre; lo strumento suggerito arriva senza argomenti
- [x] Guardie: frase troppo corta, già riconosciuta o in collisione rifiutata con il motivo in parole
- [x] Nessuna frase di `config/commands.json` cambia l'esito di una frase del banco (test senza modello)
- [x] Banchi del modello verdi, 3 giri — *router 165/165, anafora 12/12, injection 0 azioni, integrazioni 15/15; da rifare dopo la prova vera se `commands.json` cambia*
- [ ] Lettura su un thread suo; NFR-8 verde con il dialogo aperto
- [x] Prova vera: frasi nuove diventano varianti e funzionano — *due varianti, provate a voce dall'utente (§5)*
- [ ] Quota dei turni non capiti misurata prima e dopo — *una misura sola (2,5%), e sottostimata finché non c'è il segnale di §3 #6*
- [x] Catture riviste dall'utente — *approvate, 2026-09-28*
- [ ] Specifica, `docs/INSTALL.md`, `FEATURES.md`, bundle aggiornati — *specifica (§9.3, §10.1, §11.2, §11.5), guida (§5.2) e FEATURES sì; bundle no*
- [ ] `git tag p4-frasi`
