# PHASE1 — Interfaccia "Hub" · Tracking

| | |
| :-- | :-- |
| **Stato** | 🔄 Lavoro completato; restano la ricertificazione di NFR-8 (uso reale, utente) e il tag |
| **Piano** | [Piano_Interfaccia_Hub.md](Piano_Interfaccia_Hub.md) |
| **Ramo** | `svil/phase1` |
| **Inizio** | 2026-09-25 |
| **Tag** | `p1-hub`, a fine fase |

**Avanzamento:** giorni 14/14 · criteri di uscita 15/17

---

## 1. Fatto

### Giorni 1–2 — Sistema di design ✅

- [x] `metis/gui/tema.py`: colori della cornice **campionati dalla reference** (sfondo `#060a0f`, pannelli `#0b161f`, bordi `#163850`, testo `#5edfff`), font, icone, foglio di stile
- [x] Font OFL in `metis/gui/risorse/font/` (Orbitron, Inter, JetBrains Mono) e 39 icone Lucide (ISC), con le licenze
- [x] `metis/gui/componenti.py`: `Pannello`, `Tessera`, `Barra`, `PulsanteIcona`, `Pillola`
- [x] Palette degli stati rivista, verificata sulle tonalità (§3 #1)
- [x] `benchmarks/gui_catalogo.py`, pagina di prova dei componenti
- [x] Risorse aggiunte ai `datas` di `metis.spec`

### Giorni 3–5 — Hub: impalcatura e conversazione ✅

- [x] `metis/gui/hub_view.py`: intestazione (nome, salute, orologio, kill switch, Diagnostica, Minimal), tre colonne, barra dei controlli
- [x] `metis/gui/modello_conversazione.py`: la conversazione come dati, con due viste — fumetti nell'Hub, registro nella Diagnostica
- [x] Fumetti: un fumetto per turno di Metis, l'utente a destra, gli eventi al centro; al massimo 200 disegnati
- [x] Colonna sinistra: Sistema (con la VRAM, anche se la reference non ce l'ha), Sessione, Meteo e Fotocamera come segnaposto
- [x] **Input di testo**: `Orchestrator.on_testo`, evento `TESTO` nella macchina a stati, **stesso percorso di sicurezza** della voce, provato con il broker vero
- [x] Turni scritti esclusi da NFR-1/NFR-2 (`origine` nel log, filtro in `verifica_nfr.py`)
- [x] "Pulisci" (memoria, riassunto, slot) con conferma predefinita su **Annulla**; "Esporta" in Markdown
- [x] Pulsante "muto": `Player.imposta_muto`, la coda scorre senza suono
- [x] Tre viste (Minimal, Hub, Diagnostica), una alla volta; tray con "Mostra Hub" e "Mostra Diagnostica"
- [x] `benchmarks/gui_screenshot.py`: catture dell'Hub con dati finti, in `data/catture/`

### Giorni 6–8 — Il nucleo e l'onda ✅

- [x] `widgets/nucleo.py`: un movimento per stato (respiro, barre sul microfono, arco che ruota, segmenti in due versi, pulsazione, onda, lampo), colore sempre dalla palette, sfumato in 250 ms
- [x] Bagliore con gradienti radiali nello stesso `paintEvent`, nessun `QGraphicsEffect`
- [x] Onda di `PARLATO`: quattro curve di Bézier con fasi diverse, ampiezza smussata (sale in 50 ms, scende in 220)
- [x] **Inviluppo della voce nel player**: RMS ogni 20 ms calcolato all'accodamento, `Player.livello_uscita()`; il worker lo spedisce al ritmo del microfono, solo mentre Metis parla. Nessun thread nuovo
- [x] Timer a 30 fps, preciso; **fermo** con la finestra nascosta o ridotta a icona, in pausa, con "riduci animazioni"
- [x] Il nucleo cresce con la finestra: 40% dell'altezza, fra 200 e 440 px
- [x] **Misura del giorno 7**: p95 2,2 ms a 1080p, sotto i 4 ms → **niente `QOpenGLWidget`** (§4)
- [x] Provato sull'applicazione vera, con Piper: l'onda segue la voce (§4)
- [x] `benchmarks/gui_nucleo.py` (la misura), `gui_screenshot.py --nucleo` (il foglio degli stati)

- [x] **Revisione delle catture del giorno 8**: approvata dall'utente (2026-09-25)

### Giorni 9–10 — Meteo ✅

- [x] `metis/gui/workers/meteo.py`: Open-Meteo su un thread suo (`metis-meteo`), ogni 15 minuti, 2 dopo un fallimento; timeout 4 s, così all'uscita una richiesta appesa non trattiene Metis
- [x] Codici WMO in italiano, con l'icona di giorno e di notte (luna, nuvola con luna)
- [x] **Senza rete**: l'ultimo dato con la sua ora ("dato delle 14:30 · la rete non risponde") finché ha meno di tre ore, poi una frase in persona. Nessun guasto esce dal worker: rete, HTTP, JSON diverso sono la stessa cosa per chi guarda
- [x] Cache in `data/meteo.json`, che sopravvive al riavvio: all'avvio si mostra subito l'ultimo dato
- [x] La città in `config/gui.local.toml` (ignorato da git), sopra `config/gui.toml` del repository; geocodificata una volta sola, le coordinate in cache finché la città non cambia
- [x] Dal PC escono solo le coordinate, e una volta il nome della città verso la geocodifica: un test guarda i parametri di ogni richiesta
- [x] `widgets/meteo.py`: temperatura, città, cielo, umidità, vento, percepita; nell'intestazione "18° Milano" con l'icona
- [x] Provato contro Open-Meteo vero (§4)
- [x] Disco e carico medio erano già pronti dai giorni 3–5

### Giorni 11–12 — Le altre viste e le impostazioni ✅

- [x] **Minimal**: stessa cornice, il nucleo in miniatura (64 px, 20 fps) al posto del pallino, con stati, livelli, kill switch e pausa; si ferma con l'overlay nascosto
- [x] **Diagnostica**: il foglio di stile proprio è sparito, vale quello di `tema`; intestazione come l'Hub, con il pulsante per **tornare all'Hub** (prima dalla Diagnostica si andava solo alla Minimal)
- [x] **Dialogo T3**: cornice e intestazione nel fucsia di "aspetta te", "Approva" con testo scuro. Stesse proprietà: `test_gui_conferma.py` non è stato toccato
- [x] **Impostazioni** (⚙ nell'Hub): città del meteo, riduci animazioni, vista all'avvio, muto all'avvio, in `config/gui.local.toml`. La geocodifica resta al worker del meteo: nessuna rete sul thread della GUI
- [x] Tray: colori da `tema` (le voci "Mostra Minimal / Hub / Diagnostica" c'erano dai giorni 3–5)
- [x] Fotocamera: il segnaposto c'era dai giorni 3–5 (sta in `widgets/sistema.py`, non in un file suo: un pannello senza contenuto non lo giustifica)
- [x] Il VU meter si ferma con la vista nascosta, come il nucleo
- [x] **Nessun colore esadecimale fuori da `tema.py` e `palette.py`**: l'elenco a cricchetto è vuoto
- [x] Catture: `benchmarks/gui_screenshot.py --viste` (Minimal, Diagnostica, T3, impostazioni)

### Giorni 13–14 — Verifica ✅ (tranne l'uso reale)

- [x] **DPI**: catture a 125% (1536×864 logici) e 150% (1280×720) su 1920×1080, in `data/catture/dpi/`: font e icone nitidi, layout integro. I due monitor di questo PC sono entrambi al 100%: il cambio di monitor non cambia scala, e lo sfocamento non si può provare qui
- [x] **Bundle** ricostruito e **provato su cartella pulita** (collegamenti al bundle, solo i `config` del repository e `data\piper`, PATH ridotto a System32): pronto in ~8 s, saluto, 55 s in esercizio con 0 blocchi, uscita 0, `metis.stderr.log` vuoto. Font e 39 icone nel bundle
- [x] Trovato provando il bundle: **chiudere durante l'avvio faceva crashare Metis** (§3 #22). Corretto, riprovato sul bundle nuovo: uscita 0
- [x] Specifica §11 (tre viste, telemetria, §11.4 Hub) e `docs/INSTALL.md` (§4.5 meteo e impostazioni, tre viste, `verifica_nfr.py --dal`)
- [x] Per la certificazione: all'uscita il log scrive la **durata dell'uso** ("sessione interfaccia"), e `verifica_nfr.py --dal` conta solo da un istante in poi

### Da fare (utente)
- [ ] **NFR-8 con l'Hub**: 30 minuti d'uso reale con l'Hub visibile, poi `verifica_nfr.py --dal <inizio della prova>`: 0 blocchi oltre 100 ms e i minuti di esercizio
- [ ] Commit e `git tag p1-hub`

---

## 2. Scostamenti dal piano

### "Aspetta te" è fucsia, non più arancione

Il piano chiedeva di verificare che gli stati da distinguere fossero lontani almeno
30° di tonalità. La verifica ha trovato un difetto già presente in PHASE0:
l'arancione di `ATTESA_CONFERMA` stava a **11°** dall'ambra di "sta pensando" e a
**27°** dal rosso dell'errore. Lo stato che chiede di intervenire era il più facile
da confondere. Ora è fucsia (`#e879f9`); la palette è passata alle varianti più
luminose, adatte al fondo quasi nero. Vale per overlay, tray e terminale, perché
la tabella è una sola.

### La conversazione è diventata un modello

Il piano diceva "i widget restano oggetti condivisi fra le viste". Con due viste che
mostrano la conversazione in due modi diversi non basta più: un widget Qt sta in una
sola finestra. I dati stanno in `ModelloConversazione`, e fumetti e registro ne sono
due viste. Il principio di M3 ("niente si ricopia") resta.

### Due scale per i livelli, non una

Il piano diceva "l'ampiezza dal livello". Una scala sola per microfono e voce
non funziona: misurata sull'applicazione vera, la voce di Piper ha mediana
−20 dBFS e l'onda restava sopra il 60% nel 97% dei fotogrammi, cioè sempre
alta. Il microfono ha un altro fondo: la stanza silenziosa sta a −86 dBFS e
la voce di chi parla a −22 (p95), entrambe misure di M0. Ora sono due scale:
microfono da −55 a −20, voce da −38 a −8. Nella prova vera il livello
dell'onda in `PARLATO` sta fra 0,44 e 0,84 (p10–p90) e segue le parole.

La misura del microfono fatta oggi (mediana −66, p95 −55, picchi a −40) è
stata presa **con musica negli altoparlanti**: è la musica, non la stanza. Il
fondo della scala a −55 regge lo stesso, perché sta 30 dB sopra la stanza muta
di M0: in silenzio le barre sono ferme, con la musica si muovono sui picchi.
La scala della voce non ne risente: si legge dal player, non dal microfono.

### 30 fotogrammi al secondo, non 60

Il piano lasciava i 60 fps alla misura. A 60 la CPU raddoppia (15–23% di un
core contro 5–10%) e in `PARLATO` il p95 del disegno sale a 4,7 ms, sopra la
soglia. A 30 il movimento è fluido: si resta a 30.

### La città, per ora, si scrive a mano

Il piano mette la città nelle Impostazioni, che arrivano nei giorni 11–12. Fino
ad allora si scrive in `config/gui.local.toml` (le istruzioni sono in testa a
`config/gui.toml`); senza, il pannello dice "Imposti la città nelle
impostazioni." Le coordinate trovate dalla geocodifica stanno in
`data/meteo.json` e non nel file di configurazione: quel file lo scrive
l'utente, e le Impostazioni ci scriveranno città e coordinate insieme.

---

## 3. Registro problemi

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 1 | "Aspetta te" a 11° da "sta pensando" | Lo stato più importante era il meno riconoscibile | Fucsia; test sulle tonalità |
| 2 | **Il foglio di stile scavalcava i font** | Una regola `QWidget { font-family; font-size }` vale per ogni widget e vince su `setFont`: nome, valori e titoli uscivano tutti in Inter a 13 px | I font non stanno nel foglio; font di base con `app.setFont`. Test di regressione |
| 3 | Fumetti larghi una parola | Il testo elastico (che evita il problema del link lungo) non chiedeva spazio, e il layout gli dava il minimo | Larghezza calcolata: quella del testo, fino all'86% della colonna |
| 4 | A 1280×720 la colonna sinistra si schiacciava | Barre sovrapposte, tessere collassate | Colonna scorrevole: i pannelli tengono la loro altezza |
| 5 | **Crash della suite (access violation), una volta su sei** | I test lasciavano Applicazioni intere in cicli di riferimenti, raccolte dal garbage collector a metà della costruzione della successiva | Fixture `crea_applicazione` in `conftest.py`: smontaggio esplicito a event loop fermo. 8/8 esecuzioni pulite. L'applicazione vera ne ha una sola: avviata con l'Hub, uscita con codice 0 |
| 6 | **"Apri Chrome" non faceva niente dopo un'interruzione** — trovato dall'utente | Presente **da M4**. Dopo un barge-in il token del turno interrotto restava annullato, e il turno successivo lo leggeva come proprio: le azioni uscivano senza eseguire (ESECUZIONE 15 s, poi ERRORE, nessuna riga nell'audit), la conversazione restava muta in GENERAZIONE. Poi `NO_SPEECH` da ESECUZIONE, transizione inesistente, lasciava la macchina ferma | Il token nasce all'inizio di ogni turno e viaggia fino all'ultima azione (`_nuovo_token`). Tre test che falliscono sul codice di prima. Provato sull'applicazione vera: ricerca, interruzione, "apri chrome" → Chrome aperto in 5 ms |
| 7 | Interrotta la prima ricerca di una sessione, Metis rispondeva lo stesso | Stessa radice del #6: senza un token precedente da annullare, il barge-in durante la ricerca non fermava la generazione | Risolto dal #6; test dedicato |
| 8 | TRASCRIZIONE scaduta (30 s) → ELABORAZIONE senza turno → ERRORE in silenzio | Presente **da M1**. Trovato riproducendo il #6 con il microfono vero: rumore continuo per 30 s dopo l'interruzione. La tabella dice "tronca", ma nessuno avviava il turno, e il segmento arrivato un attimo dopo veniva scartato | `SpeechSegmenter.forza()`: al troncamento l'audio raccolto va alla trascrizione; se non c'è niente, si torna ad ascoltare |
| 9 | **Ogni avvio della GUI diceva "Il microfono è di nuovo disponibile."** | Presente **da M7**. Il ciclo audio segnala anche il primo blocco (da "non so" a "c'è"), e il worker lo leggeva come un ritorno: la prima riga della conversazione era un avviso su un microfono mai mancato. Trovato nella prova reale dell'onda | Il worker dice "di nuovo disponibile" solo dopo aver detto l'assenza. Il contratto del ciclo non cambia (il soak lo usa). Test che fallisce sul codice di prima |
| 10 | L'onda sempre alta | Una scala sola per microfono e voce: la voce di Piper la saturava | Due scale, misurate (§2) |

**Dalla conversazione di prova dell'utente (2026-09-25, `CONVOS/Metis_20260925_1657.md`).**
Difetti di PHASE0 venuti fuori usando l'Hub; corretti su questo ramo perché bloccano l'uso quotidiano.

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 11 | **"Sai aiutarmi nella programmazione?" apriva VS Code** | Presente **da M5**. L'orchestratore mette la frase in memoria prima di chiedere al router, e il router la riaggiungeva: il modello la leggeva due volte. Riprodotto: doppia 5/5 VS Code, singola 0/5 | Il router toglie dalla cronologia la frase di adesso (`toolcall.precedenti`). Il banco del router non poteva vederlo: passava la frase senza cronologia. Ora ha una seconda tabella con la conversazione vera |
| 12 | Dopo "Ho aperto VS Code", "e se volessi farlo in locale?" lo riapriva | Il modello ripete l'ultima azione, 4 volte su 4, anche con la frase singola | `open_application` dal modello passa solo con un verbo di apertura (apri, avvia, lancia, fai partire…). I comandi rapidi no: sono frasi scelte dall'utente |
| 13 | **Le spiegazioni finivano sul web** | "Come faccio un chatbot AI?", "che differenza c'è tra RAM e VRAM": ricerca 3 volte su 3, contro la regola del prompt. La risposta si reggeva su una pagina a caso | Regola del router riscritta, con esempi diversi da quelli del banco. **Banco: 84/102 → 102/102** (3 giri), le domande di attualità vanno ancora sul web |
| 14 | **Pubblicità fra i risultati** | I primi due risultati erano annunci di Bing (`bing.com/aclick`, 942 e 622 caratteri): scartati da `web_fetch`, ma occupavano due posti da fonte su tre. Erano anche il link gigante nella conversazione | `web.organici`: fuori annunci e link oltre i 500 caratteri, anche dalla cache; si chiedono tre risultati in più |
| 15 | **Piper ha letto un indirizzo intero** | Il modello ha scritto un link markdown, e la pulizia del testo per la voce lo lasciava passare | Del link resta il nome; l'indirizzo nudo diventa il nome del sito. Funziona anche con il link spezzato fra due pezzi del TTS |
| 16 | Risposte con fonti: tu, lunghe, e "Ollama permette di addestrare" | Le fonti dicevano il contrario. Misurato su 9 risposte con le pagine vere: tu 3, oltre tre frasi 3, affermazione falsa 3 su 3 | Istruzioni delle fonti con le regole di stile e "non attribuire alle fonti ciò che non dicono": tu 1, oltre tre frasi 0. **L'addestramento resta debole** quando le fonti non rispondono (limite del modello da 8B); con il #13 quella domanda va in conversazione, dove la risposta è giusta (dataset, Hugging Face) |
| 17 | "Verifico." nel fumetto, come inizio della risposta | Le frasi d'attesa passano dalla stessa sintesi | Escluse dalla conversazione scritta (restano nella Diagnostica e nel log). "Le fonti, subito." → "Controllo le fonti." |

**Trovati nei giorni 9–12.**

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 18 | **La suite scriveva nel log di Metis** | Presente **da M0**. `get_logger()` configura il log alla prima chiamata, e i test scrivevano kill switch, pause e conversazioni azzerate finte in `data/logs/metis.jsonl`, il file da cui `verifica_nfr.py` certifica l'uso reale | `conftest.py` sposta il log dei test in una cartella temporanea, come faceva già il soak. Provato: suite intera, log vero invariato (1269 righe prima e dopo). Le righe dei test scritte fino a oggi restano nel file: per la certificazione dei giorni 13–14 conta la finestra della prova |
| 19 | **Nel registro della Diagnostica la conversazione era un paragrafo solo** | Presente **da M3**. Ogni riga era un `<div>` inserito con `insertHtml`, e Qt fonde il primo blocco del frammento con quello in cui cade il cursore: i messaggi uno attaccato all'altro. E togliere la riga provvisoria (che cancella l'ultimo paragrafo) avrebbe cancellato tutta la conversazione | Ogni riga apre il suo blocco, con i margini nel formato del blocco. Due test, uno per la riga provvisoria |
| 20 | Gli esiti dell'audit sempre bianchi | Presente **da M3**: i colori di ok, negato ed errore erano definiti e mai usati | La cella dell'esito prende il suo colore; test |
| 21 | Il registro non mostrava i messaggi già nel modello | Introdotto nei giorni 3–5, con il modello: i fumetti li ridisegnavano, il registro no. Non si vedeva perché il modello nasce vuoto | Ridisegnati alla costruzione, come i fumetti; test |
| 22 | **Chiudere Metis durante l'avvio lo faceva crashare** (0xC0000409) | Presente **da M3**. `Nucleo.ferma()` fermava solo un ciclo audio già creato: chiudendo mentre si caricavano i modelli la richiesta andava persa, il ciclo partiva (e salutava) dopo la chiusura, `chiudi()` smetteva di aspettarlo dopo 3 s e Qt distruggeva un thread vivo: `abort()`. E `CicloAudio.esegui` azzerava il flag all'ingresso, perdendo una `ferma()` arrivata un attimo prima. MSYS lo mostrava come "exit 127" | La richiesta di arresto resta e l'avvio non fa partire il ciclo; `esegui` non azzera più il flag; `chiudi()` aspetta la fine del caricamento. Due test che falliscono sul codice di prima. Provato: chiusura a 0,6 s e a 3 s, in sviluppo e sul bundle, sempre uscita 0 |

---

## 4. Misure

| Cosa | Valore |
| :-- | :-- |
| Suite | 1070 passati, 22 saltati |
| Test nuovi | `test_tema.py` 53, `test_testo_scritto.py` 17, `test_hub.py` 37, `test_nucleo.py` 29 |
| Mutazioni intercettate | 58 su 58 (tema 5, input scritto 5, Hub 10, nucleo e onda 10, microfono 1, conversazione di prova 6, meteo 8, viste 6, impostazioni 5, chiusura 2) |
| Bundle su cartella pulita | pronto ~8 s, 55 s in esercizio, 0 blocchi oltre 100 ms (max 82 ms), uscita 0; chiuso durante l'avvio: uscita 0 in 9 s |
| Meteo, Open-Meteo vero | primo giro 0,9 s (geocodifica + previsioni), poi 0,3 s; sul thread del meteo |
| Banco del router, 3 giri | 67/78 prima dei #11–#12 → 72/78 dopo; con i casi nuovi 84/102 prima del #13 → **102/102** |
| **Disegno del nucleo**, 1920×1080, nucleo 424 px, 30 fps | p95 **2,23 ms** (p50 1,5–2,2 secondo lo stato, max 6,4); `PARLATO` il più caro, p95 2,33 |
| CPU del processo, Hub visibile | 5–10% di un core secondo lo stato; **0,0% e 0 ridisegni con l'Hub nascosto** |
| Stesso, a 60 fps | p95 3,42 ms complessivo, 4,67 in `PARLATO`; CPU 15–23% di un core → scartato |
| Onda, applicazione vera (Piper, due risposte) | 302 campioni su 308 in `PARLATO` con la voce; livello p10 0,44 · p90 0,84; disegno p95 2,61 ms |
| NFR-8, stessa prova | 0 blocchi oltre 100 ms in esercizio, max 31,7 ms, ~62 fps (prova breve, non la certificazione) |

---

## 5. Criteri di uscita

- [x] Hub con le tre colonne della reference, approvato dall'utente sulle catture — *revisione del giorno 8*
- [ ] NFR-8 ricertificato con le animazioni attive
- [x] Disegno del nucleo p95 < 4 ms a 1080p — *2,23 ms; `QOpenGLWidget` non serve*
- [x] Zero ridisegni con la finestra nascosta — *test (anche cambiando vista) e misura: 0 ridisegni, 0,0% di CPU*
- [x] Stati distinguibili a colpo d'occhio: palette verificata dal test sulle tonalità
- [x] L'onda segue la voce di Metis, dal player — *test con silenzio-tono-silenzio e prova con Piper*
- [x] Input di testo con lo stesso percorso di sicurezza della voce, conferma T3 compresa
- [x] I turni scritti esclusi da NFR-1/NFR-2
- [x] "Pulisci" azzera vista, memoria e slot; "Esporta" produce Markdown
- [x] Meteo senza rete: ultimo dato o frase in persona, nessun blocco — *la rete solo sul thread del meteo; test su rete giù, dato vecchio, nessun dato*
- [x] Pannello fotocamera presente come segnaposto, pulsante disattivato
- [x] Tutti i test di M3 verdi senza modifiche: thread, lambda, conferma T3, cambio vista — *cambiati di proposito: l'elenco della tray (tre viste), tre test che confrontavano i valori esadecimali della telemetria (ora il gettone: il rosso resta rosso), e due test di M5 che misuravano sotto il foglio della Diagnostica, che non c'è più (ora quello dell'applicazione)*
- [x] Nessun colore esadecimale fuori da `tema.py` e `palette.py` — *elenco a cricchetto vuoto dai giorni 11–12*
- [x] Layout corretto da 1280×720 in su, a 100/125/150% di scala — *1280×720, 1600×900, 1920×1080 a 100%; 1920×1080 a 125% e 150%*
- [x] Bundle con font e icone, provato su cartella pulita — *PATH ridotto a System32, uscita 0*
- [x] Specifica §11 e `docs/INSTALL.md` aggiornati
- [ ] `git tag p1-hub`
