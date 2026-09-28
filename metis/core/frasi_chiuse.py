"""Frasi chiuse con un parametro: riconosciute senza il modello (PHASE2).

    "cerca su youtube ricette di pasta"   ->  open_url(.../results?search_query=ricette+di+pasta)
    "mettimi su youtube un video relax"   ->  riproduci_youtube(query="video relax")
    "clicca il 7", "clicca sul sette"     ->  clicca_numero(numero=7)
    "mostra i numeri" / "nascondi i numeri" / "scorri giu'"
    "torna indietro", "chiudi la scheda"  ->  press_hotkey (le scorciatoie di Chrome)

LE STORPIATURE SONO MISURATE, NON IMMAGINATE
Le varianti di "mostra i numeri" qui sotto vengono dalla prima prova a voce
dell'utente (2026-09-26, `CONVOS/Metis_20260926_1920.md`): "Mastra in numeri",
"Mastrami i numeri", "Mostrain Numery", "Mastering numeria", "Mostra inumere".
Il modello le salvava quasi sempre, ma una volta ha NASCOSTO i numeri, e
un'altra ha risposto "Ecco 99 numeri" senza mostrarne nessuno.

PERCHE' NON BASTANO I COMANDI RAPIDI
Un comando rapido e' una frase fissa. Queste hanno un pezzo che cambia — cosa
cercare — e il pezzo va copiato, non interpretato. Il modello da 8 miliardi,
qui, sbagliava in modo stabile: "cerca su YouTube X" diventava `web_search`
tre volte su tre, con la regola scritta nel prompt. Un'espressione regolare
non ha bisogno di regole.

LA PORTA E' STRETTA DI PROPOSITO
Ogni frase qui dentro deve contenere letteralmente la parola che la
giustifica ("youtube"). Una frase che non la contiene passa al router, che e'
li' per le formulazioni libere. Un'espressione regolare che prova a capire
l'italiano diventa un secondo modello, peggiore del primo.

CIO' CHE ESCE E' MATERIALE PER IL BROKER
Come per i comandi rapidi: la scorciatoia salta il modello, non i controlli.
Le chiamate prodotte qui attraversano validazione, policy, guardie, conferma
e audit come tutte le altre. Il `pattern` di `OpenUrl` e il limite di 120
caratteri di `RiproduciYoutube` valgono anche per loro.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote_plus

# Le parole che si tolgono ai bordi della frase prima del confronto. Sono le
# cortesie del router, meno quelle che alla fine possono appartenere a cio'
# che si cerca.
_TOLTE_IN_TESTA = frozenset({
    "per", "favore", "perfavore", "cortesemente", "gentilmente", "prego",
    "metis", "puoi", "potresti", "ok", "okay", "ehi", "hey", "ciao", "senti",
    "dai", "allora", "adesso", "ora", "subito", "e", "si",
})
_TOLTE_IN_CODA = frozenset({"per", "favore", "perfavore", "grazie", "mille",
                            "metis", "prego", "ok", "okay"})

# In testa a cio' che si cerca: "un video" -> "video".
_ARTICOLI = re.compile(
    r"^(?:(?:un po|un poco) (?:di |d )?|(?:un|una|uno|il|lo|la|l|i|gli|le|del|dello|"
    r"della|dei|degli|delle|qualche) )+")

# "apri chrome e ..." davanti non cambia la richiesta: Chrome si apre comunque.
_PRIMA = r"(?:(?:ri)?apri(?:mi)? (?:google )?(?:chrome|il browser) e (?:poi )?)?"

_CERCA = re.compile(
    rf"^{_PRIMA}(?:mi )?cerca(?:mi)? (?:su youtube (?P<a>.+)|(?P<b>.+) su youtube)$")

_METTI = re.compile(
    rf"^{_PRIMA}(?:mi )?(?:mettimi|metti|mettici|riproduci|riproducimi|"
    r"fammi sentire|fammi vedere|fammi ascoltare|fai partire|fammi partire)"
    r"(?: su)? (?:youtube (?P<a>.+)|(?P<b>.+) su youtube)$"
    r"|"
    rf"^{_PRIMA}(?:ri)?apri(?:mi)? youtube (?:su|con) (?P<c>.+)$")

MAX_QUERY = 120

# PHASE2, i numeri. "clicca il 7" non ha niente da interpretare: un verbo, un
# articolo o una preposizione, un numero. Il numero si legge con
# `numeri_parlati.numero`, che accetta cifre e parole fino a 99.
_PREPOSIZIONI = r"(?:su|sul|sullo|sulla|il|lo|la|l|i|a|al|all|alla|allo|numero|n)"
_NUMERO = r"(?P<n>\w+(?: (?:e )?\w+)?)"
_CLICCA = re.compile(
    r"^(?:clicca(?:mi)?|click|clic|premi|seleziona|apri(?:mi)?) "
    rf"(?:{_PREPOSIZIONI} )*{_NUMERO}$")
# Senza verbo ("sul 60", "su ottantuna"): SOLO con i numeri a schermo, e con
# almeno una preposizione o un articolo. "Sei" da solo non e' un clic sul 6.
_SOLO_NUMERO = re.compile(rf"^(?:{_PREPOSIZIONI} )+{_NUMERO}$")
# PHASE4 — "ma stra minumere" (prima seduta vera, 2026-09-28, segnalata
# dall'utente dal pannello): il verbo spezzato in due, e una "mi" davanti a
# "numere". Il router aveva proposto un video.
_MOSTRA = re.compile(
    r"^(?:m[ao] ?st\w*|fammi vedere|fai vedere|metti|visualizza|dammi|numera)"
    r"(?: (?:i|in|tutti i))? (?:m?i)?n?umer\w*$")
_NASCONDI = re.compile(r"^(?:nascondi|togli|leva|chiudi|spegni|via|basta)(?: (?:i|con i))? numeri$")

# PHASE2, dopo le prove: il browser. Le scorciatoie di Chrome, che valgono
# anche nelle altre applicazioni a schede. "La prima scheda" e' Ctrl+1: il
# piano la seleziona e poi la chiude. Ctrl+9 e' sempre l'ultima.
_INDIETRO = re.compile(r"^(?:(?:torna|tornare|vai|va) (?:(?:alla )?pagina )?)?indietro$"
                       r"|^(?:torna |vai )?(?:alla )?pagina precedente$")
_AVANTI = re.compile(r"^(?:vai|torna) avanti$|^(?:vai )?(?:alla )?pagina successiva$")
_ORDINALI = {"prima": "1", "seconda": "2", "terza": "3", "quarta": "4", "quinta": "5",
             "sesta": "6", "settima": "7", "ottava": "8", "ultima": "9"}
_CHIUDI_SCHEDA = re.compile(
    r"^chiudi (?:la |l |questa )?(?:(?P<o>prima|seconda|terza|quarta|quinta|sesta|settima"
    r"|ottava|ultima) )?(?:aperta )?scheda(?: aperta)?(?: (?:di|del|in) (?:chrome|browser))?$")
_RIAPRI_SCHEDA = re.compile(r"^riapri (?:la |l )?(?:ultima )?scheda(?: chiusa)?$")
_NUOVA_SCHEDA = re.compile(r"^(?:apri )?(?:una )?nuova scheda$")

# Sembra un comando di navigazione, ma nessuno l'ha capito: meglio chiedere
# che lasciarlo alla conversazione, che una volta su due risponde "Cliccato"
# senza aver cliccato (#2 delle prove).
_SEMBRA_CLIC = re.compile(r"^(?:clicca\w*|click|clic|premi)\b|^(?:su|sul) \w+$")
_SEMBRA_ALTRO = re.compile(r"\bi?n?umer\w*$|^chiudi\b.*\bsched|\bindietro$|^riapri\b.*\bsched")
CHIEDI_NUMERO = "Non ho capito il numero: me lo ripete?"
CHIEDI_COMANDO = "Non ho capito cosa fare: me lo ripete con altre parole?"
# Lo scorrimento A BLOCCHI (richiesta dell'utente, 2026-09-28): "scorri giu'"
# e' una schermata, Pag giu'. Il passo piccolo della rotellina resta per "un
# po'". Pag giu' e Home/Fine vanno all'elemento che ha il fuoco: su una pagina
# scorrono la pagina, dentro una casella di testo muovono il cursore.
_VERSO = r"(?P<v>giu|su|basso|alto)"
_DIREZIONE = r"(?: (?:in|verso)(?: l| il)?)?"          # "verso l'alto", "verso il basso"
_SCORRI = re.compile(
    rf"^(?:scorri|scendi|sali|vai|va){_DIREZIONE} {_VERSO}"
    r"(?: di (?:una |un )?(?:pagina|blocco|schermata))?$"
    r"|^pagina (?P<p>giu|su)$|^(?P<s>scendi|sali)$")
_SCORRI_MOLTE = re.compile(
    rf"^(?:scorri|scendi|sali|vai){_DIREZIONE} {_VERSO} di (?P<n>\w+) "
    r"(?:pagine|blocchi|schermate)$")
_SCORRI_UN_PO = re.compile(
    rf"^scorri (?:un po|un poco|poco|piano){_DIREZIONE} {_VERSO}$"
    rf"|^scorri{_DIREZIONE} (?P<w>giu|su|basso|alto) (?:un po|un poco|di poco|piano)$")
_CIMA = re.compile(r"^(?:(?:vai|torna|scorri|salta) )?(?:in cima|all inizio)(?: della pagina)?$")
_FONDO = re.compile(r"^(?:(?:vai|scorri|salta) (?:in fondo|alla fine)|in fondo)(?: della pagina)?$")
MAX_PAGINE = 5

# PHASE2, dopo le prove (2026-09-28): musica, volume, browser, video.
# Le frasi sono chiuse: "pausa", "volume al 30". Le formulazioni libere le
# decide il router, che ha gli stessi strumenti.
# "Ferma" da solo no: e' anche cio' che si dice interrompendo Metis, e il tasto
# INVERTE lo stato: se non suonava niente, farebbe partire la musica.
_OGGETTO = r"(?:il video|la musica|la canzone|il brano)"
_PAUSA = re.compile(rf"^(?:metti in pausa|pausa|fai ripartire|riprendi|play|continua a suonare)"
                    rf"(?: {_OGGETTO})?$|^(?:ferma|stoppa|metti in pausa) {_OGGETTO}$")
_SUCCESSIVO = re.compile(r"^salta(?: (?:questa|questo|la|il))?(?: (?:canzone|brano|video"
                         r"|pezzo|traccia))?$"
                         r"|^(?:(?:vai al|metti il|passa al|metti la|passa alla) )?"
                         r"(?:brano|canzone|traccia|video|pezzo) (?:successiv[oa]|seguente|dopo)$"
                         r"|^(?:prossim[oa]|la prossima|il prossimo) (?:brano|canzone|traccia"
                         r"|video|pezzo)$")
_PRECEDENTE = re.compile(r"^(?:(?:torna al|metti il|torna alla|metti la) )?"
                         r"(?:brano|canzone|traccia|video|pezzo) precedente$")
_QUANTO = r"(?: di (?P<n>\w+(?: (?:e )?\w+)?)(?: punti| per cento)?)?"
_UN_PO = r"(?: un po| un pochino| un poco| appena)?"
_SUONO = r"(?: (?:il|l|la))? (?:volume|audio|musica|suono)"
_ALZA = re.compile(rf"^(?:alza|aumenta|sali con){_UN_PO}{_SUONO}{_UN_PO}{_QUANTO}$"
                   r"|^(?:piu forte|volume piu alto|alza)$")
_ABBASSA = re.compile(rf"^(?:abbassa|diminuisci|riduci|scendi con){_UN_PO}{_SUONO}{_UN_PO}"
                      rf"{_QUANTO}$|^(?:piu piano|volume piu basso|abbassa)$")
_VOLUME_A = re.compile(r"^(?:(?:metti|porta|imposta)(?: il)? )?volume (?:al |a |all )?"
                       r"(?P<n>\w+(?: (?:e )?\w+)?)(?: per cento)?$")
_MUTO = re.compile(r"^(?:muto|silenzio|silenzia(?: tutto)?|togli (?:l )?audio"
                   r"|disattiva (?:l )?audio|metti (?:il |in )?muto)$")
_SMUTO = re.compile(r"^(?:togli il muto|riattiva (?:l )?audio|rimetti (?:l )?audio"
                    r"|(?:ri)?accendi (?:l )?audio)$")
_CHE_VOLUME = re.compile(r"^(?:che volume (?:ho|c e|abbiamo)|a quanto e il volume"
                         r"|quanto e alto il volume|com e il volume)(?: adesso| ora)?$")
_RICARICA = re.compile(r"^(?:ricarica|aggiorna)(?: la pagina)?$")
_SCHEDA_DOPO = re.compile(r"^(?:vai alla |passa alla )?(?:scheda (?:successiva|seguente|dopo)"
                          r"|prossima scheda)$")
_SCHEDA_PRIMA = re.compile(r"^(?:vai alla |passa alla |torna alla )?scheda precedente$")
_VAI_SCHEDA = re.compile(r"^(?:vai|passa|torna) (?:alla |all )?(?P<o>prima|seconda|terza|quarta"
                         r"|quinta|sesta|settima|ottava|ultima) scheda$")
# "Ingrandisci" da solo no: puo' voler dire la finestra.
_ZOOM_PIU = re.compile(r"^(?:ingrandisci (?:la )?pagina|aumenta lo zoom|zoom avanti|zoom piu)$")
_ZOOM_MENO = re.compile(r"^(?:rimpicciolisci la pagina|riduci lo zoom|diminuisci lo zoom"
                        r"|zoom indietro|zoom meno)$")
_ZOOM_NORMALE = re.compile(r"^(?:zoom normale|ripristina lo zoom|zoom al cento per cento)$")
_SECONDI = re.compile(r"^(?:(?:vai|torna|manda|salta|spostati) )?(?P<d>avanti|indietro)"
                      r"(?: di (?P<n>\w+(?: (?:e )?\w+)?) (?P<u>secondi|secondo|minuto|minuti))?"
                      r"(?: nel video)?$")
_SCHERMO_INTERO = re.compile(r"^(?:(?:metti|vai|passa) (?:a |in )?)?(?:tutto |a tutto )?"
                             r"schermo intero$|^(?:esci dallo|togli lo) schermo intero$")
_SOTTOTITOLI = re.compile(r"^(?:(?:attiva|metti|togli|disattiva|accendi|spegni) (?:i )?)?"
                          r"sottotitoli$")
MAX_SALTI = 6                  # un minuto, a dieci secondi per salto

# La dettatura (D-NAV 10). "Premi invio" e' un comando a parte, che con il
# fuoco in un campo chiede conferma (D-NAV 11).
_INVIO = re.compile(r"^(?:premi |dai |fai )?invio$|^(?:invia|manda)$")

# Queste due si confrontano sulla trascrizione ORIGINALE, non su quella
# normalizzata: il testo dettato deve tenere maiuscole, accenti e punteggiatura.
_PREFISSO = r"^\s*(?:(?:per favore|metis|ok|ehi|allora)[\s,]+)*"
_SCRIVI_NEL = re.compile(
    _PREFISSO + r"(?:scrivi|digita|detta)\s+(?:nel|sul|nella|sulla|al|nello)\s+"
    r"(?:(?:campo|numero|casella)\s+)?(?P<resto>.+)$", re.IGNORECASE | re.DOTALL)
_DIGITA = re.compile(_PREFISSO + r"(?:digita|scrivi qui)\s*[:,]?\s+(?P<t>.+)$",
                     re.IGNORECASE | re.DOTALL)
_SEMBRA_DETTATURA = re.compile(r"^(?:scrivi|digita|detta) (?:nel|sul|nella|sulla|al|nello)\b")
CHIEDI_DETTATURA = "Non ho capito dove scrivere o cosa: me lo ripete?"
MAX_TESTO = 500


def _ritaglia(parole: list[str]) -> list[str]:
    while parole and parole[0] in _TOLTE_IN_TESTA:
        parole = parole[1:]
    while parole and parole[-1] in _TOLTE_IN_CODA:
        parole = parole[:-1]
    return parole


def _cosa(m: re.Match) -> str | None:
    q = next((g for g in m.groups() if g), "") or ""
    q = _ARTICOLI.sub("", q.strip()).strip()
    if len(q) < 2 or "youtube" in q.split():
        return None
    return q[:MAX_QUERY]


def _cerca_youtube(m: re.Match) -> tuple[dict, ...] | None:
    q = _cosa(m)
    if q is None:
        return None
    return ({"tool": "open_url",
             "url": "https://www.youtube.com/results?search_query=" + quote_plus(q)},)


def _riproduci_youtube(m: re.Match) -> tuple[dict, ...] | None:
    q = _cosa(m)
    if q is None:
        return None
    return ({"tool": "riproduci_youtube", "query": q},)


def _clic_per_numero(m: re.Match) -> tuple[dict, ...] | None:
    from metis.core.numeri_parlati import numero

    n = numero(m.group("n"))
    return ({"tool": "clicca_numero", "numero": n},) if n is not None else None


def _tasti(*combinazioni: list[str]) -> Callable[[re.Match], tuple[dict, ...]]:
    return lambda m: tuple({"tool": "press_hotkey", "keys": list(k)} for k in combinazioni)


def _chiudi_scheda(m: re.Match) -> tuple[dict, ...]:
    o = m.group("o")
    chiudi = {"tool": "press_hotkey", "keys": ["ctrl", "w"]}
    if not o:
        return (chiudi,)
    return ({"tool": "press_hotkey", "keys": ["ctrl", _ORDINALI[o]]}, chiudi)


def _verso(m: re.Match) -> str:
    d = m.groupdict()
    v = d.get("v") or d.get("p") or ("giu" if d.get("s") == "scendi" else "su")
    return "giu" if v in ("giu", "basso") else "su"


def _quanto(m: re.Match, predefinito: int) -> int | None:
    from metis.core.numeri_parlati import numero

    g = m.groupdict().get("n")
    if not g:
        return predefinito
    return numero(g)


def _passo_volume(verso: str):
    def costruisci(m: re.Match) -> tuple[dict, ...] | None:
        n = _quanto(m, 10)
        if n is None or not 1 <= n <= 50:
            return None
        return ({"tool": "cambia_volume", "verso": verso, "passo": n},)
    return costruisci


def _volume_a(m: re.Match) -> tuple[dict, ...] | None:
    from metis.core.numeri_parlati import numero

    parole = {"meta": 50, "massimo": 100, "minimo": 0, "zero": 0, "cento": 100}
    n = parole.get(m.group("n"))
    if n is None:
        n = numero(m.group("n"))
    if n is None and m.group("n").isdigit() and int(m.group("n")) in (0, 100):
        n = int(m.group("n"))
    return ({"tool": "set_volume", "livello": n},) if n is not None else None


def _salto(m: re.Match) -> tuple[dict, ...] | None:
    """"Avanti di 30 secondi": tre salti da dieci. Cinque secondi: una freccia."""
    avanti = m.group("d") == "avanti"
    if not m.group("n"):
        # "Vai avanti" / "torna indietro" senza durata sono il browser, non il video.
        return None
    from metis.core.numeri_parlati import numero

    n = numero(m.group("n")) or (1 if m.group("n") in ("un", "uno") else None)
    if n is None:
        return None
    secondi = n * 60 if m.group("u").startswith("minut") else n
    if secondi <= 7:
        return ({"tool": "comando_video", "comando": "avanti_poco" if avanti else "indietro_poco"},)
    salti = max(1, min(MAX_SALTI, round(secondi / 10)))
    return ({"tool": "comando_video", "comando": "avanti" if avanti else "indietro"},) * salti


def _video(comando: str):
    return lambda m: ({"tool": "comando_video", "comando": comando},)


def _scorri(m: re.Match) -> tuple[dict, ...]:
    tasto = "pagedown" if _verso(m) == "giu" else "pageup"
    return ({"tool": "press_hotkey", "keys": [tasto]},)


def _scorri_molte(m: re.Match) -> tuple[dict, ...] | None:
    from metis.core.numeri_parlati import numero

    n = numero(m.group("n"))
    if n is None or not 1 <= n <= MAX_PAGINE:
        return None
    return _scorri(m) * n


def _scorri_un_po(m: re.Match) -> tuple[dict, ...]:
    v = m.group("v") or m.group("w")
    return ({"tool": "scroll", "verso": "giu" if v in ("giu", "basso") else "su"},)


# (espressione, costruttore). In ordine: vince la prima che produce qualcosa.
FRASI: tuple[tuple[re.Pattern, Callable[[re.Match], tuple[dict, ...] | None]], ...] = (
    (_MOSTRA, lambda m: ({"tool": "mostra_numeri"},)),
    (_NASCONDI, lambda m: ({"tool": "nascondi_numeri"},)),
    (_CLICCA, _clic_per_numero),
    (_INVIO, _tasti(["enter"])),
    (_PAUSA, lambda m: ({"tool": "tasto_multimediale", "tasto": "play_pausa"},)),
    (_SUCCESSIVO, lambda m: ({"tool": "tasto_multimediale", "tasto": "successivo"},)),
    (_PRECEDENTE, lambda m: ({"tool": "tasto_multimediale", "tasto": "precedente"},)),
    (_ALZA, _passo_volume("su")),
    (_ABBASSA, _passo_volume("giu")),
    (_VOLUME_A, _volume_a),
    (_CHE_VOLUME, lambda m: ({"tool": "leggi_volume"},)),
    (_MUTO, lambda m: ({"tool": "imposta_muto", "muto": True},)),
    (_SMUTO, lambda m: ({"tool": "imposta_muto", "muto": False},)),
    (_RICARICA, _tasti(["f5"])),
    (_SCHEDA_DOPO, _tasti(["ctrl", "tab"])),
    (_SCHEDA_PRIMA, _tasti(["ctrl", "shift", "tab"])),
    (_VAI_SCHEDA, lambda m: ({"tool": "press_hotkey", "keys": ["ctrl", _ORDINALI[m.group("o")]]},)),
    (_ZOOM_PIU, _tasti(["ctrl", "plus"])),
    (_ZOOM_MENO, _tasti(["ctrl", "minus"])),
    (_ZOOM_NORMALE, _tasti(["ctrl", "0"])),
    (_SECONDI, _salto),
    (_SCHERMO_INTERO, _video("schermo_intero")),
    (_SOTTOTITOLI, _video("sottotitoli")),
    (_SCORRI_UN_PO, _scorri_un_po),
    (_SCORRI_MOLTE, _scorri_molte),
    (_SCORRI, _scorri),
    (_CIMA, _tasti(["home"])),
    (_FONDO, _tasti(["end"])),
    (_INDIETRO, _tasti(["alt", "left"])),
    (_AVANTI, _tasti(["alt", "right"])),
    (_CHIUDI_SCHEDA, _chiudi_scheda),
    (_RIAPRI_SCHEDA, _tasti(["ctrl", "shift", "t"])),
    (_NUOVA_SCHEDA, _tasti(["ctrl", "t"])),
    (_CERCA, _cerca_youtube),
    (_METTI, _riproduci_youtube),
)


def riconosci(detto: str, numeri_a_schermo: bool = False) -> tuple[dict, ...] | None:
    """Le chiamate per una frase gia' normalizzata, oppure None."""
    testo = " ".join(_ritaglia(detto.split()))
    if not testo:
        return None
    for espressione, costruisci in FRASI:
        m = espressione.match(testo)
        if m is not None:
            chiamate = costruisci(m)
            if chiamate:
                return chiamate
    if numeri_a_schermo:
        m = _SOLO_NUMERO.match(testo)
        if m is not None:
            return _clic_per_numero(m)
    return None


def _pulisci_dettato(t: str) -> str | None:
    """Il testo da scrivere: senza il punto finale che Whisper aggiunge a ogni
    frase (in una ricerca non serve), senza spazi ai bordi."""
    t = t.strip().lstrip(":,;").strip()
    if t.endswith(".") and not t.endswith(".."):
        t = t[:-1].rstrip()
    return t[:MAX_TESTO] if t else None


def dettatura(originale: str) -> tuple[dict, ...] | None:
    """"Scrivi nel 12: ricette di pasta", "digita buongiorno". Sulla frase
    ORIGINALE. Il numero si legge con `numeri_parlati`, anche in due parole."""
    from metis.core.numeri_parlati import numero
    from metis.memory.commands import normalizza

    m = _SCRIVI_NEL.match(originale or "")
    if m is not None:
        parole = m.group("resto").split(None, 2)
        for quante in (2, 1):
            if len(parole) <= quante - 1:
                continue
            candidato = " ".join(parole[:quante])
            n = numero(normalizza(candidato))
            if n is not None:
                resto = " ".join(parole[quante:]) if len(parole) > quante else ""
                testo = _pulisci_dettato(resto)
                if testo:
                    return ({"tool": "scrivi_nel_numero", "numero": n, "testo": testo},)
        return None
    m = _DIGITA.match(originale or "")
    if m is not None:
        testo = _pulisci_dettato(m.group("t"))
        if testo:
            return ({"tool": "type_text", "text": testo},)
    return None


def chiarimento(detto: str) -> str | None:
    """La domanda da fare se la frase sembra un comando e nessuno l'ha capito."""
    testo = " ".join(_ritaglia(detto.split()))
    if _SEMBRA_DETTATURA.search(testo):
        return CHIEDI_DETTATURA
    if _SEMBRA_CLIC.search(testo):
        return CHIEDI_NUMERO
    if _SEMBRA_ALTRO.search(testo):
        return CHIEDI_COMANDO
    return None
