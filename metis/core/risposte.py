"""Da esito di uno strumento a frase da pronunciare.

PERCHE' MODELLI E NON UN GIRO DALL'LLM
Far riformulare l'esito al modello costerebbe un round trip completo — 400 ms
buoni — per dire "fatto". Su un'azione riuscita non serve varieta': serve
conferma breve. Il giro dall'LLM ha senso quando c'e' da spiegare qualcosa,
e qui non c'e'.

LE RISPOSTE SONO CORTE PERCHE' VENGONO ASCOLTATE
Un dizionario letto ad alta voce e' inascoltabile. Si dicono i due o tre
numeri che contano e si tace il resto: chi vuole il dettaglio lo trova
nell'audit log.

UN RIFIUTO DEVE DIRE PERCHE'
"Non posso" lascia l'utente a indovinare se ha sbagliato frase, se Metis e'
rotto o se e' stato bloccato apposta. Il motivo c'e' gia' nel Result: si
pronuncia quello.

M4 — UN RIFIUTO DELLO STRUMENTO NON E' UN GUASTO
"Non trovo nessun link che si chiami Contatti" arriva qui come un rifiuto
allo stadio `strumento`, e va detto con parole diverse da "non ci sono
riuscito": il primo e' Metis che si comporta bene, il secondo e' Metis
rotto. Confonderli insegnerebbe all'utente a ignorare entrambi.
"""

from __future__ import annotations

import random

from metis.security.audit import Outcome
from metis.security.broker import Result

_APP = {"vscode": "Visual Studio Code", "github_desktop": "GitHub Desktop",
        "chrome": "Chrome"}

# Gli stadi del broker che rifiutano una tool call malformata. Il loro
# dettaglio e' un messaggio tecnico (JSON, Pydantic, nome sconosciuto).
_STADI_TECNICI = frozenset({"json", "registro", "schema"})

_DOVE = {0: "sul primo schermo", 1: "sul secondo schermo",
         2: "sul terzo schermo", 3: "sul quarto schermo"}


def descrivi(result: Result) -> str:
    if result.outcome is Outcome.DENIED:
        if result.stage == "strumento":
            # Lo strumento ha scelto di non agire, e il motivo e' gia' una
            # frase rivolta all'utente: si pronuncia cosi' com'e'.
            return result.detail if result.detail.endswith(".") else result.detail + "."
        if result.stage in _STADI_TECNICI:
            # M7 — "Non lo faccio: to: String should match pattern..." era il
            # messaggio di Pydantic, pronunciato. Questi tre stadi rifiutano
            # una tool call MALFORMATA: il difetto e' della decisione, non
            # della richiesta, e il dettaglio serve al log, non all'utente.
            return "Non ho capito la richiesta abbastanza bene per agire."
        return f"Non lo faccio: {result.detail}"
    if result.outcome is Outcome.ERROR:
        if "non ancora disponibile" in result.detail:
            return "Quella capacita' non c'e' ancora."
        # M7 — era "Non ci sono riuscito: {detail}", e `detail` e' il testo
        # dell'eccezione: "ConnectionError: ...", pronunciato. La matrice
        # degli errori vieta che arrivi all'utente; resta nell'audit log.
        from metis.core.errors import Categoria, messaggio

        return messaggio(Categoria.STRUMENTO)

    v = result.value if isinstance(result.value, dict) else {}

    if result.tool == "open_application":
        return f"Ho aperto {_APP.get(v.get('app'), v.get('app', 'l applicazione'))}."

    if result.tool == "open_url":
        dominio = v.get("url", "").split("/")[2] if "//" in v.get("url", "") else ""
        return f"Ho aperto {dominio}." if dominio else "Ho aperto la pagina."

    if result.tool == "get_telemetry":
        pezzi = []
        if "vram_usata_gb" in v:
            pezzi.append(f"{v['vram_usata_gb']:.1f} giga di VRAM su "
                         f"{v.get('vram_totale_gb', 0):.0f}")
        pezzi.append(f"CPU al {v.get('cpu_percento', 0):.0f} per cento")
        pezzi.append(f"RAM al {v.get('ram_percento', 0):.0f}")
        return "Sto usando " + ", ".join(pezzi) + "."

    if result.tool == "get_active_window":
        titolo = (v.get("titolo") or "").strip()
        if not titolo:
            return "Non c'e' niente in primo piano."
        if len(titolo) > 70:
            titolo = titolo[:70] + "..."
        return f"In primo piano hai {titolo}."

    if result.tool == "list_windows":
        n = v.get("totale", 0)
        if n == 0:
            return "Non vedo finestre aperte."
        prime = [f["titolo"].split(" - ")[-1] for f in v.get("finestre", [])[:3]]
        return f"Hai {n} finestre aperte, fra cui " + ", ".join(prime) + "."

    if result.tool == "list_monitors":
        ms = v.get("monitor", [])
        if len(ms) == 1:
            return "Hai un solo schermo."
        scale = {m["scala"] for m in ms}
        coda = "" if len(scale) == 1 else ", con scaling diverso fra loro"
        return f"Hai {len(ms)} schermi{coda}."

    # -- finestre --------------------------------------------------------

    if result.tool == "move_window_to_monitor":
        if not v.get("spostata"):
            return v.get("nota", "Era gia' li'.").capitalize().rstrip(".") + "."
        dove = _DOVE.get(v.get("monitor"), "sull altro schermo")
        return f"Spostata {dove}."

    if result.tool == "resize_window":
        return "Fatto."

    if result.tool in ("maximize_window", "minimize_window", "restore_window"):
        return {"massimizza": "Massimizzata.", "riduci": "Ridotta a icona.",
                "ripristina": "Ripristinata."}.get(v.get("comando"), "Fatto.")

    if result.tool == "focus_window":
        if not v.get("in_primo_piano"):
            return ("Windows non me l'ha lasciata portare davanti: "
                    "l'icona dovrebbe lampeggiare.")
        return f"Eccola: {(v.get('titolo') or '')[:60]}."

    # -- input sintetico --------------------------------------------------

    if result.tool == "type_text":
        return f"Scritto in {v.get('processo', 'quella finestra')}."

    if result.tool == "press_hotkey":
        return f"Premuto {v.get('tasti', '')}."

    if result.tool == "click_element":
        return f"Cliccato {(v.get('elemento') or '')[:60]}."

    if result.tool == "scroll":
        return "Scorro."

    if result.tool == "drag":
        return "Trascinato."

    # -- web ---------------------------------------------------------------
    #
    # Si arriva qui solo quando il modello ha chiesto una ricerca fuori dal
    # percorso web — per esempio perche' la decisione conteneva `web_search`
    # in seconda posizione. Il percorso normale non passa di qua: la
    # risposta a una ricerca la genera il modello leggendo le fonti, non
    # questo file. Elencare i titoli ad alta voce sarebbe il modo piu' rapido
    # di trasformare Metis in un lettore di risultati di ricerca.

    if result.tool == "web_search":
        n = v.get("totale", 0)
        if not n:
            return "Non ho trovato fonti su questo."
        return f"Ho {n} fonti."

    if result.tool == "web_fetch":
        # Il titolo, o il nome del sito: un indirizzo non si pronuncia.
        from metis.llm.client import sito

        return f"Ho letto {(v.get('titolo') or sito(v.get('url', '')) or 'la pagina')[:60]}."

    # -- M6: nel tempo -------------------------------------------------------
    #
    # La data si ripete SEMPRE per esteso, anche dopo la conferma. E' la
    # seconda occasione per accorgersi che il modello ha capito male, e costa
    # tre parole.

    if result.tool == "schedule_reminder":
        return f"Promemoria per {v.get('in_parole', 'l orario indicato')}."

    if result.tool == "schedule_email":
        return f"Email a {v.get('to', '')} programmata per {v.get('in_parole', '')}."

    if result.tool == "list_reminders":
        voci = v.get("voci") or []
        if not voci:
            return "Non ha niente in programma."
        prima = voci[0]
        coda = "" if len(voci) == 1 else f" Ne ha {len(voci)} in tutto."
        return f"Il prossimo e' {prima['testo']}, {prima['in_parole']}.{coda}"

    if result.tool == "cancel_reminder":
        return f"Cancellato: {v.get('testo', '')}."

    if result.tool == "send_email":
        if v.get("rimandata"):
            from metis.core.errors import Categoria, messaggio

            return messaggio(Categoria.POSTA)
        return f"Email inviata a {v.get('to', '')}."

    # -- M6: nel mondo fisico ------------------------------------------------
    #
    # "In funzione" e non "acceso/accesa": i nomi vengono dal file di
    # configurazione e il genere non si indovina. Una frase che sbaglia il
    # genere della friggitrice suona rotta anche quando dice il vero.

    if result.tool == "get_home_state":
        nome = _maiuscola(v.get("nome", "il dispositivo"))
        if not v.get("noto"):
            return f"Non conosco lo stato di {v.get('nome', 'quel dispositivo')}."
        stato = "è in funzione" if v.get("acceso") else "non è in funzione"
        return f"{nome} {stato}."

    if result.tool == "list_home_devices":
        n = v.get("totale", 0)
        if not n:
            return "Non ho dispositivi di casa configurati."
        if not v.get("connesso"):
            return f"Ne conosco {n}, ma l'hub domotico non risponde."
        attivi = [d["nome"] for d in v.get("dispositivi", []) if d.get("acceso")]
        if not attivi:
            return f"Ne conosco {n}, e nessuno e' in funzione."
        return f"Ne conosco {n}. In funzione: {', '.join(attivi)}."

    if result.tool == "set_home_device":
        nome = v.get("nome", "il dispositivo")
        if v.get("azione") == "spegni":
            return f"Ho spento {nome}."
        frase = f"Ho acceso {nome}."
        if v.get("spegnimento"):
            # "automaticamente" e non "da solo": per la friggitrice sarebbe
            # "da sola". Stessa ragione di "in funzione", vedi sopra.
            frase += f" Si spegnerà automaticamente alle {v['spegnimento']}."
        elif "spegnimento" in v:
            frase += (" Attenzione: non sono riuscito a programmare lo "
                      "spegnimento automatico.")
        if v.get("limite_giorno") is not None:
            frase += f" Oggi {v.get('oggi')} su {v['limite_giorno']}."
        return frase

    return "Fatto."


def _maiuscola(s: str) -> str:
    return s[:1].upper() + s[1:]


def domanda_conferma(call: dict) -> str:
    """Cosa dire ad alta voce mentre la finestra di conferma e' aperta.

    Il piano chiede la conferma VOCALE dell'interpretazione: "Promemoria per
    domani, martedi' 4 novembre, alle 17:00. Confermo?". La decisione passa
    comunque dalla finestra — il microfono in ATTESA_CONFERMA e' chiuso, vedi
    `state_machine.STT_MUTED` — ma la data si sente, e sentirla e' cio' che
    permette di accorgersi che e' sbagliata senza leggere niente.
    """
    from metis.core import tempo

    tool = call.get("tool", "")

    def data() -> str:
        try:
            return tempo.in_parole(tempo.interpreta(call.get("quando", "")))
        except ValueError:
            return "un orario che non ho capito"

    if tool == "schedule_reminder":
        return f"Promemoria per {data()}: {call.get('testo', '')}. Confermo?"
    if tool == "schedule_email":
        return f"Email a {call.get('to', '')}, in partenza {data()}. Confermo?"
    if tool == "send_email":
        return f"Email a {call.get('to', '')}. Confermo l'invio?"
    if tool == "set_home_device":
        verbo = "Accendo" if call.get("azione") == "accendi" else "Spengo"
        try:
            from metis.tools.home_assistant import risolvi

            nome = risolvi(call.get("dispositivo", "")).nome
        except Exception:                          # noqa: BLE001
            nome = call.get("dispositivo", "il dispositivo")
        return f"{verbo} {nome}?"
    return "Serve la sua conferma."


# --- filler vocale ------------------------------------------------------------

# Il percorso web costa 1,5-4 s, dominati dalla rete e non comprimibili. Il
# rimedio non e' tecnico: e' dire qualcosa. Un assistente che tace per tre
# secondi sembra rotto; uno che dice "verifico" e poi tace per tre secondi
# sta lavorando.
FILLERS: tuple[str, ...] = (
    "Un momento, consulto le fonti.",
    "Verifico.",
    "Controllo le fonti.",          # PHASE1: era "Le fonti, subito.", che non si dice
    "Un istante, non vorrei inventarmi nulla.",
    "Guardo.",
)


class Filler:
    """Frasi di attesa, in ordine casuale ma senza ripetizioni immediate.

    Sentire sempre la stessa frase e' peggio del silenzio: diventa un suono
    di sistema, smette di significare "sto lavorando" e comincia a
    significare "ha ricevuto l'input". La rotazione e' la meta' meno ovvia
    del requisito, ed e' quella che si dimentica.

    `scelta` e' iniettabile perche' un test sul non-ripetersi con una
    sorgente casuale vera e' un test che ogni tanto passa per fortuna.
    """

    def __init__(self, frasi: tuple[str, ...] = FILLERS, scelta=random.choice):
        self.frasi = frasi
        self._scelta = scelta
        self.ultima: str | None = None
        self.emessi = 0

    def prossimo(self) -> str:
        candidate = [f for f in self.frasi if f != self.ultima] or list(self.frasi)
        self.ultima = self._scelta(candidate)
        self.emessi += 1
        return self.ultima


def descrivi_sequenza(risultati: list[Result], risposta: str | None = None) -> str:
    """La frase per un turno intero, che puo' avere piu' di un'azione.

    Tre casi, in quest'ordine di priorita':

    **Qualcosa e' andato storto.** Si dice cosa, e basta. La sequenza si e'
    fermata li', quindi il rifiuto e' l'unica informazione utile; elencare
    anche cio' che era riuscito prima farebbe sembrare un successo parziale
    una cosa che non lo e'.

    **Un comando custom con la sua frase.** Vince sulla descrizione
    automatica: se l'utente si e' preso la briga di scrivere "Le danze
    abbiano inizio", non vuole sentirsi dire "Ho aperto Visual Studio Code,
    ho aperto GitHub Desktop".

    **Tutto bene, nessuna frase scritta.** Si concatenano le descrizioni.
    Con il tetto di tre azioni per turno, e' al massimo una riga e mezza.
    """
    if not risultati:
        return "Non ho fatto niente."

    fallito = next((r for r in risultati if not r.ok), None)
    if fallito is not None:
        return descrivi(fallito)

    if risposta:
        return risposta

    frasi = [descrivi(r) for r in risultati]
    # "Fatto." ripetuto due volte suona come un'eco. Si tiene una volta
    # sola, e solo se non c'e' niente di piu' informativo da dire.
    utili = [f for f in frasi if f != "Fatto."]
    if not utili:
        return "Fatto."
    return " ".join(dict.fromkeys(utili))
