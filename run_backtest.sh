#!/bin/bash
# Run ORION backtests on PythonAnywhere — full progression comparison
# Usage: bash run_backtest.sh
cd /home/Selukar/Amol
git fetch origin claude/general-session-YfHuZ
git reset --hard origin/claude/general-session-YfHuZ

echo "=============================="
echo " Running V2.5.8"
echo "=============================="
python3 ORION_BACKTEST_V2_5_8.py 2>&1 | tee /home/Selukar/backtest_v258.txt

echo ""
echo "=============================="
echo " Running V2.5.9"
echo "=============================="
python3 ORION_BACKTEST_V2_5_9.py 2>&1 | tee /home/Selukar/backtest_v259.txt

echo ""
echo "=============================="
echo " Running V2.5.12 (VRL exits)"
echo "=============================="
python3 ORION_BACKTEST_V2_5_12.py 2>&1 | tee /home/Selukar/backtest_v2512.txt

echo ""
echo "============================================================"
echo " FULL PROGRESSION SUMMARY"
echo "============================================================"
printf "%-12s %-8s %-14s %-10s %-10s %-12s\n" "VERSION" "TRADES" "PNL (Rs)" "WIN_RATE" "MAX_DD" "RED_MONTHS"
echo "------------------------------------------------------------"

extract() {
    local file=$1 version=$2
    local trades pnl wr dd red
    trades=$(grep "Trades" "$file" | grep -v "#" | tail -1 | awk '{print $NF}')
    pnl=$(grep "PnL (Rs)" "$file" | tail -1 | awk '{print $NF}')
    wr=$(grep "Win Rate" "$file" | tail -1 | awk '{print $NF}')
    dd=$(grep "Max DD" "$file" | tail -1 | awk '{print $NF}' | tr -d 'pts')
    red=$(grep "Red Months" "$file" | tail -1 | awk '{print $NF}')
    printf "%-12s %-8s %-14s %-10s %-10s %-12s\n" "$version" "$trades" "$pnl" "$wr" "$dd" "$red"
}

extract /home/Selukar/backtest_v258.txt   "V2.5.8"
extract /home/Selukar/backtest_v259.txt   "V2.5.9"
extract /home/Selukar/backtest_v2512.txt  "V2.5.12"

echo "============================================================"
echo ""
echo "Full logs: backtest_v258.txt / backtest_v259.txt / backtest_v2512.txt"
