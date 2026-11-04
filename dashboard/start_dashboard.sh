#!/bin/bash
# ORION dashboard launcher — idempotent, safe to run from cron every few minutes.
# Starts the dashboard server if it is not already running. Never touches any
# bot process or bot file.
DIR="/home/selukar_amol123/Amol/dashboard"
LOG="/home/selukar_amol123/orion_dashboard.log"
PORT="${ORION_DASH_PORT:-8787}"
HOST="${ORION_DASH_HOST:-0.0.0.0}"
PIDF="$DIR/dashboard.pid"

export ORION_DASH_TOKEN="$(cat "$DIR/.dash_token" 2>/dev/null)"

if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    exit 0                      # already up
fi

cd "$DIR" || exit 1
setsid nohup python3 "$DIR/server.py" --port "$PORT" --host "$HOST" \
    >> "$LOG" 2>&1 < /dev/null &
echo $! > "$PIDF"
echo "[$(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S IST')] dashboard started pid=$! on $HOST:$PORT" >> "$LOG"
