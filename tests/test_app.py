import pytest

gr = pytest.importorskip("gradio")

from subtitle_remover import app  # noqa: E402


def test_run_jobs_processes_folder_and_makes_comparison(synthetic_clip, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "PREVIEW_DIR", tmp_path / "preview")
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "clip.mp4").write_bytes((synthetic_clip / "clip.mp4").read_bytes())
    out = tmp_path / "out"
    steps = list(app.run_jobs(None, str(folder), "자막 지우기", "빠르게", "전체 화면", "", list(app.TARGETS)[0],
                              str(out), False, False, method="opencv"))
    video, text = steps[-1]
    assert (out / "clip_clean.mp4").exists()
    assert video and video.endswith("clip_compare.mp4")
    assert "끝!" in text and "✅" in text
    # second run skips the finished video
    _, text2 = list(app.run_jobs(None, str(folder), "자막 지우기", "빠르게", "전체 화면", "",
                                 list(app.TARGETS)[0], str(out), False, False, method="opencv"))[-1]
    assert "건너뜀" in text2


def test_run_jobs_reports_bad_input(tmp_path):
    _, text = list(app.run_jobs(None, str(tmp_path / "missing"), "자막 지우기", "보통", "전체 화면", "",
                                list(app.TARGETS)[0], str(tmp_path), False, False))[-1]
    assert "폴더가 없습니다" in text
    _, text = list(app.run_jobs(None, "", "자막 지우기", "보통", "직접 입력", "1,2,3", list(app.TARGETS)[0],
                                str(tmp_path), False, False))[-1]
    assert "영역" in text


def test_ui_builds():
    demo = app.build_ui("opencv")
    assert demo is not None
