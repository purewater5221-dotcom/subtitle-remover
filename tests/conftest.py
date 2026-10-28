import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def synthetic_clip(tmp_path_factory):
    """A small subtitled clip with ground truth (see tools/make_synthetic.py)."""
    out = tmp_path_factory.mktemp("synth")
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), str(out), "--seconds", "2",
                    "--size", "180x320", "--name", "clip"], check=True, capture_output=True)
    return out
