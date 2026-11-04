#!/bin/bash
# =========================================================================
# ORION STOCKS_V1 AUTO-START — Google Cloud VPS cron task
# =========================================================================
# Cron entry — INSTALLED 2026-08-23:
#   18 3 * * 1-5 bash /home/selukar_amol123/Amol/start_orion_stocks.sh
#   (= 08:48 IST, Mon-Fri — BEFORE the index bots, because the morning
#   research pass scans ~200 F&O stocks (~2-3 min) and must finish by 09:15.
#   It probes yesterday's Kite token and only runs auto_login if dead.)
#
# Stock-options paper bot. Own PID/lock/log; never touches NIFTY/SENSEX bots.
# =========================================================================

LOG="/home/selukar_amol123/orion_stocks_run.log"
SCRIPT_DIR="/home/selukar_amol123/Amol"
PID_FILE="$SCRIPT_DIR/.orion_stocks.pid"

DOW=$(TZ="Asia/Kolkata" date +%u)
if [ "$DOW" -ge 6 ]; then
    echo "[$(TZ="Asia/Kolkata" date '+%Y-%m-%d %H:%M:%S')] Weekend — ORION STOCKS skipped (DOW=$DOW)" >> "$LOG"
    exit 0
fi

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ORION STOCKS START" >> "$LOG"
echo "========================================" >> "$LOG"

source "$SCRIPT_DIR/orion_infra_guard.sh"
orion_disk_guard "$LOG" "STOCKS boot"

# 0. Kill any existing STOCKS instance only
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] Killing existing ORION STOCKS (PID=$OLD_PID)..." >> "$LOG"
        kill "$OLD_PID" 2>/dev/null; sleep 2; kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi
pkill -f "ORION_STOCKS_V1.py" 2>/dev/null || true
sleep 1

cd "$SCRIPT_DIR" || { echo "FATAL: $SCRIPT_DIR not found"; exit 1; }

# 1. Validate the Upstox access token (Kite retired 2026-08-26 per user —
#    long-lived read-only token, valid to 2027-08, no daily login needed).
echo "[$(date '+%H:%M:%S')] Validating Upstox access token..." >> "$LOG"
python3 - >> "$LOG" 2>&1 <<'PYEOF'
import sys
sys.path.insert(0, "/home/selukar_amol123/Amol")
import credentials as c
from upstox_kite_shim import UpstoxKite
UpstoxKite(c.UPSTOX_ACCESS_TOKEN).profile()
print("Upstox token OK.")
PYEOF
if [ $? -ne 0 ]; then
    echo "[$(date '+%H:%M:%S')] FATAL: Upstox token validation failed — aborting" >> "$LOG"
    python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': '🚨 ORION STOCKS failed to start: Upstox token validation error. Check orion_stocks_run.log'})
except: pass
" 2>/dev/null
    exit 1
fi

# 2. Remove stale singleton lock — STOCKS' own lock file only.
rm -f "$SCRIPT_DIR/.orion_singleton_stocks.lock"

# 3. Supervised launch loop (same shape as the other launchers)
BOT_SCRIPT="$SCRIPT_DIR/ORION_STOCKS_V1.py"
EOD_CUTOFF_HHMM="1525"
MAX_RESTARTS=50
RESTART_BACKOFF=20
restarts=0
fast_fail_streak=0

while :; do
    rm -f "$SCRIPT_DIR/.orion_singleton_stocks.lock"
    orion_disk_guard "$LOG" "STOCKS attempt $((restarts+1))"
    echo "[$(date '+%H:%M:%S')] Starting ORION STOCKS (attempt $((restarts+1)))..." >> "$LOG"
    START_TS=$(date +%s)
    python3 -u "$BOT_SCRIPT" >> "$LOG" 2>&1 &
    BOT_PID=$!
    echo "$BOT_PID" > "$PID_FILE"
    echo "[$(date '+%H:%M:%S')] ORION STOCKS started (PID=$BOT_PID)" >> "$LOG"

    wait "$BOT_PID"
    RAN_SECS=$(( $(date +%s) - START_TS ))
    rm -f "$PID_FILE"

    NOW_HHMM=$(TZ="Asia/Kolkata" date +%H%M)
    if [ "$NOW_HHMM" -ge "$EOD_CUTOFF_HHMM" ]; then
        echo "[$(date '+%H:%M:%S')] ORION STOCKS exited at/after EOD cutoff ($NOW_HHMM IST) — clean shutdown, not restarting." >> "$LOG"
        break
    fi

    restarts=$((restarts+1))
    if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
        echo "[$(date '+%H:%M:%S')] ORION STOCKS died ${restarts}x before EOD — restart cap reached, giving up." >> "$LOG"
        python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': '🚨 ORION STOCKS crashed ${restarts}x and hit the restart cap. Bot is DOWN — check orion_stocks_run.log'})
except: pass
" 2>/dev/null
        break
    fi

    if [ "$RAN_SECS" -lt 60 ]; then
        fast_fail_streak=$((fast_fail_streak+1))
    else
        fast_fail_streak=0
    fi
    if [ "$fast_fail_streak" -ge 3 ]; then
        orion_tg "stocks_crashloop" 900 "🚨 ORION STOCKS crash-looping: ${fast_fail_streak} fast deaths in a row (last ran ${RAN_SECS}s, attempt ${restarts}). Check orion_stocks_run.log — likely ENOSPC or boot error."
    fi

    echo "[$(date '+%H:%M:%S')] ORION STOCKS died after ${RAN_SECS}s (pre-EOD) — restarting in ${RESTART_BACKOFF}s." >> "$LOG"
    sleep "$RESTART_BACKOFF"
done

echo "[$(date '+%H:%M:%S')] ORION STOCKS supervisor exited." >> "$LOG"
