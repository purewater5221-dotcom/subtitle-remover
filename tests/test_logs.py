import logging

from subtitle_remover.logs import log_to_file


def test_log_file_keeps_messages_until_the_block_ends(tmp_path):
    log = logging.getLogger("subtitle_remover")
    with log_to_file(tmp_path / "logs" / "run.txt") as path:
        log.info("[1/1] a.mp4")
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("❌ 실패")
    log.info("after the run")
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert "Python" in first and "GPU" in first  # environment header
    assert "[1/1] a.mp4" in text and "ValueError: boom" in text  # tracebacks are kept
    assert "after the run" not in text
