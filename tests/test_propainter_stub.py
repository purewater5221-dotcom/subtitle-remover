"""Checks the ProPainter wrapper's tensor plumbing (shapes, chunking, compositing)
against stand-in modules with ProPainter's interfaces. The real models are
exercised on a GPU (see the Colab notebook)."""

import sys

import cv2
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from subtitle_remover.config import InpaintConfig  # noqa: E402
from subtitle_remover.inpaint.propainter import WEIGHTS, ProPainterInpainter  # noqa: E402

STUB = {
    "model/__init__.py": "",
    "model/modules/__init__.py": "",
    "model/modules/flow_comp_raft.py": """
import torch
class RAFT_bi(torch.nn.Module):
    def __init__(self, model_path, device):
        super().__init__()
    def forward(self, frames, iters=20):
        b, t, c, h, w = frames.shape
        assert t >= 2 and frames.dtype == torch.float32 and c == 3
        assert frames.min() >= -1 and frames.max() <= 1
        z = torch.zeros(b, t - 1, 2, h, w, device=frames.device)
        return z, z.clone()
""",
    "model/recurrent_flow_completion.py": """
import torch
class RecurrentFlowCompleteNet(torch.nn.Module):
    def __init__(self, model_path=None):
        super().__init__()
        self.p = torch.nn.Parameter(torch.zeros(1))
    def forward_bidirect_flow(self, flows, masks):
        assert masks.size(1) == flows[0].size(1) + 1, (masks.shape, flows[0].shape)
        return (flows[0].clone(), flows[1].clone()), None
    def combine_flow(self, gt, pred, masks):
        return pred
""",
    "model/propainter.py": """
import torch
class InpaintGenerator(torch.nn.Module):
    calls = []
    def __init__(self, model_path=None):
        super().__init__()
        self.p = torch.nn.Parameter(torch.zeros(1))
    def img_propagation(self, masked_frames, flows, masks, interpolation):
        b, t, c, h, w = masked_frames.shape
        assert flows[0].size(1) == t - 1 and masks.size(1) == t
        return masked_frames.reshape(b * t, c, h, w), masks.reshape(b * t, 1, h, w)
    def forward(self, imgs, flows, masks, upd_masks, l_t):
        b, t, c, h, w = imgs.shape
        assert flows[0].size(1) == l_t - 1 and masks.size(1) == t and upd_masks.size(1) == t
        InpaintGenerator.calls.append((t, l_t))
        return torch.full((b, l_t, 3, h, w), 0.5, dtype=imgs.dtype, device=imgs.device)
""",
}


@pytest.fixture
def stub_root(tmp_path):
    root = tmp_path / "ProPainter"
    for rel, src in STUB.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src)
    for name in WEIGHTS:
        (root / "weights").mkdir(exist_ok=True)
        (root / "weights" / name).write_bytes(b"stub")
    saved = {k: v for k, v in sys.modules.items() if k == "model" or k.startswith("model.")}
    for k in saved:
        del sys.modules[k]
    yield root
    for k in [k for k in sys.modules if k == "model" or k.startswith("model.")]:
        del sys.modules[k]
    sys.modules.update(saved)
    if str(root) in sys.path:
        sys.path.remove(str(root))


def test_wrapper_fills_only_the_dilated_mask(stub_root):
    # small sub-video/neighbour settings force every chunked code path
    cfg = InpaintConfig(subvideo_length=8, neighbor_length=4, ref_stride=3, mask_dilation=2)
    ip = ProPainterInpainter(cfg, device="cpu", root=stub_root)
    rng = np.random.default_rng(0)
    t, h, w = 23, 32, 48
    frames = rng.integers(0, 256, (t, h, w, 3), dtype=np.uint8)
    masks = np.zeros((t, h, w), np.uint8)
    masks[5:18, 12:20, 10:38] = 1

    out = ip.inpaint(frames, masks)

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dil = np.stack([cv2.dilate(m, k) for m in masks]).astype(bool)
    assert out.shape == frames.shape and out.dtype == np.uint8
    assert (out[~dil] == frames[~dil]).all()
    assert (out[dil] == 191).all()  # stub predicts 0.5 -> (0.5 + 1) * 127.5
    calls = sys.modules["model.propainter"].InpaintGenerator.calls
    assert calls and any(n > local for n, local in calls)  # windows got global reference frames


def test_wrapper_pads_very_short_clips(stub_root):
    ip = ProPainterInpainter(InpaintConfig(), device="cpu", root=stub_root)
    frames = np.zeros((1, 16, 16, 3), np.uint8)
    masks = np.ones((1, 16, 16), np.uint8)
    out = ip.inpaint(frames, masks)
    assert out.shape == (1, 16, 16, 3) and (out == 191).all()


def test_ensure_propainter_without_git_uses_source_zip(tmp_path, monkeypatch):
    import zipfile

    from subtitle_remover.inpaint import propainter

    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("ProPainter-abc123/model/propainter.py", "# stub")
        z.writestr("ProPainter-abc123/RAFT/__init__.py", "")
    release = tmp_path / "release"
    release.mkdir()
    for name in WEIGHTS:
        (release / name).write_bytes(b"w")
    monkeypatch.setattr(propainter.shutil, "which", lambda name: None)
    monkeypatch.setattr(propainter, "REPO_ZIP_URL", archive.as_uri())
    monkeypatch.setattr(propainter, "WEIGHTS_URL", release.as_uri() + "/")

    root = propainter.ensure_propainter(tmp_path / "cache" / "ProPainter")
    assert (root / "model" / "propainter.py").exists() and (root / "RAFT").is_dir()
    assert all((root / "weights" / n).read_bytes() == b"w" for n in WEIGHTS)
    assert not (tmp_path / "cache" / "ProPainter.zip").exists()
    assert propainter.ensure_propainter(root) == root  # second call: nothing to do
