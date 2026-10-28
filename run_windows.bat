@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Not installed yet. Double-click install_windows.bat first.
  pause
  exit /b 1
)
echo Starting... the page opens in your browser: http://127.0.0.1:7860
echo Close this window to stop.
".venv\Scripts\python.exe" -m subtitle_remover.app --open %*
pause
