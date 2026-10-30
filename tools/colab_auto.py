"""Remove subtitles on Google Colab, driven from this computer.

    python tools/colab_auto.py setup            # once (colab_setup.bat)
    python tools/colab_auto.py run [FOLDER]     # each time (colab_run.bat)
    python tools/colab_auto.py stop             # stop leftover runtimes (colab_stop.bat)

Uses Google's official Colab CLI (`google-colab-cli`, installed into .venv-colab)
to start a T4 runtime, mount Google Drive, fetch the latest code from GitHub on
the runtime, process the videos and stop the runtime again.

Videos go to Google Drive as subtitle-remover/input/YYYYMMDDHH: through
"Google Drive for desktop" when it is installed (copying into its folder), or
uploaded to the runtime directly otherwise. Results are written to
subtitle-remover/output/YYYYMMDDHH. Standard library only.
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv-colab"
REPO = "purewater5221-dotcom/subtitle-remover"
BRANCH = "main"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv"}
DRIVE_FOLDER_NAMES = ("My Drive", "내 드라이브")
VM_CONTENT = os.environ.get("SUBRM_VM_CONTENT", "/content")  # tests point this at a fake runtime
CHUNK = int(os.environ.get("SUBRM_CHUNK", 16 * 1024 * 1024))  # per upload/download request
EXEC_TIMEOUT = 8 * 3600
DEFAULT_SETTINGS = {"quality": "보통", "region": "전체 화면", "custom_region": "", "target": "overlay",
                    "method": "propainter", "gpu": "T4", "drive_root": ""}


class Stop(Exception):
    """Abort with a message for the user."""


def say(msg: str = "") -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- local config
def config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "subtitle-remover"
    return Path.home() / ".config" / "subtitle-remover"


def token_path() -> Path:
    return config_dir() / "github_token.txt"


def load_settings() -> dict:
    path = config_dir() / "colab.json"
    settings = dict(DEFAULT_SETTINGS)
    if path.exists():
        settings.update(json.loads(path.read_text(encoding="utf-8-sig")))
    return settings


def save_settings(settings: dict) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "colab.json").write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")


def find_drive_root(settings: dict) -> Path | None:
    """The local folder of Google Drive for desktop ("My Drive" / "내 드라이브")."""
    configured = os.environ.get("SUBRM_DRIVE_ROOT") or settings.get("drive_root")
    if configured:
        return Path(configured) if Path(configured).is_dir() else None
    if os.environ.get("SUBRM_NO_DRIVE_APP"):
        return None
    home = Path.home()
    candidates = []
    if os.name == "nt":
        candidates += [Path(f"{letter}:\\") / n for letter in "GHIJKLMNOPQRSTUVWXYZDEF" for n in DRIVE_FOLDER_NAMES]
    candidates += [home / n for n in DRIVE_FOLDER_NAMES] + [home / "Google Drive" / n for n in DRIVE_FOLDER_NAMES]
    candidates += sorted((home / "Library" / "CloudStorage").glob("GoogleDrive-*/*"))  # macOS
    for c in candidates:
        try:
            if c.is_dir() and c.name in DRIVE_FOLDER_NAMES:
                return c
        except OSError:
            continue
    return None


def list_videos(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS
                  and not p.stem.endswith(("_clean", "_mask")) and not p.name.startswith("."))


def open_folder(path: Path) -> None:
    if os.environ.get("SUBRM_NO_OPEN"):
        return
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- Colab CLI
def colab_cmd() -> list[str]:
    if os.environ.get("SUBRM_COLAB"):  # tests
        return [sys.executable, os.environ["SUBRM_COLAB"]]
    exe = VENV / ("Scripts/colab.exe" if os.name == "nt" else "bin/colab")
    if not exe.exists():
        raise Stop("Colab CLI가 설치돼 있지 않아요. 먼저 colab_setup.bat 을 실행해 주세요.")
    return [str(exe)]


class _Echo:
    """Shows CLI output as it arrives, except "@@..." lines meant for this script.

    Partial lines (prompts) are shown immediately. In quiet mode everything is
    held back until unmute() is called.
    """

    def __init__(self, quiet: bool):
        self.quiet, self.held, self.line, self.shown = quiet, "", "", 0

    def unmute(self) -> None:
        if self.quiet:
            self.quiet = False
            self.write(self.held)
            self.held = ""

    def write(self, part: str) -> None:
        if self.quiet:
            self.held += part
            return
        self.line += part
        while "\n" in self.line:
            line, self.line = self.line.split("\n", 1)
            if not line.startswith("@@"):
                sys.stdout.write(line[self.shown:] + "\n")
            self.shown = 0
        if self.line and not self.line.startswith("@"):
            sys.stdout.write(self.line[self.shown:])
            self.shown = len(self.line)
        sys.stdout.flush()


def colab(*args: str, check: bool = True, quiet: bool = False) -> tuple[int, str]:
    """Run a Colab CLI command, echoing its output live.

    Sign-in and Drive permission links the CLI prints are opened in the browser;
    the user's typing (authorization code, Enter) goes straight to the CLI.
    """
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([*colab_cmd(), *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    assert proc.stdout is not None
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    echo = _Echo(quiet)
    text, opened = "", set()
    while chunk := proc.stdout.read1(4096):
        part = decoder.decode(chunk)
        text += part
        if re.search(r"visit|authorization code", text[-3000:], re.I):
            echo.unmute()  # the CLI is asking the user something: never hide that
        echo.write(part)
        for m in re.finditer(r"visit[^\n]*\n\s*(https://\S+)\s", text[-3000:], re.I):
            if m.group(1) not in opened:
                opened.add(m.group(1))
                say("\n👉 브라우저에서 위 주소를 열었어요. 허용한 뒤 이 창으로 돌아와 주세요.")
                webbrowser.open(m.group(1))
    rc = proc.wait()
    if check and rc != 0:
        raise Stop(f"Colab 명령이 실패했어요: colab {' '.join(args[:1])} (코드 {rc})")
    return rc, text


def colab_exec_code(session: str, code: str, timeout: int = 600, quiet: bool = True) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
    try:
        return colab("exec", "-s", session, "-f", f.name, "--timeout", str(timeout), quiet=quiet)[1]
    finally:
        os.unlink(f.name)


def start_runtime(session: str, gpu: str = "T4") -> None:
    say(f"\n▶ Colab {gpu} 런타임을 켜는 중... (1분 정도 걸려요)")
    rc, out = colab("new", "-s", session, "--gpu", gpu, check=False)
    if rc != 0:
        hint = "무료 사용량이 다 찼거나 지금 GPU가 부족할 수 있어요" if gpu == "T4" else \
            f"{gpu}는 Colab Pro 이상에서만 쓸 수 있어요. colab.json의 gpu를 T4로 바꾸거나"
        raise Stop(f"{gpu} GPU 런타임을 받지 못했어요. {hint}. 잠시 뒤 다시 실행해 주세요.")


def vm_path(remote: str) -> str:
    """Absolute path on the runtime of a CLI path like "content/upload/x.mp4"."""
    return VM_CONTENT + "/" + remote.split("/", 1)[1]


def upload_file(session: str, local: Path, remote: str) -> None:
    """Upload in pieces (each `colab upload` sends the whole file in one request)."""
    size = local.stat().st_size
    if size <= CHUNK:
        colab("upload", "-s", session, str(local), remote, quiet=True)
        return
    parts = []
    with tempfile.TemporaryDirectory() as tmp, open(local, "rb") as src:
        i = 0
        while block := src.read(CHUNK):
            part = Path(tmp) / f"part{i:04d}"
            part.write_bytes(block)
            colab("upload", "-s", session, str(part), f"{remote}.part{i:04d}", quiet=True)
            parts.append(f"{remote}.part{i:04d}")
            i += 1
            say(f"    {min(size, i * CHUNK) * 100 // size}%")
    colab_exec_code(session, "import os\n"
                             f"parts = {json.dumps([vm_path(p) for p in parts])}\n"
                             f"with open({json.dumps(vm_path(remote))}, 'wb') as out:\n"
                             "    for p in parts:\n"
                             "        with open(p, 'rb') as f:\n"
                             "            out.write(f.read())\n"
                             "        os.remove(p)\n")


def download_file(session: str, remote: str, local: Path) -> None:
    out = colab_exec_code(session, "import os, json\n"
                                   f"src = {json.dumps(vm_path(remote))}\n"
                                   "parts = []\n"
                                   "with open(src, 'rb') as f:\n"
                                   "    i = 0\n"
                                   f"    while block := f.read({CHUNK}):\n"
                                   "        p = f'{src}.dl{i:04d}'\n"
                                   "        open(p, 'wb').write(block)\n"
                                   "        parts.append(p)\n"
                                   "        i += 1\n"
                                   "print('@@PARTS ' + json.dumps(parts))\n")
    m = re.search(r"@@PARTS (\[.*\])", out)
    if not m:
        raise Stop(f"결과 파일을 받지 못했어요: {remote}")
    local.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, open(local, "wb") as dst:
        for i, p in enumerate(json.loads(m.group(1))):
            piece = Path(tmp) / f"piece{i:04d}"
            colab("download", "-s", session, f"{remote}.dl{i:04d}", str(piece), quiet=True)
            dst.write(piece.read_bytes())
    colab_exec_code(session, f"import os\nfor p in {m.group(1)}:\n    os.remove(p)\n")


# ---------------------------------------------------------------- GitHub token
def check_token(token: str) -> bool | None:
    """True/False: the token can/cannot read the repository. None: could not check (offline)."""
    if os.environ.get("SUBRM_SKIP_TOKEN_CHECK"):  # tests
        return True
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}",
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": "subtitle-remover"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except OSError:
        return None


def ensure_token(ask: bool) -> Path:
    path = token_path()
    saved = path.read_text().strip() if path.exists() else ""
    if saved and not ask:
        return path
    if saved:
        if check_token(saved) is not False:
            say("\n🟢 저장된 GitHub 토큰을 그대로 써요.")
            return path
        say("\n⚠️ 저장된 GitHub 토큰이 만료됐거나 권한이 없어요. 새 토큰을 넣어 주세요.")
    elif not ask:
        raise Stop("GitHub 토큰이 없어요. 먼저 colab_setup.bat 을 실행해 주세요.")
    say("\n▶ GitHub 토큰 (Colab이 비공개 저장소에서 코드를 받을 때 써요)")
    say("  실행가이드.md 의 'GitHub 토큰 만들기'대로 만든 github_pat_... 토큰을 붙여 넣고 Enter (오른쪽 클릭 = 붙여넣기)")
    while True:
        token = input("  토큰: ").strip().strip('"')
        ok = check_token(token) if token else False
        if ok is None:
            say("  (인터넷 연결 문제로 토큰을 확인하지 못했어요. 일단 저장할게요.)")
        if ok is not False:
            break
        say("  ⚠️ 이 토큰으로는 저장소에 접근할 수 없어요. 토큰과 저장소 권한(Contents: Read-only)을 확인해 주세요.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    say("  ✅ 토큰 저장 완료")
    return path


# ---------------------------------------------------------------- commands
def cmd_setup(args) -> None:
    say("=== 자막 지우개: Colab 자동 실행 준비 ===")
    if sys.version_info < (3, 12):
        raise Stop(f"Python 3.12 이상이 필요해요 (지금 {sys.version.split()[0]}). python.org에서 3.12를 설치해 주세요.")
    if not os.environ.get("SUBRM_COLAB"):
        say("\n▶ Colab CLI 설치 중...")
        py = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not py.exists():
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip", "google-colab-cli"], check=True)

    ensure_token(ask=True)

    say("\n▶ 구글 계정 연결 (처음 한 번)")
    say("  브라우저가 열리면 Colab을 쓸 구글 계정으로 로그인하고 허용하세요.")
    say("  화면에 나온 인증 코드를 복사해서 이 창에 붙여 넣고 Enter 를 누르면 돼요.")
    colab("sessions")

    settings = load_settings()
    root = find_drive_root(settings)
    if root:
        say(f"\n🟢 Google Drive 앱 폴더를 찾았어요: {root}")
    else:
        say("\n🟠 Google Drive 앱(Google Drive for desktop)을 찾지 못했어요.")
        say("   없어도 되지만, 설치하면 영상 업로드가 더 빠르고 안정적이에요: https://www.google.com/drive/download/")
    save_settings(settings)

    session = f"subrm-setup-{datetime.now():%Y%m%d%H%M%S}"
    try:
        start_runtime(session, settings.get("gpu", "T4"))
        say("\n▶ Google Drive 연결 (처음 한 번은 브라우저에서 허용이 필요해요)")
        colab("drivemount", "-s", session)
        out = colab_exec_code(session, "import os, subprocess\n"
                                       f"os.makedirs({json.dumps(VM_CONTENT + '/drive/MyDrive/subtitle-remover/input')}, exist_ok=True)\n"
                                       f"os.makedirs({json.dumps(VM_CONTENT + '/drive/MyDrive/subtitle-remover/output')}, exist_ok=True)\n"
                                       "try:\n"
                                       "    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],"
                                       " capture_output=True, text=True).stdout.strip()\n"
                                       "except OSError:\n"
                                       "    gpu = ''\n"
                                       "print('@@GPU ' + (gpu or 'none'))\n")
        gpu = re.search(r"@@GPU (.*)", out)
        say(f"\n  GPU: {gpu.group(1).strip() if gpu else '확인 못 함'}")
    finally:
        colab("stop", "-s", session, check=False, quiet=True)
    say("\n✅ 준비 완료! 이제 colab_run.bat 을 실행하면 돼요.")


def ask_folder(arg: str | None) -> Path:
    while True:
        text = arg if arg else input("\n영상이 있는 폴더 경로를 입력하세요 (폴더를 이 창에 끌어다 놓아도 돼요): ")
        arg = None
        folder = Path(text.strip().strip('"').strip())
        if folder.is_dir():
            return folder
        say(f"  ⚠️ 폴더가 없어요: {folder}")


def unique_local_name(base: Path, name: str) -> str:
    candidate, k = name, 2
    while (base / "input" / candidate).exists() or (base / "output" / candidate).exists():
        candidate, k = f"{name}_{k}", k + 1
    return candidate


def cmd_run(args) -> None:
    say("=== 자막 지우개: Colab에서 자동으로 지우기 ===")
    colab_cmd()
    token = ensure_token(ask=False)
    settings = load_settings()
    folder = ask_folder(args.folder)
    videos = list_videos(folder)
    if not videos:
        raise Stop(f"{folder} 에 영상 파일이 없어요 ({', '.join(sorted(VIDEO_EXTS))}).")
    total_mb = sum(v.stat().st_size for v in videos) / 1e6
    say(f"\n영상 {len(videos)}개 ({total_mb:.0f}MB)")

    job_settings = {k: settings[k] for k in ("quality", "region", "custom_region", "target", "method")}
    name = datetime.now().strftime("%Y%m%d%H")
    drive_root = find_drive_root(settings)
    uploaded_dir = None
    if drive_root:
        base = drive_root / "subtitle-remover"
        name = unique_local_name(base, name)
        dst = base / "input" / name
        dst.mkdir(parents=True)
        say(f"\n▶ Google Drive 앱 폴더로 복사: {dst}")
        files = []
        for i, v in enumerate(videos, 1):
            say(f"  [{i}/{len(videos)}] {v.name}")
            shutil.copyfile(v, dst / v.name)
            files.append({"name": v.name, "size": v.stat().st_size})
        job = {"version": 1, "name": name, "created": datetime.now().astimezone().isoformat(timespec="seconds"),
               "files": files, "settings": job_settings}
        (dst / "_job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
        say("  (Drive 앱이 뒤에서 업로드해요. 끝날 때까지 컴퓨터를 켜 두세요.)")
    else:
        uploaded_dir = f"{VM_CONTENT}/upload/{name}"

    session = f"subrm-{datetime.now():%Y%m%d%H%M%S}"
    result, out = None, ""
    try:
        start_runtime(session, settings.get("gpu", "T4"))
        say("\n▶ Google Drive 연결 중...")
        colab("drivemount", "-s", session)
        colab("upload", "-s", session, str(token), "content/.gh_token", quiet=True)
        if uploaded_dir:
            say("\n▶ 영상을 Colab으로 올리는 중... (Google Drive 앱이 없어서 직접 올려요)")
            colab_exec_code(session, f"import os\nos.makedirs({json.dumps(uploaded_dir)}, exist_ok=True)\n")
            for i, v in enumerate(videos, 1):
                say(f"  [{i}/{len(videos)}] {v.name}")
                upload_file(session, v, f"content/upload/{name}/{v.name}")

        job = {"repo": REPO, "branch": BRANCH, "job": name, "vm_content": VM_CONTENT,
               "drive_base": f"{VM_CONTENT}/drive/MyDrive/subtitle-remover", "uploaded_dir": uploaded_dir,
               "keep_outputs": not drive_root, "settings": job_settings,
               **json.loads(os.environ.get("SUBRM_JOB_EXTRA", "{}"))}
        script = (f"import json\nJOB = json.loads({json.dumps(json.dumps(job))})\n"
                  + (ROOT / "tools" / "colab_bootstrap.py").read_text(encoding="utf-8"))
        say("\n▶ GitHub에서 코드를 받아 자막을 지우는 중... (영상 길이에 따라 수 분~수십 분)")
        say("   이 창을 닫지 마세요. 닫으면 Colab 런타임이 한동안 켜진 채로 남을 수 있어요.\n")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script)
        try:
            _, out = colab("exec", "-s", session, "-f", f.name, "--timeout", str(EXEC_TIMEOUT), check=False)
        finally:
            os.unlink(f.name)
        m = re.search(r"@@RESULT (\{.*\})", out)
        result = json.loads(m.group(1)) if m else None

        if result and not drive_root:
            local = folder / "subtitle-remover-output"
            for j in result["jobs"]:
                for o in j["outputs"]:
                    say(f"  내 컴퓨터로 받는 중: {o}")
                    # Drive is unmounted by now; the runtime kept a local copy of each result
                    download_file(session, f"content/work/out/{j['name']}/{o}", local / j["name"] / o)
    finally:
        say("\n▶ Colab 런타임 종료 중...")
        colab("stop", "-s", session, check=False, quiet=True)

    if not result:
        if re.search(r"Authentication failed|could not read Username|Repository not found", out):
            raise Stop("GitHub에서 코드를 받지 못했어요. 토큰이 만료됐을 수 있어요. colab_setup.bat 을 다시 실행해서 "
                       "새 토큰을 넣어 주세요. 올린 영상은 Drive에 남아 있어서 다음 실행 때 이어서 처리돼요.")
        raise Stop("처리 결과를 확인하지 못했어요. 위의 메시지를 확인해 주세요. 올린 영상은 Drive에 남아 있어서 "
                   "다음 실행 때 이어서 처리돼요.")
    say("\n✅ 끝!")
    for j in result["jobs"]:
        errors = f", 실패 {len(j['errors'])}개" if j["errors"] else ""
        say(f"  Google Drive > subtitle-remover > output > {j['name']} : 결과 {len(j['outputs'])}개{errors}")
    if drive_root:
        out_dir = drive_root / "subtitle-remover" / "output" / name
        say("  Drive 앱에 결과가 내려오기를 기다리는 중...")
        for _ in range(60):
            if (out_dir / "_done.json").exists():
                break
            time.sleep(5)
        open_folder(out_dir if out_dir.exists() else drive_root / "subtitle-remover" / "output")
    else:
        open_folder(folder / "subtitle-remover-output")


def cmd_stop(args) -> None:
    _, out = colab("sessions", check=False, quiet=True)
    names = sorted(set(re.findall(r"subrm-[\w-]+", out)))
    if not names:
        say("켜져 있는 자막 지우개 런타임이 없어요.")
    for n in names:
        say(f"종료: {n}")
        colab("stop", "-s", n, check=False, quiet=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Colab에서 자막 지우기 자동 실행")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    run = sub.add_parser("run")
    run.add_argument("folder", nargs="?")
    sub.add_parser("stop")
    args = ap.parse_args(argv)
    try:
        {"setup": cmd_setup, "run": cmd_run, "stop": cmd_stop}[args.cmd](args)
    except Stop as e:
        say(f"\n❌ {e}")
        return 1
    except KeyboardInterrupt:
        say("\n중단했어요. Colab 런타임이 남아 있으면 colab_stop.bat 으로 끌 수 있어요.")
        return 1
    except EOFError:
        say("\n❌ 입력을 받지 못했어요. 창에서 직접 실행해 주세요.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
