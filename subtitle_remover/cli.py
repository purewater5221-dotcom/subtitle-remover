"""Command line interface: python -m subtitle_remover INPUT [INPUT ...]"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import QUALITY_PRESETS, REGION_PRESETS, Config, apply_quality, parse_region
from .logs import TimeReport, format_seconds
from .video_io import list_videos


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m subtitle_remover",
        description="짧은 영상에 박힌 자막을 찾아서 배경으로 자연스럽게 메꿉니다.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("inputs", nargs="+", help="영상 파일 또는 영상이 들어 있는 폴더")
    p.add_argument("-o", "--output", help="결과 파일(.mp4) 또는 폴더. 생략하면 입력 옆에 *_clean.mp4로 저장")
    p.add_argument("--method", default="propainter", choices=["propainter", "opencv"],
                   help="지우기 방식 (opencv는 빠르지만 품질이 낮은 테스트용)")
    p.add_argument("--quality", default="balanced", choices=QUALITY_PRESETS, help="품질/속도 설정")
    p.add_argument("--region", action="append", default=[],
                   help=f"자막을 찾을 영역. 여러 번 지정 가능. 프리셋({', '.join(REGION_PRESETS)}) "
                        "또는 비율 좌표 x0,y0,x1,y1 (예: 0,0.6,1,1 = 아래쪽 40%%)")
    p.add_argument("--target", default="overlay", choices=["overlay", "all"],
                   help="overlay: 화면에 고정된 자막·글자만 / all: 간판 등 모든 글자")
    p.add_argument("--detect-only", action="store_true",
                   help="지우지 않고 마스크 미리보기 영상(*_mask.mp4)만 만들기")
    p.add_argument("--debug", action="store_true", help="결과와 함께 마스크 미리보기와 tracks.json 저장")
    p.add_argument("--overwrite", action="store_true", help="이미 결과가 있어도 다시 처리")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])

    g = p.add_argument_group("세부 조정")
    g.add_argument("--max-pixels", type=int, help="잘라낸 영역의 처리 크기 상한(픽셀 수). 줄이면 메모리 절약")
    g.add_argument("--det-every", type=int, help="N프레임마다 자막 검출 (기본: GPU면 1, CPU면 2)")
    g.add_argument("--det-max-side", type=int, help="검출할 때 프레임 긴 변 크기")
    g.add_argument("--box-thresh", type=float, help="검출 신뢰도 기준 (낮추면 더 많이 찾음)")
    g.add_argument("--mask-pad", type=float, help="글자 높이 대비 마스크 여유 비율")
    g.add_argument("--feather", type=int, help="경계 부드럽게 하는 폭(px)")
    g.add_argument("--chunk-frames", type=int, help="한 번에 처리할 프레임 수")
    g.add_argument("--crf", type=int, help="결과 화질 (낮을수록 고화질, 기본 17)")
    g.add_argument("--work-dir", help="중간 파일 폴더 (기본: 시스템 임시 폴더)")
    g.add_argument("--keep-work", action="store_true", help="중간 파일 지우지 않기")
    return p


def config_from_args(args: argparse.Namespace) -> Config:
    cfg = apply_quality(Config(), args.quality)
    cfg.device = args.device
    cfg.inpaint.method = args.method
    cfg.filter.target = args.target
    cfg.filter.regions = [r for text in args.region for r in parse_region(text)]
    cfg.output.debug = args.debug
    cfg.work_dir = args.work_dir
    cfg.keep_work = args.keep_work
    for value, section, name in [
        (args.max_pixels, cfg.inpaint, "max_pixels"), (args.det_every, cfg.detect, "every"),
        (args.det_max_side, cfg.detect, "max_side"), (args.box_thresh, cfg.detect, "box_thresh"),
        (args.mask_pad, cfg.mask, "pad_ratio"), (args.feather, cfg.mask, "feather"),
        (args.chunk_frames, cfg.inpaint, "chunk_frames"), (args.crf, cfg.output, "crf"),
    ]:
        if value is not None:
            setattr(section, name, value)
    return cfg


def output_path_for(src: Path, output: str | None, many: bool) -> Path:
    name = f"{src.stem}_clean.mp4"
    if output is None:
        return src.with_name(name)
    out = Path(output)
    if not many and out.suffix.lower() == ".mp4":
        return out
    return out / name


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("subtitle_remover")
    try:
        cfg = config_from_args(args)
    except ValueError as e:
        log.error(str(e))
        return 2

    videos = [v for src in args.inputs for v in list_videos(src)]
    videos = [v for v in videos if not v.stem.endswith(("_clean", "_mask"))]
    if not videos:
        log.error("처리할 영상이 없습니다.")
        return 1

    from .pipeline import SubtitleRemover

    remover = SubtitleRemover(cfg)
    failed, times = 0, TimeReport()
    for i, src in enumerate(videos, 1):
        dst = output_path_for(src, args.output, len(videos) > 1 or Path(args.inputs[0]).is_dir())
        if not args.detect_only and dst.exists() and not args.overwrite:
            log.info("[%d/%d] %s: 이미 결과가 있어 건너뜁니다 (%s)", i, len(videos), src.name, dst)
            continue
        log.info("[%d/%d] %s 처리 시작", i, len(videos), src.name)
        try:
            r = remover.process(src, dst, detect_only=args.detect_only)
        except Exception as e:  # noqa: BLE001 - keep going with the next video
            failed += 1
            log.exception("[%d/%d] %s 실패: %s", i, len(videos), src.name, e)
            times.add(src.name)
            continue
        done = r.output or r.preview
        times.add(src.name, r)
        log.info("[%d/%d] 완료 (%s): %s%s", i, len(videos), format_seconds(r.seconds), done,
                 f" - {r.note}" if r.note else "")
    times.log()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
