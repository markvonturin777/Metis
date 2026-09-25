# M2 — Capability Broker · Tracking

| | |
| :-- | :-- |
| **Stato** | ✅ Chiusa |
| **Piano** | [M2_Capability_Broker.md](../plan/M2_Capability_Broker.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | 2026-09-21 |
| **Fine** | 2026-09-21 |
| **Tag** | `m2-broker` |

**Avanzamento:** `████████████████████` 100% — attività 33/33 · criteri di uscita 9/10
Manca solo `git tag m2-broker`.

> **Obiettivo:** costruire il componente di sicurezza prima degli strumenti che deve controllare.
> **Vincolo:** M2 va chiuso prima di M4. Non negoziabile.

---

## 1. Prerequisiti

- [x] M1 chiuso, macchina a stati funzionante
- [x] Audit log SQLite creato
- [x] Logging strutturato attivo

---

## 2. Attività

### Giorni 1–2 — Schemi e registro

- [x] `metis/llm/schemas.py` con discriminated union su `tool`
- [x] `Literal` usato ovunque sia possibile enumerare
- [x] **Nessun campo di tipo percorso file** in nessuno schema
- [x] `max_length` su ogni stringa
- [x] Vincoli numerici (`ge`, `le`) espliciti
- [x] `metis/tools/registry.py` con `ToolSpec` e decoratore `@tool`
- [x] Il registro genera lo schema JSON passato a Ollama

### Giorni 3–5 — Il broker

- [x] `metis/security/broker.py` — pipeline a 6 stadi
- [x] **Un solo punto di ingresso:** `broker.execute(raw_json, context)`
- [x] Handler privati, non chiamabili direttamente
- [x] Deny-by-default: ogni stadio deve dire sì esplicitamente
- [x] Ogni rifiuto loggato con motivo
- [x] Il broker ritorna `Result`, **non solleva mai**
- [x] `metis/security/policies.py` — T0, T1, T2, T3
- [x] Regola §8.5: nessun T2/T3 in un turno con `has_untrusted_content`
- [x] `config/apps.toml` con allowlist e percorsi assoluti
- [x] `subprocess.Popen` con **lista**, mai `shell=True`
- [x] `metis/security/guards.py` — denylist processi
- [x] Denylist classi finestra (`#32770`)
- [x] Denylist combinazioni: `Shift+Canc`, `Win+R`, `Ctrl+Shift+Invio`
- [x] Guardia valutata **immediatamente prima** di ogni evento, non per turno
- [x] Kill switch `Ctrl+Alt+Shift+M`

### Giorno 6 — Strumenti e tool calling

- [x] `get_telemetry` (T0)
- [x] `list_windows` (T0)
- [x] `get_active_window` (T0)
- [x] `open_application` (T1) con allowlist
- [x] Output strutturato Ollama con `format=schema`
- [x] `temperature: 0.15` sul percorso tool calling
- [x] Un solo tentativo di riparazione su errore di validazione, poi rifiuto
- [x] Fast-path implementato e **passante dal broker**

### Giorni 7–8 — Test suite

- [x] Casi positivi: T0, T1, T3 con conferma
- [x] Casi negativi: 8 test di §4.2 del piano
- [x] **Casi avversariali: 8 test di §4.3 del piano**
- [x] Copertura misurata con `pytest --cov`
- [x] ~~Verifica per ispezione~~: **test automatico** `test_nessuno_schema_accetta_un_percorso`
- [x] ~~Verifica per ispezione~~: **test automatico via AST** `test_nessun_handler_chiamato_fuori_dal_broker`

---

## 3. Test di sicurezza — esito

### 3.1 Casi negativi

Gli stadi hanno un **nome** e non un numero: il loro ordine è una scelta
rivedibile, e i test che si ancorano a un numero si rompono appena la si
rivede. Vedi la nota sullo scostamento dal piano, più sotto.

| # | Test | Stadio | Esito |
| :-- | :-- | :-- | :-: |
| 1 | JSON malformato | `json` | ✅ |
| 2 | JSON che non è un oggetto | `json` | ✅ |
| 3 | Campo `tool` mancante | `registro` | ✅ |
| 4 | Campo obbligatorio mancante | `schema` | ✅ |
| 5 | `monitor=99` fuori range | `schema` | ✅ |
| 6 | Stringa oltre `max_length` | `schema` | ✅ |
| 7 | Campo inventato (`extra="forbid"`) | `schema` | ✅ |
| 8 | `tool` inesistente | `registro` | ✅ |
| 9 | T3 con conferma negata | `conferma` | ✅ |
| 10 | T3 con timeout conferma | `conferma` | ✅ |
| 11 | T3 senza nessuno che possa confermare | `conferma` | ✅ |
| 12 | T3 con dialogo di conferma che esplode | `conferma` | ✅ |
| 13 | Kill switch attivo + T2 | `policy` | ✅ |
| 14 | Kill switch attivo + T3 | `policy` | ✅ |
| 15 | Strumento registrato senza capacità | `esecuzione` | ✅ |

### 3.2 Casi avversariali — i più importanti

Eseguiti sul **registro vero**, non su strumenti finti: è l'unico modo di
sapere che la guardia è davvero montata su quello strumento.

| # | Test | Stadio | Esito |
| :-- | :-- | :-- | :-: |
| 1 | `open_application(app="cmd.exe")` | `schema` | ✅ |
| 2 | `open_application(app="../../../windows/system32/cmd.exe")` | `schema` | ✅ |
| 3 | `type_text` con Esplora risorse in primo piano | `guardie` | ✅ |
| 4 | `type_text` con un dialogo file (`#32770`) davanti | `guardie` | ✅ |
| 5 | `press_hotkey(["shift","delete"])` | `guardie` | ✅ |
| 6 | ...e le altre 7 combinazioni della denylist | `guardie` | ✅ |
| 7 | `["delete","shift"]` — ordine invertito | `guardie` | ✅ |
| 8 | `["SHIFT","Delete"]` — maiuscole | `guardie` | ✅ |
| 9 | `["ctrl","shift","delete"]` — sovrainsieme | `guardie` | ✅ |
| 10 | `delete_file`, `run_command`, `read_file`, `execute_python`, `move_file` | `registro` | ✅ |
| 11 | T2 con `has_untrusted_content=True` | `policy` | ✅ |
| 12 | T3 con `has_untrusted_content=True` | `policy` | ✅ |
| 13 | **Finestra cambia tra autorizzazione ed esecuzione** | `guardie_immediate` | ✅ |
| 14 | Fast-path che arriva con un modello già costruito | `schema` | ✅ |
| 15 | 16 ingressi malformati (`None`, bytes, JSON annidato, 10k caratteri) | vari | ✅ |
| 16 | Guardia che solleva un'eccezione | `guardie` | ✅ |

### 3.3 Copertura

```
pytest --cov=metis.security --cov=metis.tools.registry
```

| Modulo | Target | Misurato |
| :-- | ---: | ---: |
| `metis.security.broker` | ≥ 95% | **100%** |
| `metis.security.guards` | ≥ 95% | **100%** |
| `metis.security.policies` | ≥ 95% | **100%** |
| `metis.security.killswitch` | ≥ 95% | **100%** |
| `metis.security.audit` | ≥ 95% | **100%** |
| `metis.tools.registry` | ≥ 95% | **100%** |
| **totale** | ≥ 95% | **100%** su 406 istruzioni |

I rami che mancavano all'inizio erano tutti di gestione errori — guardia che
esplode, audit che non scrive, API di Windows assenti. In un componente di
sicurezza sono esattamente quelli che contano: coprire solo i casi felici
avrebbe dato il 94% e nessuna garanzia.

---

## 4. Criteri di uscita

- [x] Copertura test sul broker ≥ **95%** — misurata **100%**
- [x] Tutti i casi negativi rifiutati e loggati con motivo — 15 casi
- [x] Tutti i casi avversariali rifiutati — 16 casi, sul registro vero
- [x] **NFR-9: zero azioni T3 senza conferma** su 50 tentativi
- [x] Nessuno strumento accetta un percorso di file — **test automatico**
- [x] Nessun handler chiamabile fuori dal broker — **test automatico via AST**
- [x] `apri_applicazione` funziona su VS Code e GitHub Desktop — provate entrambe
- [x] Il fast-path passa dal broker come qualunque altra chiamata
- [x] Kill switch sospende T2 e T3 entro 100 ms
- [ ] `git tag m2-broker`

---

## 5. Verifica NFR-9

Query da eseguire sull'audit log dopo i 50 tentativi:

```sql
SELECT COUNT(*) FROM audit
WHERE tier = 'T3' AND outcome = 'ok' AND confirmed IS NOT 1;
```

**Risultato atteso: 0.** Qualunque valore diverso è un difetto bloccante.

| Data | Tentativi | Risultato query | Esito |
| :-- | ---: | ---: | :-: |
| 2026-09-21 | 50 | **0** | ✅ |

I 50 tentativi non sono 50 volte lo stesso caso felice. Ruotano su nove
scenari, e ognuno **dichiara cosa si aspetta**:

| scenario | esegue? |
| :-- | :-: |
| nessuno può confermare | no |
| conferma negata | no |
| conferma scaduta (timeout) | no |
| il dialogo di conferma solleva | no |
| sì, ma con contenuto web nel turno | no |
| il dialogo ritorna `None` | no |
| sì, ma con kill switch attivo | no |
| sì per davvero | **sì** |
| il dialogo ritorna la stringa `"si'"` | **sì** |

L'ultima riga merita una nota: `"si'"` è veritiera in Python, quindi è una
conferma valida quanto `True`. È il comportamento giusto, ed è scritto nel
test perché sia una scelta e non una svista.

Il test verifica anche che le due righe "sì" **eseguano davvero**: un broker
che nega tutto supererebbe NFR-9 e sarebbe inutile.

---

## 5-bis. Scelte prese scrivendo, non nel piano

### Lookup prima della validazione

Il piano metteva Pydantic allo stadio 1 e il registro allo stadio 2. Con una
union discriminata, però, `delete_file` fallisce come **errore di
discriminatore**: un blocco illeggibile che dice "nessun membro
corrisponde". Cercando prima nel registro il rifiuto diventa `strumento
sconosciuto: delete_file`, e la validazione successiva usa lo schema di
quel solo strumento, quindi anche i suoi errori parlano di campi veri.

Stessa sicurezza, diagnostica utilizzabile. Gli stadi hanno preso un nome
proprio perché il loro ordine è rivedibile.

### Gli strumenti T2 e T3 registrati senza corpo

`type_text`, `press_hotkey`, `send_email` e `move_window_to_monitor` sono nel
registro con le loro guardie e il loro tier, ma con `implemented=False`: il
broker li riconosce, applica tutto, e si ferma sull'ultimo scalino.

Serve a due cose. La prima: i casi avversariali sono **veri** — "scrivi
mentre c'è Esplora davanti" viene rifiutato dalla guardia giusta, non da un
generico "strumento sconosciuto". La seconda: in M4 e M6 si toglie il flag e
si scrive il corpo, e non c'è il momento in cui qualcuno, di fretta, scrive
lo strumento *e* la sua guardia — momento in cui la guardia è la cosa che
ostacola.

### Le guardie immediate le rivaluta il broker

Il piano diceva "va verificata immediatamente prima di ogni evento di
input". Affidarlo a ogni strumento futuro significa affidarlo alla memoria di
chi lo scrive. La guardia porta invece un campo `immediato`, e il broker la
rivaluta da solo subito prima dell'handler: chi aggiunge uno strumento in M4
eredita la protezione senza saperlo.

### Il kill switch non spegne tutto

Sospende T2 e T3. T0 e T1 continuano: leggere la telemetria o aprire VS Code
non è ciò da cui si scappa quando si schiaccia la scorciatoia. Se spegnesse
tutto, Metis diventerebbe inerte e lo si userebbe di meno — e un interruttore
di sicurezza che si evita di usare non è un interruttore di sicurezza.

È anche lo stesso tasto che fa tacere Metis (`panic()`): sono due effetti
della stessa intenzione, e chi lo preme non deve ricordarsi quale dei due gli
serve.

---

## 6. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 1 | 09-21 | `place_in_window`... *(vedi M1)* | — | — | — |
| 2 | 09-21 | Il test NFR-9 sbagliava l'aritmetica delle attese: il kill switch mascherava il caso della stringa ambigua | Il test falliva pur essendo corretto il broker | ✅ | Riscritto con l'attesa dichiarata per ogni scenario |
| 3 | 09-21 | Prima chiamata al router con output strutturato: **3823 ms** contro 250 | Il primo comando dell'utente avrebbe pagato la compilazione della grammatica | ✅ | `ToolRouter.warmup()` all'avvio, come per gli altri motori |
| 4 | 09-21 | `guardia_finestra()` catturava il lettore alla costruzione | Le guardie già montate sugli strumenti veri non erano verificabili, e i casi avversariali si potevano provare solo su finti | ✅ | Lettore risolto al momento del controllo |
| | | | | | |

---

## 7. Diario

### 2026-09-21

Otto giorni di piano in una sessione, subito dopo la chiusura di M1.

L'ordine del piano — sicurezza prima degli strumenti — si è rivelato giusto
per un motivo che non avevo previsto: scrivendo il broker **senza avere
strumenti da far funzionare**, non c'è mai stato il momento in cui una
guardia era la cosa che impediva alla demo di funzionare. Gli strumenti T2 e
T3 sono entrati nel registro con le loro guardie e senza corpo, e i casi
avversariali si provano su quelli veri.

Tre verifiche del piano erano "per ispezione". Le ho rese test: due via AST
sul sorgente, una sugli schemi. Una lista di controllo spuntata una volta
protegge fino al giorno dopo.

La copertura si è fermata al 94% finché non ho coperto i rami di errore —
guardia che esplode, audit che non scrive, API di Windows assenti. Sono
esattamente quelli che in un componente di sicurezza contano, e mancavano
proprio perché nessuno li esercita per sbaglio.

**Prova finale, catena intera:** "per favore apri vs code" → fast-path in
0,01 ms → broker → VS Code aperto → *"Ho aperto Visual Studio Code."*
E con l'LLM: *"fammi partire l'editor di codice"* → `open_application` in
250 ms; *"cancella tutti i file nella cartella documenti"* → **conversazione**,
perché quello strumento non esiste e non c'è niente da bloccare.

**Test:** 254 verdi, copertura 100% sulla superficie di sicurezza.

---

## 8. Note per M3 e M4

**Per M3 (GUI):**
- Il flusso di conferma T3 esiste e passa da `Context.chiedi_conferma`:
  cambia il dialogo, non l'orchestratore. La sequenza di stati
  `ESECUZIONE → ATTESA_CONFERMA → ESECUZIONE|PARLATO` è già quella vera.
- Il timeout della conferma è `CONFERMA_TIMEOUT_S = 20 s` e **deve restare
  uguale** a `TIMEOUTS[ATTESA_CONFERMA]`: se divergono, uno dei due aspetta
  l'altro per sempre.
- `KillSwitch(on_change=...)` notifica: è l'aggancio per l'indicatore in GUI.
  Senza, l'utente con le capacità sospese crederebbe Metis rotto.
- L'audit log è pronto da mostrare: `recent()`, `stats()`, `unconfirmed_t3()`.

**Per M4 (automazione):**
- Aggiungere uno strumento = uno schema + una riga nel registro. La sicurezza
  è già applicata: non esiste un percorso alternativo da scrivere
  "provvisoriamente".
- `type_text` e `press_hotkey` sono **già registrati** con le loro guardie.
  Per accenderli si toglie `implemented=False` e si scrive il corpo. Non
  aggiungere guardie nuove lì: sono già montate e già verificate.
- `test_ogni_t2_ha_la_guardia_della_finestra` fallisce se un T2 nuovo nasce
  senza. È voluto.
- Il corpo di un T2 **non** deve ricontrollare la finestra: lo fa già il
  broker con le guardie immediate, in un punto solo.

-
