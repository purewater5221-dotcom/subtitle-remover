# Runs on the Colab runtime through `colab exec` (sent by tools/colab_auto.py,
# which puts the JOB dict above this code). Keep this file ASCII-only: the Colab
# CLI reads it with the system encoding on Windows.
import os
import subprocess
import sys
from pathlib import Path

JOB = globals()["JOB"]  # defined by the lines tools/colab_auto.py puts above this file
os.environ["TQDM_DISABLE"] = "1"  # progress bars do not render through `colab exec`
CONTENT = Path(JOB["vm_content"])
REPO_DIR = Path(JOB.get("code_dir") or CONTENT / "subtitle-remover")


def sh(*cmd, secret=""):
    res = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if res.returncode != 0:
        text = (res.stderr or res.stdout or "").strip()
        raise SystemExit("command failed: " + (text.replace(secret, "***") if secret else text))
    return res.stdout


def fetch_code():
    token_file = CONTENT / ".gh_token"
    token = token_file.read_text().strip() if token_file.exists() else ""
    token_file.unlink(missing_ok=True)
    if JOB.get("code_dir"):
        return
    public = f"https://github.com/{JOB['repo']}.git"
    url = f"https://x-access-token:{token}@github.com/{JOB['repo']}.git" if token else public
    if (REPO_DIR / ".git").exists():
        sh("git", "-C", REPO_DIR, "pull", "-q", url, JOB["branch"], secret=token)
    else:
        sh("git", "clone", "-q", "--depth", "1", "-b", JOB["branch"], url, REPO_DIR, secret=token)
        sh("git", "-C", REPO_DIR, "remote", "set-url", "origin", public)
    print("code from GitHub:", sh("git", "-C", REPO_DIR, "log", "-1", "--format=%h %cd", "--date=short").strip(),
          flush=True)


def install():
    if JOB.get("skip_install"):
        return
    print("installing packages...", flush=True)
    sh(sys.executable, "-m", "pip", "install", "-q", "--no-deps", "rapidocr==3.10.0")
    sh(sys.executable, "-m", "pip", "install", "-q", "onnxruntime-gpu", "einops")


fetch_code()
install()
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
from subtitle_remover import colab_job  # noqa: E402

if not JOB.get("skip_install"):
    from subtitle_remover.inpaint.propainter import ensure_propainter

    ensure_propainter()
try:
    colab_job.main(base=JOB["drive_base"], job=JOB["job"], uploaded_dir=JOB.get("uploaded_dir"),
                   settings=JOB.get("settings"), work=CONTENT / "work", keep_outputs=JOB.get("keep_outputs", False))
finally:
    if JOB.get("flush_drive", True):
        try:  # make sure everything written to Drive is uploaded before the runtime stops
            from google.colab import drive

            drive.flush_and_unmount()
            print("Google Drive: all files saved", flush=True)
        except Exception as e:  # noqa: BLE001
            print("Google Drive flush failed:", e, "- waiting a minute for uploads to finish", flush=True)
            import time

            time.sleep(60)
