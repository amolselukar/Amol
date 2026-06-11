#!/bin/bash
# =========================================================================
# ORION AUTO-START  —  Google Cloud VPS cron task
# =========================================================================
# Cron entry (crontab -e):
#   30 3 * * 1-5 bash /home/selukar_amol123/Amol/start_orion.sh
#   (= 09:00 IST, Mon–Fri)
# Server IP: 34.100.170.253
# =========================================================================

LOG="/home/selukar_amol123/orion_run.log"
SCRIPT_DIR="/home/selukar_amol123/Amol"
PID_FILE="$SCRIPT_DIR/.orion.pid"

# Weekend guard — exit silently on Sat (6) and Sun (7) IST
DOW=$(TZ="Asia/Kolkata" date +%u)
if [ "$DOW" -ge 6 ]; then
    echo "[$(TZ="Asia/Kolkata" date '+%Y-%m-%d %H:%M:%S')] Weekend — ORION skipped (DOW=$DOW)" >> "$LOG"
    exit 0
fi

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ORION START" >> "$LOG"
echo "========================================" >> "$LOG"

# 0. Kill any existing ORION instances (prevents zombie multi-instance bugs)
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] Killing existing ORION (PID=$OLD_PID)..." >> "$LOG"
        kill "$OLD_PID" 2>/dev/null
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi
# Also kill any stray ORION processes
pkill -f "ORION_PAPER_V2_5_14.py" 2>/dev/null || true
sleep 1

# 1. Pull latest code from GitHub (fetch + reset avoids diverged-branch errors)
echo "[$(date '+%H:%M:%S')] Pulling latest code..." >> "$LOG"
cd "$SCRIPT_DIR" || { echo "FATAL: $SCRIPT_DIR not found"; exit 1; }
if git fetch origin main >> "$LOG" 2>&1; then
    git reset --hard origin/main >> "$LOG" 2>&1
else
    echo "[$(date '+%H:%M:%S')] WARN: git fetch failed — keeping local code (no reset)" >> "$LOG"
fi

# 2. Refresh Zerodha access token via TOTP auto-login
echo "[$(date '+%H:%M:%S')] Refreshing Kite access token..." >> "$LOG"
python3 "$SCRIPT_DIR/auto_login.py" >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "[$(date '+%H:%M:%S')] FATAL: auto_login failed — aborting" >> "$LOG"
    # Notify via Telegram if possible
    python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': '🚨 ORION failed to start: auto-login error. Check orion_run.log'})
except: pass
" 2>/dev/null
    exit 1
fi

# 3. Remove stale singleton lock (from a previous crash/kill)
rm -f "$SCRIPT_DIR/.orion_singleton.lock"

# 4. Start the bot (output appended to log)
echo "[$(date '+%H:%M:%S')] Starting ORION bot..." >> "$LOG"
python3 -u "$SCRIPT_DIR/ORION_PAPER_V2_5_14.py" >> "$LOG" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"
echo "[$(date '+%H:%M:%S')] ORION started (PID=$BOT_PID)" >> "$LOG"
wait "$BOT_PID"
rm -f "$PID_FILE"

echo "[$(date '+%H:%M:%S')] ORION exited." >> "$LOG"
