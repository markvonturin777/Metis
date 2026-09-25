> ⚠️ **DOCUMENTO ARCHIVIATO — non più normativo.**
> Sostituito da [`Metis_V1.0_Specifica_Ufficiale.md`](Metis_V1.0_Specifica_Ufficiale.md) in data 2026-09-20.
> Conservato come storico della fase di ideazione. Le correzioni applicate sono elencate nel §2 (Changelog) della specifica ufficiale, e motivate in [`report_bozza_Metis_V16.md`](report_bozza_Metis_V16.md).

# **Bozza di Progetto: Assistente Personale "Metis" V16**

## **1\. Obiettivo del Progetto**

Realizzazione di un assistente personale attivo/silente in background su PC Windows, provvisto di un'interfaccia grafica dedicata basata su PyQt6/PySide6 con selettore di modalità (semplificata compatto-minimale vs. completa a tutto schermo), visualizzazione in tempo reale delle conversazioni e monitoraggio hardware, in grado di eseguire automazioni avanzate di sistema e del browser (apertura software, recherches web, controllo esteso di mouse e tastiera con supporto a schermi multipli), consultare e recuperare informazioni da Internet in tempo reale, gestire dispositivi Smart Home, gestire promemoria e notifiche schedulate (es. invio email temporizzate) e interagire tramite interfaccia vocale naturale (Speech-to-Text e Text-to-Speech) a bassa latenza.

## **2\. Specifiche Hardware di Riferimento**

Il sistema verrà eseguito in locale sfruttando il seguente hardware:

> * **CPU:** AMD Ryzen 7 5800X  
> * **RAM:** 32 GB  
> * **GPU:** NVIDIA GeForce RTX 2070 Super (per accelerazione hardware e inferenza locale dei modelli)

## **3\. Persona e Stile di Comunicazione (System Prompt Guidelines)**

Metis possiede una personalità definita per l'interazione vocale e testuale, ispirata a un'assistenza di tipo "Jarvis", elegante e professionale ma non eccessivamente altolocata:

> * **Tono di Voce:** Formale ma scherzoso, elegante, con un tocco di arguzia e ironia discreta.  
> * **Stile Verbale:** Risposte fluide, precise, agili e mai pesanti, capaci di coniugare efficienza tecnica e uno stile comunicativo naturale.  
> * **Linee Guida del System Prompt:** Il modello deve mantenere la massima accuratezza operativa, aggiungendo sfumature argute e raffinata ironia senza mai apparire servile o lezioso.  
> * **Esempio di Risposta Tipo:** "I sistemi sono perfettamente operativi. L'area di sviluppo è pronta e i repository sono allineati. Le danze abbiano inizio non appena lo desidera."

## **4\. Interfaccia Grafica (GUI), Architettura Multithreading e Dashboard Hardware**

L'interfaccia grafica desktop viene sviluppata utilizzando il framework **PyQt6 / PySide6** per garantire elevate prestazioni, reattività dell'UI e completo supporto alle funzionalità native di Windows e alla gestione di layout sia ridotti che a tutto schermo:

### **4.1 Stack Tecnologico GUI e Asincronia (Segnali/Slot & QThread)**

> * **Framework di Riferimento:** PyQt6 / PySide6 per l'elaborazione dell'interfaccia utente.  
> * **Architettura Multithreading (QThread):** Le attività ad alto impatto computazionale (ascolto continuativo STT, inferenza dell'LLM locale su GPU e generazione della sintesi vocale Kokoro TTS) vengono eseguite su thread distinti gestiti tramite QThread per evitare blocchi della GUI (UI freezing).  
> * **Disaccoppiamento via Segnali e Slot:** La comunicazione tra l'orchestratore di background, i moduli di IA e la GUI avviene esclusivamente mediante l'architettura a Segnali e Slot (pyqtSignal / Signal). Ciò garantisce l'aggiornamento sicuro dei widget da thread secondari in modo asincrono.

### **4.2 Modalità di Interfaccia e Trascrizione Conversazionale in Tempo Reale**

> * **Selettore Modalità GUI:**  
  * **Modalità Semplificata (Minimal/Widget Overlay):** Finestra compatta o widget discreto sempre in primo piano, ideale durante le sessioni di lavoro per monitorare unicamente lo stato dell'ascolto vocale e gli indicatori essenziali.  
  * **Modalità Completa e Immersiva (Fullscreen Control Room):** Layout esteso a tutto schermo con plancia di comando, visualizzazione dei log di sistema, gestione dei comandi e dashboard hardware.  
> * **Trascrizione Vocale e Feedback Risposte in Tempo Reale:**  
  * **Visualizzazione Input Utente (STT):** L'interfaccia mostra a schermo la trascrizione in tempo reale del parlato rilevato dal modulo STT (Vosk/Whisper) man mano che l'utente pronuncia le frasi.  
  * **Visualizzazione Output Assistente (TTS/LLM):** Il testo generato da Qwen 3 / Ollama e riprodotto vocalmente dal motore Kokoro TTS viene stampato e formattato a schermo all'interno dell'area conversazione simultaneamente alla risposta audio.  
> * **Gestore Comandi Rapidi & Console Log:** Sezione di controllo visivo per la modifica della memoria dei comandi vocali personalizzati e console di diagnostica per gli script Python di sistema.

### **4.3 Dashboard di Monitoraggio Risorse Hardware in Tempo Reale**

> * **Integrazione psutil & pynvml:** Tramite le librerie Python psutil (per CPU e RAM) e pynvml (NVIDIA Management Library per GPU/VRAM), la GUI raccoglie costantemente la telemetria dell'hardware.  
> * **Visualizzazione Metriche Hardware:** Grafici e barre di avanzamento aggiornate in tempo reale nell'interfaccia per monitorare:  
  * Percentuale di utilizzo CPU e occupazione RAM (32 GB).  
  * Occupazione VRAM e temperatura della GPU NVIDIA GeForce RTX 2070 Super durante l'inferenza locale.  
> * **Metriche Latenza IA:** Indicatore visivo del Time To First Token (TTFT), velocità di generazione del testo (token/s) e tempo di sintesi audio di Kokoro TTS.

## **5\. Strategie Anti-Allucinazione, Mitigazione del Drifting e Vincoli Imperativi di Sicurezza**

Per prevenire derive concettuali (drifting) e generazioni di informazioni errate o inventate (allucinazioni) tipiche dei modelli locali, il sistema adotta una serie di vincoli architetturali e di prompting:

### **5.1 Grounding e Verification via Web Autonomo**

> * **Ricerca in Tempo Reale:** Per query che richiedono dati fattuali aggiornati, specifiche tecniche o notizie, l'LLM non attinge alla sola memoria dei pesi locali ma invoca prioritariamente il *Modulo Ricerca Web Autonoma*.  
> * **RAG & Context Injection:** I dati recuperati da fonti web verificate vengono inseriti direttamente nel contesto del prompt per vincolare le risposte del modello a fatti reali.

### **5.2 System Prompt Guardrails & Direttive di Incertezza**

> * **Dichiarazione Esplicita di Incertezza:** Nel System Prompt è integrata la direttiva perentoria di ammettere l'incertezza e dichiarare "Informazione non presente nei sistemi" invece di tentare di estrapolare o ipotizzare risposte in assenza di dati certi.  
> * **Scope Bounding:** Definizione rigida del perimetro d'azione: il modello rifiuta di rispondere a quesiti speculativi fuori dal contesto operativo o privi di riscontro fattuale.

### **5.3 Vincolo Imperativo Accesso File System (File Personali)**

> * **Divieto Assoluto di Manipolazione File:** L'assistente Metis NON possiede alcuna autorizzazione per accedere, organizzare, rinominare, spostare, modificare o eliminare file e cartelle personali dell'utente nel File System locale o di rete.  
> * **Guardrail di Sicurezza sull'Esecuzione:** L'Orchestratore e i moduli di automazione bloccano a livello di codice qualsiasi funzione o comando (es. operazioni su librerie os, shutil, o script shell) rivolto alla manipolazione di file utente.

### **5.4 Bounding dell'Output e Controllo dell'Esecuzione**

> * **Temperature Tuning:** Mantenimento di parametri di temperatura ridotti (es. 0.1 \- 0.3) per compiti di automazione e function calling, riducendo la varianza e l'imprevedibilità.  
> * **Structured Output Validation:** L'output destinato all'esecuzione di comandi di sistema (pyautogui, pygetwindow, pywinctl) deve rispettare uno schema rigido (es. JSON/Pydantic) validato dall'Orchestratore prima dell'effettiva esecuzione su OS.

## **6\. Stack Software, Strumenti e Architettura**

L'architettura del sistema è strutturata in moduli per garantire modularità, privacy ed esecuzione offline/ibrida:

| Componente | Tecnologia / Modello / Strumento | Descrizione e Librerie Specifiche   |
| :---- | :---- | :---- |
| Linguaggio Base | Python | Linguaggio principale per l'orchestrazione dei moduli e delle automazioni. |
| Orchestratore | Script / Servizio Background Python | Gestisce il flusso dei comandi vocali, la logica di decisione, la validazione degli schemi e l'esecuzione delle azioni con blocco rigido per operazioni sui file dell'utente. |
| Interfaccia Grafica (GUI) | PyQt6 / PySide6 | Framework grafico desktop con architettura a Segnali/Slot, gestione multithread con QThread, supporto alla doppia modalità (semplificata e fullscreen) e trascrizione live. |
| Monitoraggio Hardware | Librerie Python: psutil, pynvml | Telemetria in tempo reale di CPU, RAM, VRAM/Temperatura GPU RTX 2070 Super e latenza dell'LLM. |
| Esecuzione LLM Locale | Ollama / LM Studio | Piattaforme per l'infrastruttura e la gestione dei modelli open-weight su GPU con Temperature controllata. |
| Modulo Ricerca Web Autonoma | Librerie Python: requests, duckduckgo\_search, beautifulsoup4 / Search APIs | Script Python per interrogare API di ricerca online, recuperare risultati ed estrarre il contenuto delle pagine web per la sintesi e il grounding dell'LLM. |
| Automazione OS, Mouse & Tastiera | Librerie Python: subprocess, pyautogui, pygetwindow, pywinctl, pynput | subprocess per eseguibili; pyautogui/pynput per simulazione dinamica di clic, trascinamento e tastiera; pygetwindow/pywinctl per manipolazione e spostamento finestre tra schermi multipli. Operazioni su File System personale disabilitate. |
| Memoria Comandi Personalizzati | Database JSON / DB Locale | Mappatura dinamica delle frasi di attivazione personalizzate e delle relative azioni/script da eseguire. |
| Notifiche e Schedulazione | Librerie Python: apscheduler, smtplib, email, plyer | Gestione dei promemoria, invio automatico di email e notifiche desktop all'orario specificato via comandi vocali. |
| Speech-to-Text (STT) | Vosk / Whisper | Trascrizione vocale in testo totalmente locale e offline in tempo reale su GUI. |
| Text-to-Speech (TTS) | Kokoro (con alternative tipo Fish Speech / Qwen 3 TTS) | Sintesi vocale ad alta fedeltà con output testuale e vocale sincronizzato. |
| Domotica / Smart Home | Home Assistant | Hub per la gestione locale di dispositivi Tuya (friggitrice ad aria, distributore crocchette) e Xiaomi (videocamera). |

## **7\. Architettura dei Moduli e Requisiti Dettagliati**

### **Modulo Input (Ascolto Vocale e STT)**

> * **Cattura Audio:** Utilizzo continuo del microfono per rilevare l'input vocale in background.  
> * **Ascolto Continuo & STT:** Integrazione di modelli Speech-to-Text (Vosk / Whisper) per l'ascolto vocale continuo e la conversione del parlato in testo inviato asincronamente alla GUI via segnali Qt.

### **Modulo Processing (Analisi dell'Intento e LLM con Guardrails)**

> * **Infrastruttura LLM Locale:** Utilizzo di Ollama o LM Studio per l'esecuzione offline di modelli open-weight (es. Qwen 3\) accelerati via GPU.  
> * **Analisi dell'Intento & Verification:** Il modello analizza il testo per determinare se eseguire comandi locali, interrogare il web per grounding fattuale o schedulare attività. Se le informazioni mancano o sono incerte, applica le direttive anti-allucinazione dichiarando l'impossibilità di procedere.

### **Modulo Ricerca Web Autonoma**

> * **Integrazione Search API & Fetch:** Script dedicati in Python per il recupero di informazioni aggiornate sul Web via API o scraping controllato.  
> * **Elaborazione e Sintesi Grounded:** I dati recuperati vengono filtrati e passati come contesto vincolante al modello locale per garantire risposte basate unicamente su fonti reali.

## **8\. Modelli di Intelligenza Artificiale (LLM Open-Weight)**

Per preservare la privacy e garantire la massima velocità, si utilizzeranno modelli open-weight eseguiti in locale tramite Ollama o LM Studio.

### **Modelli in Valutazione:**

> * **Qwen 3 (14B / 30B):** Scelta principale per il bilanciamento tra capacità di ragionamento, comprensione dell'italiano, supporto alle direttive di sistema e coding per automazioni.  
> * **Devstral:** Alternativa ottimizzata per compiti avanzati di programmazione ed esecuzione comandi.

## **9\. Automazione del PC, Controllo Avanzato Periferiche e Domotica**

### **Automazione di Sistema, Controllo Mouse/Tastiera e Schermi Multipli**

Il modulo di automazione consente la simulazione precisa delle periferiche e la gestione avanzata dell'interfaccia utente di Windows tramite librerie quali pyautogui, pynput, pygetwindow e pywinctl:

> * **Simulazione Mouse e Tastiera:** Esecuzione vocale di eventi complessi di input quali clic sinistro/destro/doppio clic, drag-and-drop (trascinamento), scrolling e digitazione rapida di scorciatoie da tastiera.  
> * **Gestione Finestre e Monitor Multipli:** Possibilità di identificare e manipolare le finestre attive dell'OS, consentendo comandi per ridimensionare, minimizzare, massimizzare o spostare un'intera applicazione tra monitor differenti (es. spostamento immediato di una finestra Chrome dallo schermo principale a quello secondario).  
> * **Protezione File System:** Tutte le routine di automazione escludono la gestione diretta, lo spostamento, l'organizzazione o l'eliminazione dei file e delle cartelle personali dell'utente.

### **Mappatura Comandi Vocali Personalizzati**

Il sistema include una memoria locale (file JSON o database) per associare frasi personalizzate ad azioni precise sul PC:

| Comando Vocale | Azione / Script Eseguito   |
| :---- | :---- |
| "Inizia a lavorare" | Avvio simultaneo di Visual Studio Code e GitHub Desktop via subprocess. |
| "Sposta questa finestra sullo schermo a destra" | Identificazione della finestra attiva tramite pygetwindow/pywinctl e riposizionamento sulle coordinate del monitor secondario. |
| "Clicca sul link \[nome/posizione\]" | Emulazione del clic del mouse tramite pyautogui/pynput sulle coordinate target della pagina web o dell'applicazione. |
| "Aprimi le news dei mercati" | Apertura del browser web sulla pagina investing.com. |
| "Ricordami / mandami una mail domani alle 17:00" | Schedulazione invio email e promemoria desktop via apscheduler \+ smtplib. |
| "Cerca le ultime novità su \[argomento\]" | Invocazione dello script di ricerca web autonoma, recupero dei risultati con grounding e sintesi vocale da parte dell'LLM. |

### **Integrazione Smart Home (Home Assistant)**

> * **Ecosistema Tuya:** Controllo vocale di elettrodomestici intelligenti come la friggitrice ad aria e il distributore di cibo del gatto.  
> * **Ecosistema Xiaomi:** Integrazione e monitoraggio della videocamera di sicurezza e altri sensori domestici.

## **10\. Sintesi Vocale (TTS)**

La risposta vocale è affidata al modello Kokoro, scelto per la sua elevata qualità e naturalezza espressiva combinata a un footprint ridotto che garantisce massima fluidità sulla scheda grafica NVIDIA RTX 2070 Super.

## **11\. Prossimi Passi**

> 1. Configurazione dell'ambiente Python e test delle librerie subprocess, pyautogui, pygetwindow e pywinctl per comandi di spostamento finestre e simulazione mouse/tastiera su schermi multipli.  
> 2. Setup del progetto GUI in PyQt6/PySide6, configurando l'architettura a QThread e il disaccoppiamento via Segnali e Slot per le chiamate asincrone.  
> 3. Implementazione del widget di telemetria hardware in tempo reale basato su psutil (CPU, RAM) e pynvml (VRAM e temperatura GPU RTX 2070 Super).  
> 4. Sviluppo dei layout della GUI per il supporto sia alla modalità semplificata (overlay/widget) che alla modalità immersiva a tutto schermo, integrando la chat per la trascrizione live di STT e risposte TTS Kokoro.  
> 5. Implementazione della struttura di memoria JSON per la gestione dei comandi vocali personalizzati visibili da GUI.  
> 6. Definizione del System Prompt definitivo con guardrails anti-allucinazione, vincolo imperativo di non manipolazione dei file personali e test del tono di voce (persona Metis) sui modelli Qwen 3\.  
> 7. Sviluppo del modulo di ricerca web autonoma via API con estrazione del contesto per il grounding dell'LLM.  
> 8. Sviluppo del modulo di schedulazione (apscheduler) per promemoria ed invio email temporizzate.  
> 9. Installazione di Ollama per eseguire il benchmark di Qwen 3 sulla RTX 2070 Super con tracciamento delle metriche di latenza in GUI.  
> 10. Integrazione dell'hub Home Assistant con le integrazioni Tuya e Xiaomi.  
> 11. Setup della pipeline vocale locale (STT \+ Kokoro TTS).