"""Global hotkeys (work while the game has focus).

pynput's GlobalHotKeys runs its own listener thread; callbacks are marshalled
onto the Qt main thread via signals.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from pynput import keyboard


class HotkeyManager(QObject):
    sig_start = Signal()
    sig_stop = Signal()
    sig_panic = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._listener: keyboard.GlobalHotKeys | None = None

    def rebind(self, start: str, stop: str, panic: str) -> str | None:
        """Returns an error message, or None on success."""
        self.unbind()
        mapping: dict[str, callable] = {}
        try:
            if start.strip():
                mapping[start.strip()] = self.sig_start.emit
            if stop.strip() and stop.strip() not in mapping:
                mapping[stop.strip()] = self.sig_stop.emit
            if panic.strip() and panic.strip() not in mapping:
                mapping[panic.strip()] = self.sig_panic.emit
            if not mapping:
                return None
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
            return None
        except Exception as e:  # bad spec string
            self._listener = None
            return str(e)

    def unbind(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
