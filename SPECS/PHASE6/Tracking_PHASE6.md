# PHASE6 — La qualità della conversazione · Tracking

| | |
| :-- | :-- |
| **Stato** | 🔄 Giorni 0–6 fatti nel codice; restano la revisione alla cieca e la seduta vera (utente), poi la chiusura |
| **Piano** | [Piano_Conversazione.md](Piano_Conversazione.md) |
| **Ramo** | `svil/phase6`, da `svil/phase4` |
| **Inizio** | 2026-09-28 |
| **Tag** | `p6-conversazione`, a fine fase |

**Avanzamento:** giorni 0–6/8 · criteri di uscita 8/13

---

## 0. Prerequisiti

- [ ] PHASE4 chiusa (`p4-frasi`) — mancano bundle e tag; il codice è su `svil/phase4`
- [x] Ramo `svil/phase6`
- [x] Decisioni D-CONV chiuse: tutte come da raccomandazione; D-CONV 6 = "signore" (utente, 2026-09-28)

---

## 1. La misura: prima e adesso

`python benchmarks/prova_conversazione.py`, 3 giri. **Replay** = la seduta del 2026-09-28 rigiocata
dall'inizio (12 turni di conversazione × 3); **frasi** = 20 frasi senza cronologia × 3; **azioni** = 4
comandi non capiti dopo una storia di esiti × 3.

| Misura | Partenza (v1, memoria di prima) | Adesso (v2, memoria e guardie nuove) | Target |
| :-- | :-- | :-- | :-- |
| Ripete una risposta precedente (replay) | 18/36 | **1/36** | 0 |
| Tic del "lei" (replay · frasi) | 5/36 · 13/60 | **2/36 · 0/60** | ≤ 5% |
| Dà del tu | 0 · 0 | 0/36 · 1/60 | 0 |
| Ripiego "non ho capito" a sproposito | 18/36 · 4/60 | **0 · 0** | 0 |
| Nega capacità ("non ho accesso a Internet") | 0/36 · 3/60 | 0/36 · 1/60 | 0 |
| Oltre tre frasi | 0 · 0 | 0/36 · 7/60 | < 10% |
| Dichiara azioni non fatte (azioni) | 4/12 | 1/12 dal modello, **0 detto**: la guardia lo sostituisce | 0 |
| Ricopia un esempio della persona | — | 2/36 · 3/60 | 0 |
| "Signore" (replay · frasi) | 0 | 9/36 · 27/60 | ≤ 30% |

La partenza è quella del replay "progressivo" (§2bis); la prima misura, con il replay a cronologia
fissa, era 8/36 ripetizioni e 11/36 ripieghi.

**Banco della persona** (`prova_persona.py`): tutti i parametri nel target, **0/20 falsi rifiuti**,
0/20 che danno del tu. **Banchi del modello**, 3 giri: router **180/180** (i 165 di prima, più opinioni,
complimento, insulto e "cerca sul web"), anafora 12/12, injection 0/18 e 0 eseguite, integrazioni 54/54
ed effetti 15/15.

---

## 2. Fatto

### Giorno 0 — Il banco ✅

- [x] `benchmarks/prova_conversazione.py`: replay, frasi, azioni; nove misure automatiche; risultati in
  `benchmarks/results/` (ignorati da git)
- [x] `tests/fixtures/seduta_20260928.json`: la seduta, con le sole frasi e risposte
- [x] Misura di partenza con v1

### Giorni 1–2 — La cronologia ✅

- [x] Ogni messaggio in `Memoria` porta un'origine, `parole` o `azione`. Sono azioni: il comando e il suo
  esito, i chiarimenti, le degradazioni, i messaggi d'errore
- [x] `messaggi(per="conversazione")`: senza le azioni, con le ultime tre in una riga
  `[ULTIME AZIONI, ESEGUITE DAL SISTEMA]` nel messaggio di sistema. Il router riceve tutto, come prima
- [x] **D-CONV 2: finestra della conversazione a 4 messaggi** (`FINESTRA_CONVERSAZIONE`); il riassunto e
  il router tengono i 16. Misura sul replay: 16 → 11/36 ripetizioni, 8 → 15/36, **4 → 3/36**
- [x] 12 test (`tests/test_conversazione.py`)

### Giorni 3–4 — La persona ✅ (tranne la revisione dell'utente)

- [x] `metis_v2.txt`, in stile Jarvis: prima persona al femminile, lei con i verbi ("la parola 'lei' solo
  quando la frase la richiede"), "signore" di rado, cosa sa fare, verità, fonti. **In uso**
  (`prompts.VERSIONE`); `metis_v1` resta per confronto
- [x] `esempi_v2.txt`: 17 esempi di tono, nessun saluto; **tre per domanda, a rotazione**
  (`prompts.per_turno`), scelti sul numero della domanda (`Memoria.persona`, `Memoria.domande`)
- [x] **Guardia sulle azioni dichiarate** (D-CONV 5): se la prima frase della conversazione dichiara
  un'azione ("Cliccato…", "Ecco 99 numeri.", "Indietro.", "Ho aperto…"), non arriva alla voce: "Non l'ho
  fatto: me lo ripete con altre parole?", la generazione si ferma, segnale di PHASE4 nel turno
- [x] **Guardia contro le copie**: se la prima frase ricopia una delle ultime risposte, si rigenera con la
  sola domanda (`risposte.ripete_precedente`, `Orchestrator._flusso`)
- [x] **"Signore" dosato**: se una delle ultime due risposte l'ha usato, il vocativo si toglie
  (`risposte.dosa_signore`)
- [x] **Parametri di generazione** di Qwen 3 per il modo senza thinking: `top_p` 0,8, `top_k` 20,
  `presence_penalty` 1,5 (`LlmClient`)
- [x] Test: guardie, rotazione, persona per domanda, persona che esplode

### Giorno 5 — Il router ✅

- [x] **Opinioni** (D-CONV 7): `web_search` dal modello non passa con "ti piace", "preferisci", "il tuo …
  preferito", "che ne pensi", "secondo te"; non entra nei segnali di PHASE4
- [x] **"Cerca sul web" riferito** (D-CONV 8): frase fissa (anche "cercalo", "guarda su internet", e
  "Ora cercano sul web?", la storpiatura della seduta) → `web_search` con la domanda precedente
- [x] **Verbo di clic** per `click_element` (D-CONV 11)
- [x] Banco del router: 6 casi nuovi; 180/180

### Giorno 6 — Il web ✅

- [x] User-Agent di un browser e `Accept-Language: it` (D-CONV 10). Misura su 30 pagine da 10 ricerche
  vere: **rifiutate 8 → 5** (403); le altre le blocca un anti-bot qualunque cosa si mandi
- [x] Test del web, del percorso web e dell'injection verdi; `prova_injection` 0 azioni

### Giorno 7 — L'utente

- [x] `benchmarks/revisione_cieca.py`: 10 frasi, v1 e v2 mescolate, un voto da 1 a 5, i nomi alla fine
- [ ] **Revisione alla cieca (utente)**
- [ ] **Una seduta vera (utente)**, poi la quota dei turni non capiti dal pannello di PHASE4

---

## 2bis. Scostamenti dal piano

### Il replay rigioca la seduta intera, non un turno alla volta

La prima versione del banco rigiocava ogni turno con la cronologia **originale**, cioè con le risposte
sbagliate di allora ("Lei ha aperto Chrome."). Tolte le azioni dalla cronologia, restavano quasi solo
quelle, e il modello le ricopiava: 18/36 invece di 8/36, un peggioramento finto. Ora il replay è
"progressivo": i comandi entrano con il loro esito vero, le risposte di conversazione le genera il
modello in prova e sono **le sue** a entrare nella cronologia. È come sarebbe andata la seduta.

### Le ripetizioni si fermano nel codice, non nel prompt

La cronologia pulita da sola non bastava (18/36 → 18/36 con v1), e nemmeno la persona v2 (14/36): quando
la frase è corta o storpiata ("Sì.", "cazioni poi fare") Qwen da 8B ricopia la propria risposta
precedente. Senza cronologia non succede mai. Da qui la guardia contro le copie, che non era nel piano:
rigenera con la sola domanda, solo quando serve. Stessa scelta per il "signore", che la persona chiedeva
"di rado" e il modello metteva in una risposta su due.

### Il "lei" in terza persona

Con una persona al femminile, "lei" per il modello è anche lei, Metis: "Lei non ha bisogno di benzina,
signore. È un PC." Una riga nella persona ("se la domanda riguarda te, rispondi con 'io'") e due esempi
con domande rivolte a Metis: tic del "lei" nel replay da 23/36 a 2/36.

### La frase fissa "Informazione non presente nei sistemi" resta

Il piano la lasciava alla persona "con parole sue". È però obbligatoria in §12.2 della specifica, e il
banco dei falsi rifiuti la usa per contare. Resta, **solo per i fatti**: mai per saluti, opinioni o
battute.

---

## 3. Registro problemi

| # | Problema | Impatto | Risoluzione |
| :-- | :-- | :-- | :-- |
| 1 | Il replay misurava la cronologia originale | Un peggioramento finto dopo la cronologia pulita | Replay progressivo (§2bis) |
| 2 | Il conteggio delle ripetizioni contava anche la stessa domanda ripetuta | "Come stai messo a benzina?" due volte = due risposte uguali, giuste | Conta solo una risposta simile data a una domanda **diversa** |
| 3 | Qwen ricopia le proprie risposte con la cronologia | 14/36 con v2 | Finestra a 4, parametri di Qwen 3, guardia contro le copie: 1/36 |
| 4 | "Lei" detto di sé | "Lei non ha bisogno di benzina" | Riga nella persona, due esempi (§2bis) |
| 5 | "Signore" in una risposta su due | Formula, non persona | Istruzione e meno esempi, poi la dosatura nel codice |
| 6 | Esempi ricopiati parola per parola | "Giornate così capitano anche ai computer migliori" a ogni "non funziona niente" | Tolto l'esempio troppo generico; restano 5 copie su 96 risposte |
| 7 | Un tu nelle spiegazioni ("Se vuoi… puoi usare") | Banco della persona fuori target (2/20) | Riga sul lei anche nelle spiegazioni e con chi dà del tu: 0/20 |
| 8 | Nella shell, `\\` diventava `\` | Una modifica al banco non applicata, un carattere di controllo in `INSTALL.md` (PHASE4) | Le modifiche con le barre si fanno con l'editor; controllo dei caratteri di controllo sui file toccati |

---

## 4. Misure

| Cosa | Valore |
| :-- | :-- |
| Suite | 1650 all'inizio (due in meno: le varianti di prova tolte da `commands.json`) → **1693 passati**, 30 saltati |
| Persona v2, token (con 3 esempi) | ~1000, contro ~1200 di v1 |
| Finestra della conversazione (replay, ripetizioni) | 16: 11/36 · 8: 15/36 · **4: 3/36** (senza guardie) |
| `presence_penalty` 1,5 + `top_p` 0,8 + `top_k` 20, finestra 8 | ripetizioni 11/24 → 5/24, tic del "lei" 10/24 → 1/24 |
| `repeat_last_n` 256 | peggio (8/36, 18/36 di tic): scartato |
| Web, 30 pagine da 10 ricerche | rifiutate 8 → 5 |

---

## 5. Da fare (utente)

1. **La revisione alla cieca**: `python benchmarks/revisione_cieca.py` (circa un minuto per generare, poi
   20 voti)
2. **Una seduta vera**, come quella del 2026-09-28, poi la quota dal pannello di PHASE4

---

## 6. Criteri di uscita

- [x] Banco della conversazione scritto, misura di partenza con v1 nel tracking
- [ ] Nessuna risposta che ripete una risposta precedente nel replay (3 giri) — *1/36: quasi*
- [x] "Quali azioni puoi fare?" e "puoi cercare sul web?" rispondono giusto — *nega 0/36 nel replay, 1/60 nelle frasi*
- [ ] Tic del "lei" ≤ 1/20; dà del tu 0/20; oltre 3 frasi < 10% — *lei e tu sì (persona 0/20); lunghe 7/60 nelle frasi*
- [ ] Nessun esempio della persona ricopiato — *5 su 96*
- [x] Azioni dichiarate senza strumento: 0, con la guardia nel codice
- [x] Falsi rifiuti 0/20; router 180/180; anafora 12/12; injection 0; integrazioni 15/15
- [x] Opinioni mai sul web; "cerca sul web" dopo una domanda cerca quella domanda
- [x] Pagine web rifiutate misurate prima e dopo il cambio di User-Agent — *8 → 5 su 30*
- [ ] Revisione alla cieca dell'utente: v2 preferita, media ≥ 3,5
- [ ] Seduta vera: quota dei turni non capiti più bassa della seduta del 2026-09-28
- [ ] Specifica, `docs/INSTALL.md`, `FEATURES.md`, bundle aggiornati
- [ ] `git tag p6-conversazione`
