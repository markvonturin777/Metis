# M6 — Integrazioni

> **Maturità:** P6 Connesso · **Durata:** 1,5 settimane (8 giorni) · **Tag:** `m6-integrations`

---

## Obiettivo

Far agire Metis **nel tempo e nel mondo fisico**: promemoria che sopravvivono al riavvio, email schedulate, elettrodomestici.

È l'iterazione in cui le azioni smettono di essere reversibili. Un'email inviata non torna indietro, e una friggitrice accesa scalda davvero. Tutto ciò che si aggiunge qui è **T3 con conferma obbligatoria**, senza eccezioni.

---

## Prerequisiti

- [ ] M5 chiuso, difese contro prompt injection **verificate**
- [ ] Broker con conferma T3 funzionante in GUI (M3)
- [ ] Home Assistant installato e raggiungibile sulla rete locale
- [ ] Account SMTP disponibile con password per app

> Il primo prerequisito non è formale. Collegare un modello a dispositivi fisici prima di aver verificato le difese contro l'injection significa esporre una friggitrice a una pagina web ostile.

---

## Deliverable

| # | Componente | File |
| :-- | :-- | :-- |
| 1 | Scheduler con jobstore persistente | `metis/tools/scheduler.py` |
| 2 | Invio email | `metis/tools/email.py` |
| 3 | Notifiche desktop | `metis/tools/notify.py` |
| 4 | Gestione segreti | `metis/core/secrets.py` |
| 5 | Client Home Assistant | `metis/tools/home_assistant.py` |
| 6 | AEC — opzionale, vedi D3 | `metis/audio/aec.py` |

---

## Step operativi

### Giorno 1 — Gestione dei segreti

Va per prima: tutto il resto dell'iterazione ne dipende, e rimandarla significa trovarsi credenziali in chiaro sparse nel codice.

```python
# metis/core/secrets.py
import keyring

SERVICE = "metis"

def get(key: str) -> str:
    v = keyring.get_password(SERVICE, key)
    if v is None:
        raise SecretMissing(key)     # mai un default, mai un fallback silenzioso
    return v
```

`keyring` su Windows usa il **Credential Manager**: le credenziali sono cifrate con DPAPI e legate all'utente.

| Chiave | Contenuto |
| :-- | :-- |
| `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password` | Account di invio |
| `ha_url`, `ha_token` | Home Assistant, long-lived access token |
| `brave_api_key` | Fallback ricerca (M5) |

**Script di setup una tantum** — `scripts/setup_secrets.py` — che chiede i valori e li scrive. Non committato con valori dentro, ovviamente.

Verifica: `git grep -iE "password|token|api[_-]?key"` non deve restituire alcun valore reale.

---

### Giorni 2–3 — Scheduler

#### 2.1 Il requisito che determina tutto

> **Il promemoria deve sopravvivere al riavvio del PC.**

È il criterio di uscita non negoziabile di questa parte. Con il jobstore in memoria — il default di APScheduler — ogni riavvio cancella tutto, il che rende la funzione inutile: un promemoria per domani alle 17:00 non serve se il PC si riavvia stasera.

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

scheduler = BackgroundScheduler(
    jobstores={"default": SQLAlchemyJobStore(url="sqlite:///data/jobs.db")},
    job_defaults={
        "misfire_grace_time": 3600,   # se il PC era spento, esegue entro 1 h
        "coalesce": True,             # un solo recupero, non uno per occorrenza persa
    },
)
```

`misfire_grace_time` è il parametro che gestisce il caso reale: PC spento all'ora prevista, riacceso dopo. Senza, il job scade silenziosamente.

#### 2.2 Gli strumenti

| Strumento | Tier | Motivo del tier |
| :-- | :-- | :-- |
| `schedule_reminder` | **T1** | Notifica locale, reversibile, nessun effetto esterno |
| `schedule_email` | **T3** | Conferma alla creazione: è un'email che partirà |
| `list_reminders` | T0 | — |
| `cancel_reminder` | T1 | — |

**Decisione:** per `schedule_email` la conferma è richiesta **alla creazione**, non all'invio. Chiedere conferma alle 17:00 di domani presuppone che tu sia davanti al PC, il che vanifica lo scopo della schedulazione. Il dialogo di conferma mostra destinatario, oggetto, corpo completo e orario di invio.

#### 2.3 Parsing delle date in italiano

*"domani alle 17:00"*, *"fra due ore"*, *"lunedì mattina"*. Due approcci:

| Approccio | Pro | Contro |
| :-- | :-- | :-- |
| Libreria di parsing (`dateparser`) | Deterministico, veloce | Copertura incompleta dell'italiano colloquiale |
| **LLM con schema Pydantic** ✅ | Copre il linguaggio naturale | Va validato |

**Raccomandazione: LLM con output strutturato**, dato che il tool calling esiste già. Lo schema forza un `datetime` ISO, e il broker valida che sia nel futuro e entro 1 anno.

**Conferma vocale obbligatoria dell'interpretazione:** *"Promemoria per domani, martedì 4 novembre, alle 17:00. Confermo?"* Sbagliare la data di un promemoria è il modo più semplice per rendere la funzione inaffidabile.

---

### Giorno 4 — Email e notifiche

#### 3.1 Invio email

```python
@tool(tier=Tier.T3, schema=SendEmail)
def send_email(to: str, subject: str, body: str) -> None:
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
        s.login(user, password)
        s.send_message(msg)
```

| Requisito | Dettaglio |
| :-- | :-- |
| Connessione | `SMTP_SSL`, mai in chiaro |
| Credenziali | Da `keyring`, mai da file |
| **Allowlist destinatari** | `config/email.toml`. Per la V1.0, Metis scrive solo a indirizzi noti |
| Conferma | Corpo **completo** nel dialogo, non un riassunto |
| Log | Nell'audit, con destinatario e oggetto; il corpo va troncato |

L'allowlist destinatari è una scelta conservativa deliberata: nella V1.0 Metis non ha motivo di scrivere a indirizzi arbitrari, e la restrizione elimina un'intera classe di danni possibili.

#### 3.2 Notifiche desktop

`win11toast` per notifiche native (più integrate di `plyer` su Windows 10/11).

| Caso | Contenuto |
| :-- | :-- |
| Promemoria scaduto | Testo + azione "Ricordamelo fra 10 minuti" |
| Azione T3 completata | Conferma |
| Errore | Quando Metis non può parlare (kill switch, audio occupato) |

Il promemoria produce **sia** la notifica **sia** l'annuncio vocale — ma solo se lo stato è `DORMIENTE`. Interrompere una conversazione in corso con un promemoria è un comportamento sbagliato: va accodato.

---

### Giorni 5–6 — Home Assistant

#### 4.1 WebSocket, non REST

| Approccio | Valutazione |
| :-- | :-- |
| REST in polling | Semplice, ma latenza alta e nessun aggiornamento di stato |
| **WebSocket** ✅ | Connessione persistente, stato in tempo reale, latenza minima |

```python
# autenticazione con long-lived access token da keyring
# sottoscrizione a state_changed per mantenere una cache locale degli stati
```

La cache degli stati serve a due cose: rispondere a *"la friggitrice è accesa?"* senza round-trip, e popolare lo slot `ultimo_dispositivo`.

#### 4.2 Mappatura dispositivi e tier

**Decisione di progetto:** il tier non è uniforme per dominio, ma **per entità**, configurato esplicitamente. Accendere una luce e accendere una friggitrice non sono la stessa cosa.

```toml
# config/home_assistant.toml
[entities.friggitrice]
entity_id = "switch.friggitrice_aria"
nome = "friggitrice ad aria"
tier = "T3"                  # scalda: conferma obbligatoria
max_durata_min = 60          # limite di sicurezza

[entities.crocchette]
entity_id = "switch.distributore_crocchette"
nome = "distributore crocchette"
tier = "T3"                  # eroga cibo: conferma obbligatoria
max_erogazioni_giorno = 3    # il gatto ringrazia

[entities.videocamera]
entity_id = "camera.xiaomi_salotto"
nome = "videocamera"
tier_lettura = "T0"
tier_scrittura = "T3"
```

I limiti `max_durata_min` e `max_erogazioni_giorno` sono guardie del broker, non suggerimenti: un ciclo di allucinazione che accende ripetutamente il distributore è uno scenario concreto, e il gatto non può dare il consenso informato.

#### 4.3 Gli strumenti

| Strumento | Tier |
| :-- | :-- |
| `get_home_state(entity_id)` | T0 |
| `list_home_devices()` | T0 |
| `set_home_device(entity_id, state)` | **T3**, sempre |

#### 4.4 Gestione della disconnessione

Home Assistant può essere irraggiungibile: rete, riavvio, aggiornamento. Comportamento richiesto:

- riconnessione automatica con backoff
- stato "non disponibile" dichiarato, **mai** uno stato memorizzato spacciato per attuale
- risposta in persona: *"L'hub domotico non risponde. Provo a riconnettermi."*

---

### Giorno 7 — AEC (opzionale)

#### Decision gate D3

| Situazione | Azione |
| :-- | :-- |
| **Si usano le cuffie** | **Saltare interamente questo step.** L'AEC non serve, e il tempo va su M7 |
| Si usano gli altoparlanti | Implementare L3 |

Con i livelli L1 (half-duplex gating) e L2 (barge-in via wake word) di M1, il sistema **funziona già** anche con gli altoparlanti. L'AEC aggiunge una sola capacità: interrompere Metis con una frase qualunque anziché con "Hey Metis".

#### Se si implementa

```python
# webrtc-audio-processing: AEC3
# Requisito critico: allineamento temporale fra segnale di riferimento
# (ciò che va agli altoparlanti) e segnale catturato.
```

La difficoltà non è l'algoritmo, è **la sincronizzazione**. Il ritardo fra l'invio del PCM al device e la sua cattura dal microfono va misurato e compensato; varia per scheda audio e per buffer.

| Test | Soglia |
| :-- | :-- |
| ERLE (attenuazione dell'eco) | > 20 dB |
| Barge-in con frase generica, altoparlanti al volume d'uso | Funziona in 8 casi su 10 |
| Nessuna degradazione del WER in assenza di eco | WER invariato entro 1 punto |

L'ultimo test è quello che si dimentica: un AEC mal tarato peggiora il riconoscimento **anche quando non c'è eco da cancellare**.

---

### Giorno 8 — Integrazione e prove

Prove end-to-end dei comandi completi dell'iterazione:

| # | Comando | Verifica |
| :-- | :-- | :-- |
| 1 | "Ricordami di chiamare il commercialista domani alle 17" | Conferma vocale della data, notifica all'orario |
| 2 | "Mandami una mail domani alle 9 con la lista della spesa" | T3 confermata alla creazione, email recapitata |
| 3 | **Riavvio del PC**, poi verifica dei due promemoria | **Entrambi sopravvivono ed eseguono** |
| 4 | "Accendi la friggitrice" | Conferma T3, accensione, limite di durata attivo |
| 5 | "La friggitrice è accesa?" | Risposta da cache, senza conferma (è T0) |
| 6 | "Dai le crocchette al gatto" | Conferma T3, limite giornaliero applicato al quarto tentativo |
| 7 | Home Assistant spento → "accendi la friggitrice" | Dichiara l'indisponibilità, non finge |

---

## Criteri di uscita

- [ ] "Ricordami / mandami una mail domani alle 17:00" → schedulato e recapitato
- [ ] **Il promemoria sopravvive al riavvio del PC** — verificato riavviando davvero
- [ ] `misfire_grace_time` verificato: promemoria con PC spento all'ora prevista viene recuperato
- [ ] Interpretazione della data confermata vocalmente prima della schedulazione
- [ ] Nessuna credenziale in chiaro nel repository — verificato con `git grep`
- [ ] Email inviata solo a destinatari in allowlist
- [ ] Conferma T3 mostra il corpo **completo** dell'email
- [ ] Dispositivo Tuya controllato con conferma T3
- [ ] Limite `max_erogazioni_giorno` applicato al superamento
- [ ] Stato Xiaomi letto senza conferma (T0)
- [ ] Home Assistant irraggiungibile → indisponibilità dichiarata, mai stato memorizzato
- [ ] Promemoria durante una conversazione → accodato, non interrompe
- [ ] **D3 deciso e documentato**: AEC implementato oppure esplicitamente escluso
- [ ] Se AEC implementato: ERLE > 20 dB e WER invariato senza eco
- [ ] `git tag m6-integrations`

---

## Fuori ambito per M6

| Non si fa | Arriva in |
| :-- | :-- |
| Lettura della posta in arrivo | Dopo la V1.0 — richiede IMAP e un modello di privacy diverso |
| Automazioni Home Assistant complesse (scene, routine) | Dopo la V1.0 |
| Streaming video della videocamera in GUI | Dopo la V1.0 |
| Integrazione calendario | Dopo la V1.0 |
| Destinatari email arbitrari | Scelta conservativa deliberata per la V1.0 |

---

## Rischi specifici di M6

| Rischio | Sintomo | Contromisura |
| :-- | :-- | :-- |
| **Jobstore in memoria** | Promemoria persi a ogni riavvio: la funzione è inutile | `SQLAlchemyJobStore` su SQLite, testato con riavvio reale |
| Promemoria persi con PC spento | Scadono silenziosamente | `misfire_grace_time = 3600` + `coalesce` |
| Data interpretata male | Promemoria alla settimana sbagliata | Conferma vocale dell'interpretazione, sempre |
| Credenziali in chiaro | Password nel repository | `keyring` + verifica `git grep` nei criteri di uscita |
| **Ciclo di allucinazione su dispositivo fisico** | Friggitrice accesa ripetutamente | Limiti per entità nel broker (`max_durata_min`, `max_erogazioni_giorno`) |
| Stato HA memorizzato spacciato per attuale | Metis dice che la friggitrice è spenta quando è accesa | Stato "non disponibile" esplicito alla disconnessione |
| Promemoria che interrompe una conversazione | Esperienza d'uso pessima | Accodamento se lo stato non è `DORMIENTE` |
| AEC mal tarato | WER peggiorato **anche senza eco** | Test di non-regressione del WER in assenza di eco |
| AEC implementato senza necessità | Una settimana persa | D3 deciso **prima** di iniziare lo step 7 |

---

## Handoff a M7

M6 consegna:

1. **Un assistente completo sul piano funzionale.** Tutte le capacità della specifica esistono.
2. **Il primo stato persistente** (`jobs.db`), che M7 deve verificare nel soak test di 72 ore.
3. **Dipendenze esterne** (SMTP, Home Assistant, rete) che M7 deve testare in condizioni di fallimento.
4. **L'ultima decisione aperta chiusa** (D3). Da M7 in poi si consolida, non si aggiunge.
