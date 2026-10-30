import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from subtitle_remover import detect
from subtitle_remover.detect import TextDetector, default_model_path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def frame_with_text():
    rng = np.random.default_rng(0)
    img = Image.fromarray((rng.random((640, 360, 3)) * 80 + 60).astype(np.uint8))
    ImageDraw.Draw(img).text((180, 520), "Burned-in subtitle", font=ImageFont.truetype(FONT, 28),
                             fill=(255, 255, 255), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
    return np.array(img)[..., ::-1].copy()


def test_torch_conversion_matches_onnxruntime():
    pytest.importorskip("onnx2torch")
    gpu = detect._TorchDetector(default_model_path(), device="cpu")  # same conversion as on the GPU
    cpu = TextDetector(device="cpu")
    batch = np.random.default_rng(1).uniform(-1, 1, (2, 3, 320, 192)).astype(np.float32)
    ref = cpu._infer(batch)
    out = gpu(batch)
    assert out.shape == ref.shape and np.abs(out - ref).max() < 1e-3


def test_falls_back_to_cpu_when_the_gpu_detector_fails(monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("Failed to initialize CUDNN Frontend")

    monkeypatch.setattr(detect, "_cuda_available", lambda: True)
    monkeypatch.setattr(detect, "_TorchDetector", Broken)
    det = TextDetector()
    assert det.device == "cpu" and det.max_side == 960
    boxes = det([frame_with_text()])[0]
    assert any(abs(b.cy - 520) < 20 and abs(b.angle) < 5 for b in boxes)


def test_switches_to_cpu_if_the_gpu_fails_mid_run(monkeypatch):
    class FailsLater:
        def __init__(self, *a, **k):
            pass

        def __call__(self, batch):
            raise RuntimeError("CUDA error: an illegal memory access was encountered")

    monkeypatch.setattr(detect, "_cuda_available", lambda: True)
    monkeypatch.setattr(detect, "_TorchDetector", FailsLater)
    det = TextDetector()
    assert det.device == "cuda"
    assert det([frame_with_text()])[0]
    assert det.device == "cpu"
