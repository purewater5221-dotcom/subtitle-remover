"""Local web UI: python -m subtitle_remover.app [--open]

Runs on this computer (with its GPU) and opens in the browser at
http://127.0.0.1:7860. Same engine and settings as the Colab notebook.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .config import Config, apply_quality, parse_region
from .device import gpu_info
from .pipeline import SubtitleRemover
from .video_io import list_videos, make_comparison

log = logging.getLogger("subtitle_remover")

TASKS = ["자막 지우기", "마스크만 확인"]
QUALITIES = {"빠르게": "fast", "보통": "balanced", "최고": "best"}
REGIONS = {"전체 화면": "all", "아래쪽 절반": "bottom", "아래쪽 1/3": "bottom-third",
           "위쪽 절반": "top", "위쪽 1/3": "top-third", "직접 입력": None}
TARGETS = {"화면에 고정된 자막·글자만 (권장)": "overlay", "간판 등 모든 글자": "all"}
DEFAULT_OUTPUT = Path.cwd() / "output"
PREVIEW_DIR = Path(tempfile.gettempdir()) / "subtitle_remover_preview"


def build_config(quality: str, region: str, custom_region: str, target: str, save_preview: bool,
                 method: str = "propainter") -> Config:
    cfg = apply_quality(Config(), QUALITIES[quality])
    region_text = REGIONS.get(region) or custom_region
    cfg.filter.regions = [r for part in region_text.split(";") if part.strip() for r in parse_region(part)]
    cfg.filter.target = TARGETS[target]
    cfg.output.debug = save_preview
    cfg.inpaint.method = method
    return cfg


class _Runner:
    """Keeps loaded models between runs; settings changes reuse what they can."""

    def __init__(self):
        self.remover: SubtitleRemover | None = None

    def get(self, cfg: Config) -> SubtitleRemover:
        new = SubtitleRemover(cfg)
        old = self.remover
        if old is not None:
            if old.cfg.detect == new.cfg.detect and old._detector is not None:
                new._detector = old._detector
            if old.cfg.inpaint.method == new.cfg.inpaint.method and old._inpainter is not None:
                new._inpainter = old._inpainter
                if hasattr(new._inpainter, "cfg"):
                    new._inpainter.cfg = new.cfg.inpaint
        self.remover = new
        return new


_runner = _Runner()


class _LogCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def text(self) -> str:
        return "\n".join(self.lines[-200:])


def run_jobs(files, folder, task, quality, region, custom_region, target, out_dir, redo, save_preview,
             method: str = "propainter"):
    """Generator for the UI: yields (comparison video or None, log text)."""
    logs = _LogCollector()
    log.addHandler(logs)
    if log.getEffectiveLevel() > logging.INFO:
        log.setLevel(logging.INFO)
    try:
        try:
            cfg = build_config(quality, region, custom_region, target, save_preview, method)
        except ValueError as e:
            yield None, f"⚠️ {e}"
            return
        videos = [Path(f) for f in (files or [])]
        if folder and folder.strip():
            path = Path(folder.strip().strip('"'))
            if not path.exists():
                yield None, f"⚠️ 폴더가 없습니다: {path}"
                return
            videos += list_videos(path)
        videos = [v for v in videos if not v.stem.endswith(("_clean", "_mask"))]
        if not videos:
            yield None, "⚠️ 영상을 올리거나 영상이 있는 폴더 경로를 입력해 주세요."
            return
        out_dir = Path(out_dir.strip().strip('"') or DEFAULT_OUTPUT)
        out_dir.mkdir(parents=True, exist_ok=True)
        detect_only = task == "마스크만 확인"
        remover = _runner.get(cfg)
        preview = None
        for i, src in enumerate(videos, 1):
            dst = out_dir / f"{src.stem}_clean.mp4"
            if not detect_only and dst.exists() and not redo:
                log.info("[%d/%d] %s: 이미 결과가 있어 건너뜀 (%s)", i, len(videos), src.name, dst)
                continue
            log.info("[%d/%d] %s 처리 시작", i, len(videos), src.name)
            box: dict = {}
            worker = threading.Thread(target=_process, args=(remover, src, dst, detect_only, box), daemon=True)
            worker.start()
            while worker.is_alive():
                worker.join(1.0)
                yield preview, logs.text()
            if "error" in box:
                log.error("❌ %s 실패: %s", src.name, box["error"], exc_info=box["error"])
                continue
            r = box["result"]
            done = r.output or r.preview
            log.info("✅ %.0f초, 지운 글자 %d개 → %s%s", r.seconds, r.removed, done, f" ({r.note})" if r.note else "")
            try:
                if r.output is not None:
                    preview = str(make_comparison(src, r.output, PREVIEW_DIR / f"{src.stem}_compare.mp4"))
                elif r.preview is not None:  # mask preview only
                    preview = _copy_preview(r.preview)
            except Exception as e:  # noqa: BLE001 - preview is optional
                log.warning("미리보기를 만들지 못했어요: %s", e)
            yield preview, logs.text()
        log.info("끝! 결과 폴더: %s", out_dir)
        yield preview, logs.text()
    finally:
        log.removeHandler(logs)


def _process(remover, src, dst, detect_only, box):
    try:
        box["result"] = remover.process(src, dst, detect_only=detect_only)
    except Exception as e:  # noqa: BLE001 - reported in the UI
        box["error"] = e


def _copy_preview(path: Path) -> str:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    target = PREVIEW_DIR / path.name
    target.write_bytes(path.read_bytes())
    return str(target)


def open_folder(path: str) -> str:
    path = Path(path.strip().strip('"') or DEFAULT_OUTPUT)
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return f"폴더를 열었어요: {path}"
    except Exception as e:  # noqa: BLE001
        return f"폴더를 열지 못했어요 ({e}). 직접 열어 주세요: {path}"


def build_ui(method: str = "propainter"):
    # local tool: no usage analytics or update checks
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    import gradio as gr

    info = gpu_info()
    status = (f"🟢 GPU: {info[0]} ({info[1]:.0f}GB)" if info else
              "🟠 GPU를 찾지 못했어요. CPU로 실행하면 매우 느려요 (NVIDIA 드라이버와 설치 상태를 확인하세요).")

    with gr.Blocks(title="자막 지우개") as demo:
        gr.Markdown(f"# 자막 지우개\n짧은 영상의 자막을 찾아서 배경으로 자연스럽게 메꿔요.  \n{status}")
        with gr.Row():
            with gr.Column(scale=1):
                files = gr.File(label="영상 올리기 (여러 개 가능)", file_count="multiple", type="filepath",
                                file_types=["video"])
                folder = gr.Textbox(label="또는 영상이 있는 폴더 경로", placeholder=r"예: C:\Users\me\Videos\shorts")
                task = gr.Radio(TASKS, value=TASKS[0], label="무엇을 할까요?",
                                info="마스크만 확인: 지울 부분을 빨갛게 표시한 미리보기만 빠르게 만들어요")
                quality = gr.Radio(list(QUALITIES), value="보통", label="품질",
                                   info="빠르게 → 최고로 갈수록 느리지만 더 자연스러워요")
                region = gr.Dropdown(list(REGIONS), value="전체 화면", label="어디에 있는 글자를 지울까요?")
                custom = gr.Textbox(value="0,0.6,1,1", label="직접 입력 영역",
                                    info="x0,y0,x1,y1 (0~1 비율). 예) 0,0.6,1,1 = 아래쪽 40%. 여러 개는 ;로 구분")
                target = gr.Radio(list(TARGETS), value=list(TARGETS)[0], label="어떤 글자를 지울까요?")
                out_dir = gr.Textbox(value=str(DEFAULT_OUTPUT), label="결과 저장 폴더")
                with gr.Row():
                    redo = gr.Checkbox(label="이미 처리한 영상도 다시 하기")
                    save_preview = gr.Checkbox(label="마스크 미리보기도 저장")
                start = gr.Button("시작", variant="primary")
            with gr.Column(scale=1):
                video = gr.Video(label="원본 | 결과 (가장 최근 영상)", interactive=False, autoplay=True)
                logs = gr.Textbox(label="진행 상황", lines=16, max_lines=16, autoscroll=True)
                open_btn = gr.Button("결과 폴더 열기")
                open_msg = gr.Markdown()

        def handler(files, folder, task, quality, region, custom, target, out_dir, redo, save_preview,
                    progress=gr.Progress(track_tqdm=True)):
            yield from run_jobs(files, folder, task, quality, region, custom, target, out_dir, redo,
                                save_preview, method)

        start.click(handler, [files, folder, task, quality, region, custom, target, out_dir, redo, save_preview],
                    [video, logs])
        open_btn.click(open_folder, [out_dir], [open_msg])
    return demo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m subtitle_remover.app", description="자막 지우개 로컬 화면")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="브라우저 자동으로 열기")
    ap.add_argument("--method", default="propainter", choices=["propainter", "opencv"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        import gradio  # noqa: F401
    except ImportError:
        print("gradio가 설치돼 있지 않아요: pip install gradio")
        return 1
    demo = build_ui(args.method)
    demo.queue(default_concurrency_limit=1).launch(server_name=args.host, server_port=args.port,
                                                   inbrowser=args.open, allowed_paths=[str(PREVIEW_DIR)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
