import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import install  # noqa: E402


def test_cuda_build_choice_follows_driver():
    assert install.candidate_tags(12.6) == ["cu126", "cu124", "cu121", "cu118"]
    assert install.candidate_tags(12.8)[0] == "cu128"  # CUDA 12 builds first (onnxruntime-gpu)
    assert "cu130" in install.candidate_tags(13.0)
    assert install.candidate_tags(11.4) == []


def test_nvidia_smi_parsing(tmp_path, monkeypatch):
    smi = tmp_path / "nvidia-smi"
    smi.write_text('#!/bin/sh\nif [ "$1" = "--query-gpu=name" ]; then echo "NVIDIA GeForce RTX 3060"; exit 0; fi\n'
                   'echo "| NVIDIA-SMI 572.16   Driver Version: 572.16   CUDA Version: 12.8 |"\n')
    smi.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")
    assert install.nvidia_gpu() == ("NVIDIA GeForce RTX 3060", 12.8)


def test_no_nvidia_smi(monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    assert install.nvidia_gpu() is None
