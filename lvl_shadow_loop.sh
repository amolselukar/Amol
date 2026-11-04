#!/bin/bash
# LVL SHADOW 2-LOT — PAPER-ONLY (no orders). Reads lvl_engine signal + option 1m data,
# step-trails a hypothetical 2nd lot, posts to the V2520/LVL Telegram channel.
# Self-healing singleton; loop() self-exits at market close.
cd /home/selukar_amol123/Amol
export PYTHONPATH=/home/selukar_amol123/Amol
pgrep -f "lvl_shadow_2lot.py loop" >/dev/null && exit 0   # already running -> singleton
nohup /usr/bin/python3 /home/selukar_amol123/Amol/lvl_shadow_2lot.py loop >> /home/selukar_amol123/Amol/lvl_shadow_run.log 2>&1 &
