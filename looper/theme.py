"""Dark QSS theme."""

QSS = """
* { font-family: 'Segoe UI'; font-size: 13px; }

QMainWindow, QDialog { background: #0d1117; }
QWidget { color: #e6edf3; background: transparent; }

QFrame#panel {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
}

QLabel#h1 { font-size: 17px; font-weight: 600; }
QLabel#h2 { font-size: 13px; font-weight: 600; color: #8b949e; }
QLabel#stateLabel { font-size: 15px; font-weight: 600; color: #58a6ff; }
QLabel#cycleLabel { font-size: 26px; font-weight: 700; color: #3fb950; }
QLabel#hint { color: #8b949e; font-size: 12px; }

QPushButton {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background: #30363d; }
QPushButton:pressed { background: #282e36; }
QPushButton:disabled { color: #545d68; background: #161b22; }

QPushButton#primary {
    background: #238636;
    border-color: #2ea043;
    font-weight: 600;
}
QPushButton#primary:hover { background: #2ea043; }
QPushButton#primary:disabled { background: #1a3a24; color: #6a737d; }

QPushButton#danger {
    background: #da3633;
    border-color: #f85149;
    font-weight: 600;
}
QPushButton#danger:hover { background: #f85149; }
QPushButton#danger:disabled { background: #4a1d1c; color: #8b6a6a; }

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #1f6feb;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #58a6ff;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #161b22; border: 1px solid #30363d;
    selection-background-color: #1f6feb;
}

QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #30363d; border-radius: 4px; background: #0d1117;
}
QCheckBox::indicator:checked { background: #1f6feb; border-color: #1f6feb; }

QListWidget {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 6px;
    margin: 1px 2px;
}
QListWidget::item:selected { background: rgba(31,111,235,0.20); color: #e6edf3; }
QListWidget::item:hover { background: #21262d; }

QPlainTextEdit {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 8px;
    color: #8b949e;
    font-family: 'Cascadia Mono', 'Consolas';
    font-size: 12px;
}

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent;
    color: #8b949e;
    padding: 7px 16px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #e6edf3; border-bottom: 2px solid #f78166; }
QTabBar::tab:hover { color: #e6edf3; }

QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #30363d; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip { background: #161b22; color: #e6edf3; border: 1px solid #30363d; }

/* ---------- setup guide ---------- */

QFrame#setupGuide {
    background: #11161d;
    border: 1px solid rgba(31,111,235,0.33);
    border-radius: 10px;
}
QLabel#guideTitle { font-size: 14px; font-weight: 600; }
QLabel#guideProgress { color: #8b949e; }
QPushButton#guideHide {
    background: transparent; border: none; color: #8b949e; padding: 2px 6px;
}
QPushButton#guideHide:hover { color: #e6edf3; }

QFrame#guideRow { border-radius: 8px; }
QFrame#guideRow[state="current"] { background: rgba(31,111,235,0.10); }
QFrame#guideRow[state="done"] QLabel#guideRowTitle { color: #8b949e; }
QFrame#guideRow[state="todo"] QLabel { color: #545d68; }

QLabel#guideDot {
    border-radius: 13px;
    font-weight: 700;
    background: #21262d;
    color: #8b949e;
}
QLabel#guideDot[state="current"] { background: #1f6feb; color: #ffffff; }
QLabel#guideDot[state="done"] { background: rgba(35,134,54,0.20); color: #3fb950; }

QLabel#guideRowTitle { font-weight: 600; }
QLabel#guideRowDesc { color: #8b949e; font-size: 12px; }

QPushButton#guideAction {
    background: #1f6feb;
    border: none;
    border-radius: 6px;
    color: #ffffff;
    font-weight: 600;
    padding: 6px 18px;
}
QPushButton#guideAction:hover { background: #388bfd; }
"""
