import json
import logging
import sys
from pathlib import Path

import pytest

from subtitle_remover.config import Config
from subtitle_remover.pipeline import SubtitleRemover
from subtitle_remover.video_io import probe

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from evaluate import evaluate  # noqa: E402


def test_detect_only_finds_subtitles_and_title_but_not_the_sign(synthetic_clip, tmp_path):
    remover = SubtitleRemover(Config())
    r = remover.process(synthetic_clip / "clip.mp4", tmp_path / "clip_clean.mp4", detect_only=True)
    assert r.output is None and r.preview.exists()
    report = json.loads((tmp_path / "clip_clean_tracks.json").read_text())
    kept = [t for t in report["tracks"] if t["keep"]]
    ys = sorted(t["box"]["cy"] / report["size"][1] for t in kept)
    assert len(kept) == 2 and ys[0] < 0.2 and 0.75 < ys[1] < 0.9  # title + subtitle line
    sign = [t for t in report["tracks"] if 0.3 < t["box"]["cy"] / report["size"][1] < 0.45 and t["detections"] > 20]
    assert sign and not any(t["keep"] for t in sign)


def test_end_to_end_opencv(synthetic_clip, tmp_path):
    cfg = Config()
    cfg.inpaint.method = "opencv"
    out = tmp_path / "out.mp4"
    r = SubtitleRemover(cfg).process(synthetic_clip / "clip.mp4", out)
    assert r.removed == 2 and r.jobs == 2
    assert set(r.timings) == {"찾기", "메꾸기", "합치기"} and all(v >= 0 for v in r.timings.values())
    assert r.size == (180, 320) and abs(r.duration - 2) < 0.1
    src_info, out_info = probe(synthetic_clip / "clip.mp4"), probe(out)
    assert (out_info.width, out_info.height, out_info.fps) == (src_info.width, src_info.height, src_info.fps)
    assert out_info.has_audio
    clean, gt = synthetic_clip / "clip_clean.mp4", synthetic_clip / "clip_gt.npz"
    before = evaluate(str(synthetic_clip / "clip.mp4"), str(clean), str(gt))
    after = evaluate(str(out), str(clean), str(gt))
    assert after["psnr_text_area"] > before["psnr_text_area"] + 5
    assert after["psnr_elsewhere"] > 35



def test_cli_lists_the_time_each_video_took(synthetic_clip, tmp_path, caplog):
    from subtitle_remover import cli

    caplog.set_level(logging.INFO, logger="subtitle_remover")
    assert cli.main([str(synthetic_clip / "clip.mp4"), "-o", str(tmp_path / "out.mp4"), "--method", "opencv"]) == 0
    assert "⏱ 걸린 시간" in caplog.text and "clip.mp4 (180×320, 2초 영상) → " in caplog.text


def test_job_masks_are_made_per_chunk(synthetic_clip):
    from subtitle_remover.pipeline import _JobMasks

    remover = SubtitleRemover(Config())
    a = remover.analyze(synthetic_clip / "clip.mp4")
    job = a.jobs[0]
    lazy, full = _JobMasks(remover, a, job), remover.job_masks(a, job)
    assert len(lazy) == len(full) == job.length
    assert (lazy[5:17] == full[5:17]).all() and (lazy[0:job.length] == full).all()


def test_detection_skips_frames_once_the_gpu_falls_back_to_cpu(synthetic_clip):
    class FallsBack:  # stands in for TextDetector: the first batch runs on the GPU, then it switches to CPU
        device = "cuda"
        frames = 0

        def __call__(self, frames):
            self.frames += len(frames)
            self.device = "cpu"
            return [[] for _ in frames]

    remover = SubtitleRemover(Config())
    remover._detector = det = FallsBack()
    a = remover.analyze(synthetic_clip / "clip.mp4")
    batch = Config().detect.batch
    assert det.frames == batch + len([i for i in range(batch, a.n_frames) if i % 2 == 0])


def test_main_encoder_stops_when_the_preview_encoder_cannot_start(synthetic_clip, tmp_path, monkeypatch):
    from subtitle_remover import pipeline

    started = []

    class Recorded(pipeline.FrameWriter):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            started.append(self)

    class BrokenPreview:
        def __init__(self, *a, **k):
            raise OSError("cannot start the preview encoder")

    monkeypatch.setattr(pipeline, "FrameWriter", Recorded)
    monkeypatch.setattr(pipeline, "_PreviewWriter", BrokenPreview)
    cfg = Config()
    cfg.inpaint.method = "opencv"
    cfg.output.debug = True  # also writes the mask preview
    with pytest.raises(OSError):
        SubtitleRemover(cfg).process(synthetic_clip / "clip.mp4", tmp_path / "out.mp4")
    assert len(started) == 1 and started[0]._proc.poll() is not None  # no ffmpeg left waiting for frames
