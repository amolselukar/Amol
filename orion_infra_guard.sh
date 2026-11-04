#!/bin/bash
# =========================================================================
# ORION INFRA GUARD  —  shared helpers sourced by start_orion*.sh
# =========================================================================
# Created 2026-07-19 in response to the 2026-07-17 outage:
#   * both bots died on ENOSPC (root disk full, ~/.npm cache = 2.5 GB) and
#     crash-looped ~28x SILENTLY — no Telegram alert until the restart cap,
#     which V2.5.20 (cap=50) never reached, so the whole afternoon was lost
#     with no warning. Move 2 (+134.9 pts) was 100% unreachable.
#     See memory: orion-v2520-monitor-2026-07-17-two-moves-missed-analysis
#
# Provides two functions:
#   orion_tg   KEY MIN_INTERVAL_SEC TEXT   -> throttled Telegram alert
#   orion_disk_guard LOGFILE [TAG]         -> free-space check + trim + alert
#
# Both are best-effort and NEVER fail the caller (always return 0). A guard
# that aborts the launch would be worse than the problem it solves.
# =========================================================================

ORION_GUARD_DIR="${ORION_GUARD_DIR:-/home/selukar_amol123/Amol}"
ORION_TG_STATE_DIR="${ORION_TG_STATE_DIR:-/tmp/orion_tg_state}"

# Free-space thresholds on the 9.7 GB root disk (KB).
# SOFT: below this we trim caches. HARD: below this (after trim) we alert.
ORION_DISK_SOFT_KB="${ORION_DISK_SOFT_KB:-1572864}"   # 1.5 GB
ORION_DISK_HARD_KB="${ORION_DISK_HARD_KB:-524288}"    #  512 MB

# -------------------------------------------------------------------------
# orion_tg KEY MIN_INTERVAL_SEC TEXT
#   Send a Telegram message, but at most once per MIN_INTERVAL_SEC per KEY.
#   Throttling stops the 246x / 28x spam seen on 2026-07-07 and 2026-07-17.
# -------------------------------------------------------------------------
orion_tg() {
    local key="$1" min_interval="$2" text="$3"
    mkdir -p "$ORION_TG_STATE_DIR" 2>/dev/null
    local stamp="$ORION_TG_STATE_DIR/$key"
    local now last=0
    now=$(date +%s)
    if [ -f "$stamp" ]; then
        last=$(cat "$stamp" 2>/dev/null || echo 0)
    fi
    if [ $((now - last)) -lt "$min_interval" ]; then
        return 0   # throttled
    fi
    echo "$now" > "$stamp" 2>/dev/null
    python3 -c "
import sys; sys.path.insert(0,'$ORION_GUARD_DIR')
try:
    import credentials as c, requests
    requests.post(f'https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': c.TELEGRAM_CHAT_ID, 'text': '''$text'''}, timeout=10)
except Exception:
    pass
" 2>/dev/null
    return 0
}

# -------------------------------------------------------------------------
# orion_disk_guard LOGFILE [TAG]
#   Measure free space on / . If below SOFT, trim known-safe caches
#   (npm, pip, journald, old /tmp files, apt) then re-measure. If still
#   below HARD, fire a throttled CRITICAL Telegram. Always returns 0.
# -------------------------------------------------------------------------
orion_disk_guard() {
    local logfile="$1" tag="${2:-ORION}"
    local free_kb
    free_kb=$(df -Pk / | awk 'NR==2{print $4}')
    echo "[$(date '+%H:%M:%S')] [disk-guard] $tag free=$((free_kb/1024))MB (soft=$((ORION_DISK_SOFT_KB/1024))MB hard=$((ORION_DISK_HARD_KB/1024))MB)" >> "$logfile"

    if [ "$free_kb" -ge "$ORION_DISK_SOFT_KB" ]; then
        return 0   # plenty of room, nothing to do
    fi

    echo "[$(date '+%H:%M:%S')] [disk-guard] below soft threshold — trimming caches..." >> "$logfile"
    # 1. npm cache — THE 2026-07-17 culprit (ballooned to 2.5 GB)
    rm -rf /home/selukar_amol123/.npm/_cacache 2>/dev/null
    # 2. pip cache
    rm -rf /home/selukar_amol123/.cache/pip 2>/dev/null
    # 3. journald — cap persistent size
    journalctl --vacuum-size=50M >/dev/null 2>&1
    # 4. /tmp files older than 1 day (never the current session's)
    find /tmp -mindepth 1 -maxdepth 1 -mtime +1 ! -name 'orion_tg_state' -exec rm -rf {} + 2>/dev/null
    # 5. apt cache (sudo is passwordless on this box; harmless if not)
    sudo -n apt-get clean >/dev/null 2>&1 || true

    free_kb=$(df -Pk / | awk 'NR==2{print $4}')
    echo "[$(date '+%H:%M:%S')] [disk-guard] after trim: free=$((free_kb/1024))MB" >> "$logfile"

    if [ "$free_kb" -lt "$ORION_DISK_HARD_KB" ]; then
        echo "[$(date '+%H:%M:%S')] [disk-guard] STILL below hard threshold — alerting." >> "$logfile"
        orion_tg "disk_critical" 1800 "⚠️ ORION disk LOW: only $((free_kb/1024))MB free on / after auto-trim ($tag). ENOSPC risk — bots may crash-loop. Check the VM."
    fi
    return 0
}
