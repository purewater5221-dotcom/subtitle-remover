"""Set up a local environment in .venv (Windows / Linux; macOS runs on CPU).

    python tools/install.py            # detect the NVIDIA GPU and install everything
    python tools/install.py --cpu      # no GPU
    python tools/install.py --cuda cu126 --dry-run

PyTorch is installed from download.pytorch.org with the newest CUDA build that
the installed NVIDIA driver supports (nvidia-smi reports it); if that build
cannot use the GPU, older builds are tried.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
# cu12x first: onnxruntime-gpu (text detection) is built against CUDA 12
CUDA_TAGS = ["cu128", "cu126", "cu130", "cu129", "cu124", "cu121", "cu118"]
PACKAGES = ["numpy>=1.24", "opencv-python-headless>=4.8", "tqdm", "pillow", "einops", "scipy", "matplotlib",
            "gradio>=4.44", "static-ffmpeg"]


def say(msg: str) -> None:
    print(msg, flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(cmd: list, dry: bool, check: bool = True) -> int:
    say("  $ " + " ".join(str(c) for c in cmd))
    if dry:
        return 0
    rc = subprocess.run([str(c) for c in cmd], cwd=ROOT).returncode
    if check and rc != 0:
        raise SystemExit(f"\n❌ 실패했어요 (코드 {rc}). 위의 메시지를 확인해 주세요.")
    return rc


def nvidia_gpu() -> tuple[str, float] | None:
    """(GPU name, highest CUDA version the driver supports) or None."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        header = subprocess.run([smi], capture_output=True, text=True, timeout=30).stdout
        name = subprocess.run([smi, "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                              text=True, timeout=30).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", header)
    if not m or not name:
        return None
    return name[0], int(m.group(1)) + int(m.group(2)) / 10


def candidate_tags(driver_cuda: float) -> list[str]:
    return [t for t in CUDA_TAGS if int(t[2:]) / 10 <= driver_cuda + 1e-6]


def cuda_works(py: Path) -> bool:
    code = "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
    return subprocess.run([str(py), "-c", code], cwd=ROOT).returncode == 0


def install_torch(py: Path, tags: list[str], dry: bool) -> str | None:
    for tag in tags:
        say(f"\n▶ PyTorch ({tag}) 설치 중... (2~3GB라 시간이 걸려요)")
        rc = run([py, "-m", "pip", "install", "--upgrade", "torch", "torchvision",
                  "--index-url", f"https://download.pytorch.org/whl/{tag}"], dry, check=False)
        if rc != 0:
            say(f"  {tag} 버전을 설치하지 못해서 다음 버전을 시도해요.")
            continue
        if dry or cuda_works(py):
            return tag
        say(f"  {tag} 버전으로는 GPU를 쓸 수 없어서 다른 버전을 시도해요.")
        run([py, "-m", "pip", "uninstall", "-y", "torch", "torchvision"], dry, check=False)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="자막 지우개 로컬 설치")
    ap.add_argument("--cpu", action="store_true", help="GPU 없이 설치")
    ap.add_argument("--cuda", help="PyTorch CUDA 빌드 지정 (예: cu126)")
    ap.add_argument("--skip-torch", action="store_true", help="PyTorch 설치 건너뛰기")
    ap.add_argument("--dry-run", action="store_true", help="실행할 명령만 보여주기")
    args = ap.parse_args()
    dry = args.dry_run

    v = sys.version_info
    say(f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    if not (3, 10) <= (v.major, v.minor) <= (3, 13):
        say("⚠️ Python 3.10~3.13을 권장해요 (가장 안전한 건 3.12). 계속 진행하지만 설치가 실패할 수 있어요.")

    say(f"\n▶ 가상환경 만들기: {VENV}")
    if not venv_python().exists():
        run([sys.executable, "-m", "venv", VENV], dry)
    py = venv_python()
    run([py, "-m", "pip", "install", "--upgrade", "pip"], dry)

    gpu = None if args.cpu else nvidia_gpu()
    if gpu:
        say(f"\n🟢 NVIDIA GPU: {gpu[0]} (드라이버 CUDA {gpu[1]:.1f})")
    elif not args.cpu:
        say("\n🟠 NVIDIA GPU를 찾지 못했어요 (nvidia-smi 없음). CPU용으로 설치해요. 매우 느려요.")

    if not args.skip_torch:
        if gpu or args.cuda:
            tags = [args.cuda] if args.cuda else candidate_tags(gpu[1])
            tag = install_torch(py, tags, dry) if tags else None
            if tag is None:
                raise SystemExit("\n❌ GPU용 PyTorch를 설치하지 못했어요. NVIDIA 드라이버를 최신으로 업데이트한 뒤 "
                                 "다시 실행하거나, --cpu 옵션으로 설치하세요.")
        else:
            say("\n▶ PyTorch (CPU) 설치 중...")
            index = [] if sys.platform == "darwin" else ["--index-url", "https://download.pytorch.org/whl/cpu"]
            run([py, "-m", "pip", "install", "--upgrade", "torch", "torchvision", *index], dry)

    say("\n▶ 나머지 패키지 설치 중...")
    onnx = "onnxruntime-gpu" if gpu and sys.platform != "darwin" else "onnxruntime"
    run([py, "-m", "pip", "install", "--upgrade", *PACKAGES, onnx], dry)
    run([py, "-m", "pip", "install", "--no-deps", "rapidocr==3.10.0"], dry)

    say("\n▶ FFmpeg와 ProPainter 모델 준비 중...")
    run([py, "-c", "from subtitle_remover.video_io import _tool; print('  ffmpeg:', _tool('ffmpeg'))"], dry)
    run([py, "-c", "from subtitle_remover.inpaint.propainter import ensure_propainter as e; "
                   "print('  ProPainter:', e())"], dry)

    say("\n▶ 점검")
    run([py, "-c", "from subtitle_remover.device import gpu_info; from subtitle_remover.detect import TextDetector; "
                   "g = gpu_info(); d = TextDetector(); "
                   "print('  GPU:', f'{g[0]} ({g[1]:.0f}GB)' if g else '없음 (CPU)'); "
                   "print('  텍스트 검출:', d.device)"], dry)

    say("\n✅ 설치 완료!")
    if sys.platform == "win32":
        say("   run_windows.bat 을 더블클릭하면 브라우저에 자막 지우개 화면이 열려요.")
    else:
        say("   ./run.sh 를 실행하면 브라우저에 자막 지우개 화면이 열려요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
