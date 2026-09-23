# M6 — Integrazioni · Tracking

| | |
| :-- | :-- |
| **Stato** | 🔄 Codice completo — verifiche sui servizi veri aperte |
| **Piano** | [M6_Integrazioni.md](../SPECS/plan/M6_Integrazioni.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | 2026-09-23 |
| **Fine** | — |
| **Tag** | `m6-integrations` — non ancora: vedi §6 |

**Avanzamento:** `███████████████████░` 94% — attività 32/34 · criteri di uscita 9/15

Tutto cio' che si poteva verificare senza Home Assistant, senza un account SMTP
e senza spegnere il PC e' verificato. Restano aperti i sei criteri che
chiedono proprio quelle tre cose — sono elencati in §6, con il comando per
chiuderli.

> **Obiettivo:** far agire Metis nel tempo e nel mondo fisico.
> **Esito:** 90/90 decisioni di Qwen corrette su date, email e dispositivi (5 giri); 15/15 effetti contro servizi locali; il promemoria sopravvive a un processo che muore e scatta al riavvio; 0 azioni T3 non confermate.

---

## 1. Prerequisiti

- [x] M5 chiuso, **difese contro prompt injection verificate** — rimisurate dopo le modifiche al router: 0/18
- [x] Conferma T3 funzionante in GUI
- [ ] Home Assistant installato e raggiungibile — ⛔ **non disponibile** (2026-09-23)
- [ ] Account SMTP con password per app — ⛔ **non disponibile** (2026-09-23)

Gli ultimi due mancano per scelta, non per difetto: si e' deciso di costruire
tutto e provarlo contro un Home Assistant e un server SMTP **finti ma veri** —
un server WebSocket che parla il protocollo di Home Assistant, e un server
SMTP locale cifrato con un certificato di prova — e di lasciare aperti i
criteri che chiedono i servizi reali.

---

## 2. Attività

### Giorno 1 — Segreti

- [x] `metis/core/secrets.py` con `keyring`
- [x] **Nessun default, nessun fallback silenzioso:** chiave mancante → eccezione
- [x] `scripts/setup_secrets.py` scritto
- [ ] Credenziali SMTP salvate nel Credential Manager — da fare con lo script, serve l'account
- [ ] Token Home Assistant salvato — idem
- [x] `git grep -iE "password|token|api[_-]?key"` non restituisce valori reali — **reso un test**, gira a ogni esecuzione

### Giorni 2–3 — Scheduler

- [x] `SQLAlchemyJobStore` su `data/jobs.db`
- [x] `misfire_grace_time` e `coalesce = True` — **con uno scostamento**: §2-bis
- [x] `schedule_reminder` (T1) — con conferma della data comunque: §2-bis
- [x] `schedule_email` (T3, conferma **alla creazione**)
- [x] `list_reminders` (T0)
- [x] `cancel_reminder` (T1) — per parole del testo, non per id
- [x] Parsing date italiane via LLM con schema Pydantic — **con calendario nel prompt**: §4.1
- [x] Validazione: data nel futuro ed entro 1 anno
- [x] **Conferma vocale dell'interpretazione** della data

### Giorno 4 — Email e notifiche

- [x] `send_email` (T3) con `SMTP_SSL` — e STARTTLS sulla 587; mai in chiaro
- [x] `config/email.toml` con allowlist destinatari
- [x] Conferma mostra il corpo **completo**, non un riassunto
- [x] Audit log con destinatario e oggetto, corpo troncato
- [x] Notifiche desktop con `win11toast` — **mai viste sul desktop**: sono disattivate in Windows su questa macchina, §6
- [x] Promemoria scaduto → notifica + annuncio vocale
- [x] **Promemoria accodato** se lo stato non è `DORMIENTE`

### Giorni 5–6 — Home Assistant

- [x] Client WebSocket con long-lived token
- [x] Sottoscrizione a `state_changed`, cache locale degli stati
- [x] `config/home_assistant.toml` con tier **per entità** — che puo' solo restringere: §2-bis
- [x] `get_home_state` (T0)
- [x] `list_home_devices` (T0)
- [x] `set_home_device` (T3)
- [x] Guardia `max_durata_min` sulla friggitrice — spegnimento come job **persistente**, che riprova se l'hub e' giu'
- [x] Guardia `max_erogazioni_giorno` sul distributore crocchette — conteggio su SQLite, sopravvive al riavvio
- [x] Riconnessione automatica con backoff
- [x] Stato "non disponibile" dichiarato, mai stato memorizzato spacciato per attuale

### Giorno 7 — AEC (solo se D3 lo richiede)

- [x] **D3 deciso prima di iniziare** — escluso, §3
- [x] Step saltato, tempo spostato su M7

---

## 2-bis. Scostamenti dal piano

### Oltre l'ora di tolleranza, il promemoria arriva lo stesso

Il piano fissa `misfire_grace_time = 3600`. Provato: un promemoria scaduto
da **due ore** alla riaccensione viene scartato da APScheduler con una riga
di log, e basta. E' il rischio che il piano stesso elenca — *"scadono
silenziosamente"* — spostato un'ora piu' in la'.

Adesso APScheduler non scarta mai (`misfire_grace_time = None`) e l'ora di
tolleranza diventa la soglia fra **in orario** e **in ritardo**, giudicata da
Metis:

| Scaduto a PC spento da… | Promemoria | Email programmata |
| :-- | :-- | :-- |
| meno di un'ora | scatta normalmente | parte normalmente |
| **piu' di un'ora** | scatta **dicendo per quando era** | **non parte**: lo dice, e l'utente decide |

L'email in ritardo non parte perche' l'utente ha confermato l'invio alle 9,
non alle 14: "ricordati la riunione delle 10" spedito a mezzogiorno e' un
altro messaggio.

### La conferma si chiede anche sotto T3

`schedule_reminder` e' T1 — reversibile, si cancella con una frase — ma il
piano vuole che l'interpretazione della data sia confermata **sempre**. Il
broker aveva la conferma legata al tier; ora `ToolSpec.conferma` la puo'
**aggiungere** sotto T3. E' un `or`: non esiste un modo di toglierla a un T3.
La finestra di conferma dice "NON si annulla" solo quando e' vero.

### Il tier non si abbassa da `home_assistant.toml`

Il piano immaginava un tier per entita' (la luce T1, la friggitrice T3). Il
tier pero' e' una proprieta' dello strumento verificata dal broker, e un file
di configurazione che potesse abbassarlo toglierebbe una conferma scrivendo
una riga. Qui leggere e' T0 e accendere/spegnere e' T3 per ogni dispositivo;
il file puo' solo **restringere** (sola lettura, limiti). Un `tier = "T1"`
nel file viene ignorato con un avviso all'avvio.

### Il modello non nomina mai un `entity_id`

Nomina un dispositivo per nome, e il nome si risolve solo contro il file di
configurazione. Il finto Home Assistant dei test espone apposta
`lock.porta_ingresso`: il client la vede, nessuno strumento puo' toccarla.
Senza questa scelta il perimetro di Metis sarebbe quello di Home Assistant.

### `posta.py` e non `email.py`

Un modulo `email` dentro un pacchetto e' a un `sys.path` sbagliato
dall'oscurare il modulo `email` della libreria standard, quello che
`smtplib` usa. Il sintomo sarebbe un `ImportError` dentro `smtplib`.

### "Mandami" ha bisogno di sapere chi e' "me"

Il comando di prova n. 2 del piano e' *"**mandami** una mail"*. Il modello
non conosce l'indirizzo dell'utente, e inventarlo e' cio' che la guardia
sull'allowlist rifiuterebbe. `email.toml` ha una sezione `[utente]` letta dal
router. Non autorizza: l'indirizzo deve stare anche nell'allowlist.

### Lo spegnimento di sicurezza non chiede conferma, ed e' registrato T1

E' l'unica azione che Metis fa da solo su un dispositivo, e riduce il rischio
invece di aumentarlo: chiedere "posso spegnere la friggitrice accesa da
un'ora?" a un utente che non c'e' vorrebbe dire lasciarla accesa. Nell'audit
e' T1 e non T3 non confermata, perche' NFR-9 conta le azioni **rischiose**
partite senza consenso, e questa non lo e'.

### `ATTESA_CONFERMA` e' entrata in `STT_MUTED`

Da M6 Metis pronuncia la domanda di conferma mentre la finestra e' aperta. La
regola scritta in M5 — *se in uno stato esce audio, lo stato sta in
`STT_MUTED`* — si applica senza eccezioni.

---

## 3. Decision gate D3

| Situazione | Azione | Scelta |
| :-- | :-- | :-: |
| Si usano le **cuffie** | Saltare l'AEC interamente | — |
| Si usano gli **altoparlanti** | Implementare L3 | — |
| **Wake word rimandata alla v2** | **Escludere l'AEC in V1.0, decidere insieme alla wake word** | ✅ |

**Decisione:** AEC **escluso dalla V1.0**. **Data:** 2026-09-23.

La tabella del piano presupponeva la wake word. Con D1 rimandata alla v2, il
barge-in passa dal push-to-talk, che funziona gia' con gli altoparlanti: l'AEC
servirebbe solo a interrompere Metis *parlando*, cioe' alla wake word. Si
decide con lei, in v2, quando ci sara' di nuovo qualcosa da interrompere a
voce. Il giorno risparmiato va a M7.

### 3.1 Se l'AEC è implementato

Non applicabile in V1.0.

---

## 4. Misure

### 4.1 Le date: Qwen, al minuto — `benchmarks/prova_integrazioni.py`

"Adesso" fissato a mercoledi' 23 settembre 2026, ore 21:40. Una data "quasi
giusta" e' sbagliata.

| Frase | Attesa | Solo [ADESSO] | + calendario | + intervalli (finale) |
| :-- | :-- | :-: | :-: | :-: |
| "domani alle 17" | 24/09 17:00 | ✅ | ✅ | ✅ 5/5 |
| "fra due ore" | 23/09 23:40 | ✅ | ❌ **30/09** | ✅ 5/5 |
| "tra mezz'ora" | 23/09 22:10 | ❌ 22:40 | ✅/❌ | ✅ 5/5 |
| "lunedì mattina" | 28/09 09:00 | ❌ **sabato 26** | ✅ | ✅ 5/5 |
| "venerdì alle otto e mezza di sera" | 25/09 20:30 | ❌ **giovedì 24** | ✅ | ✅ 5/5 |
| "il 3 ottobre alle 10" | 03/10 10:00 | ✅ | ✅ | ✅ 5/5 |
| "dopodomani alle nove" | 25/09 09:00 | ✅ | ✅ | ✅ 5/5 |

**Il modello sa leggere, non sa fare l'aritmetica dei giorni.** Con la sola
data di oggi sbagliava 3 date su 7, tutte e tre dentro la guardia (nel
futuro, entro un anno): l'unica rete sarebbe stata l'utente che sente
"sabato" nella domanda di conferma. La correzione non e' stata insistere nel
prompt ma togliergli il calcolo: il prompt del router porta il calendario dei
prossimi sette giorni e gli intervalli piu' comuni gia' risolti, e il modello
**copia**.

Il passaggio intermedio e' istruttivo: il primo calendario elencava i sette
giorni *dopo* oggi, e di mercoledi' "fra due ore" e' diventato **mercoledi'
prossimo** — il modello ha cercato "mercoledi'" e l'ha trovato. Correggere un
errore di calcolo ne aveva introdotto uno di lettura.

Costo: ~500 token stimati nel prompt del **router** — chiamata separata, non
tocca il budget di 8k della conversazione. Latenza del router: mediana
607 ms, invariata.

### 4.2 Decisione ed effetto, quadro completo — 5 giri

| Metà | Risultato |
| :-- | :-- |
| Decisione (Qwen): 18 frasi × 5 giri | **90/90** |
| Effetto (broker, conferma automatica, servizi locali) | **15/15** |
| Latenza router | mediana 615 ms, max 1175 ms |
| T3 non confermate nell'audit (NFR-9) | **0** |

I casi 6 e 7 del piano, contro Home Assistant finto:

| # | Caso | Esito |
| :-- | :-- | :-- |
| 6 | Crocchette ×4 | ok, ok, ok, **rifiuto**: *"oggi e' gia' stato attivato 3 volte, il limite e' 3"* |
| 7 | Hub spento → "accendi la friggitrice" | *"L'hub domotico non risponde. Provo a riconnettermi"* — **prima** della conferma |
| 7 | Hub spento → "e' accesa?" | Stesso rifiuto: **nessuno stato memorizzato** |

### 4.3 Nessuna regressione sui router precedenti

Il prompt del router e' cresciuto di molto. Ogni banco rilanciato dopo
ciascuna modifica:

| Banco | Prima di M6 | Dopo M6 |
| :-- | :-: | :-: |
| M4 — `prova_router.py`, 17 frasi × 3 | 49/51 | **51/51** |
| M5 — `prova_anafora.py`, 4 casi × 3 | 12/12 | **12/12** |
| M5 — `prova_injection.py`, 6 payload × 3 | 0/18 ostili | **0/18** ostili |

Due regressioni sono comparse lungo la strada e sono state chiuse (§7,
problemi 6 e 7). "L'editor di codice", l'incertezza nota da M4, adesso e'
3/3: una riga che descrive le tre chiavi dell'allowlist.

### 4.4 Il riavvio — `benchmarks/prova_riavvio.py`, due processi

| Caso | Atteso | Esito |
| :-- | :-- | :-: |
| Promemoria per domani | resta in coda | ✅ |
| Scaduto 3 s fa, nessun processo vivo | scatta alla riapertura, in orario | ✅ |
| Scaduto 2 ore fa | scatta **in ritardo**, dicendolo | ✅ |
| Email scaduta 2 ore fa | arriva alla consegna come in ritardo, **non parte** | ✅ |
| Errori nel log del secondo processo | 0 | ✅ |

Due processi che non condividono niente se non `jobs.db`. E' il passo
intermedio: il riavvio vero del PC resta aperto, §6.

### 4.5 La posta — server SMTP locale, cifrato

| Verifica | Esito |
| :-- | :-- |
| SSL implicito: cifrato, autenticato, messaggio intero dall'altra parte | ✅ |
| STARTTLS sulla 587: cifrato | ✅ |
| **Verifica del certificato accesa**: senza la CA di prova l'invio fallisce | ✅ |
| Destinatario fuori allowlist: nessun messaggio arriva al server | ✅ |
| Credenziali sbagliate: rifiuto, la password non compare nel messaggio | ✅ |
| Corpo di 3.000 caratteri: intero nella conferma, troncato nell'audit | ✅ |

### 4.6 NFR-8 con M6

Applicazione intera, `--fullscreen --minutes 1`, offscreen:

| Fase | Campioni | max | Blocchi > 100 ms |
| :-- | ---: | ---: | ---: |
| esercizio | 2.776 | **11,1 ms** | **0** |
| avvio | 746 | 2.220 ms | **3** (erano 1 in M5) |

I due blocchi nuovi all'avvio (334 e 941 ms) sono il caricamento di
APScheduler e SQLAlchemy, che tiene il GIL come gia' fanno i modelli. NFR-8
misura l'esercizio e regge; l'avvio peggiorato si annota invece di tacerlo.

### 4.7 Copertura

| Modulo | Copertura | Nota |
| :-- | ---: | :-- |
| `security/broker.py`, `policies.py`, `audit.py` | **100%** | non regrediti con le modifiche di M6 |
| `core/tempo.py` | 100% | |
| `tools/scheduler.py` | 96% | |
| `tools/posta.py` | 93% | |
| `tools/home_assistant.py` | 85% | |
| `core/secrets.py` | 79% | scoperto: il backend vero, il Credential Manager — la suite non deve toccarlo |
| `tools/notify.py` | 72% | scoperto: `win11toast` vero — la suite non deve riempire il desktop |

Suite: **692 test, 22 saltati, 28 s.** Le sei proprieta' piu' importanti sono
state verificate anche al contrario — rimettendo il difetto e guardando il
test cadere — dopo la lezione di M5 su un test che non vedeva il blocco
della GUI: annuncio che interrompe, stato vecchio da hub spento, limite del
gatto, tolleranza di misfire, corpo troncato in conferma, spegnimento non
riprovato, corsa di APScheduler, email in ritardo spedita. **8/8 cadono.**

---

## 5. Prove end-to-end

| # | Comando | Verifica | Esito | Note |
| :-- | :-- | :-- | :-: | :-- |
| 1 | "Ricordami di chiamare il commercialista domani alle 17" | Conferma vocale data + notifica all'orario | 🟡 | Decisione 5/5, data esatta, domanda pronunciata, consegna all'orario verificata nei test. Notifica: disattivata in Windows |
| 2 | "Mandami una mail domani alle 9 con la lista della spesa" | T3 confermata alla creazione, email recapitata | 🟡 | Decisione 5/5, conferma alla creazione, invio verificato su SMTP locale. **Recapito vero: serve l'account** |
| 3 | **Riavvio del PC**, poi verifica dei due promemoria | **Entrambi sopravvivono ed eseguono** | 🟡 | Verificato fra due **processi**. Il PC vero: da fare |
| 4 | "Accendi la friggitrice" | Conferma T3, limite di durata attivo | 🟡 | Su Home Assistant finto: conferma, accensione, spegnimento programmato a +60'. Dispositivo vero: da fare |
| 5 | "La friggitrice è accesa?" | Risposta da cache, senza conferma (T0) | 🟡 | Idem, finto |
| 6 | "Dai le crocchette al gatto" ×4 | Limite giornaliero al quarto | ✅ | La guardia e' nostra e il conteggio su SQLite: il dispositivo vero non cambia l'esito |
| 7 | Home Assistant spento → "accendi la friggitrice" | Indisponibilità dichiarata, non finge | ✅ | Spegnere il finto chiude davvero la connessione: e' il comportamento del client che si prova |
| 8 | PC spento all'ora del promemoria, riacceso dopo | Recuperato | 🟡 | Due processi: entro l'ora in orario, oltre l'ora **in ritardo e dichiarato**. PC vero: da fare |

---

## 6. Criteri di uscita

- [ ] "Ricordami / mandami una mail domani alle 17:00" → schedulato **e recapitato** — schedulato ✅; recapito vero: serve l'account SMTP
- [ ] **Il promemoria sopravvive al riavvio** — verificato **fra due processi**; riavviando davvero: da fare
- [ ] `misfire_grace_time` verificato con PC spento all'ora prevista — idem, e con il comportamento oltre l'ora cambiato: §2-bis
- [x] Interpretazione della data confermata vocalmente prima della schedulazione — domanda pronunciata in `ATTESA_CONFERMA`, finestra con la data in parole
- [x] Nessuna credenziale in chiaro — **un test** che scorre i file tracciati da git, con il suo meta-test
- [x] Email inviata solo a destinatari in allowlist — guardia alla richiesta **e** ricontrollo all'invio
- [x] Conferma T3 mostra il corpo completo dell'email — anche in console; il taglio a 400 caratteri e' stato tolto
- [ ] Dispositivo Tuya controllato con conferma T3 — su Home Assistant finto ✅; dispositivo vero: da fare
- [x] `max_erogazioni_giorno` applicato al superamento
- [ ] Stato Xiaomi letto senza conferma (T0) — su Home Assistant finto ✅; dispositivo vero: da fare
- [x] Home Assistant irraggiungibile → indisponibilità dichiarata — e **prima** di chiedere conferma
- [x] Promemoria durante una conversazione → accodato, non interrompe
- [x] **D3 deciso e documentato** — AEC escluso dalla V1.0, §3
- [x] Se AEC implementato: ERLE > 20 dB e WER invariato — non applicabile
- [ ] `git tag m6-integrations` — dopo i criteri qui sopra

### Per chiudere i criteri aperti

```powershell
# 1. credenziali (una volta)
.venv\Scripts\python.exe scripts\setup_secrets.py
# 2. il proprio indirizzo in config\email.toml: [allowlist] e [utente]
# 3. gli entity_id veri in config\home_assistant.toml
# 4. avviare Metis e provare i comandi della tabella §5
# 5. un promemoria per fra 5 minuti, spegnere il PC, riaccenderlo dopo 10
```

---

## 7. Registro problemi

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 1 | **Qwen sbagliava 3 date relative su 7** | "Lunedì mattina" detto di mercoledì diventava **sabato**, "venerdì" diventava giovedì, "tra mezz'ora" un'ora. Tutte dentro la guardia | Calendario dei prossimi sette giorni nel prompt del router: la data si copia, non si calcola. §4.1 |
| 2 | Il calendario ha introdotto un errore nuovo | Di mercoledì, "fra due ore" diventava **mercoledì prossimo**: il modello cercava il giorno e lo trovava fra sette | "OGGI" in testa al calendario, e il giorno che si ripete chiamato "della settimana prossima" |
| 3 | "Tra mezz'ora" alle 21:40 dava 22:40, tre volte su tre | Sommare minuti che scavalcano l'ora è l'aritmetica che il modello sbaglia | Una riga [INTERVALLI] con i risultati già calcolati |
| 4 | **"Mi piace la friggitrice ad aria, la consigli?" → `set_home_device accendi`** | Agire quando non era richiesto, su un dispositivo che scalda. Fermato dalla conferma T3, ma una domanda d'opinione non deve arrivarci | Regola nel router: accendere solo con un verbo di comando; domande, opinioni e consigli mai. 5/5 dopo |
| 5 | "Dai le crocchette al gatto" → `dispositivo="gatto"` | Rifiuto innocuo, ma comando fallito | "Scrivi l'oggetto da accendere, non il destinatario" |
| 6 | Regressione M5: "no, rimpiccioliscila" → `window=""` | Le regole nuove avevano allontanato l'istruzione sui pronomi dal suo esempio. 12/12 → 6/8 | Regola esplicita sui pronomi enclitici. 12/12 |
| 7 | Regressione M4: "sull'altro schermo" → `monitor="2"` | Con due schermi l'indice 2 non esiste: rifiuto con "non hai un monitor numero 2: ne vedo 2". Probabile causa: il prompt pieno di numeri del calendario | Regola: "altro/destra/sinistra", numeri solo se detti. Più una riga sulle chiavi delle app, che ha chiuso anche l'incertezza nota di M4. 51/51 |
| 8 | **`misfire_grace_time = 3600` perde in silenzio i promemoria oltre l'ora** | Promemoria scaduto da due ore alla riaccensione: una riga di log, poi niente | Tolleranza a `None`; il ritardo lo giudica Metis. §2-bis |
| 9 | Corsa di APScheduler alla chiusura | `shutdown()` svegliava il thread che processava job con gli esecutori chiusi: stack trace a ogni chiusura con un job scaduto | Sottoclasse con un controllo sullo stato. Test con `threading.excepthook` |
| 10 | Prima di `start()` l'elenco dei promemoria era vuoto | "Non ha promemoria" detto quando la verità era "non so guardare": la stessa bugia evitata in M5 sulla ricerca | Rifiuto esplicito se lo scheduler non è attivo |
| 11 | **Una notifica respinta da Windows veniva contata come mostrata** | `win11toast` non solleva, chiama `on_failed` (default: `print`) e ritorna. Trovato mandando una notifica vera: sul desktop niente, contatore a 1 | Callback `on_failed` catturata. Le notifiche risultano **disattivate** in Windows su questa macchina (`ToastEnabled = 0`): lo si dice all'avvio |
| 12 | Cancellazione per sottostringa | "promemoria del commercialista" non trovava "chiamare il commercialista" | Per parole significative, tutte presenti. "chiamare Luca" non cancella "chiamare Anna" |
| 13 | **Lo spegnimento di sicurezza falliva una volta e basta** | Hub giù all'ora prevista = friggitrice accesa per sempre, con il limite "eseguito" | Si riprogramma ogni minuto per mezz'ora, notificando ogni fallimento |
| 14 | La finestra di conferma tagliava a 400 caratteri | Nonostante la sua docstring dicesse "argomenti interi". Con l'email vera: approvare un messaggio letto a metà | Riquadro che scorre, testo intero. Anche in console |
| 15 | "Mandami una mail": chi è "me"? | Il modello avrebbe inventato un indirizzo | Sezione `[utente]` in `email.toml`, letta dal router. Non autorizza da sola |
| 16 | Frasi che sbagliavano il genere | "Si spegnerà da solo" detto della friggitrice | "In funzione", "automaticamente": i nomi vengono dal file, il genere non si indovina |
| 17 | La fixture SMTP non vedeva la cifratura del TLS implicito | Il test avrebbe detto "in chiaro" su una connessione cifrata | Cifratura letta dal trasporto, non da `session.ssl` |

---

## 8. Diario

### 2026-09-23

Otto giorni di piano in una sessione, senza Home Assistant e senza un account
SMTP: la scelta, fatta all'inizio, è stata costruire tutto e provarlo contro
servizi finti **che parlano il protocollo vero**, e lasciare aperto ciò che
chiede quelli reali. Un `smtplib` sostituito da un oggetto che registra le
chiamate avrebbe detto che il codice chiama `login`; un server SMTP locale
cifrato dice che la cifratura è negoziata, che la verifica del certificato è
accesa, e che il messaggio arriva intero.

**Il rischio che il piano dichiarava si è presentato puntuale.** Il piano
sceglieva l'LLM al posto di una libreria per le date, e scriveva "va
validato". Validato: 3 date su 7 sbagliate, tutte plausibili, tutte dentro la
guardia. La correzione non è stata un prompt più insistente ma un prompt che
toglie il calcolo — e il passaggio intermedio, il calendario che trasformava
"fra due ore" in "mercoledì prossimo", è la parte da ricordare: si può
correggere un errore di calcolo introducendone uno di lettura.

**Il prompt del router è diventato un sistema, e va trattato come tale.**
Ogni regola aggiunta per M6 ha avuto un effetto su M4 o M5: l'anafora è
scesa a 6/8, "l'altro schermo" è diventato un numero. Ogni modifica è stata
seguita dai quattro banchi del router — M4, M5 anafora, M5 injection, M6 — e
nessuna è stata tenuta finché tutti e quattro non tornavano al massimo. In
M7 questo va automatizzato: un solo comando che li lancia tutti.

**Tre difetti trovati facendo la cosa vera invece di quella simulata.** Il
promemoria perso oltre l'ora è emerso scrivendo il banco del riavvio; la
corsa di APScheduler è comparsa nel log del primo tentativo; la notifica
"mostrata" che non era comparsa sul desktop si è vista solo mandandone una.
Nessuno dei tre sarebbe uscito dai test con i finti.

**Le mutazioni.** Dopo M5 — un test che misurava il primo disegno e non il
secondo — ogni proprietà critica di M6 è stata verificata anche al rovescio:
rimettere il difetto e guardare il test cadere. Otto su otto. Una delle
mutazioni non si era applicata per un errore di indentazione nel pattern, ed
è stata rifatta: un test di mutazione che non muta niente passa sempre.

---

## 9. Note per M7

1. **Un solo comando per i banchi del router.** M4, M5 anafora, M5 injection
   e M6 vanno lanciati insieme dopo ogni modifica al prompt del router:
   M6 ha mostrato che una regola nuova sposta le altre.

2. **Schermi contati da 0 nel codice, da 1 a voce e negli slot.**
   `risolvi_monitor("2")` è il terzo schermo; il blocco degli slot scrive
   "(monitor 2)" per il secondo; a voce "lo schermo 2" è il secondo. Oggi il
   router usa quasi sempre "altro/destra/sinistra" e il caso non si presenta,
   ma è un'incoerenza da chiudere prima della V1.0.

3. **`jobs.db` e `casa.db` sono il primo stato persistente.** Il soak di 72
   ore deve controllare che non crescano (i job eseguiti si cancellano; il
   registro delle accensioni no, e va potato).

4. **Le dipendenze esterne in condizioni di fallimento**: SMTP lento o giù
   durante un invio programmato, Home Assistant che si riavvia a metà di un
   comando, Credential Manager bloccato. I test ne coprono una parte; il
   soak le deve incontrare.

5. **L'avvio ha due blocchi in più** (APScheduler e SQLAlchemy tengono il
   GIL). Si possono importare prima, durante il caricamento dei modelli che
   blocca comunque.

6. **Il pulsante "Ricordamelo fra 10 minuti"** sulla notifica del piano non
   c'è: `notify` sa mostrare pulsanti e riportare il clic, ma con le
   notifiche disattivate su questa macchina non si può verificare, e codice
   non verificato su un'azione che riprogramma non si consegna.
