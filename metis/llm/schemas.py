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
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# Le applicazioni che il modello puo' nominare. Deve coincidere con le chiavi
# di config/apps.toml: `test_allowlist_schema_e_config_coincidono` lo verifica.
# Restano due barriere separate di proposito — qui il modello non puo' dirlo,
# nella guardia il percorso viene comunque verificato.
AppKey = Literal["vscode", "github_desktop"]

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


class _Strumento(BaseModel):
    """Base comune. `extra="forbid"` non e' pignoleria.

    Senza, un modello che inventa un campo — per allucinazione o perche'
    qualcuno gliel'ha suggerito in un testo recuperato dal web — vedrebbe
    quel campo ignorato in silenzio invece che rifiutato. Un campo ignorato
    e' un'ipotesi non verificata su cosa il chiamante credeva di fare.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


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


# --- T1: reversibile ---------------------------------------------------------

class OpenApplication(_Strumento):
    """T1 — Apre un'applicazione dell'allowlist."""

    tool: Literal["open_application"]
    app: AppKey


class MoveWindowToMonitor(_Strumento):
    """T1 — Sposta una finestra su un altro monitor."""

    tool: Literal["move_window_to_monitor"]
    window_id: int = Field(..., ge=0)
    monitor: int = Field(..., ge=0, le=3)


# --- T2: input sintetico (perimetro definito qui, capacita' in M4) -----------

class TypeText(_Strumento):
    """T2 — Scrive testo nella finestra in primo piano.

    Il perimetro si definisce in M2 anche se la capacita' arriva in M4: le
    guardie che lo governano sono logica di sicurezza e vanno scritte e
    verificate mentre il broker viene costruito, non accanto allo strumento
    che dovrebbero contenere.
    """

    tool: Literal["type_text"]
    text: str = Field(..., max_length=500)


class PressHotkey(_Strumento):
    """T2 — Preme una combinazione di tasti."""

    tool: Literal["press_hotkey"]
    keys: list[KeyName] = Field(..., min_length=1, max_length=4)


# --- T3: effetti esterni, conferma obbligatoria ------------------------------

class SendEmail(_Strumento):
    """T3 — Invia una email. Conferma utente OBBLIGATORIA."""

    tool: Literal["send_email"]
    to: str = Field(..., max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    subject: str = Field(..., max_length=200)
    body: str = Field(..., max_length=5000)


ToolCall = Annotated[
    Union[
        GetTelemetry,
        ListWindows,
        GetActiveWindow,
        OpenApplication,
        MoveWindowToMonitor,
        TypeText,
        PressHotkey,
        SendEmail,
    ],
    Field(discriminator="tool"),
]

# Tutti gli schemi, per chi deve scorrerli: il registro e le verifiche.
SCHEMI: tuple[type[_Strumento], ...] = (
    GetTelemetry,
    ListWindows,
    GetActiveWindow,
    OpenApplication,
    MoveWindowToMonitor,
    TypeText,
    PressHotkey,
    SendEmail,
)


def nome_strumento(schema: type[BaseModel]) -> str:
    """Il valore di `tool` fissato dal Literal dello schema."""
    annotazione = schema.model_fields["tool"].annotation
    return annotazione.__args__[0]        # Literal["x"] -> "x"
