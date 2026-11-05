#!/bin/bash
cd /home/selukar_amol123/Amol
export PYTHONPATH=/home/selukar_amol123/Amol
pgrep -f "ORION_SELLER_V1.py loop" >/dev/null && exit 0   # singleton
nohup /usr/bin/python3 /home/selukar_amol123/Amol/ORION_SELLER_V1.py loop >> /home/selukar_amol123/orion_seller_run.log 2>&1 &
