@echo off
setlocal
cd /d "%~dp0"
rem One-time setup for colab_run.bat. The Colab CLI needs Python 3.12 or newer.
set "PY="
py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if not defined PY (py -3.13 --version >nul 2>nul && set "PY=py -3.13")
if not defined PY (py -3 --version >nul 2>nul && set "PY=py -3")
if not defined PY (python --version >nul 2>nul && set "PY=python")
if not defined PY (
  echo [ERROR] Python was not found.
  echo Install Python 3.12 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the installer, then run this again.
  pause
  exit /b 1
)
%PY% tools\colab_auto.py setup
pause
