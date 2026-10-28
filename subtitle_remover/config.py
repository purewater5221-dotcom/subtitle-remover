"""All tunable settings in one place, plus quality/region presets."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

Region = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the frame


@dataclass
class DetectConfig:
    model_path: str | None = None  # default: PP-OCRv6 detector bundled with rapidocr
    max_side: int = 1280  # frames are downscaled so the long side is at most this
    every: int = 0  # run the detector on every N-th frame (0 = auto: 1 on GPU, 2 on CPU)
    batch: int = 4
    thresh: float = 0.3
    box_thresh: float = 0.5
    unclip_ratio: float = 1.6
    min_height: float = 8.0  # text lines thinner than this (px) are ignored


@dataclass
class FilterConfig:
    # "overlay": horizontal text that stays put on screen (subtitles, titles, captions)
    # "all": every detected text line, including signs and text moving with the scene
    target: str = "overlay"
    regions: list[Region] = field(default_factory=list)  # empty = whole frame
    max_angle: float = 12.0  # overlay text must be within this many degrees of horizontal
    max_spread: float = 0.35  # overlay text may drift at most this many text heights
    min_duration: float = 0.25  # seconds; shorter tracks are treated as noise
    max_gap: float = 0.5  # seconds; missed detections inside a track are filled in
    pad_before: float = 0.15  # seconds of mask added before a track (fade-in)
    pad_after: float = 0.15  # seconds of mask added after a track (fade-out)


@dataclass
class MaskConfig:
    pad_ratio: float = 0.18  # grow each text box by this fraction of its height
    pad_min: float = 4.0  # ...but at least this many pixels (covers outlines and shadows)
    feather: int = 3  # px of soft edge when pasting the filled area back


@dataclass
class SceneConfig:
    threshold: float = 27.0  # mean HSV change between frames that counts as a cut
    min_len: int = 10  # frames


@dataclass
class InpaintConfig:
    method: str = "propainter"  # propainter | opencv
    max_pixels: int = 450_000  # processing size budget of one cropped region
    chunk_frames: int = 120  # long clips are inpainted in overlapping chunks
    chunk_overlap: int = 12
    context_frames: int = 15  # extra frames around masked frames used as references
    roi_margin: float = 0.75  # context around the text band, in band heights
    roi_margin_min: int = 48
    roi_merge_gap: float = 0.08  # text bands closer than this (fraction of height) are merged
    fp16: bool = True
    # ProPainter
    raft_iter: int = 20
    neighbor_length: int = 10
    ref_stride: int = 10
    subvideo_length: int = 80
    flow_mask_dilation: int = 4
    mask_dilation: int = 2


@dataclass
class OutputConfig:
    crf: int = 17
    preset: str = "medium"
    debug: bool = False  # also write a mask preview video and tracks.json


@dataclass
class Config:
    detect: DetectConfig = field(default_factory=DetectConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    mask: MaskConfig = field(default_factory=MaskConfig)
    scene: SceneConfig = field(default_factory=SceneConfig)
    inpaint: InpaintConfig = field(default_factory=InpaintConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    device: str = "auto"  # auto | cuda | cpu
    work_dir: str | None = None
    keep_work: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


REGION_PRESETS: dict[str, list[Region]] = {
    "all": [],
    "bottom": [(0.0, 0.5, 1.0, 1.0)],
    "bottom-third": [(0.0, 2 / 3, 1.0, 1.0)],
    "top": [(0.0, 0.0, 1.0, 0.5)],
    "top-third": [(0.0, 0.0, 1.0, 1 / 3)],
}

QUALITY_PRESETS = ("fast", "balanced", "best")


def parse_region(text: str) -> list[Region]:
    """Parse a preset name or "x0,y0,x1,y1" with fractions between 0 and 1."""
    text = text.strip().lower()
    if text in REGION_PRESETS:
        return list(REGION_PRESETS[text])
    try:
        x0, y0, x1, y1 = (float(v) for v in text.replace(" ", "").split(","))
    except ValueError:
        raise ValueError(f"영역 형식이 잘못됐습니다: '{text}' (예: 0,0.6,1,1 또는 {', '.join(REGION_PRESETS)})")
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError(f"영역 값은 0~1 사이이고 x0<x1, y0<y1 이어야 합니다: '{text}'")
    return [(x0, y0, x1, y1)]


def apply_quality(cfg: Config, quality: str) -> Config:
    ip = cfg.inpaint
    if quality == "fast":
        ip.max_pixels, ip.raft_iter, ip.chunk_frames = 250_000, 12, 100
        cfg.detect.every = 2
    elif quality == "balanced":
        pass
    elif quality == "best":
        ip.max_pixels, ip.raft_iter, ip.chunk_frames = 700_000, 20, 90
        ip.neighbor_length, ip.ref_stride = 12, 8
    else:
        raise ValueError(f"알 수 없는 품질 설정: {quality} ({', '.join(QUALITY_PRESETS)})")
    return cfg


# Korean labels used by the notebook, the local UI and colab_run.bat jobs
QUALITY_LABELS = {"빠르게": "fast", "보통": "balanced", "최고": "best"}
REGION_LABELS = {"전체 화면": "all", "아래쪽 절반": "bottom", "아래쪽 1/3": "bottom-third",
                 "위쪽 절반": "top", "위쪽 1/3": "top-third", "직접 입력": None}
TARGET_LABELS = {"화면에 고정된 자막·글자만 (권장)": "overlay", "간판 등 모든 글자": "all"}


def config_from_choices(quality: str = "보통", region: str = "전체 화면", target: str = "overlay",
                        custom_region: str = "", method: str = "propainter") -> Config:
    """Build a Config from UI choices; each accepts the Korean label or the internal value."""
    cfg = apply_quality(Config(), QUALITY_LABELS.get(quality, quality))
    region_text = region if region not in REGION_LABELS else (REGION_LABELS[region] or custom_region)
    cfg.filter.regions = [r for part in region_text.split(";") if part.strip() for r in parse_region(part)]
    target = TARGET_LABELS.get(target, target)
    if target not in ("overlay", "all"):
        raise ValueError(f"알 수 없는 대상: {target} (overlay, all 중 선택)")
    cfg.filter.target = target
    cfg.inpaint.method = method
    return cfg
