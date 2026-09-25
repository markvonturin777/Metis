# Metis: installazione e configurazione

Scritto per chi riprende in mano Metis fra sei mesi e ha dimenticato metà delle decisioni.
Ogni passo dice **cosa** fare e, quando non è ovvio, **perché** si fa così.

---

## 1. Prerequisiti

| Cosa | Versione | Note |
| :-- | :-- | :-- |
| Windows | 10 o 11, 64 bit | Metis usa UI Automation, il Credential Manager e l'Utilità di pianificazione |
| GPU NVIDIA | 8 GB di VRAM | Qwen3 8B (~5,6 GB) e Whisper `small` (~0,3 GB) insieme. Driver recente |
| Python | **3.12** | Non la 3.13: diverse dipendenze native non hanno ancora le wheel |
| Ollama | recente | Serve il modello linguistico, vedi §3 |
| Microfono | qualunque | Sviluppato con un Blue Yeti su WASAPI a 48 kHz |
| Spazio su disco | ~6 GB | venv ~3 GB, modello ~5 GB (in Ollama), voci ~160 MB |

Metis **non** va eseguito come amministratore, né va installato da una console elevata.

---

## 2. Codice e ambiente

```powershell
git clone <repository> Metis
cd Metis
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Tutti i comandi di questa guida si lanciano **dalla radice del repository**: `config\` e
`data\` sono percorsi relativi.

---

## 3. Modelli

I modelli restano **fuori dal codice** e fuori dal bundle: si aggiornano senza ricompilare.

| Modello | Dove sta | Come si installa |
| :-- | :-- | :-- |
| Qwen3 8B (Q4_K_M) | Ollama | `ollama pull qwen3:8b` |
| Whisper `small` | cache di Hugging Face (`%USERPROFILE%\.cache\huggingface`) | si scarica da solo al primo avvio (~480 MB) |
| Voce Piper `it_IT-paola-medium` | `data\piper\` | `.venv\Scripts\python.exe -m piper.download_voices --download-dir data\piper it_IT-paola-medium` |
| Kokoro (voce di riserva) | cache di Hugging Face | si scarica da solo la prima volta che serve (Piper guasto) |
| Silero VAD | dentro il pacchetto `silero_vad` | niente da fare |

Il modello Ollama è configurato in `metis/llm/client.py` (`MODEL`) e `metis/llm/toolcall.py`.
Router e conversazione usano la **stessa** finestra di contesto (`NUM_CTX = 8192`): se
differissero, Ollama ricaricherebbe il modello a ogni cambio (3,6 s per turno, misurati in M7).

---

## 4. Configurazione

Tutto in `config\`. I file del repository contengono **solo valori di esempio o vuoti**.

| File | Cosa decide |
| :-- | :-- |
| `stt.toml` | Modello Whisper, device (`cuda`), lingua, vocabolario di dominio |
| `tts.toml` | Motore (Piper) e voce |
| `wakeword.toml` | Wake word: **spenta in V1.0** (decisione D1). Si attiva con il push-to-talk |
| `apps.toml` | Allowlist delle applicazioni che Metis può aprire |
| `email.toml` | Destinatari ammessi: nel repository è **vuoto** di proposito |
| `email.local.toml` | I tuoi indirizzi veri. **Ignorato da git**, da creare a mano (§4.1) |
| `home_assistant.toml` | Dispositivi controllabili, con i loro limiti |
| `settings.toml` | Posizione della finestra. Locale, ignorato da git |

### 4.1 Posta

`email.toml` è nel repository: un indirizzo scritto lì finisce pubblicato al primo push.
Gli indirizzi veri vanno in `config\email.local.toml`, stesso formato:

```toml
[allowlist]
indirizzi = ["tuo.indirizzo@gmail.com"]

[utente]
indirizzo = "tuo.indirizzo@gmail.com"   # chi è "me" in "mandami una mail"
```

Le allowlist dei due file si **uniscono**; per `[utente]` vince il file locale. `[utente]`
dice *a chi* scrivere, ma non autorizza: l'indirizzo deve comparire anche in `[allowlist]`.

### 4.2 Segreti

Credenziali SMTP, token di Home Assistant e chiave Brave vivono nel **Credential Manager di
Windows**, mai su file:

```powershell
.venv\Scripts\python.exe scripts\setup_secrets.py            # chiede quelle mancanti
.venv\Scripts\python.exe scripts\setup_secrets.py --stato    # mostra cosa c'è (mascherato)
```

| Chiave | Esempio | Note |
| :-- | :-- | :-- |
| `smtp_host` | `smtp.gmail.com` | |
| `smtp_port` | `465` | 465 = SSL implicito, 587 = STARTTLS. Mai in chiaro |
| `smtp_user` | l'indirizzo | È anche il mittente |
| `smtp_password` | | Con Gmail: una **password per app** (serve la verifica in due passaggi) |
| `ha_url` | `ws://homeassistant.local:8123/api/websocket` | |
| `ha_token` | | Profilo utente di Home Assistant → token di accesso a lunga durata |
| `brave_api_key` | | Facoltativa: ripiego della ricerca web |

### 4.3 Home Assistant

In `config\home_assistant.toml` ogni dispositivo ha un `entity_id`, un nome, gli alias con
cui lo si chiama a voce e i limiti (durata massima, erogazioni al giorno). Gli `entity_id`
si leggono in Home Assistant → Impostazioni → Dispositivi ed entità. Un dispositivo che non
è in questo file, per Metis, non esiste.

### 4.4 Variabili d'ambiente

| Variabile | Effetto |
| :-- | :-- |
| `METIS_HOME` | Cartella con `config\` e `data\`. Serve solo al bundle installato altrove (§6) |

---

## 5. Avvio

```powershell
.venv\Scripts\python.exe -m metis.gui.app                # overlay minimal
.venv\Scripts\python.exe -m metis.gui.app --fullscreen   # control room
.venv\Scripts\python.exe -m metis.core.app               # solo console, senza GUI
```

| Scorciatoia | Effetto |
| :-- | :-- |
| `Ctrl+Alt+M` | Push-to-talk: apre l'ascolto, oppure interrompe Metis mentre parla |
| `Ctrl+Alt+Shift+M` | Kill switch: zittisce e sospende le azioni T2/T3 |

**L'icona nella tray** ha il colore dello stato (lo stesso dell'overlay), un anello rosso
quando il kill switch è attivo e due barre bianche quando l'ascolto è in pausa. Dal menu:
mostrare le due viste, kill switch, **Pausa ascolto** (il microfono non arriva a nessuno;
il push-to-talk interrompe ancora Metis ma non riapre l'ascolto) ed **Esci**.

Con la tray presente, **chiudere la finestra non chiude Metis**: si esce da *Esci*, che è
l'unico percorso che ferma thread e scheduler e rilascia il microfono.

**Avvio robusto.** Metis aspetta Ollama fino a 120 s; se il microfono non c'è aspetta che
venga collegato invece di chiudersi; se la GPU finisce la memoria sposta Whisper sul
processore. Quando l'avvio riesce saluta a voce, una volta.

---

## 6. Avvio automatico

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Anteprima    # mostra, non tocca
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1               # registra
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Disinstalla  # toglie
```

Registra l'attività **"Metis"** nell'Utilità di pianificazione:

- all'accesso **del tuo utente**, con **60 s di ritardo** (Ollama, rete e microfono USB
  devono avere il tempo di comparire);
- **`RunLevel Limited`**: mai amministratore. Lo script si rifiuta di girare da una console
  elevata e, dopo la registrazione, rilegge cosa Windows ha registrato davvero;
- nessun limite di durata (il default di Windows è 72 ore: ucciderebbe Metis al terzo giorno);
- una sola istanza; fino a 3 riavvii a un minuto di distanza **se l'avvio fallisce**.
  Un crash dopo l'avvio non viene coperto da qui: è un limite dell'Utilità di pianificazione.

Esegue `dist\Metis\Metis.exe` se il bundle esiste, altrimenti `.venv\Scripts\pythonw.exe -m
metis.gui.app`. In entrambi i casi non c'è console: il log va in `data\logs\metis.jsonl` e
gli errori imprevisti in `data\logs\metis.stderr.log`.

---

## 7. Bundle (facoltativo)

```powershell
.venv\Scripts\python.exe -m PyInstaller metis.spec --noconfirm
```

Produce `dist\Metis\` (modalità **onedir**: onefile scompatterebbe centinaia di MB a ogni
avvio), circa **3,1 GB**: ~2 GB sono cuBLAS e cuDNN 9, inclusi perché Whisper non parte
senza e sul sistema di solito non ci sono. I modelli restano fuori (§3). `Metis.exe` trova `config\` e `data\` in quest'ordine:
`METIS_HOME`, la cartella dell'eseguibile, due livelli sopra (cioè la radice del repository
quando il bundle sta in `dist\Metis\`).

Per un'installazione fuori dal repository: copiare `dist\Metis\` insieme a `config\` e
`data\piper\` in una cartella, e metterli uno accanto all'altro, oppure impostare `METIS_HOME`.

---

## 8. Verifiche

```powershell
.venv\Scripts\python.exe -m pytest -q                          # suite completa
.venv\Scripts\python.exe -m ruff check .                       # lint
.venv\Scripts\python.exe tests\nfr\verifica_nfr.py             # i 10 NFR dai dati raccolti
.venv\Scripts\python.exe tests\soak\run_soak.py --ore 72       # soak (tre giorni)
.venv\Scripts\python.exe tests\soak\run_soak.py --ore 0.25 --intervallo-min 1 --scala 0.005
                                                               # soak di prova, ~15 minuti
```

La verifica NFR non spunta niente senza dati sufficienti: NFR-1 vuole 100 interazioni
**reali** (dal log d'uso, non dal soak, che scrive in una cartella sua in `data\soak\`).

---

## 9. Quando qualcosa non va

| Sintomo | Dove guardare |
| :-- | :-- |
| Metis non parte all'accesso | `data\logs\metis.stderr.log`; Utilità di pianificazione → "Metis" → Cronologia |
| "L'infrastruttura di inferenza non risponde" | Ollama è acceso? `ollama ps`. Metis riprova da solo ogni 5 s |
| "Il microfono non risponde" | Il device è collegato? Metis riprova ogni 2 s e lo dice quando torna |
| Nessuna notifica desktop | Impostazioni → Sistema → Notifiche (su questa macchina erano spente: `ToastEnabled=0`) |
| Risposte lente (secondi) | `ollama ps`: il modello deve essere al 100% GPU e con contesto 8192 |
| Un'azione è stata negata | Vista audit nella control room, oppure `data\audit.db` |
| Tutto il resto | `data\logs\metis.jsonl`: una riga JSON per evento, con lo stato e il turno |

---

## 10. Disinstallazione

1. `scripts\install_autostart.ps1 -Disinstalla`
2. Credenziali: `scripts\setup_secrets.py --cancella <chiave>` per ognuna, oppure
   Gestione credenziali di Windows → Credenziali generiche → voci `metis`.
3. Cancellare la cartella del repository (con `data\`: audit, promemoria, log).
4. Facoltativo: `ollama rm qwen3:8b`; la cache di Hugging Face per Whisper e Kokoro.
