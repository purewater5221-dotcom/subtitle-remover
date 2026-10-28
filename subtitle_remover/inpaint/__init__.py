"""Inpainting backends.

Every backend takes BGR uint8 frames of shape (T, H, W, 3) and uint8 masks of
shape (T, H, W) (1 = fill in) and returns filled frames of the same shape.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from ..config import InpaintConfig


class Inpainter(Protocol):
    name: str

    def inpaint(self, frames: np.ndarray, masks: np.ndarray) -> np.ndarray: ...


def create_inpainter(cfg: InpaintConfig, device: str = "auto") -> Inpainter:
    if cfg.method == "opencv":
        from .opencv import OpenCVInpainter

        return OpenCVInpainter()
    if cfg.method == "propainter":
        from .propainter import ProPainterInpainter

        return ProPainterInpainter(cfg, device)
    raise ValueError(f"알 수 없는 지우기 방식: {cfg.method} (propainter, opencv 중 선택)")
