#!/bin/bash
# =========================================================================
# ORION EOD CAPTURE  —  PythonAnywhere scheduled task
# =========================================================================
# Schedule on PythonAnywhere Tasks tab:
#   Command : bash /home/Selukar/Amol/eod_capture.sh
#   UTC Time: 10:10  (= 15:40 IST, Mon–Fri)
# =========================================================================

LOG="/home/Selukar/orion_run.log"
SCRIPT_DIR="/home/Selukar/Amol"

# Weekend guard
DOW=$(TZ="Asia/Kolkata" date +%u)
if [ "$DOW" -ge 6 ]; then
    echo "[$(TZ="Asia/Kolkata" date '+%Y-%m-%d %H:%M:%S')] Weekend — EOD capture skipped" >> "$LOG"
    exit 0
fi

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] EOD CAPTURE START" >> "$LOG"
echo "========================================" >> "$LOG"

cd "$SCRIPT_DIR" || { echo "FATAL: $SCRIPT_DIR not found" >> "$LOG"; exit 1; }

# 1. Pull latest code
echo "[$(date '+%H:%M:%S')] Pulling latest code..." >> "$LOG"
git fetch origin claude/general-session-YfHuZ >> "$LOG" 2>&1
git reset --hard origin/claude/general-session-YfHuZ >> "$LOG" 2>&1

# 2. Refresh Kite token (needed for historical_data + quote calls)
echo "[$(date '+%H:%M:%S')] Refreshing Kite token..." >> "$LOG"
python3 "$SCRIPT_DIR/auto_login.py" >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "[$(date '+%H:%M:%S')] FATAL: auto_login failed — aborting EOD capture" >> "$LOG"
    python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': 'ORION EOD capture failed: auto-login error. Run Optiondata_1.py manually.'})
except: pass
" 2>/dev/null
    exit 1
fi

# 3. Run EOD data capture + OI analysis (Optiondata_1.py calls eod_analysis.py automatically)
echo "[$(date '+%H:%M:%S')] Running EOD data capture + OI analysis..." >> "$LOG"
python3 -u "$SCRIPT_DIR/Optiondata_1.py" >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "[$(date '+%H:%M:%S')] EOD capture failed — check log" >> "$LOG"
    python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID,
              'text': 'ORION EOD capture FAILED. Check orion_run.log or run Optiondata_1.py manually.'})
except: pass
" 2>/dev/null
    exit 1
fi

echo "[$(date '+%H:%M:%S')] EOD capture complete." >> "$LOG"
