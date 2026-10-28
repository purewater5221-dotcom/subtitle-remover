"""Compare a processed clip with its ground truth (see make_synthetic.py).

Reports PSNR inside the subtitle area (how well it was filled), outside it
(how much the rest of the frame was disturbed) and a flicker score: the mean
frame-to-frame change of the error inside the subtitle area (lower = steadier).

usage: python tools/evaluate.py RESULT.mp4 CLEAN.mp4 GT.npz [--subtitled ORIGINAL.mp4]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subtitle_remover.video_io import probe, read_frames  # noqa: E402


def psnr(err_sq_sum: float, count: int) -> float:
    if count == 0:
        return float("nan")
    mse = err_sq_sum / count
    return float("inf") if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def evaluate(result: str, clean: str, gt_path: str) -> dict:
    gt = np.load(gt_path)["mask"]
    near = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    far = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))
    sums = {"in": [0.0, 0], "out": [0.0, 0]}
    flicker, prev_err = [], None
    for i, (a, b) in enumerate(zip(read_frames(probe(result)), read_frames(probe(clean)))):
        if i >= len(gt):
            break
        m = cv2.dilate(gt[i], near).astype(bool)  # where text was drawn
        o = ~cv2.dilate(gt[i], far).astype(bool)  # well away from any text
        err = a.astype(np.float32) - b.astype(np.float32)
        sq = (err ** 2).sum(axis=2)
        sums["in"][0] += float(sq[m].sum()); sums["in"][1] += int(m.sum()) * 3
        sums["out"][0] += float(sq[o].sum()); sums["out"][1] += int(o.sum()) * 3
        if prev_err is not None and m.any():
            flicker.append(float(np.abs(err - prev_err)[m].mean()))
        prev_err = err
    return {"psnr_text_area": psnr(*sums["in"]), "psnr_elsewhere": psnr(*sums["out"]),
            "flicker": float(np.mean(flicker)) if flicker else float("nan")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("clean")
    ap.add_argument("gt")
    ap.add_argument("--subtitled", help="also score the unprocessed input as a baseline")
    a = ap.parse_args()
    if a.subtitled:
        print("input   ", {k: round(v, 2) for k, v in evaluate(a.subtitled, a.clean, a.gt).items()})
    print("result  ", {k: round(v, 2) for k, v in evaluate(a.result, a.clean, a.gt).items()})


if __name__ == "__main__":
    main()
