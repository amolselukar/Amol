#!/bin/bash
# Auto-pull latest code from GitHub and run backtest
# Usage on PythonAnywhere: bash run_backtest.sh
cd /home/Selukar/Amol
git pull origin claude/general-session-YfHuZ
python3 ORION_BACKTEST_V2_5_6_LOCKED.py 2>&1 | tee /home/Selukar/backtest_results.txt
echo ""
echo "Results saved to /home/Selukar/backtest_results.txt"
