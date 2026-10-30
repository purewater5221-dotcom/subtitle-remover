"""Text detection with a PP-OCR (DB) ONNX model.

The default model is the PP-OCRv6 detector bundled inside the `rapidocr` pip
package, so nothing has to be downloaded at runtime. Only the .onnx file is
used; rapidocr itself is never imported.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL = "PP-OCRv6_det_small.onnx"


@dataclass(frozen=True)
class TextBox:
    """A detected text line as a rotated rectangle in full-frame pixels.

    `w` is always the long side and `angle` (degrees, in (-90, 90]) is the
    direction of that side, so horizontal text has an angle near 0.
    """

    cx: float
    cy: float
    w: float
    h: float
    angle: float
    score: float

    def points(self, pad: float = 0.0, scale: float | tuple[float, float] = 1.0,
               offset: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
        """Corner points, optionally grown by `pad` px on every side, then
        shifted by -offset and scaled (uniformly or per axis)."""
        pts = cv2.boxPoints(((self.cx, self.cy), (self.w + 2 * pad, self.h + 2 * pad), self.angle))
        return (pts - np.asarray(offset, np.float32)) * np.asarray(scale, np.float32)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        pts = self.points()
        return (float(pts[:, 0].min()), float(pts[:, 1].min()),
                float(pts[:, 0].max()), float(pts[:, 1].max()))

    def to_dict(self) -> dict:
        return {k: round(float(getattr(self, k)), 2) for k in ("cx", "cy", "w", "h", "angle", "score")}


def rect_to_box(rect, score: float) -> TextBox:
    (cx, cy), (w, h), angle = rect
    if w < h:
        w, h = h, w
        angle += 90.0
    while angle > 90.0:
        angle -= 180.0
    while angle <= -90.0:
        angle += 180.0
    return TextBox(float(cx), float(cy), float(w), float(h), float(angle), float(score))


def default_model_path() -> Path:
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("rapidocr 패키지가 필요합니다: pip install --no-deps rapidocr==3.10.0")
    path = Path(list(spec.submodule_search_locations)[0]) / "models" / DEFAULT_MODEL
    if not path.exists():
        raise RuntimeError(f"검출 모델 파일을 찾을 수 없습니다: {path}")
    return path


def _explicit_same_padding(model) -> None:
    """Replace auto_pad=SAME_* on Conv/pooling nodes with explicit pads.

    onnx2torch cannot convert SAME padding, and cuDNN rejects the asymmetric
    padding it implies. Input sizes are always multiples of 32, so every
    layer's input is divisible by its stride and the padding is a constant.
    """
    from onnx import helper

    weights = {i.name: i for i in model.graph.initializer}
    for node in model.graph.node:
        if node.op_type not in ("Conv", "MaxPool", "AveragePool"):
            continue
        attrs = {a.name: helper.get_attribute_value(a) for a in node.attribute}
        auto = attrs.get("auto_pad", b"NOTSET")
        auto = auto.decode() if isinstance(auto, bytes) else auto
        if auto not in ("SAME_UPPER", "SAME_LOWER"):
            continue
        k = list(attrs.get("kernel_shape") or weights[node.input[1]].dims[2:])
        strides = attrs.get("strides", [1] * len(k))
        dilations = attrs.get("dilations", [1] * len(k))
        total = [max((ki - 1) * di + 1 - si, 0) for ki, si, di in zip(k, strides, dilations)]
        begin = [t // 2 if auto == "SAME_UPPER" else t - t // 2 for t in total]
        end = [t - b for t, b in zip(total, begin)]
        keep = [a for a in node.attribute if a.name not in ("auto_pad", "pads")]
        del node.attribute[:]
        node.attribute.extend(keep + [helper.make_attribute("pads", begin + end)])


class _TorchDetector:
    """The ONNX detector converted to PyTorch, so it runs on the same CUDA/cuDNN
    stack as ProPainter (onnxruntime-gpu often does not match Colab's cuDNN)."""

    def __init__(self, path: Path, device: str = "cuda"):
        import onnx
        import torch
        from onnx2torch import convert

        model = onnx.load(str(path))
        _explicit_same_padding(model)
        self.torch, self.dev = torch, torch.device(device)
        self.net = convert(model).eval().to(self.dev)
        self(np.zeros((1, 3, 64, 64), np.float32))  # fail now, not mid-video, if the GPU path is unusable

    def __call__(self, batch: np.ndarray) -> np.ndarray:
        with self.torch.inference_mode():
            return self.net(self.torch.from_numpy(batch).to(self.dev)).float().cpu().numpy()


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return torch.cuda.is_available()


class TextDetector:
    def __init__(self, model_path: str | Path | None = None, max_side: int = 1280,
                 thresh: float = 0.3, box_thresh: float = 0.5, unclip_ratio: float = 1.6,
                 device: str = "auto", max_candidates: int = 300):
        self.path = Path(model_path) if model_path else default_model_path()
        self._gpu: _TorchDetector | None = None
        self._ort = None
        if device in ("auto", "cuda") and _cuda_available():
            try:
                self._gpu = _TorchDetector(self.path)
            except Exception as e:  # noqa: BLE001 - CPU detection still works
                hint = " → pip install onnx onnx2torch" if isinstance(e, ImportError) else ""
                log.warning("GPU에서 검출 모델을 쓰지 못해 CPU로 자막을 찾아요 (느려요): %s%s", e, hint)
        self.device = "cuda" if self._gpu else "cpu"
        # on CPU, smaller frames keep detection time reasonable
        self.max_side = max_side if self._gpu else min(max_side, 960)
        self.thresh = thresh
        self.box_thresh = box_thresh
        self.unclip_ratio = unclip_ratio
        self.max_candidates = max_candidates

    def _cpu_session(self):
        if self._ort is None:
            import onnxruntime as ort

            if hasattr(ort, "disable_telemetry_events"):
                ort.disable_telemetry_events()
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            self._ort = ort.InferenceSession(str(self.path), opts, providers=["CPUExecutionProvider"])
        return self._ort

    def _infer(self, batch: np.ndarray) -> np.ndarray:
        if self._gpu is not None:
            try:
                return self._gpu(batch)
            except Exception as e:  # noqa: BLE001
                log.warning("GPU 검출 중 오류가 나서 CPU로 바꿔요: %s", e)
                self._gpu, self.device = None, "cpu"
        sess = self._cpu_session()
        return sess.run(None, {sess.get_inputs()[0].name: batch})[0]

    def input_size(self, h: int, w: int) -> tuple[int, int]:
        s = min(1.0, self.max_side / max(h, w))
        return max(32, round(h * s / 32) * 32), max(32, round(w * s / 32) * 32)

    def __call__(self, frames: list[np.ndarray]) -> list[list[TextBox]]:
        """Detect text lines in a batch of same-sized BGR frames."""
        if not frames:
            return []
        h, w = frames[0].shape[:2]
        rh, rw = self.input_size(h, w)
        interp = cv2.INTER_AREA if rh < h else cv2.INTER_LINEAR
        batch = np.stack([cv2.resize(f, (rw, rh), interpolation=interp) for f in frames])
        batch = (batch.astype(np.float32) / 127.5 - 1.0).transpose(0, 3, 1, 2)
        prob = self._infer(batch)[:, 0]
        return [self._boxes(p, w / rw, h / rh) for p in prob]

    def _boxes(self, prob: np.ndarray, sx: float, sy: float) -> list[TextBox]:
        bitmap = cv2.dilate((prob > self.thresh).astype(np.uint8), np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours[: self.max_candidates]:
            rect = cv2.minAreaRect(contour)
            (cx, cy), (rw, rh), angle = rect
            if min(rw, rh) < 3:
                continue
            score = _box_score(prob, cv2.boxPoints(rect))
            if score < self.box_thresh:
                continue
            # DB "unclip": grow the shrunk text kernel by area * ratio / perimeter
            d = rw * rh * self.unclip_ratio / (2 * (rw + rh))
            grown = cv2.boxPoints(((cx, cy), (rw + 2 * d, rh + 2 * d), angle))
            if min(rw, rh) + 2 * d < 5:
                continue
            grown = (grown * np.array([sx, sy], np.float32)).astype(np.float32)
            boxes.append(rect_to_box(cv2.minAreaRect(grown), score))
        return boxes


def _box_score(prob: np.ndarray, pts: np.ndarray) -> float:
    h, w = prob.shape
    x0 = int(np.clip(np.floor(pts[:, 0].min()), 0, w - 1))
    x1 = int(np.clip(np.ceil(pts[:, 0].max()), 0, w - 1))
    y0 = int(np.clip(np.floor(pts[:, 1].min()), 0, h - 1))
    y1 = int(np.clip(np.ceil(pts[:, 1].max()), 0, h - 1))
    mask = np.zeros((y1 - y0 + 1, x1 - x0 + 1), np.uint8)
    cv2.fillPoly(mask, [np.round(pts - [x0, y0]).astype(np.int32)], 1)
    return float(cv2.mean(prob[y0:y1 + 1, x0:x1 + 1], mask)[0])
