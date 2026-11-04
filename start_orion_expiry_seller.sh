#!/bin/bash
# ORION EXPIRY SELLER — expiry-day-only paper bot (NIFTY Tue / SENSEX Thu, decided from the instrument master).
# Cron: 50 3 * * 1-5 (= 09:20 IST). The process exits by itself on a non-expiry day.
cd /home/selukar_amol123/Amol || exit 1
LOG=/home/selukar_amol123/orion_expiry_seller_run.log
if pgrep -f "ORION_EXPIRY_SELLER.py" > /dev/null; then echo "$(date '+%F %T') already running" >> $LOG; exit 0; fi
nohup /usr/bin/python3 -u /home/selukar_amol123/Amol/ORION_EXPIRY_SELLER.py >> $LOG 2>&1 &
echo "$(date '+%F %T') EXPIRY SELLER launched (pid $!)" >> $LOG
