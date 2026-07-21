"""Template matching.

Normalised cross-correlation over a single scale. The search region is user
picked and small, so this stays cheap enough to poll a few times a second
without touching the CPU budget of the game.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class MatchResult:
    found: bool
    confidence: float
    center: tuple[int, int] | None   # absolute physical screen coords


class TemplateCache:
    """Templates are read once and reused every poll."""

    def __init__(self) -> None:
        self._cache: dict[str, np.ndarray] = {}

    def get(self, path: str, grayscale: bool) -> np.ndarray | None:
        key = f"{path}|{int(grayscale)}"
        if key in self._cache:
            return self._cache[key]

        p = Path(path)
        if not p.is_file():
            return None
        # imdecode handles non-ASCII paths that cv2.imread chokes on.
        raw = np.fromfile(str(p), dtype=np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if img is None:
            return None
        if grayscale:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self._cache[key] = img
        return img

    def clear(self) -> None:
        self._cache.clear()


def find(frame: np.ndarray, template: np.ndarray, threshold: float,
         origin: tuple[int, int], grayscale: bool,
         scales: tuple[float, ...] = (1.0,)) -> MatchResult:
    """Locate `template` inside `frame`. `origin` is the frame's screen offset.

    `scales` resizes the template before matching -- pass a sweep like
    (0.9, 1.0, 1.1) so a template captured at one screen resolution still
    matches at another. Best scale wins.
    """
    if grayscale and frame.ndim == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    fh, fw = frame.shape[:2]
    best_val = -1.0
    best_loc = None
    best_tw = best_th = 0
    for sc in scales:
        if sc == 1.0:
            tpl = template
        else:
            th0, tw0 = template.shape[:2]
            nw, nh = max(1, round(tw0 * sc)), max(1, round(th0 * sc))
            interp = cv2.INTER_AREA if sc < 1.0 else cv2.INTER_LINEAR
            tpl = cv2.resize(template, (nw, nh), interpolation=interp)
        th, tw = tpl.shape[:2]
        if th > fh or tw > fw:
            continue
        res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_val:
            best_val, best_loc, best_tw, best_th = max_val, max_loc, tw, th

    if best_loc is None or best_val < threshold:
        return MatchResult(False, float(max(best_val, 0.0)), None)

    max_loc, tw, th = best_loc, best_tw, best_th
    max_val = best_val
    cx = origin[0] + max_loc[0] + tw // 2
    cy = origin[1] + max_loc[1] + th // 2
    return MatchResult(True, float(max_val), (cx, cy))


def save_png(path: str, image: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", image)
    if ok:
        buf.tofile(path)
