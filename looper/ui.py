"""Main window."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QImage, QPixmap, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QDoubleSpinBox,
    QSpinBox, QListWidget, QListWidgetItem, QPlainTextEdit, QTabWidget,
    QFileDialog, QMessageBox, QInputDialog, QSplitter, QKeySequenceEdit,
    QDialog,
)

import re
from pathlib import PurePath

from . import (config, capture, engine, hotkeys, matcher, onboarding,
               overlay, player, webhook)
from .config import Profile, Step


def _panel() -> QFrame:
    f = QFrame()
    f.setObjectName("panel")
    return f


def _bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    h, w = bgr.shape[:2]
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())


class HotkeyEdit(QKeySequenceEdit):
    """Press-to-record hotkey field. Click it, press the keys, done.

    Speaks the app's canonical format ('<ctrl>+<shift>+p') at the edges;
    nobody has to type bracket syntax anymore.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMaximumSequenceLength(1)
        self.setClearButtonEnabled(True)
        self._canonical = ""
        self.editingFinished.connect(self._on_edited)

    def canonical(self) -> str:
        return self._canonical

    def set_canonical(self, spec: str) -> None:
        self._canonical = spec.strip()
        qt = player.to_qt_keysequence(self._canonical) if self._canonical else ""
        self.setKeySequence(QKeySequence(qt))

    def _on_edited(self) -> None:
        qt = self.keySequence().toString(QKeySequence.PortableText)
        if not qt:
            self._canonical = ""
            self.changed.emit()
            return
        try:
            self._canonical = player.from_qt_keysequence(qt)
        except ValueError:
            # combination we can't replay (media keys etc.) - roll back
            self.set_canonical(self._canonical)
            return
        self.changed.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Looper v1.6")
        self.setMinimumSize(760, 420)
        self.resize(1060, 700)

        self.profile = Profile(name="Default")
        self.hook = webhook.Webhook()
        self.engine: engine.LoopEngine | None = None
        self.hk = hotkeys.HotkeyManager()
        self._picker: overlay.RegionPicker | None = None
        self._active_step = -1
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

        outer.addWidget(self._build_hero())
        outer.addWidget(self._build_reference())

        # Everything below the hero is the "tinker" face: hidden by default
        # so a friend's first sight is guide + status + Start, nothing else.
        self.tinker = QWidget()
        tv = QVBoxLayout(self.tinker)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_steps_panel())
        split.addWidget(self._build_settings_panel())
        split.setSizes([560, 480])
        tv.addWidget(split, 1)

        self.log_view = QPlainTextEdit(readOnly=True, maximumBlockCount=500)
        self.log_view.setFixedHeight(130)
        self.log_view.setPlaceholderText(
            "Activity shows up here once the loop is running - every match "
            "detected, every restart, every click.")
        tv.addWidget(self.log_view)

        outer.addWidget(self.tinker, 1)
        self._spacer = QWidget()
        outer.addWidget(self._spacer, 1)

        open_ = onboarding.tinker_open()
        self.tinker.setVisible(open_)
        self._spacer.setVisible(not open_)
        self.btn_tinker.setChecked(open_)
        self.btn_tinker.setText("Fewer options" if open_ else "More options")

    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("hero")
        hero.setProperty("mode", "idle")
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(20, 14, 20, 14)

        self.state_label = QLabel("Not running")
        self.state_label.setObjectName("heroState")
        lay.addWidget(self.state_label, 1)

        self.record_label = QLabel("")
        self.record_label.setObjectName("heroRecord")
        self.record_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self.record_label.hide()
        lay.addWidget(self.record_label)

        right = QVBoxLayout()
        right.setSpacing(0)
        self.cycle_label = QLabel("0")
        self.cycle_label.setObjectName("heroCount")
        self.cycle_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cap = QLabel("matches done")
        cap.setObjectName("heroCountCaption")
        cap.setAlignment(Qt.AlignRight)
        right.addWidget(self.cycle_label)
        right.addWidget(cap)
        lay.addLayout(right)

        self.hero = hero
        return hero

    def _on_result(self, wins: int, losses: int) -> None:
        self.record_label.setText(f"{wins}W · {losses}L")
        self.record_label.show()

    def _build_reference(self) -> QFrame:
        """Two one-time photos so the player equips the right team before
        farming. Shown for whichever recording is selected."""
        panel = _panel()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QLabel("YOUR SETUP FOR THIS RECORDING")
        head.setObjectName("h2")
        lay.addWidget(head)

        hint = QLabel("Take one photo of your team and one of the act info, so "
                      "next time you open this recording you know exactly what "
                      "to equip and where.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(16)
        self._ref_thumbs: dict[str, QLabel] = {}
        for which, caption in (("units", "Your team"), ("act", "Act info")):
            col = QVBoxLayout()
            col.setSpacing(4)
            cap = QLabel(caption)
            cap.setStyleSheet("font-weight: 600;")
            col.addWidget(cap)

            thumb = QLabel("not taken yet")
            thumb.setObjectName("thumb")
            thumb.setFixedSize(QSize(220, 124))
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setCursor(Qt.PointingHandCursor)
            thumb.mousePressEvent = lambda e, w=which: self._enlarge_reference(w)
            self._ref_thumbs[which] = thumb
            col.addWidget(thumb)

            btn = QPushButton(f"Capture {caption.lower()}")
            btn.clicked.connect(lambda _=False, w=which: self._capture_reference(w))
            col.addWidget(btn)
            row.addLayout(col)
        row.addStretch(1)
        lay.addLayout(row)

        self._reference_panel = panel
        return panel

    def _refresh_reference(self) -> None:
        for which, thumb in self._ref_thumbs.items():
            path = getattr(self.profile, f"ref_{which}")
            if path and Path(path).is_file():
                pm = QPixmap(path)
                thumb.setPixmap(pm.scaled(thumb.size(), Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
            else:
                thumb.setPixmap(QPixmap())
                thumb.setText("not taken yet")

    def _enlarge_reference(self, which: str) -> None:
        path = getattr(self.profile, f"ref_{which}")
        if not (path and Path(path).is_file()):
            self._capture_reference(which)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Your team" if which == "units" else "Act info")
        v = QVBoxLayout(dlg)
        img = QLabel()
        pm = QPixmap(path)
        if pm.width() > 1000:
            pm = pm.scaledToWidth(1000, Qt.SmoothTransformation)
        img.setPixmap(pm)
        v.addWidget(img)
        dlg.exec()

    def _set_hero_mode(self, mode: str) -> None:
        self.hero.setProperty("mode", mode)
        self.hero.style().unpolish(self.hero)
        self.hero.style().polish(self.hero)
        for child in (self.state_label, self.cycle_label):
            child.style().unpolish(child)
            child.style().polish(child)

    def _update_title(self) -> None:
        running = bool(self.engine and self.engine.isRunning())
        if running:
            self.setWindowTitle(
                f"Looper - {self.cycle_label.text()} matches - running")
        else:
            self.setWindowTitle("Looper v1.6")

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

        self.btn_tinker = QPushButton("More options")
        self.btn_tinker.setCheckable(True)
        self.btn_tinker.toggled.connect(self._toggle_tinker)
        lay.addWidget(self.btn_tinker)

        lay.addSpacing(8)
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
        self.thumb.setObjectName("thumb")
        self.thumb.setFixedSize(QSize(150, 84))
        self.thumb.setAlignment(Qt.AlignCenter)
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
        tabs.addTab(self._tab_result(), "Win / Loss")
        tabs.addTab(self._tab_webhook(), "Webhook")
        lay.addWidget(tabs)
        return panel

    def _tab_result(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setVerticalSpacing(8)
        r = 0

        intro = QLabel("Optional. Show Looper what a win and a loss look like "
                       "and it'll keep score - and say which you got in the "
                       "Discord message. Capture a small, always-the-same part "
                       "of each end screen (the 'Victory' or 'Defeat' word is "
                       "perfect). Skip anything with changing numbers.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        g.addWidget(intro, r, 0, 1, 3)
        r += 1

        for which, word in (("win", "win"), ("loss", "loss")):
            btn = QPushButton(f"Capture what a {word} looks like")
            btn.clicked.connect(lambda _=False, k=which: self._capture_result(k))
            g.addWidget(btn, r, 0, 1, 2)
            lbl = QLabel("not set")
            lbl.setObjectName("hint")
            setattr(self, f"_result_lbl_{which}", lbl)
            g.addWidget(lbl, r, 2)
            r += 1

        g.addWidget(QLabel("Match strictness"), r, 0)
        self.res_threshold = QDoubleSpinBox(minimum=0.5, maximum=1.0,
                                            singleStep=0.01, decimals=2)
        self.res_threshold.setToolTip("Lower it a little if Looper mixes up "
                                      "wins and losses.")
        self.res_threshold.valueChanged.connect(self._apply_settings)
        g.addWidget(self.res_threshold, r, 1)
        r += 1

        g.setRowStretch(r, 1)
        return w

    def _refresh_result_labels(self) -> None:
        for which in ("win", "loss"):
            lbl = getattr(self, f"_result_lbl_{which}", None)
            if lbl is None:
                continue
            tpl = getattr(self.profile, f"{which}_template")
            lbl.setText("captured ✓" if tpl and Path(tpl).is_file() else "not set")

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
        b.clicked.connect(self._browse_macro)
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
        self.pb_play_hk = HotkeyEdit()
        self.pb_play_hk.changed.connect(self._apply_settings)
        g.addWidget(self.pb_play_hk, r, 1, 1, 2)
        r += 1

        g.addWidget(QLabel("Stop hotkey"), r, 0)
        self.pb_stop_hk = HotkeyEdit()
        self.pb_stop_hk.changed.connect(self._apply_settings)
        g.addWidget(self.pb_stop_hk, r, 1, 1, 2)
        r += 1

        hint = QLabel("These are the player app's own shortcuts - Looper "
                      "presses them for you. Click a field and press the "
                      "actual keys to set it. TinyTask uses the same key "
                      "for play and stop.")
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
        self.hk_edits: list[HotkeyEdit] = []
        for i, text in enumerate(labels):
            g.addWidget(QLabel(text), i, 0)
            e = HotkeyEdit()
            e.changed.connect(self._apply_settings)
            g.addWidget(e, i, 1)
            self.hk_edits.append(e)

        hint = QLabel("These work while the game is focused. Click a field "
                      "and press the actual keys to set it.")
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
        show = QCheckBox("Show")
        show.setToolTip("The link is hidden because anyone who has it can "
                        "post in your channel.")
        show.toggled.connect(lambda on: self.wh_url.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        g.addWidget(show, r, 2)
        b = QPushButton("Test")
        b.clicked.connect(self._test_webhook)
        g.addWidget(b, r, 3)
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
            self.pb_play_hk.set_canonical(p.play_hotkey)
            self.pb_stop_hk.set_canonical(p.stop_hotkey)
            self.pb_pre.setValue(p.pre_playback_delay)
            self.pb_poll.setValue(p.poll_interval)

            self.hk_edits[0].set_canonical(p.hk_start)
            self.hk_edits[1].set_canonical(p.hk_stop)
            self.hk_edits[2].set_canonical(p.hk_panic)
            self.btn_start.setText(f"Start  ({p.hk_start.strip('<>').upper()})")
            self.btn_stop.setText(f"Stop  ({p.hk_stop.strip('<>').upper()})")

            self.wh_enabled.setChecked(p.webhook_enabled)
            self.wh_url.setText(p.webhook_url)
            self.wh_cycle.setChecked(p.webhook_on_cycle)
            self.wh_every.setValue(p.webhook_every)
            self.wh_start.setChecked(p.webhook_on_start)
            self.wh_stop.setChecked(p.webhook_on_stop)
            self.wh_err.setChecked(p.webhook_on_error)

            self.res_threshold.setValue(p.result_threshold)

        self._step_to_editor()
        self._refresh_guide()
        self._refresh_reference()
        self._refresh_result_labels()
        self.record_label.hide()

    def _step_item(self, s: Step) -> QListWidgetItem:
        state = "" if s.enabled else "  (off)"
        img = "" if s.template else "  -  needs a capture"
        act = "watch + click" if s.click else "watch only"
        item = QListWidgetItem(f"{s.name}  -  {act}{img}{state}")
        return item

    def _refresh_step_row(self, row: int) -> None:
        if 0 <= row < len(self.profile.steps):
            s = self.profile.steps[row]
            base = self._step_item(s).text()
            if row == self._active_step:
                base = f"▶  {base}"
            self.step_list.item(row).setText(base)

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

        p.play_hotkey = self.pb_play_hk.canonical()
        p.stop_hotkey = self.pb_stop_hk.canonical()

        p.hk_start = self.hk_edits[0].canonical()
        p.hk_stop = self.hk_edits[1].canonical()
        p.hk_panic = self.hk_edits[2].canonical()
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
        p.result_threshold = self.res_threshold.value()
        self._refresh_guide()

    @contextmanager
    def _filling_ui(self):
        """While active, widget-change signals must not write to the profile."""
        self._loading += 1
        try:
            yield
        finally:
            self._loading -= 1

    def _toggle_tinker(self, open_: bool) -> None:
        self.tinker.setVisible(open_)
        self._spacer.setVisible(not open_)
        self.btn_tinker.setText("Fewer options" if open_ else "More options")
        onboarding.set_tinker(open_)

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
        self._browse_macro()

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

    def _browse_macro(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick your macro recording", "",
            "Macro recordings (*.rec *.mcr *.ahk *.exe);;All files (*)")
        if not path:
            return
        self.pb_macro.setText(path)
        # nobody should have to answer "how does your macro run?" - the
        # file extension already knows
        mode = (config.MODE_STANDALONE if PurePath(path).suffix.lower() == ".exe"
                else config.MODE_PLAYER)
        idx = self.pb_mode.findData(mode)
        if idx >= 0 and idx != self.pb_mode.currentIndex():
            self.pb_mode.setCurrentIndex(idx)
            self.log("Set 'How your macro runs' automatically from the "
                     "file you picked.")
        self._apply_settings()

    def _add_step(self) -> None:
        self.profile.steps.append(Step(name=f"Step {len(self.profile.steps) + 1}"))
        self.step_list.addItem(self._step_item(self.profile.steps[-1]))
        self.step_list.setCurrentRow(len(self.profile.steps) - 1)

    def _remove_step(self) -> None:
        row = self.step_list.currentRow()
        if row < 0:
            return
        s = self.profile.steps[row]
        if s.template:   # captured work would be lost - confirm
            box = QMessageBox(self)
            box.setWindowTitle("Remove step")
            box.setText(f"Remove the step '{s.name}'?\n\n"
                        "Its captured image goes with it.")
            rm = box.addButton("Remove step", QMessageBox.DestructiveRole)
            box.addButton("Keep it", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not rm:
                return
        self.profile.steps.pop(row)
        self.step_list.takeItem(row)
        self._refresh_guide()

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

    def _capture(self, handler) -> None:
        """Hide the window, let the user drag a region, hand the result to
        `handler(region_dict, image_bgr)`. Shared by steps, reference photos,
        and win/loss templates."""
        self._pick_handler = handler
        self.hide()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(350, self._launch_picker)

    def _capture_region(self) -> None:
        if not self._current_step():
            return
        self._capture(self._store_step_capture)

    def _launch_picker(self) -> None:
        self._picker = overlay.RegionPicker()
        self._picker.picked.connect(self._on_region_picked)
        self._picker.cancelled.connect(self._on_pick_cancelled)
        self._picker.start()

    def _on_region_picked(self, region: dict, template: np.ndarray) -> None:
        self.show()
        handler = getattr(self, "_pick_handler", None)
        if handler:
            handler(region, template)

    def _store_step_capture(self, region: dict, template: np.ndarray) -> None:
        s = self._current_step()
        if not s:
            return
        path = s.template if s.template else str(config.new_asset_path())
        matcher.save_png(path, template)
        s.template = path
        s.region = [region["left"], region["top"], region["width"], region["height"]]
        desk = capture.virtual_desktop()
        s.base = [desk["width"], desk["height"]]
        self._show_thumb(s)
        self._refresh_step_row(self.step_list.currentRow())
        self.log(f"[{s.name}] captured {region['width']}x{region['height']}px "
                 f"at ({region['left']}, {region['top']})")
        self._refresh_guide()

    def _on_pick_cancelled(self) -> None:
        self.show()

    # -- reference photos + win/loss captures --
    def _capture_reference(self, which: str) -> None:
        def store(region: dict, image: np.ndarray) -> None:
            path = str(config.new_asset_path())
            matcher.save_png(path, image)
            setattr(self.profile, f"ref_{which}", path)
            self._refresh_reference()
            self.log(f"Saved your {which} photo for this recording.")
        self._capture(store)

    def _capture_result(self, which: str) -> None:
        def store(region: dict, image: np.ndarray) -> None:
            path = str(config.new_asset_path())
            matcher.save_png(path, image)
            desk = capture.virtual_desktop()
            setattr(self.profile, f"{which}_template", path)
            setattr(self.profile, f"{which}_region",
                    [region["left"], region["top"], region["width"], region["height"]])
            setattr(self.profile, f"{which}_base", [desk["width"], desk["height"]])
            self._refresh_result_labels()
            label = "win" if which == "win" else "loss"
            self.log(f"Captured what a {label} looks like.")
        self._capture(store)

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
        self.engine.sig_result.connect(self._on_result)
        self.engine.sig_stopped.connect(self._on_engine_stopped)
        self.engine.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_profile_controls(False)
        self.cycle_label.setText("0")
        self.record_label.hide()
        self._set_hero_mode("running")
        self._update_title()
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
        self._update_title()
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
        self._highlight_step(-1)
        self._update_title()
        self._refresh_guide()
        if reason:
            self.state_label.setText("Stopped - needs you")
            self._set_hero_mode("error")
            self.log(f"Stopped: {reason}")
            QMessageBox.warning(self, "Loop stopped", reason)
        else:
            self.state_label.setText("Not running")
            self._set_hero_mode("idle")
            self.log("=== Loop stopped ===")

    def _highlight_step(self, idx: int) -> None:
        """Mark the step the engine is watching. Rebuild every row from the
        profile (the source of truth) so names never get mangled."""
        self._active_step = idx
        for i, s in enumerate(self.profile.steps):
            if i >= self.step_list.count():
                break
            item = self.step_list.item(i)
            base = self._step_item(s).text()
            font = item.font()
            font.setBold(i == idx)
            item.setFont(font)
            item.setText(f"▶  {base}" if i == idx else base)

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
