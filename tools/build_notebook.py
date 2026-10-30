"""Generate colab/subtitle_remover.ipynb (edit this file, then run it)."""

import json
from pathlib import Path

REPO = "purewater5221-dotcom/subtitle-remover"


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(True)}


def code(text, title=None):
    meta = {"cellView": "form"} if title else {}
    return {"cell_type": "code", "metadata": meta, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(True)}


INTRO = """
# 자막 지우개 (Subtitle Remover)

짧은 영상에 박힌 자막을 찾아서, 그 자리를 **배경으로 자연스럽게 메꿔** 줍니다.

**처음 한 번만 할 일** (자세한 방법은 저장소의 README 참고)
1. GitHub 토큰을 만들어서 왼쪽 🔑 **보안 비밀**에 `GITHUB_TOKEN` 이름으로 저장하고, **노트북 액세스**를 켜 주세요. (보안 비밀 이름은 토큰을 만들 때 붙인 이름과 상관없이 꼭 `GITHUB_TOKEN`이에요.)
2. 메뉴 **런타임 → 런타임 유형 변경 → T4 GPU** 를 선택하세요.

**매번 할 일**
1. **①** 을 실행합니다 (Drive 연결 허용 창이 뜨면 허용).
2. 내 Google Drive의 `subtitle-remover/input` 폴더에 영상을 넣습니다.
3. **②** 에서 설정을 고르고 **③** 을 실행합니다. 결과는 `subtitle-remover/output` 폴더에 저장돼요.
4. **④** 로 원본과 결과를 나란히 비교합니다.

💡 처음 보는 종류의 영상이면 ② 에서 **마스크만 확인**을 먼저 해 보세요. 지울 부분이 빨갛게 칠해진 미리보기 영상이 1~2분 안에 나와요.
"""

SETUP = f'''
#@title ① 준비하기 (세션마다 한 번)
import os, subprocess, sys
from pathlib import Path

REPO = "{REPO}"
REPO_DIR = Path("/content/subtitle-remover")
DRIVE_DIR = Path("/content/drive/MyDrive/subtitle-remover")

gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                     capture_output=True, text=True)
if gpu.returncode != 0:
    raise SystemExit("⚠️ GPU가 없습니다. 메뉴 [런타임 → 런타임 유형 변경 → T4 GPU]를 선택한 뒤 다시 실행하세요.")
print("GPU:", gpu.stdout.strip())

from google.colab import drive, userdata
drive.mount("/content/drive")
for sub in ("input", "output"):
    (DRIVE_DIR / sub).mkdir(parents=True, exist_ok=True)

try:
    token = userdata.get("GITHUB_TOKEN")
except Exception:
    raise SystemExit("⚠️ 왼쪽 🔑 보안 비밀에 GITHUB_TOKEN 을 저장하고 '노트북 액세스'를 켜 주세요. (README 참고)")

def git(*args):
    url = f"https://x-access-token:{{token}}@github.com/{{REPO}}.git"
    res = subprocess.run(["git", *[a.replace("URL", url) for a in args]], capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit("⚠️ 코드를 받지 못했습니다: " + res.stderr.replace(token, "***"))

if (REPO_DIR / ".git").exists():
    git("-C", str(REPO_DIR), "pull", "-q", "URL")
else:
    git("clone", "-q", "URL", str(REPO_DIR))
print("코드 버전:", subprocess.run(["git", "-C", str(REPO_DIR), "log", "-1", "--format=%h %cd", "--date=short"],
                               capture_output=True, text=True).stdout.strip())

if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
from subtitle_remover.colab_job import install_packages
install_packages()  # the package list comes with the code, so this cell never goes stale

from subtitle_remover.inpaint.propainter import ensure_propainter
ensure_propainter()
print("\\n✅ 준비 완료! Drive의 subtitle-remover/input 폴더에 영상을 넣고 ②, ③ 을 실행하세요.")
'''

SETTINGS = '''
#@title ② 설정 { display-mode: "form" }
#@markdown **무엇을 할까요?** (마스크만 확인 = 지울 부분을 빨갛게 표시한 미리보기만 빠르게 만들기)
TASK = "자막 지우기"  #@param ["자막 지우기", "마스크만 확인"]
#@markdown **품질** (빠르게 → 최고로 갈수록 느리지만 더 자연스러움)
QUALITY = "보통"  #@param ["빠르게", "보통", "최고"]
#@markdown **어디에 있는 글자를 지울까요?**
REGION = "전체 화면"  #@param ["전체 화면", "아래쪽 절반", "아래쪽 1/3", "위쪽 절반", "위쪽 1/3", "직접 입력"]
#@markdown 직접 입력: `x0,y0,x1,y1` (0~1 비율). 예) `0,0.6,1,1` = 아래쪽 40%. 여러 개는 `;`로 구분
CUSTOM_REGION = "0,0.6,1,1"  #@param {type:"string"}
#@markdown **어떤 글자를 지울까요?**
TARGET = "화면에 고정된 자막·글자만 (권장)"  #@param ["화면에 고정된 자막·글자만 (권장)", "간판 등 모든 글자"]
#@markdown **폴더** (내 Drive 기준)
INPUT_DIR = "/content/drive/MyDrive/subtitle-remover/input"  #@param {type:"string"}
OUTPUT_DIR = "/content/drive/MyDrive/subtitle-remover/output"  #@param {type:"string"}
#@markdown **기타**
REDO = False  #@param {type:"boolean"}
#@markdown ↑ 이미 결과가 있는 영상도 다시 처리
SAVE_MASK_PREVIEW = False  #@param {type:"boolean"}
#@markdown ↑ 결과와 함께 마스크 미리보기 영상도 저장
print("설정 완료:", TASK, "/", QUALITY, "/", REGION, "/", TARGET)
'''

RUN = '''
#@title ③ 실행
import logging, shutil, time
from pathlib import Path
from subtitle_remover import Config, apply_quality, parse_region
from subtitle_remover.pipeline import SubtitleRemover
from subtitle_remover.video_io import list_videos

logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
logging.getLogger("subtitle_remover").setLevel(logging.INFO)

cfg = apply_quality(Config(), {"빠르게": "fast", "보통": "balanced", "최고": "best"}[QUALITY])
region_text = {"전체 화면": "all", "아래쪽 절반": "bottom", "아래쪽 1/3": "bottom-third",
               "위쪽 절반": "top", "위쪽 1/3": "top-third"}.get(REGION, CUSTOM_REGION)
cfg.filter.regions = [r for part in region_text.split(";") if part.strip() for r in parse_region(part)]
cfg.filter.target = "overlay" if TARGET.startswith("화면") else "all"
cfg.output.debug = SAVE_MASK_PREVIEW
cfg.work_dir = "/content/work"
detect_only = TASK == "마스크만 확인"

in_dir, out_dir, local_out = Path(INPUT_DIR), Path(OUTPUT_DIR), Path("/content/out")
out_dir.mkdir(parents=True, exist_ok=True)
local_out.mkdir(parents=True, exist_ok=True)
videos = [v for v in list_videos(in_dir) if not v.stem.endswith(("_clean", "_mask"))] if in_dir.exists() else []
if not videos:
    print(f"⚠️ {in_dir} 에 영상이 없습니다. Drive에 영상을 올린 뒤 다시 실행하세요.")

remover = SubtitleRemover(cfg)
results = []
for i, src in enumerate(videos, 1):
    final = out_dir / f"{src.stem}_clean.mp4"
    if not detect_only and final.exists() and not REDO:
        print(f"[{i}/{len(videos)}] {src.name}: 이미 결과가 있어 건너뜀")
        results.append((src, final))
        continue
    print(f"\\n[{i}/{len(videos)}] {src.name}")
    try:
        r = remover.process(src, local_out / final.name, detect_only=detect_only)
    except Exception as e:
        print(f"❌ 실패: {e}")
        continue
    for name in (final.name, f"{src.stem}_clean_mask.mp4", f"{src.stem}_clean_tracks.json"):
        f = local_out / name  # result, mask preview, detection report
        if f.exists():
            shutil.copy(f, out_dir / name)
            f.unlink()
    done = out_dir / (r.output or r.preview).name
    results.append((src, done))
    print(f"✅ {r.seconds:.0f}초, 지운 글자 {r.removed}개 → {done}" + (f" ({r.note})" if r.note else ""))
print("\\n끝! ④ 로 결과를 비교해 보세요.")
'''

COMPARE = '''
#@title ④ 결과 비교 보기 (왼쪽: 원본, 오른쪽: 결과)
import base64
from IPython.display import HTML, display
from subtitle_remover.video_io import make_comparison

HOW_MANY = 3  #@param {type:"integer"}
for src, dst in results[-HOW_MANY:]:
    if not dst.exists():
        continue
    if dst.stem.endswith("_mask"):  # mask preview only: show it as it is
        preview = dst
    else:
        preview = make_comparison(src, dst, Path("/content/compare") / f"{src.stem}.mp4")
    data = base64.b64encode(preview.read_bytes()).decode()
    display(HTML(f"<p><b>{src.name}</b></p><video controls loop muted autoplay playsinline "
                 f"style='max-height:640px;max-width:100%' src='data:video/mp4;base64,{data}'></video>"))
'''

HELP = """
### 문제가 생기면
- **GPU가 없다고 나와요** → 메뉴 *런타임 → 런타임 유형 변경 → T4 GPU*. 무료 GPU를 못 받는 시간대도 있어요. 잠시 뒤 다시 시도하세요.
- **GPU 메모리 부족** → ② 에서 품질을 *빠르게*로 낮추세요.
- **자막이 덜 지워져요** → *마스크만 확인*으로 빨간 부분이 자막을 다 덮는지 보세요. 노란 테두리는 "찾았지만 남긴 글자"예요. 자막이 노란색이면 대상을 *모든 글자*로 바꾸거나 영역을 지정하세요.
- **지우면 안 되는 글자까지 지워져요** → 영역을 *아래쪽 1/3* 등으로 좁히세요.
- **세션이 끊겼어요** → ① 부터 다시 실행하세요. 이미 끝난 영상은 건너뜁니다.
"""


def main():
    nb = {
        "nbformat": 4, "nbformat_minor": 0,
        "metadata": {"colab": {"provenance": [], "gpuType": "T4"}, "accelerator": "GPU",
                     "kernelspec": {"name": "python3", "display_name": "Python 3"},
                     "language_info": {"name": "python"}},
        "cells": [md(INTRO), code(SETUP, True), code(SETTINGS, True), code(RUN, True), code(COMPARE, True), md(HELP)],
    }
    out = Path(__file__).resolve().parents[1] / "colab" / "subtitle_remover.ipynb"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
