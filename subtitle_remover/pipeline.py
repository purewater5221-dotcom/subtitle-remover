"""End-to-end processing of one video in three passes over the frames.

1. analyze:   detect text on (every N-th) frame and find scene cuts
2. inpaint:   crop each text region to small clips and fill them in
3. composite: paste the filled regions back into the full frames and encode
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from tqdm.auto import tqdm

from .config import Config
from .detect import TextBox, TextDetector
from .device import fit_to_gpu
from .masks import feather, rasterize
from .planner import Job, plan_jobs
from .scenes import SceneDetector
from .tracking import Track, build_schedule, build_tracks, classify_tracks, in_regions
from .video_io import FrameWriter, VideoInfo, copy_as_mp4, probe, read_frames

log = logging.getLogger("subtitle_remover")


@dataclass
class VideoResult:
    input: Path
    output: Path | None
    preview: Path | None
    frames: int
    tracks: int
    removed: int
    jobs: int
    seconds: float
    note: str = ""
    timings: dict = field(default_factory=dict)  # seconds per stage


@dataclass
class Analysis:
    info: VideoInfo
    n_frames: int
    tracks: list[Track]
    schedule: list[list[TextBox]]
    scenes: list[tuple[int, int]]
    jobs: list[Job]


def chunk_ranges(n: int, chunk: int, overlap: int) -> list[tuple[int, int]]:
    """Evenly sized [start, end) chunks of length <= chunk overlapping by `overlap`."""
    if n <= chunk:
        return [(0, n)]
    overlap = min(overlap, chunk // 2)
    count = math.ceil((n - overlap) / (chunk - overlap))
    length = math.ceil((n - overlap) / count) + overlap
    ranges, s = [], 0
    while True:
        e = min(n, s + length)
        ranges.append((s, e))
        if e == n:
            return ranges
        s = e - overlap


def _is_oom(e: BaseException) -> bool:
    return "out of memory" in str(e).lower() or type(e).__name__ == "OutOfMemoryError"


def inpaint_chunked(inpainter, frames: np.ndarray, masks: np.ndarray, out: np.ndarray,
                    chunk: int, overlap: int, min_chunk: int = 24) -> None:
    """Inpaint a long clip in overlapping chunks, cross-fading the overlaps.

    On GPU out-of-memory the chunk length is halved and the clip retried.
    """
    while True:
        try:
            prev_end = 0
            for s, e in chunk_ranges(len(frames), chunk, overlap):
                res = inpainter.inpaint(np.asarray(frames[s:e]), np.asarray(masks[s:e]))
                ov = prev_end - s
                if ov > 0:
                    w = np.linspace(0, 1, ov + 2, dtype=np.float32)[1:-1, None, None, None]
                    out[s:prev_end] = np.round(out[s:prev_end] * (1 - w) + res[:ov] * w).astype(np.uint8)
                out[s + max(ov, 0):e] = res[max(ov, 0):]
                prev_end = e
            return
        except Exception as e:  # noqa: BLE001
            if not _is_oom(e) or chunk <= min_chunk:
                if _is_oom(e):
                    raise RuntimeError("GPU 메모리가 부족합니다. 품질을 '빠르게'로 낮추거나 "
                                       "--max-pixels 값을 줄여 주세요.") from e
                raise
            _free_gpu()
            chunk = max(min_chunk, chunk // 2)
            overlap = min(overlap, chunk // 4)
            log.warning("GPU 메모리가 부족해 %d프레임씩 나눠서 다시 처리합니다.", chunk)


def _free_gpu() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


class SubtitleRemover:
    def __init__(self, cfg: Config | None = None):
        self.cfg = copy.deepcopy(cfg) if cfg else Config()
        self._detector: TextDetector | None = None
        self._inpainter = None
        note = fit_to_gpu(self.cfg)
        if note:
            log.info(note)

    @property
    def detector(self) -> TextDetector:
        if self._detector is None:
            d = self.cfg.detect
            self._detector = TextDetector(d.model_path, d.max_side, d.thresh, d.box_thresh,
                                          d.unclip_ratio, self.cfg.device)
            log.info("텍스트 검출 모델 준비 완료 (%s)", self._detector.device)
        return self._detector

    @property
    def inpainter(self):
        if self._inpainter is None:
            from .inpaint import create_inpainter

            self._inpainter = create_inpainter(self.cfg.inpaint, self.cfg.device)
            log.info("지우기 모델 준비 완료 (%s)", self._inpainter.name)
        return self._inpainter

    # ------------------------------------------------------------------ pass 1
    def analyze(self, path: str | Path) -> Analysis:
        cfg = self.cfg
        info = probe(path)
        if info.is_hdr:
            log.warning("HDR 영상입니다. 결과 영상은 SDR로 저장되어 색이 조금 달라질 수 있어요.")
        fps = float(info.fps)
        every = cfg.detect.every or (1 if self.detector.device == "cuda" else 2)
        scenes = SceneDetector(cfg.scene.threshold, cfg.scene.min_len)
        detections: dict[int, list[TextBox]] = {}
        batch, batch_idx = [], []

        def flush():
            for idx, boxes in zip(batch_idx, self.detector(batch)):
                detections[idx] = [b for b in boxes if b.h >= cfg.detect.min_height
                                   and in_regions(b, cfg.filter.regions, info.width, info.height)]
            batch.clear()
            batch_idx.clear()

        n = 0
        for idx, frame in enumerate(tqdm(read_frames(info), total=info.est_frames, desc="1/3 자막 찾는 중",
                                         unit="f", leave=False)):
            scenes.update(idx, frame)
            if idx % every == 0:
                batch.append(frame)
                batch_idx.append(idx)
                if len(batch) >= cfg.detect.batch:
                    flush()
            n = idx + 1
        if batch:
            flush()
        if n == 0:
            raise RuntimeError(f"프레임을 읽지 못했습니다: {path}")

        tracks = build_tracks(detections, max_gap=max(every, round(cfg.filter.max_gap * fps)))
        classify_tracks(tracks, cfg.filter, fps)
        schedule = build_schedule(tracks, n, fps, cfg.filter, every)
        scene_list = scenes.scenes(n)
        jobs = plan_jobs(schedule, scene_list, info.width, info.height, cfg.mask, cfg.inpaint)
        return Analysis(info, n, tracks, schedule, scene_list, jobs)

    # ------------------------------------------------------------------ main
    def process(self, input_path: str | Path, output_path: str | Path,
                detect_only: bool = False) -> VideoResult:
        t0 = time.time()
        cfg = self.cfg
        input_path, output_path = Path(input_path), Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        a = self.analyze(input_path)
        timings = {"찾기": time.time() - t0}
        kept = sum(t.keep for t in a.tracks)
        log.info("%s: %d프레임, 텍스트 %d개 중 %d개 제거 대상, 장면 %d개, 처리 구간 %d개",
                 input_path.name, a.n_frames, len(a.tracks), kept, len(a.scenes), len(a.jobs))

        preview = output_path.with_name(output_path.stem + "_mask.mp4")
        if detect_only or cfg.output.debug:
            self._write_report(a, output_path.with_name(output_path.stem + "_tracks.json"))
        if detect_only:
            self._write_preview(a, preview)
            return VideoResult(input_path, None, preview, a.n_frames, len(a.tracks), kept, len(a.jobs),
                               time.time() - t0, "마스크 미리보기만 만들었습니다")
        if not a.jobs:
            copy_as_mp4(input_path, output_path)
            return VideoResult(input_path, output_path, None, a.n_frames, len(a.tracks), 0, 0,
                               time.time() - t0, "지울 자막을 찾지 못해 원본을 그대로 복사했습니다")

        work_root = Path(cfg.work_dir) if cfg.work_dir else Path(tempfile.gettempdir()) / "subtitle_remover"
        st = input_path.stat()
        settings = json.dumps(cfg.to_dict(), sort_keys=True, default=str)
        key = hashlib.sha1(f"{input_path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{settings}".encode()).hexdigest()
        work = work_root / f"{input_path.stem}_{key[:10]}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            t = time.time()
            self._extract(a, work)
            self._inpaint_jobs(a, work)
            timings["메꾸기"] = time.time() - t
            t = time.time()
            self._composite(a, work, output_path, preview if cfg.output.debug else None)
            timings["합치기"] = time.time() - t
        finally:
            if not cfg.keep_work:
                shutil.rmtree(work, ignore_errors=True)
        log.info("⏱ %s", " · ".join(f"{k} {v:.0f}초" for k, v in timings.items()))
        return VideoResult(input_path, output_path, preview if cfg.output.debug else None, a.n_frames,
                           len(a.tracks), kept, len(a.jobs), time.time() - t0, timings=timings)

    # ------------------------------------------------------------------ pass 2
    def _extract(self, a: Analysis, work: Path) -> None:
        todo = [j for j in a.jobs if not (work / f"job{j.id}.done").exists()]
        if not todo:
            return
        arrays = {j.id: np.lib.format.open_memmap(work / f"job{j.id}_in.npy", mode="w+", dtype=np.uint8,
                                                  shape=(j.length, j.proc_h, j.proc_w, 3)) for j in todo}
        last = max(j.end for j in todo)
        for idx, frame in enumerate(tqdm(read_frames(a.info), total=last, desc="2/3 영역 자르는 중",
                                         unit="f", leave=False)):
            if idx >= last:
                break
            for j in todo:
                if j.start <= idx < j.end:
                    x0, y0, x1, y1 = j.roi
                    crop = frame[y0:y1, x0:x1]
                    if (j.proc_w, j.proc_h) != (j.roi_w, j.roi_h):
                        crop = cv2.resize(crop, (j.proc_w, j.proc_h), interpolation=cv2.INTER_AREA)
                    arrays[j.id][idx - j.start] = crop
        for arr in arrays.values():
            arr.flush()

    def job_masks(self, a: Analysis, job: Job) -> np.ndarray:
        x0, y0 = job.roi[:2]
        return np.stack([rasterize([b for b in a.schedule[f] if job.owns(b)], (job.proc_h, job.proc_w),
                                   self.cfg.mask, offset=(x0, y0), scale=job.scale)
                         for f in range(job.start, job.end)])

    def _inpaint_jobs(self, a: Analysis, work: Path) -> None:
        icfg = self.cfg.inpaint
        for k, job in enumerate(a.jobs, 1):
            done = work / f"job{job.id}.done"
            if done.exists():
                continue
            t = time.time()
            frames = np.load(work / f"job{job.id}_in.npy", mmap_mode="r")
            masks = self.job_masks(a, job)
            out = np.lib.format.open_memmap(work / f"job{job.id}_out.npy", mode="w+", dtype=np.uint8,
                                            shape=frames.shape)
            log.info("2/3 지우는 중: 구간 %d/%d (%d프레임, %dx%d)", k, len(a.jobs), job.length,
                     job.proc_w, job.proc_h)
            inpaint_chunked(self.inpainter, frames, masks, out, icfg.chunk_frames, icfg.chunk_overlap)
            out.flush()
            del out, frames
            done.touch()
            log.info("   구간 %d 완료 (%.1f초)", k, time.time() - t)
        _free_gpu()

    # ------------------------------------------------------------------ pass 3
    def _composite(self, a: Analysis, work: Path, output: Path, preview: Path | None) -> None:
        cfg, info = self.cfg, a.info
        results = {j.id: np.load(work / f"job{j.id}_out.npy", mmap_mode="r") for j in a.jobs}
        writer = FrameWriter(output, info.width, info.height, info.fps, info.color_space, info,
                             cfg.output.crf, cfg.output.preset)
        pw = _PreviewWriter(preview, a, cfg) if preview else None
        with writer:
            for idx, frame in enumerate(tqdm(read_frames(info), total=a.n_frames, desc="3/3 합치는 중",
                                             unit="f", leave=False)):
                if idx >= a.n_frames:
                    break
                out = frame.copy()
                for j in a.jobs:
                    if not (j.start <= idx < j.end):
                        continue
                    boxes = [b for b in a.schedule[idx] if j.owns(b)]
                    if not boxes:
                        continue
                    x0, y0, x1, y1 = j.roi
                    alpha = feather(rasterize(boxes, (j.roi_h, j.roi_w), cfg.mask, offset=(x0, y0)),
                                    cfg.mask.feather)[..., None]
                    filled = np.asarray(results[j.id][idx - j.start])
                    if (j.proc_w, j.proc_h) != (j.roi_w, j.roi_h):
                        filled = cv2.resize(filled, (j.roi_w, j.roi_h), interpolation=cv2.INTER_CUBIC)
                    region = out[y0:y1, x0:x1].astype(np.float32)
                    out[y0:y1, x0:x1] = np.round(region + (filled.astype(np.float32) - region) * alpha
                                                 ).clip(0, 255).astype(np.uint8)
                writer.write(out)
                if pw:
                    pw.write(idx, frame)
        if pw:
            pw.close()

    # ------------------------------------------------------------------ debug output
    def _write_preview(self, a: Analysis, path: Path) -> None:
        pw = _PreviewWriter(path, a, self.cfg)
        for idx, frame in enumerate(tqdm(read_frames(a.info), total=a.n_frames, desc="마스크 미리보기",
                                         unit="f", leave=False)):
            if idx >= a.n_frames:
                break
            pw.write(idx, frame)
        pw.close()

    def _write_report(self, a: Analysis, path: Path) -> None:
        report = {
            "video": str(a.info.path), "size": [a.info.width, a.info.height], "fps": float(a.info.fps),
            "frames": a.n_frames, "scenes": a.scenes, "jobs": [j.to_dict() for j in a.jobs],
            "tracks": [t.summary() for t in a.tracks], "config": self.cfg.to_dict(),
        }
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1))


class _PreviewWriter:
    """Half-size preview: red = area that will be filled, yellow = detected
    text that is kept, blue = processing regions."""

    def __init__(self, path: Path, a: Analysis, cfg: Config):
        self.a, self.cfg = a, cfg
        info = a.info
        self.scale = min(1.0, 720 / max(info.width, info.height))
        self.size = (max(2, round(info.width * self.scale / 2) * 2), max(2, round(info.height * self.scale / 2) * 2))
        self.writer = FrameWriter(path, *self.size, info.fps, info.color_space, None, crf=23, preset="veryfast")
        self.dropped: dict[int, list[TextBox]] = {}
        for t in a.tracks:
            if not t.keep:
                for f, b in zip(t.frames, t.boxes):
                    self.dropped.setdefault(f, []).append(b)
        self.cuts = {s for s, _ in a.scenes[1:]}

    def write(self, idx: int, frame: np.ndarray) -> None:
        sx, sy = self.size[0] / self.a.info.width, self.size[1] / self.a.info.height
        img = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        mask = rasterize(self.a.schedule[idx], (self.size[1], self.size[0]), self.cfg.mask, scale=(sx, sy))
        if mask.any():
            red = np.zeros_like(img)
            red[..., 2] = 255
            m = mask.astype(bool)
            img[m] = (img[m] * 0.45 + red[m] * 0.55).astype(np.uint8)
        for b in self.dropped.get(idx, []):
            cv2.polylines(img, [np.round(b.points(scale=(sx, sy))).astype(np.int32)], True, (0, 220, 255), 1)
        for j in self.a.jobs:
            if j.start <= idx < j.end:
                x0, y0, x1, y1 = j.roi
                cv2.rectangle(img, (round(x0 * sx), round(y0 * sy)), (round(x1 * sx) - 1, round(y1 * sy) - 1),
                              (255, 160, 0), 1)
        if idx in self.cuts:
            cv2.rectangle(img, (0, 0), (self.size[0] - 1, self.size[1] - 1), (255, 255, 255), 6)
        self.writer.write(img)

    def close(self) -> None:
        self.writer.close()
