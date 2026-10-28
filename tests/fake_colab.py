"""Stand-in for Google's `colab` CLI, used by tests/test_colab_auto.py.

The fake runtime's /content is $SUBRM_VM_CONTENT, Google Drive is
$FAKE_COLAB_DRIVE (linked into the runtime by `drivemount`), and the list of
sessions plus a log of calls live in $FAKE_COLAB_HOME.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path(os.environ["FAKE_COLAB_HOME"])
CONTENT = Path(os.environ["SUBRM_VM_CONTENT"])
DRIVE = Path(os.environ["FAKE_COLAB_DRIVE"])
MAX_UPLOAD = int(os.environ.get("FAKE_COLAB_MAX_UPLOAD", 10**12))
STATE = HOME / "sessions.json"

args = sys.argv[1:]
HOME.mkdir(parents=True, exist_ok=True)
with open(HOME / "calls.log", "a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")


def sessions():
    return json.loads(STATE.read_text()) if STATE.exists() else []


def option(name):
    return args[args.index(name) + 1]


def positional():
    out, skip = [], False
    for a in args[1:]:
        if skip:
            skip = False
        elif a in ("-s", "-f", "--timeout", "--gpu"):
            skip = True
        else:
            out.append(a)
    return out


def local(remote):  # "content/x/y" -> <fake /content>/x/y
    return CONTENT / remote.split("/", 1)[1]


cmd = args[0]
if cmd == "sessions":
    print("\n".join(sessions()) or "[colab] No active sessions.")
    sys.exit(0)
if cmd == "new":
    if os.environ.get("FAKE_COLAB_NO_GPU"):
        print("[colab] Backend rejected accelerator 'T4'.")
        sys.exit(1)
    STATE.write_text(json.dumps(sessions() + [option("-s")]))
    CONTENT.mkdir(parents=True, exist_ok=True)
    print("[colab] Session READY.")
    sys.exit(0)
if cmd == "stop":
    STATE.write_text(json.dumps([s for s in sessions() if s != option("-s")]))
    print("[colab] Session terminated.")
    sys.exit(0)
if option("-s") not in sessions():
    print(f"[colab] Session '{option('-s')}' not found.")
    sys.exit(1)
if cmd == "drivemount":
    (CONTENT / "drive").mkdir(parents=True, exist_ok=True)
    link = CONTENT / "drive" / "MyDrive"
    if not link.exists():
        link.symlink_to(DRIVE, target_is_directory=True)
    print("Mounted at /content/drive")
elif cmd == "upload":
    src, remote = positional()
    if os.path.getsize(src) > MAX_UPLOAD:
        print("[colab] Upload failed: 413 Request Entity Too Large")
        sys.exit(1)
    local(remote).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, local(remote))
elif cmd == "download":
    remote, dst = positional()
    shutil.copyfile(local(remote), dst)
elif cmd == "exec":
    sys.exit(subprocess.run([sys.executable, option("-f")], cwd=CONTENT).returncode)
else:
    print(f"unknown command {cmd}")
    sys.exit(2)
