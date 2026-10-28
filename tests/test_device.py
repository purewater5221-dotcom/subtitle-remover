from subtitle_remover.config import Config, apply_quality
from subtitle_remover.device import fit_to_gpu


def test_small_gpu_lowers_processing_size():
    cfg = apply_quality(Config(), "best")
    note = fit_to_gpu(cfg, ("RTX 4060", 8.0))
    assert cfg.inpaint.max_pixels < 700_000 and cfg.inpaint.chunk_frames <= 80
    assert "RTX 4060" in note


def test_big_gpu_keeps_settings():
    cfg = Config()
    fit_to_gpu(cfg, ("RTX 4090", 24.0))
    assert cfg.inpaint.max_pixels == Config().inpaint.max_pixels


def test_opencv_method_is_untouched():
    cfg = Config()
    cfg.inpaint.method = "opencv"
    assert fit_to_gpu(cfg, ("tiny", 2.0)) == "" and cfg.inpaint.max_pixels == Config().inpaint.max_pixels
