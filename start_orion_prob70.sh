#!/bin/bash
# =========================================================================
# ORION PROB70 AUTO-START  —  Google Cloud VPS cron task
# =========================================================================
# Cron entry (crontab -e):
#   30 3 * * 1-5 bash /home/selukar_amol123/Amol/start_orion_prob70.sh
#   (= 09:00 IST, Mon-Fri)
#
# 2026-08-01: REPLACES start_orion.sh (V2.5.19) in this cron slot, per user
# instruction to stop V2.5.19 and run PROB70 (single conservative engine:
# day-type gate + level confluence + countertrend veto + premium confluence
# entry, pivot-target/base-stop/giveback-lock exit) instead, from Monday.
#
# Self-sufficient: refreshes its own Kite access token via auto_login.py
# below, with no dependency on V2.5.19 (stopped) or V2.5.20's launcher/timing
# -- V2.5.20 independently refreshes its own token too (2026-08-01 fix),
# so neither bot depends on the other's cron ordering or existence.
#
# V2.5.20 is left completely untouched -- separate process, separate
# singleton lock, separate state/log files, unaffected by this change.
# PROB70 runs PAPER only (EXECUTION_BROKER hardcoded "kite_paper", /live
# command disabled, real-order code paths physically removed from the file).
# =========================================================================

LOG="/home/selukar_amol123/orion_prob70_run.log"
SCRIPT_DIR="/home/selukar_amol123/Amol"
PID_FILE="$SCRIPT_DIR/.orion_prob70.pid"

# Weekend guard — exit silently on Sat (6) and Sun (7) IST
DOW=$(TZ="Asia/Kolkata" date +%u)
if [ "$DOW" -ge 6 ]; then
    echo "[$(TZ="Asia/Kolkata" date '+%Y-%m-%d %H:%M:%S')] Weekend — ORION PROB70 skipped (DOW=$DOW)" >> "$LOG"
    exit 0
fi

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ORION PROB70 START" >> "$LOG"
echo "========================================" >> "$LOG"

# Infra guard (reused from V2.5.19/20) — disk precheck + throttled Telegram + death alerts.
source "$SCRIPT_DIR/orion_infra_guard.sh"
orion_disk_guard "$LOG" "PROB70 boot"

# 0. Kill any existing PROB70 instance only (never touches V2.5.19/V2.5.20)
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] Killing existing ORION PROB70 (PID=$OLD_PID)..." >> "$LOG"
        kill "$OLD_PID" 2>/dev/null
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi
pkill -f "ORION_PAPER_PROB70.py" 2>/dev/null || true
sleep 1

cd "$SCRIPT_DIR" || { echo "FATAL: $SCRIPT_DIR not found"; exit 1; }

# 1. Refresh Kite access token via TOTP auto-login (self-sufficient, no dependency on V2.5.19/20)
echo "[$(date '+%H:%M:%S')] Refreshing Kite access token..." >> "$LOG"
python3 "$SCRIPT_DIR/auto_login.py" >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "[$(date '+%H:%M:%S')] FATAL: auto_login failed — aborting" >> "$LOG"
    python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': '🚨 ORION PROB70 failed to start: auto-login error. Check orion_prob70_run.log'})
except: pass
" 2>/dev/null
    exit 1
fi

# 2. Remove stale singleton lock (from a previous crash/kill) — PROB70's own lock only.
rm -f "$SCRIPT_DIR/.orion_singleton_prob70.lock"

# 3. Supervised launch loop (mirrors start_orion_v2520.sh; no fallback build exists)
BOT_SCRIPT="$SCRIPT_DIR/ORION_PAPER_PROB70.py"
EOD_CUTOFF_HHMM="1525"        # IST — after this, a bot exit is "clean EOD"
MAX_RESTARTS=50
RESTART_BACKOFF=20
restarts=0
fast_fail_streak=0            # consecutive <60s deaths — early crash-loop alert

while :; do
    rm -f "$SCRIPT_DIR/.orion_singleton_prob70.lock"
    orion_disk_guard "$LOG" "PROB70 attempt $((restarts+1))"
    echo "[$(date '+%H:%M:%S')] Starting ORION PROB70 (attempt $((restarts+1)))..." >> "$LOG"
    START_TS=$(date +%s)
    python3 -u "$BOT_SCRIPT" >> "$LOG" 2>&1 &
    BOT_PID=$!
    echo "$BOT_PID" > "$PID_FILE"
    echo "[$(date '+%H:%M:%S')] ORION PROB70 started (PID=$BOT_PID)" >> "$LOG"

    wait "$BOT_PID"
    RAN_SECS=$(( $(date +%s) - START_TS ))
    rm -f "$PID_FILE"

    NOW_HHMM=$(TZ="Asia/Kolkata" date +%H%M)
    if [ "$NOW_HHMM" -ge "$EOD_CUTOFF_HHMM" ]; then
        echo "[$(date '+%H:%M:%S')] ORION PROB70 exited at/after EOD cutoff ($NOW_HHMM IST) — clean shutdown, not restarting." >> "$LOG"
        break
    fi

    restarts=$((restarts+1))
    if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
        echo "[$(date '+%H:%M:%S')] ORION PROB70 died ${restarts}x before EOD — restart cap reached, giving up." >> "$LOG"
        python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': '🚨 ORION PROB70 crashed ${restarts}x and hit the restart cap. Bot is DOWN — check orion_prob70_run.log'})
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
        orion_tg "prob70_crashloop" 900 "🚨 ORION PROB70 crash-looping: ${fast_fail_streak} fast deaths in a row (last ran ${RAN_SECS}s, attempt ${restarts}). Check orion_prob70_run.log — likely ENOSPC or boot error."
    fi

    echo "[$(date '+%H:%M:%S')] ORION PROB70 died after ${RAN_SECS}s (pre-EOD) — restarting in ${RESTART_BACKOFF}s." >> "$LOG"
    sleep "$RESTART_BACKOFF"
done

echo "[$(date '+%H:%M:%S')] ORION PROB70 supervisor exited." >> "$LOG"
