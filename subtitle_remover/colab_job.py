"""Process the jobs that colab_run.bat puts into Google Drive (runs on the Colab runtime).

Google Drive layout, under MyDrive/subtitle-remover:
  input/<job>/    the videos and _job.json (file names, sizes, settings)
  output/<job>/   <video>_clean.mp4, _status.json while running, _done.json when finished

A job folder is "pending" while it has _job.json and no output/<job>/_done.json,
so jobs whose runtime could not start are picked up by the next run.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

from .config import config_from_choices
from .video_io import VIDEO_EXTS

log = logging.getLogger("subtitle_remover")

DEFAULT_BASE = "/content/drive/MyDrive/subtitle-remover"
JOB_FILE, STATUS_FILE, DONE_FILE = "_job.json", "_status.json", "_done.json"
WAIT_JOB_SEC = 15 * 60  # Google Drive for desktop may still be uploading
WAIT_FILES_SEC = 60 * 60
POLL_SEC = 10


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def unique_job_name(base: Path, name: str) -> str:
    candidate, k = name, 2
    while (base / "input" / candidate).exists() or (base / "output" / candidate).exists():
        candidate, k = f"{name}_{k}", k + 1
    return candidate


def pending_jobs(base: Path) -> list[str]:
    inp = base / "input"
    if not inp.is_dir():
        return []
    return sorted(d.name for d in inp.iterdir()
                  if d.is_dir() and (d / JOB_FILE).exists() and not (base / "output" / d.name / DONE_FILE).exists())


def missing_files(job_dir: Path, files: list[dict]) -> list[str]:
    missing = []
    for f in files:
        try:
            if (job_dir / f["name"]).stat().st_size != f["size"]:
                missing.append(f["name"])
        except FileNotFoundError:
            missing.append(f["name"])
    return missing


def wait_until(check, timeout: float, on_wait=None) -> bool:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() >= deadline:
            return False
        if on_wait:
            on_wait()
        time.sleep(POLL_SEC)
    return True


def import_uploaded(base: Path, name: str, upload_dir: Path, settings: dict) -> str:
    """Copy videos that were uploaded straight to the runtime into Drive input/<name>."""
    name = unique_job_name(base, name)
    dst = base / "input" / name
    dst.mkdir(parents=True)
    files = []
    for p in sorted(upload_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            shutil.copyfile(p, dst / p.name)
            files.append({"name": p.name, "size": p.stat().st_size})
    write_json(dst / JOB_FILE, {"version": 1, "name": name, "created": now(), "files": files, "settings": settings})
    print(f"Drive에 업로드: input/{name} ({len(files)}개)", flush=True)
    return name


def run_job(base: Path, name: str, work: Path, keep_outputs: bool = False) -> dict:
    from .pipeline import SubtitleRemover

    job_dir, out_dir = base / "input" / name, base / "output" / name
    job = read_json(job_dir / JOB_FILE)
    files = job.get("files", [])
    out_dir.mkdir(parents=True, exist_ok=True)
    status = {"job": name, "total": len(files), "done": 0, "current": None, "state": "waiting", "updated": now()}
    write_json(out_dir / STATUS_FILE, status)
    print(f"\n=== 작업 {name}: 영상 {len(files)}개 ===", flush=True)

    last_report = [0.0]

    def report_wait():  # at most once a minute
        if time.monotonic() - last_report[0] >= 60:
            last_report[0] = time.monotonic()
            left = missing_files(job_dir, files)
            print(f"  Drive에 영상이 다 올라오기를 기다리는 중... (남은 파일 {len(left)}개)", flush=True)

    wait_until(lambda: not missing_files(job_dir, files), WAIT_FILES_SEC, report_wait)
    missing = missing_files(job_dir, files)
    if missing:
        print(f"  ⚠️ 끝내 올라오지 않은 파일은 건너뜀: {', '.join(missing)}", flush=True)

    s = job.get("settings", {})
    cfg = config_from_choices(s.get("quality", "보통"), s.get("region", "전체 화면"), s.get("target", "overlay"),
                              s.get("custom_region", ""), s.get("method", "propainter"))
    cfg.work_dir = str(work / "cache")
    remover = SubtitleRemover(cfg)
    results = []
    todo = [f for f in files if f["name"] not in missing]
    for i, f in enumerate(todo, 1):
        status.update(done=i - 1, current=f["name"], state="processing", updated=now())
        write_json(out_dir / STATUS_FILE, status)
        print(f"\n[{i}/{len(todo)}] {f['name']}", flush=True)
        local_in = work / "in" / name / f["name"]
        local_out = work / "out" / name / f"{Path(f['name']).stem}_clean.mp4"
        local_in.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(job_dir / f["name"], local_in)
            r = remover.process(local_in, local_out)
            shutil.copyfile(local_out, out_dir / local_out.name)
            results.append({"file": f["name"], "output": local_out.name, "removed": r.removed,
                            "seconds": round(r.seconds, 1), "note": r.note})
            print(f"  ✅ {r.seconds:.0f}초, 지운 글자 {r.removed}개 → output/{name}/{local_out.name}", flush=True)
        except Exception as e:  # noqa: BLE001 - keep going with the next video
            log.exception("  ❌ %s 실패", f["name"])
            results.append({"file": f["name"], "error": str(e)})
        finally:
            local_in.unlink(missing_ok=True)
            if not keep_outputs:  # kept when the results are downloaded from the runtime afterwards
                local_out.unlink(missing_ok=True)

    status.update(done=len(todo), current=None, state="finished", updated=now())
    write_json(out_dir / STATUS_FILE, status)
    done = {"job": name, "finished": now(), "results": results, "missing": missing}
    write_json(out_dir / DONE_FILE, done)
    return done


def main(base: str | Path = DEFAULT_BASE, job: str | None = None, uploaded_dir: str | None = None,
         settings: dict | None = None, work: str | Path = "/content/work", keep_outputs: bool = False) -> list[dict]:
    """Process the given job (waiting for it to reach Drive) and any other pending jobs."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
    base, work = Path(base), Path(work)
    (base / "input").mkdir(parents=True, exist_ok=True)
    (base / "output").mkdir(parents=True, exist_ok=True)

    if uploaded_dir:
        job = import_uploaded(base, job or datetime.now().strftime("%Y%m%d%H"), Path(uploaded_dir), settings or {})
    elif job and not (base / "input" / job / JOB_FILE).exists():
        print(f"Drive의 input/{job} 폴더가 동기화되기를 기다리는 중...", flush=True)
        if not wait_until(lambda: (base / "input" / job / JOB_FILE).exists(), WAIT_JOB_SEC):
            print(f"⚠️ input/{job} 이(가) Drive에 나타나지 않았어요. Google Drive 앱의 업로드 상태를 확인해 주세요.",
                  flush=True)

    names = pending_jobs(base)
    if job in names:  # this run's job first, then leftovers from earlier runs
        names.remove(job)
        names.insert(0, job)
    if not names:
        print("처리할 작업이 없어요.", flush=True)
    results = [run_job(base, n, work, keep_outputs) for n in names]
    summary = {"jobs": [{"name": d["job"], "outputs": [r["output"] for r in d["results"] if "output" in r],
                         "errors": [r["file"] for r in d["results"] if "error" in r]} for d in results]}
    print("@@RESULT " + json.dumps(summary, ensure_ascii=False), flush=True)
    return results
