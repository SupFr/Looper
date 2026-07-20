"""Macro playback control + synthetic input.

Two ways to drive a macro:

  standalone  the macro is a compiled .exe. We run it and kill the process.
              Exact, no hotkeys, no focus games.

  player      the macro is a data file (.rec etc). We launch the player app
              with the file as an argument, then send its play/stop hotkey.
              TinyTask has no CLI verb for "play", so the hotkey is the only
              lever -- which is why it is user-configurable.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from pynput import keyboard, mouse

from . import config

_kb = keyboard.Controller()
_mouse = mouse.Controller()


# Names friends type without brackets that we can map to real keys.
_KEY_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "win": "cmd", "windows": "cmd", "cmd": "cmd",
    "esc": "esc", "escape": "esc",
    "enter": "enter", "return": "enter",
    "space": "space", "spacebar": "space",
    "tab": "tab", "backspace": "backspace", "delete": "delete", "del": "delete",
    "home": "home", "end": "end", "insert": "insert",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "pageup": "page_up", "pagedown": "page_down",
    "capslock": "caps_lock", "numlock": "num_lock",
    **{f"f{i}": f"f{i}" for i in range(1, 25)},
}


def normalize_hotkey(spec: str) -> str:
    """Turn whatever a person typed into canonical '<ctrl>+<shift>+p' form.

    Accepts 'F9', '<f9>', 'ctrl+shift+p', 'CTRL + F6', etc. Raises ValueError
    with a friendly message when a part can't be understood.
    """
    parts_out = []
    for part in spec.split("+"):
        part = part.strip().lower().strip("<>")
        if not part:
            continue
        if part in _KEY_ALIASES:
            parts_out.append(f"<{_KEY_ALIASES[part]}>")
        elif len(part) == 1:
            parts_out.append(part)
        else:
            raise ValueError(
                f"'{part}' isn't a key Looper knows. Use names like F9, "
                "ctrl, shift, alt, space - or single letters.")
    if not parts_out:
        raise ValueError("The hotkey is empty - type a key like F9.")
    return "+".join(parts_out)


def parse_hotkey(spec: str) -> list:
    """'<ctrl>+<shift>+p' (or anything normalize_hotkey accepts) -> pynput keys."""
    keys = []
    for part in normalize_hotkey(spec).split("+"):
        if part.startswith("<") and part.endswith(">"):
            name = part[1:-1]
            key = getattr(keyboard.Key, name, None)
            if key is None:
                raise ValueError(
                    f"'{name}' isn't a key Looper knows. Use names like F9, "
                    "ctrl, shift, alt, space - or single letters.")
            keys.append(key)
        else:
            keys.append(keyboard.KeyCode.from_char(part))
    return keys


def send_hotkey(spec: str) -> None:
    keys = parse_hotkey(spec)
    for k in keys:
        _kb.press(k)
    time.sleep(0.04)
    for k in reversed(keys):
        _kb.release(k)


def click(x: int, y: int, settle: float = 0.06) -> None:
    _mouse.position = (x, y)
    time.sleep(settle)
    _mouse.press(mouse.Button.left)
    time.sleep(0.03)
    _mouse.release(mouse.Button.left)


class MacroPlayer:
    """Owns the playback process/state for one profile."""

    def __init__(self, profile: config.Profile, log) -> None:
        self.p = profile
        self.log = log
        self._proc: subprocess.Popen | None = None
        self._player_proc: subprocess.Popen | None = None
        self._playing = False

    # -- lifecycle ------------------------------------------------------
    def prepare(self) -> None:
        """Open the player app once, up front, so the loop never waits on it."""
        if self.p.mode != config.MODE_PLAYER or not self.p.launch_player:
            return
        player = self.p.player_path.strip()
        if not player:
            self.log("No player app chosen - assuming you already have it open.")
            return
        if not Path(player).is_file():
            raise FileNotFoundError(
                f"Can't find the player app at:\n{player}\n\n"
                "It may have moved. Pick it again in the Playback tab.")

        args = [player]
        macro = self.p.macro_file.strip()
        if macro:
            if not Path(macro).is_file():
                raise FileNotFoundError(
                    f"Can't find your macro recording at:\n{macro}\n\n"
                    "It may have moved or been renamed. Pick it again in "
                    "the Playback tab.")
            args.append(macro)

        self._player_proc = subprocess.Popen(args)
        self.log(f"Launched {Path(player).name}"
                 + (f" with {Path(macro).name}" if macro else ""))
        time.sleep(1.2)   # give it a moment to take the file

    def start_playback(self) -> None:
        if self._playing:
            return
        if self.p.mode == config.MODE_STANDALONE:
            macro = self.p.macro_file.strip()
            if not Path(macro).is_file():
                raise FileNotFoundError(
                    f"Can't find your macro program at:\n{macro}\n\n"
                    "It may have moved or been renamed. Pick it again in "
                    "the Playback tab.")
            self._proc = subprocess.Popen([macro])
            self.log(f"Playback started ({Path(macro).name})")
        else:
            send_hotkey(self.p.play_hotkey)
            self.log(f"Playback started (sent {self.p.play_hotkey})")
        self._playing = True

    def stop_playback(self) -> None:
        if not self._playing:
            return
        if self.p.mode == config.MODE_STANDALONE:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
        else:
            send_hotkey(self.p.stop_hotkey)
        self._playing = False
        self.log("Playback stopped")

    def shutdown(self, close_player: bool = False) -> None:
        try:
            self.stop_playback()
        except Exception:
            pass
        if close_player and self._player_proc and self._player_proc.poll() is None:
            self._player_proc.terminate()

    @property
    def playing(self) -> bool:
        return self._playing
