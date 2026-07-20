"""Fullscreen drag-select overlay.

Freezes the desktop into a screenshot, dims it, and lets the user rubber-band
a rectangle. The selected area is returned both as a physical-pixel region and
as the cropped template image -- one gesture defines watch zone + target.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap, QColor, QPen, QKeyEvent
from PySide6.QtWidgets import QWidget

from . import capture


class RegionPicker(QWidget):
    """Emits picked(region_physical, template_bgr) or cancelled()."""

    picked = Signal(dict, np.ndarray)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._desk = capture.virtual_desktop()          # physical px
        self._frame = capture.grab_virtual()            # BGR

        h, w = self._frame.shape[:2]
        rgb = np.ascontiguousarray(self._frame[:, :, ::-1])
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        self._shot = QPixmap.fromImage(img.copy())

        self._origin: QPoint | None = None
        self._current: QPoint | None = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setCursor(Qt.CrossCursor)

        # Cover the virtual desktop in LOGICAL coords.
        vg = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(vg)
        self._scale_x = w / vg.width()
        self._scale_y = h / vg.height()

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.drawPixmap(self.rect(), self._shot)
        p.fillRect(self.rect(), QColor(10, 12, 18, 130))

        if self._origin and self._current:
            sel = QRect(self._origin, self._current).normalized()
            # punch a clear hole showing the live selection
            src = QRect(
                int(sel.x() * self._scale_x), int(sel.y() * self._scale_y),
                int(sel.width() * self._scale_x), int(sel.height() * self._scale_y),
            )
            p.drawPixmap(sel, self._shot, src)
            pen = QPen(QColor(88, 166, 255), 2)
            p.setPen(pen)
            p.drawRect(sel)
            p.setPen(QColor(230, 237, 243))
            phys_w = int(sel.width() * self._scale_x)
            phys_h = int(sel.height() * self._scale_y)
            p.drawText(sel.x(), max(16, sel.y() - 8), f"{phys_w} x {phys_h}px")
        else:
            p.setPen(QColor(230, 237, 243))
            f = p.font()
            f.setPointSize(14)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignHCenter | Qt.AlignTop,
                       "\nDrag to select the image to detect  -  Esc to cancel")

    # -- input --------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._origin:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or not self._origin:
            return
        sel = QRect(self._origin, e.position().toPoint()).normalized()
        self.close()
        if sel.width() < 8 or sel.height() < 8:
            self.cancelled.emit()
            return

        # logical -> physical, clamped to the frame
        x = int(sel.x() * self._scale_x)
        y = int(sel.y() * self._scale_y)
        w = int(sel.width() * self._scale_x)
        h = int(sel.height() * self._scale_y)
        fh, fw = self._frame.shape[:2]
        x, y = max(0, x), max(0, y)
        w = min(w, fw - x)
        h = min(h, fh - y)

        template = self._frame[y:y + h, x:x + w].copy()
        region = {
            "left": self._desk["left"] + x,
            "top": self._desk["top"] + y,
            "width": w,
            "height": h,
        }
        self.picked.emit(region, template)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()

    def start(self) -> None:
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
