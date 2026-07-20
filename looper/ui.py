"""Main window."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPixmap, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QDoubleSpinBox,
    QSpinBox, QListWidget, QListWidgetItem, QPlainTextEdit, QTabWidget,
    QFileDialog, QMessageBox, QInputDialog, QSplitter,
)

import re

from . import config, engine, hotkeys, matcher, onboarding, overlay, player, webhook
from .config import Profile, Step


def _panel() -> QFrame:
    f = QFrame()
    f.setObjectName("panel")
    return f


def _bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    h, w = bgr.shape[:2]
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Looper v1.3")
        self.resize(1060, 700)

        self.profile = Profile(name="Default")
        self.hook = webhook.Webhook()
        self.engine: engine.LoopEngine | None = None
        self.hk = hotkeys.HotkeyManager()
        self._picker: overlay.RegionPicker | None = None
        self._loading = 0   # re-entrant depth counter, not a bool: nested
                            # UI-fill routines must not unguard their parent

        with self._filling_ui():   # widget construction fires change signals
            self._build()
        self._load_initial_profile()
        self._bind_hotkeys()

        self.hk.sig_start.connect(self.start_loop)
        self.hk.sig_stop.connect(self.stop_loop)
        self.hk.sig_panic.connect(self.panic)

    # ==================================================================
    # UI construction
    # ==================================================================
    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        outer.addWidget(self._build_header())

        self.guide = onboarding.SetupChecklist()
        self.guide.capture_requested.connect(self._guide_capture)
        self.guide.macro_requested.connect(self._guide_macro)
        self.guide.start_requested.connect(self.start_loop)
        self.guide.dismissed.connect(self._guide_dismiss)
        self.guide.setVisible(not onboarding.guide_dismissed())
        outer.addWidget(self.guide)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_steps_panel())
        split.addWidget(self._build_settings_panel())
        split.setSizes([560, 480])
        outer.addWidget(split, 1)

        self.log_view = QPlainTextEdit(readOnly=True, maximumBlockCount=500)
        self.log_view.setFixedHeight(130)
        self.log_view.setPlaceholderText(
            "Activity shows up here once the loop is running - every match "
            "detected, every restart, every click.")
        outer.addWidget(self.log_view)

    def _build_header(self) -> QFrame:
        panel = _panel()
        lay = QHBoxLayout(panel)
        lay.setContentsMargins(14, 10, 14, 10)

        title = QLabel("Looper")
        title.setObjectName("h1")
        lay.addWidget(title)

        lay.addSpacing(16)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.currentTextChanged.connect(self._on_profile_switch)
        lay.addWidget(self.profile_combo)

        self._profile_buttons = []
        for text, slot in (("New", self._new_profile), ("Save", self._save_profile),
                           ("Delete", self._delete_profile)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            self._profile_buttons.append(b)
            lay.addWidget(b)

        lay.addStretch(1)

        self.state_label = QLabel("Not running")
        self.state_label.setObjectName("stateLabel")
        lay.addWidget(self.state_label)

        lay.addSpacing(14)
        lay.addWidget(QLabel("Matches done"))
        self.cycle_label = QLabel("0")
        self.cycle_label.setObjectName("cycleLabel")
        lay.addWidget(self.cycle_label)

        lay.addSpacing(14)
        self.btn_start = QPushButton("Start  (F9)")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.start_loop)
        self.btn_stop = QPushButton("Stop  (F10)")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_loop)
        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        return panel

    # ---------------- steps panel ----------------
    def _build_steps_panel(self) -> QFrame:
        panel = _panel()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)

        head = QHBoxLayout()
        lbl = QLabel("WHAT LOOPER WATCHES FOR")
        lbl.setObjectName("h2")
        head.addWidget(lbl)
        head.addStretch(1)
        for text, slot in (("+ Add", self._add_step), ("Remove", self._remove_step),
                           ("Up", lambda: self._move_step(-1)),
                           ("Down", lambda: self._move_step(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            head.addWidget(b)
        lay.addLayout(head)

        hint = QLabel("Step 1 is the end screen - when Looper sees it, the "
                      "macro stops. Any steps after that click through the "
                      "menus back into a match.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.step_list = QListWidget()
        self.step_list.currentRowChanged.connect(self._on_step_selected)
        lay.addWidget(self.step_list, 1)

        # -- editor --
        ed = QGridLayout()
        ed.setVerticalSpacing(6)
        r = 0

        ed.addWidget(QLabel("Name"), r, 0)
        self.ed_name = QLineEdit()
        self.ed_name.editingFinished.connect(self._apply_editor)
        ed.addWidget(self.ed_name, r, 1, 1, 2)

        self.thumb = QLabel("nothing captured\nyet")
        self.thumb.setFixedSize(QSize(150, 84))
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet(
            "border: 1px dashed #30363d; border-radius: 6px; color: #545d68;")
        ed.addWidget(self.thumb, r, 3, 3, 1)
        r += 1

        self.btn_capture = QPushButton("Capture from screen")
        self.btn_capture.clicked.connect(self._capture_region)
        ed.addWidget(self.btn_capture, r, 0, 1, 3)
        r += 1

        ed.addWidget(QLabel("Match strictness"), r, 0)
        self.ed_threshold = QDoubleSpinBox(minimum=0.5, maximum=1.0,
                                           singleStep=0.01, decimals=2)
        self.ed_threshold.setToolTip(
            "How closely the screen has to match your captured image "
            "before it counts. Lower it a little if Looper keeps missing it.")
        self.ed_threshold.valueChanged.connect(self._apply_editor)
        ed.addWidget(self.ed_threshold, r, 1)
        self.ed_click = QCheckBox("Click when detected")
        self.ed_click.stateChanged.connect(self._apply_editor)
        ed.addWidget(self.ed_click, r, 2)
        r += 1

        ed.addWidget(QLabel("Wait after (seconds)"), r, 0)
        self.ed_post = QDoubleSpinBox(minimum=0.0, maximum=120.0, singleStep=0.5)
        self.ed_post.setToolTip("Pause after this step before moving on - "
                                "gives menus time to open.")
        self.ed_post.valueChanged.connect(self._apply_editor)
        ed.addWidget(self.ed_post, r, 1)
        ed.addWidget(QLabel("Give up after (seconds, 0 = never)"), r, 2)
        self.ed_timeout = QDoubleSpinBox(minimum=0.0, maximum=3600.0, singleStep=5.0)
        self.ed_timeout.valueChanged.connect(self._apply_editor)
        ed.addWidget(self.ed_timeout, r, 3)
        r += 1

        ed.addWidget(QLabel("If it never shows"), r, 0)
        self.ed_on_timeout = QComboBox()
        self.ed_on_timeout.addItem("start the cycle over", config.ON_TIMEOUT_RESTART)
        self.ed_on_timeout.addItem("skip this step", config.ON_TIMEOUT_SKIP)
        self.ed_on_timeout.addItem("stop and tell me", config.ON_TIMEOUT_STOP)
        self.ed_on_timeout.currentIndexChanged.connect(self._apply_editor)
        ed.addWidget(self.ed_on_timeout, r, 1)
        self.ed_enabled = QCheckBox("Enabled")
        self.ed_enabled.stateChanged.connect(self._apply_editor)
        ed.addWidget(self.ed_enabled, r, 2)

        lay.addLayout(ed)
        return panel

    # ---------------- settings panel ----------------
    def _build_settings_panel(self) -> QFrame:
        panel = _panel()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 8, 14, 12)

        tabs = QTabWidget()
        tabs.addTab(self._tab_playback(), "Playback")
        tabs.addTab(self._tab_hotkeys(), "Hotkeys")
        tabs.addTab(self._tab_webhook(), "Webhook")
        lay.addWidget(tabs)
        return panel

    def _tab_playback(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setVerticalSpacing(8)
        r = 0

        g.addWidget(QLabel("How your macro runs"), r, 0)
        self.pb_mode = QComboBox()
        self.pb_mode.addItem("A player app opens it (TinyTask)", config.MODE_PLAYER)
        self.pb_mode.addItem("It's a program that runs by itself (.exe)",
                             config.MODE_STANDALONE)
        self.pb_mode.currentIndexChanged.connect(self._apply_settings)
        g.addWidget(self.pb_mode, r, 1, 1, 2)
        r += 1

        g.addWidget(QLabel("Macro recording"), r, 0)
        self.pb_macro = QLineEdit()
        self.pb_macro.editingFinished.connect(self._apply_settings)
        g.addWidget(self.pb_macro, r, 1)
        b = QPushButton("Browse")
        b.setFixedWidth(64)
        b.clicked.connect(lambda: self._browse(self.pb_macro, "Macro file"))
        g.addWidget(b, r, 2)
        r += 1

        g.addWidget(QLabel("Player app"), r, 0)
        self.pb_player = QLineEdit()
        self.pb_player.setPlaceholderText("e.g. C:\\Tools\\tinytask.exe")
        self.pb_player.editingFinished.connect(self._apply_settings)
        g.addWidget(self.pb_player, r, 1)
        b = QPushButton("Browse")
        b.setFixedWidth(64)
        b.clicked.connect(lambda: self._browse(self.pb_player, "Player app",
                                               "Programs (*.exe)"))
        g.addWidget(b, r, 2)
        r += 1

        self.pb_launch = QCheckBox("Open the player app for me when the loop starts")
        self.pb_launch.stateChanged.connect(self._apply_settings)
        g.addWidget(self.pb_launch, r, 0, 1, 3)
        r += 1

        g.addWidget(QLabel("Play hotkey"), r, 0)
        self.pb_play_hk = QLineEdit()
        self.pb_play_hk.editingFinished.connect(self._apply_settings)
        g.addWidget(self.pb_play_hk, r, 1, 1, 2)
        r += 1

        g.addWidget(QLabel("Stop hotkey"), r, 0)
        self.pb_stop_hk = QLineEdit()
        self.pb_stop_hk.editingFinished.connect(self._apply_settings)
        g.addWidget(self.pb_stop_hk, r, 1, 1, 2)
        r += 1

        hint = QLabel("These are the player app's own shortcuts - Looper "
                      "presses them for you. TinyTask uses the same key for "
                      "play and stop (default <ctrl>+<shift>+<alt>+p). "
                      "Write keys like <f6> or <ctrl>+<shift>+p.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        g.addWidget(hint, r, 0, 1, 3)
        r += 1

        g.addWidget(QLabel("Map load time (seconds)"), r, 0)
        self.pb_pre = QDoubleSpinBox(minimum=0.0, maximum=300.0, singleStep=0.5)
        self.pb_pre.setToolTip("How long your game takes to load into a match. "
                               "The macro waits this long before it starts "
                               "playing. Raise it if the macro starts too early.")
        self.pb_pre.valueChanged.connect(self._apply_settings)
        g.addWidget(self.pb_pre, r, 1)
        r += 1

        g.addWidget(QLabel("Check the screen every (seconds)"), r, 0)
        self.pb_poll = QDoubleSpinBox(minimum=0.05, maximum=5.0, singleStep=0.05)
        self.pb_poll.setToolTip("How often Looper looks for your captured "
                                "images. The default is fine for almost everyone.")
        self.pb_poll.valueChanged.connect(self._apply_settings)
        g.addWidget(self.pb_poll, r, 1)
        r += 1

        g.setRowStretch(r, 1)
        return w

    def _tab_hotkeys(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setVerticalSpacing(8)

        labels = ("Start loop", "Stop loop", "Panic (stop everything)")
        self.hk_edits: list[QLineEdit] = []
        for i, text in enumerate(labels):
            g.addWidget(QLabel(text), i, 0)
            e = QLineEdit()
            e.editingFinished.connect(self._apply_settings)
            g.addWidget(e, i, 1)
            self.hk_edits.append(e)

        hint = QLabel("Global - they work while the game is focused. "
                      "Format: <f9>, <ctrl>+<alt>+s, etc.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        g.addWidget(hint, 3, 0, 1, 2)
        g.setRowStretch(4, 1)
        return w

    def _tab_webhook(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setVerticalSpacing(8)
        r = 0

        self.wh_enabled = QCheckBox("Send updates to my phone (through Discord)")
        self.wh_enabled.stateChanged.connect(self._apply_settings)
        g.addWidget(self.wh_enabled, r, 0, 1, 3)
        r += 1

        g.addWidget(QLabel("Discord webhook URL"), r, 0)
        self.wh_url = QLineEdit()
        self.wh_url.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.wh_url.setEchoMode(QLineEdit.Password)
        self.wh_url.editingFinished.connect(self._apply_settings)
        g.addWidget(self.wh_url, r, 1)
        b = QPushButton("Test")
        b.clicked.connect(self._test_webhook)
        g.addWidget(b, r, 2)
        r += 1

        self.wh_cycle = QCheckBox("Message me when a match finishes")
        self.wh_cycle.stateChanged.connect(self._apply_settings)
        g.addWidget(self.wh_cycle, r, 0, 1, 2)
        r += 1
        g.addWidget(QLabel("...but only every N matches"), r, 0)
        self.wh_every = QSpinBox(minimum=1, maximum=1000)
        self.wh_every.valueChanged.connect(self._apply_settings)
        g.addWidget(self.wh_every, r, 1)
        r += 1

        self.wh_start = QCheckBox("Message me when the loop starts")
        self.wh_stop = QCheckBox("Message me when the loop stops")
        self.wh_err = QCheckBox("Message me if something goes wrong")
        for cb in (self.wh_start, self.wh_stop, self.wh_err):
            cb.stateChanged.connect(self._apply_settings)
            g.addWidget(cb, r, 0, 1, 3)
            r += 1

        hint = QLabel("To get a webhook link: in any Discord server you own, "
                      "right-click a channel > Edit Channel > Integrations > "
                      "Webhooks > New Webhook > Copy URL. Paste it above and "
                      "hit Test - the message shows up in that channel, and "
                      "on your phone if you have the Discord app.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        g.addWidget(hint, r, 0, 1, 4)
        g.setRowStretch(r + 1, 1)
        return w

    # ==================================================================
    # profile <-> UI sync
    # ==================================================================
    def _load_initial_profile(self) -> None:
        paths = Profile.list_all()
        if paths:
            self.profile = Profile.load(paths[0])
        else:
            self.profile.steps.append(Step(name="End screen"))
            self.profile.save()
        self._refresh_profile_combo()
        self._profile_to_ui()

    def _refresh_profile_combo(self) -> None:
        with self._filling_ui():
            self.profile_combo.clear()
            for p in Profile.list_all():
                self.profile_combo.addItem(p.stem)
            self.profile_combo.setCurrentText(self.profile.name)

    def _profile_to_ui(self) -> None:
        p = self.profile
        with self._filling_ui():
            self.step_list.clear()
            for s in p.steps:
                self.step_list.addItem(self._step_item(s))
            if p.steps:
                self.step_list.setCurrentRow(0)

            idx = self.pb_mode.findData(p.mode)
            self.pb_mode.setCurrentIndex(max(0, idx))
            self.pb_macro.setText(p.macro_file)
            self.pb_player.setText(p.player_path)
            self.pb_launch.setChecked(p.launch_player)
            self.pb_play_hk.setText(p.play_hotkey)
            self.pb_stop_hk.setText(p.stop_hotkey)
            self.pb_pre.setValue(p.pre_playback_delay)
            self.pb_poll.setValue(p.poll_interval)

            self.hk_edits[0].setText(p.hk_start)
            self.hk_edits[1].setText(p.hk_stop)
            self.hk_edits[2].setText(p.hk_panic)
            self.btn_start.setText(f"Start  ({p.hk_start.strip('<>').upper()})")
            self.btn_stop.setText(f"Stop  ({p.hk_stop.strip('<>').upper()})")

            self.wh_enabled.setChecked(p.webhook_enabled)
            self.wh_url.setText(p.webhook_url)
            self.wh_cycle.setChecked(p.webhook_on_cycle)
            self.wh_every.setValue(p.webhook_every)
            self.wh_start.setChecked(p.webhook_on_start)
            self.wh_stop.setChecked(p.webhook_on_stop)
            self.wh_err.setChecked(p.webhook_on_error)

        self._step_to_editor()
        self._refresh_guide()

    def _step_item(self, s: Step) -> QListWidgetItem:
        state = "" if s.enabled else "  (off)"
        img = "" if s.template else "  -  needs a capture"
        act = "watch + click" if s.click else "watch only"
        item = QListWidgetItem(f"{s.name}  -  {act}{img}{state}")
        return item

    def _refresh_step_row(self, row: int) -> None:
        if 0 <= row < len(self.profile.steps):
            s = self.profile.steps[row]
            self.step_list.item(row).setText(self._step_item(s).text())

    # -- step editor sync --
    def _current_step(self) -> Step | None:
        row = self.step_list.currentRow()
        if 0 <= row < len(self.profile.steps):
            return self.profile.steps[row]
        return None

    def _on_step_selected(self, _row: int) -> None:
        self._step_to_editor()

    def _step_to_editor(self) -> None:
        s = self._current_step()
        enabled = s is not None
        with self._filling_ui():
            for w in (self.ed_name, self.ed_threshold, self.ed_click, self.ed_post,
                      self.ed_timeout, self.ed_on_timeout, self.ed_enabled,
                      self.btn_capture):
                w.setEnabled(enabled)
            if s:
                self.ed_name.setText(s.name)
                self.ed_threshold.setValue(s.threshold)
                self.ed_click.setChecked(s.click)
                self.ed_post.setValue(s.post_delay)
                self.ed_timeout.setValue(s.timeout)
                idx = self.ed_on_timeout.findData(s.on_timeout)
                self.ed_on_timeout.setCurrentIndex(max(0, idx))
                self.ed_enabled.setChecked(s.enabled)
                self._show_thumb(s)
            else:
                self.thumb.setText("select a step")
                self.thumb.setPixmap(QPixmap())

    def _show_thumb(self, s: Step) -> None:
        if s.template and Path(s.template).is_file():
            pm = QPixmap(s.template)
            self.thumb.setPixmap(pm.scaled(self.thumb.size(), Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("nothing captured\nyet")

    def _apply_editor(self) -> None:
        if self._loading:
            return
        s = self._current_step()
        if not s:
            return
        s.name = self.ed_name.text() or s.name
        s.threshold = self.ed_threshold.value()
        s.click = self.ed_click.isChecked()
        s.post_delay = self.ed_post.value()
        s.timeout = self.ed_timeout.value()
        s.on_timeout = self.ed_on_timeout.currentData()
        s.enabled = self.ed_enabled.isChecked()
        self._refresh_step_row(self.step_list.currentRow())

    def _apply_settings(self) -> None:
        if self._loading:
            return
        p = self.profile
        p.mode = self.pb_mode.currentData()
        p.macro_file = self.pb_macro.text().strip()
        p.player_path = self.pb_player.text().strip()
        p.launch_player = self.pb_launch.isChecked()
        p.pre_playback_delay = self.pb_pre.value()
        p.poll_interval = self.pb_poll.value()

        p.play_hotkey = self._checked_hotkey(
            self.pb_play_hk, p.play_hotkey, "play")
        p.stop_hotkey = self._checked_hotkey(
            self.pb_stop_hk, p.stop_hotkey, "stop")

        p.hk_start = self._checked_hotkey(self.hk_edits[0], p.hk_start, "start")
        p.hk_stop = self._checked_hotkey(self.hk_edits[1], p.hk_stop, "stop loop")
        p.hk_panic = self._checked_hotkey(self.hk_edits[2], p.hk_panic, "panic")
        self.btn_start.setText(f"Start  ({p.hk_start.strip('<>').upper()})")
        self.btn_stop.setText(f"Stop  ({p.hk_stop.strip('<>').upper()})")
        self._bind_hotkeys()

        p.webhook_enabled = self.wh_enabled.isChecked()
        p.webhook_url = self.wh_url.text().strip()
        p.webhook_on_cycle = self.wh_cycle.isChecked()
        p.webhook_every = self.wh_every.value()
        p.webhook_on_start = self.wh_start.isChecked()
        p.webhook_on_stop = self.wh_stop.isChecked()
        p.webhook_on_error = self.wh_err.isChecked()
        self._refresh_guide()

    @contextmanager
    def _filling_ui(self):
        """While active, widget-change signals must not write to the profile."""
        self._loading += 1
        try:
            yield
        finally:
            self._loading -= 1

    def _checked_hotkey(self, field: QLineEdit, previous: str, label: str) -> str:
        """Validate a hotkey field. Good -> write the canonical form back.
        Bad -> explain, restore the last working value. Never saves garbage."""
        text = field.text().strip()
        if not text:
            return ""
        try:
            canonical = player.normalize_hotkey(text)
        except ValueError as e:
            self.log(f"That {label} hotkey won't work: {e} "
                     f"Kept the old one ({previous or 'none'}).")
            field.setText(previous)
            return previous
        if canonical != text:
            field.setText(canonical)
        return canonical

    # ==================================================================
    # setup guide
    # ==================================================================
    def _refresh_guide(self) -> None:
        running = bool(self.engine and self.engine.isRunning())
        self.guide.refresh(self.profile, running, self.profile.hk_start)

    def _guide_capture(self) -> None:
        if not self.profile.steps:
            self._add_step()
        self.step_list.setCurrentRow(0)
        self._capture_region()

    def _guide_macro(self) -> None:
        self._browse(self.pb_macro, "Pick your macro recording")

    def _guide_dismiss(self) -> None:
        onboarding.dismiss_guide()
        self.guide.setVisible(False)

    def _setup_ready(self) -> tuple[bool, str]:
        """Is there enough configuration for the loop to actually run?"""
        s0 = self.profile.steps[0] if self.profile.steps else None
        if not (s0 and s0.template and s0.has_region):
            return False, ("Almost - Looper doesn't know what the end "
                           "screen looks like yet. Do step 1: capture the "
                           "Retry button.")
        if not self.profile.macro_file.strip():
            return False, ("Almost - pick the macro recording to play "
                           "(step 2 in the guide).")
        return True, ""

    # ==================================================================
    # actions
    # ==================================================================
    def _bind_hotkeys(self) -> None:
        err = self.hk.rebind(self.profile.hk_start, self.profile.hk_stop,
                             self.profile.hk_panic)
        if err:
            self.log(f"Hotkey error: {err}")

    def _browse(self, target: QLineEdit, caption: str, filt: str = "All files (*)") -> None:
        path, _ = QFileDialog.getOpenFileName(self, caption, "", filt)
        if path:
            target.setText(path)
            self._apply_settings()

    def _add_step(self) -> None:
        self.profile.steps.append(Step(name=f"Step {len(self.profile.steps) + 1}"))
        self.step_list.addItem(self._step_item(self.profile.steps[-1]))
        self.step_list.setCurrentRow(len(self.profile.steps) - 1)

    def _remove_step(self) -> None:
        row = self.step_list.currentRow()
        if row < 0:
            return
        self.profile.steps.pop(row)
        self.step_list.takeItem(row)

    def _move_step(self, delta: int) -> None:
        row = self.step_list.currentRow()
        new = row + delta
        if row < 0 or not (0 <= new < len(self.profile.steps)):
            return
        s = self.profile.steps
        s[row], s[new] = s[new], s[row]
        self._refresh_step_row(row)
        self._refresh_step_row(new)
        self.step_list.setCurrentRow(new)

    def _capture_region(self) -> None:
        s = self._current_step()
        if not s:
            return
        self.hide()
        # give the window time to actually leave the screen
        from PySide6.QtCore import QTimer
        QTimer.singleShot(350, self._launch_picker)

    def _launch_picker(self) -> None:
        self._picker = overlay.RegionPicker()
        self._picker.picked.connect(self._on_region_picked)
        self._picker.cancelled.connect(self._on_pick_cancelled)
        self._picker.start()

    def _on_region_picked(self, region: dict, template: np.ndarray) -> None:
        self.show()
        s = self._current_step()
        if not s:
            return
        path = s.template if s.template else str(config.new_asset_path())
        matcher.save_png(path, template)
        s.template = path
        s.region = [region["left"], region["top"], region["width"], region["height"]]
        self._show_thumb(s)
        self._refresh_step_row(self.step_list.currentRow())
        self.log(f"[{s.name}] captured {region['width']}x{region['height']}px "
                 f"at ({region['left']}, {region['top']})")
        self._refresh_guide()

    def _on_pick_cancelled(self) -> None:
        self.show()

    # -- profiles --
    def _on_profile_switch(self, name: str) -> None:
        if self._loading or not name or name == self.profile.name:
            return
        path = config.PROFILE_DIR / f"{name}.json"
        if path.is_file():
            self.profile.save()
            self.profile = Profile.load(path)
            self._profile_to_ui()
            self._bind_hotkeys()

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if not ok:
            return
        # strip characters Windows can't put in a filename
        name = re.sub(r'[<>:"/\\|?*]', "", name).strip()
        if not name:
            self.log("That name can't be used - try plain letters and numbers.")
            return
        if (config.PROFILE_DIR / f"{name}.json").is_file():
            self.log(f"A profile called '{name}' already exists - "
                     "pick it from the dropdown instead.")
            return
        self.profile.save()
        self.profile = Profile(name=name,
                               steps=[Step(name="End screen")])
        self.profile.save()
        self._refresh_profile_combo()
        self._profile_to_ui()

    def _save_profile(self) -> None:
        self._apply_editor()
        self._apply_settings()
        path = self.profile.save()
        self.log(f"Saved -> {path}")

    def _delete_profile(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Delete profile")
        box.setText(f"Delete the profile '{self.profile.name}'?\n\n"
                    "Its captured images and settings go with it. "
                    "This can't be undone.")
        delete_btn = box.addButton("Delete profile", QMessageBox.DestructiveRole)
        box.addButton("Keep it", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not delete_btn:
            return
        self.profile.path.unlink(missing_ok=True)
        paths = Profile.list_all()
        self.profile = Profile.load(paths[0]) if paths else Profile(
            name="Default", steps=[Step(name="End screen")])
        if not paths:
            self.profile.save()
        self._refresh_profile_combo()
        self._profile_to_ui()

    def _test_webhook(self) -> None:
        self._apply_settings()
        self.hook.configure(self.profile.webhook_url, True)
        ok, msg = self.hook.test()
        (QMessageBox.information if ok else QMessageBox.warning)(
            self, "Webhook test", msg)

    # -- loop control --
    def start_loop(self) -> None:
        if self.engine and self.engine.isRunning():
            return
        self._apply_editor()
        self._apply_settings()

        ready, why = self._setup_ready()
        if not ready:
            self.guide.setVisible(True)
            self._refresh_guide()
            self.log(why)
            self.state_label.setText("Finish setup first")
            return

        self.profile.save()
        self.hook.configure(self.profile.webhook_url, self.profile.webhook_enabled)

        self.engine = engine.LoopEngine(self.profile, self.hook)
        self.engine.sig_log.connect(self.log)
        self.engine.sig_state.connect(self.state_label.setText)
        self.engine.sig_cycle.connect(self._on_cycle)
        self.engine.sig_step.connect(self._highlight_step)
        self.engine.sig_stopped.connect(self._on_engine_stopped)
        self.engine.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_profile_controls(False)
        self.cycle_label.setText("0")
        self.log("=== Loop started ===")
        self._refresh_guide()

    def stop_loop(self) -> None:
        if self.engine and self.engine.isRunning():
            self.log("Stopping...")
            self.engine.stop()

    def panic(self) -> None:
        self.stop_loop()
        self.log("PANIC - loop halted.")

    def _on_cycle(self, n: int) -> None:
        self.cycle_label.setText(str(n))
        if n == 1 and not onboarding.first_cycle_done():
            onboarding.mark_first_cycle()
            self.log("First full cycle done - it's farming on its own now. "
                     "You can minimize this window and walk away.")
            self._refresh_guide()

    def _set_profile_controls(self, enabled: bool) -> None:
        """Profiles can't change under a running loop."""
        self.profile_combo.setEnabled(enabled)
        for b in self._profile_buttons:
            b.setEnabled(enabled)

    def _on_engine_stopped(self, reason: str) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_profile_controls(True)
        self.state_label.setText("Not running")
        self._highlight_step(-1)
        self._refresh_guide()
        if reason:
            self.log(f"Stopped: {reason}")
            QMessageBox.warning(self, "Loop stopped", reason)
        else:
            self.log("=== Loop stopped ===")

    def _highlight_step(self, idx: int) -> None:
        for i in range(self.step_list.count()):
            item = self.step_list.item(i)
            base = item.text().lstrip("> ")
            item.setText(f"> {base}" if i == idx else base)

    # -- misc --
    def log(self, msg: str) -> None:
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.engine and self.engine.isRunning():
            self.engine.stop()
            self.engine.wait(3000)
        self.hk.unbind()
        self._apply_editor()
        self._apply_settings()
        self.profile.save()
        event.accept()
