"""ProPainter video inpainting (ICCV 2023, https://github.com/sczhou/ProPainter).

ProPainter is not vendored: its code is cloned at a pinned commit into a cache
directory on first use and its weights are downloaded from the official
GitHub release. ProPainter is licensed for non-commercial use only (NTU S-Lab
License 1.0).

The inference below follows ProPainter's `inference_propainter.py`, but works
on in-memory frames and masks instead of files.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import cv2
import numpy as np

from ..config import InpaintConfig

log = logging.getLogger(__name__)

REPO_URL = "https://github.com/sczhou/ProPainter.git"
REPO_COMMIT = "326782529a63d997cab80ab21439b92ed422b3d3"
REPO_ZIP_URL = f"https://github.com/sczhou/ProPainter/archive/{REPO_COMMIT}.zip"
WEIGHTS_URL = "https://github.com/sczhou/ProPainter/releases/download/v0.1.0/"
WEIGHTS = ("raft-things.pth", "recurrent_flow_completion.pth", "ProPainter.pth")
MIN_FRAMES = 3


def cache_dir() -> Path:
    return Path(os.environ.get("SUBTITLE_REMOVER_CACHE", Path.home() / ".cache" / "subtitle_remover"))


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("다운로드 중: %s", url)
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)


def _fetch_code(root: Path) -> None:
    if shutil.which("git"):
        try:
            subprocess.run(["git", "clone", "-q", REPO_URL, str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "checkout", "-q", REPO_COMMIT], check=True)
            return
        except subprocess.CalledProcessError:
            shutil.rmtree(root, ignore_errors=True)
    # No git (typical on Windows): download the source archive of the same commit
    archive = root.parent / f"{root.name}.zip"
    _download(REPO_ZIP_URL, archive)
    with zipfile.ZipFile(archive) as z:
        top = z.namelist()[0].split("/")[0]
        z.extractall(root.parent)
    (root.parent / top).rename(root)
    archive.unlink()


def ensure_propainter(root: Path | None = None) -> Path:
    """Fetch ProPainter (pinned commit) and its weights if missing."""
    root = Path(root) if root else cache_dir() / "ProPainter"
    if not (root / "model" / "propainter.py").exists():
        if root.exists() and any(p.name != "weights" for p in root.iterdir()):
            raise RuntimeError(f"ProPainter 폴더가 손상된 것 같아요. 이 폴더를 지우고 다시 실행해 주세요: {root}")
        shutil.rmtree(root, ignore_errors=True)  # at most leftover weights from an interrupted setup
        root.parent.mkdir(parents=True, exist_ok=True)
        log.info("ProPainter 코드를 받는 중...")
        _fetch_code(root)
    for name in WEIGHTS:
        path = root / "weights" / name
        if not path.exists():
            _download(WEIGHTS_URL + name, path)
    return root


@contextlib.contextmanager
def _compatible_torch_load():
    """ProPainter calls torch.load() without weights_only. Newer PyTorch
    defaults to weights_only=True; if a checkpoint needs more than that, retry
    the official release checkpoint with weights_only=False."""
    import torch

    original = torch.load

    def load(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except Exception as e:
            if "weights_only" not in str(e) or "weights_only" in kwargs:
                raise
            return original(*args, **kwargs, weights_only=False)

    torch.load = load
    try:
        yield
    finally:
        torch.load = original


def _dilate(masks: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return masks
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    return np.stack([cv2.dilate(m, k) for m in masks])


def _ref_index(mid: int, neighbor_ids: list[int], length: int, ref_stride: int, ref_num: int) -> list[int]:
    if ref_num == -1:
        return [i for i in range(0, length, ref_stride) if i not in neighbor_ids]
    refs: list[int] = []
    start = max(0, mid - ref_stride * (ref_num // 2))
    end = min(length, mid + ref_stride * (ref_num // 2))
    for i in range(start, end, ref_stride):
        if i not in neighbor_ids:
            if len(refs) > ref_num:
                break
            refs.append(i)
    return refs


class ProPainterInpainter:
    name = "propainter"

    def __init__(self, cfg: InpaintConfig, device: str = "auto", root: Path | None = None):
        import torch

        self.cfg = cfg
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        if self.device.type == "cpu":
            log.warning("GPU가 없어 CPU로 ProPainter를 실행합니다. 매우 느릴 수 있어요.")
        self.half = cfg.fp16 and self.device.type == "cuda"

        root = ensure_propainter(root)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from model.modules.flow_comp_raft import RAFT_bi
        from model.propainter import InpaintGenerator
        from model.recurrent_flow_completion import RecurrentFlowCompleteNet

        weights = root / "weights"
        with _compatible_torch_load():
            self._build(RAFT_bi, RecurrentFlowCompleteNet, InpaintGenerator, weights)

    def _build(self, RAFT_bi, RecurrentFlowCompleteNet, InpaintGenerator, weights: Path) -> None:
        self.raft = RAFT_bi(str(weights / "raft-things.pth"), self.device)
        self.flow_complete = RecurrentFlowCompleteNet(str(weights / "recurrent_flow_completion.pth"))
        for p in self.flow_complete.parameters():
            p.requires_grad = False
        self.flow_complete.to(self.device).eval()
        self.model = InpaintGenerator(model_path=str(weights / "ProPainter.pth")).to(self.device).eval()
        if self.half:
            self.flow_complete = self.flow_complete.half()
            self.model = self.model.half()

    def inpaint(self, frames: np.ndarray, masks: np.ndarray) -> np.ndarray:
        n = len(frames)
        if n < MIN_FRAMES:  # flow needs a few frames: repeat the last one
            reps = MIN_FRAMES - n
            frames = np.concatenate([frames, np.repeat(frames[-1:], reps, 0)])
            masks = np.concatenate([masks, np.repeat(masks[-1:], reps, 0)])
        return self._run(frames, masks)[:n]

    def _empty_cache(self):
        import torch

        if self.device.type == "cuda":
            torch.cuda.empty_cache()

    def _run(self, frames_bgr: np.ndarray, masks: np.ndarray) -> np.ndarray:
        import torch

        cfg, dev = self.cfg, self.device
        t, h, w = masks.shape
        assert h % 8 == 0 and w % 8 == 0, "processing size must be a multiple of 8"
        rgb = np.ascontiguousarray(frames_bgr[..., ::-1])
        dilated_np = _dilate(masks, cfg.mask_dilation)

        with torch.no_grad():
            frames = torch.from_numpy(rgb).to(dev).permute(0, 3, 1, 2).float().div_(127.5).sub_(1).unsqueeze(0)
            flow_masks = torch.from_numpy(_dilate(masks, cfg.flow_mask_dilation)).to(dev).float()[None, :, None]
            masks_dilated = torch.from_numpy(dilated_np).to(dev).float()[None, :, None]

            # ---- optical flow (RAFT, fp32) ----
            short_clip = 12 if w <= 640 else 8 if w <= 720 else 4 if w <= 1280 else 2
            flows_f, flows_b = [], []
            for f in range(0, t, short_clip):
                e = min(t, f + short_clip)
                s = f if f == 0 else f - 1
                if e - s < 2:
                    continue
                ff, fb = self.raft(frames[:, s:e], iters=cfg.raft_iter)
                flows_f.append(ff)
                flows_b.append(fb)
                self._empty_cache()
            gt_flows = (torch.cat(flows_f, dim=1), torch.cat(flows_b, dim=1))

            if self.half:
                frames, flow_masks, masks_dilated = frames.half(), flow_masks.half(), masks_dilated.half()
                gt_flows = (gt_flows[0].half(), gt_flows[1].half())

            # ---- flow completion ----
            flow_len = gt_flows[0].size(1)
            sub = cfg.subvideo_length
            if flow_len > sub:
                pred_f, pred_b = [], []
                pad = 5
                for f in range(0, flow_len, sub):
                    s, e = max(0, f - pad), min(flow_len, f + sub + pad)
                    ps, pe = f - s, e - min(flow_len, f + sub)
                    part = (gt_flows[0][:, s:e], gt_flows[1][:, s:e])
                    pred, _ = self.flow_complete.forward_bidirect_flow(part, flow_masks[:, s:e + 1])
                    pred = self.flow_complete.combine_flow(part, pred, flow_masks[:, s:e + 1])
                    pred_f.append(pred[0][:, ps:e - s - pe])
                    pred_b.append(pred[1][:, ps:e - s - pe])
                    self._empty_cache()
                pred_flows = (torch.cat(pred_f, dim=1), torch.cat(pred_b, dim=1))
            else:
                pred_flows, _ = self.flow_complete.forward_bidirect_flow(gt_flows, flow_masks)
                pred_flows = self.flow_complete.combine_flow(gt_flows, pred_flows, flow_masks)
                self._empty_cache()

            # ---- image propagation ----
            masked_frames = frames * (1 - masks_dilated)
            sub_prop = min(100, sub)
            if t > sub_prop:
                upd_frames, upd_masks = [], []
                pad = 10
                for f in range(0, t, sub_prop):
                    s, e = max(0, f - pad), min(t, f + sub_prop + pad)
                    ps, pe = f - s, e - min(t, f + sub_prop)
                    n = e - s
                    prop, upd_local = self.model.img_propagation(
                        masked_frames[:, s:e], (pred_flows[0][:, s:e - 1], pred_flows[1][:, s:e - 1]),
                        masks_dilated[:, s:e], "nearest")
                    part = frames[:, s:e] * (1 - masks_dilated[:, s:e]) + \
                        prop.view(1, n, 3, h, w) * masks_dilated[:, s:e]
                    upd_frames.append(part[:, ps:n - pe])
                    upd_masks.append(upd_local.view(1, n, 1, h, w)[:, ps:n - pe])
                    self._empty_cache()
                updated_frames = torch.cat(upd_frames, dim=1)
                updated_masks = torch.cat(upd_masks, dim=1)
            else:
                prop, upd_local = self.model.img_propagation(masked_frames, pred_flows, masks_dilated, "nearest")
                updated_frames = frames * (1 - masks_dilated) + prop.view(1, t, 3, h, w) * masks_dilated
                updated_masks = upd_local.view(1, t, 1, h, w)
                self._empty_cache()

            # ---- feature propagation + transformer ----
            stride = max(1, cfg.neighbor_length // 2)
            ref_num = sub // cfg.ref_stride if t > sub else -1
            acc = np.zeros((t, h, w, 3), np.float32)
            cnt = np.zeros(t, np.float32)
            for f in range(0, t, stride):
                nb = list(range(max(0, f - stride), min(t, f + stride + 1)))
                refs = _ref_index(f, nb, t, cfg.ref_stride, ref_num)
                ids = nb + refs
                pred = self.model(updated_frames[:, ids], (pred_flows[0][:, nb[:-1]], pred_flows[1][:, nb[:-1]]),
                                  masks_dilated[:, ids], updated_masks[:, ids], len(nb))
                pred = ((pred.view(-1, 3, h, w).float() + 1) * 127.5).clamp_(0, 255)
                pred = pred.permute(0, 2, 3, 1).cpu().numpy()
                for i, idx in enumerate(nb):
                    acc[idx] += pred[i]
                    cnt[idx] += 1
                self._empty_cache()

        filled = (acc / np.maximum(cnt, 1)[:, None, None, None]).round().astype(np.uint8)[..., ::-1]
        m = dilated_np[..., None].astype(bool)
        return np.where(m, filled, frames_bgr)
