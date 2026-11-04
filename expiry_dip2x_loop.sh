#!/bin/bash
cd /home/selukar_amol123/Amol
export PYTHONPATH=/home/selukar_amol123/Amol
pgrep -f "expiry_dip2x_tracker.py loop" >/dev/null && exit 0   # singleton
nohup /usr/bin/python3 /home/selukar_amol123/Amol/expiry_dip2x_tracker.py loop >> /home/selukar_amol123/expiry_dip2x_run.log 2>&1 &
