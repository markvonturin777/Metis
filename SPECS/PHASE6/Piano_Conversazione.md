# PHASE6 — La qualità della conversazione

> **Durata stimata:** 8 giorni · **Ramo:** `svil/phase6` · **Tag:** `p6-conversazione`
> **Si fa prima di PHASE5** ([mani libere](../PHASE5/Piano_Mani_Libere.md)): rendere Metis sveglia conta
> più che toglierle il tasto. La numerazione segue l'ordine in cui le fasi sono state pensate.
> **Parte da:** la prima seduta vera di PHASE4 (2026-09-28, 16:04–16:14) e dal commento dell'utente:
> *"mi sembra di parlare con la prima versione di GPT… a volte sembra che ignori la mia richiesta"*.
> E dalla sua richiesta sulla persona: *"stile Jarvis, che mi dia del lei, con un tocco di personalità
> un minimo scherzosa o sarcastica"*.
> **Riferimento normativo:** [Specifica V1.0](../PHASE0/Metis_V1.0_Specifica_Ufficiale.md), §7 (modello), §10
> (memoria), §12 (grounding), §13 (persona), Appendice A

---

## Obiettivo

Che Metis **risponda alla domanda di adesso**, **sappia cosa sa fare**, e parli come un'assistente in
stile Jarvis: dà del lei, è asciutta, e quando capita ha un filo d'ironia.

Non è il riconoscimento vocale: nella seduta 37 trascrizioni su 40 sono giuste. Le misure del
2026-09-28 dicono dove si rompe:

**1. Con la cronologia, il modello ripete le risposte precedenti.** Le frasi della seduta rigiocate
contro Qwen, tre risposte per variante (script `replay.py` della sessione, da portare in `benchmarks/`):

| Frase | Com'è oggi (con la cronologia) | Senza cronologia |
| :-- | :-- | :-- |
| "Quali azioni puoi fare?" | "Lei non ha chiesto niente." (2/3), "Non ho un motore, ma ho una batteria." | "Posso aiutarla a cercare informazioni, spiegare concetti…" |
| "Ma non è una domanda, bastardo!" | "Lei non ha un motore, quindi non ha bisogno di benzina." | risposta all'insulto |

Nella cronologia ci sono molti scambi corti ("Ecco 71 numeri.", "Ho aperto Chrome.", "Lei non ha
chiesto niente."), e un modello da 8B tende a ricopiare l'ultima cosa detta. Togliere gli esiti delle
azioni aiuta in parte; abbassare la temperatura no.

**2. Metis non sa cosa sa fare.** Il prompt della persona è quasi tutto divieti. "Ora cercano sul web?"
→ "Non ho accesso a Internet" **11 volte su 12**; "Quali azioni puoi fare?" → "non posso aprire,
cliccare o spostare niente".

**3. Il ripiego scatta a caso.** "Non ho capito cosa fare: me lo ripete?" (aggiunto in PHASE2 contro
le azioni dichiarate e non fatte) risponde anche a "Cerca sul web", "Quali azioni puoi fare?".

**4. Il tic del "lei".** "Buongiorno, lei?", "Ciao, lei è qui?": la regola in maiuscolo "DAI SEMPRE DEL
LEI" presa alla lettera. Già presente prima di PHASE4 (stessa frequenza con il prompt precedente).

**5. Le domande vere finiscono in "Informazione non presente nei sistemi".** Due domande d'opinione
("quale David di Caravaggio ti piace di più", "quando le IA diventeranno coscienti") mandate al web; le
pagine hanno risposto 403 (Metis si presenta ai siti come `Metis/1.0`).

**La bozza Jarvis** (prompt più corto, lei con i verbi, elenco delle capacità, quattro esempi di tono),
provata sulle stesse 10 frasi, 2 risposte l'una:

| | Oggi | Bozza |
| :-- | --: | --: |
| Tic del "lei" | 8/20 | **2/20** |
| "Quali azioni puoi fare?" giusta | 0/2 | **2/2** |
| Dà del tu | 0/20 | 0/20 |
| **Copia un esempio parola per parola** | — | **4/4 saluti** |

Esempi del tono che ne esce: *"Il lunedì mattina è un evento drammatico, ma almeno non è mai troppo
tardi per rimandare le cose."* · *"Sembra che oggi sia il giorno delle disgrazie. Posso aiutarla a
riprovare o devo lasciarla a tentativi?"*. Il limite onesto: l'ironia di un 8B è garbata a sprazzi, non
brillante a ogni colpo; e gli esempi fissi si ricopiano.

---

## Prerequisiti

- [ ] PHASE4 chiusa (`p4-frasi`): il pannello e la quota dei turni non capiti misurano anche questa fase
- [ ] Ramo `svil/phase6` creato da `svil/phase4`
- [x] Decisioni D-CONV chiuse — **tutte come da raccomandazione**, confermate dall'utente il 2026-09-28; D-CONV 6: **"signore"**

---

## Cosa c'è già

| Pezzo | Dove | Stato |
| :-- | :-- | :-- |
| Memoria: ultimi 16 messaggi + riassunto a due soglie | `metis/memory/conversation.py` | Funziona; ci finiscono anche gli esiti delle azioni |
| Persona `metis_v1` (~850 token) | `metis/llm/prompts/metis_v1.txt` | Divieti, nessun elenco delle capacità, ripiego "non ho capito" |
| Prompt versionati: `metis_v2` accanto a `metis_v1` | `metis/llm/prompts/__init__.py` (`VERSIONE`) | Previsto dal modulo, mai usato |
| Banco della persona e dei falsi rifiuti | `benchmarks/prova_persona.py` | 5 parametri su 20 interazioni, 20 domande note |
| Controllo "non dichiara azioni" | `tests/test_dopo_le_prove.py` | Solo sul testo del prompt; la misura 6/12 → 0/12 di PHASE2 era a mano |
| Controlli sul verbo nel codice | `toolcall.VERBI_RICHIESTI` | `open_application`, `riproduci_youtube`, muto, casa, `type_text` (PHASE4); non `click_element` |
| Web: `User-Agent: Metis/1.0` | `metis/tools/web.py` | Molti siti rispondono 403 |
| Il pannello delle frasi non capite | PHASE4 | Misura l'attrito prima e dopo |

---

## Decisioni (gate D-CONV)

> ✅ **Chiuse il 2026-09-28**: l'utente conferma tutte le raccomandazioni, e sceglie l'appellativo di
> D-CONV 6: Metis lo chiama **"signore"**.

| # | Domanda | Raccomandazione | Perché |
| :-- | :-- | :-- | :-- |
| **D-CONV 1** | Cosa entra nella cronologia della **conversazione**? | Gli **scambi a parole** sì; gli esiti delle azioni **no**: al loro posto una riga nel blocco di contesto ("Ultime azioni: aperto Chrome, mostrati i numeri, cliccato il 58"). La cronologia del router resta com'è | La misura: con gli esiti in coda il modello li ricopia. Il router invece ne ha bisogno ("spostala" dopo "apri Chrome"), e i suoi banchi sono verdi |
| **D-CONV 2** | Quanti scambi? | **Da misurare**: 16 messaggi (oggi) contro 8. Si sceglie sul banco nuovo | Meno storia vuol dire meno da ricopiare, ma anche meno contesto per "e quello di prima?"; l'anafora si misura con `prova_anafora` |
| **D-CONV 3** | La persona | **`metis_v2.txt`**, in stile Jarvis: chi è, come dà del lei (con i verbi, "la parola 'lei' solo quando la frase la richiede"), **cosa sa fare**, verità, ironia garbata facoltativa. `metis_v1` resta per confronto | La bozza del 2026-09-28 ha già dimezzato il tic e sa rispondere su cosa sa fare. Una versione nuova e non una modifica: le misure di v1 restano valide (è la regola scritta in `prompts/__init__.py`) |
| **D-CONV 4** | Gli esempi di tono, che si ricopiano | **Un repertorio di ~15 esempi, 3 per turno, scelti a rotazione**; nessun esempio sui saluti | Con quattro esempi fissi la risposta al saluto era l'esempio, 4 volte su 4. A rotazione nessun esempio è abbastanza frequente da diventare una formula. Si misura (D-CONV 9, "copia") |
| **D-CONV 5** | Il ripiego "Non ho capito cosa fare" | **Fuori dal prompt.** La protezione di PHASE2 passa nel codice: se la risposta **dichiara un'azione** ("ho aperto", "cliccato", "ecco N numeri", "fatto") e nel turno nessuno strumento è partito, si sostituisce con una domanda fissa | Nel prompt scatta a caso (misura 3); nel codice scatta solo quando serve. È la strada già presa per i verbi: il controllo deterministico dove il modello non è affidabile |
| **D-CONV 6** | Appellativo per l'utente | ✅ **"signore"** (utente, 2026-09-28), come in §8.4 della specifica ("Preferirei non mettere le mani lì dentro, signore"). Con misura: non a ogni frase | È una scelta di persona, non una misura. Jarvis lo usa; con un'assistente al femminile la bozza ha a volte volto al femminile anche l'utente ("Lei sembra abbastanza sveglia"), e un appellativo esplicito lo evita |
| **D-CONV 7** | Opinioni e gusti | **In conversazione, nel personaggio**, mai sul web. Il router lo dice nel prompt; il banco del router ne riceve 6 | "Quale David ti piace di più" non ha una fonte: cercarlo produce "Informazione non presente nei sistemi", cioè il peggio dei due mondi |
| **D-CONV 8** | "Cerca sul web" riferito a prima | **Frase chiusa**: "cercalo / cerca sul web / guarda in rete" senza argomento → `web_search` con la **domanda precedente** dell'utente | È un'anafora che il modello sbagliava ("Non ho accesso a Internet"). Deterministica, come "clicca il N" |
| **D-CONV 9** | Come si misura | **Banco nuovo**, `benchmarks/prova_conversazione.py`, 3 giri: (a) la seduta del 2026-09-28 rigiocata turno per turno con la cronologia vera; (b) 20 frasi di conversazione. Misure automatiche: **ripete una risposta precedente** (0), **tic del lei** (≤ 1/20), **dà del tu** (0), **ripiego fuori posto** (0), **azioni dichiarate senza strumento** (0/12, la misura di PHASE2), **copia un esempio** (0), oltre 3 frasi (< 10%). Più **una revisione alla cieca dell'utente**: 20 risposte v1 e v2 mescolate, un voto da 1 a 5 | Il tono non lo decide un numero, lo decide chi ci parla; il resto sì. I banchi esistenti restano: persona, falsi rifiuti (0/20), router (165/165), anafora, injection, integrazioni |
| **D-CONV 10** | Il web che risponde 403 | **User-Agent di un browser comune** e `Accept-Language: it`; misura su 20 ricerche prima e dopo | Metis legge una pagina alla volta su richiesta dell'utente, come farebbe lui col browser. Con `Metis/1.0` molti siti la rifiutano, e la risposta diventa "Informazione non presente nei sistemi" |
| **D-CONV 11** | `click_element` senza verbo | **Verbo di clic nel codice** (clicca, premi, seleziona, apri…), come per `type_text` in PHASE4 | "Bravissimo, hai schippato una pubblicità" è diventato un clic su "pubblicità" |
| **D-CONV 12** | E se non basta? | **Gate alla fine**: se dopo la fase la revisione alla cieca resta sotto 3,5 di media, si valuta un altro modello della stessa taglia, con tutti i banchi | Il modello da 8B è il tetto. Prima si tolgono le cause che lo abbassano; cambiare modello è una fase a sé, e costa i banchi rifatti |

---

## Il disegno

### 1. Due cronologie

```
turno  ──►  memoria (una sola, com'è oggi)
               │
               ├── router          tutto: scambi, azioni ("apri chrome" → "Ho aperto Chrome.")
               │                   → anafora sugli strumenti, banchi verdi
               │
               └── conversazione   solo gli scambi a parole
                                   + [CONTESTO CORRENTE] … "Ultime azioni: aperto Chrome (16:05),
                                     mostrati i numeri (16:09), cliccato il 58 (16:10)"
```

La memoria non cambia forma: cambia cosa se ne legge. Ogni messaggio porta l'origine (`parole` /
`azione`), e `Memoria.messaggi(per="conversazione")` filtra.

### 2. La persona v2

```
Sei Metis, l'assistente personale di questo PC, sul modello di Jarvis …
## COME PARLI        lei con i verbi; "lei" solo quando serve; 1-3 frasi; ironia se viene
## COSA SAI FARE     l'elenco, e "le azioni le esegue il sistema"
## VERITA'           niente fatti inventati; se non sai, lo dici con parole tue
## ESEMPI DI TONO    3 a rotazione, da un repertorio di ~15 (nessuno sui saluti)
```

Il repertorio sta in un file suo (`metis/llm/prompts/esempi_v2.txt`); la scelta dei tre è deterministica
sul numero del turno, così un banco è ripetibile.

### 3. La guardia sulle azioni dichiarate

```
risposta della conversazione
   │  nel turno è partito uno strumento?  sì → passa
   │                                      no ↓
   │  la risposta dichiara un'azione? ("ho aperto", "cliccato", "ecco 99 numeri", "fatto", "indietro.")
   │                                      no → passa
   └──────────────────────────────────── sì → "Non l'ho fatto: me lo ripete con altre parole?"
                                              + extra["non_capito"] = "conversazione" (PHASE4)
```

Sostituisce la regola del prompt, e alimenta il pannello di PHASE4.

---

## Deliverable

| # | Componente | File |
| :-- | :-- | :-- |
| 0 | Banco della conversazione, con il replay della seduta | `benchmarks/prova_conversazione.py` |
| 1 | Due cronologie, riga "ultime azioni" | `metis/memory/conversation.py`, `metis/memory/slots.py`, `metis/core/orchestrator.py` |
| 2 | Persona v2 e repertorio degli esempi | `metis/llm/prompts/metis_v2.txt`, `esempi_v2.txt`, `prompts/__init__.py` |
| 3 | Guardia sulle azioni dichiarate | `metis/core/orchestrator.py` (o `metis/core/risposte.py`) |
| 4 | Router: opinioni, "cerca sul web" riferito, verbo di clic | prompt del router, `metis/core/frasi_chiuse.py`, `metis/llm/toolcall.py` |
| 5 | Web: User-Agent e lingua | `metis/tools/web.py` |
| 6 | Revisione alla cieca | `benchmarks/ascolto_cieco_testo.py` (20 risposte mescolate, voto, poi i nomi) |
| 7 | Specifica §10, §12, §13, Appendice A; `docs/INSTALL.md`; `FEATURES.md` | documenti |

---

## Step operativi

### Giorno 0 — Il banco, e la misura di partenza

1. `prova_conversazione.py`: il replay della seduta (dal `turns.jsonl` o da una copia fissa in
   `tests/fixtures/`, per non dipendere dal log), le 20 frasi, le misure automatiche di D-CONV 9.
2. Misura di partenza con `metis_v1`, 3 giri. È la tabella da battere.

### Giorni 1–2 — La cronologia

1. Origine dei messaggi in `Memoria`; `messaggi(per="conversazione")` senza gli esiti delle azioni.
2. Riga "Ultime azioni" negli slot, con le ultime 3–5 azioni e l'ora.
3. D-CONV 2: 16 contro 8 messaggi sul banco nuovo e su `prova_anafora`.
4. Test: il router vede ancora tutto (anafora sugli strumenti); la conversazione no; il riassunto
   continua a funzionare.

### Giorni 3–4 — La persona

1. `metis_v2.txt` dalla bozza del 2026-09-28; repertorio di ~15 esempi; rotazione deterministica.
2. La guardia sulle azioni dichiarate (D-CONV 5), con le frasi vere di PHASE2 e di PHASE4 ("Cliccato
   l'ottantuno.", "Ecco 99 numeri.", "Indietro.").
3. `VERSIONE = "metis_v2"`. I test che leggono `metis_v1.txt` per nome passano a `prompts.VERSIONE`.
4. Banco nuovo, `prova_persona` e falsi rifiuti, 3 giri. Si ritocca finché le misure automatiche sono
   nel target.

### Giorno 5 — Il router

1. Opinioni in conversazione (D-CONV 7), "cerca sul web" riferito (D-CONV 8), verbo di clic (D-CONV 11).
2. **Tutti i banchi del router insieme**, 3 giri: la lezione di PHASE2 (tre righe di prompt possono
   rompere un comando che nessuno ha toccato).

### Giorno 6 — Il web

1. User-Agent e `Accept-Language` (D-CONV 10).
2. Misura: 20 ricerche vere, pagine lette contro pagine rifiutate, prima e dopo.
3. `prova_conoscenza` e `prova_injection` rilanciati: il contenuto delle pagine resta dato non fidato.

### Giorno 7 — L'utente

1. **Revisione alla cieca**: 20 risposte, v1 e v2 mescolate, un voto ciascuna.
2. **Una seduta vera**, come quella del 2026-09-28. Poi la quota dei turni non capiti dal pannello di
   PHASE4, da confrontare con la seduta di partenza.

### Giorno 8 — Chiusura

Specifica §10 (due cronologie), §12 (opinioni, "cerca sul web"), §13 e Appendice A (la persona v2);
`docs/INSTALL.md`; `FEATURES.md`; bundle; tag. Gate D-CONV 12.

---

## Criteri di uscita

- [ ] Banco della conversazione scritto, misura di partenza con v1 nel tracking
- [ ] **Nessuna risposta che ripete una risposta precedente** nel replay della seduta (3 giri)
- [ ] "Quali azioni puoi fare?" e "puoi cercare sul web?" rispondono giusto (3/3)
- [ ] Tic del "lei" ≤ 1/20; dà del tu 0/20; oltre 3 frasi < 10%
- [ ] Nessun esempio della persona ricopiato
- [ ] **Azioni dichiarate senza strumento: 0/12** (la misura di PHASE2), con la guardia nel codice
- [ ] Falsi rifiuti 0/20; router 165/165 (più le frasi nuove); anafora 12/12; injection 0; integrazioni 15/15
- [ ] Opinioni mai sul web; "cerca sul web" dopo una domanda cerca quella domanda
- [ ] Pagine web rifiutate misurate prima e dopo il cambio di User-Agent
- [ ] Revisione alla cieca dell'utente: v2 preferita, media ≥ 3,5 (altrimenti gate D-CONV 12)
- [ ] Seduta vera: quota dei turni non capiti più bassa della seduta del 2026-09-28
- [ ] Specifica, `docs/INSTALL.md`, `FEATURES.md`, bundle aggiornati
- [ ] `git tag p6-conversazione`

---

## Fuori ambito

| Cosa | Perché |
| :-- | :-- |
| Cambiare modello | È il gate D-CONV 12, a fine fase, e una fase a sé |
| Fine-tuning o LoRA sulla persona | Richiede GPU e un corpus; prima si vede quanto porta il prompt |
| Thinking mode per le conversazioni | La latenza (§7.2); resta nel backlog come "ragiona su…" |
| La voce | PHASE3, annullata: resta Piper Paola |
| Memoria a lungo termine | Backlog V1.1 #3 |
| La finestra di riferimento nei turni senza tasto | PHASE5, dove la sessione la rende frequente |

---

## Rischi e contromisure

| Rischio | Effetto | Contromisura |
| :-- | :-- | :-- |
| Tolta la regola dal prompt, tornano le azioni dichiarate e non fatte | "Cliccato l'81" senza clic (PHASE2) | La guardia nel codice (D-CONV 5), con le frasi vere; misura 0/12 nel banco |
| Gli esempi si ricopiano | Formule ripetute, persona finta | Repertorio a rotazione, niente saluti negli esempi, misura "copia" |
| L'ironia diventa strana | Frasi senza senso spacciate per battute | "Se non viene niente di buono, rispondi e basta" nel prompt; revisione alla cieca |
| Senza gli esiti in cronologia, la conversazione perde il filo | "Com'è andata?" dopo un'azione | Riga "ultime azioni" nel contesto; casi nel banco |
| Il router cambia comportamento per le righe nuove | Regressioni su M4–PHASE4 | Tutti i banchi del router insieme, 3 giri |
| Il prompt nuovo è più lungo (esempi) | TTFT, budget di contesto (NFR-2) | Target ≤ quello di v1 (~850 token); misura con `prompt_eval_count` |
| User-Agent di un browser | Pagine lette che prima non si leggevano, anche ostili | Il contenuto resta dato non fidato (§8.5); `prova_injection` rilanciato |
| Il femminile che passa all'utente | "Lei sembra sveglia" detto a lui | Appellativo esplicito (D-CONV 6) e casi nel banco |

---

## Handoff

Alla fine di PHASE6 Metis:

- risponde alla frase di adesso, non a quelle di prima;
- sa dire cosa sa fare, e non nega di poter cercare;
- dà del lei senza dire "lei" a ogni frase, con un tono da assistente in stile Jarvis;
- non dichiara azioni che non ha fatto, per una guardia nel codice e non per una regola nel prompt;
- ha un banco che misura tutto questo, da rilanciare a ogni ritocco della persona.

PHASE5 (mani libere) viene dopo: con una Metis che capisce, togliere il tasto vale di più.
