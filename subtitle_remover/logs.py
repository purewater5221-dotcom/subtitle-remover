"""Keep a copy of a run's messages in a text file next to its results."""

from __future__ import annotations

import logging
import platform
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

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
