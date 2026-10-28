"""Split the work into inpainting jobs.

A job is one cropped region (ROI) over a frame range inside one scene. Only
the area around the text is inpainted, which keeps GPU memory low and lets the
rest of the frame stay untouched at full resolution.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from .config import InpaintConfig, MaskConfig
from .detect import TextBox
from .masks import box_pad, fill_box

_UNION_SCALE = 0.25  # resolution of the union mask used to find text bands


@dataclass
class Job:
    id: int
    start: int  # first frame (inclusive)
    end: int  # last frame (exclusive)
    roi: tuple[int, int, int, int]  # x0, y0, x1, y1 in full-frame pixels
    proc_w: int  # processing size (multiple of 8)
    proc_h: int

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def roi_w(self) -> int:
        return self.roi[2] - self.roi[0]

    @property
    def roi_h(self) -> int:
        return self.roi[3] - self.roi[1]

    @property
    def scale(self) -> tuple[float, float]:
        return self.proc_w / self.roi_w, self.proc_h / self.roi_h

    def owns(self, box: TextBox) -> bool:
        x0, y0, x1, y1 = self.roi
        return x0 <= box.cx < x1 and y0 <= box.cy < y1

    def to_dict(self) -> dict:
        return asdict(self)


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index ranges where flags is True."""
    idx = np.flatnonzero(np.diff(np.concatenate([[0], flags.astype(np.int8), [0]])))
    return list(zip(idx[0::2], idx[1::2]))


def _merge_overlapping(rects: list[list[int]]) -> list[list[int]]:
    rects = [r[:] for r in rects]
    merged = True
    while merged:
        merged = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    rects[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del rects[j]
                    merged = True
                    break
            if merged:
                break
    return rects


def _scene_rois(schedule: list[list[TextBox]], start: int, end: int, width: int, height: int,
                mcfg: MaskConfig, icfg: InpaintConfig) -> list[list[int]]:
    s = _UNION_SCALE
    uh, uw = max(1, round(height * s)), max(1, round(width * s))
    union = np.zeros((uh, uw), np.uint8)
    for f in range(start, end):
        for b in schedule[f]:
            fill_box(union, b.points(box_pad(b, mcfg), s))
    if not union.any():
        return []

    # Horizontal bands of text; bands separated by a small gap belong together
    bands = _runs(union.any(axis=1))
    gap = icfg.roi_merge_gap * uh
    joined = [list(bands[0])]
    for a, b in bands[1:]:
        if a - joined[-1][1] <= gap:
            joined[-1][1] = b
        else:
            joined.append([a, b])

    rects = []
    for a, b in joined:
        cols = np.flatnonzero(union[a:b].any(axis=0))
        x0, x1 = cols[0] / s, (cols[-1] + 1) / s
        y0, y1 = a / s, b / s
        margin = max(icfg.roi_margin_min, icfg.roi_margin * (y1 - y0))
        rects.append([max(0, math.floor(x0 - margin)), max(0, math.floor(y0 - margin)),
                      min(width, math.ceil(x1 + margin)), min(height, math.ceil(y1 + margin))])
    return _merge_overlapping(rects)


def _proc_size(roi_w: int, roi_h: int, max_pixels: int) -> tuple[int, int]:
    s = min(1.0, math.sqrt(max_pixels / (roi_w * roi_h)))
    return max(64, round(roi_w * s / 8) * 8), max(64, round(roi_h * s / 8) * 8)


def plan_jobs(schedule: list[list[TextBox]], scenes: list[tuple[int, int]], width: int, height: int,
              mcfg: MaskConfig, icfg: InpaintConfig) -> list[Job]:
    jobs: list[Job] = []
    for start, end in scenes:
        for x0, y0, x1, y1 in _scene_rois(schedule, start, end, width, height, mcfg, icfg):
            active = [f for f in range(start, end)
                      if any(x0 <= b.cx < x1 and y0 <= b.cy < y1 for b in schedule[f])]
            if not active:
                continue
            f0 = max(start, active[0] - icfg.context_frames)
            f1 = min(end, active[-1] + 1 + icfg.context_frames)
            pw, ph = _proc_size(x1 - x0, y1 - y0, icfg.max_pixels)
            jobs.append(Job(id=len(jobs), start=f0, end=f1, roi=(x0, y0, x1, y1), proc_w=pw, proc_h=ph))
    return jobs
