#!/usr/bin/env bash
set -euo pipefail
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
export PYTHONPATH=src
python -m icai_slot_monitor.cli --config config/config.yaml --once
