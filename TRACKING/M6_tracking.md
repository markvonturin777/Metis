# M6 — Integrazioni · Tracking

| | |
| :-- | :-- |
| **Stato** | ⬜ Non iniziata |
| **Piano** | [M6_Integrazioni.md](../SPECS/plan/M6_Integrazioni.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | — |
| **Fine** | — |
| **Tag** | `m6-integrations` |

**Avanzamento:** `░░░░░░░░░░░░░░░░░░░░` 0% — attività 0/28 · criteri di uscita 0/15

> **Obiettivo:** far agire Metis nel tempo e nel mondo fisico.
> Da qui le azioni non sono più reversibili: tutto ciò che si aggiunge è T3 con conferma.

---

## 1. Prerequisiti

- [ ] M5 chiuso, **difese contro prompt injection verificate**
- [ ] Conferma T3 funzionante in GUI
- [ ] Home Assistant installato e raggiungibile
- [ ] Account SMTP con password per app

> Il primo prerequisito non è formale: collegare il modello a dispositivi fisici senza aver verificato le difese significa esporre una friggitrice a una pagina web ostile.

---

## 2. Attività

### Giorno 1 — Segreti

- [ ] `metis/core/secrets.py` con `keyring`
- [ ] **Nessun default, nessun fallback silenzioso:** chiave mancante → eccezione
- [ ] `scripts/setup_secrets.py` scritto
- [ ] Credenziali SMTP salvate nel Credential Manager
- [ ] Token Home Assistant salvato
- [ ] `git grep -iE "password|token|api[_-]?key"` non restituisce valori reali

### Giorni 2–3 — Scheduler

- [ ] `SQLAlchemyJobStore` su `data/jobs.db`
- [ ] `misfire_grace_time = 3600` e `coalesce = True`
- [ ] `schedule_reminder` (T1)
- [ ] `schedule_email` (T3, conferma **alla creazione**)
- [ ] `list_reminders` (T0)
- [ ] `cancel_reminder` (T1)
- [ ] Parsing date italiane via LLM con schema Pydantic
- [ ] Validazione: data nel futuro ed entro 1 anno
- [ ] **Conferma vocale dell'interpretazione** della data

### Giorno 4 — Email e notifiche

- [ ] `send_email` (T3) con `SMTP_SSL`
- [ ] `config/email.toml` con allowlist destinatari
- [ ] Conferma mostra il corpo **completo**, non un riassunto
- [ ] Audit log con destinatario e oggetto, corpo troncato
- [ ] Notifiche desktop con `win11toast`
- [ ] Promemoria scaduto → notifica + annuncio vocale
- [ ] **Promemoria accodato** se lo stato non è `DORMIENTE`

### Giorni 5–6 — Home Assistant

- [ ] Client WebSocket con long-lived token
- [ ] Sottoscrizione a `state_changed`, cache locale degli stati
- [ ] `config/home_assistant.toml` con tier **per entità**
- [ ] `get_home_state` (T0)
- [ ] `list_home_devices` (T0)
- [ ] `set_home_device` (T3)
- [ ] Guardia `max_durata_min` sulla friggitrice
- [ ] Guardia `max_erogazioni_giorno` sul distributore crocchette
- [ ] Riconnessione automatica con backoff
- [ ] Stato "non disponibile" dichiarato, mai stato memorizzato spacciato per attuale

### Giorno 7 — AEC (solo se D3 lo richiede)

- [ ] **D3 deciso prima di iniziare**
- [ ] Se cuffie: step saltato, tempo spostato su M7

---

## 3. Decision gate D3

| Situazione | Azione | Scelta |
| :-- | :-- | :-: |
| Si usano le **cuffie** | Saltare l'AEC interamente | ⬜ |
| Si usano gli **altoparlanti** | Implementare L3 | ⬜ |

**Decisione:** — **Data:** —

### 3.1 Se l'AEC è implementato

| Test | Soglia | Misurato | Esito |
| :-- | :-- | :-- | :-: |
| ERLE (attenuazione eco) | > 20 dB | — | ⬜ |
| Barge-in con frase generica, altoparlanti al volume d'uso | 8 su 10 | — | ⬜ |
| **WER invariato in assenza di eco** | entro 1 punto | — | ⬜ |

> L'ultimo test è quello che si dimentica: un AEC mal tarato peggiora il riconoscimento anche quando non c'è eco da cancellare.

---

## 4. Prove end-to-end

| # | Comando | Verifica | Esito | Note |
| :-- | :-- | :-- | :-: | :-- |
| 1 | "Ricordami di chiamare il commercialista domani alle 17" | Conferma vocale data + notifica all'orario | ⬜ | |
| 2 | "Mandami una mail domani alle 9 con la lista della spesa" | T3 confermata alla creazione, email recapitata | ⬜ | |
| 3 | **Riavvio del PC**, poi verifica dei due promemoria | **Entrambi sopravvivono ed eseguono** | ⬜ | |
| 4 | "Accendi la friggitrice" | Conferma T3, limite di durata attivo | ⬜ | |
| 5 | "La friggitrice è accesa?" | Risposta da cache, senza conferma (T0) | ⬜ | |
| 6 | "Dai le crocchette al gatto" ×4 | Limite giornaliero applicato al quarto | ⬜ | |
| 7 | Home Assistant spento → "accendi la friggitrice" | Indisponibilità dichiarata, non finge | ⬜ | |
| 8 | PC spento all'ora del promemoria, riacceso dopo | Recuperato entro `misfire_grace_time` | ⬜ | |

---

## 5. Criteri di uscita

- [ ] "Ricordami / mandami una mail domani alle 17:00" → schedulato e recapitato
- [ ] **Il promemoria sopravvive al riavvio** — verificato riavviando davvero
- [ ] `misfire_grace_time` verificato con PC spento all'ora prevista
- [ ] Interpretazione della data confermata vocalmente prima della schedulazione
- [ ] Nessuna credenziale in chiaro — verificato con `git grep`
- [ ] Email inviata solo a destinatari in allowlist
- [ ] Conferma T3 mostra il corpo completo dell'email
- [ ] Dispositivo Tuya controllato con conferma T3
- [ ] `max_erogazioni_giorno` applicato al superamento
- [ ] Stato Xiaomi letto senza conferma (T0)
- [ ] Home Assistant irraggiungibile → indisponibilità dichiarata
- [ ] Promemoria durante una conversazione → accodato, non interrompe
- [ ] **D3 deciso e documentato**
- [ ] Se AEC implementato: ERLE > 20 dB e WER invariato
- [ ] `git tag m6-integrations`

---

## 6. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | | | | | |

---

## 7. Diario

### AAAA-MM-GG
-

---

## 8. Note per M7

-
