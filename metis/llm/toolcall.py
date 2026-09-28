"""Decidere se una frase e' una richiesta di azione, e quale.

UNA SOLA CHIAMATA, NON DUE
La tentazione e' chiedere prima "e' un comando?" e poi "quale comando?".
Sono due round trip, due occasioni di sbagliare e il doppio della latenza.
Qui l'alternativa "nessuno strumento" e' **un membro della union**: il
modello sceglie fra gli strumenti disponibili e quella, con output
strutturato, in una chiamata sola. Rispondere a parole e' una scelta
esplicita come le altre, non l'assenza di scelta.

M4 — UNA LISTA DI AZIONI, NON UNA SOLA
"Metti Chrome sull'altro schermo e massimizzala" e' una frase sola e due
azioni. Da M4 la risposta strutturata e' quindi una LISTA, con un tetto
basso: al massimo tre. Il tetto non e' prudenza generica — e' che un
modello da 8 miliardi di parametri, davanti a uno schema che accetta una
lista, tende a riempirla, e ogni azione in piu' e' un'azione che l'utente
non ha chiesto e che il broker eseguira' comunque, perche' e' valida.

Le contromisure sono tre, e solo la terza regge da sola: il tetto, una
riga esplicita nel prompt, e il fatto che ogni elemento della lista
attraversa il broker per conto suo e la sequenza si ferma al primo
rifiuto. Una lista sbagliata costa una frase di spiegazione, non una
catena di azioni.

L'OUTPUT STRUTTURATO NON BASTA
`format=schema` vincola la GRAMMATICA, non il senso: il modello produrra'
sempre un JSON valido per lo schema, e potra' comunque scegliere lo
strumento sbagliato o un'applicazione che non c'entra. Per questo il broker
rivalida tutto: qui si guadagna che il JSON arriva sempre ben formato, non
che sia giusto.

UN SOLO TENTATIVO DI RIPARAZIONE
Se la validazione fallisce si reinietta l'errore Pydantic e si riprova una
volta. Poi si rinuncia. Un secondo tentativo alla cieca non serve: se il
modello sbaglia due volte non sta sbagliando la sintassi, sta sbagliando
l'intento, e insistere produce solo latenza.

LA FRASE DELL'UTENTE, UNA VOLTA SOLA (PHASE1)
Da M5 l'orchestratore mette la frase in memoria PRIMA di chiedere al router,
e la cronologia che passa la contiene gia'. Qui la si riaggiungeva in coda:
il modello la leggeva due volte, e una domanda ripetuta pesa come un ordine.
"Sai aiutarmi nella programmazione?" apriva VS Code 5 volte su 5; detta una
volta sola, 0 su 5. Si toglie dalla cronologia, perche' in coda deve restare:
e' l'ultima cosa che il modello deve leggere.

APRIRE UN'APPLICAZIONE CHIEDE UN VERBO (PHASE1)
Con la cronologia giusta il modello sbaglia ancora: dopo "Ho aperto Visual
Studio Code", "e se volessi farlo in locale?" riapriva VS Code 4 volte su 4.
La regola nel prompt non basta a un modello da 8 miliardi, quindi c'e' anche
nel codice: `open_application` passa solo se la frase contiene un verbo di
apertura. Vale per le decisioni del modello, non per i comandi rapidi, che
sono frasi scelte dall'utente ("inizia a lavorare").

TEMPERATURA BASSA
0,15 contro lo 0,7 della conversazione. Qui non serve varieta': serve che la
stessa frase produca sempre la stessa azione, perche' un assistente che a
volte apre VS Code e a volte no e' peggio di uno che non lo apre mai.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Annotated, Literal, Union

import ollama
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from metis.llm.client import NUM_CTX
from metis.tools.registry import Registry

MODEL = "qwen3:8b"
TEMPERATURA = 0.15

# "apri", "aprimi", "riapri", "avvia", "lancia", "fai partire", "esegui",
# "open": sulla frase normalizzata (minuscole, senza accenti). Un prefisso
# che prende anche una parola estranea ("aprile", "avvisami") lascia passare
# la decisione del modello, cioe' il comportamento di prima: il controllo
# puo' solo togliere un'azione, mai aggiungerla.
VERBO_APERTURA = re.compile(r"\b(?:ri)?(?:apr|avvi|lanci|esegu|open|start)\w*|\bpartire\b")

# PHASE2 — lo stesso controllo per `riproduci_youtube`. "Che musica mi
# consigli per rilassarmi?" faceva partire un video 2 volte su 3, con la
# regola gia' nel prompt. Metti, mettimi, riproduci, suona, apri/aprimi
# ("aprimi YouTube su ..."), avvia, lancia, play, e "fammi/fai sentire,
# vedere, ascoltare, partire".
VERBO_RIPRODUZIONE = re.compile(
    r"\b(?:metti|riproduc|suon|(?:ri)?apr|avvi|lanci|play)\w*"
    r"|\bfa(?:mmi|i|te|cci)? (?:sentire|vedere|ascoltare|partire)\b")

PROMPT = """Sei il router di Metis, un assistente vocale su questo PC.
Ricevi cio' che l'utente ha detto e scegli UNA cosa da fare.

Strumenti disponibili:
{strumenti}

Regole:
- Rispondi con una lista "azioni".
- QUASI SEMPRE la lista contiene UN SOLO elemento. Mettine due solo se
  l'utente ha chiesto esplicitamente due cose ("... e poi ..."); tre quasi
  mai. Un'azione che l'utente non ha chiesto verra' eseguita lo stesso.
- Per le finestre: "window" e' un pezzo del TITOLO della finestra.
  Lascialo VUOTO se l'utente dice "questa finestra" o non ne nomina una.
  MA un pronome attaccato al verbo — spostaLA, rimpiccioliscILA,
  massimizzaLO, chiudiLA — si riferisce alla finestra del [CONTESTO
  CORRENTE] ("Finestra di riferimento" o "Ultima azione"): scrivi quel
  titolo in "window", non lasciarlo vuoto.
- Per "monitor" usa "altro", "destra", "sinistra" o "primario". "L'altro
  schermo", "sull'altro monitor" = "altro". Un NUMERO solo se l'utente dice
  esplicitamente un numero di schermo.
- Le applicazioni: "vscode" = Visual Studio Code, l'editor di codice;
  "github_desktop" = GitHub Desktop, il client di git; "chrome" = il
  browser.
- "fammi sentire", "riproduci" una canzone, della musica, un video =
  "riproduci_youtube", con in "query" cosa cercare. Un consiglio su musica
  o video ("che canzone mi consigli?") = "nessuno_strumento".
- Se la richiesta corrisponde chiaramente a uno strumento, usalo.
- Usa "web_search" SOLO quando la risposta dipende da qualcosa che cambia
  nel tempo o che nessuno puo' sapere a memoria: notizie, prezzi,
  quotazioni, meteo, risultati, orari, versioni, "ultime novita' su", "cosa
  e' successo", "quanto costa oggi". Nel campo "query" scrivi cosa cercare,
  non la frase dell'utente parola per parola.
- "come si fa", "come faccio", "come posso", "come funziona", "che
  differenza c'e'", "cos'e'", "perche'", "mi spieghi", "mi consigli" sono
  SPIEGAZIONI: "nessuno_strumento", anche quando parlano di tecnologia, di
  programmi o di intelligenza artificiale. Metis le sa, e una pagina web
  trovata a caso le spiega peggio. Esempi: "come si cucina il risotto",
  "come faccio un curriculum", "che differenza c'e' tra HTTP e HTTPS",
  "come posso migliorare il mio inglese", "e se volessi farlo da solo?" =
  "nessuno_strumento".
- NON usare "web_search" per definizioni, spiegazioni, calcoli, opinioni,
  storia, o per qualunque cosa che non sia cambiata di recente.
- Altrimenti usa "nessuno_strumento": conversazione, domande, saluti,
  richieste che nessuno strumento sopra puo' soddisfare.
- Nel dubbio scegli "nessuno_strumento". Rispondere a parole non fa danni,
  agire quando non era richiesto sì.
- Non inventare strumenti e non inventare argomenti.
- Se ricevi un blocco [CONTESTO CORRENTE], quelle righe dicono a cosa si
  riferiscono "la", "lo", "quella finestra", "quel sito": usale per
  riempire gli argomenti invece di lasciarli vuoti o di inventarli.
- "aprimi il primo risultato", "apri quel sito", "aprila", "fammela
  vedere" dopo una ricerca = "open_url" con l'indirizzo della riga
  "Ultima fonte". NON una nuova ricerca: l'indirizzo ce l'hai gia'.
- "torna su quell'argomento", "dimmi le ultime su quello", "aggiornamenti"
  = "web_search" con il testo della riga "Ultimo argomento cercato".
  Cercare di nuovo, non rileggere la stessa pagina: l'utente vuole cio'
  che e' cambiato.
- "ricordami di ...", "promemoria per ..." = "schedule_reminder". Nel campo
  "quando" scrivi data e ora nel formato AAAA-MM-GGTHH:MM.
  Per un GIORNO ("domani", "lunedi'", "venerdi'") copia la data dalla riga
  del [CALENDARIO], non calcolarla.
  Per un INTERVALLO ("fra mezz'ora", "tra un'ora") copia il valore dalla
  riga [INTERVALLI]; se non c'e', parti dall'ora di [ADESSO].
  Se l'utente non dice l'ora: la mattina e' 09:00, il pomeriggio 15:00, la
  sera 20:00.
- "mandami/manda una mail ... domani/lunedi'/alle ..." = "schedule_email".
  Solo se c'e' un momento futuro; se e' "adesso" o non c'e' un momento,
  "send_email". "Mandami" = all'indirizzo della riga [UTENTE]. Non
  inventare MAI un indirizzo: se non lo conosci, "nessuno_strumento".
- "cosa ho in programma", "che promemoria ho" = "list_reminders".
  "cancella/annulla il promemoria di ..." = "cancel_reminder": in
  "riferimento" UNA o due parole del contenuto ("commercialista"), non la
  frase intera. "No, annullalo" subito dopo un promemoria =
  "cancel_reminder" con il testo della riga "Ultima azione".
- "set_home_device" SOLO se l'utente da' un ORDINE con un verbo di comando:
  "accendi", "spegni", "attiva", "disattiva", "dai le crocchette". Nel
  campo "dispositivo" scrivi l'OGGETTO da accendere ("crocchette", non
  "gatto").
- Una domanda, un'opinione, un consiglio o un commento su un dispositivo
  NON e' un ordine: "mi piace la friggitrice", "la consigli?", "e' buona?",
  "quanto consuma?" = mai "set_home_device". Accendere quando non era
  richiesto e' l'errore peggiore: un dispositivo fisico scalda davvero.
- "e' accesa?", "com'e' la ..." = "get_home_state". "che dispositivi ho" =
  "list_home_devices"."""


class NessunoStrumento(BaseModel):
    """Nessuna azione: si risponde a parole."""

    model_config = ConfigDict(extra="forbid")
    tool: Literal["nessuno_strumento"]


@dataclass
class Decisione:
    """Cosa fare, e quanto e' costato deciderlo.

    `calls` e' una tupla anche quando l'azione e' una sola, che resta il
    caso normale. `call` sopravvive come proprieta' perche' quasi tutti i
    lettori vogliono la prima e unica azione, e obbligarli a scrivere `[0]`
    avrebbe sparso indici nel codice per un caso che ricorre di rado.
    """

    calls: tuple[dict, ...] = ()      # vuota = conversazione
    origine: str = "llm"              # "llm" | "fast_path" | "chat"
    latenza_ms: float = 0.0
    riparazioni: int = 0
    errore: str | None = None
    # Frase gia' pronta, se la decisione viene da un comando custom che ne
    # dichiara una. Altrimenti la compone `risposte.descrivi`.
    risposta: str | None = None
    # PHASE2: una domanda fissa al posto della conversazione, quando la frase
    # chiedeva un'azione e l'azione non si e' potuta decidere. Vedi
    # `frasi_chiuse.chiarimento` e `CHIARIRE_SE_TOLTO`.
    chiarimento: str | None = None
    # PHASE4: cosa il modello aveva proposto e il codice ha tolto (verbo
    # mancante, numero o testo non detti). Solo i NOMI degli strumenti: gli
    # argomenti sono scelte del modello, e un 81 inventato non va suggerito a
    # nessuno (specifica §9.6). Li legge il pannello delle frasi non capite.
    tolte: tuple[str, ...] = ()
    # PHASE4: due JSON non validi di fila. Diverso da `errore` senza azioni,
    # che vale anche per Ollama giu': quello non e' una frase non capita.
    riparazione_fallita: bool = False

    @property
    def call(self) -> dict | None:
        return self.calls[0] if self.calls else None

    @property
    def e_strumento(self) -> bool:
        return bool(self.calls)


MAX_AZIONI = 3


class ToolRouter:
    def __init__(self, registry: Registry, model: str = MODEL,
                 host: str = "http://127.0.0.1:11434"):
        self.registry = registry
        self.model = model
        self.client = ollama.Client(host=host)
        # Lo stesso contesto della conversazione, o Ollama ricarica il
        # modello a ogni cambio: vedi la nota su NUM_CTX in `client.py`.
        self.options = {"temperature": TEMPERATURA, "num_ctx": NUM_CTX}

    def _union(self):
        schemi = [s.schema for s in self.registry.per_il_modello()]
        schemi.append(NessunoStrumento)
        uno = Annotated[Union[tuple(schemi)], Field(discriminator="tool")]

        class Piano(BaseModel):
            """Cosa fare, in ordine."""

            model_config = ConfigDict(extra="forbid")
            azioni: list[uno] = Field(..., min_length=1, max_length=MAX_AZIONI)

        return TypeAdapter(Piano)

    def _prompt(self, slot: str = "") -> str:
        """Il prompt del router, con gli slot in coda.

        GLI SLOT SERVONO A CHI DECIDE, NON SOLO A CHI PARLA
        Iniettarli nel solo modello di conversazione risolve "di cosa stiamo
        parlando" e non risolve "spostala sull'altro schermo", che e' un
        problema di argomenti mancanti in una tool call. E' la meta' del
        meccanismo che si dimentica, perche' funziona a meta': Metis capisce
        il pronome e poi non sa cosa metterci dentro.
        """
        from metis.core.tempo import contesto_temporale

        base = PROMPT.format(strumenti=self.registry.descrizione_per_prompt())
        # M6 — che giorno e'. Un modello non ha un orologio: senza questa riga
        # "domani" e' il giorno dopo la data di addestramento, e il promemoria
        # finisce nel passato — dove la guardia lo rifiuta, per fortuna, ma
        # l'utente non capisce perche'. Ricalcolata a ogni decisione.
        base = f"{base}\n\n{contesto_temporale()}"
        # E chi e' "me" in "mandami una mail". Vedi `posta.indirizzo_utente`:
        # senza questa riga il modello inventerebbe un indirizzo.
        from metis.tools.posta import indirizzo_utente

        io = indirizzo_utente()
        if io:
            base += f"\n[UTENTE] il suo indirizzo email e' {io}"
        return f"{base}\n\n{slot}" if slot else base

    def warmup(self) -> float:
        """Prima decisione a vuoto. Misurata: 3823 ms a freddo, ~250 a caldo.

        Ollama compila la grammatica dell'output strutturato alla prima
        richiesta con quello schema. E' la stessa lezione di M0 sul
        caricamento dei modelli: il costo esiste, si paga una volta, e non
        deve pagarlo il primo turno dell'utente.
        """
        t0 = time.perf_counter()
        self.decidi("ciao")
        return _ms(t0)

    def decidi(self, testo: str, storia: list[dict] | None = None,
               slot: str = "") -> Decisione:
        """Ritorna la tool call da dare al broker, oppure None per la chat."""
        t0 = time.perf_counter()
        adapter = self._union()
        schema = adapter.json_schema()

        messaggi = [{"role": "system", "content": self._prompt(slot)}]
        messaggi += precedenti(storia, testo)
        messaggi.append({"role": "user", "content": testo})

        riparazioni = 0
        ultimo_errore: str | None = None

        from metis.core.errors import SALUTE, Categoria, classifica

        # M7 — Ollama noto come giu': conversazione subito, senza pagare i
        # 2,26 s di una connessione rifiutata. Sara' la generazione a dire in
        # persona che l'inferenza non risponde. Vedi `errors.Salute`.
        if SALUTE.e_giu(Categoria.INFERENZA):
            return Decisione((), "llm", _ms(t0), 0, "inferenza non disponibile")

        for tentativo in (1, 2):
            try:
                risposta = self.client.chat(
                    model=self.model, messages=messaggi, format=schema,
                    think=False, options=self.options,
                )
                grezzo = risposta["message"]["content"]
                SALUTE.su(Categoria.INFERENZA)
            except Exception as exc:              # noqa: BLE001
                # Ollama giu' o modello assente: si degrada in conversazione,
                # che e' il comportamento innocuo.
                if classifica(exc) is Categoria.INFERENZA:
                    SALUTE.giu(Categoria.INFERENZA)
                return Decisione((), "llm", _ms(t0), riparazioni,
                                 f"{type(exc).__name__}: {exc}")

            try:
                scelta = adapter.validate_python(json.loads(grezzo))
            except (ValidationError, ValueError) as exc:
                ultimo_errore = str(exc)[:300]
                if tentativo == 2:
                    break
                riparazioni += 1
                messaggi.append({"role": "assistant", "content": grezzo})
                messaggi.append({"role": "user", "content":
                                 "Quel JSON non e' valido: " + ultimo_errore +
                                 " Riprova rispettando lo schema."})
                continue

            # "nessuno strumento" vale per l'intero turno anche quando
            # compare in mezzo: un modello che scrive [apri_x,
            # nessuno_strumento] ha finito le azioni, non ne ha chiesta una
            # in piu'. Si tronca li'.
            azioni: list[dict] = []
            for a in scelta.azioni:
                if isinstance(a, NessunoStrumento):
                    break
                azioni.append(a.model_dump())
            chieste = [a for a in azioni if chiesta(a, testo)]
            tenute = senza_browser_superfluo(senza_deittici(chieste))
            note = []
            if len(chieste) < len(azioni):
                note.append(" e ".join(sorted({f"{a.get('tool')} non chiesto"
                                              if a.get("tool") == "clicca_numero"
                                              else f"{a.get('tool')} senza verbo"
                                              for a in azioni if a not in chieste})))
            if len(tenute) < len(chieste):
                note.append("chrome superfluo")
            nota = "; ".join(note) or None
            tolte = [a for a in azioni if a not in chieste]
            domanda = next((CHIARIRE_SE_TOLTO[a.get("tool")] for a in tolte
                            if a.get("tool") in CHIARIRE_SE_TOLTO), None) if not tenute else None
            return Decisione(tuple(tenute), "llm", _ms(t0), riparazioni, nota,
                             chiarimento=domanda,
                             # Una ricerca tolta perche' la domanda era un'opinione
                             # (PHASE6) e' il comportamento voluto, non una frase
                             # non capita: non va nel pannello di PHASE4.
                             tolte=tuple(a.get("tool", "?") for a in tolte
                                         if a.get("tool") != "web_search"))

        # Due tentativi falliti: si risponde a parole. Deny-by-default anche
        # qui — nel dubbio non si agisce.
        return Decisione((), "llm", _ms(t0), riparazioni, ultimo_errore,
                         riparazione_fallita=True)


def precedenti(storia: list[dict] | None, testo: str) -> list[dict]:
    """Gli ultimi scambi, senza la frase di adesso.

    Solo gli ultimi: il router decide su cio' che e' stato detto adesso, e un
    contesto lungo aumenta la latenza senza aiutare. I messaggi di sistema —
    persona, riassunto, slot — si saltano: quelli che servono qui sono gia'
    nel prompt del router, e gli altri parlano di come rispondere, non di
    cosa fare. La frase di adesso, se la cronologia la contiene gia', si
    toglie: va in coda, una volta (vedi la nota in testa).
    """
    if not storia:
        return []
    scambi = [m for m in storia if m.get("role") != "system"]
    if scambi and scambi[-1].get("role") == "user" and scambi[-1].get("content") == testo:
        scambi = scambi[:-1]
    return scambi[-4:]


# PHASE2, dopo le prove: "chiudi la prima scheda di Chrome" ha ridotto Chrome a
# icona. Il modello, senza uno strumento per la scheda, aveva preso il piu'
# vicino. Ridurre a icona passa solo con un verbo che lo chiede.
VERBO_RIDUZIONE = re.compile(
    r"\b(?:riduc|riduci|minimizz|rimpicciol|nascond|abbass|iconizz)\w*|\bicona\b")

# PHASE2, dopo le aggiunte (2026-09-28): il modello usava il muto come ripiego
# per "meno suono". "La musica e' troppo forte" e "fermati un attimo con la
# musica" toglievano l'audio, 3 volte su 3. Il muto passa solo se la frase
# parla di muto, silenzio, audio o suono.
VERBO_MUTO = re.compile(r"\bmut\w*|\bsilenz\w*|\bzitt\w*|\baudio\b|\bsuono\b")

# E i dispositivi di casa (T3): la regola "solo con un verbo di comando" era
# nel prompt da M6, non nel codice. Tolti gli strumenti dell'audio dal prompt,
# "la musica e' troppo forte" e' diventata `set_home_device`: la conferma
# l'avrebbe fermata, ma un T3 scelto per una lamentela non si propone.
VERBO_CASA = re.compile(r"\b(?:accend|spegn|attiv|disattiv|avvi|azion)\w*|\bdai\b"
                        r"|\bfai partire\b|\bmetti in funzione\b")

# PHASE4, dalla prima seduta vera (2026-09-28): "Devi dire grazie." e "Ma sei
# rincoglionito?" sono diventati `type_text`. Li ha fermati solo il controllo
# "il cursore non e' in un campo di testo"; con il fuoco in un campo, Metis
# avrebbe scritto "grazie". Si scrive solo se la frase chiede di scrivere.
VERBO_SCRITTURA = re.compile(r"\b(?:scriv|digit|batt|inserisc|dett)\w*")

# PHASE6 (D-CONV 11), dalla stessa seduta: "bravissimo, hai schippato una
# pubblicita' su youtube" e' diventato `click_element("pubblicita'")`. Un clic
# per nome passa solo se la frase chiede di cliccare.
VERBO_CLIC = re.compile(r"\b(?:clicc|click|premi|preme|pigia|schiacc|selezion|tocca)\w*")

# PHASE6 (D-CONV 7): le domande sui gusti di Metis non hanno una fonte. "Qual
# e' il David di Caravaggio che ti piace di piu'?" era finita sul web, e la
# risposta era "Informazione non presente nei sistemi". Con queste parole la
# ricerca proposta dal modello si toglie, e risponde la conversazione.
OPINIONE = re.compile(r"\bti piac\w*|\bpreferisc\w*|\b(?:tuo|tua|tuoi|tue)(?:\s+\w+){0,3}\s+prefer\w*"
                      r"|\bche ne pensi\b|\bcosa ne pensi\b|\bsecondo te\b")

# Gli strumenti che passano solo se la frase contiene il loro verbo.
VERBI_RICHIESTI = {"open_application": VERBO_APERTURA,
                   "riproduci_youtube": VERBO_RIPRODUZIONE,
                   "minimize_window": VERBO_RIDUZIONE,
                   "imposta_muto": VERBO_MUTO,
                   "set_home_device": VERBO_CASA,
                   "type_text": VERBO_SCRITTURA,
                   "click_element": VERBO_CLIC}

# Se il controllo toglie uno di questi, l'utente aveva chiesto un'azione: si
# fa una domanda invece di lasciare la frase alla conversazione. Non
# `open_application`: li' la frase tolta era una domanda ("sai aiutarmi nella
# programmazione?", PHASE1), e alla domanda si risponde.
CHIARIRE_SE_TOLTO = {"clicca_numero": "Non ho capito il numero: me lo ripete?",
                     "scrivi_nel_numero": "Non ho capito dove scrivere o cosa: me lo ripete?",
                     "minimize_window": "Non ho capito cosa fare: me lo ripete con altre parole?",
                     "imposta_muto": "Non ho capito cosa fare: me lo ripete con altre parole?",
                     "set_home_device": "Non ho capito cosa fare: me lo ripete con altre parole?"}


def chiesta(azione: dict, testo: str) -> bool:
    """L'azione e' stata chiesta dalla frase? Conta per gli strumenti di
    `VERBI_RICHIESTI` (vedi la nota in testa), e per `clicca_numero`."""
    if azione.get("tool") == "scrivi_nel_numero":
        # Il numero detto, e il testo DETTO: il modello non scrive nelle pagine
        # parole sue. Confronto sulle forme normalizzate.
        from metis.core.numeri_parlati import numeri_in
        from metis.core.router import normalizza

        detto = normalizza(testo)
        return (azione.get("numero") in numeri_in(detto)
                and normalizza(str(azione.get("testo", ""))) in detto)
    if azione.get("tool") == "clicca_numero":
        # PHASE2 — il numero deve essere stato DETTO. E' la stessa ragione per
        # cui le finestre non hanno un handle (specifica §9.6): un indice
        # inventato e' un intero valido, e qui e' un clic vero su qualcosa
        # che l'utente non ha scelto.
        from metis.core.numeri_parlati import numeri_in
        from metis.core.router import normalizza

        return azione.get("numero") in numeri_in(normalizza(testo))
    if azione.get("tool") == "web_search":
        from metis.core.router import normalizza

        return OPINIONE.search(normalizza(testo)) is None
    if azione.get("tool") == "type_text":
        # Il verbo di scrittura E il testo detto, come `scrivi_nel_numero`: il
        # modello non scrive parole sue.
        from metis.core.router import normalizza

        detto = normalizza(testo)
        scritto = normalizza(str(azione.get("text", "")))
        return (VERBO_SCRITTURA.search(detto) is not None
                and bool(scritto) and scritto in detto)
    verbo = VERBI_RICHIESTI.get(azione.get("tool"))
    if verbo is None:
        return True
    from metis.core.router import normalizza

    return verbo.search(normalizza(testo)) is not None


# PHASE2 — "window" vuoto vuol dire "la finestra di riferimento" (vedi
# `schemas._SuFinestra`). Con tre strumenti in piu' nel prompt il modello ha
# cominciato a scriverci il nome del concetto invece di lasciarlo vuoto:
# "Finestra di riferimento" (l'etichetta della riga del contesto), "questa
# finestra". Nessuna finestra ha quel titolo, e "sposta questa finestra a
# destra" falliva 3 volte su 3. Il senso e' univoco, quindi si normalizza qui.
# "Quella finestra" no: secondo il prompt si riferisce a un'altra, nominata
# nel contesto, e va risolta dal modello.
FINESTRA_DI_ADESSO = frozenset({
    "questa", "questa finestra", "finestra di riferimento",
    "la finestra di riferimento", "finestra corrente", "la finestra corrente",
    "finestra attuale", "la finestra attuale", "finestra in primo piano",
    "la finestra in primo piano",
})


def senza_deittici(azioni: list[dict]) -> list[dict]:
    from metis.core.router import normalizza

    return [{**a, "window": ""} if isinstance(a.get("window"), str)
            and normalizza(a["window"]) in FINESTRA_DI_ADESSO else a for a in azioni]


# Gli strumenti che aprono Chrome da soli, su un indirizzo.
APRONO_IL_BROWSER = frozenset({"open_url", "riproduci_youtube"})


def senza_browser_superfluo(azioni: list[dict]) -> list[dict]:
    """"Apri chrome e mettimi su YouTube ..." e' un'azione, non due (PHASE2).

    Il modello scrive spesso [open_application chrome, riproduci_youtube]:
    la prima apre una finestra vuota, la seconda una scheda con il video, e
    l'utente si ritrova due finestre. Se il piano apre gia' un indirizzo,
    l'apertura di Chrome si toglie. Come `chiesta`, puo' solo togliere.
    """
    if not any(a.get("tool") in APRONO_IL_BROWSER for a in azioni):
        return azioni
    return [a for a in azioni if not _chrome_a_parte(a)]


def _chrome_a_parte(a: dict) -> bool:
    """Aprire Chrome o portarlo davanti: lo fa gia' chi apre l'indirizzo."""
    if a.get("tool") == "open_application":
        return a.get("app") == "chrome"
    if a.get("tool") == "focus_window":
        return "chrome" in (a.get("window") or "").lower()
    return False


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0
