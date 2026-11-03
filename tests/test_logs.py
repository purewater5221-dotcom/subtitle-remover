import logging
from types import SimpleNamespace

from subtitle_remover.logs import TimeReport, format_seconds, log_to_file


def test_log_file_keeps_messages_until_the_block_ends(tmp_path):
    log = logging.getLogger("subtitle_remover")
    log.setLevel(logging.WARNING)
    with log_to_file(tmp_path / "logs" / "run.txt") as path:
        log.info("[1/1] a.mp4")
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("❌ 실패")
    log.info("after the run")
    assert log.level == logging.WARNING  # the logger is left as it was
    log.setLevel(logging.NOTSET)
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert "Python" in first and "GPU" in first  # environment header
    assert "[1/1] a.mp4" in text and "ValueError: boom" in text  # tracebacks are kept
    assert "after the run" not in text


def test_format_seconds():
    assert [format_seconds(s) for s in (0.4, 45, 240, 252.4, 3723)] == ["0초", "45초", "4분", "4분 12초", "1시간 2분 3초"]


def test_time_report_lists_each_video_and_the_total():
    times = TimeReport()
    times.add("01.mp4", SimpleNamespace(seconds=252, duration=58, size=(720, 1280),
                                        timings={"찾기": 20, "메꾸기": 210, "합치기": 22}))
    times.add("02.mp4")  # failed
    times.add("03.mp4", SimpleNamespace(seconds=65, duration=15, size=(720, 1280), timings={}))
    assert times.seconds == 317
    assert times.lines() == [
        "  01.mp4 (720×1280, 58초 영상) → 4분 12초 (찾기 20초 · 메꾸기 3분 30초 · 합치기 22초)",
        "  02.mp4: ❌ 실패",
        "  03.mp4 (720×1280, 15초 영상) → 1분 5초",
        "  자막 지우기 합계: 5분 17초 (영상 2개, 모두 1분 13초 분량)",
    ]
