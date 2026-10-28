"""Turn per-frame text detections into a per-frame mask schedule.

Detections are linked over time into tracks. A track is one piece of on-screen
text (a subtitle line, a title, a caption). Tracks are then classified:
overlay text (subtitles etc.) stays horizontal and does not drift with the
camera, while scene text (signs, labels) moves with the picture. The kept
tracks are expanded in time to cover fade-in/out frames the detector missed.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from .config import FilterConfig, Region
from .detect import TextBox


@dataclass
class Track:
    id: int
    frames: list[int] = field(default_factory=list)  # frames with a detection
    boxes: list[TextBox] = field(default_factory=list)
    keep: bool = False
    reason: str = ""

    @property
    def first(self) -> int:
        return self.frames[0]

    @property
    def last(self) -> int:
        return self.frames[-1]

    def summary(self) -> dict:
        b = self.boxes[len(self.boxes) // 2]
        return {"id": self.id, "first": self.first, "last": self.last, "detections": len(self.frames),
                "keep": self.keep, "reason": self.reason, "box": b.to_dict()}


def in_regions(box: TextBox, regions: list[Region], width: int, height: int) -> bool:
    if not regions:
        return True
    x, y = box.cx / width, box.cy / height
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in regions)


def _match_score(a: TextBox, b: TextBox) -> float:
    """Similarity of two boxes in consecutive detections; 0 means no match.

    Text lines must overlap strongly in their vertical extent. Horizontally
    they only need to touch, because a subtitle that switches to the next
    sentence keeps its line position but changes its width.
    """
    ax0, ay0, ax1, ay1 = a.bbox
    bx0, by0, bx1, by1 = b.bbox
    y_inter = min(ay1, by1) - max(ay0, by0)
    x_inter = min(ax1, bx1) - max(ax0, bx0)
    if y_inter <= 0 or x_inter <= 0:
        return 0.0
    y_iou = y_inter / (max(ay1, by1) - min(ay0, by0))
    if y_iou < 0.5:
        return 0.0
    return y_iou + x_inter / (max(ax1, bx1) - min(ax0, bx0))


def build_tracks(detections: dict[int, list[TextBox]], max_gap: int) -> list[Track]:
    tracks: list[Track] = []
    active: list[Track] = []
    for f in sorted(detections):
        active = [t for t in active if f - t.last <= max_gap]
        boxes = detections[f]
        pairs = sorted(((_match_score(t.boxes[-1], b), ti, bi)
                        for ti, t in enumerate(active) for bi, b in enumerate(boxes)), reverse=True)
        used_t, used_b = set(), set()
        for score, ti, bi in pairs:
            if score <= 0:
                break
            if ti in used_t or bi in used_b:
                continue
            used_t.add(ti)
            used_b.add(bi)
            active[ti].frames.append(f)
            active[ti].boxes.append(boxes[bi])
        for bi, b in enumerate(boxes):
            if bi not in used_b:
                t = Track(id=len(tracks), frames=[f], boxes=[b])
                tracks.append(t)
                active.append(t)
    return tracks


def _spread(values: np.ndarray, scale: float) -> float:
    """Robust spread of a position series in units of `scale`."""
    if len(values) < 3:
        return 0.0
    return float(np.percentile(np.abs(values - np.median(values)), 80) / max(scale, 1.0))


def classify_tracks(tracks: list[Track], cfg: FilterConfig, fps: float) -> None:
    min_frames = max(1, round(cfg.min_duration * fps))
    for t in tracks:
        t.keep, t.reason = False, ""
        if t.last - t.first + 1 < min_frames:
            t.reason = "too short"
            continue
        if cfg.target == "all":
            t.keep, t.reason = True, "text"
            continue
        angles = np.array([abs(b.angle) for b in t.boxes])
        if np.median(angles) > cfg.max_angle:
            t.reason = "tilted"
            continue
        h = float(np.median([b.h for b in t.boxes]))
        cy = np.array([b.cy for b in t.boxes])
        x0 = np.array([b.bbox[0] for b in t.boxes])
        x1 = np.array([b.bbox[2] for b in t.boxes])
        cx = (x0 + x1) / 2
        spread_y = _spread(cy, h)
        # Left-, right- or center-aligned text keeps at least one edge in place
        spread_x = min(_spread(x0, h), _spread(x1, h), _spread(cx, h))
        if max(spread_x, spread_y) > cfg.max_spread:
            t.reason = f"moving ({max(spread_x, spread_y):.2f})"
            continue
        t.keep, t.reason = True, "overlay"


def build_schedule(tracks: list[Track], n_frames: int, fps: float, cfg: FilterConfig,
                   det_every: int) -> list[list[TextBox]]:
    """For every frame, the text boxes that must be removed in it."""
    schedule: list[list[TextBox]] = [[] for _ in range(n_frames)]
    pad_before = round(cfg.pad_before * fps)
    pad_after = round(cfg.pad_after * fps)
    window = max(1, det_every)
    for t in tracks:
        if not t.keep:
            continue
        frames = t.frames
        for f in range(max(0, t.first - pad_before), min(n_frames, t.last + pad_after + 1)):
            lo = bisect.bisect_left(frames, f - window)
            hi = bisect.bisect_right(frames, f + window)
            if lo < hi:
                # union of nearby detections smooths frame-to-frame size jitter
                chosen = t.boxes[lo:hi]
            else:
                # inside a detection gap or in the fade padding: use both neighbours
                i = bisect.bisect_left(frames, f)
                chosen = t.boxes[max(0, i - 1):i + 1]
            schedule[f].extend(chosen)
    return schedule
