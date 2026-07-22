"""First-run setup guide.

A live checklist, not a tour: each row is the real action, state is computed
from the profile every time it changes, and the panel retires itself once the
user has farmed a first cycle. No stale "seen" flags for setup state -- only
the final dismissal is persisted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget,
)

from . import config

_STATE_FILE = config.APP_DIR / "onboarding.json"


def _state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(**updates) -> None:
    try:
        config.APP_DIR.mkdir(parents=True, exist_ok=True)
        data = _state()
        data.update(updates)
        _STATE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def first_cycle_done() -> bool:
    return _state().get("first_cycle", False)


def mark_first_cycle() -> None:
    _write(first_cycle=True)


def guide_dismissed() -> bool:
    return _state().get("dismissed", False)


def dismiss_guide() -> None:
    _write(dismissed=True)


def tinker_open() -> bool:
    """Whether the advanced panels (steps editor, tabs, log) are shown."""
    return _state().get("tinker", False)


def set_tinker(open_: bool) -> None:
    _write(tinker=open_)


def always_on_top() -> bool:
    return _state().get("always_on_top", False)


def set_always_on_top(on: bool) -> None:
    _write(always_on_top=on)


@dataclass
class _Row:
    frame: QFrame
    dot: QLabel
    title: QLabel
    desc: QLabel
    button: QPushButton


class SetupChecklist(QFrame):
    """Three rows to first value: capture Retry -> pick macro -> press start.

    Emits the same actions the main window already implements; it never owns
    logic, it only routes the user to the next real control.
    """

    capture_requested = Signal()
    macro_requested = Signal()
    start_requested = Signal()
    dismissed = Signal()

    _TITLES = (
        ("Show me the Retry button",
         "Click Capture, then drag a box around the game's Retry button "
         "on the end screen. That's how Looper knows a match ended."),
        ("Pick your recorded macro",
         "The TinyTask recording (or macro .exe) that plays one match."),
        ("Start a match and press {start}",
         "Get into a match in the game, then hit {start}. Looper "
         "replays your macro and restarts every match for you."),
    )
    _ACTIONS = ("Capture", "Browse", "Start")

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("setupGuide")
        self._rows: list[_Row] = []
        self._start_key = "F9"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("Set up in 3 steps")
        title.setObjectName("guideTitle")
        head.addWidget(title)
        self.progress = QLabel("")
        self.progress.setObjectName("guideProgress")
        head.addWidget(self.progress)
        head.addStretch(1)
        self.btn_hide = QPushButton("Hide guide")
        self.btn_hide.setObjectName("guideHide")
        self.btn_hide.setCursor(Qt.PointingHandCursor)
        self.btn_hide.clicked.connect(self.dismissed.emit)
        self.btn_hide.hide()   # only offered once everything is done
        head.addWidget(self.btn_hide)
        lay.addLayout(head)

        signals = (self.capture_requested, self.macro_requested,
                   self.start_requested)
        for i, ((t, d), action, sig) in enumerate(
                zip(self._TITLES, self._ACTIONS, signals)):
            lay.addWidget(self._build_row(i, t, d, action, sig))

    # ------------------------------------------------------------------
    def _build_row(self, idx: int, title: str, desc: str, action: str,
                   signal: Signal) -> QFrame:
        frame = QFrame()
        frame.setObjectName("guideRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(12)

        dot = QLabel(str(idx + 1))
        dot.setObjectName("guideDot")
        dot.setFixedSize(26, 26)
        dot.setAlignment(Qt.AlignCenter)
        row.addWidget(dot, 0, Qt.AlignTop)

        text = QWidget()
        tv = QVBoxLayout(text)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(1)
        lbl_title = QLabel(title)
        lbl_title.setObjectName("guideRowTitle")
        lbl_desc = QLabel(desc)
        lbl_desc.setObjectName("guideRowDesc")
        lbl_desc.setWordWrap(True)
        tv.addWidget(lbl_title)
        tv.addWidget(lbl_desc)
        row.addWidget(text, 1)

        btn = QPushButton(action)
        btn.setObjectName("guideAction")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(signal.emit)
        row.addWidget(btn, 0, Qt.AlignVCenter)

        self._rows.append(_Row(frame, dot, lbl_title, lbl_desc, btn))
        return frame

    # ------------------------------------------------------------------
    def refresh(self, profile: config.Profile, running: bool,
                start_key: str) -> None:
        """Recompute every row from real state. Called on any change."""
        self._start_key = start_key.strip("<>").upper() or "F9"

        step1 = profile.steps[0] if profile.steps else None
        done = [
            bool(step1 and step1.template and step1.has_region),
            bool(profile.macro_file.strip()),
            running or first_cycle_done(),
        ]
        current = next((i for i, d in enumerate(done) if not d), None)

        # keep the hotkey in the third row's copy honest
        t, d = self._TITLES[2]
        self._rows[2].title.setText(t.format(start=self._start_key))
        self._rows[2].desc.setText(d.format(start=self._start_key))

        for i, (row, is_done) in enumerate(zip(self._rows, done)):
            state = "done" if is_done else ("current" if i == current else "todo")
            row.frame.setProperty("state", state)
            row.dot.setProperty("state", state)
            row.dot.setText("✓" if is_done else str(i + 1))
            row.button.setVisible(state == "current")
            # re-polish so the QSS property selectors take effect
            for w in (row.frame, row.dot):
                w.style().unpolish(w)
                w.style().polish(w)

        n = sum(done)
        self.progress.setText(f"·  {n} of 3 done")
        self.btn_hide.setVisible(n == 3)

    def first_unfinished(self) -> int | None:
        for i, row in enumerate(self._rows):
            if row.frame.property("state") != "done":
                return i
        return None
