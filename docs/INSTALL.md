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
| `tts.toml` | Motore (Piper), voce e **velocità di lettura** (`[voce] velocita`, oggi 1,3: vedi i commenti nel file) |
| `wakeword.toml` | Wake word: **spenta in V1.0** (decisione D1). Si attiva con il push-to-talk |
| `apps.toml` | Allowlist delle applicazioni che Metis può aprire |
| `email.toml` | Destinatari ammessi: nel repository è **vuoto** di proposito |
| `email.local.toml` | I tuoi indirizzi veri. **Ignorato da git**, da creare a mano (§4.1) |
| `home_assistant.toml` | Dispositivi controllabili, con i loro limiti |
| `settings.toml` | Posizione della finestra. Locale, ignorato da git |
| `gui.toml` | Interfaccia: nel repository è **vuoto** (nessuna città) |
| `gui.local.toml` | Città del meteo e preferenze dell'Hub. **Ignorato da git**, lo scrivono le Impostazioni (§4.5) |
| `navigazione.toml` | Clic per numero (PHASE2): parole che chiedono conferma, parole su cui non si clicca mai (§5.1) |

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

### 4.5 Meteo e impostazioni dell'Hub

Il pannello del meteo usa **Open-Meteo**: nessun account, nessuna chiave. Dal PC escono solo
le coordinate, ogni 15 minuti, e una volta il nome della città per trovarle. La città si
sceglie dalle **Impostazioni** (⚙ in alto a destra nell'Hub), insieme a "riduci animazioni",
vista all'avvio e voce spenta all'avvio. Finisce in `config\gui.local.toml`:

```toml
[meteo]
citta = "Milano"

[interfaccia]
riduci_animazioni = false
vista_avvio = "minimal"      # minimal | hub | diagnostica
muto_avvio = false
```

Senza rete il pannello mostra l'ultimo dato con la sua ora, fino a tre ore; poi lo dice.
L'ultima lettura e le coordinate trovate stanno in `data\meteo.json`.

---

## 5. Avvio

Il modo più semplice è un doppio clic su **`Metis.bat`** nella radice del progetto: parte
senza console. `Metis.bat --console` tiene aperta la finestra con i log, per quando qualcosa
non parte; le altre opzioni (`--fullscreen`, `--no-tools`, …) passano all'applicazione.

```powershell
.venv\Scripts\python.exe -m metis.gui.app                # la vista delle impostazioni (Minimal)
.venv\Scripts\python.exe -m metis.gui.app --fullscreen   # Hub
.venv\Scripts\python.exe -m metis.gui.app --diagnostica  # Diagnostica (la control room di PHASE0)
.venv\Scripts\python.exe -m metis.core.app               # solo console, senza GUI
```

**Le tre viste.** La **Minimal** sta in un angolo, sempre in primo piano. L'**Hub** è la vista
di tutti i giorni: il nucleo al centro dice lo stato con il colore e con il movimento, a
destra la conversazione, dove si può anche **scrivere** (stesse regole e stesse conferme
della voce); "muto" toglie la voce, e le risposte restano scritte. La **Diagnostica** serve a
capire perché Metis ha fatto qualcosa: audit, contesto del prompt, latenze, comandi rapidi.
Con la finestra nascosta o in tray le animazioni si fermano.

| Scorciatoia | Effetto |
| :-- | :-- |
| `Ctrl+Alt+M` | Push-to-talk: apre l'ascolto, oppure interrompe Metis mentre parla |
| `Ctrl+Alt+Shift+M` | Kill switch: zittisce e sospende le azioni T2/T3 |

**L'icona nella tray** ha il colore dello stato (lo stesso dell'overlay), un anello rosso
quando il kill switch è attivo e due barre bianche quando l'ascolto è in pausa. Dal menu:
mostrare le tre viste, kill switch, **Pausa ascolto** (il microfono non arriva a nessuno;
il push-to-talk interrompe ancora Metis ma non riapre l'ascolto) ed **Esci**.

Con la tray presente, **chiudere la finestra non chiude Metis**: si esce da *Esci*, che è
l'unico percorso che ferma thread e scheduler e rilascia il microfono.

**Avvio robusto.** Metis aspetta Ollama fino a 120 s; se il microfono non c'è aspetta che
venga collegato invece di chiudersi; se la GPU finisce la memoria sposta Whisper sul
processore. Quando l'avvio riesce saluta a voce, una volta.

### 5.1 Navigare: YouTube e i numeri (PHASE2)

**YouTube.** "Mettimi su YouTube un video rilassante", "fammi sentire Bohemian Rhapsody",
"apri Chrome e mettimi su YouTube…": Metis apre in Chrome il primo video della ricerca.
"Cerca su YouTube ricette di pasta" apre la pagina dei risultati. Il video lo sceglie YouTube,
non Metis; se parte da solo dipende dalla politica di Chrome sull'audio automatico. Il titolo
compare nell'Hub come riga di sistema.

**I numeri.** Con la finestra che interessa davanti (un sito in Chrome, VS Code, un'altra
applicazione), a voce:

| Frase | Effetto |
| :-- | :-- |
| "Mostra i numeri" | Un numero su ogni link, pulsante, scheda e casella visibile (al massimo 99) |
| "Clicca il 7" (anche "clicca sul sette") | Clic sull'elemento 7. Se nel frattempo la pagina si è mossa, **non clicca** e lo dice |
| "Scorri giù" / "scorri su" (anche "pagina giù", "scendi", "sali") | Un blocco, cioè una schermata (Pag↓/Pag↑). I numeri spariscono, e si richiedono |
| "Scorri giù di tre pagine" | Più blocchi, fino a 5 |
| "Vai in cima" / "vai in fondo" | L'inizio e la fine della pagina |
| "Scorri un po' giù" | Un passo piccolo, con la rotellina |
| "Torna indietro" / "vai avanti" | La pagina precedente e la successiva |
| "Chiudi la scheda", "chiudi la seconda scheda", "riapri la scheda", "nuova scheda" | Le schede del browser |
| "Ricarica la pagina", "scheda successiva", "vai alla seconda scheda", "ingrandisci la pagina", "zoom normale" | Il browser |
| "Pausa", "riprendi", "brano successivo", "canzone precedente" | Il lettore che sta suonando (YouTube, Spotify…), anche dietro |
| "Alza/abbassa il volume (di 20)", "volume al 30", "muto", "togli il muto" | Il volume di Windows, anche quello della voce di Metis |
| "Avanti/indietro di 10 secondi", "schermo intero", "sottotitoli" | Il video di YouTube in primo piano (non con il cursore in un campo di testo) |
| "Scrivi nel 12: ricette di pasta" | Scrive nel campo con quel numero (i campi di testo prendono numero). Senza numero: "digita …" nel campo dove c'è il cursore |
| "Premi invio" | Con il cursore in un campo di testo **chiede sempre conferma**, e mostra il testo che parte |
| "Nascondi i numeri" | Li toglie. Spariscono anche da soli dopo 60 s e dopo ogni clic |

I clic su elementi che **pubblicano, inviano, seguono, eliminano** ("Condividi", "Mi piace",
"Pubblica", …) chiedono conferma come le azioni T3: dialogo e domanda a voce ("Il 7 è
'Condividi'. Confermo?"). Su **pagamenti e accessi** ("Acquista", "Paga", "Accedi", …) Metis
non clicca mai. Le parole stanno in `config\navigazione.toml`, in italiano e in inglese.

**La bolla.** Prima di ogni clic, per numero o per nome, una bolla si stringe sul punto dove il
clic sta per andare, e resta almeno un quarto di secondo (`[evidenza] attesa_ms` in
`config\navigazione.toml`); al clic parte un'onda. Durante una conferma la bolla è fucsia e resta
sull'elemento finché non si risponde. Se la pagina si è mossa, un lampo rosso mostra dove
l'elemento era. Con "riduci animazioni" (Impostazioni) la bolla è ferma.

Anche "clicca su Contatti" (per nome) continua a funzionare; se i candidati sono più d'uno,
Metis mette i numeri solo su quelli. Un elemento sensibile trovato per nome riceve il numero 1
e si clicca con "clicca il 1", che passa dalla conferma.

Cosa sapere:
- I numeri si vedono solo con l'interfaccia grafica, e mai in Esplora risorse, nel terminale e
  nelle altre finestre in cui Metis non scrive (§8.4 della specifica).
- Il testo della pagina non arriva mai al modello: i nomi degli elementi li legge solo Metis,
  per riconoscerli al momento del clic e per le conferme.
- Chrome non richiede niente di particolare: i numeri si leggono con UI Automation, come nelle
  altre applicazioni. La prima volta su una finestra appena aperta servono fino a ~1 s,
  poi ~0,1 s.
- "Clicca il 7" **scritto** nell'Hub viene rifiutato come ogni altra azione T2 mentre Metis è
  in primo piano: si usa la voce, con la finestra giusta davanti.

### 5.2 Le frasi non capite (PHASE4)

Quando Metis non capisce una frase (chiede di ripetere, toglie un'azione proposta, uno
strumento non riesce…), la frase finisce nel pannello **FRASI NON CAPITE** della Diagnostica,
sotto i comandi rapidi; nell'Hub la tessera Sessione dice quante ce ne sono da rivedere, e un
clic porta lì. "Rivedi le frasi…" le mostra una per una:

| Azione | Effetto |
| :-- | :-- |
| **Crea comando…** | L'editor dei comandi con la frase già scritta; se il modello aveva proposto uno strumento, c'è anche lui, senza argomenti da completare |
| **Variante di…** | La frase si aggiunge a un comando che esiste già |
| **Segnala** | La frase va fra quelle da passare a chi sviluppa; "Esporta segnalate…" le scrive in Markdown |
| **Ignora** | Sparisce dal pannello |

Le frasi con un numero, una quantità o un testo ("clicca su ottanto uno") non possono diventare
comandi, che hanno azioni fisse: si segnalano. Una frase nuova deve avere almeno due parole oltre
alle cortesie e non essere già riconosciuta; se no, l'editor dice perché.

In testa al pannello c'è la **quota dei turni non capiti** degli ultimi 30 giorni: è la misura
di quanto Metis è macchinosa. Le decisioni stanno in `data\frasi_decise.json`; per ricominciare
da capo basta cancellarlo. I turni si leggono da `[frasi] dal` in `config\gui.toml` in poi.

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
.venv\Scripts\python.exe tests\nfr\verifica_nfr.py --dal 2026-09-26T10:00
                                                               # solo da quell'istante: una prova sola
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
| "Mostra i numeri" non mostra niente | La finestra è ridotta a icona o coperta? È una di quelle vietate (Esplora risorse, terminale)? |
| "La pagina è cambiata" a ogni clic | Il contenuto si muove da solo (un feed): "mostra i numeri" e il numero subito dopo |
| Tutto il resto | `data\logs\metis.jsonl`: una riga JSON per evento, con lo stato e il turno |

---

## 10. Disinstallazione

1. `scripts\install_autostart.ps1 -Disinstalla`
2. Credenziali: `scripts\setup_secrets.py --cancella <chiave>` per ognuna, oppure
   Gestione credenziali di Windows → Credenziali generiche → voci `metis`.
3. Cancellare la cartella del repository (con `data\`: audit, promemoria, log).
4. Facoltativo: `ollama rm qwen3:8b`; la cache di Hugging Face per Whisper e Kokoro.
