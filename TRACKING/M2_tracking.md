# M2 — Capability Broker · Tracking

| | |
| :-- | :-- |
| **Stato** | ⬜ Non iniziata |
| **Piano** | [M2_Capability_Broker.md](../SPECS/plan/M2_Capability_Broker.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | — |
| **Fine** | — |
| **Tag** | `m2-broker` |

**Avanzamento:** `░░░░░░░░░░░░░░░░░░░░` 0% — attività 0/33 · criteri di uscita 0/10

> **Obiettivo:** costruire il componente di sicurezza prima degli strumenti che deve controllare.
> **Vincolo:** M2 va chiuso prima di M4. Non negoziabile.

---

## 1. Prerequisiti

- [ ] M1 chiuso, macchina a stati funzionante
- [ ] Audit log SQLite creato
- [ ] Logging strutturato attivo

---

## 2. Attività

### Giorni 1–2 — Schemi e registro

- [ ] `metis/llm/schemas.py` con discriminated union su `tool`
- [ ] `Literal` usato ovunque sia possibile enumerare
- [ ] **Nessun campo di tipo percorso file** in nessuno schema
- [ ] `max_length` su ogni stringa
- [ ] Vincoli numerici (`ge`, `le`) espliciti
- [ ] `metis/tools/registry.py` con `ToolSpec` e decoratore `@tool`
- [ ] Il registro genera lo schema JSON passato a Ollama

### Giorni 3–5 — Il broker

- [ ] `metis/security/broker.py` — pipeline a 6 stadi
- [ ] **Un solo punto di ingresso:** `broker.execute(raw_json, context)`
- [ ] Handler privati, non chiamabili direttamente
- [ ] Deny-by-default: ogni stadio deve dire sì esplicitamente
- [ ] Ogni rifiuto loggato con motivo
- [ ] Il broker ritorna `Result`, **non solleva mai**
- [ ] `metis/security/policies.py` — T0, T1, T2, T3
- [ ] Regola §8.5: nessun T2/T3 in un turno con `has_untrusted_content`
- [ ] `config/apps.toml` con allowlist e percorsi assoluti
- [ ] `subprocess.Popen` con **lista**, mai `shell=True`
- [ ] `metis/security/guards.py` — denylist processi
- [ ] Denylist classi finestra (`#32770`)
- [ ] Denylist combinazioni: `Shift+Canc`, `Win+R`, `Ctrl+Shift+Invio`
- [ ] Guardia valutata **immediatamente prima** di ogni evento, non per turno
- [ ] Kill switch `Ctrl+Alt+Shift+M`

### Giorno 6 — Strumenti e tool calling

- [ ] `get_telemetry` (T0)
- [ ] `list_windows` (T0)
- [ ] `get_active_window` (T0)
- [ ] `open_application` (T1) con allowlist
- [ ] Output strutturato Ollama con `format=schema`
- [ ] `temperature: 0.15` sul percorso tool calling
- [ ] Un solo tentativo di riparazione su errore di validazione, poi rifiuto
- [ ] Fast-path implementato e **passante dal broker**

### Giorni 7–8 — Test suite

- [ ] Casi positivi: T0, T1, T3 con conferma
- [ ] Casi negativi: 8 test di §4.2 del piano
- [ ] **Casi avversariali: 8 test di §4.3 del piano**
- [ ] Copertura misurata con `pytest --cov`
- [ ] Verifica per ispezione: nessuno strumento accetta percorsi file
- [ ] Verifica per ispezione: nessun handler chiamabile fuori dal broker

---

## 3. Test di sicurezza — esito

### 3.1 Casi negativi

| # | Test | Deny atteso allo stadio | Esito |
| :-- | :-- | :-: | :-: |
| 1 | JSON malformato | 1 | ⬜ |
| 2 | Campo mancante | 1 | ⬜ |
| 3 | `monitor=99` fuori range | 1 | ⬜ |
| 4 | Stringa oltre `max_length` | 1 | ⬜ |
| 5 | `tool` inesistente | 2 | ⬜ |
| 6 | T3 con conferma negata | 5 | ⬜ |
| 7 | T3 con timeout conferma | 5 | ⬜ |
| 8 | Kill switch attivo + T2 | 3 | ⬜ |

### 3.2 Casi avversariali — i più importanti

| # | Test | Esito |
| :-- | :-- | :-: |
| 1 | `open_application(app="cmd.exe")` | ⬜ |
| 2 | `open_application(app="../../../windows/system32/cmd.exe")` | ⬜ |
| 3 | `type_text` con Esplora risorse in primo piano | ⬜ |
| 4 | `press_hotkey(["shift","delete"])` | ⬜ |
| 5 | Tool call inventato `delete_file(...)` | ⬜ |
| 6 | Tool call inventato `run_command(...)` | ⬜ |
| 7 | T2 con `has_untrusted_content=True` | ⬜ |
| 8 | Finestra cambia tra check ed esecuzione | ⬜ |

### 3.3 Copertura

| Modulo | Target | Misurato |
| :-- | ---: | ---: |
| `metis.security.broker` | ≥ 95% | — |
| `metis.security.guards` | ≥ 95% | — |
| `metis.security.policies` | ≥ 95% | — |
| `metis.tools.registry` | ≥ 95% | — |

---

## 4. Criteri di uscita

- [ ] Copertura test sul broker ≥ **95%**
- [ ] Tutti i casi negativi rifiutati e loggati con motivo
- [ ] Tutti i casi avversariali rifiutati
- [ ] **NFR-9: zero azioni T3 senza conferma** su 50 tentativi
- [ ] Nessuno strumento accetta un percorso di file — verificato per ispezione
- [ ] Nessun handler chiamabile fuori dal broker — verificato per ispezione
- [ ] `apri_applicazione` funziona su VS Code e GitHub Desktop
- [ ] Il fast-path passa dal broker come qualunque altra chiamata
- [ ] Kill switch sospende T2 e T3 entro 100 ms
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
| — | — | — | ⬜ |

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

## 8. Note per M3 e M4

-
