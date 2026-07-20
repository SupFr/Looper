"""Looper entry point."""

import sys

from PySide6.QtWidgets import QApplication

from looper import theme
from looper.ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Looper")
    app.setStyleSheet(theme.QSS)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
