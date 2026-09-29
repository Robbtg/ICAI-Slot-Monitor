@echo off
setlocal
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m playwright install chromium
set PYTHONPATH=src
python -m icai_slot_monitor.cli --config config\config.yaml --once
pause
