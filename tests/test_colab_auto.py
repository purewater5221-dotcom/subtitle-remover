"""End-to-end test of colab_run (tools/colab_auto.py) against a fake Colab CLI.

The fake runs the real bootstrap and job code locally (with the fast OpenCV
backend), so everything except Google's servers is exercised.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path, synthetic_clip):
    home = tmp_path / "home"
    cfg = home / ".config" / "subtitle-remover"
    cfg.mkdir(parents=True)
    (cfg / "github_token.txt").write_text("github_pat_test")
    (cfg / "colab.json").write_text(json.dumps({"method": "opencv"}))
    videos = tmp_path / "my videos"
    videos.mkdir()
    (videos / "clip one.mp4").write_bytes((synthetic_clip / "clip.mp4").read_bytes())
    (videos / "notes.txt").write_text("not a video")
    drive = tmp_path / "drive"
    drive.mkdir()
    e = {**os.environ, "HOME": str(home), "SUBRM_COLAB": str(ROOT / "tests" / "fake_colab.py"),
         "SUBRM_VM_CONTENT": str(tmp_path / "vm" / "content"), "FAKE_COLAB_HOME": str(tmp_path / "colab"),
         "FAKE_COLAB_DRIVE": str(drive), "SUBRM_NO_OPEN": "1", "SUBRM_SKIP_TOKEN_CHECK": "1",
         "SUBRM_JOB_EXTRA": json.dumps({"code_dir": str(ROOT), "skip_install": True, "flush_drive": False})}
    return {"env": e, "videos": videos, "drive": drive, "vm": tmp_path / "vm" / "content", "colab": tmp_path / "colab"}


def run(env, *args):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "colab_auto.py"), *args], env=env,
                          capture_output=True, text=True, timeout=600)


def test_run_with_drive_app(env):
    e = {**env["env"], "SUBRM_DRIVE_ROOT": str(env["drive"])}
    res = run(e, "run", str(env["videos"]))
    assert res.returncode == 0, res.stdout + res.stderr
    jobs = list((env["drive"] / "subtitle-remover" / "input").iterdir())
    assert len(jobs) == 1 and len(jobs[0].name) == 10  # YYYYMMDDHH
    job = json.loads((jobs[0] / "_job.json").read_text(encoding="utf-8"))
    assert [f["name"] for f in job["files"]] == ["clip one.mp4"]
    out = env["drive"] / "subtitle-remover" / "output" / jobs[0].name
    assert (out / "clip one_clean.mp4").exists()
    done = json.loads((out / "_done.json").read_text(encoding="utf-8"))
    assert done["results"][0]["output"] == "clip one_clean.mp4" and done["missing"] == []
    log = (out / "_log.txt").read_text(encoding="utf-8")
    assert "[1/1] clip one.mp4" in log and "⏱" in log and "✅" in log
    assert not (env["vm"] / ".gh_token").exists()  # token removed from the runtime after use
    calls = (env["colab"] / "calls.log").read_text()
    assert "new -s subrm-" in calls and "--gpu T4" in calls and calls.strip().splitlines()[-1].startswith("stop")
    assert json.loads((env["colab"] / "sessions.json").read_text()) == []  # runtime stopped

    # a second run in the same hour gets its own folder
    res = run(e, "run", str(env["videos"]))
    assert res.returncode == 0, res.stdout + res.stderr
    names = sorted(p.name for p in (env["drive"] / "subtitle-remover" / "output").iterdir())
    assert len(names) == 2 and names[1] == names[0] + "_2"


def test_run_without_drive_app_uploads_in_pieces(env):
    e = {**env["env"], "SUBRM_NO_DRIVE_APP": "1", "SUBRM_CHUNK": "100000", "FAKE_COLAB_MAX_UPLOAD": "150000"}
    res = run(e, "run", str(env["videos"]))
    assert res.returncode == 0, res.stdout + res.stderr
    out_dirs = list((env["drive"] / "subtitle-remover" / "output").iterdir())
    assert len(out_dirs) == 1
    in_drive = out_dirs[0] / "clip one_clean.mp4"
    downloaded = env["videos"] / "subtitle-remover-output" / out_dirs[0].name / "clip one_clean.mp4"
    assert downloaded.read_bytes() == in_drive.read_bytes()
    assert (downloaded.parent / "_log.txt").read_bytes() == (out_dirs[0] / "_log.txt").read_bytes()
    original = (env["videos"] / "clip one.mp4").read_bytes()
    assert (env["drive"] / "subtitle-remover" / "input" / out_dirs[0].name / "clip one.mp4").read_bytes() == original
    assert not list((env["vm"] / "upload").rglob("*.part*"))  # pieces were joined and removed


def test_no_gpu_leaves_job_for_next_time(env):
    e = {**env["env"], "SUBRM_DRIVE_ROOT": str(env["drive"]), "FAKE_COLAB_NO_GPU": "1"}
    res = run(e, "run", str(env["videos"]))
    assert res.returncode == 1 and "T4" in res.stdout
    pending = list((env["drive"] / "subtitle-remover" / "input").iterdir())
    assert len(pending) == 1 and (pending[0] / "_job.json").exists()

    # the next successful run also processes the leftover job
    e.pop("FAKE_COLAB_NO_GPU")
    res = run(e, "run", str(env["videos"]))
    assert res.returncode == 0, res.stdout + res.stderr
    done = [p for p in (env["drive"] / "subtitle-remover" / "output").iterdir() if (p / "_done.json").exists()]
    assert len(done) == 2


def test_missing_setup_is_reported(env):
    e = {**env["env"]}
    e.pop("SUBRM_COLAB")
    res = run(e, "run", str(env["videos"]))
    assert res.returncode == 1 and "colab_setup.bat" in res.stdout


def test_echo_hides_internal_lines_and_shows_prompts(capsys):
    sys.path.insert(0, str(ROOT / "tools"))
    import colab_auto

    e = colab_auto._Echo(quiet=False)
    for part in ["Session ", "READY.\n@@RES", "ULT {}\nEnter the authorization code: "]:
        e.write(part)
    assert capsys.readouterr().out == "Session READY.\nEnter the authorization code: "

    q = colab_auto._Echo(quiet=True)
    q.write("[colab] Uploaded\n")
    assert capsys.readouterr().out == ""
    q.unmute()
    q.write("To authorize, visit this URL\n")
    assert capsys.readouterr().out == "[colab] Uploaded\nTo authorize, visit this URL\n"


def test_colab_job_skips_files_that_never_arrive(tmp_path, monkeypatch, synthetic_clip):
    from subtitle_remover import colab_job

    monkeypatch.setattr(colab_job, "WAIT_FILES_SEC", 0)
    base = tmp_path / "drive" / "subtitle-remover"
    job_dir = base / "input" / "2026010112"
    job_dir.mkdir(parents=True)
    clip = (synthetic_clip / "clip.mp4").read_bytes()
    (job_dir / "a.mp4").write_bytes(clip)
    (job_dir / "b.mp4").write_bytes(clip[:100])  # still uploading
    files = [{"name": "a.mp4", "size": len(clip)}, {"name": "b.mp4", "size": len(clip)}]
    colab_job.write_json(job_dir / "_job.json", {"files": files, "settings": {"method": "opencv", "quality": "빠르게"}})
    (base / "input" / "2025123123").mkdir()  # no _job.json: not a job
    assert colab_job.pending_jobs(base) == ["2026010112"]

    results = colab_job.main(base=base, job="2026010112", work=tmp_path / "work")
    done = results[0]
    assert done["missing"] == ["b.mp4"] and done["results"][0]["output"] == "a_clean.mp4"
    assert (base / "output" / "2026010112" / "a_clean.mp4").exists()
    log = (base / "output" / "2026010112" / "_log.txt").read_text(encoding="utf-8")
    assert "b.mp4" in log and "[1/1] a.mp4" in log and "⏱" in log
    assert colab_job.pending_jobs(base) == []
    assert colab_job.unique_job_name(base, "2026010112") == "2026010112_2"


def test_colab_job_installs_only_missing_packages(monkeypatch):
    import importlib.util

    from subtitle_remover import colab_job

    real = importlib.util.find_spec
    missing = {"rapidocr", "onnx", "onnx2torch"}  # e.g. an older bootstrap installed only the rest
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name in missing else real(name, *a))
    calls = []
    done = subprocess.CompletedProcess
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd[3:]) or done(cmd, 0))
    colab_job.install_packages()
    assert calls == [["install", "-q", "--no-deps", "rapidocr==3.10.0"], ["install", "-q", "onnx", "onnx2torch"]]


def test_setup_checks_runtime_and_drive(env):
    res = run(env["env"], "setup")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "준비 완료" in res.stdout and "GPU: none" in res.stdout  # the fake runtime has no nvidia-smi
    assert (env["drive"] / "subtitle-remover" / "input").is_dir()
    calls = (env["colab"] / "calls.log").read_text().splitlines()
    assert calls[0] == "sessions" and calls[1].startswith("new -s subrm-setup-") and calls[-1].startswith("stop")


def test_setup_asks_for_a_new_token_when_the_saved_one_is_rejected(env, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import colab_auto

    monkeypatch.setenv("HOME", env["env"]["HOME"])
    monkeypatch.delenv("SUBRM_SKIP_TOKEN_CHECK", raising=False)
    monkeypatch.setattr(colab_auto, "check_token", lambda t: t == "github_pat_new")
    monkeypatch.setattr("builtins.input", lambda prompt="": "github_pat_new")
    path = colab_auto.ensure_token(ask=True)
    assert path.read_text() == "github_pat_new"
    assert colab_auto.ensure_token(ask=False) == path


def test_first_setup_walks_through_sign_in_and_drive_permission(env, tmp_path):
    e = {**env["env"], "FAKE_COLAB_AUTH": "1"}
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "colab_auto.py"), "setup"], env=e,
                         input="4/0AUTHCODE\n\n", capture_output=True, text=True, timeout=300)
    out = res.stdout
    assert res.returncode == 0, out + res.stderr
    for step in ("[1/5]", "[2/5]", "[3/5]", "[4/5]", "[5/5]"):
        assert step in out
    assert out.count("👉 브라우저에서 위 주소를 열었어요") == 2  # Google sign-in, then Drive permission
    assert "Enter the authorization code:" in out and "Press Enter after you have granted access" in out
    assert "저장된 토큰을 그대로" in out and "✅ 구글 계정 연결 완료" in out and "✅ Google Drive 연결 완료" in out
    # our hint comes before the CLI's prompt, which is repeated so the cursor sits right after it
    assert out.index("👉") < out.rindex("Enter the authorization code:")
