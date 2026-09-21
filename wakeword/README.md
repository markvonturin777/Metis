# Wake word "Hey Metis"

> **Spenta in V1.0** (`enabled = false` in `config/wakeword.toml`). Decisione
> D1 del 2026-09-21: NFR-7 non superato, 57 auto-inneschi in 125 minuti.
> L'attivazione della V1.0 è il push-to-talk. Tutto quello che c'è in questa
> cartella resta valido e pronto: per riaccenderla serve una riga di
> configurazione e una seduta `nfr7_test.py` a stanza vuota.

## Perché un ambiente separato

Le dipendenze di training — `audiomentations`, `librosa`, `numba`, `torchmetrics`
— pesano circa 500 MB e **il runtime non le usa mai**. Peggio: installandole in
`.venv` hanno retrocesso `soxr` da 1.1.0 a 0.5.0, cioè una libreria sul percorso
audio critico, già validata in M0.

soxr 0.5.0 si è poi rivelato corretto (nessuna perdita di campioni, solo 8-14 ms
di latenza di filtro costante), ma il principio resta: **un'attività offline
non deve poter cambiare le versioni del runtime.**

Il training vive quindi in `.venv-train`. Il runtime in `.venv` contiene solo
`openwakeword` per l'inferenza, che è leggera e usa onnxruntime.

## Perché non si usa `openwakeword.train`

Il modulo di training del progetto tira dentro speechbrain, datasets,
pronouncing, yaml e altro: una catena pensata per il loro notebook e le loro
sorgenti dati. Il contratto vero del modello è invece banale, verificato
ispezionando i modelli preaddestrati:

```
input   (batch, 16, 96)  float32     16 finestre x 96 feature di embedding
output  (batch, 1)       float32     punteggio in [0, 1]
```

Sedici finestre sono **esattamente 2,000 secondi** a 16 kHz. Bastano torch e
numpy, già presenti. Il classificatore ha ~50k parametri: il lavoro pesante
l'ha già fatto l'estrattore di embedding.

## Pipeline

```powershell
# 1. corpus sintetico — Piper, 866 parlanti inglesi + le 2 voci italiane
.\.venv-train\Scripts\python.exe wakeword\generate_samples.py

# 2. feature con augmentation
.\.venv-train\Scripts\python.exe wakeword\extract_features.py both

# 3. training ed export ONNX
.\.venv-train\Scripts\python.exe wakeword\train_model.py

# 4. prova con la TUA voce
.\.venv\Scripts\python.exe wakeword\live_test.py 15
```

Il passaggio 2 cerca da solo il rumore reale in `wakeword/data/noise/`: se c'è,
lo usa al posto del rumore rosa sintetico, e vale molto di più.

## Banchi di prova

| script | a cosa serve |
| :-- | :-- |
| `live_test.py` | rilevamento e trabocchetti, guidati a voce |
| `record_ambient.py` | registra la stanza vera: rumore per il training **e** NFR-6 |
| `nfr7_test.py` | NFR-7: Metis parla per due ore, si conta se si auto-innesca |
| `pronunciation_check.py` | quale grafia inglese suona come l'italiano "Metis" |
| `../benchmarks/e2e_replay.py` | wake word dentro la catena completa, barge-in compreso |

## Due cose che non sono ovvie

### Il FPR sintetico non predice i falsi risvegli

Sul set di validazione il modello ha 0 falsi positivi su 4800 clip negativi,
e **non significa nulla per NFR-6**. In esecuzione il rilevatore valuta un
blocco ogni 32 ms: 900.000 volte in 8 ore. Servirebbe un FPR sotto lo
0,00011%, mentre 4800 campioni risolvono al minimo lo 0,021% — due ordini di
grandezza sopra. Da qui la soglia alta (0,95), la conferma su blocchi
consecutivi, e la taratura **dal vivo**.

### Il punteggio dipende da dove cadono i confini dei blocchi

Misurato il 2026-09-21: lo stesso audio, spostato di 64 campioni — quattro
millisecondi — cambia punteggio in modo drastico.

| clip | escursione su 8 allineamenti |
| :-- | :-- |
| "Hey Metis", voce reale | 0,954 – 0,996 → **+0,042** |
| "Ehi mi senti" | 0,152 – 0,891 → **+0,739** |
| rumore ambientale | 0,016 – 0,969 → **+0,953** |

Il melspettrogramma si calcola su una griglia ancorata all'inizio del flusso:
spostare il segnale rispetto a quella griglia produce feature diverse.

**Se rivaluti clip salvate, spazzola gli allineamenti e prendi il massimo.**
Una lettura sola sottostima il rischio, e spiega perché un punteggio misurato
ieri non si riproduce oggi.

La stessa misura suggerisce però la regola a **doppia fase**: due rilevatori
sfasati di 256 campioni, scatta solo se sono d'accordo entrambi. I veri
positivi sono robusti allo spostamento, i quasi-falsi no. Sulle clip
disponibili non costa nulla sui positivi (93,3% in entrambi i casi) e azzera
i picchi ambientali (6,2% → 0%). È in `config/wakeword.toml` come
`dual_phase`, **disattivata**: due clip ambientali non sono un campione, e
`record_ambient.py` conta le due regole in parallelo sulla stessa audio
durante le 8 ore di NFR-6.

## Storia delle versioni

| file | esito |
| :-- | :-- |
| `hey_metis.onnx` | **in produzione** = copia di v3 |
| `hey_metis_v3_reali.onnx` | addestrato con 2880 negativi duri **reali** dalla seduta NFR-7. Su 39 clip tenute fuori dall'addestramento: **0 falsi**, 14/15 pronunce rilevate, margine **+0,953** |
| `hey_metis_v1.onnx` | senza duri reali. Sulle stesse 39 clip: 18 falsi, margine +0,000 |

La lezione dei duri **sintetici** (v2, 20 settembre) resta valida: peggioravano
il margine da +0,184 a +0,122. Quelli **reali** fanno l'opposto. La differenza
non è la quantità, è che vengono dal microfono vero nella stanza vera.

**Quello che v3 NON risolve.** Rivalutando su 8 allineamenti:

| clip | v1 | v3 |
| :-- | :-- | :-- |
| "Hey Metis", tua voce | 1,000 – 1,000 | 1,000 – 1,000 |
| auto-innesco NFR-7 (Piper) | 0,999 – 0,999 | **0,000 – 0,000** |
| rumore ambientale | 0,244 – 0,916 | **0,000 – 0,001** |
| "Ehi mi senti" (voce umana) | 0,992 – 0,999 | 0,247 – **0,994** |

La confusione con "Ehi mi senti" resta: quella frase non era fra i negativi
duri, perché viene da `live_test.py` e non dalla seduta NFR-7. È un problema
di NFR-6, non di NFR-7, e la cura è la stessa — negativi umani **reali**, che
la seduta ambientale da 8 ore raccoglie mentre misura.

### Attenzione ai pesi esterni

`torch.onnx.export` scrive i pesi in un file **esterno con nome fisso**. Per
mezza giornata tutti i `.onnx` di questa cartella hanno puntato allo stesso
`hey_metis.onnx.data`: copiare un modello copiava solo il grafo da 14 KB, e
ogni addestramento sovrascriveva i pesi di tutte le versioni "archiviate".
Abbiamo creduto di avere in produzione un modello che era già stato
sostituito.

`train_model.py` adesso ricompatta l'export in un file unico e **verifica la
dimensione**: sotto i 100 KB solleva. Un modello che non sta in un file solo
non è una versione, è un riferimento a qualcos'altro.

## Criteri di uscita (M1)

| Metrica | Soglia | Stato |
| :-- | :-- | :-- |
| Mancati riconoscimenti | < 10% su 50 tentativi | 6,7% su 15 |
| Falsi risvegli | < 1 ogni 8 ore di uso normale | da misurare |
| Auto-inneschi con Metis che parla | 0 in 2 h | da misurare |

Se non si arriva, il piano B è Porcupine. Il push-to-talk copre il caso nel
frattempo, quindi il progetto non si blocca.
