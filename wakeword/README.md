# Addestramento wake word "Hey Metis"

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

## Preparazione

```powershell
py -3.12 -m venv .venv-train
.\.venv-train\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv-train\Scripts\python.exe -m pip install openwakeword audiomentations torchinfo torchmetrics piper-tts
```

## Pipeline

1. **Positivi sintetici** — Piper genera migliaia di "Hey Metis" variando voce,
   velocità e intonazione. Vedi `generate_positives.py`.
2. **Negativi mirati** — è il passaggio che quasi tutte le guide saltano ed è
   quello che determina il tasso di falsi risvegli. In italiano servono
   "metti", "mettiamo", "Mattia", "ehi", "hey", "mettiamoci", "amnesie":
   parole comuni foneticamente vicine. Vedi `generate_negatives.py`.
3. **Negativi generici** — dataset di rumore e parlato forniti dal progetto
   openWakeWord.
4. **Augmentation** — rumore di fondo a SNR variabile, riverbero, e
   **registrazioni del microfono reale**: la risposta in frequenza del Blue
   Yeti conta, e un modello addestrato solo su voci sintetiche non generalizza.
5. **Training ed export** in `data/wakeword/hey_metis.onnx`.

## Criteri di uscita (M1)

| Metrica | Soglia |
| :-- | :-- |
| Mancati riconoscimenti | < 10% su 50 tentativi |
| Falsi risvegli | < 1 ogni 8 ore di uso normale |

Se non si arriva, il piano B è Porcupine. Il push-to-talk copre il caso nel
frattempo, quindi il progetto non si blocca.
