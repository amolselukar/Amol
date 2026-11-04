#!/bin/bash
cd /home/selukar_amol123/Amol
export PYTHONPATH=/home/selukar_amol123/Amol
pgrep -f "lvl_engine.py loop" >/dev/null && exit 0   # already running -> singleton
nohup /usr/bin/python3 /home/selukar_amol123/Amol/lvl_engine.py loop >> /home/selukar_amol123/orion_lvl_run.log 2>&1 &
