#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$BASE_DIR"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m ensurepip --upgrade
  .venv/bin/python -m pip install -r requirements.txt
fi

mkdir -p logs
if [ -f logs/open-tender-monitor.pid ] && kill -0 "$(cat logs/open-tender-monitor.pid)" 2>/dev/null; then
  echo "Open Tender Monitor is already running."
  exit 0
fi

nohup .venv/bin/python app.py > logs/open-tender-monitor.log 2>&1 < /dev/null &
echo $! > logs/open-tender-monitor.pid
echo "Open Tender Monitor started: http://localhost:8081"
