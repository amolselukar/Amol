#!/bin/bash
# cleanup_retention.sh — keep disk from filling with regenerable per-day data.
# Built 2026-11-04 (user-directed). CONSERVATIVE by design:
#   - deletes ONLY specific regenerable per-day files older than RETAIN_DAYS
#     (flight-recorder logs, bar-level CSVs, daily option-data day-folders);
#   - truncates ever-growing *_run.log files that exceed MAXLOG_MB (keeps tail);
#   - NEVER touches .py / .sh / .json / credentials / tradebooks / .git / state.
# Run daily from cron. Logs every action to the retention log.

set -u
AMOL=/home/selukar_amol123/Amol
HOME_DIR=/home/selukar_amol123
RETAIN_DAYS=15
MAXLOG_MB=20
KEEP_LINES=5000
RLOG="$HOME_DIR/retention.log"
ts() { TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" >> "$RLOG"; }

log "=== retention run start (retain ${RETAIN_DAYS}d, maxlog ${MAXLOG_MB}MB) ==="

# 1) delete old regenerable per-day DATA files (exact name patterns only, files only)
for pat in "Nifty_FlightRecorder_*.log" "Sensex_FlightRecorder_*.log" \
           "Nifty_BarLevel_*.csv" "Sensex_BarLevel_*.csv" \
           "*_FlightRecorder_*.log" "*_BarLevel_*.csv"; do
    while IFS= read -r f; do
        log "del data: $f ($(du -h "$f" 2>/dev/null | cut -f1))"
        rm -f "$f"
    done < <(find "$AMOL" -maxdepth 1 -type f -name "$pat" -mtime +$RETAIN_DAYS 2>/dev/null)
done

# 2) delete old daily option-data day-folders (dir named like a date)
for base in "$AMOL/daily_option_data" "$AMOL/daily_option_data_sensex"; do
    [ -d "$base" ] || continue
    while IFS= read -r d; do
        log "del datadir: $d ($(du -sh "$d" 2>/dev/null | cut -f1))"
        rm -rf "$d"
    done < <(find "$base" -mindepth 1 -maxdepth 1 -type d -mtime +$RETAIN_DAYS 2>/dev/null)
done

# 3) truncate oversized append run-logs (keep last $KEEP_LINES lines). Never delete.
for L in "$HOME_DIR"/*_run.log "$HOME_DIR"/orion_*.log "$AMOL"/*.log; do
    [ -f "$L" ] || continue
    sz=$(( $(stat -c%s "$L" 2>/dev/null || echo 0) / 1048576 ))
    if [ "$sz" -ge "$MAXLOG_MB" ]; then
        tail -n "$KEEP_LINES" "$L" > "$L.tmp" 2>/dev/null && mv "$L.tmp" "$L"
        log "truncated log: $L (was ${sz}MB -> kept last ${KEEP_LINES} lines)"
    fi
done

log "=== retention run done | Amol working size now: $(du -sh --exclude=.git "$AMOL" 2>/dev/null | cut -f1) ==="
