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

from metis.security.audit import Outcome
from metis.security.broker import Result

_APP = {"vscode": "Visual Studio Code", "github_desktop": "GitHub Desktop",
        "chrome": "Chrome"}

_DOVE = {0: "sul primo schermo", 1: "sul secondo schermo",
         2: "sul terzo schermo", 3: "sul quarto schermo"}


def descrivi(result: Result) -> str:
    if result.outcome is Outcome.DENIED:
        if result.stage == "strumento":
            # Lo strumento ha scelto di non agire, e il motivo e' gia' una
            # frase rivolta all'utente: si pronuncia cosi' com'e'.
            return result.detail if result.detail.endswith(".") else result.detail + "."
        return f"Non lo faccio: {result.detail}"
    if result.outcome is Outcome.ERROR:
        if "non ancora disponibile" in result.detail:
            return "Quella capacita' non c'e' ancora."
        return f"Non ci sono riuscito: {result.detail}"

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

    return "Fatto."


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
