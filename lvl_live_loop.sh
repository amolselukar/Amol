#!/bin/bash
# LVL LIVE NIFTY — REAL mSTOCK orders (qty=1 micro). Data via Upstox (lvl_engine),
# trades via mStock. Self-healing singleton; loop() self-exits at market close.
cd /home/selukar_amol123/Amol
export PYTHONPATH=/home/selukar_amol123/Amol
pgrep -f "lvl_live_nifty.py loop" >/dev/null && exit 0   # already running -> singleton
nohup /usr/bin/python3 /home/selukar_amol123/Amol/lvl_live_nifty.py loop >> /home/selukar_amol123/orion_lvl_live_run.log 2>&1 &
