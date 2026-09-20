"""Push-to-talk: hotkey globale.

Non e' un ripiego in attesa della wake word: resta nella V1.0 in modo
permanente. Serve quando c'e' rumore, quando si e' in chiamata, o quando
semplicemente non si vuole parlare ad alta voce.

Comportamento: TOGGLE, non hold. Una pressione apre l'ascolto, il VAD chiude
da solo a fine frase. Tenere premuto sarebbe scomodo e complicherebbe il
codice senza alcun vantaggio.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from pynput import keyboard

DEFAULT_HOTKEY = "<ctrl>+<alt>+m"
DEFAULT_KILL_SWITCH = "<ctrl>+<alt>+<shift>+m"


class GlobalHotkeys:
    """Hotkey di sistema, attive anche quando Metis non ha il fuoco."""

    def __init__(self) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._listener: keyboard.GlobalHotKeys | None = None
        self._lock = threading.Lock()

    def bind(self, combo: str, callback: Callable[[], None]) -> None:
        if self._listener is not None:
            raise RuntimeError("le hotkey vanno registrate prima di start()")
        self._bindings[combo] = callback

    def start(self) -> None:
        if not self._bindings:
            raise RuntimeError("nessuna hotkey registrata")
        # Il callback di pynput gira sul suo thread: qualunque lavoro pesante
        # va delegato, altrimenti si perdono le pressioni successive.
        self._listener = keyboard.GlobalHotKeys(self._bindings)
        self._listener.start()

    def stop(self) -> None:
        with self._lock:
            if self._listener is not None:
                self._listener.stop()
                self._listener = None

    def __enter__(self) -> "GlobalHotkeys":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


class PushToTalk:
    """Stato di ascolto commutato dall'hotkey.

    In M0 e' l'unico modo di attivare Metis. Da M1 convive con la wake word:
    entrambi emettono lo stesso evento verso la macchina a stati.
    """

    def __init__(self, on_change: Callable[[bool], None] | None = None) -> None:
        self._listening = False
        self._on_change = on_change
        self._lock = threading.Lock()

    @property
    def listening(self) -> bool:
        with self._lock:
            return self._listening

    def toggle(self) -> None:
        with self._lock:
            self._listening = not self._listening
            state = self._listening
        if self._on_change is not None:
            self._on_change(state)

    def set(self, value: bool) -> None:
        with self._lock:
            changed = value != self._listening
            self._listening = value
        if changed and self._on_change is not None:
            self._on_change(value)
