"""Schemi degli strumenti — una sola fonte di verita'.

Ogni modello Pydantic e' CONTEMPORANEAMENTE la definizione passata a Ollama
per l'output strutturato e il validatore applicato dal broker. Due definizioni
separate divergerebbero, e divergerebbero proprio nel punto in cui la
divergenza e' pericolosa: il modello potrebbe produrre qualcosa che il broker
accetta ma che nessuno ha progettato.

IL VINCOLO PRINCIPALE NON E' UN CONTROLLO, E' UN'ASSENZA
"Metis non tocca i file personali" non si ottiene bloccando `os` e `shutil`:
l'LLM non esegue mai Python. Si ottiene **non esistendo alcun campo che
contenga un percorso**. Non c'e' niente da bloccare perche' non c'e' niente da
nominare. `test_nessuno_schema_accetta_un_percorso` lo verifica a ogni
esecuzione della suite, perche' la disciplina si perde e una `Path` aggiunta
per comodita' fra sei mesi non sembrerebbe pericolosa.

LE REGOLE DI PROGETTAZIONE

    Literal ovunque si possa enumerare  il modello non nomina cio' che non c'e'
    nessun campo percorso               e' il meccanismo di sicurezza
    max_length su ogni stringa          niente payload abnormi
    ge/le espliciti sui numeri          un monitor=99 non arriva al codice
    extra="forbid"                      un campo inventato e' un rifiuto
    union discriminata su `tool`        validazione deterministica

M4 — PERCHE' LE FINESTRE SI INDICANO PER TITOLO E NON PER HANDLE
Il piano prevedeva `move_window_to_monitor(window_id: int, ...)`, con
l'handle ottenuto da `list_windows`. E' il modo giusto fra due programmi e
quello sbagliato con un modello linguistico in mezzo, per una ragione sola:
**un handle inventato e' un intero valido**. Se il modello allucina 853420,
quel numero ha buone probabilita' di essere una finestra vera — solo non
quella che l'utente intendeva — e Metis la sposta senza che nulla protesti.
Un titolo inventato, invece, non corrisponde a niente e produce un rifiuto.

Stessa logica per le destinazioni: non un indice di monitor libero, ma un
`Literal` con "destra", "sinistra", "altro". Il modello sceglie fra parole
che esistono, e la traduzione in indice la fa il codice che sa quanti
schermi ci sono davvero.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# Le applicazioni che il modello puo' nominare. Deve coincidere con le chiavi
# di config/apps.toml: `test_allowlist_schema_e_config_coincidono` lo verifica.
# Restano due barriere separate di proposito — qui il modello non puo' dirlo,
# nella guardia il percorso viene comunque verificato.
AppKey = Literal["vscode", "github_desktop", "chrome"]

# Tasti nominabili. Una enumerazione, non una stringa libera: "win" e "delete"
# esistono perche' le combinazioni pericolose vanno RICONOSCIUTE per essere
# rifiutate dalla guardia, non nascoste rendendole innominabili.
KeyName = Literal[
    "ctrl", "alt", "shift", "win", "tab", "enter", "esc", "space",
    "backspace", "delete", "home", "end", "pageup", "pagedown",
    "up", "down", "left", "right",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
]

# Dove mandare una finestra. Le prime tre sono relative a dove si trova
# adesso, le ultime assolute. "altro" esiste perche' con due schermi — il
# caso normale — e' quello che si dice davvero.
MonitorRef = Literal["destra", "sinistra", "altro", "primario", "0", "1", "2", "3"]

# Come disporre una finestra sul suo monitor. Non larghezza e altezza in
# pixel: a voce non si dicono i pixel, e un numero libero sarebbe l'unico
# posto di M4 in cui il modello potrebbe scrivere qualcosa di arbitrario.
Disposizione = Literal[
    "meta_sinistra", "meta_destra", "meta_alto", "meta_basso",
    "due_terzi", "centrata", "piena",
]

# Tipi di elemento che UI Automation sa distinguere. Restringere aiuta la
# ricerca: "il pulsante Salva" e "il link Salva" sono due cose diverse e, se
# il modello lo sa, il risolutore non deve indovinare.
TipoElemento = Literal[
    "qualsiasi", "pulsante", "link", "casella_di_testo", "voce_di_menu",
    "casella_di_spunta", "scheda", "elemento_lista",
]


class _Strumento(BaseModel):
    """Base comune. `extra="forbid"` non e' pignoleria.

    Senza, un modello che inventa un campo — per allucinazione o perche'
    qualcuno gliel'ha suggerito in un testo recuperato dal web — vedrebbe
    quel campo ignorato in silenzio invece che rifiutato. Un campo ignorato
    e' un'ipotesi non verificata su cosa il chiamante credeva di fare.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class _SuFinestra(_Strumento):
    """Strumenti che agiscono su UNA finestra.

    `window` vuoto significa "questa finestra", cioe' quella che era in
    primo piano **quando l'utente ha cominciato a parlare** — non quella di
    adesso. Fra le due cose passano un paio di secondi e un cambio di fuoco,
    e la seconda sarebbe spesso Metis stesso. Il valore viene catturato
    all'ingresso in IN_ASCOLTO: vedi `metis/tools/finestre.py`.

    Il default vuoto e non `None` e' voluto: un campo opzionale nullable
    diventa `anyOf` nello schema JSON, e la grammatica dell'output
    strutturato con `anyOf` e' il posto in cui i modelli piccoli sbagliano
    di piu'. Una stringa vuota e' un valore, e il modello sa produrlo.
    """

    window: str = Field(
        "", max_length=120,
        description="parte del titolo della finestra; vuoto = la finestra "
                    "in primo piano quando l'utente ha parlato",
    )


# --- T0: sola lettura --------------------------------------------------------

class GetTelemetry(_Strumento):
    """T0 — Stato della macchina: VRAM, CPU, RAM."""

    tool: Literal["get_telemetry"]


class ListWindows(_Strumento):
    """T0 — Elenco delle finestre aperte."""

    tool: Literal["list_windows"]


class GetActiveWindow(_Strumento):
    """T0 — Finestra in primo piano. La usano anche le guardie."""

    tool: Literal["get_active_window"]


class ListMonitors(_Strumento):
    """T0 — Monitor collegati, con posizione e scaling."""

    tool: Literal["list_monitors"]


class WebSearch(_Strumento):
    """T0 — Cerca sul web.

    M5 — PERCHE' NON C'E' `max_results`
    Il piano lo prevedeva. E' fuori perche' il numero di fonti e' una
    decisione di budget del contesto — 8k token in tutto, ~1.200 per fonte —
    e non una preferenza dell'utente che il modello debba interpretare. Un
    `max_results=10` sarebbe uno schema valido che espelle la memoria
    conversazionale, cioe' un modo di far dimenticare Metis scrivendo un
    JSON legittimo. Sta come costante in `metis/tools/web.py`.
    """

    tool: Literal["web_search"]
    query: str = Field(..., min_length=2, max_length=200,
                       description="cosa cercare, in parole")


class WebFetch(_Strumento):
    """T0 — Legge una pagina web.

    Solo `https`, come `open_url` e per lo stesso motivo: questo campo e uno
    solo altro sono gli unici di tutto il perimetro che assomiglino a un
    percorso, e senza il `pattern` sarebbero il modo per nominare
    `file:///C:/Users/...` scrivendo un JSON valido.
    """

    tool: Literal["web_fetch"]
    url: str = Field(..., max_length=500,
                     pattern=r"^https://[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}(:\d{1,5})?(/[^\s]*)?$")


# --- T1: reversibile ---------------------------------------------------------

class OpenApplication(_Strumento):
    """T1 — Apre un'applicazione dell'allowlist."""

    tool: Literal["open_application"]
    app: AppKey


class OpenUrl(_Strumento):
    """T1 — Apre un indirizzo web nel browser.

    Il `pattern` non e' una validazione di cortesia: e' cio' che impedisce
    `file:///C:/Users/...`. Senza, questo sarebbe l'unico campo di tutto il
    perimetro capace di nominare un percorso, e l'assenza su cui poggia il
    vincolo principale del progetto smetterebbe di essere un'assenza.
    """

    tool: Literal["open_url"]
    url: str = Field(..., max_length=500,
                     pattern=r"^https?://[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}(:\d{1,5})?(/[^\s]*)?$")


class MoveWindowToMonitor(_SuFinestra):
    """T1 — Sposta una finestra su un altro monitor."""

    tool: Literal["move_window_to_monitor"]
    monitor: MonitorRef


class ResizeWindow(_SuFinestra):
    """T1 — Dispone una finestra sul suo monitor."""

    tool: Literal["resize_window"]
    disposizione: Disposizione


class MaximizeWindow(_SuFinestra):
    """T1 — Massimizza una finestra."""

    tool: Literal["maximize_window"]


class MinimizeWindow(_SuFinestra):
    """T1 — Riduce a icona una finestra."""

    tool: Literal["minimize_window"]


class RestoreWindow(_SuFinestra):
    """T1 — Riporta una finestra alle dimensioni normali."""

    tool: Literal["restore_window"]


class FocusWindow(_SuFinestra):
    """T1 — Porta una finestra in primo piano."""

    tool: Literal["focus_window"]


# --- T2: input sintetico -----------------------------------------------------

class TypeText(_Strumento):
    """T2 — Scrive testo nella finestra in primo piano.

    Il perimetro e' stato definito in M2 insieme alle sue guardie, mentre si
    costruiva il broker; qui in M4 e' arrivata la capacita'. L'ordine conta:
    le guardie sono state scritte e verificate quando l'obiettivo era la
    sicurezza, non quando l'obiettivo era far funzionare l'automazione.
    """

    tool: Literal["type_text"]
    text: str = Field(..., max_length=500)


class PressHotkey(_Strumento):
    """T2 — Preme una combinazione di tasti."""

    tool: Literal["press_hotkey"]
    keys: list[KeyName] = Field(..., min_length=1, max_length=4)


class ClickElement(_Strumento):
    """T2 — Clicca un elemento individuato per NOME, mai per coordinate.

    Non esiste un campo `x` e un campo `y`, ed e' la decisione centrale di
    M4: le coordinate grezze come parametro sarebbero un clic alla cieca in
    un punto che nessuno ha verificato. Qui il modello dice *cosa* vuole
    premere; dove si trovi lo scopre il risolutore guardando l'albero di UI
    Automation o il DOM della pagina. Se non lo trova, si rifiuta.
    """

    tool: Literal["click_element"]
    elemento: str = Field(..., min_length=1, max_length=120)
    tipo: TipoElemento = "qualsiasi"
    doppio: bool = False


class ScrollWindow(_Strumento):
    """T2 — Scorre la finestra in primo piano."""

    tool: Literal["scroll"]
    verso: Literal["su", "giu"]
    quantita: int = Field(3, ge=1, le=10)


class DragElement(_Strumento):
    """T2 — Trascina un elemento su un altro. Entrambi per nome."""

    tool: Literal["drag"]
    da: str = Field(..., min_length=1, max_length=120)
    a: str = Field(..., min_length=1, max_length=120)


# --- T3: effetti esterni, conferma obbligatoria ------------------------------

class SendEmail(_Strumento):
    """T3 — Invia una email. Conferma utente OBBLIGATORIA."""

    tool: Literal["send_email"]
    to: str = Field(..., max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    subject: str = Field(..., max_length=200)
    body: str = Field(..., max_length=5000)


# --- M6: nel tempo -------------------------------------------------------------
#
# LE DATE SONO STRINGHE CON UN PATTERN, NON `datetime`
# Un campo `datetime` di Pydantic accetta una dozzina di formati, fusi orari
# compresi, e diventa `anyOf` nello schema JSON — il punto in cui i modelli
# piccoli sbagliano di piu'. Un formato solo, senza fuso e senza secondi, e'
# un formato che il modello produce sempre uguale. Che la data sia nel futuro
# lo verifica una guardia, non lo schema: e' una questione di quando, non di
# forma.

Quando = Annotated[str, Field(
    pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$",
    description="data e ora locali, formato AAAA-MM-GGTHH:MM, es. 2026-09-24T17:00",
)]


class ScheduleReminder(_Strumento):
    """T1 — Programma un promemoria. Conferma della data SEMPRE."""

    tool: Literal["schedule_reminder"]
    testo: str = Field(..., min_length=1, max_length=200,
                       description="cosa ricordare, in poche parole")
    quando: Quando


class ScheduleEmail(_Strumento):
    """T3 — Programma l'invio di una email. Conferma alla CREAZIONE.

    Non all'invio: chiedere conferma alle 9 di domani presuppone che l'utente
    sia davanti al PC alle 9 di domani, e allora la schedulazione non serve.
    """

    tool: Literal["schedule_email"]
    to: str = Field(..., max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    subject: str = Field(..., max_length=200)
    body: str = Field(..., max_length=5000)
    quando: Quando


class ListReminders(_Strumento):
    """T0 — Elenco dei promemoria e delle email programmate."""

    tool: Literal["list_reminders"]


class CancelReminder(_Strumento):
    """T1 — Cancella un promemoria o un'email programmata.

    Per TESTO, non per id: e' la stessa scelta delle finestre in M4. Un id
    inventato dal modello potrebbe esistere; un pezzo di testo inventato non
    corrisponde a niente e produce un rifiuto. Due corrispondenze, rifiuto.
    """

    tool: Literal["cancel_reminder"]
    riferimento: str = Field(..., min_length=2, max_length=120,
                             description="parte del testo del promemoria o "
                                         "dell'oggetto dell'email")


# --- M6: nel mondo fisico -------------------------------------------------------
#
# IL MODELLO NON NOMINA MAI UN `entity_id`
# Nomina un dispositivo per NOME, fra quelli di `config/home_assistant.toml`.
# Non e' comodita': e' il perimetro. Home Assistant espone anche serrature,
# allarmi, termostati; se il modello potesse scrivere `lock.porta_ingresso`,
# il perimetro di Metis sarebbe quello di Home Assistant. Cosi' e' quello del
# file di configurazione, e un nome che non c'e' e' un rifiuto.

class GetHomeState(_Strumento):
    """T0 — Stato attuale di un dispositivo di casa."""

    tool: Literal["get_home_state"]
    dispositivo: str = Field(..., min_length=2, max_length=60,
                             description="nome del dispositivo, es. friggitrice")


class ListHomeDevices(_Strumento):
    """T0 — Elenco dei dispositivi di casa che Metis puo' usare."""

    tool: Literal["list_home_devices"]


class SetHomeDevice(_Strumento):
    """T3 — Accende o spegne un dispositivo di casa. Conferma SEMPRE."""

    tool: Literal["set_home_device"]
    dispositivo: str = Field(..., min_length=2, max_length=60,
                             description="nome del dispositivo, es. friggitrice")
    azione: Literal["accendi", "spegni"]


# Tutti gli schemi, per chi deve scorrerli: il registro e le verifiche.
SCHEMI: tuple[type[_Strumento], ...] = (
    GetTelemetry,
    ListWindows,
    GetActiveWindow,
    ListMonitors,
    WebSearch,
    WebFetch,
    OpenApplication,
    OpenUrl,
    MoveWindowToMonitor,
    ResizeWindow,
    MaximizeWindow,
    MinimizeWindow,
    RestoreWindow,
    FocusWindow,
    TypeText,
    PressHotkey,
    ClickElement,
    ScrollWindow,
    DragElement,
    SendEmail,
    ScheduleReminder,
    ScheduleEmail,
    ListReminders,
    CancelReminder,
    GetHomeState,
    ListHomeDevices,
    SetHomeDevice,
)

ToolCall = Annotated[Union[SCHEMI], Field(discriminator="tool")]


def nome_strumento(schema: type[BaseModel]) -> str:
    """Il valore di `tool` fissato dal Literal dello schema."""
    annotazione = schema.model_fields["tool"].annotation
    return annotazione.__args__[0]        # Literal["x"] -> "x"
