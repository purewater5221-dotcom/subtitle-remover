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


def test_fast_preset_does_about_half_the_work():
    fast, balanced = apply_quality(Config(), "fast"), Config()
    assert fast.inpaint.max_pixels < balanced.inpaint.max_pixels / 2
    assert fast.inpaint.raft_iter < balanced.inpaint.raft_iter
    assert fast.inpaint.ref_stride > balanced.inpaint.ref_stride
    assert fast.detect.every == 2


def test_gtx_16_series_runs_in_fp32_with_a_smaller_size():
    gtx = Config()
    note = fit_to_gpu(gtx, ("NVIDIA GeForce GTX 1660 Ti", 5.8))
    assert gtx.inpaint.fp16 is False and "FP32" in note
    rtx = Config()
    fit_to_gpu(rtx, ("NVIDIA GeForce RTX 2060", 5.8))
    assert rtx.inpaint.fp16 is True
    assert gtx.inpaint.max_pixels < rtx.inpaint.max_pixels  # FP32 needs more memory per pixel
    t4 = Config()
    assert fit_to_gpu(t4, ("Tesla T4", 15.0)) == "GPU: Tesla T4 (15GB)" and t4.inpaint.fp16 is True
