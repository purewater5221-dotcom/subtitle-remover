import json
import sys
from pathlib import Path

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
    src_info, out_info = probe(synthetic_clip / "clip.mp4"), probe(out)
    assert (out_info.width, out_info.height, out_info.fps) == (src_info.width, src_info.height, src_info.fps)
    assert out_info.has_audio
    clean, gt = synthetic_clip / "clip_clean.mp4", synthetic_clip / "clip_gt.npz"
    before = evaluate(str(synthetic_clip / "clip.mp4"), str(clean), str(gt))
    after = evaluate(str(out), str(clean), str(gt))
    assert after["psnr_text_area"] > before["psnr_text_area"] + 5
    assert after["psnr_elsewhere"] > 35

