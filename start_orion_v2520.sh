#!/bin/bash
# =========================================================================
# ORION V2.5.20 AUTO-START  —  Google Cloud VPS cron task
# =========================================================================
# Cron entry (crontab -e):
#   32 3 * * 1-5 bash /home/selukar_amol123/Amol/start_orion_v2520.sh
#   (= 09:02 IST, Mon-Fri)
#
# 2026-08-01: V2.5.19 is stopped (replaced by PROB70 in that cron slot). This
# script no longer depends on any other bot's launcher for its Kite token --
# it refreshes its own via auto_login.py below, so it is fully self-sufficient
# regardless of what else is or isn't running.
#
# V2.5.20 runs ALONGSIDE V2.5.19 (not a replacement): separate process,
# separate singleton lock (.orion_singleton_v2520.lock), separate state/
# log/CSV files (state_V2_5_20.json, Nifty_*_V2_5_20_*), same PAPER broker
# (EXECUTION_BROKER hardcoded "kite_paper", /live command disabled), same
# Telegram chat but outbound-only (no getUpdates polling -- see comment at
# main()'s tg_cmd_thread in ORION_PAPER_V2_5_20.py).
# =========================================================================

LOG="/home/selukar_amol123/orion_v2520_run.log"
SCRIPT_DIR="/home/selukar_amol123/Amol"
PID_FILE="$SCRIPT_DIR/.orion_v2520.pid"

# Weekend guard — exit silently on Sat (6) and Sun (7) IST
DOW=$(TZ="Asia/Kolkata" date +%u)
if [ "$DOW" -ge 6 ]; then
    echo "[$(TZ="Asia/Kolkata" date '+%Y-%m-%d %H:%M:%S')] Weekend — ORION V2.5.20 skipped (DOW=$DOW)" >> "$LOG"
    exit 0
fi

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ORION V2.5.20 START" >> "$LOG"
echo "========================================" >> "$LOG"

# Infra guard (2026-07-19) — disk precheck + throttled Telegram + death alerts.
# Prevents a repeat of the 2026-07-17 ENOSPC crash-loop that ran silently.
source "$SCRIPT_DIR/orion_infra_guard.sh"
orion_disk_guard "$LOG" "V2.5.20 boot"

# 0. Kill any existing V2.5.20 instance only (never touches V2.5.19/others)
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] Killing existing ORION V2.5.20 (PID=$OLD_PID)..." >> "$LOG"
        kill "$OLD_PID" 2>/dev/null
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi
pkill -f "ORION_PAPER_V2_5_20.py" 2>/dev/null || true
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
              'text': '🚨 ORION V2.5.20 failed to start: Upstox token validation error. Check orion_v2520_run.log'})
except: pass
" 2>/dev/null
    exit 1
fi

# 2. Remove stale singleton lock (from a previous crash/kill) — V2.5.20's
#    own lock file only, never V2.5.19's.
rm -f "$SCRIPT_DIR/.orion_singleton_v2520.lock"

# 3. Supervised launch loop (mirrors start_orion.sh; no V2.5.14-style
#    fallback build exists for V2.5.20, so a persistent crash just retries
#    up to MAX_RESTARTS then gives up and alerts).
BOT_SCRIPT="$SCRIPT_DIR/ORION_PAPER_V2_5_20.py"
EOD_CUTOFF_HHMM="1525"        # IST — after this, a bot exit is "clean EOD"
# 2026-07-08 FIX: mStock's order API isn't consistently ready for the boot
# self-test right at 09:02 IST — both 2026-07-07 and 2026-07-08 saw ~9
# straight self-test failures before mStock came up (worked once actual
# market session opened, ~09:15-09:18 IST). 10 restarts x ~27s cycle only
# covers to ~09:06 -- well before that. Widened so the retry window comfortably
# spans past market open instead of giving up and needing a manual restart.
MAX_RESTARTS=50
RESTART_BACKOFF=20
restarts=0
fast_fail_streak=0            # consecutive <60s deaths — early crash-loop alert

while :; do
    rm -f "$SCRIPT_DIR/.orion_singleton_v2520.lock"
    orion_disk_guard "$LOG" "V2.5.20 attempt $((restarts+1))"
    echo "[$(date '+%H:%M:%S')] Starting ORION V2.5.20 (attempt $((restarts+1)))..." >> "$LOG"
    START_TS=$(date +%s)
    python3 -u "$BOT_SCRIPT" >> "$LOG" 2>&1 &
    BOT_PID=$!
    echo "$BOT_PID" > "$PID_FILE"
    echo "[$(date '+%H:%M:%S')] ORION V2.5.20 started (PID=$BOT_PID)" >> "$LOG"

    wait "$BOT_PID"
    RAN_SECS=$(( $(date +%s) - START_TS ))
    rm -f "$PID_FILE"

    NOW_HHMM=$(TZ="Asia/Kolkata" date +%H%M)
    if [ "$NOW_HHMM" -ge "$EOD_CUTOFF_HHMM" ]; then
        echo "[$(date '+%H:%M:%S')] ORION V2.5.20 exited at/after EOD cutoff ($NOW_HHMM IST) — clean shutdown, not restarting." >> "$LOG"
        break
    fi

    restarts=$((restarts+1))
    if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
        echo "[$(date '+%H:%M:%S')] ORION V2.5.20 died ${restarts}x before EOD — restart cap reached, giving up." >> "$LOG"
        python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': '🚨 ORION V2.5.20 crashed ${restarts}x and hit the restart cap. Bot is DOWN — check orion_v2520_run.log'})
except: pass
" 2>/dev/null
        break
    fi

    # Early crash-loop alert — do NOT wait for the 50-restart cap (2026-07-17
    # crash-looped 28x, below the cap, so it never alerted). After 3 straight
    # fast (<60s) deaths, fire ONE throttled Telegram (repeats at most /15min).
    if [ "$RAN_SECS" -lt 60 ]; then
        fast_fail_streak=$((fast_fail_streak+1))
    else
        fast_fail_streak=0
    fi
    if [ "$fast_fail_streak" -ge 3 ]; then
        orion_tg "v2520_crashloop" 900 "🚨 ORION V2.5.20 crash-looping: ${fast_fail_streak} fast deaths in a row (last ran ${RAN_SECS}s, attempt ${restarts}). Check orion_v2520_run.log — likely ENOSPC or boot error."
    fi

    echo "[$(date '+%H:%M:%S')] ORION V2.5.20 died after ${RAN_SECS}s (pre-EOD) — restarting in ${RESTART_BACKOFF}s." >> "$LOG"
    sleep "$RESTART_BACKOFF"
done

echo "[$(date '+%H:%M:%S')] ORION V2.5.20 supervisor exited." >> "$LOG"
