"""Global hotkeys (work while the game has focus).

pynput's GlobalHotKeys runs its own listener thread; callbacks are marshalled
onto the Qt main thread via signals.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from pynput import keyboard

from .player import normalize_hotkey


class HotkeyManager(QObject):
    sig_start = Signal()
    sig_stop = Signal()
    sig_panic = Signal()

    _NAMES = ("start", "stop", "panic")

    def __init__(self) -> None:
        super().__init__()
        self._listener: keyboard.GlobalHotKeys | None = None

    def rebind(self, start: str, stop: str, panic: str) -> str | None:
        """Returns a friendly error message, or None on success."""
        self.unbind()
        mapping: dict[str, callable] = {}
        signals = (self.sig_start.emit, self.sig_stop.emit, self.sig_panic.emit)
        for name, spec, emit in zip(self._NAMES, (start, stop, panic), signals):
            spec = spec.strip()
            if not spec:
                continue
            try:
                canonical = normalize_hotkey(spec)
            except ValueError as e:
                return f"The {name} hotkey doesn't work: {e}"
            if canonical in mapping:
                return (f"The {name} hotkey is the same key as another one - "
                        "give each action its own key.")
            mapping[canonical] = emit
        if not mapping:
            return None
        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
            return None
        except Exception as e:
            self._listener = None
            return f"Couldn't set up the hotkeys: {e}"

    def unbind(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
