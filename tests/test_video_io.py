import subprocess
from fractions import Fraction

import numpy as np
import pytest

from subtitle_remover.video_io import FrameWriter, probe, read_frames


def make_clip(path, extra_v=(), size="96x64", rate="30", seconds=1, audio=True):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=duration={seconds}", "-c:a", "aac"]
    cmd += [*extra_v, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10", str(path)]
    subprocess.run(cmd, check=True)


def test_probe_and_read(tmp_path):
    p = tmp_path / "a.mp4"
    make_clip(p)
    info = probe(p)
    assert (info.width, info.height, info.fps, info.has_audio) == (96, 64, Fraction(30), True)
    frames = list(read_frames(info))
    assert len(frames) == 30 and frames[0].shape == (64, 96, 3)


def test_ntsc_rate_is_kept(tmp_path):
    p = tmp_path / "ntsc.mp4"
    make_clip(p, rate="30000/1001", audio=False)
    assert probe(p).fps == Fraction(30000, 1001)


def test_rotation_metadata_swaps_size(tmp_path):
    plain, rotated = tmp_path / "plain.mp4", tmp_path / "rot.mp4"
    make_clip(plain, audio=False)
    res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90", "-i", str(plain),
                          "-c", "copy", str(rotated)], capture_output=True)
    if res.returncode != 0:
        pytest.skip("this ffmpeg cannot write display rotation")
    info = probe(rotated)
    assert (info.width, info.height) == (64, 96)
    assert next(iter(read_frames(info))).shape == (96, 64, 3)


def test_roundtrip_keeps_audio_and_frame_count(tmp_path):
    src = tmp_path / "src.mp4"
    make_clip(src)
    info = probe(src)
    dst = tmp_path / "dst.mp4"
    frames = list(read_frames(info))
    with FrameWriter(dst, info.width, info.height, info.fps, info.color_space, info, crf=10) as w:
        for f in frames:
            w.write(f)
    out_info = probe(dst)
    assert out_info.has_audio and out_info.fps == info.fps
    assert len(list(read_frames(out_info))) == len(frames)


def test_roundtrip_has_no_color_shift(tmp_path):
    # smooth, natural-looking colors (saturated test patterns lose chroma to 4:2:0 regardless)
    yy, xx = np.mgrid[0:64, 0:96].astype(np.float32)
    rng = np.random.default_rng(0)
    frames = []
    for t in range(5):
        img = np.stack([60 + xx + t, 90 + yy * 1.5, 160 - xx * 0.5 + yy * 0.3], axis=-1)
        frames.append(np.clip(img + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8))
    p = tmp_path / "smooth.mp4"
    with FrameWriter(p, 96, 64, Fraction(30), None, None, crf=0) as w:
        for f in frames:
            w.write(f)
    back = list(read_frames(probe(p)))
    diff = np.mean([b.astype(np.float32) - f for b, f in zip(back, frames)], axis=(0, 1, 2))
    assert np.abs(diff).max() < 0.5, diff


def test_gray_roundtrip_exact(tmp_path):
    gray = np.full((64, 64, 3), 128, np.uint8)
    p = tmp_path / "g.mp4"
    with FrameWriter(p, 64, 64, Fraction(30), None, None, crf=0) as w:
        for _ in range(3):
            w.write(gray)
    back = next(iter(read_frames(probe(p))))
    assert np.abs(back.astype(int) - 128).max() <= 1
