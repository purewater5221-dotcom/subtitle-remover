"""Classic per-frame inpainting (OpenCV Telea). Fast, no GPU, low quality:
useful for checking masks and for testing the pipeline."""

from __future__ import annotations

import cv2
import numpy as np


class OpenCVInpainter:
    name = "opencv"

    def __init__(self, radius: int = 5):
        self.radius = radius

    def inpaint(self, frames: np.ndarray, masks: np.ndarray) -> np.ndarray:
        out = np.array(frames, copy=True)
        for i, (frame, mask) in enumerate(zip(frames, masks)):
            if mask.any():
                out[i] = cv2.inpaint(np.ascontiguousarray(frame), mask * 255, self.radius, cv2.INPAINT_TELEA)
        return out
