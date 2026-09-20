# M4 — Automazione del PC · Tracking

| | |
| :-- | :-- |
| **Stato** | ⬜ Non iniziata |
| **Piano** | [M4_Automazione_PC.md](../SPECS/plan/M4_Automazione_PC.md) |
| **Durata prevista** | 8 giorni |
| **Inizio** | — |
| **Fine** | — |
| **Tag** | `m4-automation` |

**Avanzamento:** `░░░░░░░░░░░░░░░░░░░░` 0% — attività 0/29 · criteri di uscita 0/12

> **Obiettivo:** far controllare davvero il computer a Metis.
> **Vincolo:** ogni strumento T2 nasce dentro il broker. Nessun percorso provvisorio.

---

## 1. Prerequisiti

- [ ] M2 chiuso, broker con copertura ≥ 95%
- [ ] M3 chiuso, conferme T3 funzionanti in GUI
- [ ] Denylist finestre implementata e testata
- [ ] Due monitor collegati, **possibilmente con scaling DPI diverso**

---

## 2. Attività

### Giorni 1–2 — DPI e geometria

- [ ] `metis/tools/display.py` con `set_dpi_awareness()`
- [ ] **Chiamata prima di `QApplication`** e prima di ogni import che tocca il display
- [ ] Enumerazione monitor via `mss`
- [ ] Coordinate negative gestite
- [ ] Tabella geometria §3.1 compilata

### Giorni 3–4 — Gestione finestre

- [ ] `move_window_to_monitor` (T1)
- [ ] `resize_window` (T1)
- [ ] `minimize_window` / `maximize_window` / `focus_window` (T1)
- [ ] Algoritmo di spostamento con ridimensionamento proporzionale
- [ ] Passo 5: verifica del rect ottenuto e correzione
- [ ] "Questa finestra" catturata all'ingresso in `IN_ASCOLTO`, non all'esecuzione
- [ ] Caso "il primo piano è Metis stesso" gestito
- [ ] Slot `ultima_finestra` popolato

### Giorni 5–6 — Input sintetico e risoluzione elementi

- [ ] `click_element` (T2) con denylist
- [ ] `type_text` (T2) con denylist
- [ ] `press_hotkey` (T2) con denylist finestre + combinazioni
- [ ] `scroll` (T2)
- [ ] `drag` (T2) con denylist
- [ ] `metis/tools/uia.py` — ricerca esatta → parziale → `AutomationId`
- [ ] **Nessuna ricerca fuzzy**
- [ ] Elemento non trovato → rifiuto esplicito, nessun clic a caso
- [ ] `metis/tools/browser.py` — Playwright su CDP
- [ ] `--remote-debugging-port=9222` aggiunto alla voce `chrome` in `apps.toml`
- [ ] Connessione a Chrome esistente verificata (sessioni e login attivi)

### Giorni 7–8 — Comandi custom e accettazione

- [ ] `config/commands.json` con lo schema di §4.1
- [ ] Matching su forma normalizzata (minuscole, senza punteggiatura, senza accenti)
- [ ] Le azioni sono tool call, **non** script
- [ ] Editor in GUI: aggiunta, modifica, eliminazione
- [ ] **Validazione contro il registro** al salvataggio
- [ ] **Ricarica a caldo** senza riavvio
- [ ] I 6 comandi di accettazione §3.2 provati

---

## 3. Misure da registrare

### 3.1 Geometria dei monitor

| Monitor | Risoluzione | Scaling | left | top | Coord. negative |
| :-- | :-- | :-- | ---: | ---: | :-: |
| 1 (primario) | — | — | 0 | 0 | no |
| 2 | — | — | — | — | ⬜ |
| 3 | — | — | — | — | ⬜ |

### 3.2 I sei comandi di accettazione

| # | Comando | Verifica | Esito | Note |
| :-- | :-- | :-- | :-: | :-- |
| 1 | "Hey Metis, inizia a lavorare" | VS Code + GitHub Desktop aperti | ⬜ | |
| 2 | "Sposta questa finestra sullo schermo a destra" | Corretto **anche con DPI diverso** | ⬜ | |
| 3 | "Clicca sul link \[nome\]" | Via UIA o Playwright, mai coordinate | ⬜ | |
| 4 | "Aprimi le news dei mercati" | Browser su investing.com | ⬜ | |
| 5 | "Massimizza Chrome" | Massimizzata sul monitor corrente | ⬜ | |
| 6 | "Metti Chrome sull'altro schermo e massimizzala" | **Comando composto**, due azioni dal broker | ⬜ | |

### 3.3 Tasso di successo della localizzazione elementi

Serve per il decision gate D2.

| Contesto | Tentativi | Successi | Tasso |
| :-- | ---: | ---: | ---: |
| Browser (Playwright) | — | — | — |
| App native (UIA) | — | — | — |
| **Totale** | — | — | — |

---

## 4. Test di sicurezza T2

| # | Test | Atteso | Esito |
| :-- | :-- | :-- | :-: |
| 1 | Digitare in Esplora risorse | Rifiuto in persona | ⬜ |
| 2 | Digitare in PowerShell | Rifiuto | ⬜ |
| 3 | Digitare in un dialogo "Salva con nome" | Rifiuto | ⬜ |
| 4 | `press_hotkey(["shift","delete"])` in qualunque contesto | Rifiuto | ⬜ |
| 5 | `press_hotkey(["win","r"])` | Rifiuto | ⬜ |
| 6 | Ogni azione T2 compare nell'audit log con la finestra target | Presente | ⬜ |

---

## 5. Criteri di uscita

- [ ] `set_dpi_awareness()` chiamata prima di `QApplication` — verificato per ispezione
- [ ] Tabella geometria compilata, coordinate negative gestite
- [ ] I sei comandi di accettazione funzionano
- [ ] Comando 2 verificato in **entrambe le direzioni** e con scaling DPI diverso
- [ ] Digitare in Esplora risorse viene rifiutato con messaggio in persona
- [ ] `press_hotkey(["shift","delete"])` rifiutato in qualunque contesto
- [ ] Clic su elemento non individuabile → rifiuto esplicito, nessun clic a caso
- [ ] Nuovo comando custom aggiungibile da GUI senza riavvio
- [ ] Comando custom con strumento inesistente → salvataggio rifiutato
- [ ] Ogni azione T2 nell'audit log con la finestra target
- [ ] **NFR-8 non regredito:** nessun freeze > 100 ms
- [ ] `git tag m4-automation`

---

## 6. Decision gate D2

| Decisione | Criterio | Esito | Motivo |
| :-- | :-- | :-- | :-- |
| **Strategia localizzazione elementi** | UIA + Playwright coprono ≥ 80% dei tentativi | — | — |

Alternativa: aggiungere OCR (`mss` + RapidOCR) come terzo livello, accettando 300 ms – 2 s di latenza.

---

## 7. Registro problemi

| # | Data | Problema | Impatto | Stato | Risoluzione |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | | | | | |

---

## 8. Diario

### AAAA-MM-GG
-

---

## 9. Note per M5

-
