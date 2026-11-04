#!/bin/bash
# =========================================================================
# ORION MCA ANALYST AUTO-START — study-only per-second recorder
# Cron: 50 7 * * 1-5  (= 13:20 IST, Mon-Fri) — the process waits for 13:25
# itself, so a slightly early start is harmless.
# STUDY ONLY: no orders, no book, no P&L. Separate process from the trading
# bot on purpose (see CHANGE_HISTORY in ORION_MCA_ANALYST.py).
# =========================================================================
cd /home/selukar_amol123/Amol || exit 1
if pgrep -f "ORION_MCA_ANALYST.py" > /dev/null; then
  echo "$(date '+%F %T') MCA already running" >> /home/selukar_amol123/orion_mca_run.log
  exit 0
fi
nohup /usr/bin/python3 -u /home/selukar_amol123/Amol/ORION_MCA_ANALYST.py \
  >> /home/selukar_amol123/orion_mca_run.log 2>&1 &
echo "$(date '+%F %T') MCA launched (pid $!)" >> /home/selukar_amol123/orion_mca_run.log
