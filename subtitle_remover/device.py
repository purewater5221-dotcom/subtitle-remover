"""GPU detection and fitting the processing size to the available GPU memory."""

from __future__ import annotations

import re

from .config import Config

# Rough ProPainter (fp16) memory cost per processed pixel, from the GPU memory
# table in ProPainter's README (~7 GB at 720x480 and ~19 GB at 1280x720).
_BYTES_PER_PIXEL = 1024**3 / 45_000
_RESERVED_GB = 1.5
_MIN_PIXELS = 120_000
# GTX 1650/1660 cards are known to turn FP16 work into invalid values (black patches in
# other AI tools), so ProPainter runs in FP32 there.
_FP16_UNSAFE = re.compile(r"GTX\s*16\d\d", re.IGNORECASE)


def fp16_unsafe(gpu_name: str) -> bool:
    return bool(_FP16_UNSAFE.search(gpu_name))


def gpu_info() -> tuple[str, float] | None:
    """(name, memory in GB) of the first CUDA GPU, or None."""
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    props = torch.cuda.get_device_properties(0)
    return props.name, props.total_memory / 1024**3


def fit_to_gpu(cfg: Config, info: tuple[str, float] | None = None) -> str:
    """Turn FP16 off where it is unsafe and lower cfg.inpaint.max_pixels if the GPU cannot
    hold it. Returns a log line."""
    if cfg.inpaint.method != "propainter":
        return ""
    info = info if info is not None else (gpu_info() if cfg.device != "cpu" else None)
    if info is None:
        return "GPU를 찾지 못해 CPU로 실행합니다. ProPainter는 CPU에서 매우 느려요."
    name, gb = info
    notes = []
    if cfg.inpaint.fp16 and fp16_unsafe(name):
        cfg.inpaint.fp16 = False
        notes.append("GTX 16 시리즈라 FP32로 처리해요 (FP16은 결과가 까맣게 나올 수 있어요)")
    per_pixel = _BYTES_PER_PIXEL * (1 if cfg.inpaint.fp16 else 2)  # FP32 needs about twice the memory
    cap = max(_MIN_PIXELS, int((gb - _RESERVED_GB) * 1024**3 / per_pixel))
    if cfg.inpaint.max_pixels > cap:
        cfg.inpaint.max_pixels = cap
        if gb < 10:
            cfg.inpaint.chunk_frames = min(cfg.inpaint.chunk_frames, 80)
        notes.append(f"메모리에 맞춰 처리 크기를 {cap // 1000}k 픽셀로 줄였어요")
    return f"GPU: {name} ({gb:.0f}GB)" + (" → " + ", ".join(notes) if notes else "")
