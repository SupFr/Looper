"""Screen capture. Everything here works in PHYSICAL pixels.

Qt hands us logical pixels (DPI-scaled); mss and the Win32 cursor both speak
physical. The overlay converts once at selection time so every region stored in
a profile is already physical and nothing downstream has to think about DPI.
"""

from __future__ import annotations

import threading

import numpy as np
import mss


_local = threading.local()


def _sct() -> mss.base.MSSBase:
    """mss instances are not thread-safe; keep one per thread."""
    inst = getattr(_local, "sct", None)
    if inst is None:
        inst = mss.mss()
        _local.sct = inst
    return inst


def virtual_desktop() -> dict[str, int]:
    """Bounding box of every monitor combined, in physical px."""
    return dict(_sct().monitors[0])


def grab(region: dict[str, int]) -> np.ndarray:
    """Capture a region -> BGR uint8 array."""
    shot = _sct().grab(region)
    frame = np.asarray(shot, dtype=np.uint8)   # BGRA
    return frame[:, :, :3]


def grab_virtual() -> np.ndarray:
    return grab(virtual_desktop())
