"""Memoria conversazionale: ricordare abbastanza, dentro 8k token.

TRE LIVELLI, NON UNO

    finestra scorrevole   gli ultimi 8 turni, per intero
    riassunto             i turni piu' vecchi, condensati in <= 300 token
    slot di riferimento   lo stato degli oggetti citabili (slots.py)

Il terzo livello sta in un file suo perche' non e' memoria del *discorso*, e'
memoria del *mondo*: "la finestra di Chrome" resta vera anche se la frase in
cui e' stata nominata e' uscita dalla finestra scorrevole.

IL BUDGET NON E' UN'OTTIMIZZAZIONE, E' IL VINCOLO
8k token di contesto sono la conseguenza degli 8 GB di VRAM (§3.2 della
specifica). Ogni token speso in contenuto web e' un token tolto alla
memoria. Con tre fonti da 1.200 token il web si prende meta' del contesto, e
senza un tetto esplicito la memoria verrebbe espulsa in silenzio — il
sintomo sarebbe "Metis ogni tanto dimentica", che e' fra i difetti piu'
difficili da riprodurre.

IL RIASSUNTO NON STA SUL PERCORSO CRITICO
Riassumere costa 2-3 secondi. Farlo quando il contesto si riempie significa
che un turno a caso, in modo imprevedibile, dura tre secondi in piu' — che
e' il tipo peggiore di latenza, perche' non se ne capisce la causa e quindi
non si impara a prevederla.

Qui si separano le due domande: `serve_riassunto()` dice se c'e' da farlo e
costa una divisione; `compatta()` lo fa davvero e lo chiama l'orchestratore
**solo in stato DORMIENTE**, cioe' quando nessuno sta aspettando. Se
l'utente riprende a parlare prima, il riassunto non parte e il contesto
resta grande: e' un problema piu' piccolo di una pausa inspiegata.

COSA NON SI RIASSUME MAI
System prompt, slot, ultimi 4 turni. I primi due perche' sono la persona e
il mondo, non il discorso. Gli ultimi 4 perche' sono esattamente quelli a cui
si riferiscono i pronomi della frase che l'utente sta per dire, e un
riassunto li trasformerebbe in "l'utente ha chiesto di una finestra", che
non e' abbastanza per risolvere "quella".
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from metis.llm.grounding import BUDGET, CONTESTO_MAX, conta_messaggi, conta_token

# Quanti turni completi restano sempre leggibili per intero. Un "turno" qui
# e' un messaggio: 8 turni di conversazione sono 16 messaggi.
FINESTRA_MESSAGGI = 16

# Mai riassunti, qualunque cosa succeda. Vedi la nota in testa.
INTOCCABILI_MESSAGGI = 8

# Il riassunto scatta al 70% del contesto occupato.
SOGLIA_RIASSUNTO = 0.70

MAX_TOKEN_RIASSUNTO = 300
TEMPERATURA_RIASSUNTO = 0.1

PROMPT_RIASSUNTO = """Riassumi questo scambio fra un utente e il suo assistente.

Regole:
- Al massimo 120 parole, in italiano, in terza persona.
- Se lo scambio comincia con un blocco [RIASSUNTO DEI TURNI PRECEDENTI],
  quel blocco e' memoria gia' condensata: RIPORTANE TUTTI I FATTI nel nuovo
  riassunto, e aggiungi quelli nuovi. Non ricominciare da capo.
- Conserva sempre: i nomi propri, le applicazioni aperte, le finestre, gli
  argomenti cercati, i numeri e le date.
- Conserva i fatti che l'utente ha dichiarato di se' o delle sue cose.
- Scarta: convenevoli, formule di cortesia, ripetizioni, e le domande a cui
  l'assistente ha risposto di non poter rispondere.
- Non aggiungere nulla che non sia nello scambio.
- Scrivi solo il riassunto, senza introduzione.

SCAMBIO:
{scambio}"""

INTESTAZIONE_RIASSUNTO = "[RIASSUNTO DEI TURNI PRECEDENTI]"


@dataclass
class Conteggio:
    """Da dove vengono i token del prossimo prompt. Serve alla GUI e ai banchi."""

    system: int = 0
    slot: int = 0
    riassunto: int = 0
    turni: int = 0
    web: int = 0

    @property
    def totale(self) -> int:
        return self.system + self.slot + self.riassunto + self.turni + self.web

    @property
    def occupazione(self) -> float:
        """Frazione del contesto gia' impegnata, margine di risposta escluso."""
        utile = CONTESTO_MAX - BUDGET["risposta"]
        return self.totale / utile if utile > 0 else 1.0

    def come_dizionario(self) -> dict:
        return {"system": self.system, "slot": self.slot,
                "riassunto": self.riassunto, "turni": self.turni,
                "web": self.web, "totale": self.totale,
                "occupazione": round(self.occupazione, 3)}


@dataclass
class Memoria:
    """La cronologia di una sessione, con il suo budget.

    `riassumi` e' iniettata: la memoria non sa che esiste Ollama, e i test
    possono farle riassumere con una funzione che non chiama niente. E' la
    stessa scelta fatta per il broker nell'orchestratore, per lo stesso
    motivo: cio' che riguarda la correttezza dev'essere verificabile senza
    accendere un modello.
    """

    system: str = ""
    riassumi: Callable[[str], str] | None = None
    finestra: int = FINESTRA_MESSAGGI
    intoccabili: int = INTOCCABILI_MESSAGGI
    soglia: float = SOGLIA_RIASSUNTO

    turni: list[dict] = field(default_factory=list)
    riassunto: str = ""
    riassunti_fatti: int = 0
    ms_riassunto: float = 0.0
    messaggi_condensati: int = 0

    def __post_init__(self) -> None:
        # Il turno scrive, la GUI legge, il riassunto riscrive da un terzo
        # thread. Tre scrittori su una lista sono un difetto che si vede una
        # volta ogni mille turni, cioe' mai durante lo sviluppo.
        self._lock = threading.RLock()

    # -- scrittura ---------------------------------------------------------

    def aggiungi(self, ruolo: str, testo: str) -> None:
        if not testo:
            return
        with self._lock:
            self.turni.append({"role": ruolo, "content": testo})

    def svuota(self) -> None:
        with self._lock:
            self.turni.clear()
            self.riassunto = ""

    # -- lettura -----------------------------------------------------------

    def messaggi(self, slot: str = "", fonti: str = "",
                 domanda: str | None = None) -> list[dict]:
        """I messaggi da passare al modello, nell'ordine che conta.

            system + slot        la persona e il mondo
            riassunto            cosa e' successo prima
            finestra scorrevole  gli ultimi turni per intero
            [fonti + domanda]    solo nei turni con contenuto web

        GLI SLOT STANNO NEL MESSAGGIO DI SISTEMA, NON IN UNO LORO
        Qwen 3 tratta il secondo messaggio `system` come testo qualunque, e
        un blocco di contesto declassato a testo qualunque e' un blocco che
        il modello contraddice. Attaccato al system prompt resta nella parte
        di prompt a cui il modello obbedisce.

        `domanda` sostituisce l'ultimo messaggio utente invece di
        aggiungersene uno: le fonti si iniettano **nel** turno che le ha
        recuperate, e la cronologia conserva la domanda pulita. Vedi la nota
        su cosa non entra in memoria in `grounding.py`.
        """
        with self._lock:
            testa = self.system
            if slot:
                testa = f"{testa}\n\n{slot}" if testa else slot

            out: list[dict] = []
            if testa:
                out.append({"role": "system", "content": testa})
            if self.riassunto:
                out.append({"role": "system",
                            "content": f"{INTESTAZIONE_RIASSUNTO}\n{self.riassunto}"})

            coda = self.turni[-self.finestra:]
            if domanda is not None:
                # La sostituzione vale se l'ultimo messaggio e' dell'utente,
                # che e' il caso normale: l'orchestratore lo aggiunge prima di
                # chiedere le fonti.
                #
                # SE NON LO E', SI AGGIUNGE. La prima versione lo scartava in
                # silenzio, e le conseguenze erano le peggiori possibili: il
                # modello riceveva la conversazione SENZA le fonti e
                # rispondeva a memoria a una domanda per cui si era appena
                # andati a cercare. Un turno che sembra fondato e non lo e'
                # e' esattamente lo scenario che questo progetto esiste per
                # evitare, e scartare in silenzio e' il modo piu' rapido di
                # arrivarci.
                if coda and coda[-1]["role"] == "user":
                    coda = coda[:-1] + [{"role": "user", "content": domanda}]
                else:
                    coda = list(coda) + [{"role": "user", "content": domanda}]
            out += [dict(m) for m in coda]

            if fonti and domanda is None:
                out.append({"role": "user", "content": fonti})
            return out

    def conteggio(self, slot: str = "", fonti: str = "") -> Conteggio:
        """Quanto costa il prossimo prompt, voce per voce."""
        with self._lock:
            return Conteggio(
                system=conta_token(self.system) + 5,
                slot=conta_token(slot),
                riassunto=conta_token(self.riassunto) + (5 if self.riassunto else 0),
                turni=conta_messaggi(self.turni[-self.finestra:]),
                web=conta_token(fonti),
            )

    def occupazione(self, slot: str = "", fonti: str = "") -> float:
        return self.conteggio(slot, fonti).occupazione

    # -- compattazione -----------------------------------------------------

    def da_condensare(self, slot: str = "") -> int:
        """Quanti messaggi in testa vanno riassunti adesso. Zero = niente.

        DUE SOGLIE, NON UNA (scoperta scrivendo i test, M5)
        Il piano dice "riassunto al 70% del contesto occupato", e con quella
        sola condizione il riassunto **non sarebbe mai partito**: la finestra
        scorrevole tiene 16 messaggi, e 16 messaggi di conversazione parlata
        occupano il venti per cento scarso del contesto. La soglia del 70%
        si raggiunge solo con messaggi lunghi, che in un assistente vocale
        sono l'eccezione.

        Il problema vero non era la pressione sul contesto: era che i turni
        usciti dalla finestra **sparivano**, e con loro l'argomento cercato
        quattro turni fa. Il caso di prova §4.4 numero 4 — "Cerca X, tre
        turni di altro, torna su quell'argomento" — non poteva funzionare.

        Quindi:

            sotto pressione     si condensa fino agli intoccabili, per fare
                                posto davvero (e' la soglia del piano)
            in condizioni normali  si condensa solo cio' che la finestra ha
                                gia' lasciato cadere, per non perderlo

        Il secondo caso non riduce il prompt di un token — quei messaggi non
        c'erano gia' piu'. Trasforma una perdita in un riassunto, che e' il
        motivo per cui i livelli di memoria sono tre e non due.
        """
        with self._lock:
            n = len(self.turni)
        if self.occupazione(slot) >= self.soglia:
            return max(0, n - self.intoccabili)
        return max(0, n - self.finestra)

    def serve_riassunto(self, slot: str = "") -> bool:
        """Costa una divisione: si puo' chiamare a ogni tick.

        Almeno due messaggi, cioe' uno scambio intero: riassumere una
        domanda senza la sua risposta produce un riassunto che dice cosa e'
        stato chiesto e non cosa e' successo.
        """
        return self.da_condensare(slot) >= 2

    def compatta(self, slot: str = "") -> bool:
        """Condensa i turni vecchi. **Solo in stato DORMIENTE.**

        Ritorna True se ha riassunto davvero. Non solleva: se il modello non
        risponde, la memoria resta grande — un problema minore che si
        risolve da solo al riavvio, mentre un'eccezione qui fermerebbe il
        thread che la chiama.
        """
        if self.riassumi is None:
            return False
        quanti = self.da_condensare(slot)
        if quanti < 2:
            return False
        with self._lock:
            vecchi = self.turni[:quanti]
            testa = self.riassunto

        scambio = "\n".join(
            f"{'Utente' if m['role'] == 'user' else 'Metis'}: {m['content']}"
            for m in vecchi)
        if testa:
            scambio = f"{INTESTAZIONE_RIASSUNTO}\n{testa}\n\n{scambio}"

        t0 = time.perf_counter()
        try:
            nuovo = (self.riassumi(PROMPT_RIASSUNTO.format(scambio=scambio)) or "").strip()
        except Exception:                          # noqa: BLE001
            return False
        if not nuovo:
            return False

        # Il tetto e' duro: un riassunto che cresce a ogni giro ricrea, un
        # turno alla volta, il problema che doveva risolvere.
        nuovo = _entro(nuovo, MAX_TOKEN_RIASSUNTO)

        with self._lock:
            # Fra l'inizio del riassunto e adesso l'utente puo' aver parlato:
            # si tagliano solo i messaggi che erano li' quando si e'
            # cominciato, non gli ultimi `quanti`.
            self.turni = self.turni[quanti:]
            self.riassunto = nuovo
            self.riassunti_fatti += 1
            self.messaggi_condensati += quanti
            self.ms_riassunto = (time.perf_counter() - t0) * 1000
        return True

    def stats(self) -> dict:
        with self._lock:
            return {"messaggi": len(self.turni),
                    "riassunti": self.riassunti_fatti,
                    "condensati": self.messaggi_condensati,
                    "token_riassunto": conta_token(self.riassunto),
                    "ms_ultimo_riassunto": round(self.ms_riassunto)}


def _entro(testo: str, max_token: int) -> str:
    """Tronca a un confine di frase. Vedi `grounding._taglia`, stessa regola.

    Il limite in caratteri e' una prima approssimazione e **si ricontrolla**:
    `conta_token` non e' una divisione, ha un sovrapprezzo per cifre e
    simboli, e un riassunto pieno di numeri costa piu' di quanto la
    conversione lasci credere. Senza il ciclo, il tetto di 300 token non era
    un tetto: era un'intenzione.
    """
    from metis.llm.grounding import CARATTERI_PER_TOKEN

    limite = int(max_token * CARATTERI_PER_TOKEN)
    for _ in range(8):
        if conta_token(testo) <= max_token:
            return testo.strip()
        taglio = testo.rfind(". ", 0, limite)
        testo = (testo[:taglio + 1] if taglio > limite // 2 else testo[:limite])
        limite = int(limite * 0.8)
    return testo.strip()
