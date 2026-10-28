#!/usr/bin/env bash
# Local setup for Linux (NVIDIA GPU) or macOS (CPU only)
set -euo pipefail
cd "$(dirname "$0")"
"${PYTHON:-python3}" tools/install.py "$@"
