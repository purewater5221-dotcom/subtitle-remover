"""Make synthetic test clips with known ground truth.

Writes, for each clip:
  <name>_clean.mp4       background only (ground truth)
  <name>.mp4             background + burned-in subtitles and a title (+ test tone)
  <name>_gt.npz          per-frame subtitle mask (where text was drawn)

The background is a procedural texture; with --motion pan the "camera" pans
across it (the area behind subtitles becomes visible in other frames), with
--motion static it does not (the area must be hallucinated). A sign painted on
the background moves with the scene and must NOT be removed in overlay mode.

usage: python tools/make_synthetic.py OUT_DIR [--motion pan|static] [--seconds 4] [--size 360x640]
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SENTENCES = ["Hello everyone, welcome back", "Today we cook something simple",
             "First, slice the onions thinly", "Then fry them until golden",
             "Add a pinch of salt", "And that's it, enjoy!"]


def texture(h: int, w: int, rng: np.random.Generator) -> np.ndarray:
    img = np.zeros((h, w, 3), np.float32)
    for octave in range(5):  # fractal color noise
        s = 2 ** octave
        noise = rng.random((max(2, h // (64 // s)), max(2, w // (64 // s)), 3)).astype(np.float32)
        img += cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC) / s
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    for _ in range(w * h // 9000):  # shapes with hard edges give the flow something to track
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        if rng.random() < 0.5:
            cv2.circle(img, (x, y), int(rng.integers(4, 30)), color, -1, cv2.LINE_AA)
        else:
            cv2.rectangle(img, (x, y), (x + int(rng.integers(8, 60)), y + int(rng.integers(8, 60))), color, -1)
    img = img.clip(0, 255).astype(np.uint8)
    # a sign that belongs to the scene
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    fs = max(12, h // 12)
    d.rectangle((w // 3, h // 3, w // 3 + fs * 4, h // 3 + int(fs * 1.6)), fill=(30, 60, 120))
    d.text((w // 3 + fs // 3, h // 3 + fs // 4), "SHOP", font=ImageFont.truetype(FONT, fs), fill=(255, 255, 255))
    return np.array(pil)


def draw_text(img: Image.Image, mask: Image.Image, text: str, xy, size: int, fill, stroke: int):
    font = ImageFont.truetype(FONT, size)
    while size > 8 and font.getlength(text) > 0.9 * img.width:  # shrink to fit the frame width
        size -= 1
        font = ImageFont.truetype(FONT, size)
    for target, f, s in ((img, fill, (0, 0, 0)), (mask, 255, 255)):
        ImageDraw.Draw(target).text(xy, text, font=font, fill=f, anchor="mm", stroke_width=stroke, stroke_fill=s)


def make_clip(out_dir: Path, name: str, motion: str, seconds: float, w: int, h: int, fps: int, seed: int):
    rng = np.random.default_rng(seed)
    n = int(seconds * fps)
    speed = 3 if motion == "pan" else 0
    bg = texture(h, w + speed * n + 1, rng)
    sub_size, title_size = max(12, h // 24), max(14, h // 14)
    per = max(1, int(1.2 * fps))

    def encode(path: Path, audio: bool):
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
               "-r", str(fps), "-i", "-"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
        cmd += ["-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)]
        return subprocess.Popen(cmd, stdin=subprocess.PIPE)

    clean_p = encode(out_dir / f"{name}_clean.mp4", False)
    sub_p = encode(out_dir / f"{name}.mp4", True)
    gt = np.zeros((n, h, w), np.uint8)
    for i in range(n):
        x = i * speed
        frame = np.ascontiguousarray(bg[:, x:x + w])
        clean_p.stdin.write(frame.tobytes())
        img, mask = Image.fromarray(frame), Image.new("L", (w, h), 0)
        draw_text(img, mask, "MY VLOG", (w // 2, int(h * 0.12)), title_size, (255, 225, 0), 3)
        k = i // per
        if k < len(SENTENCES):
            draw_text(img, mask, SENTENCES[k], (w // 2, int(h * 0.82)), sub_size, (255, 255, 255), 2)
        gt[i] = (np.array(mask) > 0).astype(np.uint8)
        sub_p.stdin.write(np.array(img).tobytes())
    for p in (clean_p, sub_p):
        p.stdin.close()
        p.wait()
    np.savez_compressed(out_dir / f"{name}_gt.npz", mask=gt)
    print(f"{name}: {n} frames {w}x{h} ({motion})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--motion", default="pan", choices=["pan", "static"])
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--size", default="360x640")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name")
    a = ap.parse_args()
    w, h = (int(v) for v in a.size.split("x"))
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    make_clip(out, a.name or f"synth_{a.motion}", a.motion, a.seconds, w, h, a.fps, a.seed)


if __name__ == "__main__":
    main()
