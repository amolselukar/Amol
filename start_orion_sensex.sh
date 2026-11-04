#!/bin/bash
# =========================================================================
# ORION V2.5.20-SENSEX AUTO-START — Google Cloud VPS cron task
# =========================================================================
# Cron entry (crontab -e) — NOT yet installed, user to confirm:
#   36 3 * * 1-5 bash /home/selukar_amol123/Amol/start_orion_sensex.sh
#   (= 09:06 IST, Mon-Fri — after PROB70 (09:00) and V2.5.20 (09:02) have
#   already refreshed the Kite token in credentials.py)
#
# SENSEX port of start_orion_v2520.sh. Differences:
#  - Launches ORION_SENSEX_V2520.py (BSE SENSEX / BFO, lot 20, Thu expiry)
#  - Reuses the Kite token the NIFTY launchers just wrote; only runs
#    auto_login itself if that token fails a quick validity probe (avoids a
#    third headless-Firefox login racing the other two).
#  - Own PID/lock/log files; never touches the NIFTY V2.5.20 process.
# =========================================================================

LOG="/home/selukar_amol123/orion_sensex_run.log"
SCRIPT_DIR="/home/selukar_amol123/Amol"
PID_FILE="$SCRIPT_DIR/.orion_sensex.pid"

DOW=$(TZ="Asia/Kolkata" date +%u)
if [ "$DOW" -ge 6 ]; then
    echo "[$(TZ="Asia/Kolkata" date '+%Y-%m-%d %H:%M:%S')] Weekend — ORION SENSEX skipped (DOW=$DOW)" >> "$LOG"
    exit 0
fi

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ORION SENSEX START" >> "$LOG"
echo "========================================" >> "$LOG"

source "$SCRIPT_DIR/orion_infra_guard.sh"
orion_disk_guard "$LOG" "SENSEX boot"

# 0. Kill any existing SENSEX instance only
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] Killing existing ORION SENSEX (PID=$OLD_PID)..." >> "$LOG"
        kill "$OLD_PID" 2>/dev/null; sleep 2; kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi
pkill -f "ORION_SENSEX_V2520.py" 2>/dev/null || true
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
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_SENSEX_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_SENSEX_CHAT_ID,
              'text': '🚨 ORION SENSEX failed to start: Upstox token validation error. Check orion_sensex_run.log'})
except: pass
" 2>/dev/null
    exit 1
fi

# 2. Remove stale singleton lock — SENSEX's own lock file only.
rm -f "$SCRIPT_DIR/.orion_singleton_sensex.lock"

# 3. Supervised launch loop (same shape as start_orion_v2520.sh)
BOT_SCRIPT="$SCRIPT_DIR/ORION_SENSEX_V2520.py"
EOD_CUTOFF_HHMM="1525"
MAX_RESTARTS=50
RESTART_BACKOFF=20
restarts=0
fast_fail_streak=0

while :; do
    rm -f "$SCRIPT_DIR/.orion_singleton_sensex.lock"
    orion_disk_guard "$LOG" "SENSEX attempt $((restarts+1))"
    echo "[$(date '+%H:%M:%S')] Starting ORION SENSEX (attempt $((restarts+1)))..." >> "$LOG"
    START_TS=$(date +%s)
    python3 -u "$BOT_SCRIPT" >> "$LOG" 2>&1 &
    BOT_PID=$!
    echo "$BOT_PID" > "$PID_FILE"
    echo "[$(date '+%H:%M:%S')] ORION SENSEX started (PID=$BOT_PID)" >> "$LOG"

    wait "$BOT_PID"
    RAN_SECS=$(( $(date +%s) - START_TS ))
    rm -f "$PID_FILE"

    NOW_HHMM=$(TZ="Asia/Kolkata" date +%H%M)
    if [ "$NOW_HHMM" -ge "$EOD_CUTOFF_HHMM" ]; then
        echo "[$(date '+%H:%M:%S')] ORION SENSEX exited at/after EOD cutoff ($NOW_HHMM IST) — clean shutdown, not restarting." >> "$LOG"
        break
    fi

    restarts=$((restarts+1))
    if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
        echo "[$(date '+%H:%M:%S')] ORION SENSEX died ${restarts}x before EOD — restart cap reached, giving up." >> "$LOG"
        python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': '🚨 ORION SENSEX crashed ${restarts}x and hit the restart cap. Bot is DOWN — check orion_sensex_run.log'})
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
        orion_tg "sensex_crashloop" 900 "🚨 ORION SENSEX crash-looping: ${fast_fail_streak} fast deaths in a row (last ran ${RAN_SECS}s, attempt ${restarts}). Check orion_sensex_run.log — likely ENOSPC or boot error."
    fi

    echo "[$(date '+%H:%M:%S')] ORION SENSEX died after ${RAN_SECS}s (pre-EOD) — restarting in ${RESTART_BACKOFF}s." >> "$LOG"
    sleep "$RESTART_BACKOFF"
done

echo "[$(date '+%H:%M:%S')] ORION SENSEX supervisor exited." >> "$LOG"
