"""Profile model + JSON persistence.

A profile is one game setup: the macro to play back, how to drive the player
app, and the ordered list of image steps that walk the end screen back into a
fresh match.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Looper"
PROFILE_DIR = APP_DIR / "profiles"
ASSET_DIR = APP_DIR / "assets"

# What to do when a step's image never shows up inside its timeout.
ON_TIMEOUT_RESTART = "restart"    # bail to step 1 and keep watching
ON_TIMEOUT_SKIP = "skip"          # pretend it matched, move on
ON_TIMEOUT_STOP = "stop"          # kill the loop, notify

# How the macro playback is driven.
MODE_STANDALONE = "standalone"    # macro is a compiled .exe -> run/kill process
MODE_PLAYER = "player"            # macro is a file -> launch player, send hotkeys


def _ensure_dirs() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Step:
    """One image the supervisor waits for, and what it does when it appears."""

    name: str = "New step"
    template: str = ""                       # abs path to the captured .png
    region: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # physical px
    threshold: float = 0.85
    click: bool = True
    click_offset: list[int] = field(default_factory=lambda: [0, 0])
    post_delay: float = 1.5                  # seconds to wait after acting
    timeout: float = 60.0                    # 0 = wait forever
    on_timeout: str = ON_TIMEOUT_RESTART
    enabled: bool = True

    @property
    def region_dict(self) -> dict[str, int]:
        x, y, w, h = self.region
        return {"left": x, "top": y, "width": w, "height": h}

    @property
    def has_region(self) -> bool:
        return self.region[2] > 0 and self.region[3] > 0


@dataclass
class Profile:
    """Everything needed to run one game's loop."""

    name: str = "Untitled"
    steps: list[Step] = field(default_factory=list)

    # --- macro playback -----------------------------------------------
    mode: str = MODE_PLAYER
    macro_file: str = ""
    player_path: str = ""
    play_hotkey: str = "<ctrl>+<shift>+<alt>+p"   # TinyTask default
    stop_hotkey: str = "<ctrl>+<shift>+<alt>+p"   # TinyTask toggles on the same key
    launch_player: bool = True
    pre_playback_delay: float = 3.0   # let the map load before playback fires
    stop_before_steps: bool = True    # kill playback the instant step 1 matches

    # --- detection ----------------------------------------------------
    poll_interval: float = 0.4
    grayscale: bool = True

    # --- global hotkeys -----------------------------------------------
    hk_start: str = "<f9>"
    hk_stop: str = "<f10>"
    hk_panic: str = "<f12>"

    # --- webhook ------------------------------------------------------
    webhook_url: str = ""
    webhook_enabled: bool = False
    webhook_on_cycle: bool = True
    webhook_every: int = 1            # only ping every Nth cycle
    webhook_on_start: bool = True
    webhook_on_stop: bool = True
    webhook_on_error: bool = True

    # ------------------------------------------------------------------
    @property
    def path(self) -> Path:
        return PROFILE_DIR / f"{self.name}.json"

    def to_json(self) -> dict:
        d = asdict(self)
        d["steps"] = [asdict(s) for s in self.steps]
        return d

    @classmethod
    def from_json(cls, data: dict) -> "Profile":
        steps = [Step(**s) for s in data.pop("steps", [])]
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        p = cls(**clean)
        p.steps = steps
        return p

    def save(self) -> Path:
        _ensure_dirs()
        self.path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")
        return self.path

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_json(data)

    @staticmethod
    def list_all() -> list[Path]:
        _ensure_dirs()
        return sorted(PROFILE_DIR.glob("*.json"))


def new_asset_path() -> Path:
    """Unique .png path for a freshly captured template."""
    _ensure_dirs()
    return ASSET_DIR / f"tpl_{uuid.uuid4().hex[:12]}.png"
