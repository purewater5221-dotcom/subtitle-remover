"""Keep a copy of a run's messages in a text file next to its results, and sum up the times."""

from __future__ import annotations

import logging
import platform
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .device import gpu_info

log = logging.getLogger("subtitle_remover")
ROOT = Path(__file__).resolve().parents[1]


class _AppendHandler(logging.Handler):
    """Opens the file for every record, so a copy on Google Drive is uploaded as it grows."""

    def __init__(self, path: Path):
        super().__init__(logging.INFO)
        self.path = path
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(self.format(record) + "\n")
        except Exception:  # noqa: BLE001 - a log file must never stop a run
            self.handleError(record)


def format_seconds(sec: float) -> str:
    """45초, 4분 12초, 1시간 2분 3초"""
    s = round(sec)
    text = " ".join(f"{n}{unit}" for n, unit in ((s // 3600, "시간"), (s // 60 % 60, "분"), (s % 60, "초")) if n)
    return text or "0초"


class TimeReport:
    """How long each video took, listed at the end of a run."""

    def __init__(self):
        self.rows: list[tuple[str, Any]] = []  # (file name, VideoResult or None if it failed)

    def add(self, name: str, result: Any = None) -> None:
        self.rows.append((name, result))

    @property
    def seconds(self) -> float:
        return sum(r.seconds for _, r in self.rows if r is not None)

    def lines(self) -> list[str]:
        out = []
        for name, r in self.rows:
            if r is None:
                out.append(f"  {name}: ❌ 실패")
                continue
            stages = " · ".join(f"{k} {format_seconds(v)}" for k, v in r.timings.items())
            out.append(f"  {name} ({r.size[0]}×{r.size[1]}, {format_seconds(r.duration)} 영상) → "
                       f"{format_seconds(r.seconds)}" + (f" ({stages})" if stages else ""))
        done = [r for _, r in self.rows if r is not None]
        if len(done) > 1:
            out.append(f"  자막 지우기 합계: {format_seconds(self.seconds)} "
                       f"(영상 {len(done)}개, 모두 {format_seconds(sum(r.duration for r in done))} 분량)")
        return out

    def log(self) -> None:
        if self.rows:
            log.info("⏱ 걸린 시간")
            for line in self.lines():
                log.info(line)


def code_version() -> str:
    """The commit when the code is a git clone (as on Colab), else the package version."""
    if (ROOT / ".git").exists():
        try:
            res = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %cd", "--date=short"],
                                 capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return __version__


def environment() -> str:
    try:
        import torch

        torch_version = torch.__version__
    except ImportError:
        torch_version = "없음"
    gpu = gpu_info()
    return (f"코드 {code_version()} · Python {platform.python_version()} · PyTorch {torch_version} · "
            f"GPU {f'{gpu[0]} ({gpu[1]:.0f}GB)' if gpu else '없음'}")


@contextmanager
def log_to_file(path: str | Path):
    """Also write the subtitle_remover log to `path` (appending, each line with its time)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _AppendHandler(path)
    log.addHandler(handler)
    if log.getEffectiveLevel() > logging.INFO:
        log.setLevel(logging.INFO)
    log.info("── %s · %s", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"), environment())
    try:
        yield path
    finally:
        log.removeHandler(handler)
