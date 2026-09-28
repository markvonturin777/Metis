# PHASE5 — Mani libere

> **Durata stimata:** 12 giorni · **Ramo:** `svil/phase5` · **Tag:** `p5-mani-libere`
> **Si fa dopo PHASE4** ([frasi non capite](../PHASE4/Piano_Frasi_Non_Capite.md)) **e PHASE6**
> ([qualità della conversazione](../PHASE6/Piano_Conversazione.md)), scelte dell'utente del 2026-09-28:
> il pannello di PHASE4 misurerà quanto attrito toglie questa fase, e con una Metis che capisce togliere
> il tasto vale di più.
> **Parte da:** la conversazione del 2026-09-28. L'utente non usa Metis attivamente perché è
> "clunky". Delle cinque cause proposte ha indicato **il tasto per ogni comando** ("sicuramente"),
> **le conferme solo col clic** e **le frasi troppo rigide** ("abbastanza"), meno **i numeri che
> spariscono**; la latenza di qualche secondo va bene. Usa **quasi sempre le casse**. Le email restano
> confermate col clic, tutto il resto anche a voce.
> **Riferimento normativo:** [Specifica V1.0](../PHASE0/Metis_V1.0_Specifica_Ufficiale.md), §5 (macchina a
> stati, anti-eco), §6.1 (attivazione), §8 (broker e conferme), §9.3 (T2)

---

## Obiettivo

Poter usare Metis per qualche minuto di fila **senza toccare la tastiera**: dare comandi uno dopo
l'altro, confermare a voce, dirli con parole proprie.

Il log delle sedute vere (`data/logs/metis.jsonl`, fino al 2026-09-26) dice dove si inceppa oggi:

| Cosa | Quante volte |
| :-- | --: |
| Comandi dati senza tasto, negli 8 s di ascolto dopo una risposta | 78 |
| Finestra di 8 s scaduta, poi il tasto premuto (di solito 10–20 s dopo) | 12 |
| **Tasto premuto mentre Metis ascoltava già → ascolto chiuso**, poi ripremuto 1–3 s dopo | 6 |
| Turni partiti dal rumore e finiti in una trascrizione vuota | 22 |

L'ascolto dopo la risposta **esiste già e si usa**. È troppo corto per la navigazione (si guarda la
pagina, si decide, poi si parla) e il tasto lo spegne proprio quando lo si preme per parlare
(`IN_ASCOLTO` + `PTT` → `DORMIENTE`).

Il rischio dominante è **acustico**, ed è lo stesso che ha fermato la wake word in M1: con le casse,
un microfono aperto più a lungo sente anche il PC. Nella seduta NFR-7 le casse arrivavano al microfono
a +35,4 dB sul silenzio. Un video che dice "torna indietro", "pausa" o "sì" non deve diventare un
comando né una conferma. **La fase comincia misurando questo rischio, non costruendo.**

---

## Prerequisiti

- [ ] PHASE2 chiusa (`p2-navigazione`): questa fase lavora sopra le sue frasi chiuse e i suoi numeri
- [ ] PHASE4 chiusa (`p4-frasi`): i turni di sessione ignorati diventano un segnale del suo pannello
- [ ] PHASE6 chiusa (`p6-conversazione`)
- [ ] Ramo `svil/phase5` creato dal ramo di PHASE6
- [ ] **Spike del giorno 0** fatto: le sue misure confermano le soglie di D-MANI 3, 5 e 9
- [x] Decisioni D-MANI chiuse — **tutte come da raccomandazione**, confermate dall'utente il 2026-09-28,
      compresa la facoltativa D-MANI 11

---

## Cosa c'è già

| Pezzo | Dove | Stato |
| :-- | :-- | :-- |
| Ascolto senza tasto dopo ogni risposta: `PARLATO` → `IN_ASCOLTO`, timeout 8 s | `state_machine.py` (`TIMEOUTS`), `orchestrator.py` (VAD → `SPEECH_START`) | Funziona, troppo corto |
| Il tasto in `IN_ASCOLTO` chiude l'ascolto | `orchestrator.py`, `(IN_ASCOLTO, PTT) → DORMIENTE` | È la trappola da togliere |
| Gating half-duplex: microfono sordo mentre Metis parla | `STT_MUTED` | Funziona; include `ATTESA_CONFERMA` |
| Domanda di conferma pronunciata ("… Confermo?") | `risposte.domanda_conferma` | Funziona; **contiene la parola "confermo"** |
| La conferma passa da un callable del contesto | `Context.chiedi_conferma`, oggi `ponte.chiedi` della GUI (`workers/nucleo.py`) | Funziona: il broker non sa chi risponde |
| Broker: la conferma è NO se nessuno risponde, se scade o se il meccanismo esplode | `security/broker.py`, `_conferma` | Funziona, e **non si tocca** |
| Frasi chiuse (numeri, scorrimento, media, volume, browser, video, dettatura) | `core/frasi_chiuse.py` | Funzionano, ma solo con le formule previste |
| Strumenti di PHASE2 **non offerti** al modello principale (`al_modello=False`) | `tools/registry.py`, `per_il_modello` | Scelta misurata: sette strumenti in più nel prompt degradavano il router |
| Volume di sistema con Core Audio via `comtypes` | `tools/media.py` | Funziona; il **misuratore di picco** dello stesso dispositivo non è ancora letto |
| Chiarimento con domanda fissa ("Non ho capito il numero: me lo ripete?") | `frasi_chiuse.chiarimento`, orchestratore | Funziona; a microfono aperto andrebbe ripensato (D-MANI 6) |
| Kill switch, pausa dell'ascolto dalla tray | `panic()`, tray | Funzionano, restano la via d'uscita |
| Finestra di riferimento catturata al tasto | `finestre.cattura_riferimento` | **Difetto trovato in PHASE4** (seduta del 2026-09-28): nei turni senza tasto resta quella di prima, anche chiusa → "quella finestra non c'è più" quattro volte di fila. Con la sessione diventerebbe la norma: va ricatturata a ogni turno (giorni 1–2) |

---

## Decisioni (gate D-MANI)

> ✅ **Chiuse il 2026-09-28**: l'utente conferma tutte le raccomandazioni, compresa D-MANI 11 (che quindi
> entra nella fase, come opzione spenta di default). Sul rischio acustico l'utente osserva che lo Yeti è
> in cardioide, rivolto dalla parte opposta alle casse. È lo stesso assetto della seduta NFR-7 di M1
> (`M0_tracking.md`: "Blue Yeti Classic, cardioide, altoparlanti del monitor"), che misurò +35,4 dB di
> casse nel microfono: lo spike resta, per confermare le soglie.

| # | Domanda | Raccomandazione | Perché |
| :-- | :-- | :-- | :-- |
| **D-MANI 1** | Come si apre e si chiude la **sessione di ascolto**? | Si apre con il tasto o dopo ogni risposta, come oggi. Dura **45 s dall'ultimo comando** (in `config/ascolto.toml`), e ogni comando la rinnova. Si chiude con il timeout, con "basta così" / "grazie Metis" / "a posto così", con la pausa della tray o con il kill switch | Il tempo di guardare una pagina e decidere. Un limite dall'ultimo comando, non dall'apertura: finché si usa resta aperta, e appena si smette si chiude da sola |
| **D-MANI 2** | Cosa fa il **tasto** durante una sessione? | **"Sto per parlare"**: la sessione resta aperta e il timeout riparte. Non la chiude più | È la trappola misurata: sei volte il tasto ha spento l'ascolto un attimo prima che l'utente parlasse. Per chiudere ci sono la voce, il timeout e la tray |
| **D-MANI 3** | Cosa si accetta **senza tasto**? | Frasi chiuse e router di navigazione (D-MANI 4) **sempre**; conversazione e router principale **solo se non c'è audio in uscita dal PC**, oppure se la frase comincia con "Metis". Numeri definitivi dopo lo spike | Il testo di un video, trascritto, non deve arrivare al modello libero. Le frasi chiuse e il router di navigazione possono solo scorrere, cliccare numeri detti, cambiare volume o scheda: T1 e T2 con le guardie di sempre, nessun T3. "Metis" all'inizio è una wake word *nel testo*: la decide Whisper, dopo la trascrizione, e non il rilevatore acustico di M1 |
| **D-MANI 4** | Come si rendono **meno rigide** le frasi? | Un **secondo router, piccolo**: un prompt corto con i soli strumenti di navigazione e media, chiamato quando frasi chiuse e comandi non riconoscono la frase e questa usa il lessico della navigazione (pagina, scheda, video, musica, volume, scorri, numero…) | Il prompt principale resta com'è, e con lui i 165/165 del banco. Il router piccolo ha pochi strumenti e una sola domanda da risolvere; costa qualche centinaio di millisecondi, e l'utente accetta un po' di latenza. Valgono gli stessi controlli nel codice: verbo presente, numero e testo detti |
| **D-MANI 5** | Come si difende la sessione dall'**audio del PC** (casse)? | Tre livelli, da confermare con lo spike: **(a)** senza tasto, frasi chiuse solo se sono **l'intero enunciato** (al più due parole di cortesia), non contenute in una frase più lunga; **(b)** con audio in uscita (misuratore di picco del dispositivo di riproduzione), solo frasi chiuse e router di navigazione, il resto chiede "Metis" all'inizio; **(c)** gli enunciati non riconosciuti **tacciono** | Un "torna indietro" dentro la frase di un video non è un enunciato intero. Il picco di Core Audio distingue "c'è musica" da "silenzio" senza un AEC. Il terzo livello evita che Metis risponda a ogni frase della televisione |
| **D-MANI 6** | Chiarimenti e "non ho capito" a microfono aperto? | **Solo con il tasto.** Un turno senza tasto che nessuno capisce **non parla**: si segna nel log (sarà una frase debole per PHASE4) e il nucleo fa un piccolo segno visivo | A microfono aperto il rumore produce turni (22 nel log). Un "me lo ripete?" a ogni rumore è peggio del silenzio |
| **D-MANI 7** | **Conferme a voce**: per cosa? | ✅ **Per tutto tranne le email** (`send_email`, `schedule_email`), che restano col clic. Scelta dell'utente del 2026-09-28. Valgono quindi a voce: clic sensibili, Invio nei campi, date dei promemoria, **dispositivi di Home Assistant**. Elenco delle eccezioni in `config/ascolto.toml` → `[conferma_vocale] solo_clic` | Le email sono l'unica azione che esce davvero dal PC e non si richiama. I dispositivi di casa sono T3 anch'essi: sono dentro per scelta esplicita dell'utente, e l'elenco li può aggiungere con una riga |
| **D-MANI 8** | Quali parole valgono come risposta? | **Sì**: "sì", "sì grazie", "vai", "procedi", "conferma", "confermo", "ok". **No**: "no", "annulla", "lascia stare", "fermo", "stop". **Solo come enunciato intero**, riconosciute senza modello. Qualunque altra cosa = nessuna risposta, e resta la finestra | Una frase chiusa, come "clicca il N". Enunciato intero perché "no, sì, fai pure" non è un sì. Ciò che non si capisce non conta né come sì né come no: decide la finestra o il timeout, che dice no |
| **D-MANI 9** | Come si evita che la **domanda confermi se stessa**? | La domanda **non contiene nessuna parola di D-MANI 8**: "Il 3 è Condividi. Lo clicco?", "Promemoria per domani alle 17. Lo imposto?", verificato da un test su tutte le domande. Il microfono si apre solo **a riproduzione finita, più una coda di 300 ms** | Con le casse l'eco della domanda arriva al microfono. Oggi la domanda finisce con "Confermo?": con il microfono aperto, l'eco sarebbe una conferma. Il test lo impedisce per costruzione, non per fortuna |
| **D-MANI 10** | E con l'audio del PC durante una conferma? | Con audio in uscita, la conferma a voce di un **T3** (i dispositivi) vuole **il tasto premuto**; per i clic sensibili e l'Invio basta la voce | Un "sì" isolato in un video è raro, ma non impossibile: su un'azione fisica non si scommette |
| **D-MANI 11** | Numeri che restano (**facoltativo**)? | Un'opzione, spenta di default: nella sessione, dopo un clic o uno scorrimento i numeri **si rimostrano da soli** quando la pagina si ferma (~800 ms) | L'utente la sente meno delle altre. È un `mostra_numeri` T0 ripetuto: nessun rischio nuovo, ma rumore visivo che non tutti vogliono |
| **D-MANI 12** | Si vede che il microfono è aperto? | **Sì, sempre**: anello del nucleo (Hub e Minimal) con il tempo che resta, e un suono breve e discreto all'apertura e alla chiusura della sessione (disattivabile) | Un microfono aperto che non si vede è un problema di fiducia prima che di sicurezza |

---

## Il disegno

### 1. La sessione

```
        tasto, o fine di una risposta
DORMIENTE ─────────────────────────────► IN_ASCOLTO  (sessione, 45 s dall'ultimo comando)
    ▲                                        │   ▲
    │  timeout · "basta così" · tray · kill  │   │  tasto = "sto per parlare": il tempo riparte
    └────────────────────────────────────────┘   │
                                             VAD │
                                                 ▼
                                   TRASCRIZIONE → ELABORAZIONE → … → PARLATO ─┐
                                                                               │
                                        la sessione continua, il tempo riparte ◄┘
```

Nessuno stato nuovo: la sessione è il timeout di `IN_ASCOLTO` reso configurabile, più la
transizione `(IN_ASCOLTO, PTT)` che resta in `IN_ASCOLTO` (con il timer azzerato) invece di andare a
`DORMIENTE`. I test di integrità della tabella (nessuno stato irraggiungibile, nessun vicolo cieco)
restano verdi: `DORMIENTE` si raggiunge con il timeout, la voce e la tray.

### 2. Il turno senza tasto

```
enunciato arrivato senza tasto
   │
   ├─ "basta così" …                     → chiude la sessione
   ├─ frase chiusa, enunciato INTERO     → azione (T1/T2, guardie di sempre)
   ├─ comando dell'utente, intero        → azione
   ├─ lessico di navigazione             → router piccolo → azione, o silenzio
   ├─ audio in uscita?  sì → comincia con "Metis"? no → silenzio (log)
   │                    no ─┐                     sì ─┐
   │                        ▼                         ▼
   │                   router principale / conversazione, come col tasto
   └─ nessuno lo capisce → silenzio + segno visivo (log per PHASE4)
```

Col tasto premuto, il turno è quello di oggi: tutto passa, e chi non capisce chiede.

### 3. La conferma a voce

```
ESECUZIONE ─► ATTESA_CONFERMA
                 │  la finestra si apre (come oggi)
                 │  Metis dice: "Il 3 è Condividi. Lo clicco?"   ← nessuna parola di risposta dentro
                 │  riproduzione finita + 300 ms → microfono aperto
                 │
                 ├─ "sì" / "vai" / "procedi" (enunciato intero)  ─┐
                 ├─ clic su Approva                              ─┼─► il primo che arriva decide,
                 ├─ "no" / "annulla"  · clic su Nega             ─┘   la finestra si chiude
                 └─ 20 s senza risposta                            ─► NO (broker, come oggi)

email: la voce non vale, solo la finestra (D-MANI 7)
T3 con audio in uscita: la voce vale solo col tasto premuto (D-MANI 10)
```

**Il broker non cambia.** Cambia solo il callable `chiedi_conferma` che la GUI gli passa: oggi apre la
finestra e aspetta il clic, domani aspetta il clic **o** la risposta vocale, e chiude la finestra
quando decide la voce. Le proprietà di M2 restano: nel dubbio è no, e il timeout è quello del broker.

### 4. Il router piccolo

Un secondo `ToolCallRouter` con un prompt suo di poche righe e il registro ristretto agli strumenti di
navigazione e media (`scroll`, `clicca_numero`, `mostra_numeri`, `nascondi_numeri`,
`tasto_multimediale`, `cambia_volume`, `set_volume`, `imposta_muto`, `comando_video`, `press_hotkey`
delle schede). Nessun T3, nessun `open_application`, nessun `web_search`. Stessa temperatura (0,15),
stesso schema JSON, stessi controlli a valle: numero detto, testo detto, verbo presente.

---

## Scelte tecniche

### Il misuratore di picco

`IAudioMeterInformation::GetPeakValue` sul dispositivo di riproduzione predefinito, con le stesse
interfacce `comtypes` di `tools/media.py`: nessuna dipendenza nuova. Si legge al momento del turno,
non in continuo. Il picco comprende anche la voce di Metis, ma in `IN_ASCOLTO` Metis non parla: quello
che si misura è l'audio degli altri programmi. La soglia si decide sullo spike.

### Il microfono in ATTESA_CONFERMA

Oggi `ATTESA_CONFERMA` sta in `STT_MUTED` perché Metis vi pronuncia la domanda. Diventa: sordo mentre
il player riproduce e per 300 ms dopo, aperto poi. Il segmento che arriva va a Whisper e al solo
riconoscitore delle risposte (D-MANI 8), mai al router né alla conversazione.

### "Enunciato intero"

`frasi_chiuse.riconosci` oggi riconosce una frase anche con parole attorno (le cortesie). Per i turni
senza tasto riceve un parametro in più: le parole oltre la frase riconosciuta, cortesie escluse,
devono essere zero. Col tasto il comportamento non cambia.

### Lo spike usa il sistema vero, in prova a secco

`benchmarks/spike_mani_libere.py`: Metis con la sessione forzata sempre aperta, YouTube che suona
dalle casse al volume d'uso, e **nessuna azione eseguita**. Per ogni enunciato si registrano la
trascrizione, il picco dell'audio in uscita e cosa avrebbe deciso ogni livello di D-MANI 5. È lo
stesso principio del soak di M7: sistema vero, effetti spenti.

---

## Deliverable

| # | Componente | File |
| :-- | :-- | :-- |
| 0 | Spike: audio del PC a microfono aperto, prova a secco | `benchmarks/spike_mani_libere.py` |
| 1 | Sessione di ascolto, tasto "sto per parlare", chiusura a voce | `metis/core/state_machine.py`, `metis/core/orchestrator.py`, `config/ascolto.toml` |
| 2 | Turni senza tasto: enunciato intero, filtri di D-MANI 3 e 5, silenzio | `metis/core/router.py`, `metis/core/frasi_chiuse.py`, `metis/core/orchestrator.py` |
| 3 | Misuratore di picco dell'audio in uscita | `metis/tools/media.py` (o `metis/audio/uscita.py`) |
| 4 | Router di navigazione | `metis/llm/toolcall.py`, `metis/llm/prompts/navigazione_v1.txt` |
| 5 | Conferma a voce: domande riscritte, microfono dopo la domanda, risposte chiuse | `metis/core/risposte.py`, `metis/core/state_machine.py`, `metis/gui/workers/nucleo.py` (`chiedi_conferma`) |
| 6 | Anello della sessione nel nucleo, suono di apertura e chiusura | `metis/gui/widgets/nucleo.py`, Minimal |
| 7 | Numeri che restano (opzione, D-MANI 11) | `metis/tools/numeri.py`, Impostazioni |
| 8 | Specifica §5, §6.1, §8.3; `docs/INSTALL.md`; `FEATURES.md` | documenti |

---

## Step operativi

### Giorno 0 — Spike: quanto sente il microfono del PC

1. `spike_mani_libere.py` in prova a secco, **20 minuti** con un video parlato (notiziario, intervista)
   dalle casse al volume d'uso. Ridotto dai 90 minuti iniziali per scelta dell'utente (2026-09-28): le
   difese sono comunque nel codice, lo spike conferma le soglie. Se in 20 minuti compare anche una sola
   azione fantasma, si torna alla versione lunga (video musicale e silenzio in stanza, 30 minuti l'uno).
2. Per ogni enunciato: trascrizione, picco in uscita, e decisione di ciascun livello (nessun filtro;
   solo frasi chiuse; frasi chiuse intere; con "Metis" richiesto sotto audio).
3. Una misura sull'eco di Metis: 20 domande di conferma riprodotte con il microfono aperto a 0, 150,
   300 e 500 ms dalla fine. Cosa arriva a Whisper?

**Uscita:** una tabella "azioni fantasma per livello" e la soglia del picco. Il criterio è **0 azioni
fantasma in 20 minuti** con il livello scelto; le soglie di D-MANI 3, 5 e 9 si fissano su questi numeri.

### Giorni 1–2 — La sessione

1. `config/ascolto.toml`: durata della sessione, frasi di chiusura, suoni, eccezioni della conferma a
   voce.
2. Timeout di `IN_ASCOLTO` dalla configurazione; rinnovo a ogni comando riuscito.
3. `(IN_ASCOLTO, PTT)`: resta in ascolto e azzera il timer. Il test di M1 che si aspettava `DORMIENTE`
   cambia di proposito; i test di integrità della tabella restano verdi.
4. Chiusura a voce ("basta così", "grazie Metis", "a posto così") nel percorso rapido.
5. Test: sessione che si rinnova, che scade, che si chiude a voce, dalla tray, col kill switch; il tasto
   durante la sessione non la chiude più (il caso del log).

### Giorni 3–4 — I turni senza tasto

1. Il turno sa se è partito dal tasto o dal VAD (`origine`: `tasto` / `sessione`).
2. Enunciato intero per le frasi chiuse e i comandi, solo per i turni di sessione.
3. Misuratore di picco; filtro di D-MANI 3 e 5; "Metis" all'inizio tolto prima del router.
4. Silenzio per i turni di sessione non capiti, segno visivo nel nucleo, `extra["sessione_ignorato"]`
   con il motivo.
5. Test con enunciati costruiti: "torna indietro" dentro una frase lunga non scatta; "torna indietro"
   da solo sì; con audio in uscita una domanda libera senza "Metis" tace, con "Metis" passa.

### Giorni 5–6 — Il router di navigazione

1. Registro ristretto e prompt `navigazione_v1.txt`, da scrivere con esempi diversi da quelli del banco
   (la lezione di PHASE1, problema #13).
2. Quando si chiama: dopo frasi chiuse e comandi, prima del router principale, solo se la frase usa il
   lessico della navigazione.
3. **Banco nuovo** (`benchmarks/prova_navigazione.py`): 40 formulazioni libere ("abbassa un pelo la
   musica", "vai giù", "metti in pausa 'sto video", "torna alla scheda di prima") e 20 frasi che **non**
   sono navigazione, che devono andare altrove. 3 giri.
4. **Tutti i banchi del modello rilanciati insieme**: router principale (165/165 da tenere), anafora,
   injection, integrazioni.

### Giorni 7–9 — La conferma a voce

1. Domande riscritte senza parole di risposta; test su ogni ramo di `domanda_conferma` (clic sensibile,
   Invio, promemoria, email, dispositivi).
2. Microfono in `ATTESA_CONFERMA` dopo la riproduzione più la coda (misurata nello spike).
3. Riconoscitore delle risposte: enunciato intero, sì e no, niente modello.
4. `chiedi_conferma` della GUI: la finestra **o** la voce, la prima che arriva; la finestra si chiude
   quando decide la voce; email solo finestra; T3 con audio in uscita solo con il tasto.
5. Test: sì, no, frase non capita (resta la finestra), timeout (no), kill switch a finestra aperta,
   email a cui si dice "sì" (non parte), "no, sì, vai pure" (non è un sì), eco della domanda (nessuna
   conferma). **NFR-9 esteso**: 0 T3 e 0 clic sensibili non confermati, **e 0 email confermate a voce**,
   verificato con una query sull'audit.
6. L'audit registra **come** è arrivata la conferma (`clic` / `voce`).

### Giorno 10 — Interfaccia

1. Anello della sessione nel nucleo e nella Minimal, con il tempo che resta; segno del turno ignorato.
2. Suoni di apertura e chiusura (brevi, disattivabili dalle Impostazioni).
3. Opzione "numeri che restano" (D-MANI 11), spenta di default, attivabile dalle Impostazioni.
4. Catture con dati finti (`benchmarks/gui_screenshot.py --sessione`), da rivedere con l'utente.

### Giorno 11 — Prova vera

1. Dieci minuti di navigazione senza tastiera, con le casse e un video che suona: YouTube, un
   quotidiano, Facebook. Si contano i comandi riusciti, quelli ripetuti, le azioni fantasma (devono
   essere 0) e le volte in cui è servito il tasto.
2. Cinque conferme a voce (clic sensibile, Invio, promemoria) e una email (deve chiedere il clic).
3. NFR-1 e NFR-8 non peggiorano; soak breve di M7 con la sessione sempre attiva (CPU del VAD, memoria).

### Giorno 12 — Chiusura

Specifica §5 (la sessione, il tasto), §6.1 (attivazione: tasto più sessione), §8.3 (conferma a voce e
sue eccezioni); `docs/INSTALL.md` (`ascolto.toml`, come si usa senza mani); `FEATURES.md`; bundle
rigenerato e riprovato; tag.

---

## Criteri di uscita

- [ ] Spike fatto: **0 azioni fantasma in 20 minuti** di audio del PC con il livello scelto, soglie scritte nel tracking
- [ ] La sessione dura 45 s dall'ultimo comando, si rinnova, si chiude a voce, dalla tray, col kill switch
- [ ] Il tasto durante la sessione non chiude l'ascolto (il caso misurato nel log)
- [ ] Senza tasto: frasi chiuse solo come enunciato intero; con audio in uscita il modello libero solo con "Metis"; i turni non capiti tacciono
- [ ] Router di navigazione: banco nuovo verde a 3 giri; **router principale ancora 165/165**, anafora, injection e integrazioni verdi
- [ ] Nessuna domanda di conferma contiene una parola di risposta (test)
- [ ] Conferma a voce per clic sensibili, Invio, promemoria, dispositivi; **email solo col clic**; T3 con audio in uscita solo col tasto
- [ ] **NFR-9 esteso**: 0 T3 e 0 clic sensibili non confermati, 0 email confermate a voce (query sull'audit)
- [ ] L'eco della domanda non conferma mai (spike e test)
- [ ] Anello della sessione visibile nell'Hub e nella Minimal; catture riviste dall'utente
- [ ] Prova vera: dieci minuti senza tastiera, con le casse, 0 azioni fantasma
- [ ] NFR-1, NFR-8 non peggiorano; soak breve senza crescita di memoria
- [ ] Specifica, `docs/INSTALL.md`, `FEATURES.md`, bundle aggiornati
- [ ] `git tag p5-mani-libere`

---

## Fuori ambito

| Cosa | Perché |
| :-- | :-- |
| Wake word acustica ("Hey Metis" con openWakeWord) | Resta v2 (D1). Qui "Metis" all'inizio è riconosciuto nel testo trascritto, e solo per sbloccare il modello libero sotto audio |
| AEC vero | D3 resta aperta. Lo spike dirà se i tre livelli bastano; se no, l'AEC torna in discussione con numeri nuovi |
| Ascolto sempre attivo, senza sessione | La sessione si chiude da sola apposta: un microfono aperto per ore con le casse è la seduta NFR-7 |
| Conferme a voce per le email | Scelta dell'utente (D-MANI 7) |
| Strumenti di navigazione nel prompt principale | Misurato in PHASE2: degradano il router. Vanno nel router piccolo |
| Riconoscimento di chi parla (verifica del parlante) | Un modello in più sulla CPU; si rivaluta se lo spike mostra voci umane in stanza come problema |
| Navigazione autonoma a più passi | Invariato da PHASE2: un agente che legge le pagine e decide |

---

## Rischi e contromisure

| Rischio | Effetto | Contromisura |
| :-- | :-- | :-- |
| **Un video diventa un comando** | Pausa, indietro, clic non voluti | Spike prima di tutto; enunciato intero; con audio in uscita niente modello libero senza "Metis"; nessun T3 dai turni di sessione |
| **L'eco della domanda conferma da sola** | Un clic sensibile o un dispositivo confermato da Metis stessa | Nessuna parola di risposta nelle domande (test); microfono dopo la riproduzione più la coda; misura nello spike |
| Un "sì" nel video durante una conferma | Conferma non voluta | Enunciato intero; T3 con audio in uscita solo col tasto; le email mai a voce |
| Il router piccolo sbaglia strumento | Volume invece di scorrimento, scheda sbagliata | Solo T1/T2 reversibili; controlli nel codice; banco dedicato a 3 giri |
| Il router piccolo sposta il principale | Regressioni in M4–M6 | Due prompt separati; tutti i banchi rilanciati insieme |
| Metis risponde alla televisione | Voce a ogni rumore | I turni di sessione non capiti tacciono (D-MANI 6) |
| Sessione aperta senza accorgersene | Perdita di fiducia | Anello visibile, suoni di apertura e chiusura, chiusura da sola a 45 s |
| Voci umane in stanza (altre persone) | Comandi dati da altri | Stesse difese dell'audio del PC; misura nella prova vera; verifica del parlante nel backlog se serve |
| VAD e Whisper più attivi | CPU e GPU sotto carico con un video che suona | Soak breve con la sessione sempre aperta; il VAD gira già sempre, cambia solo quante trascrizioni partono |

---

## Handoff

Alla fine di PHASE5 Metis si usa per minuti di fila senza tastiera:

- una sessione di ascolto che si rinnova a ogni comando e si chiude da sola;
- il tasto che non spegne più l'ascolto quando lo si preme per parlare;
- conferme a voce per tutto tranne le email, con la domanda che non può confermare se stessa;
- frasi di navigazione dette con parole proprie, grazie a un router piccolo che non tocca il principale;
- una misura delle azioni fantasma con le casse, che dirà anche se la wake word (D1) e l'AEC (D3)
  valgono la pena in v2.

Il pannello di PHASE4, già in piedi, dice quanto attrito questa fase ha tolto: la quota dei turni non
capiti prima e dopo.
