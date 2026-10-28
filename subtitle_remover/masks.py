"""Rasterizing text boxes into masks and soft alpha maps."""

from __future__ import annotations

import cv2
import numpy as np

from .config import MaskConfig
from .detect import TextBox


def box_pad(box: TextBox, cfg: MaskConfig) -> float:
    return max(cfg.pad_min, cfg.pad_ratio * box.h)


def rasterize(boxes: list[TextBox], size: tuple[int, int], cfg: MaskConfig,
              offset: tuple[float, float] = (0.0, 0.0),
              scale: float | tuple[float, float] = 1.0) -> np.ndarray:
    """uint8 mask (1 = remove) of shape `size` = (h, w).

    Boxes are given in full-frame pixels; `offset` is the top-left corner of the
    target area in full-frame pixels and `scale` maps full-frame to target pixels.
    """
    h, w = size
    mask = np.zeros((h, w), np.uint8)
    for b in boxes:
        fill_box(mask, b.points(box_pad(b, cfg), scale, offset))
    return mask


def fill_box(mask: np.ndarray, pts: np.ndarray) -> None:
    # One polygon per call: cv2.fillPoly with several polygons uses an even-odd
    # rule, so two overlapping boxes would cancel each other out.
    cv2.fillConvexPoly(mask, np.round(pts).astype(np.int32), 1)


def feather(mask: np.ndarray, radius: int) -> np.ndarray:
    """float32 alpha: 1 inside the mask, fading to 0 within ~2*radius outside."""
    m = mask.astype(np.float32)
    if radius <= 0 or not mask.any():
        return m
    k = 2 * radius + 1
    grown = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    soft = cv2.GaussianBlur(grown.astype(np.float32), (0, 0), sigmaX=radius / 2 + 0.5)
    return np.maximum(soft, m)
