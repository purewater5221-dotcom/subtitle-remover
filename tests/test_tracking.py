from subtitle_remover.config import FilterConfig
from subtitle_remover.detect import TextBox
from subtitle_remover.tracking import build_schedule, build_tracks, classify_tracks, in_regions

FPS = 30.0


def box(cx, cy, w=200, h=30, angle=0.0):
    return TextBox(cx, cy, w, h, angle, 0.9)


def run(dets, cfg=None, every=1, n=None):
    cfg = cfg or FilterConfig()
    tracks = build_tracks(dets, max_gap=round(cfg.max_gap * FPS))
    classify_tracks(tracks, cfg, FPS)
    n = n or (max(dets) + 1)
    return tracks, build_schedule(tracks, n, FPS, cfg, every)


def test_subtitle_changing_sentences_is_one_kept_track():
    # centered subtitle line whose width changes with every sentence
    dets = {f: [box(540, 1600, w=300 + 200 * ((f // 30) % 3))] for f in range(120)}
    tracks, schedule = run(dets)
    assert len(tracks) == 1
    assert tracks[0].keep and tracks[0].reason == "overlay"
    assert all(schedule[f] for f in range(120))


def test_text_moving_with_camera_is_dropped():
    dets = {f: [box(100 + 4 * f, 900)] for f in range(90)}
    tracks, schedule = run(dets)
    assert len(tracks) == 1
    assert not tracks[0].keep and tracks[0].reason.startswith("moving")
    assert not any(schedule)


def test_target_all_keeps_moving_text():
    dets = {f: [box(100 + 4 * f, 900)] for f in range(90)}
    tracks, _ = run(dets, FilterConfig(target="all"))
    assert tracks[0].keep


def test_tilted_and_short_tracks_are_dropped():
    dets = {f: [box(500, 500, angle=35.0)] for f in range(60)}
    dets.update({f: dets.get(f, []) + [box(300, 1500)] for f in range(60, 62)})
    tracks, _ = run(dets)
    reasons = sorted(t.reason for t in tracks)
    assert reasons == ["tilted", "too short"]


def test_schedule_pads_fades_and_fills_gaps():
    cfg = FilterConfig(pad_before=0.1, pad_after=0.1)
    frames = [f for f in range(20, 80) if not 40 <= f < 50]  # detector missed 10 frames
    dets = {f: [box(540, 1600)] for f in range(100)}
    for f in range(100):
        if f not in frames:
            dets[f] = []
    tracks, schedule = run(dets, cfg)
    assert len([t for t in tracks if t.keep]) == 1
    assert [f for f in range(100) if schedule[f]] == list(range(17, 83))


def test_two_lines_are_separate_tracks():
    dets = {f: [box(540, 1500), box(540, 1550)] for f in range(60)}
    tracks, _ = run(dets)
    assert len(tracks) == 2 and all(t.keep for t in tracks)


def test_regions():
    b = box(540, 1700)
    assert in_regions(b, [], 1080, 1920)
    assert in_regions(b, [(0, 0.5, 1, 1)], 1080, 1920)
    assert not in_regions(b, [(0, 0, 1, 0.5)], 1080, 1920)
