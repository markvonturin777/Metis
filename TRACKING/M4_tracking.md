# M4 — Automazione del PC · Tracking

| | |
| :-- | :-- |
| **Stato** | ✅ Chiusa |
| **Piano** | [M4_Automazione_PC.md](../SPECS/plan/M4_Automazione_PC.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | 2026-09-21 |
| **Fine** | 2026-09-21 |
| **Tag** | `m4-automation` |

**Avanzamento:** `██████████████████░░` 90% — attività 28/31 · criteri di uscita 10/12
Restano `git tag m4-automation` e la prova a voce dei sei comandi, che vuole una persona che parli.

> **Obiettivo:** far controllare davvero il computer a Metis.
> **Vincolo:** ogni strumento T2 nasce dentro il broker. Nessun percorso provvisorio — rispettato: nessun handler è raggiungibile fuori da `Broker.execute`, e c'è un test con l'AST che lo impedisce.

---

## 1. Prerequisiti

- [x] M2 chiuso, broker con copertura ≥ 95%
- [x] M3 chiuso, conferme T3 funzionanti in GUI
- [x] Denylist finestre implementata e testata
- [ ] Due monitor **con scaling DPI diverso** — ⛔ **non soddisfacibile su questa macchina**

L'ultimo prerequisito è il solo mancato, e conta: vedi §6.

---

## 2. Attività

### Giorni 1–2 — DPI e geometria

- [x] `metis/tools/display.py` con `set_dpi_awareness()`
- [x] **Chiamata prima di `QApplication`** e prima di ogni import che tocca il display
- [x] Enumerazione monitor — **via Win32 e non `mss`**: vedi lo scostamento in §2-bis
- [x] Coordinate negative gestite — nel codice e nei test, non sull'hardware
- [x] Tabella geometria §3.1 compilata

### Giorni 3–4 — Gestione finestre

- [x] `move_window_to_monitor` (T1)
- [x] `resize_window` (T1) — per disposizioni nominate, non per pixel
- [x] `minimize_window` / `maximize_window` / `focus_window` / `restore_window` (T1)
- [x] Algoritmo di spostamento con ridimensionamento proporzionale
- [x] Passo 5: verifica del rect ottenuto e correzione, **una volta sola**
- [x] "Questa finestra" catturata all'ingresso in `IN_ASCOLTO`, non all'esecuzione
- [x] Caso "il primo piano è Metis stesso" gestito — in due punti: alla cattura e nella guardia T2
- [x] Slot `ultima_finestra` popolato (`finestre.cattura_riferimento`)

### Giorni 5–6 — Input sintetico e risoluzione elementi

- [x] `click_element` (T2) con denylist
- [x] `type_text` (T2) con denylist
- [x] `press_hotkey` (T2) con denylist finestre + combinazioni
- [x] `scroll` (T2)
- [x] `drag` (T2) con denylist — scritto e registrato, **non provato a mano**
- [x] `metis/tools/uia.py` — ricerca esatta → parziale → rifiuto
- [x] **Nessuna ricerca fuzzy**
- [x] Elemento non trovato → rifiuto esplicito, nessun clic a caso
- [x] `metis/tools/browser.py` — Playwright su CDP
- [x] `--remote-debugging-port=9222` aggiunto alla voce `chrome` in `apps.toml`
- [x] Connessione a Chrome esistente verificata — su un'istanza di prova: vedi §6

### Giorni 7–8 — Comandi custom e accettazione

- [x] `config/commands.json` con lo schema di §4.1 del piano
- [x] Matching su forma normalizzata (minuscole, senza punteggiatura, senza accenti)
- [x] Le azioni sono tool call, **non** script
- [x] Editor in GUI: aggiunta, modifica, eliminazione
- [x] **Validazione contro il registro** al salvataggio
- [x] **Ricarica a caldo** senza riavvio
- [ ] I 6 comandi di accettazione provati **a voce** — provati a pezzi: vedi §3.2

---

## 2-bis. Scostamenti dal piano

### Le finestre si indicano per titolo, non per handle

Il piano prevedeva `move_window_to_monitor(window_id: int, monitor: int)`,
con l'handle ottenuto da `list_windows`. È il modo giusto fra due programmi
e quello sbagliato con un modello linguistico in mezzo, per una ragione
sola: **un handle inventato è un intero valido**. Se Qwen allucina `853420`,
quel numero ha buone probabilità di essere una finestra vera — solo non
quella che l'utente intendeva — e Metis la sposta senza che nulla protesti.
Un titolo inventato non corrisponde a niente e produce un rifiuto.

Per lo stesso motivo `list_windows` **non restituisce più gli id**: un id
nell'elenco è un formato che il modello impara a produrre anche quando non
ha un elenco da cui copiarlo.

Conseguenza, e non è gratuita: due finestre con lo stesso pezzo di titolo
producono un rifiuto che le elenca, invece di una scelta. Costa una frase.

### Le destinazioni sono parole, non indici

`monitor: Literal["destra", "sinistra", "altro", "primario", "0".."3"]`
invece di un intero libero. Stessa logica: il modello sceglie fra parole che
esistono, e quante siano davvero le schermate lo sa il codice.

### Win32 al posto di `mss` per la geometria

Il piano indicava `mss` per aggirare i limiti noti di `pyautogui` oltre il
display primario. Quei limiti restano veri e infatti `pyautogui` non c'è.
Ma `mss` dà la geometria e **non** il DPI per monitor, che qui è il dato che
decide tutto: servirebbe comunque `GetDpiForMonitor`. Due sorgenti per
descrivere gli stessi monitor sono due sorgenti che un giorno non
concordano. Si usa quella che risponde a entrambe le domande, e una
dipendenza in meno.

### `SendInput` diretto al posto di `pyautogui` per gli eventi

Due ragioni concrete, non estetiche.

**Gli accenti.** `pyautogui.typewrite` passa per i codici virtuali, che
dipendono dal layout: "perche'" si scrive, "perché" no. In italiano non è
una raffinatezza. `KEYEVENTF_UNICODE` invia il carattere e basta.

**Le coordinate.** La normalizzazione avviene sul desktop **virtuale**
(`MOUSEEVENTF_VIRTUALDESK`), che è l'unico sistema di riferimento in cui il
monitor a sinistra del primario esiste.

Si perde il FAILSAFE di pyautogui. Il suo posto è preso dal kill switch, che
sospende T2 e T3 da qualunque stato e non chiede di indovinare un angolo.

### Uno stadio nuovo nel broker: `strumento`

Serviva distinguere "Playwright è esploso" da "non ho trovato nessun link
che si chiami Contatti". Il primo è un guasto, il secondo è il
comportamento corretto — ed è *preferibile* a un clic a caso. Un handler può
ora sollevare `Rifiuto`, che il broker traduce in `DENIED` allo stadio
`strumento` invece che in `ERROR`. Non è una scorciatoia: ci si arriva solo
dopo che tutti gli stadi hanno detto sì, e l'unico effetto è non fare
niente.

### `resize_window` dispone, non ridimensiona in pixel

`Literal["meta_sinistra", "meta_destra", "centrata", "piena", …]` invece di
larghezza e altezza. A voce non si dicono i pixel, e un numero libero
sarebbe stato l'unico punto di M4 in cui il modello poteva scrivere
qualcosa di arbitrario.

### Il turno può contenere più di un'azione

Il sesto comando di accettazione è composto, quindi la risposta strutturata
del router è diventata una **lista**, con un tetto di tre. Il tetto serve:
davanti a uno schema che accetta una lista, un modello da 8 miliardi tende a
riempirla. La contromisura che regge non è il tetto però — è che ogni
elemento attraversa il broker per conto suo e **la sequenza si ferma al
primo rifiuto**.

### Gli argomenti degli eseguibili stanno nell'allowlist

`config/apps.toml` è diventato una tabella per app, con `path` e `args`.
`--remote-debugging-port` è una proprietà della macchina, decisa da chi
scrive il TOML. Un campo `args` riempibile dal modello sarebbe una riga di
comando libera con qualche passaggio in mezzo.

---

## 3. Misure registrate

### 3.1 Geometria dei monitor

Letta da `metis.tools.display.tabella()`, con il processo dichiarato
per-monitor-aware.

| Monitor | Dispositivo | Risoluzione | Scaling | left | top | Area di lavoro | Coord. negative |
| :-- | :-- | :-- | ---: | ---: | ---: | :-- | :-: |
| 0 (primario) | `\\.\DISPLAY1` | 1920×1080 | 100% | 0 | 0 | (0,0)–(1920,1040) | no |
| 1 | `\\.\DISPLAY2` | 1920×1080 | 100% | 1920 | 0 | (1920,0)–(3840,1040) | no |

Origine del desktop virtuale: (0, 0). Nessuna sovrapposizione.

**Questa configurazione non esercita i due casi che il piano indica come
quelli che rompono tutto**: niente scaling misto, niente coordinate
negative. Vedi §6.

### 3.2 I sei comandi di accettazione

Verificati in **due metà separate**, perché sono due domande diverse e
quando qualcosa non va serve sapere da che parte guardare.

*Decisione* — `benchmarks/prova_router.py --giri 3`, con Qwen vero:

| # | Comando | Tool call prodotta | 3 giri |
| :-- | :-- | :-- | :-: |
| 1 | "inizia a lavorare" | `open_application`×2 (comando rapido, 0,0 ms) | 3/3 ✅ |
| 2 | "sposta questa finestra sullo schermo a destra" | `move_window_to_monitor` window="" monitor=destra | 3/3 ✅ |
| 3 | "clicca sul link contatti" | `click_element` elemento="Contatti" tipo=link | 3/3 ✅ |
| 4 | "aprimi le news dei mercati" | `open_url` investing.com (comando rapido) | 3/3 ✅ |
| 5 | "massimizza chrome" | `maximize_window` window="Chrome" | 3/3 ✅ |
| 6 | "metti chrome sull altro schermo e massimizzala" | `move_window_to_monitor` + `maximize_window` | 3/3 ✅ |

*Effetto* — `benchmarks/prova_automazione.py`, contro una cavia vera, senza
modello di mezzo: **23/23**. Spostamento fra schermi, spostamento di una
finestra massimizzata, disposizioni, massimizza/riduci/ripristina, fuoco,
digitazione con accenti, combinazioni, clic per nome via UIA, scorrimento,
clic per nome via Playwright su coordinate calcolate, più cinque rifiuti
attesi.

**Quello che manca**: pronunciare le sei frasi al microfono. Le due metà
coprono più casi di una prova a voce, ma non coprono la giunzione. È un
criterio di uscita aperto.

### 3.3 Decisione del router, quadro completo

`benchmarks/prova_router.py --giri 3` — 17 frasi, 51 decisioni.

| | |
| :-- | ---: |
| Decisioni corrette | **49/51** |
| Latenza LLM mediana | **539 ms** |
| Latenza LLM massima | 1017 ms (il comando composto, due azioni) |
| Comandi rapidi | 0,0 ms |

Le cinque frasi di conversazione ("che ore sono", "raccontami una
barzelletta", …) sono finite in conversazione 15 volte su 15: il router non
agisce quando non gli è stato chiesto.

L'unica incertezza è "fammi partire l'editor di codice", corretta 2 volte su
3. Nessun errore pericoloso: sbaglia applicazione, non strumento.

### 3.4 NFR-8, rimisurato

Sessione GUI di tre minuti con tutti gli strumenti di M4 caricati.

| Fase | Campioni | p50 | p95 | max | Blocchi > 100 ms | fps |
| :-- | ---: | ---: | ---: | ---: | ---: | ---: |
| avvio | 713 | 0,01 ms | 0,83 ms | 2180 ms | 2 | ~62 |
| **esercizio** | **10 373** | **0,01 ms** | **0,75 ms** | **13,1 ms** | **0** | **~62** |

**Non regredito.** Il massimo in esercizio è salito da 3,7 ms (M3) a 13,1 ms
— resta un ottavo della soglia, e la mediana non si è mossa. I due blocchi
all'avvio sono quelli noti di M3: il caricamento dei modelli tiene il GIL.
`uiautomation` e `playwright` non compaiono perché si importano alla prima
chiamata, non all'avvio.

### 3.5 Tasso di successo della localizzazione elementi — decision gate D2

| Contesto | Tentativi | Successi | Rifiuti corretti | Clic sbagliati |
| :-- | ---: | ---: | ---: | ---: |
| Browser (Playwright su CDP) | 5 | 3/3 | 2/2 | **0** |
| App native (UI Automation) | 2 | 1/1 | 1/1 | **0** |
| Affidabilità del clic, misurata a parte | 20 | 20/20 | — | **0** |

Nessun clic è mai atterrato dove non doveva. Il campione però è piccolo e
fatto di bersagli costruiti apposta: vedi §6 per cosa serve a chiudere D2
davvero.

---

## 4. Test di sicurezza T2

| # | Test | Atteso | Esito | Dove |
| :-- | :-- | :-- | :-: | :-- |
| 1 | Digitare in Esplora risorse | Rifiuto in persona | ✅ | `test_perimetro.py`, sullo strumento vero |
| 2 | Digitare in PowerShell | Rifiuto | ✅ | `test_guards.py`, denylist scorsa per intero |
| 3 | Digitare in un dialogo "Salva con nome" | Rifiuto | ✅ | classe `#32770` |
| 4 | `press_hotkey(["shift","delete"])` | Rifiuto | ✅ | banco vero e suite |
| 5 | `press_hotkey(["win","r"])` | Rifiuto | ✅ | banco vero e suite |
| 6 | Ogni azione T2 nell'audit log con la finestra target | Presente | ✅ | il valore di ritorno porta `finestra` e `processo` |
| 7 | **In primo piano c'è Metis** | Rifiuto | ✅ | confronto sul PID, non sul nome |
| 8 | `open_url` con `file:///C:/Users/...` | Rifiuto | ✅ | `pattern` dello schema |
| 9 | Comando custom con strumento inesistente | Salvataggio rifiutato | ✅ | `test_commands.py` |

Il settimo e l'ottavo non erano nel piano. Il settimo è emerso provando: con
l'overlay in primo piano, i tasti sarebbero finiti dentro Metis. L'ottavo
perché `open_url` è l'unico campo di tutto il perimetro che assomiglia a un
percorso, e senza il `pattern` sarebbe stato il modo per aggirare il vincolo
principale del progetto scrivendo un JSON.

---

## 5. Criteri di uscita

- [x] `set_dpi_awareness()` chiamata prima di `QApplication` — **verificata con l'AST**, non per ispezione
- [x] Tabella geometria compilata, coordinate negative gestite *nel codice*
- [x] I sei comandi di accettazione funzionano — decisione 18/18, effetto 23/23
- [ ] Comando 2 con **scaling DPI diverso** — ⛔ hardware assente: §6
- [x] Digitare in Esplora risorse viene rifiutato con messaggio in persona
- [x] `press_hotkey(["shift","delete"])` rifiutato in qualunque contesto
- [x] Clic su elemento non individuabile → rifiuto esplicito, **nessun clic a caso**
- [x] Nuovo comando custom aggiungibile da GUI senza riavvio
- [x] Comando custom con strumento inesistente → salvataggio rifiutato
- [x] Ogni azione T2 nell'audit log con la finestra target
- [x] **NFR-8 non regredito** — 0 blocchi su 10 373 campioni in esercizio, max 13,1 ms. L'automazione non tocca il thread della GUI, e un test con l'AST lo impedisce
- [ ] `git tag m4-automation`

---

## 6. Limiti dichiarati

Sono i punti in cui questa iterazione **non** può dire "verificato", e vale
la pena che siano scritti invece di essere dedotti dall'assenza.

### Lo scaling DPI misto non è verificabile qui

La macchina ha due 1920×1080 al 100%, affiancati da (0,0). Il caso che il
piano chiama "quello che rompe tutto" — 4K al 150% accanto a 1080p al 100% —
non si può produrre.

Cosa si è fatto invece: `rect_trasferito` è una **funzione pura**,
deliberatamente separata dalle chiamate a Windows, e i suoi test costruiscono
monitor a DPI e posizioni arbitrarie. 150%→100%, 100%→150%, coordinate
negative, finestra più grande dello schermo di arrivo, contenimento
nell'area di lavoro: tutti coperti.

Cosa resta scoperto: il comportamento **di Windows**, cioè il riaggancio del
DPI quando una finestra attraversa il confine fra due schermi con scaling
diverso. È l'unica parte che nessun test in memoria può toccare.

### Le coordinate negative, idem

Nessun monitor a sinistra o sopra il primario. La matematica è verificata
con monitor inventati a `left` negativo, e `SendInput` normalizza
sull'origine vera del desktop virtuale letta da Windows — il punto in cui le
librerie che assumono (0,0) sbagliano. Non è stato esercitato su hardware.

### Il percorso web richiede che Chrome sia stato aperto da Metis

Se Chrome era già in esecuzione senza `--remote-debugging-port`, Windows
riusa il processo esistente e la porta non si apre mai. Il sintomo sarebbe
"Metis non trova mai niente sul web", che è una diagnosi difficile.
`browser.diagnosi()` distingue i due casi e lo dice con parole diverse —
"Chrome non è aperto" contro "Chrome è aperto ma senza la porta di debug:
chiudilo del tutto e riaprilo da me". Verificato entrambi.

La verifica end-to-end è stata fatta su una **seconda istanza** di Chrome
con profilo temporaneo, per non toccare le schede e i login aperti.

### D2 resta provvisorio

**Decisione: niente OCR, per ora.** Nei tentativi fatti, UIA e Playwright
hanno trovato tutto ciò che c'era e rifiutato tutto ciò che non c'era, senza
un solo clic fuori bersaglio. Ma i bersagli erano costruiti apposta: sette
tentativi non sono un tasso di successo.

Cosa serve per chiudere D2 sul serio: qualche decina di "clicca su X" sulle
applicazioni vere di chi usa Metis. `prova_automazione.py` non serve a
questo — serve l'uso. Se emergesse una classe di applicazioni invisibili a
UIA (Electron senza accessibilità attiva è la candidata) allora OCR
diventerebbe il terzo livello, con i suoi 300 ms – 2 s.

Un dato già in mano: **Tk è invisibile a UI Automation**. Una finestra Tk
espone solo la cornice — riduci a icona, ingrandisci, chiudi — e nessuno dei
suoi widget. Scoperto costruendo il banco.

### `drag` non è stato provato a mano

È scritto, registrato con la sua guardia, e usa lo stesso risolutore di
`click_element`. Non esiste un bersaglio ovvio su cui provarlo, e nessuno
dei sei comandi di accettazione lo richiede.

---

## 7. Registro problemi

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 1 | **Il primo clic dopo l'attivazione di una finestra si perde**, 2 volte su 8 | Un "clicca sul link" su quattro non faceva niente, e il broker diceva ok | Misurato con tre condizioni × 8 ripetizioni. La pagina riceveva tutti i `mousedown` ma non li trasformava in clic: dopo un cambio di fuoco il bersaglio non ha aggiornato l'hit-testing. Due spostamenti del puntatore, in pixel **diversi**, prima di premere. 20/20 dopo |
| 2 | `SetForegroundWindow` fallisce con `GetLastError()` a **zero** anche quando la finestra viene su | pywin32 lo trasforma in eccezione, e `focus_window` dichiarava fallita un'operazione riuscita | L'esito non si chiede all'API, si guarda: si prova, si assorbe l'eccezione, poi si legge chi è davvero in primo piano |
| 3 | `focus_window` non attecchisce sulla prima chiamata a una finestra appena comparsa | Il comando composto "aprila e portala davanti" falliva sistematicamente sulla seconda metà | Fino a tre tentativi a 150 ms. Lecito qui e non sul clic: alzare due volte una finestra la lascia alzata, cliccare due volte preme due volte |
| 4 | La cavia in Tk era invisibile a UIA | Il banco dichiarava rotto un rifiuto corretto | Cavia riscritta in Qt. Il rifiuto era giusto: il difetto era nel bersaglio |
| 5 | Chrome sopravvive a `terminate()` sul processo lanciato | Alla prova successiva due finestre con lo stesso titolo, e un rifiuto per ambiguità che sembrava un difetto | Il banco chiude i Chrome **di prova**, riconosciuti dalla porta di debug. Quelli dell'utente non si toccano |
| 6 | La cavia nel processo di Metis non veniva trovata | Nessuno: era `elenca()` che scarta le finestre di Metis, cioè il comportamento voluto | Cavia in un processo suo |
| 7 | `destinazione` e `direzione` come nomi di campo | `test_nessuno_schema_accetta_un_percorso` li segnalava | Rinominati `monitor` e `verso`. Il test aveva ragione: sono parole del vocabolario dei percorsi |

---

## 8. Diario

### 2026-09-21

Otto giorni di piano in una sessione, dopo M3.

**Prima il DPI, come dice il piano.** È la riga che, se manca, fa sbagliare
tutto il resto allo stesso modo e in silenzio — e solo sul monitor
secondario, quindi invisibile a chi prova di fretta. Sta nella prima riga
utile di `metis/gui/app.py`, prima degli import di Qt, e c'è un test che
legge l'**ordine** nell'AST: una ricerca testuale troverebbe anche la
docstring che spiega la regola, ed è già successo tre volte in questo
progetto.

**La decisione che ha dato forma al resto** non era nel piano in questa
forma: il piano diceva `window_id: int`. Un intero allucinato è una finestra
vera; un titolo allucinato non è niente. Da lì sono discesi il `Literal` per
le destinazioni, `list_windows` senza id, e il rifiuto quando due finestre
corrispondono. Tutte scelte che costano una frase in più e tolgono una
classe intera di errori silenziosi.

**Il difetto che sarebbe sopravvissuto a una prova superficiale.** Il primo
clic dopo che una finestra passa in primo piano si perde, due volte su otto.
Sarebbe passato: si prova "clicca sul link", funziona, si va avanti. È
emerso perché il banco non chiede al broker se è andata bene — chiede alla
pagina. Tre condizioni, otto ripetizioni ciascuna, e la risposta è che la
pagina riceve il `mousedown` ma non lo trasforma in clic, perché dopo un
cambio di fuoco il bersaglio non ha ancora aggiornato dove sia il puntatore.
Due spostamenti invece di uno, in pixel diversi. 20/20.

La tentazione era ritentare il clic quando non ha effetto. Sarebbe stato più
semplice e molto peggio: un clic ripetuto su qualcosa che ha già funzionato
è un'azione doppia, e su "Invia" è un'azione doppia che si vede. Ritentare
va bene per alzare una finestra, che è idempotente, e infatti lì si ritenta.

**Playwright clicca meglio di me, e non lo si usa.** `locator.click()`
sarebbe più affidabile di qualunque conversione di coordinate. Non si usa
per una ragione di sicurezza: un clic sintetizzato dentro il browser non
passa dal desktop, quindi non è soggetto alla guardia sulla finestra in
primo piano. Esisterebbero due modi di cliccare, di cui uno solo
controllato. Con la conversione, ogni clic di Metis — nativo o web — è lo
stesso evento del sistema operativo, sottoposto agli stessi controlli,
rivalutati un millisecondo prima di partire.

Lo scotto è la conversione stessa: `screenX` + bordo + `devicePixelRatio`.
Funziona, ed è verificata leggendo cosa ha registrato la pagina.

**Un test ha bocciato due nomi di campo**, `destinazione` e `direzione`, per
somiglianza con il vocabolario dei percorsi. Aveva ragione: sono diventati
`monitor` e `verso`, che sono anche nomi migliori.

**Test:** 411 verdi. Banchi: 23/23 sull'automazione, 49/51 sul router.

---

## 9. Note per M5

**Quello che M4 consegna:**

- **Un assistente operativo.** Da qui Metis fa cose, non solo ne parla.
- **Lo slot di riferimento popolato.** `finestre.riferimento()` contiene la
  finestra che l'utente stava usando quando ha cominciato a parlare: è
  l'aggancio per la risoluzione anaforica di M5.
- **Playwright pronto.** `browser.pagina_attiva()` dà la scheda vera
  dell'utente; per il fetch RAG di M5 serve la stessa connessione.
- **L'audit log con azioni T2 reali**, base per NFR-9 in M7.
- **`Rifiuto`**, che M5 userà molto: "non ho trovato niente su questo" è la
  risposta normale di un sistema di ricerca, non un guasto.

**Quattro cose da non ripetere:**

1. **Non ritentare un'azione che potrebbe aver avuto effetto.** Alzare una
   finestra sì, cliccare no. La differenza è l'idempotenza, non la comodità.
2. **Non chiedere all'API se è andata bene: guardare lo stato.**
   `SetForegroundWindow` restituisce FALSE con errore zero su operazioni
   riuscite.
3. **Un banco che chiede al broker "è andata bene?" non verifica niente.**
   Deve chiedere al bersaglio. È così che è venuto fuori il clic perso.
4. **Attenzione a `has_untrusted_content`.** In M5 arriva il contenuto web,
   e la riga in `policies.py` che vieta T2 e T3 dopo un recupero comincia a
   rifiutare cose. È scritta dal primo giorno: quando comincerà a dare
   fastidio, non è un difetto.
