@echo off
setlocal
cd /d "%~dp0"
rem Removes subtitles on Google Colab. Drop a video folder on this file, or type the path when asked.
if not exist ".venv-colab\Scripts\python.exe" (
  echo [ERROR] Not set up yet. Double-click colab_setup.bat first.
  pause
  exit /b 1
)
".venv-colab\Scripts\python.exe" tools\colab_auto.py run %*
pause
