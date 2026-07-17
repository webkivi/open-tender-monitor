#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PID_FILE="$BASE_DIR/logs/open-tender-monitor.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "Open Tender Monitor is not running via the helper script."
  exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
fi
rm -f "$PID_FILE"
echo "Open Tender Monitor stopped."
