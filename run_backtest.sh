#!/bin/bash
# Run ORION backtests on PythonAnywhere
# Usage: bash run_backtest.sh
cd /home/Selukar/Amol
git fetch origin claude/general-session-YfHuZ
git reset --hard origin/claude/general-session-YfHuZ

echo "=============================="
echo " Running V2.5.9 (baseline)"
echo "=============================="
python3 ORION_BACKTEST_V2_5_9.py 2>&1 | tee /home/Selukar/backtest_v259.txt

echo ""
echo "=============================="
echo " Running V2.5.12 (VRL exits)"
echo "=============================="
python3 ORION_BACKTEST_V2_5_12.py 2>&1 | tee /home/Selukar/backtest_v2512.txt

echo ""
echo "=============================="
echo " SIDE-BY-SIDE SUMMARY"
echo "=============================="
echo "--- V2.5.9 ---"
grep -E "Trades|PnL|Win Rate|Max DD|Red Months" /home/Selukar/backtest_v259.txt | head -6
echo "--- V2.5.12 ---"
grep -E "Trades|PnL|Win Rate|Max DD|Red Months" /home/Selukar/backtest_v2512.txt | head -6

echo ""
echo "Full results saved to:"
echo "  /home/Selukar/backtest_v259.txt"
echo "  /home/Selukar/backtest_v2512.txt"
