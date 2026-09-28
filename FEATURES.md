# Metis — Catalogo delle funzionalità

> Riassunto di **tutte** le funzionalità di Metis: quelle sviluppate, quelle in verifica, quelle
> rimandate, nel backlog, scartate o escluse per principio.
> Fonte: la cartella [`SPECS/`](SPECS/) (specifica V1.0, piani e tracking di PHASE0–PHASE3) e
> [`NEW FEATURES/Idee.md`](NEW%20FEATURES/Idee.md).
> Stato aggiornato al **2026-09-28**, ramo `svil/phase2`.

---

## Legenda

| Simbolo | Significato |
| :-: | :-- |
| ✅ | **Sviluppata e verificata** (test automatici e/o prova sul sistema vero) |
| 🟡 | **Sviluppata, verifica aperta**: il codice c'è, manca la prova sul campo (utente, hardware, account) |
| ⏸️ | **Rimandata**: pronta o progettata, ma spenta o sospesa per una decisione |
| 📋 | **Da fare / backlog**: prevista, non ancora scritta |
| ❌ | **Scartata o eliminata**: valutata e respinta, o sostituita da altro |
| 🚫 | **Esclusa per principio**: vincolo di sicurezza o privacy, non si fa |

---

## Stato del progetto in breve

| Fase | Contenuto | Stato |
| :-- | :-- | :-- |
| **PHASE0 · M0–M5** | Scheletro vocale, macchina a stati, broker di sicurezza, GUI, automazione PC, conoscenza web | ✅ chiuse |
| **PHASE0 · M6** | Integrazioni: promemoria, email, notifiche, Home Assistant | 🟡 codice completo, in pausa: mancano HA, account SMTP, riavvio vero |
| **PHASE0 · M7** | Consolidamento V1.0: errori, tray, autostart, bundle, soak | 🟡 codice completo, mancano le prove lunghe (soak 72 h, 100 interazioni, 50 frasi) |
| **PHASE1** | Interfaccia "Hub" (tre viste, nucleo animato, meteo, input di testo) | 🟡 15/17 criteri; manca NFR-8 con l'uso reale e il tag `p1-hub` |
| **PHASE2** | Navigazione: YouTube, "mostra i numeri", bolla, media, dettatura | 🟡 codice fatto; mancano prove a voce (Facebook, feed), catture, bundle, tag |
| **PHASE3** | Voce e lingua (Kokoro, inglese) | ❌ annullata il 2026-09-26; resta solo la velocità della voce |
| **PHASE4** | Imparare dall'uso: frasi non capite → comandi ([piano](SPECS/PHASE4/Piano_Frasi_Non_Capite.md)) | 📋 pianificata il 2026-09-28 — **la prossima** |
| **PHASE5** | Mani libere: sessione di ascolto, conferme a voce, router di navigazione ([piano](SPECS/PHASE5/Piano_Mani_Libere.md)) | 📋 pianificata il 2026-09-28, decisioni D-MANI chiuse; dopo PHASE4 |

---

## 1. Pipeline vocale

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| Push-to-talk globale `Ctrl+Alt+M` | ✅ | Unica via di attivazione in V1.0; interrompe anche mentre Metis parla. Premuto mentre Metis ascolta già, **chiude l'ascolto** (6 volte nel log): da correggere in PHASE5 |
| Ascolto senza tasto dopo ogni risposta (8 s) | ✅ | Usato 78 volte nelle sedute vere; scaduto e seguito dal tasto 12 volte. PHASE5 lo trasforma in una sessione di 45 s |
| Cattura audio `sounddevice` + resampling `soxr` 48→16 kHz | ✅ | Obbligatorio per il Blue Yeti su WASAPI; stream sempre aperto |
| VAD Silero, endpointing ~260 ms | ✅ | CPU |
| STT finale `faster-whisper small` su GPU | ✅ | WER 8,6% su 10 frasi; vocabolario di dominio ("mostra i numeri", "clicca il") |
| TTS **Piper `it_IT-paola-medium`** su CPU | ✅ | Decisione D0: 102 ms contro 858 ms di Kokoro |
| Velocità di lettura configurabile (`[voce] velocita = 1,3`) | 🟡 | Nel codice e testata; l'utente deve confermare 1,3 all'orecchio e nell'uso vero |
| Streaming frase per frase con primo chunk corto (`first_max_chars=45`) | ✅ | Determina quando Metis comincia a parlare |
| Pulizia del testo per la voce (markdown, link, indirizzi) | ✅ | Del link resta il nome; l'URL nudo diventa il nome del sito |
| Half-duplex gating (L1 anti-eco) | ✅ | STT e VAD sospesi in `PARLATO`, `RICERCA_WEB`, `ATTESA_CONFERMA` |
| Barge-in (interruzione entro 200 ms) | ✅ | Ferma player, svuota la coda TTS, annulla lo stream LLM; token per turno |
| Filler vocale durante la ricerca web | ✅ | "Controllo le fonti.", a rotazione, interrompibile; escluso dalla conversazione scritta |
| Saluto vocale all'avvio | ✅ | Una tantum |
| Kokoro TTS come riserva | ✅ | Caricato in sottofondo se Piper fallisce |
| **Wake word "Hey Metis"** (openWakeWord) | ⏸️ | Modello v3 pronto (0 falsi su 39 clip tenute fuori), ma NFR-7 fallito col v1 (57 auto-inneschi in 125 min). Rimandata alla v2: si riaccende con `enabled = true` in `config/wakeword.toml` |
| Barge-in via wake word (L2) | ⏸️ | Cablato, spento con la wake word |
| **Parziali live con Vosk** (trascrizione che scorre mentre si parla) | 📋 | Previsti da §6.3. Il meccanismo "parziali in grigio" della GUI è pronto e testato, ma **nessuna sorgente di parziali è mai stata implementata** |
| **STT speculativo** (trascrizione avviata al primo silenzio) | 📋 | Pianificato per M1 per recuperare ~250 ms; non fatto |
| AEC vero (L3, `webrtc-audio-processing`) | ❌ | Escluso dalla V1.0 (D3): senza wake word il barge-in è il PTT. Si decide con la wake word in v2 |
| Kokoro come voce principale / Kokoro ONNX | ❌ | PHASE3 annullata: voci `if_sara` e `im_nicola` scartate dall'utente, latenza +0,5 s per turno |
| Passaggio all'inglese | ❌ | D-VOCE 3: italiano. Stima (~10 giorni) conservata in PHASE3 Parte B |
| XTTSv2, voci cloud, voce clonata, TTS su GPU | ❌ | VRAM piena, vincolo di privacy |
| Wake word multiple per contesti diversi | 📋 | Backlog V1.1 |

## 2. Modello linguistico e instradamento

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| Qwen 3 8B Q4_K_M via Ollama, `keep_alive=-1` | ✅ | 67 tok/s, TTFT 87 ms, 6,58 GB VRAM totali con STT |
| Thinking mode **disattivata** sul percorso vocale | ✅ | `think=False`, ripiego `/no_think` |
| Due prompt distinti: conversazione (0,7) e tool calling (0,15) | ✅ | Output strutturato con schema JSON di Ollama |
| Una sola `NUM_CTX` per router e conversazione | ✅ | Prima Ollama ricaricava il modello due volte per turno (3,6 s) |
| Un solo tentativo di riparazione su JSON non valido | ✅ | Poi rifiuto esplicito |
| **Router con percorso rapido** (comandi noti senza LLM) | ✅ | 5–30 ms; passa comunque da tutto il broker |
| Comandi custom `config/commands.json` + editor in GUI | ✅ | Validazione contro il registro, ricarica a caldo |
| Contenimento solo con parole di cortesia | ✅ | "apri chrome e mettimi YouTube…" non viene più "mangiato" dal comando rapido |
| Frasi chiuse con parametro (`core/frasi_chiuse.py`) | ✅ | YouTube, numeri, scorrimento, media, volume, browser, dettatura |
| Controlli sul verbo nel codice | ✅ | `open_application`, `riproduci_youtube`, muto, `minimize`, `set_home_device` passano solo con un verbo esplicito |
| Numero e testo "detti" (`toolcall.chiesta`) | ✅ | Un numero o un testo dal modello passa solo se compare nella frase |
| Domanda fissa di chiarimento | ✅ | "Non ho capito il numero: me lo ripete?" invece di un'azione dichiarata e non fatta |
| Strumenti non offerti al modello (`al_modello=False`) | ✅ | I 7 strumenti di PHASE2 si raggiungono solo con frasi chiuse: la lista lunga degradava il router |
| Calendario e intervalli precalcolati nel prompt del router | ✅ | Qwen sbagliava 3 date relative su 7 |
| Banchi del modello (router, anafora, injection, integrazioni, persona) | ✅ | Router 165/165, anafora 12/12, injection 0/18, integrazioni 54/54 |
| **Thinking su richiesta** ("Metis, ragiona su…") | 📋 | Progettata in §7.2 (indicatore, avviso vocale, timeout 30 s), **non implementata** |
| **Profilo "Profondo"** Qwen 3 30B-A3B su CPU | 📋 | Backlog V1.1 #4, già progettato in §3.3 |
| Profilo "Rapido" Qwen 3 4B | ❌ | Non scaricato: l'8B supera ogni criterio |
| Qwen 14B/30B su GPU, Devstral, LM Studio | ❌ | Non entrano in 8 GB di VRAM (C1) |
| **Router e conversazione in parallelo** | 📋 | Backlog V1.1 #7: la leva più grande su NFR-1 (0,3–0,6 s) |

## 3. Sicurezza — Capability Broker

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| Broker a 6 stadi: schema → registro → policy → guardie → conferma → audit | ✅ | Unico ingresso `broker.execute`, non solleva mai; copertura test 100% |
| Livelli T0 (lettura) · T1 (reversibile) · T2 (input sintetico) · T3 (esterno) | ✅ | Deny-by-default |
| Allowlist applicazioni `config/apps.toml` | ✅ | `Popen` con lista, mai `shell=True` |
| Denylist finestre T2 (Esplora risorse, cmd, PowerShell, Terminal, regedit, taskmgr, dialoghi file) | ✅ | Rivalutata un istante prima di ogni evento |
| Denylist combinazioni (`Shift+Canc`, `Win+R`, `Ctrl+Shift+Invio`) | ✅ | |
| Conferma T3 sempre, in GUI, con timeout 20 s | ✅ | Nessun pulsante predefinito, fuoco su "Nega", argomenti completi |
| Domanda di conferma pronunciata ("… Confermo?") | ✅ | La risposta però **passa solo dalla finestra**: il microfono è chiuso in `ATTESA_CONFERMA` |
| Conferma a voce (tranne le email) | 📋 | PHASE5, D-MANI 7–10 |
| Conferma aggiungibile sotto T3 (`ToolSpec.conferma` booleano o funzione) | ✅ | Mai toglibile a un T3; nel dubbio si chiede |
| Kill switch `Ctrl+Alt+Shift+M` | ✅ | Sospende T2/T3 entro 100 ms; rivalutato anche dopo la bolla |
| Audit log SQLite append-only | ✅ | Verificato via AST |
| Contenuto web = dato non fidato; nessun T2/T3 in un turno contaminato | ✅ | 0 azioni ostili su 18 giri di injection |
| Il testo delle pagine non entra nel modello quando si agisce | ✅ | `mostra_numeri` restituisce solo un conteggio |
| Clic sensibili con conferma, parole vietate mai cliccate (`navigazione.toml`) | ✅ | Italiano e inglese; NFR-9 esteso: 0 clic sensibili non confermati |
| Invio in un campo di testo sempre confermato (D-NAV 11) | ✅ | |
| Segreti nel Windows Credential Manager (`keyring`) | ✅ | Test che scansiona i file tracciati da git |
| Handle di finestra e coordinate non nominabili dal modello | ✅ | Solo titoli; nessun campo `x`/`y` in nessuno schema (test) |
| Strumenti su file (`read_file`, `write_file`, `delete_file`, `list_directory`…) | 🚫 | L'assenza è il meccanismo di sicurezza |
| Esecuzione di codice arbitrario (`run_command`, `run_python`, `install_package`) | 🚫 | |
| Blocco di `os`/`shutil` nel codice (idea della V16) | ❌ | Sostituito dal broker: il divieto va applicato al registro strumenti |

## 4. Automazione del PC

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| Apertura applicazioni in allowlist (`open_application`) | ✅ | VS Code, GitHub Desktop, Chrome… |
| Apertura URL https (`open_url`) | ✅ | |
| Spostamento finestre fra monitor, DPI-aware, coordinate negative | ✅ | Per-monitor DPI V2; verifica e correzione del rettangolo una volta |
| Disposizioni nominate (metà, centrata, piena), minimizza/massimizza/ripristina/fuoco | ✅ | Mai pixel |
| "Questa finestra" catturata al PTT | ✅ | Deittici ("questa finestra") risolti nel codice |
| Scaling DPI **diverso** fra monitor | 🟡 | Matematica testata su monitor sintetici; hardware con scaling misto assente |
| `click_element` per nome via UI Automation (anche nel browser) | ✅ | Esatti → sottostringhe → rifiuto; ambiguità → numeri sui candidati |
| `type_text` | ✅ | Da PHASE2 solo con il fuoco in un campo di testo |
| `press_hotkey`, `scroll` | ✅ | Con denylist |
| `drag` | 🟡 | Scritto e registrato, **mai provato a mano** |
| Playwright su CDP per il browser | ❌ | Da Chrome 136 la porta di debug non si apre sul profilo dell'utente: sostituito da UIA. `browser.py` resta per i banchi |
| OCR come terzo livello di localizzazione | ⏸️ | D2 provvisoria: UIA basta finora. Si riapre se compaiono app invisibili a UIA (Tk, Electron senza accessibilità) |
| `pyautogui`, `pygetwindow`, coordinate grezze | ❌ | Sostituiti da `SendInput`, `pywin32`, UIA |
| Registrazione di macro complesse | 📋 | Dopo la V1.0 |

## 5. Navigazione (PHASE2)

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| "Cerca su YouTube X" (livello A: pagina dei risultati) | ✅ | Frase chiusa |
| `riproduci_youtube` (livello B: parte il primo video) | 🟡 | Dal web esce solo un id di 11 caratteri; il titolo va all'Hub. Manca la prova a voce della frase di partenza |
| **"Mostra i numeri"**: etichette sugli elementi cliccabili visibili, in ogni finestra | ✅ | UIA filtrato, 34–48 ms a caldo, max 99, scadono a 60 s e allo scorrimento |
| **"Clicca il N"** | ✅ | Rilettura, stesso nome entro 6 px, guardia sul primo piano; 275 ms con la bolla |
| Rifiuto "la pagina è cambiata" | ✅ | Lampo rosso sulla posizione vecchia |
| Numeri su Facebook in < 1 s | 🟡 | D-NAV 1 provvisoria: manca la misura sul feed vero |
| **Bolla di evidenziazione** (stile eye tracker) + contorno | ✅ | ≥ 250 ms prima del clic; fucsia durante la conferma; "riduci animazioni" |
| Revisione delle catture della bolla | 🟡 | Utente |
| "Dov'è il 7?" (`indica_numero`, solo bolla) | 📋 | Facoltativo, non fatto |
| Niente numeri nelle finestre in denylist T2 | ✅ | Rifiuto immediato su Esplora risorse |
| Scorrimento a blocchi (Pag↓/Pag↑, Home/Fine, "di tre pagine", "un po'") | ✅ | Scelta dell'utente: a blocchi, non continuo |
| Tasti multimediali (play/pausa, successivo, precedente, stop) | ✅ | T1 (D-NAV 8) |
| Volume di sistema (`set_volume`, `cambia_volume`, `imposta_muto`, `leggi_volume`) | ✅ | Core Audio via `comtypes`; era nella specifica da M0 e mai fatto prima |
| Browser: ricarica, schede, "vai alla seconda scheda", zoom, indietro/avanti, chiudi/riapri/nuova scheda | ✅ | Scorciatoie di Chrome, T2 |
| Comandi video YouTube (±10 s, ±1 min, schermo intero, sottotitoli) | ✅ | T2, solo con YouTube davanti e fuoco fuori dai campi (D-NAV 9) |
| **Dettatura**: "scrivi nel 12: …", "digita …", "premi invio" | ✅ | Campi numerati, fuoco verificato, Invio confermato (D-NAV 10–12) |
| Scale 125%/150% vere, due monitor | 🟡 | Qui entrambi i monitor sono al 100% |
| Finestre e desktop (funzioni proposte il 2026-09-28) | ❌ | Scartate dall'utente |
| Cerca nella pagina | ❌ | Scartata dall'utente |
| Leggimi la pagina | ❌ | Scartata dall'utente |
| Guardia sul primo piano spostata dopo il ritorno della finestra | ❌ | Problema #4: l'utente ha scelto di lasciare la guardia di M2 nel broker |
| Il modello che "guarda" lo schermo (visione) | 🚫 | VRAM piena, e un modello che ha visto la pagina deciderebbe il clic |
| Navigazione autonoma a più passi ("trovami il volo più economico") | 🚫 | Agente che legge le pagine e decide: stessa ragione della visione |
| Moduli compilati dal modello, login, acquisti, pagamenti | 🚫 | Mai, confermato o no |
| Musica senza YouTube (Spotify, file locali) | ❌ | Altra integrazione; i file locali sono fuori ambito |

## 6. Conoscenza e memoria

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| `web_search` con `ddgs`, cache SQLite 15 min, backoff | ✅ | |
| Fallback Brave Search API e SearXNG | ✅ | Configurabili (chiave in `keyring`, `METIS_SEARXNG`) |
| Filtro annunci e link giganti (`web.organici`) | ✅ | |
| `web_fetch` https, 200 KB, 8 s, `trafilatura` + pulizia HTML preventiva | ✅ | Testo nascosto via CSS eliminato prima dell'estrazione |
| Grounding con delimitatori `<<<FONTE_ESTERNA_NON_FIDATA>>>` ed escape | ✅ | Risposte con citazione della fonte |
| Regola di precedenza: fatti attuali → web, spiegazioni → conversazione | ✅ | Router 102/102 dopo la correzione di PHASE1 |
| Dichiarazione di incertezza ("Informazione non presente nei sistemi") | ✅ | 0% di falsi rifiuti su 20 domande |
| Ricerca fallita dichiarata, mai sostituita da risposta a memoria | ✅ | |
| Memoria conversazionale: 8 turni + riassunto automatico a due soglie | ✅ | Riassunto solo in `DORMIENTE`, su un thread suo |
| Slot di riferimento (anafora: "aprilo", "spostala") | ✅ | 6 slot, nel prompt di conversazione e del router |
| Il contenuto web non entra nella memoria | ✅ | |
| Persona Metis (formale, "lei", 1–3 frasi, ironia discreta) | ✅ | Non dichiara mai azioni non fatte (6/12 → 0/12) |
| Metis parla di sé al femminile e in prima persona | ✅ | 2026-09-28: 1 maschile su 36 risposte (prima ~8 su 24); banco della persona nel target |
| Pannello "frasi non capite" → comandi e varianti | 📋 | PHASE4 |
| **Memoria a lungo termine, preferenze persistenti** | 📋 | Backlog V1.1 #3 |
| **Ricerca multi-hop** | 📋 | Dopo la V1.0 |
| RAG su documenti locali, vector store | 🚫 | Nessun accesso ai file; 3 fonti per turno non richiedono embedding |
| Meteo come strumento di Metis ("che tempo fa?") | 📋 | D-UI 6: backlog |

## 7. Integrazioni (M6)

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| Scheduler APScheduler con jobstore SQLite persistente | ✅ | `misfire_grace_time=None`; oltre l'ora il promemoria arriva dicendolo |
| Promemoria (`schedule_reminder`, `list_reminders`, `cancel_reminder` per parole) | ✅ | Data confermata a voce e in finestra; accodato se Metis è occupato |
| Parsing di date italiane relative | ✅ | Con calendario nel prompt: 5/5 |
| Promemoria che sopravvive al **riavvio vero del PC** | 🟡 | Verificato fra due processi, non con un riavvio |
| Email `send_email` / `schedule_email` (T3) | 🟡 | SMTP_SSL/STARTTLS, allowlist ricontrollata all'invio, retry ogni 10 min ×6. Manca l'account SMTP vero |
| Notifiche desktop `win11toast` | 🟡 | Scritte, ma le notifiche di Windows sono disattivate su questa macchina: il promemoria arriva a voce |
| Home Assistant via WebSocket (`get_home_state`, `list_home_devices`, `set_home_device`) | 🟡 | Testato su HA finto; tier solo restringibili; il modello non nomina mai un `entity_id` |
| Guardie domestiche: `max_durata_min` friggitrice, `max_erogazioni_giorno` crocchette | ✅ | Spegnimento come job persistente; conteggio su SQLite |
| Dispositivi Tuya e videocamera Xiaomi reali | 🟡 | HA non ancora disponibile |
| "Ricordamelo fra 10 minuti" sulla notifica | 📋 | Backlog V1.1 #8 |
| Lettura posta in arrivo (IMAP) | 📋 | Backlog V1.1 #1: serve un modello di privacy diverso |
| Integrazione calendario | 📋 | Backlog V1.1 #2 |
| Scene e routine di Home Assistant | 📋 | Dopo la V1.0 |
| Destinatari email arbitrari | 🚫 | Scelta conservativa: solo allowlist |

## 8. Interfaccia grafica

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| PySide6 con `QThread` + worker, solo Signal/Slot | ✅ | Test via AST sull'accesso ai widget |
| Vista **Minimal** (overlay sempre in primo piano) | ✅ | Nucleo in miniatura 64 px, trascinabile, posizione salvata |
| Vista **Hub** a tre colonne (ispirata alla reference Jarvis) | ✅ | Approvata dall'utente sulle catture |
| Vista **Diagnostica** (ex control room) | ✅ | Registro, contesto del prompt, editor comandi, audit, latenze |
| **Nucleo animato** (un movimento per stato, colori dalla palette unica) | ✅ | QPainter, p95 2,2 ms, 30 fps, fermo con la vista nascosta |
| **Onda sonora** che segue la voce dal player | ✅ | Inviluppo RMS a 20 ms; due scale (microfono e voce) |
| Conversazione a fumetti (modello condiviso Hub/Diagnostica) | ✅ | |
| Input di testo con lo stesso percorso di sicurezza della voce | ✅ | Turni scritti esclusi da NFR-1/2 |
| "Pulisci" (vista + memoria + slot) ed "Esporta" in Markdown | ✅ | Conferma predefinita su Annulla |
| Pulsante muto | ✅ | Le risposte restano scritte |
| Widget Sistema (CPU, RAM, VRAM, disco, temperatura GPU) e Sessione | ✅ | Barra VRAM rossa sopra 7,5 GB |
| Widget Meteo (Open-Meteo, cache, senza rete in persona) | ✅ | Escono solo le coordinate |
| Impostazioni (città, riduci animazioni, vista e muto all'avvio) | ✅ | `config/gui.local.toml`, ignorato da git |
| Dashboard latenze (TTFT, tok/s, p50/p95) e audit filtrabile | ✅ | Colori degli esiti corretti in PHASE1 |
| Sistema di design (`tema.py`, Orbitron/Inter/JetBrains Mono, icone Lucide) | ✅ | Nessun colore esadecimale fuori da `tema.py`/`palette.py` (test) |
| Tray con stato, viste, kill switch, pausa ascolto, esci | ✅ | Chiudere la finestra non chiude Metis |
| **NFR-8 ricertificato con l'Hub** in 30 minuti d'uso reale | 🟡 | Utente |
| Pannello **Fotocamera** | ⏸️ | Segnaposto vuoto (D-UI 1): aspetta Home Assistant. Webcam del PC esclusa senza una decisione sulla privacy |
| Streaming video della videocamera | 📋 | Backlog V1.1 #5 |
| Grafici storici della telemetria | 📋 | Backlog |
| Temi, tema chiaro, personalizzazione estetica | 📋 | Backlog V1.1 #6 |
| `QOpenGLWidget` per l'onda (proposto in `Idee.md`) | ❌ | Non serve: QPainter a 2,2 ms |
| 60 fps | ❌ | CPU raddoppiata, p95 4,7 ms in `PARLATO` |
| Riscrittura in QML/QtQuick | ❌ | Riscrittura totale e regole dei thread da rifare |
| PyQt6 | ❌ | Licenza GPL: si usa PySide6 (LGPL) |
| Parziali STT in grigio | 📋 | Pronti nella GUI, manca la sorgente (vedi §1) |

## 9. Residenza e affidabilità (M7)

| Funzionalità | Stato | Dettagli |
| :-- | :-: | :-- |
| Matrice degli errori con frasi in persona, mai traceback | ✅ | Ollama giù, OOM, microfono scollegato, rete assente, HA offline, SMTP, TTS, STT vuoto, VRAM alta |
| Monitor di salute `SALUTE` in sottofondo, 1 retry verso Ollama | ✅ | |
| Whisper sulla CPU come contromisura a VRAM > 7,5 GB | ✅ | |
| Microfono scollegato: rilevato, riprovato, annunciato una volta | ✅ | |
| Avvio robusto (Ollama che parte dopo, fino a 120 s) | 🟡 | Provato con finti |
| Chiusura sicura anche durante l'avvio | ✅ | Crash 0xC0000409 corretto in PHASE1 |
| Bundle PyInstaller `onedir`, provato su cartella pulita | ✅ | Da rigenerare per PHASE2 |
| Autostart con Utilità di pianificazione, non amministratore | 🟡 | Script provato in anteprima, non installato né provato con un riavvio |
| Harness di soak 72 h con iniezione di guasti | 🟡 | Due prove da 9 minuti; la prova lunga tocca all'utente |
| `verifica_nfr.py` (NFR da log e audit) | ✅ | Con `--dal` per le finestre di prova |
| `docs/INSTALL.md` provato da zero | 🟡 | Scritto, non provato |

---

## Requisiti non funzionali — stato

| NFR | Target | Misurato | Stato |
| :-- | :-- | :-- | :-: |
| 1 · Latenza e2e | p50 < 1,2 s · p95 < 1,8 s | 1119/1625 ms in M0; **1,9–2,3 s in conversazione** con il router | 🟡 a rischio |
| 2 · TTFT | < 400 ms | 87 ms (627 a 3,6k token) | 🟡 |
| 3 · Throughput | ≥ 45 tok/s | 67,1 (51–59 nel soak) | ✅ |
| 4 · VRAM | ≤ 7,2 GB | 6,58 GB | ✅ |
| 5 · WER | < 12% | 8,6% su 10 frasi (ne servono 50) | 🟡 |
| 6 · Falsi risvegli | < 1 / 8 h | non applicabile senza wake word | ⏸️ |
| 7 · Auto-inneschi | 0 | 57 in 125 min (v1) | ⏸️ |
| 8 · Reattività GUI | ≥ 30 fps, nessun freeze > 100 ms | 62 fps, 0 blocchi; da ricertificare con l'Hub | 🟡 |
| 9 · T3 non confermate | 0 | 0 (anche clic sensibili) | ✅ |
| 10 · Stabilità | 72 h, RSS < +10% | solo 72 minuti | 🟡 |

---

## Backlog consolidato

| # | Idea | Origine |
| :-- | :-- | :-- |
| 1 | Lettura della posta in arrivo (IMAP) | Specifica, V1.1 #1 |
| 2 | Integrazione calendario | Specifica, V1.1 #2 |
| 3 | Memoria a lungo termine, preferenze persistenti | Specifica, V1.1 #3 |
| 4 | Modalità "analisi profonda" con Qwen 30B-A3B su CPU | Specifica §3.3, V1.1 #4 |
| 5 | Thinking mode su richiesta | Specifica §7.2 (mai implementata) |
| 6 | Streaming videocamera in GUI / contenuto del pannello Fotocamera | V1.1 #5, D-UI 1 |
| 7 | Temi e personalizzazione estetica | V1.1 #6 |
| 8 | Router e conversazione in parallelo | M7, V1.1 #7 |
| 9 | "Ricordamelo fra 10 minuti" sulla notifica | M6, V1.1 #8 |
| 10 | Meteo come strumento | D-UI 6 |
| 11 | Grafici storici della telemetria | M3, PHASE1 |
| 12 | Ricerca multi-hop | M5 |
| 13 | Scene e routine di Home Assistant | M6 |
| 14 | Registrazione di macro complesse | M4 |
| 15 | Wake word multiple | M7 |
| 16 | Parziali STT live (Vosk) | Specifica §6.3 (mai implementata) |
| 17 | STT speculativo | M0/M1 (mai implementato) |
| 18 | "Dov'è il N?" (`indica_numero`) | PHASE2 |
| 19 | OCR come terzo livello | D2, se servirà |
| 20 | Riaccensione della wake word (v2) con seduta NFR-7 a stanza vuota | D1 |
