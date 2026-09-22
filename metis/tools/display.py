"""Geometria dei monitor e consapevolezza DPI.

E' il primo file di M4 e va letto per primo, perche' se questo pezzo e'
sbagliato tutto il resto sbaglia nello stesso modo e senza dirlo.

IL PROBLEMA
Windows mente alle applicazioni che non dichiarano di sapere cos'e' il DPI.
A un processo non consapevole racconta un desktop virtualizzato: coordinate
scalate, dimensioni scalate, e un secondo monitor con scaling diverso
descritto come se avesse lo scaling del primo. Il risultato e' che un clic
calcolato su quelle coordinate finisce sistematicamente nel punto sbagliato,
con un errore proporzionale alla differenza di scaling.

Il modo in cui questo difetto si manifesta e' peggio del difetto: sul
monitor primario non succede niente, perche' li' la bugia coincide con la
verita'. Passa ogni prova fatta di fretta.

LA CONTROMISURA, E QUANDO VA APPLICATA
Una riga: dichiararsi `PER_MONITOR_AWARE_V2`. Ma va eseguita **prima che
qualunque cosa tocchi il display** — prima di `QApplication`, prima degli
import di Qt. Il contesto DPI di un processo si fissa al primo uso e poi la
chiamata non ha piu' effetto e non lo dice: ritorna False e basta. Per
questo `metis/gui/app.py` la chiama sulla prima riga di `main()` e c'e' un
test che verifica che nessun import di Qt la preceda.

PERCHE' WIN32 E NON `mss`
Il piano indicava `mss` per la geometria, per aggirare i limiti noti di
`pyautogui` oltre il display primario e con coordinate negative. Quei limiti
restano veri, ma `mss` da' la geometria e **non** il DPI per monitor, che
qui e' il dato che conta: servirebbe comunque `GetDpiForMonitor` da shcore.
Due sorgenti per descrivere gli stessi monitor sono due sorgenti che un
giorno non concordano. Si usa quella che risponde a entrambe le domande.

LE COORDINATE NEGATIVE SONO NORMALI
Il monitor a sinistra del primario ha `left` negativo; quello sopra ha `top`
negativo. Non e' un caso limite esotico ed e' il motivo per cui qui non
compare mai `abs()`, ne' si assume che (0,0) sia l'angolo del desktop.
`origine_desktop()` esiste apposta.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2. E' un handle fittizio, non un
# intero: va passato come puntatore o Windows lo rifiuta in silenzio.
_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

DPI_BASE = 96                 # 96 dpi = 100% di scaling
MDT_EFFECTIVE_DPI = 0


def set_dpi_awareness() -> bool:
    """Dichiara il processo consapevole del DPI per monitor.

    Ritorna True se la dichiarazione e' stata accettata. False significa che
    era gia' stata fissata — da Qt, da un import, dal manifest — e che da qui
    in avanti le coordinate potrebbero essere virtualizzate. Non solleva: su
    una macchina senza shcore (Windows 7) si lavora comunque, solo peggio.
    """
    try:
        return bool(ctypes.windll.user32.SetProcessDpiAwarenessContext(
            _PER_MONITOR_AWARE_V2))
    except Exception:                          # noqa: BLE001
        return False


def dpi_consapevole() -> bool:
    """Verifica a posteriori. Serve alla diagnostica, non alle decisioni."""
    try:
        ctx = ctypes.windll.user32.GetThreadDpiAwarenessContext()
        # AreDpiAwarenessContextsEqual confronta i contesti, che non sono
        # numeri comparabili con ==.
        return bool(ctypes.windll.user32.AreDpiAwarenessContextsEqual(
            ctypes.c_void_p(ctx), _PER_MONITOR_AWARE_V2))
    except Exception:                          # noqa: BLE001
        return False


# --- il modello dei monitor --------------------------------------------------

@dataclass(frozen=True)
class Monitor:
    """Un monitor fisico. Le coordinate sono in pixel del desktop virtuale e
    possono essere negative."""

    indice: int                # 0..n-1, ordinati da sinistra a destra
    nome: str                  # \\.\DISPLAY1
    rect: tuple[int, int, int, int]        # left, top, right, bottom
    lavoro: tuple[int, int, int, int]      # senza barra delle applicazioni
    dpi: int
    primario: bool

    @property
    def larghezza(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def altezza(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def scala(self) -> float:
        """1.0 = 100%, 1.5 = 150%."""
        return self.dpi / DPI_BASE

    def contiene(self, x: int, y: int) -> bool:
        l, t, r, b = self.rect
        return l <= x < r and t <= y < b

    def descrivi(self) -> str:
        l, t, r, b = self.rect
        return (f"{self.indice}: {self.larghezza}x{self.altezza} @ {self.scala:.0%} "
                f"({l},{t}) {'primario' if self.primario else ''}".strip())


def _dpi_di(hmonitor: int) -> int:
    try:
        x = ctypes.c_uint()
        y = ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(
            hmonitor, MDT_EFFECTIVE_DPI, ctypes.byref(x), ctypes.byref(y))
        return int(x.value) or DPI_BASE
    except Exception:                          # noqa: BLE001
        return DPI_BASE


def monitors() -> list[Monitor]:
    """I monitor collegati, ordinati per posizione orizzontale.

    L'ordine e' per `left` crescente e non quello che restituisce Windows,
    che non ha un criterio stabile. Cosi' "il monitor a destra" e' l'indice
    successivo, ed e' l'unica cosa che l'utente puo' dire a voce.
    """
    import win32api

    trovati: list[Monitor] = []
    for handle, _hdc, _rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(handle)
        trovati.append(Monitor(
            indice=-1,
            nome=info["Device"],
            rect=tuple(info["Monitor"]),
            lavoro=tuple(info["Work"]),
            dpi=_dpi_di(int(handle)),
            primario=bool(info["Flags"] & 1),   # MONITORINFOF_PRIMARY
        ))
    trovati.sort(key=lambda m: (m.rect[0], m.rect[1]))
    return [
        Monitor(indice=i, nome=m.nome, rect=m.rect, lavoro=m.lavoro,
                dpi=m.dpi, primario=m.primario)
        for i, m in enumerate(trovati)
    ]


def origine_desktop(elenco: list[Monitor] | None = None) -> tuple[int, int]:
    """L'angolo in alto a sinistra del desktop virtuale. Spesso non e' (0,0)."""
    ms = elenco if elenco is not None else monitors()
    if not ms:
        return (0, 0)
    return (min(m.rect[0] for m in ms), min(m.rect[1] for m in ms))


# --- a quale monitor appartiene una cosa -------------------------------------

def monitor_di_punto(x: int, y: int,
                     elenco: list[Monitor] | None = None) -> Monitor | None:
    ms = elenco if elenco is not None else monitors()
    for m in ms:
        if m.contiene(x, y):
            return m
    return None


def _sovrapposizione(a: tuple[int, int, int, int],
                     b: tuple[int, int, int, int]) -> int:
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0


def monitor_di_rect(rect: tuple[int, int, int, int],
                    elenco: list[Monitor] | None = None) -> Monitor | None:
    """Il monitor su cui la finestra sta **di piu'**.

    Non il monitor dell'angolo in alto a sinistra: una finestra trascinata a
    cavallo di due schermi ha spesso quell'angolo sul monitor su cui non sta.
    Windows stesso decide per area massima, e discordare da lui vorrebbe dire
    calcolare lo scaling con il DPI sbagliato.
    """
    ms = elenco if elenco is not None else monitors()
    migliore, area_migliore = None, 0
    for m in ms:
        area = _sovrapposizione(rect, m.rect)
        if area > area_migliore:
            migliore, area_migliore = m, area
    if migliore is None:
        # Finestra fuori da ogni schermo (succede: minimizzata a -32000).
        return monitor_di_punto(rect[0], rect[1], ms) or (ms[0] if ms else None)
    return migliore


# --- il trasferimento di un rettangolo ---------------------------------------

def rect_trasferito(rect: tuple[int, int, int, int],
                    sorgente: Monitor, destinazione: Monitor,
                    ) -> tuple[int, int, int, int]:
    """Dove va la finestra sull'altro monitor. Funzione pura: e' testabile
    con monitor inventati, ed e' l'unico modo di verificare il caso a DPI
    misti su una macchina che ha due schermi identici.

    DUE REGOLE DIVERSE PER POSIZIONE E DIMENSIONE, ED E' VOLUTO

    La *posizione* si conserva come frazione dell'area di lavoro: una
    finestra al centro resta al centro, una in alto a destra resta in alto a
    destra. E' cio' che l'utente si aspetta e non dipende dal DPI.

    La *dimensione* si scala con il rapporto fra i DPI. Una finestra larga
    1200 pixel su un monitor al 150% occupa 800 pixel logici; sull'altro al
    100% deve restare larga 800, altrimenti il suo contenuto — che Windows
    ridisegna alla nuova scala — le si rimpicciolisce dentro e la finestra
    resta mezza vuota. Quando i due monitor hanno lo stesso DPI il rapporto
    e' 1 e la dimensione non cambia, che e' il comportamento giusto.

    Infine il rettangolo viene contenuto nell'area di lavoro di destinazione:
    una finestra piu' grande dello schermo di arrivo viene rimpicciolita, non
    lasciata a sbordare oltre il bordo dove nessuno puo' prenderla.
    """
    l, t, r, b = rect
    sl, st, sr, sb = sorgente.lavoro
    dl, dt, dr, db = destinazione.lavoro
    sw, sh = max(1, sr - sl), max(1, sb - st)
    dw, dh = max(1, dr - dl), max(1, db - dt)

    k = destinazione.dpi / sorgente.dpi
    nuova_w = max(1, round((r - l) * k))
    nuova_h = max(1, round((b - t) * k))
    # Mai piu' grande dello schermo di arrivo.
    nuova_w = min(nuova_w, dw)
    nuova_h = min(nuova_h, dh)

    fx = (l - sl) / sw
    fy = (t - st) / sh
    nuovo_l = dl + round(fx * dw)
    nuovo_t = dt + round(fy * dh)
    # Contenimento: il bordo destro/inferiore non esce, e l'angolo in alto a
    # sinistra non finisce prima dell'origine dell'area di lavoro.
    nuovo_l = max(dl, min(nuovo_l, dr - nuova_w))
    nuovo_t = max(dt, min(nuovo_t, db - nuova_h))
    return (nuovo_l, nuovo_t, nuovo_l + nuova_w, nuovo_t + nuova_h)


def tabella() -> str:
    """Riga per monitor. La stampano il banco di prova e la diagnostica."""
    ms = monitors()
    righe = [f"DPI per-monitor: {'si' if dpi_consapevole() else 'NO'} · "
             f"origine desktop {origine_desktop(ms)}"]
    for m in ms:
        l, t, r, b = m.rect
        wl, wt, wr, wb = m.lavoro
        righe.append(
            f"  [{m.indice}] {m.nome:<14} {m.larghezza:>5}x{m.altezza:<5} "
            f"dpi {m.dpi:>3} ({m.scala:>5.0%})  rect ({l},{t})-({r},{b})  "
            f"lavoro ({wl},{wt})-({wr},{wb})"
            f"{'  PRIMARIO' if m.primario else ''}"
            f"{'  [coord. negative]' if l < 0 or t < 0 else ''}")
    return "\n".join(righe)
