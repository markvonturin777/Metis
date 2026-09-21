"""Da esito di uno strumento a frase da pronunciare.

PERCHE' MODELLI E NON UN GIRO DALL'LLM
Far riformulare l'esito al modello costerebbe un round trip completo — 400 ms
buoni — per dire "fatto". Su un'azione riuscita non serve varieta': serve
conferma breve. Il giro dall'LLM ha senso quando c'e' da spiegare qualcosa,
e in M2 non c'e'.

LE RISPOSTE SONO CORTE PERCHE' VENGONO ASCOLTATE
Un dizionario letto ad alta voce e' inascoltabile. Si dicono i due o tre
numeri che contano e si tace il resto: chi vuole il dettaglio lo trova
nell'audit log.

UN RIFIUTO DEVE DIRE PERCHE'
"Non posso" lascia l'utente a indovinare se ha sbagliato frase, se Metis e'
rotto o se e' stato bloccato apposta. Il motivo c'e' gia' nel Result: si
pronuncia quello.
"""

from __future__ import annotations

from metis.security.audit import Outcome
from metis.security.broker import Result

_APP = {"vscode": "Visual Studio Code", "github_desktop": "GitHub Desktop"}


def descrivi(result: Result) -> str:
    if result.outcome is Outcome.DENIED:
        return f"Non lo faccio: {result.detail}"
    if result.outcome is Outcome.ERROR:
        if "non ancora disponibile" in result.detail:
            return "Quella capacita' non c'e' ancora."
        return f"Non ci sono riuscito: {result.detail}"

    v = result.value if isinstance(result.value, dict) else {}

    if result.tool == "open_application":
        return f"Ho aperto {_APP.get(v.get('app'), v.get('app', 'l applicazione'))}."

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

    return "Fatto."
