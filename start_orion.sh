#!/bin/bash
# =========================================================================
# ORION AUTO-START  —  PythonAnywhere scheduled task
# =========================================================================
# Schedule this on PythonAnywhere Tasks tab:
#   Command : bash /home/Selukar/Amol/start_orion.sh
#   UTC Time: 03:30  (= 09:00 IST, Mon–Fri)
# =========================================================================

LOG="/home/Selukar/orion_run.log"
SCRIPT_DIR="/home/Selukar/Amol"

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ORION START" >> "$LOG"
echo "========================================" >> "$LOG"

# 1. Pull latest code from GitHub
echo "[$(date '+%H:%M:%S')] Pulling latest code..." >> "$LOG"
cd "$SCRIPT_DIR" || { echo "FATAL: $SCRIPT_DIR not found"; exit 1; }
git pull origin claude/general-session-YfHuZ >> "$LOG" 2>&1

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

# 3. Start the paper bot (output appended to log)
echo "[$(date '+%H:%M:%S')] Starting ORION paper bot..." >> "$LOG"
python3 "$SCRIPT_DIR/ORION_PAPER_V2_5_6.py" >> "$LOG" 2>&1

echo "[$(date '+%H:%M:%S')] ORION exited." >> "$LOG"
