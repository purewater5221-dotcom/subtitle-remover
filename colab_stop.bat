@echo off
setlocal
cd /d "%~dp0"
rem Stops Colab runtimes left running by colab_run.bat
if not exist ".venv-colab\Scripts\python.exe" (
  echo [ERROR] Not set up yet. Double-click colab_setup.bat first.
  pause
  exit /b 1
)
".venv-colab\Scripts\python.exe" tools\colab_auto.py stop
pause
