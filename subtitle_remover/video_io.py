"""FFmpeg-based video reading and writing.

Frames are decoded as BGR24 at a constant frame rate, so every pass over a
video yields exactly the same frame sequence and the original audio track
stays in sync when it is muxed back in.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import numpy as np

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv"}

# Audio codecs that can be stream-copied into an .mp4 container.
_MP4_AUDIO_COPY = {"aac", "mp3", "ac3", "eac3", "alac"}

# Common frame rates; a probed rate within 0.5% of one of these is snapped to it.
_STD_RATES = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
              Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60)]

# Without accurate rounding swscale's RGB->YUV conversion is biased (gray 128 comes
# back as ~124), which would visibly shift the colors of every re-encoded frame.
_SWS_FLAGS = "bicubic+accurate_rnd+full_chroma_int+full_chroma_inp"

# ffprobe color_space -> swscale color matrix name
_MATRIX = {"bt709": "bt709", "smpte170m": "bt601", "bt470bg": "bt601", "fcc": "fcc",
           "smpte240m": "smpte240m", "bt2020nc": "bt2020", "bt2020c": "bt2020"}


class VideoError(RuntimeError):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise VideoError(f"{name}을(를) 찾을 수 없습니다. FFmpeg를 설치해 주세요.")
    return path


@lru_cache(maxsize=1)
def ffmpeg_major_version() -> int:
    out = subprocess.run([_tool("ffmpeg"), "-version"], capture_output=True, text=True).stdout
    m = re.search(r"ffmpeg version n?(\d+)", out)
    return int(m.group(1)) if m else 6


def _cfr_args() -> list[str]:
    # -fps_mode replaced -vsync in FFmpeg 5.1
    return ["-fps_mode", "cfr"] if ffmpeg_major_version() >= 5 else ["-vsync", "cfr"]


@dataclass
class VideoInfo:
    path: Path
    width: int  # displayed size (rotation applied)
    height: int
    fps: Fraction
    duration: float
    has_audio: bool
    audio_codec: str | None
    color_space: str | None
    color_primaries: str | None
    color_transfer: str | None

    @property
    def est_frames(self) -> int:
        return max(1, round(self.duration * float(self.fps)))

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in ("smpte2084", "arib-std-b67")


def _parse_rate(s: str | None) -> Fraction | None:
    if not s:
        return None
    try:
        r = Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None
    return r if r > 0 else None


def _snap_rate(r: Fraction) -> Fraction:
    best = min(_STD_RATES, key=lambda std: abs(float(r) / float(std) - 1))
    if abs(float(r) / float(best) - 1) < 0.005:
        return best
    return r.limit_denominator(1001)


def _rotation(stream: dict) -> int:
    rot = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if not rot and "rotate" in (stream.get("tags") or {}):
        rot = int(float(stream["tags"]["rotate"]))
    return rot % 360


def probe(path: str | Path) -> VideoInfo:
    path = Path(path)
    if not path.exists():
        raise VideoError(f"파일이 없습니다: {path}")
    cmd = [_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise VideoError(f"ffprobe 실패 ({path.name}): {res.stderr.strip()}")
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    vids = [s for s in streams if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")]
    if not vids:
        raise VideoError(f"영상 스트림이 없습니다: {path.name}")
    v = vids[0]
    auds = [s for s in streams if s.get("codec_type") == "audio"]

    w, h = int(v["width"]), int(v["height"])
    if _rotation(v) % 180 == 90:
        w, h = h, w
    fps = _parse_rate(v.get("avg_frame_rate"))
    if fps is None or fps > 240:
        fps = _parse_rate(v.get("r_frame_rate")) or Fraction(30)
    fps = _snap_rate(fps)
    duration = float(v.get("duration") or (data.get("format") or {}).get("duration") or 0.0)

    return VideoInfo(
        path=path, width=w, height=h, fps=fps, duration=duration,
        has_audio=bool(auds), audio_codec=auds[0].get("codec_name") if auds else None,
        color_space=v.get("color_space"), color_primaries=v.get("color_primaries"),
        color_transfer=v.get("color_transfer"),
    )


def read_frames(info: VideoInfo) -> Iterator[np.ndarray]:
    """Yield BGR uint8 frames of shape (H, W, 3) at a constant frame rate."""
    cmd = [_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(info.path),
           "-map", "0:v:0", "-an", "-sn", "-dn", *_cfr_args(), "-r", str(info.fps),
           "-sws_flags", _SWS_FLAGS, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    frame_bytes = info.width * info.height * 3
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, bufsize=frame_bytes)
        assert proc.stdout is not None
        try:
            while True:
                buf = proc.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
                yield np.frombuffer(buf, np.uint8).reshape(info.height, info.width, 3)
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
            rc = proc.wait()
        if rc not in (0, -9):
            err.seek(0)
            raise VideoError(f"디코딩 실패 ({info.path.name}): {err.read().decode(errors='replace')[-800:]}")


class FrameWriter:
    """Encode BGR frames to H.264 and mux the audio of `audio_from` back in."""

    def __init__(self, out_path: str | Path, width: int, height: int, fps: Fraction,
                 color_space: str | None = None, audio_from: VideoInfo | None = None,
                 crf: int = 17, preset: str = "medium"):
        self.out_path = Path(out_path)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.width, self.height = width, height

        cmd = [_tool("ffmpeg"), "-v", "error", "-nostdin", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
               "-r", str(fps), "-i", "-"]
        if audio_from is not None and audio_from.has_audio:
            cmd += ["-i", str(audio_from.path), "-map", "0:v:0", "-map", "1:a:0"]
            if audio_from.audio_codec in _MP4_AUDIO_COPY:
                cmd += ["-c:a", "copy"]
            else:
                cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-map", "0:v:0"]

        # Convert back to YUV with the same matrix ffmpeg used for decoding, so
        # untouched pixels keep their original colors.
        matrix = _MATRIX.get(color_space or "")
        vf = f"scale=out_range=tv:flags={_SWS_FLAGS}"
        if matrix:
            vf += f":out_color_matrix={matrix}"
        if width % 2 or height % 2:
            vf = f"pad=ceil(iw/2)*2:ceil(ih/2)*2,{vf}"
        vf += ",format=yuv420p"
        cmd += ["-vf", vf, "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-color_range", "tv"]
        if matrix:
            cmd += ["-colorspace", color_space]
            if matrix == "bt709":
                cmd += ["-color_primaries", "bt709", "-color_trc", "bt709"]
        cmd += ["-movflags", "+faststart", str(self.out_path)]

        self._err = tempfile.TemporaryFile()
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self._err)

    def write(self, frame: np.ndarray) -> None:
        if frame.shape != (self.height, self.width, 3) or frame.dtype != np.uint8:
            raise ValueError(f"frame shape/dtype mismatch: {frame.shape} {frame.dtype}")
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(np.ascontiguousarray(frame).data)
        except BrokenPipeError:
            self._fail()

    def close(self) -> None:
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.close()
        except BrokenPipeError:
            pass
        if self._proc.wait() != 0:
            self._fail()
        self._err.close()

    def _fail(self):
        self._proc.wait()
        self._err.seek(0)
        msg = self._err.read().decode(errors="replace")[-800:]
        raise VideoError(f"인코딩 실패 ({self.out_path.name}): {msg}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.close()
        else:
            if self._proc.poll() is None:
                self._proc.kill()
            self._proc.wait()
            self._err.close()


def copy_as_mp4(src: str | Path, dst: str | Path) -> None:
    """Copy a video unchanged into an .mp4 container (plain copy if that fails)."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() != ".mp4":
        res = subprocess.run([_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0",
                              "-map", "0:a?", "-c", "copy", "-movflags", "+faststart", str(dst)],
                             capture_output=True)
        if res.returncode == 0:
            return
    shutil.copyfile(src, dst)


def list_videos(path: str | Path) -> list[Path]:
    path = Path(path)
    if path.is_file():
        return [path]
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS
                  and not p.name.startswith("."))
