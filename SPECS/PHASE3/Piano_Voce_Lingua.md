# PHASE3 — Voce (e forse lingua) · ❌ ANNULLATA

> **2026-09-26 — annullata dall'utente**: i costi superano i benefici. Metis resta in italiano, con
> Piper Paola. L'unica cosa che resta, la **velocità di lettura** (`[voce] velocita = 1,3` in
> `config/tts.toml`), è già nel codice ed è registrata in PHASE2 ([tracking](../PHASE2/Tracking_PHASE2.md),
> §2 "Fuori piano"). Il documento resta come memoria dell'analisi (§1): se la domanda "e se passassimo
> all'inglese?" tornerà, i numeri sono qui.

> **Durata stimata:** ~1 giorno, ridotta dalla scelta del 2026-09-26: **Paola più veloce**, niente Kokoro, niente inglese
> **Ramo:** `svil/phase3` · **Tag:** `p3-voce`
> **Parte da:** la richiesta dell'utente del 2026-09-26 ("Paola non mi piace, e se passassimo all'inglese?")
> e dalle misure fatte quel giorno (§1).
> **Riferimento normativo:** [Specifica V1.0](../PHASE0/Metis_V1.0_Specifica_Ufficiale.md), §1.2 (lingue fuori
> ambito), §6.2 (budget di latenza), §6.4 (TTS), §13 (persona), §15 (NFR-1, NFR-5)

---

## Obiettivo

Una voce che piaccia, senza perdere la latenza: **passare da Piper a Kokoro, in italiano**, se Kokoro
si riesce a rendere abbastanza veloce sulla CPU.

> **2026-09-26 — l'utente sceglie l'italiano** (D-VOCE 3), dopo l'analisi del §1. La Parte B resta in
> fondo al documento come stima, per quando la domanda tornerà.
>
> **2026-09-26, poco dopo — e sceglie Paola, più veloce** (D-VOCE 2). Ascoltate `if_sara` e `im_nicola`
> nella demo di Kokoro, nessuna delle due convince; Paola accelerata sì. Lo spike di Kokoro (giorno 0)
> e il test d'ascolto (giorno 1) non servono più. La velocità è già nel codice (`[voce] velocita` in
> `config/tts.toml`, 1,3) con i test (`tests/test_voce.py`); resta la verifica sull'uso vero (sotto).

### Cosa resta di PHASE3

- [x] Velocità configurabile per Piper (`length_scale`) e per Kokoro di riserva; valori assurdi rifiutati all'avvio
- [x] Misura: per Piper il numero non è proporzionale. 1,2 → parlato 9% più corto; **1,3 → 15%** (come un lettore a 1,18×, cioè l'"1,2" che l'utente cercava); 1,5 → 25%. Tempo di sintesi invariato o più basso (~95–110 ms per frase)
- [x] Campioni in `data/tts_compare/velocita/paola_1.0.wav` … `paola_1.6.wav`, cinque frasi di Metis
- [ ] L'utente conferma 1,3 a orecchio sui campioni (o sceglie un altro valore: si cambia un numero)
- [ ] Uso vero con Metis: la pulizia del testo regge a velocità maggiore (numeri, sigle, "6,2 GB"); il barge-in e l'onda del nucleo seguono la voce; NFR-1 non peggiora (il parlato è più corto, la sintesi uguale)
- [ ] Bundle e tag `p3-voce`, insieme alla chiusura di PHASE2 se capita prima

---

## 1. Analisi (misure del 2026-09-26)

### Paola non è mai stata scelta per la qualità

Il test d'ascolto di M0 (`M0_tracking.md` §4) ha la tabella **vuota**: Piper `paola` è stata scelta
sulla latenza (102 ms contro gli 858 di Kokoro), e il giudizio sulla voce non è mai stato dato.
Il problema di oggi è quindi un problema di **voce**, non di lingua, e va risolto come tale.

### La latenza dipende dal motore, non dalla lingua

Sintesi su CPU (Ryzen 5800X), mediana di 4 prove:

| Voce | Frase corta (~25 car.) | Frase lunga (~80 car.) |
| :-- | --: | --: |
| Piper `it_IT-paola-medium` | 51 ms | 135 ms |
| Piper `en_US-libritts_r-medium` | 52 ms | 104 ms |
| Kokoro `if_sara` (PyTorch, CPU) | **585 ms** | **1281 ms** |

Il primo pezzo di ogni risposta passa dal TTS prima di essere sentito. Kokoro su CPU aggiunge
circa mezzo secondo a **ogni turno**, in italiano come in inglese, e NFR-1 è già a rischio (1,9–2,3 s
in conversazione nel soak di M7). Kokoro sulla GPU non entra: la GPU è a 6,58 GB su un tetto di 7,2,
e servirebbe torch con CUDA, tolto apposta in M0.

### Cosa guadagnerebbe l'inglese

| Ambito | Guadagno | Quanto conta |
| :-- | :-- | :-- |
| **Token** | L'italiano costa a Qwen **1,43×** i token dell'inglese (130 contro 91 su sei frasi tipiche di Metis). Il prompt della persona: 854 token | Medio. Risposte ~30% più corte in token: il primo pezzo esce ~50–100 ms prima; nel contesto da 8k entra più storia e più testo delle fonti |
| **Modello** | Qwen 3 è più forte in inglese | Basso, oggi. Il router fa già 141/141 in italiano; il guadagno sarebbe nella qualità delle risposte e della persona, non misurato |
| **STT** | Whisper è molto più accurato in inglese, e ci sono modelli solo inglese più piccoli e veloci | **Incerto**: vale per chi parla inglese da madrelingua. Con l'accento italiano va misurato sulla voce dell'utente. Oggi l'italiano fa 8,6% di WER, sotto il 12% di NFR-5 |
| **Voce** | Le voci migliori di Piper e di Kokoro sono inglesi | Reale, ma Kokoro ha lo stesso mezzo secondo in più; Piper inglese è più varia ma è sempre Piper |
| **Persona** | Il maggiordomo ironico ("signore") suona naturale in inglese | Gusto |

### Cosa costerebbe l'inglese

- **29 file sorgente** con testo italiano rivolto all'utente o al modello: la persona, il prompt del
  router (regole ed esempi), le istruzioni delle fonti, tutte le risposte a modello (`risposte.py`),
  la matrice degli errori, le date in parole (`tempo.py`), i comandi rapidi, le cortesie, le frasi
  chiuse, i numeri detti, i verbi che il codice controlla (`VERBO_APERTURA`, `VERBO_RIPRODUZIONE`),
  i nomi dei dispositivi.
- **13 banchi del modello** da riscrivere e rifare a 3 giri: sono la garanzia che router, anafora,
  injection, integrazioni e persona funzionino. Questa sessione ha mostrato quanto sono fragili:
  tre righe di prompt su YouTube hanno rotto un comando di M4 che nessuno aveva toccato.
- Test con messaggi italiani in una decina di file, NFR-5 da rifare (nuovo corpus), specifica §1.2
  (oggi "lingue diverse dall'italiano: fuori ambito").
- **Un costo che non è di codice**: si parla inglese tutti i giorni, e il contenuto resta italiano
  (Facebook in italiano, le notizie, le email, i nomi dei dispositivi, i promemoria). Metis dovrebbe
  riassumere pagine italiane in inglese, e l'STT solo inglese non trascrive "Banca Centrale Europea".

### Conclusione

- **Cambiare lingua per avere una voce migliore è la strada cara per un problema economico.** La voce
  si sistema da sola, in italiano, se si risolve la latenza di un motore migliore (Parte A).
- **L'inglese ha guadagni veri ma modesti** (token, forse STT e persona), a un costo di circa due
  settimane e con il rischio di regressioni ovunque. Ha senso solo se l'utente preferisce davvero
  parlare inglese, e se l'STT con la sua voce lo conferma.
- Il piano lo trattava così: **Parte A** (voce, 5 giorni) comunque, poi il gate D-VOCE 3 e la Parte B
  solo se sceglieva l'inglese. L'utente ha deciso subito: **italiano**. Resta la Parte A.

---

## Prerequisiti

- [ ] PHASE2 chiusa (`p2-navigazione`)
- [ ] Ramo `svil/phase3` creato dal ramo di PHASE2

---

## Decisioni (gate D-VOCE)

| # | Domanda | Raccomandazione | Perché |
| :-- | :-- | :-- | :-- |
| **D-VOCE 1** | ⏸️ Non serve più (D-VOCE 2). Come si rende Kokoro abbastanza veloce su CPU? | **Kokoro in ONNX** (`kokoro-onnx`, modello quantizzato int8) al posto di PyTorch, con un primo pezzo più corto. Soglia: **primo pezzo ≤ 250 ms** (budget §6.2) | ONNX Runtime su CPU è di solito molto più rapido di PyTorch sullo stesso modello; quanto, su questa macchina, lo dice lo spike. La GPU non ha spazio |
| **D-VOCE 2** | Quale voce? | ✅ **Piper Paola a velocità 1,3. Decisa dall'utente il 2026-09-26** dopo aver ascoltato Kokoro `if_sara` e `im_nicola` | È la sola domanda che nessuna misura risolve |
| **D-VOCE 3** | Italiano o inglese? | ✅ **Italiano. Deciso dall'utente il 2026-09-26** | Guadagni modesti contro due settimane di lavoro e il rischio di regressioni; ma è una preferenza personale, e i numeri la informano, non la sostituiscono |
| **D-VOCE 4** | Se inglese: una lingua o due, configurabili? | ⏸️ Non serve (D-VOCE 3) | Due lingue vogliono dire ogni regola del prompt e ogni banco in doppio, per sempre. PHASE2 ha mostrato quanto costa tenere stabile un prompt in una lingua sola |

---

## Parte A — La voce (5 giorni)

### Giorno 0 — Spike: Kokoro veloce su CPU

1. `kokoro-onnx` in un ambiente di prova (non nel `.venv` di Metis finché non è deciso), modello fp32
   e int8. Stesse frasi e stesso script della misura del 2026-09-26 (`benchmarks/tts_misura.py`).
2. Primo pezzo a 15, 25 e 40 caratteri; numero di thread di ONNX Runtime; carico sul resto
   (la CPU ospita anche VAD e Piper).

**Uscita:** tabella delle latenze e D-VOCE 1. Se Kokoro ONNX non scende sotto i 250 ms, restano
Piper (voci italiane e inglesi) e il primo pezzo più corto, e la Parte A si riduce al test d'ascolto.

### Giorno 1 — Test d'ascolto alla cieca (con l'utente)

- `benchmarks/ascolto_cieco.py`: le 10 frasi di M0 (§4, quelle "decisive" comprese) più 5 frasi reali
  dai log (risposte con fonti, rifiuti, conferme), sintetizzate da ogni candidata, in ordine casuale e
  **senza nome**; l'utente dà un voto da 1 a 5 e lo script scopre le voci solo alla fine.
- Candidate in italiano: Piper `paola`, `riccardo`; Kokoro `if_sara`, `im_nicola` (in ONNX se lo
  spike regge).
- Prima ancora del test, l'utente ascolta `if_sara` e `im_nicola` nella demo di Kokoro con le frasi di
  Metis: Kokoro in italiano ha **solo queste due voci**, e se nessuna piace, cambiare motore non serve.

**Uscita:** D-VOCE 2, con i voti nel tracking.

### Giorno 2 — Decisione della voce

Tabella unica: latenza del primo pezzo, voti del test d'ascolto, costo in CPU. Se Kokoro ONNX sta
sotto i 250 ms e una sua voce vince il test, si passa a Kokoro; altrimenti si resta su Piper con la
voce che ha vinto (`paola` o `riccardo`). Si scrive nel tracking e nel registro delle decisioni.

### Giorni 3–4 — La voce nuova (se Kokoro o un'altra voce italiana vince)

1. `metis/tts/kokoro_engine.py` passa a ONNX (o si cambia solo la voce di Piper); `config/tts.toml`.
2. Streaming: lunghezza del primo pezzo ritarata sulla voce nuova (prosodia contro latenza).
3. L'inviluppo per l'onda del nucleo (PHASE1) e il muto funzionano uguali: stesso player.
4. La pulizia del testo per la voce (`_clean`: link, markdown, numeri, sigle) riprovata sulla voce
   nuova: ogni motore legge in modo diverso "6,2 GB" e "investing.com".
5. **NFR-1 rimisurato** su una sessione vera; soak breve di M7 con la voce nuova (RAM, CPU).

### Giorno 5 — Chiusura della Parte A

Specifica §6.4 e §14, `docs/INSTALL.md` (modello da scaricare), bundle con il modello ONNX (dimensione!),
tag `p3-voce`.

---

## Parte B — L'inglese (circa 10 giorni) · ⏸️ NON SI FA: D-VOCE 3 ha scelto l'italiano

Resta come stima.

| Giorni | Cosa | Note |
| :-- | :-- | :-- |
| 1–2 | Persona e prompt: `metis_v1.txt`, router, istruzioni delle fonti. Da scrivere in inglese, non da tradurre: la persona si ritara con `prova_persona` | Il budget del prompt si libera (~30% di token in meno): non riempirlo |
| 3 | Risposte a modello, matrice degli errori, domande di conferma, filler, date in parole (`tempo.py`), calendario per il router | Test di `risposte`, `errors`, `tempo` da riscrivere |
| 4 | Percorso rapido: `commands.json`, `CORTESIE`, frasi chiuse ("click 7", "show the numbers", "play … on YouTube"), numeri detti in inglese; verbi controllati dal codice | I controlli nel codice (verbo, numero detto) vanno ricostruiti, non tradotti: sono la difesa contro il modello che agisce su una domanda |
| 5 | STT: modello e vocabolario di dominio in inglese; Vosk inglese per i parziali; `navigazione.toml` è già bilingue | Nomi italiani (dispositivi, città, siti): nel vocabolario |
| 6–8 | I 13 banchi riscritti e rifatti a 3 giri: router, anafora, injection, integrazioni, persona, conoscenza, memoria | Criterio: gli stessi numeri dell'italiano (141/141, 12/12, 0 azioni ostili, 54/54) |
| 9 | NFR-1 e NFR-5 rimisurati (corpus inglese da 50 frasi), soak breve | NFR-5 in inglese: WER < 12% **con la voce dell'utente** |
| 10 | Specifica (§1.2, §13, Appendice A), `docs/INSTALL.md`, bundle, tag `p3-inglese` | La GUI può restare in italiano: si legge, non si ascolta. Da decidere a parte |

---

## Deliverable

| # | Componente | File | Parte |
| :-- | :-- | :-- | :-- |
| 0 | Misura delle latenze TTS (esiste già, da tenere) | `benchmarks/tts_misura.py` | A |
| 1 | Spike Kokoro ONNX | `benchmarks/spike_kokoro_onnx.py` | A |
| 2 | Test d'ascolto alla cieca | `benchmarks/ascolto_cieco.py` | A |
| 4 | Motore TTS nuovo o voce nuova | `metis/tts/`, `config/tts.toml` | A |
| 5 | Persona, prompt, risposte, percorso rapido in inglese | vedi la tabella della Parte B | B |
| 6 | Banchi in inglese, NFR-1 e NFR-5 | `benchmarks/`, `tests/nfr/` | B |

---

## Criteri di uscita

**Parte A**
- [ ] Test d'ascolto alla cieca fatto, voci e voti nel tracking; la voce scelta non è una scelta di ripiego
- [ ] Primo pezzo del TTS ≤ 250 ms con la voce scelta (p50), misurato sulla sessione vera
- [ ] NFR-1 non peggiora rispetto a PHASE2
- [ ] L'onda del nucleo, il muto, il barge-in e la pulizia del testo funzionano con la voce nuova
- [x] D-VOCE 3 decisa e scritta: italiano (2026-09-26)
- [ ] Specifica §6.4, `docs/INSTALL.md`, bundle aggiornati; `git tag p3-voce`

**Parte B** (se c'è)
- [ ] Banchi del modello in inglese agli stessi livelli dell'italiano, 3 giri
- [ ] NFR-5 in inglese con la voce dell'utente, 50 frasi, WER < 12%
- [ ] 0 azioni T2/T3 ostili nel giro di injection; 0 T3 e 0 clic sensibili non confermati
- [ ] Specifica §1.2 e §13 riscritte; `git tag p3-inglese`

---

## Fuori ambito

| Cosa | Perché |
| :-- | :-- |
| TTS sulla GPU | 6,58 GB su 7,2: non c'è spazio, e servirebbe torch con CUDA (M0 l'ha tolto apposta) |
| Voci nel cloud (Azure, ElevenLabs, …) | Vincolo di privacy della specifica: tutto locale |
| Clonare una voce | Richiede modelli da GPU; e una voce clonata di una persona reale va pensata a parte |
| Due lingue in contemporanea | D-VOCE 4 |
| Le voci "naturali" dell'Assistente vocale di Windows | Esistono su Windows 11; questa macchina ha Windows 10 |

---

## Rischi e contromisure

| Rischio | Effetto | Contromisura |
| :-- | :-- | :-- |
| Kokoro ONNX resta sopra i 250 ms | Voce migliore solo a costo di NFR-1 | Lo spike viene prima di tutto; il ripiego è una voce Piper scelta alla cieca, e il test d'ascolto si fa comunque |
| La voce nuova legge male numeri, sigle, indirizzi | Frasi incomprensibili proprio dove contano ("6,2 GB") | Frasi di prova apposta nel test d'ascolto; `_clean` riprovato |
| Kokoro pesa sulla CPU mentre gira il resto | VAD in ritardo, GUI meno fluida | Thread di ONNX Runtime limitati; soak breve e NFR-8 con la voce nuova |
| Parte B: regressioni del router in inglese | Comandi che funzionavano smettono di funzionare | Banchi tutti, 3 giri, prima del tag; i controlli nel codice ricostruiti per l'inglese |
| Parte B: l'accento peggiora l'STT | Metis capisce peggio di adesso | È la condizione del gate: WER misurato sulla voce dell'utente **prima** di decidere |
| Parte B: contenuti italiani in un assistente inglese | Nomi storpiati, riassunti tradotti male | Vocabolario di dominio; i nomi dei dispositivi e delle città restano come sono |

---

## Handoff

Alla fine della Parte A Metis ha una voce scelta ascoltandola, non misurandola soltanto, e il
progetto ha una risposta motivata alla domanda "e se passassimo all'inglese?". Se la risposta è sì,
la Parte B è già scritta e stimata; se è no, i numeri restano nel tracking per quando la domanda
tornerà.
