import numpy as np
import pytest

from subtitle_remover.config import InpaintConfig, MaskConfig, parse_region
from subtitle_remover.detect import TextBox, rect_to_box
from subtitle_remover.masks import feather, rasterize
from subtitle_remover.pipeline import chunk_ranges
from subtitle_remover.planner import plan_jobs


def box(cx, cy, w=400, h=40):
    return TextBox(cx, cy, w, h, 0.0, 0.9)


@pytest.mark.parametrize("n,chunk,overlap", [(10, 120, 12), (121, 120, 12), (500, 120, 12), (1800, 90, 10)])
def test_chunk_ranges_cover_everything_with_overlap(n, chunk, overlap):
    ranges = chunk_ranges(n, chunk, overlap)
    assert ranges[0][0] == 0 and ranges[-1][1] == n
    assert all(e - s <= chunk for s, e in ranges)
    for (s0, e0), (s1, e1) in zip(ranges, ranges[1:]):
        assert e0 - s1 == overlap


def test_rect_to_box_normalizes_orientation():
    b = rect_to_box(((100, 50), (20, 300), 90.0), 0.9)  # OpenCV may report horizontal text like this
    assert (b.w, b.h) == (300, 20) and abs(b.angle) < 1e-6
    assert abs(rect_to_box(((0, 0), (300, 20), -89.0), 0.9).angle - (-89.0)) < 1e-6


def test_rasterize_offset_scale_and_feather():
    cfg = MaskConfig(pad_ratio=0.0, pad_min=0.0)
    m = rasterize([box(100, 100, w=40, h=20)], (100, 200), cfg, offset=(50, 50), scale=1.0)
    ys, xs = np.nonzero(m)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (30, 70, 40, 60)
    half = rasterize([box(100, 100, w=40, h=20)], (50, 100), cfg, offset=(50, 50), scale=0.5)
    assert half.sum() == pytest.approx(m.sum() / 4, rel=0.2)
    a = feather(m, 3)
    assert a.max() == 1.0 and (a[m.astype(bool)] == 1.0).all()
    assert 0 < a[50, 75] < 1  # soft edge just outside the box
    assert a[0, 0] == 0


def test_plan_jobs_splits_far_apart_bands_and_respects_scenes():
    n = 100
    schedule = [[box(540, 150), box(540, 1700)] if 10 <= f < 90 else [] for f in range(n)]
    icfg = InpaintConfig(context_frames=5, max_pixels=200_000)
    jobs = plan_jobs(schedule, [(0, 50), (50, 100)], 1080, 1920, MaskConfig(), icfg)
    assert len(jobs) == 4  # 2 bands x 2 scenes
    for j in jobs:
        assert j.proc_w % 8 == 0 and j.proc_h % 8 == 0
        assert j.proc_w * j.proc_h <= icfg.max_pixels * 1.1
        assert j.start in (5, 50) and j.end in (50, 95)
    top = [j for j in jobs if j.roi[1] < 960]
    assert all(j.owns(box(540, 150)) and not j.owns(box(540, 1700)) for j in top)


def test_plan_jobs_merges_close_lines():
    schedule = [[box(540, 1500), box(540, 1560)] for _ in range(30)]
    jobs = plan_jobs(schedule, [(0, 30)], 1080, 1920, MaskConfig(), InpaintConfig())
    assert len(jobs) == 1


def test_parse_region():
    assert parse_region("bottom") == [(0.0, 0.5, 1.0, 1.0)]
    assert parse_region("0, 0.6, 1, 1") == [(0.0, 0.6, 1.0, 1.0)]
    with pytest.raises(ValueError):
        parse_region("0,0.6,1")
    with pytest.raises(ValueError):
        parse_region("0.5,0.6,0.2,1")


class _FakeInpainter:
    """Fills with a per-call constant and fails like CUDA when given too many frames."""

    def __init__(self, limit):
        self.limit, self.sizes = limit, []

    def inpaint(self, frames, masks):
        if len(frames) > self.limit:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        self.sizes.append(len(frames))
        return np.full_like(frames, 100 + 10 * (len(self.sizes) % 2))


def test_inpaint_chunked_crossfades_and_retries_on_oom():
    from subtitle_remover.pipeline import inpaint_chunked

    frames = np.zeros((100, 4, 4, 3), np.uint8)
    masks = np.ones((100, 4, 4), np.uint8)
    out = np.zeros_like(frames)
    fake = _FakeInpainter(limit=40)
    inpaint_chunked(fake, frames, masks, out, chunk=120, overlap=12)
    assert max(fake.sizes) <= 40
    assert out.min() >= 100 and out.max() <= 110  # every frame filled, overlaps blended in between
    assert len(np.unique(out[:, 0, 0, 0])) > 2


def test_inpaint_chunked_gives_up_with_a_hint():
    from subtitle_remover.pipeline import inpaint_chunked

    frames = np.zeros((100, 4, 4, 3), np.uint8)
    with pytest.raises(RuntimeError, match="GPU 메모리"):
        inpaint_chunked(_FakeInpainter(limit=10), frames, np.ones((100, 4, 4), np.uint8),
                        np.zeros_like(frames), chunk=120, overlap=12)


def test_overlapping_boxes_do_not_cancel_out():
    cfg = MaskConfig()
    one = rasterize([box(100, 100)], (200, 600), cfg)
    two = rasterize([box(100, 100), box(101, 100)], (200, 600), cfg)
    assert two.sum() >= one.sum() > 0
    assert (two[one.astype(bool)] == 1).all()
