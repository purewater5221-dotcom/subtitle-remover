"""Hard-cut detection, so inpainting never borrows pixels across a cut."""

from __future__ import annotations

import cv2
import numpy as np


class SceneDetector:
    """Content-change detector in the spirit of PySceneDetect's ContentDetector:
    a cut is the mean absolute change of the HSV channels between consecutive
    (downscaled) frames exceeding a threshold."""

    def __init__(self, threshold: float = 27.0, min_len: int = 10, width: int = 128):
        self.threshold = threshold
        self.min_len = min_len
        self.width = width
        self.cuts: list[int] = []
        self.scores: list[float] = []
        self._prev: np.ndarray | None = None
        self._last_cut = 0

    def update(self, idx: int, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (self.width, max(1, round(h * self.width / w))), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.int16)
        if self._prev is not None:
            score = float(np.abs(hsv - self._prev).mean())
            self.scores.append(score)
            if score >= self.threshold and idx - self._last_cut >= self.min_len:
                self.cuts.append(idx)
                self._last_cut = idx
        self._prev = hsv

    def scenes(self, n_frames: int) -> list[tuple[int, int]]:
        bounds = [0] + [c for c in self.cuts if 0 < c < n_frames] + [n_frames]
        return [(a, b) for a, b in zip(bounds[:-1], bounds[1:]) if b > a]
