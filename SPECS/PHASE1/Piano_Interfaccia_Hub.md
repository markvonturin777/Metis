# PHASE1 — Interfaccia "Hub"

> **Durata stimata:** 16 giorni · **Ramo:** `svil/phase1` · **Tag:** `p1-hub`
> **Materiale di partenza:** [`NEW FEATURES/Idee.md`](../../NEW%20FEATURES/Idee.md), [`NEW FEATURES/JARVIS_INTERFACE.png`](../../NEW%20FEATURES/JARVIS_INTERFACE.png)
> **Riferimento normativo:** [Specifica V1.0](../PHASE0/Metis_V1.0_Specifica_Ufficiale.md), §11 (interfaccia) e §15 (NFR-8)

---

## Obiettivo

Dare a Metis **una faccia all'altezza di quello che fa**, senza perdere niente di quello che la
faccia attuale garantisce.

L'interfaccia di PHASE0 è corretta ma è una console di sviluppo: tre colonne di pannelli
testuali pensate per rispondere a "perché ha fatto così?". La nuova vista principale, l'**Hub**,
deve rispondere a una domanda diversa, quella di chi la usa ogni giorno: *"cosa sta facendo
Metis adesso, e come sta il sistema?"*. È l'impostazione della reference: widget di sistema a
sinistra, un nucleo animato al centro, la conversazione a destra.

Il rischio dominante **non è estetico**, come in M3. Un'interfaccia che anima un anello e un'onda
a 60 fotogrammi al secondo può rompere tre garanzie già misurate:

| Garanzia | Dove si rompe | Contromisura |
| :-- | :-- | :-- |
| **NFR-8**: nessun freeze > 100 ms | Effetti grafici costosi (ombre, sfocature) sul thread della GUI | Disegno in `paintEvent`, niente `QGraphicsEffect` sulle parti animate |
| **Residenza 72 h** (M7) | Animazioni che girano anche con la finestra nascosta nella tray | Animazioni ferme quando la vista non è visibile, verificato da un test |
| **Leggibilità a due metri** (M3) | Estetica monocromatica ciano: tutti gli stati dello stesso colore | Colori di stato dalla palette unica, distinguibili, verificati da un test |

---

## Prerequisiti

- [x] M7: codice completo, GUI di PHASE0 stabile e coperta da test
- [ ] **Decisioni D-UI chiuse** (§Decisioni, qui sotto): cambiano il perimetro del lavoro
- [ ] Ramo `svil/phase1` creato da `svil/m7`

**Rapporto con M7, ancora aperto.** M7 vieta nuove funzionalità prima del tag `v1.0`, e questa
fase ne aggiunge (meteo, fotocamera, input di testo). Resta compatibile con la chiusura di M7 a
due condizioni:

1. **Il soak di 72 ore non dipende dalla GUI**: `tests/soak/run_soak.py` usa `costruisci_sistema`
   senza interfaccia. Si può fare quando si vuole, a patto di non sviluppare in contemporanea
   (GPU e altoparlanti sono gli stessi).
2. **NFR-8 va ricertificato alla fine di questa fase**, perché la GUI su cui è stato misurato
   non esisterà più come vista principale.

---

## Decisioni da prendere prima di iniziare (gate D-UI)

Ognuna ha una raccomandazione. Se va bene la raccomandazione, basta spuntarla.

| # | Domanda | Raccomandazione | Perché |
| :-- | :-- | :-- | :-- |
| **D-UI 1** | Il modulo **Fotocamera** mostra quale fotocamera? | **La videocamera di Home Assistant** (`camera.xiaomi_salotto`, già in `config/home_assistant.toml`). **La webcam del PC è esclusa** | La videocamera è già nel perimetro della specifica (§17 M6) e nel backlog V1.1 (#5 "Streaming videocamera in GUI"). La webcam sarebbe un sensore nuovo puntato sull'utente: un problema di privacy da trattare a parte, non un widget |
| **D-UI 2** | A un messaggio **scritto** Metis risponde a voce o per iscritto? | **A voce e per iscritto, come sempre.** Un pulsante "muto" nella barra dei controlli toglie la voce a tutto, scritto o parlato | Un solo percorso di risposta. Una risposta solo scritta chiederebbe un secondo percorso nella macchina a stati (GENERAZIONE → PARLATO dipende dal primo audio) |
| **D-UI 3** | **"Pulisci"** cancella solo la vista o anche la memoria? | **Anche la memoria** (finestra, riassunto, slot), con una conferma | Pulire la vista lasciando la memoria è ingannevole: la conversazione sembra nuova, ma Metis ricorda ancora |
| **D-UI 4** | La **control room** attuale sparisce? | **No: diventa la vista "Diagnostica"**, restilizzata e raggiungibile dall'Hub | Audit, contesto, editor dei comandi e latenze sono strumenti che servono ancora, e sono coperti da test |
| **D-UI 5** | Da dove arriva il **meteo**? | **Open-Meteo**: nessun account, nessuna chiave. La posizione sta in `config/gui.local.toml`, ignorato da git | L'unico dato che esce dal PC sono le coordinate. Stesso schema di `email.local.toml` |
| **D-UI 6** | Il meteo diventa anche uno **strumento** di Metis ("che tempo fa?")? | **No, non in questa fase** | Sarebbe uno strumento T0 nuovo, da provare con i banchi del router. Va nel backlog |

---

## Il disegno

### L'Hub

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ M.E.T.I.S  ● Operativo        🕒 14:52:27 │ giovedì 25 settembre       ☁ 18°  ⛨  ⚙ │
├───────────────────┬────────────────────────────────────────────┬─────────────────────┤
│ ▣ SISTEMA         │                                            │ CONVERSAZIONE  ⌫ ⤓  │
│ CPU   ▓▓░░░░  8%  │                                            │                     │
│ RAM   ▓▓▓▓░░ 44%  │               ╭──────────╮                 │  ┌───────────────┐  │
│ VRAM  ▓▓▓▓▓░ 6,1G │            ╭──┤          ├──╮              │  │ I sistemi sono│  │
│ [CPU][RAM][DISCO] │            │  │  ∿∿∿∿∿   │  │              │  │ operativi.    │  │
│ [GPU 54°C]        │            ╰──┤          ├──╯              │  │         14:45 │  │
├───────────────────┤               ╰──────────╯                 │  └───────────────┘  │
│ ☁ METEO           │                                            │       ┌───────────┐ │
│ 18°C  Milano      │               M.E.T.I.S                    │       │ Che ore   │ │
│ coperto           │          ● sta ascoltando                  │       │ sono?     │ │
│ [umid][vento][perc]│                                           │       └───────────┘ │
├───────────────────┤                                            │                     │
│ ◉ FOTOCAMERA      │                                            │                     │
│  (spenta)         │                                            │                     │
├───────────────────┤                                            │                     │
│ ⏱ SESSIONE        │                                            │                     │
│ attivo da 00:07:19│           [ 📷 ]  [ 🎙 ]  [ ⌨ ]  [ 🔇 ]      ├─────────────────────┤
│ turni 12 · az. 4  │                                            │ [Scrivi…       ] ➤  │
└───────────────────┴────────────────────────────────────────────┴─────────────────────┘
```

**Tre viste, non due** (D-UI 4). Cambia la specifica §11.2:

| Vista | Per cosa | Stato |
| :-- | :-- | :-- |
| **Minimal** (overlay) | Guardare di sfuggita mentre si lavora | Esiste: si restilizza con un nucleo in miniatura |
| **Hub** | L'uso quotidiano | **Nuova**, diventa la vista a schermo intero predefinita |
| **Diagnostica** | Capire perché Metis ha fatto qualcosa | È la control room di oggi, restilizzata |

I widget restano **oggetti condivisi fra le viste**, come in M3: la conversazione dell'Hub e
quella della Diagnostica sono lo stesso modello e non si ricopia niente.

### Il nucleo: uno stato, un comportamento

Il nucleo al centro sostituisce il pallino di stato. Deve dire lo stato **di sbieco e a due
metri** (principio di M3), quindi il colore resta quello della palette unica
`metis/core/palette.py` (la stessa della tray e della console). L'estetica ciano della reference
vale per la cornice: pannelli, bordi, titoli.

| Stato | Colore (palette) | Movimento |
| :-- | :-- | :-- |
| `DORMIENTE` | grigio | respiro lento, periodo 4 s |
| `IN_ASCOLTO`, `TRASCRIZIONE` | blu, azzurro | gli anelli seguono il livello del **microfono** |
| `ELABORAZIONE`, `GENERAZIONE` | ambra | un arco che ruota |
| `RICERCA_WEB`, `ESECUZIONE` | viola | segmenti che ruotano |
| `ATTESA_CONFERMA` | arancione | pulsazione, finché il dialogo T3 è aperto |
| `PARLATO` | verde | **l'onda sonora** segue la **voce di Metis** |
| `INTERROTTO`, `ERRORE` | rosso | un lampo, poi si torna allo stato successivo |
| + kill switch | anello esterno rosso | come l'icona nella tray |
| + pausa ascolto | desaturato, due barre | come l'icona nella tray |

### La barra dei controlli

| Pulsante | Azione | Esiste già? |
| :-- | :-- | :-- |
| 📷 Fotocamera | Mostra o nasconde il flusso nel modulo a sinistra | No |
| 🎙 Microfono | **Push-to-talk**, lo stesso di `Ctrl+Alt+M`. Barrato quando l'ascolto è in pausa | Sì, è `nucleo.ptt()` |
| ⌨ Tastiera | Porta il cursore nel campo di testo | No |
| 🔇 Muto | Toglie la voce a Metis; le risposte restano scritte (D-UI 2) | No |

Il **kill switch** non va in questa barra, perché accanto al microfono si preme per sbaglio. Sta
nell'intestazione (⛨) e diventa rosso quando è attivo.

---

## Scelte tecniche

### PySide6, non PyQt6

`Idee.md` parla di PyQt6. Il progetto usa **PySide6**, e la scelta è vincolante (specifica
§11.1): PyQt6 è GPL, PySide6 è LGPL. Le classi citate nel documento esistono identiche in
PySide6 (`QPainter`, `QPainterPath`, `QOpenGLWidget` in `PySide6.QtOpenGLWidgets`), quindi il
piano non cambia.

### QPainter prima, OpenGL solo se misurato

`Idee.md` propone `QOpenGLWidget` per l'onda. Si parte da un `QWidget` normale con `QPainter`
e antialiasing, e si passa a `QOpenGLWidget` **solo se** la misura del giorno 7 lo chiede
(disegno del nucleo sopra i 4 ms per fotogramma a 1080p). Tre motivi:

- un nucleo e un'onda sono qualche centinaio di primitive: `QPainter` li disegna in pochi ms;
- `QOpenGLWidget` introduce differenze fra driver e problemi con le finestre traslucide (l'overlay
  Minimal lo è) e con le catture dello schermo;
- il `MisuratoreLag` misura l'event loop, e con OpenGL una parte del costo si sposta dove non si
  vede.

**QML/QtQuick è scartato.** Renderebbe le animazioni più comode, ma vorrebbe dire riscrivere
tutta l'interfaccia e cambiare le regole dei thread verificate in M3.

### L'onda segue la voce vera

`Idee.md` collega l'onda "all'uscita TTS di Kokoro". Il motore è **Piper** (decisione D0), e
Kokoro è solo la riserva. L'onda deve quindi leggere dal **player**, che riproduce l'audio di
qualunque motore.

Oggi il player usa `sd.play()` + `sd.wait()` e non espone l'ampiezza. Si aggiunge:

- all'accodamento, un **inviluppo** della frase: l'RMS ogni 20 ms, calcolato con numpy su un
  array già in memoria;
- all'inizio della riproduzione, l'istante di partenza;
- `livello_uscita()`, che restituisce il valore dell'inviluppo all'istante corrente.

Il nucleo emette già il livello del microfono 31 volte al secondo (`_su_blocco`), e lì
aggiunge quello della voce. **Nessun thread nuovo**, nessun callback audio da toccare.

### Un sistema di design, in un file

`metis/gui/tema.py` raccoglie colori della cornice, raggi, spaziature, font e il foglio di stile
unico. È il file equivalente, per la cornice, di quello che `palette.py` è per gli stati. Un test
vieta i colori esadecimali scritti fuori da questi due file, come in M3 era vietata la seconda
tabella dei colori.

| Risorsa | Scelta | Licenza |
| :-- | :-- | :-- |
| Font dei titoli | **Orbitron** (il carattere "tecnico" della reference) | SIL OFL |
| Font dei numeri | **JetBrains Mono** (cifre a larghezza fissa: l'orologio non balla) | SIL OFL |
| Font del testo | **Inter** | SIL OFL |
| Icone | **Lucide**, SVG, colorate a runtime con `QSvgRenderer` | ISC |

Font e icone stanno in `metis/gui/risorse/` con le loro licenze, e vanno aggiunti ai `datas` di
`metis.spec`.

---

## Deliverable

| # | Componente | File |
| :-- | :-- | :-- |
| 1 | Sistema di design, font, icone | `metis/gui/tema.py`, `metis/gui/risorse/` |
| 2 | Componenti base: pannello, tessera, barra, pulsante-icona, pillola di stato | `metis/gui/componenti.py` |
| 3 | Vista Hub | `metis/gui/hub_view.py` |
| 4 | Nucleo animato e onda sonora | `metis/gui/widgets/nucleo.py` |
| 5 | Inviluppo della voce nel player | `metis/tts/kokoro_engine.py` (`Player`) |
| 6 | Conversazione a fumetti, pulisci, esporta | `metis/gui/widgets/conversazione.py` |
| 7 | Input di testo | `metis/core/orchestrator.py` (`on_testo`), macchina a stati |
| 8 | Widget sistema, sessione | `metis/gui/widgets/sistema.py` |
| 9 | Meteo | `metis/gui/workers/meteo.py`, `metis/gui/widgets/meteo.py` |
| 10 | Fotocamera | `metis/gui/workers/fotocamera.py`, `metis/gui/widgets/fotocamera.py` |
| 11 | Impostazioni | `metis/gui/impostazioni.py`, `config/gui.toml` + `gui.local.toml` |
| 12 | Minimal, Diagnostica, dialogo T3, tray restilizzati | file esistenti |
| 13 | Specifica §11 aggiornata, `docs/INSTALL.md` | documenti |

---

## Step operativi

### Giorni 1–2 — Fondamenta: il sistema di design

1. `tema.py`: gettoni di colore (sfondo `#05080d`, pannello, bordo, accento ciano, testo
   primario e secondario), raggi, spaziature, e il foglio di stile generato da lì.
2. Font caricati con `QFontDatabase.addApplicationFont` all'avvio. Un test fallisce se un font
   non si carica, perché Qt ripiegherebbe su un altro carattere senza dirlo.
3. Icone Lucide: un sottoinsieme di circa 20 SVG, `icona(nome, colore, lato) -> QIcon`.
4. `componenti.py`: `Pannello` (titolo, icona, azioni a destra, come le card della reference),
   `Tessera` (etichetta e valore), `Barra` (percentuale colorata sopra una soglia),
   `PulsanteIcona`, `Pillola`.
5. **Palette degli stati rivista** per il fondo più scuro: stessi significati, tonalità neon.
   Un test verifica che gli stati da distinguere a colpo d'occhio (dormiente, ascolto, pensa,
   parla, aspetta te, errore) abbiano tonalità lontane almeno 30°.

**Uscita:** una pagina di prova (`benchmarks/gui_catalogo.py`) che mostra tutti i componenti.

### Giorni 3–5 — L'Hub: impalcatura e conversazione

1. `hub_view.py` con l'intestazione (nome, stato, orologio a 1 Hz, meteo compatto, kill switch,
   impostazioni) e le tre colonne. Le colonne laterali hanno una larghezza fissa e la centrale è
   elastica. **Sotto i 1280 px** la colonna sinistra si riduce alle sole icone: la reference è
   a 1920, ma il monitor secondario o una finestra affiancata no.
2. Conversazione a fumetti: Metis a sinistra, l'utente a destra, l'ora sotto a ogni fumetto, il
   parziale sostituito dal finale (proprietà già verificata in M3). Tutto il testo passa da
   `metis/gui/testo.py`, perché il link di 1500 caratteri esiste ancora.
3. **Pulisci** (D-UI 3): conferma, poi vista, memoria e slot azzerati tramite il nucleo. Solo in
   `DORMIENTE`: a turno in corso il pulsante è disattivato.
4. **Esporta**: Markdown con gli orari, salvato in un file scelto dall'utente con `QFileDialog`.
   Non contraddice il divieto di accesso al file system (§1.2), che riguarda le capacità di Metis:
   qui scrive l'utente, con il suo clic, e Metis non ne sa niente.
5. **Input di testo**:
   - `Orchestrator.on_testo(testo)` avvia un turno saltando cattura, VAD e STT. Evento nuovo
     `TESTO` nella macchina a stati: da `DORMIENTE` e `IN_ASCOLTO` porta a `ELABORAZIONE`. I test
     di integrità della tabella (stati irraggiungibili, vicoli ciechi) vanno tenuti verdi.
   - Invio durante `PARLATO`: interrompe come il PTT, poi elabora. Durante `ELABORAZIONE`,
     `ESECUZIONE` e `ATTESA_CONFERMA` l'invio è disattivato.
   - **Stesso percorso di sicurezza**: router, broker, conferma T3. Un test: "mandami una mail"
     scritto chiede conferma esattamente come detto.
   - Il turno scritto porta `origine="testo"` nelle metriche, e `tests/nfr/verifica_nfr.py` lo
     esclude da NFR-1 e NFR-2: senza parlato non esiste una latenza fine-parlato → primo audio.
6. Il cambio vista (Minimal ↔ Hub ↔ Diagnostica) non perde niente: si estendono i test di M3 alla
   terza vista.

### Giorni 6–8 — Il nucleo e l'onda

1. `widgets/nucleo.py`: tre anelli concentrici e un disco interno, disegnati in `paintEvent` con
   gradienti radiali per il bagliore. **Niente `QGraphicsDropShadowEffect`**, che su un widget
   animato ridisegna tutto a ogni fotogramma.
2. L'onda: 3–5 curve di Bézier con fase diversa, l'ampiezza dal livello (microfono in ascolto,
   voce in `PARLATO`) smussato con una media esponenziale per non tremare.
3. Animazione con un `QTimer` a **30 fps**, 60 solo se la misura lo permette. **Il timer si ferma**
   quando la vista è nascosta o minimizzata, e con "riduci animazioni" attivo. Un test conta i
   ridisegni con la finestra nascosta e ne vuole zero: in residenza per 72 ore, un'animazione
   invisibile è CPU sprecata.
4. L'inviluppo della voce nel player (§Scelte tecniche). Un test sintetizza un segnale noto
   (silenzio, tono, silenzio) e verifica che il livello letto durante la riproduzione lo segua.
5. **Misura, giorno 7:** tempo di `paintEvent` del nucleo (p95), CPU del processo con l'Hub
   visibile a riposo e in `PARLATO`, `MisuratoreLag` durante 10 minuti di conversazione. Se il
   disegno supera i 4 ms a 1080p si passa a `QOpenGLWidget`, altrimenti no.

### Giorni 9–10 — Colonna sinistra: sistema, sessione, meteo

1. **Sistema:** CPU, RAM e **VRAM**, con la barra rossa sopra 7,5 GB come oggi (è l'indicatore
   della matrice degli errori di M7), più le tessere CPU, RAM, disco e temperatura GPU. Il disco
   si aggiunge al worker di telemetria esistente, a 0,2 Hz: `psutil.disk_usage` non va letto due
   volte al secondo.
2. **Sessione** (la "System Uptime" della reference): da quanto è attivo Metis, turni, azioni
   eseguite, azioni negate. Per il carico si usa la media mobile della CPU: `getloadavg` su
   Windows è un'emulazione.
3. **Meteo** (D-UI 5):
   - worker su un `QThread` suo, che non importa `QtWidgets` (la regola di M3 vale anche qui, e il
     test che la verifica copre `metis/gui/workers/` da solo);
   - Open-Meteo ogni 15 minuti, con una cache che sopravvive al riavvio;
   - i codici meteo WMO tradotti in italiano, con la loro icona;
   - **senza rete**: ultimo dato con l'ora ("alle 14:30"), poi una frase in persona. Mai un
     traceback e mai un'attesa sul thread della GUI;
   - la città si imposta nelle Impostazioni: la geocodifica di Open-Meteo trasforma il nome in
     coordinate, una volta sola, e il risultato va in `config/gui.local.toml`.

### Giorni 11–12 — Fotocamera (D-UI 1)

1. Worker che legge un'istantanea con `GET /api/camera_proxy/<entity_id>` di Home Assistant,
   usando lo stesso token del Credential Manager di M6. Un fotogramma al secondo, **solo con il
   modulo acceso e visibile**.
2. **Spenta all'avvio, sempre.** Si accende con un clic, e un'indicazione "IN DIRETTA" resta
   visibile finché è accesa.
3. **Nessun fotogramma tocca il disco o il modello.** L'immagine vive in memoria fino al
   fotogramma successivo. Un test verifica che il modulo non importi niente di `metis/llm` né di
   `metis/memory` e che non scriva file.
4. Il pulsante di accensione mostra e nasconde il flusso nella GUI. **Non accende la videocamera
   fisica**: quello sarebbe un'azione su un dispositivo, e passerebbe dal broker come ogni altra.
5. Home Assistant non è ancora disponibile (M6 in pausa): come in M6 si sviluppa contro un
   server finto che risponde a `camera_proxy` con un JPEG, e la prova con la videocamera vera
   resta un criterio aperto.

### Giorni 13–14 — Le altre viste e le impostazioni

1. **Minimal:** stessa cornice, un nucleo in miniatura (64 px) al posto del pallino, stesse
   informazioni di oggi.
2. **Diagnostica:** la control room di oggi con il nuovo tema. Il contenuto non cambia.
3. **Dialogo di conferma T3:** nuovo aspetto, **stesse proprietà**. Nessun pulsante predefinito,
   fuoco su "Nega", argomenti per intero, conto alla rovescia: i test di `test_gui_conferma.py`
   non si toccano, e se falliscono si corregge il dialogo, non il test.
4. **Tray:** voci "Mostra Minimal / Hub / Diagnostica".
5. **Impostazioni** (⚙): città del meteo, fotocamera (entità), riduci animazioni, vista all'avvio,
   muto all'avvio. Si salvano in `config/gui.local.toml`, ignorato da git.

### Giorni 15–16 — Verifica

1. **NFR-8 ricertificato:** 30 minuti di uso reale con l'Hub visibile e le animazioni attive,
   `MisuratoreLag` in fase di esercizio, 0 freeze oltre 100 ms. Il log porta la `fase` da M7, e
   `tests/nfr/verifica_nfr.py` legge da lì.
2. **Risoluzioni e DPI:** 1280×720, 1920×1080 e il secondo monitor, a 100%, 125% e 150%. Il
   processo è già per-monitor DPI aware da M4, e un cambio di monitor non deve sfocare i font.
3. **Revisione visiva:** `benchmarks/gui_screenshot.py` produce le catture di ogni vista in ogni
   stato con dati finti. Il criterio estetico è soggettivo, quindi **lo chiude l'utente
   guardando le catture**, non un test.
4. **Bundle** rigenerato con font e icone e riprovato su cartella pulita (la prova di M7).
5. Specifica §11 aggiornata (tre viste, nucleo, input di testo), `docs/INSTALL.md` (meteo,
   fotocamera, `gui.local.toml`).

---

## Criteri di uscita

- [ ] Hub con le tre colonne della reference, approvato dall'utente sulle catture
- [ ] **NFR-8 ricertificato con le animazioni attive**: 0 freeze > 100 ms in 30 minuti d'uso, ≥ 30 fps
- [ ] Disegno del nucleo p95 < 4 ms a 1080p (o `QOpenGLWidget`, se non basta)
- [ ] **Zero ridisegni con la finestra nascosta**: le animazioni si fermano in tray
- [ ] Stati distinguibili a colpo d'occhio: palette verificata dal test sulle tonalità
- [ ] L'onda segue la voce di Metis, dal player e non dal motore
- [ ] Input di testo con **lo stesso percorso di sicurezza** della voce, conferma T3 compresa
- [ ] I turni scritti esclusi da NFR-1/NFR-2
- [ ] "Pulisci" azzera vista, memoria e slot; "Esporta" produce Markdown
- [ ] Meteo senza rete: ultimo dato o frase in persona, nessun blocco
- [ ] Fotocamera spenta all'avvio, nessun fotogramma su disco o al modello
- [ ] Fotocamera provata con la videocamera vera di Home Assistant — *quando HA sarà disponibile*
- [ ] Tutti i test di M3 verdi senza modifiche: thread, lambda, conferma T3, cambio vista
- [ ] Nessun colore esadecimale fuori da `tema.py` e `palette.py`
- [ ] Layout corretto da 1280×720 in su, a 100/125/150% di scala
- [ ] Bundle con font e icone, provato su cartella pulita
- [ ] Specifica §11 e `docs/INSTALL.md` aggiornati
- [ ] `git tag p1-hub`

---

## Fuori ambito

| Cosa | Quando |
| :-- | :-- |
| Webcam del PC | Solo con una decisione esplicita sulla privacy (D-UI 1) |
| Meteo come strumento di Metis | Backlog (D-UI 6) |
| Tema chiaro, temi personalizzabili | Backlog V1.1 #6 |
| Streaming video continuo della videocamera | Qui istantanee a 1 fps; il flusso RTSP è un'altra cosa |
| Grafici storici della telemetria | Backlog |
| Riscrittura in QML | Scartata (§Scelte tecniche) |
| Wake word | v2, invariato |

---

## Rischi e contromisure

| Rischio | Effetto | Contromisura |
| :-- | :-- | :-- |
| Rifinitura estetica senza fine | La fase non chiude mai | Due revisioni sulle catture (giorni 8 e 16), poi si chiude |
| Effetti grafici costosi (ombre, sfocature, trasparenze) | NFR-8 fallisce durante l'inferenza | Bagliore disegnato con gradienti; misura al giorno 7 |
| Animazioni sempre accese | CPU sprecata per 72 ore in tray | Timer fermo quando non è visibile, con un test |
| Ciano ovunque | Gli stati non si distinguono più | Colore del nucleo dalla palette; test sulle tonalità |
| `QOpenGLWidget` instabile | Schermo nero su certi driver, problemi con l'overlay traslucido | QPainter prima; OpenGL solo se misurato e mai nell'overlay |
| Rete o Home Assistant lenti | Blocchi della GUI | Ogni rete su un worker; timeout; la regola dei thread verificata dal test di M3 |
| L'input di testo apre una porta laterale | Un'azione senza conferma | Stesso `_process`, stesso broker; test dedicato |
| Font non caricati nel bundle | Carattere di ripiego, estetica rotta solo nel bundle | Test di caricamento; prova su cartella pulita |
| Licenze delle risorse | Problemi di redistribuzione | Solo OFL, ISC, MIT, con i file di licenza accanto |

---

## Handoff

Alla fine di PHASE1:

- l'Hub è la vista predefinita; Minimal e Diagnostica restano, con lo stesso tema;
- NFR-8 è ricertificato sulla nuova interfaccia;
- `tema.py` e `componenti.py` sono la base per qualunque vista futura;
- restano aperti, e ereditati: la fotocamera con Home Assistant vero e i criteri di M7 (soak,
  100 interazioni reali, autostart con riavvio, installazione da zero).
