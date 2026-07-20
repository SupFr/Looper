"""Warm dark QSS theme.

Palette rules (contrast-verified, all text >= 4.5:1 on its background):
  bg      #1a1512   warm near-black body
  surface #241d18   panels
  border  #38302a   hairlines
  ink     #f2ece4   primary text (15.4:1 on bg)
  muted   #b3a698   secondary text (7.0:1 on surface)
  faint   #9c8f81   placeholders / de-emphasized (5.3:1 on surface)
  accent  #e8944a   THE interactive color: primary buttons, focus, selection
  green   #5fbf74   reserved for running / success state only
  danger  #e06c5b   destructive / error only
"""

QSS = """
* { font-family: 'Segoe UI'; font-size: 13px; }

QMainWindow, QDialog { background: #1a1512; }
QWidget { color: #f2ece4; background: transparent; }

QFrame#panel {
    background: #241d18;
    border: 1px solid #38302a;
    border-radius: 10px;
}

QLabel#h1 { font-size: 17px; font-weight: 600; }
QLabel#h2 { font-size: 13px; font-weight: 600; color: #b3a698; }
QLabel#hint { color: #b3a698; font-size: 12px; }

/* ---------- hero status ---------- */

QFrame#hero {
    background: #241d18;
    border: 1px solid #38302a;
    border-radius: 10px;
}
QFrame#hero[mode="running"] { background: #1d2b1f; border-color: #2f5237; }
QFrame#hero[mode="error"]   { background: #2e1d1a; border-color: #5c332c; }

QLabel#heroState { font-size: 30px; font-weight: 700; }
QFrame#hero[mode="running"] QLabel#heroState { color: #5fbf74; }
QFrame#hero[mode="error"]   QLabel#heroState { color: #e06c5b; }
QLabel#heroCount { font-size: 44px; font-weight: 800; color: #f2ece4; }
QFrame#hero[mode="running"] QLabel#heroCount { color: #5fbf74; }
QLabel#heroCountCaption { color: #b3a698; font-size: 12px; }

/* ---------- buttons ---------- */

QPushButton {
    background: #2c241e;
    border: 1px solid #38302a;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background: #38302a; }
QPushButton:pressed { background: #32291f; }
QPushButton:focus { border: 1px solid #e8944a; }
QPushButton:disabled { color: #9c8f81; background: #241d18; }

QPushButton#primary {
    background: #e8944a;
    border: 1px solid #e8944a;
    color: #1a1512;
    font-weight: 600;
}
QPushButton#primary:hover { background: #f0a35e; }
QPushButton#primary:focus { border: 1px solid #f2ece4; }
QPushButton#primary:disabled { background: #4a3a29; color: #9c8f81; }

QPushButton#danger {
    background: #b04a3c;
    border: 1px solid #b04a3c;
    color: #f2ece4;
    font-weight: 600;
}
QPushButton#danger:hover { background: #c65a4a; }
QPushButton#danger:focus { border: 1px solid #f2ece4; }
QPushButton#danger:disabled { background: #3a2622; color: #9c8f81; }

/* ---------- inputs ---------- */

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QKeySequenceEdit {
    background: #1a1512;
    border: 1px solid #38302a;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #e8944a;
    selection-color: #1a1512;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QKeySequenceEdit:focus {
    border-color: #e8944a;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #241d18; border: 1px solid #38302a;
    selection-background-color: #e8944a;
    selection-color: #1a1512;
}

QCheckBox:focus { color: #e8944a; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #4a3f36; border-radius: 4px; background: #1a1512;
}
QCheckBox::indicator:checked { background: #e8944a; border-color: #e8944a; }

/* ---------- lists / log / tabs ---------- */

QListWidget {
    background: #1a1512;
    border: 1px solid #38302a;
    border-radius: 8px;
    padding: 4px;
}
QListWidget:focus { border: 1px solid #e8944a; }
QListWidget::item {
    padding: 8px 10px;
    border-radius: 6px;
    margin: 1px 2px;
}
QListWidget::item:selected {
    background: rgba(232,148,74,0.18);
    color: #f2ece4;
}
QListWidget::item:hover { background: #2c241e; }

QPlainTextEdit {
    background: #1a1512;
    border: 1px solid #38302a;
    border-radius: 8px;
    color: #b3a698;
    font-family: 'Cascadia Mono', 'Consolas';
    font-size: 12px;
}

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent;
    color: #b3a698;
    padding: 7px 16px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #f2ece4; border-bottom: 2px solid #e8944a; }
QTabBar::tab:hover { color: #f2ece4; }

QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #38302a; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip { background: #241d18; color: #f2ece4; border: 1px solid #38302a; }

QLabel#thumb {
    border: 1px dashed #4a3f36;
    border-radius: 6px;
    color: #9c8f81;
}

/* ---------- setup guide ---------- */

QFrame#setupGuide {
    background: #211a15;
    border: 1px solid rgba(232,148,74,0.35);
    border-radius: 10px;
}
QLabel#guideTitle { font-size: 14px; font-weight: 600; }
QLabel#guideProgress { color: #b3a698; }
QPushButton#guideHide {
    background: transparent; border: none; color: #b3a698; padding: 2px 6px;
}
QPushButton#guideHide:hover { color: #f2ece4; }
QPushButton#guideHide:focus { color: #e8944a; }

QFrame#guideRow { border-radius: 8px; }
QFrame#guideRow[state="current"] { background: rgba(232,148,74,0.10); }
QFrame#guideRow[state="done"] QLabel#guideRowTitle { color: #b3a698; }
QFrame#guideRow[state="todo"] QLabel { color: #9c8f81; }

QLabel#guideDot {
    border-radius: 13px;
    font-weight: 700;
    background: #2c241e;
    color: #b3a698;
}
QLabel#guideDot[state="current"] { background: #e8944a; color: #1a1512; }
QLabel#guideDot[state="done"] { background: rgba(95,191,116,0.18); color: #5fbf74; }

QLabel#guideRowTitle { font-weight: 600; }
QLabel#guideRowDesc { color: #b3a698; font-size: 12px; }

QPushButton#guideAction {
    background: #e8944a;
    border: none;
    border-radius: 6px;
    color: #1a1512;
    font-weight: 600;
    padding: 6px 18px;
}
QPushButton#guideAction:hover { background: #f0a35e; }
QPushButton#guideAction:focus { border: 1px solid #f2ece4; }
"""
