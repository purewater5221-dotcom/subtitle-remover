"""Remove burned-in subtitles from short-form videos by video inpainting."""

from .config import Config, apply_quality, parse_region

__version__ = "0.1.0"

__all__ = ["Config", "apply_quality", "parse_region", "SubtitleRemover"]


def __getattr__(name):
    if name == "SubtitleRemover":
        from .pipeline import SubtitleRemover

        return SubtitleRemover
    raise AttributeError(name)
