"""Eventi di tastiera e mouse veri, via `SendInput`. Il livello piu' basso.

QUESTO FILE NON E' RAGGIUNGIBILE DAL MODELLO
Non contiene nessuno strumento registrato. Gli unici a chiamarlo sono gli
handler T2 di `input_sintetico.py`, che stanno dietro la guardia della
finestra e dietro la rivalutazione immediata del broker. E' voluto che il
pezzo che preme i tasti sia una libreria muta: qui non si decide niente.

PERCHE' `SendInput` E NON `pyautogui`
Il piano prevedeva `pyautogui` "solo per l'evento". Due ragioni per scendere
di un livello, entrambe concrete:

**Gli accenti.** `pyautogui.typewrite` passa per i codici virtuali della
tastiera, che dipendono dal layout: "perche'" si scrive, "perché" no, e in
italiano quella non e' una raffinatezza. `KEYEVENTF_UNICODE` invia il
carattere e basta, qualunque layout ci sia.

**Le coordinate.** `pyautogui` ha limiti noti oltre il monitor primario e
con coordinate negative, che e' precisamente il caso di un desktop a due
schermi. Qui la normalizzazione e' fatta sul **desktop virtuale**
(`MOUSEEVENTF_VIRTUALDESK`), che e' l'unico sistema di riferimento in cui il
monitor a sinistra del primario esiste.

In cambio si perde il FAILSAFE di pyautogui — il mouse nell'angolo che
interrompe tutto. Il suo posto e' preso dal kill switch, che sospende T2 e
T3 da qualunque stato e non richiede di indovinare un angolo.

LA PAUSA FRA GLI EVENTI
`SendInput` consegna gli eventi in coda senza attendere che l'applicazione
li elabori. Senza una pausa, una combinazione puo' arrivare con i tasti
ancora premuti dal gesto precedente, e un clic puo' precedere lo spostamento
del puntatore. Sono millisecondi, ma sono la differenza fra "funziona" e
"funziona quasi sempre".
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

PAUSA_S = 0.012              # fra un evento e il successivo
PAUSA_CLIC_S = 0.12          # fra l'ultimo spostamento e la pressione
PAUSA_ASSESTAMENTO_S = 0.08  # fra i due spostamenti: vedi `clic`

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

WHEEL_DELTA = 120

# Dai nomi del `Literal` KeyName ai codici virtuali. Le lettere e le cifre
# non sono qui: per quelle il codice coincide con l'ASCII maiuscolo.
VK = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
VK.update({f"f{n}": 0x6F + n for n in range(1, 13)})        # F1 = 0x70


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _UNIONE(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _UNIONE)]


def _invia(*eventi: _INPUT) -> int:
    n = len(eventi)
    array = (_INPUT * n)(*eventi)
    return int(ctypes.windll.user32.SendInput(n, array, ctypes.sizeof(_INPUT)))


def _tasto(vk: int, su: bool) -> _INPUT:
    e = _INPUT(type=INPUT_KEYBOARD)
    e.ki = _KEYBDINPUT(wVk=vk, wScan=0,
                       dwFlags=KEYEVENTF_KEYUP if su else 0,
                       time=0, dwExtraInfo=None)
    return e


def _carattere(cp: int, su: bool) -> _INPUT:
    e = _INPUT(type=INPUT_KEYBOARD)
    e.ki = _KEYBDINPUT(wVk=0, wScan=cp,
                       dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if su else 0),
                       time=0, dwExtraInfo=None)
    return e


def _mouse(dx: int, dy: int, flags: int, dati: int = 0) -> _INPUT:
    e = _INPUT(type=INPUT_MOUSE)
    e.mi = _MOUSEINPUT(dx=dx, dy=dy, mouseData=dati, dwFlags=flags,
                       time=0, dwExtraInfo=None)
    return e


# --- tastiera ----------------------------------------------------------------

def scrivi(testo: str) -> int:
    """Digita testo carattere per carattere. Ritorna quanti ne ha inviati.

    I caratteri fuori dal Piano Multilingue di Base (emoji) si inviano come
    coppia surrogata: sono due eventi, e Windows li ricompone. Senza questo,
    `ord(c) > 0xFFFF` non entrerebbe in un `WORD` e il carattere uscirebbe
    troncato in qualcosa di diverso.
    """
    inviati = 0
    for c in testo:
        cp = ord(c)
        unita = ([cp] if cp <= 0xFFFF else
                 [0xD800 + ((cp - 0x10000) >> 10), 0xDC00 + ((cp - 0x10000) & 0x3FF)])
        for u in unita:
            _invia(_carattere(u, False), _carattere(u, True))
            inviati += 1
        time.sleep(PAUSA_S)
    return inviati


def _vk_di(nome: str) -> int:
    if nome in VK:
        return VK[nome]
    if len(nome) == 1 and (nome.isalpha() or nome.isdigit()):
        return ord(nome.upper())
    raise KeyError(f"tasto non mappato: {nome}")


def combinazione(tasti: list[str]) -> None:
    """Premi in ordine, rilasci in ordine inverso.

    L'ordine inverso non e' estetica: rilasciare prima il modificatore
    lascerebbe l'ultimo tasto premuto da solo, e "Ctrl+S" diventerebbe
    "Ctrl+S" seguito da una "s" nel documento.
    """
    codici = [_vk_di(t) for t in tasti]
    for vk in codici:
        _invia(_tasto(vk, False))
        time.sleep(PAUSA_S)
    for vk in reversed(codici):
        _invia(_tasto(vk, True))
        time.sleep(PAUSA_S)


# --- mouse -------------------------------------------------------------------

def _normalizza(x: int, y: int) -> tuple[int, int]:
    """Da pixel del desktop virtuale a 0..65535, che e' cio' che vuole
    `MOUSEEVENTF_ABSOLUTE`.

    L'origine non e' (0,0): con un monitor a sinistra del primario e'
    negativa, ed e' esattamente il caso in cui le librerie che assumono
    (0,0) mandano il puntatore fuori schermo. Qui si sottrae l'origine vera,
    letta da Windows.
    """
    gsm = ctypes.windll.user32.GetSystemMetrics
    ox, oy = gsm(SM_XVIRTUALSCREEN), gsm(SM_YVIRTUALSCREEN)
    w, h = max(1, gsm(SM_CXVIRTUALSCREEN)), max(1, gsm(SM_CYVIRTUALSCREEN))
    nx = round((x - ox) * 65535 / max(1, w - 1))
    ny = round((y - oy) * 65535 / max(1, h - 1))
    return (max(0, min(65535, nx)), max(0, min(65535, ny)))


def muovi(x: int, y: int) -> None:
    nx, ny = _normalizza(x, y)
    _invia(_mouse(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                  | MOUSEEVENTF_VIRTUALDESK))


def clic(x: int, y: int, doppio: bool = False) -> None:
    """Due spostamenti prima di premere, e il secondo non e' ridondante.

    MISURATO, NON SUPPOSTO. Con un solo spostamento, il primo clic dopo che
    una finestra e' passata in primo piano si perde una volta su quattro:
    su otto tentativi, Chrome riceveva tutti e otto i `mousedown` e ne
    trasformava in clic sul link solo sei. Con la finestra gia' davanti,
    otto su otto. Aggiungendo un secondo spostamento e una pausa, otto su
    otto anche dopo l'attivazione.

    La spiegazione e' che dopo un cambio di fuoco il bersaglio non ha
    ancora aggiornato il proprio hit-testing sulla posizione del
    puntatore: il tasto arriva, ma non sa su cosa. Il secondo spostamento
    deve essere in un pixel DIVERSO, altrimenti Windows lo assorbe come
    ridondante e non genera l'evento che serve a svegliare il bersaglio.

    Costa 200 ms per clic. La ritentativa automatica costerebbe di meno e
    sarebbe molto peggio: un clic ripetuto su un pulsante che ha gia'
    funzionato e' un'azione doppia, e su "Invia" e' un'azione doppia che si
    vede.
    """
    muovi(x, max(0, y - 1) if y > 0 else y + 1)
    time.sleep(PAUSA_ASSESTAMENTO_S)
    muovi(x, y)
    time.sleep(PAUSA_CLIC_S)
    for _ in range(2 if doppio else 1):
        _invia(_mouse(0, 0, MOUSEEVENTF_LEFTDOWN),
               _mouse(0, 0, MOUSEEVENTF_LEFTUP))
        time.sleep(PAUSA_S)


def scorri(tacche: int) -> None:
    """Positivo = verso l'alto, come la rotellina."""
    _invia(_mouse(0, 0, MOUSEEVENTF_WHEEL, dati=tacche * WHEEL_DELTA & 0xFFFFFFFF))


def trascina(x1: int, y1: int, x2: int, y2: int, passi: int = 12) -> None:
    """Premi, muovi a tappe, rilascia.

    I passi intermedi servono: molte applicazioni iniziano un trascinamento
    solo dopo aver visto il puntatore muoversi con il tasto gia' premuto. Un
    salto unico dal punto di partenza a quello di arrivo viene letto come un
    clic e basta.
    """
    muovi(x1, y1)
    time.sleep(PAUSA_CLIC_S)
    _invia(_mouse(0, 0, MOUSEEVENTF_LEFTDOWN))
    for i in range(1, passi + 1):
        muovi(round(x1 + (x2 - x1) * i / passi),
              round(y1 + (y2 - y1) * i / passi))
        time.sleep(PAUSA_S)
    time.sleep(PAUSA_CLIC_S)
    _invia(_mouse(0, 0, MOUSEEVENTF_LEFTUP))
