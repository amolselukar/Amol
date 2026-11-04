#!/bin/bash
# DISK DEEP SCAN — runs ONCE after market close, appends file-level detail to the
# cleanup report, then removes its own cron line. Observe-only, deletes nothing.
# Created 2026-10-30 (user: scan all disk, prepare deletable-data report for EOD review).
REPORT="/home/selukar_amol123/DISK_CLEANUP_REPORT_2026-10-30.txt"
HOME_DIR="/home/selukar_amol123"

{
echo ""
echo "############################################################"
echo "## DEEP SCAN (post-close)  $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M IST')"
echo "############################################################"
echo ""
echo "=== df ==="; df -h / | tail -1
echo ""
echo "=== TOP 40 LARGEST FILES under \$HOME ==="
du -ah "$HOME_DIR" 2>/dev/null | sort -rh | head -40
echo ""
echo "=== Amol subdirs (depth 2, >1M) ==="
du -h --max-depth=2 "$HOME_DIR/Amol" 2>/dev/null | sort -rh | awk '$1 ~ /[0-9]M|[0-9]G/'
echo ""
echo "=== All *.log >1M (size, mtime) ==="
find "$HOME_DIR" -name '*.log' -size +1M -printf '%s\t%TY-%Tm-%Td\t%p\n' 2>/dev/null | sort -rn | awk '{printf "%.1fM\t%s\t%s\n",$1/1048576,$2,$3}'
echo ""
echo "=== All *.csv >0.5M (size, mtime) ==="
find "$HOME_DIR" -name '*.csv' -size +512k -printf '%s\t%TY-%Tm-%Td\t%p\n' 2>/dev/null | sort -rn | awk '{printf "%.1fM\t%s\t%s\n",$1/1048576,$2,$3}'
echo ""
echo "=== *.pkl / *.parquet / *.h5 (size, mtime) ==="
find "$HOME_DIR" \( -name '*.pkl' -o -name '*.parquet' -o -name '*.h5' \) -printf '%s\t%TY-%Tm-%Td\t%p\n' 2>/dev/null | sort -rn | head -30 | awk '{printf "%.1fM\t%s\t%s\n",$1/1048576,$2,$3}'
echo ""
echo "=== Research/workdirs NOT touched in >21 days (candidates to purge) ==="
for d in "$HOME_DIR"/Amol/*/; do
  last=$(find "$d" -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1)
  if [ -n "$last" ]; then
    age=$(( ( $(date +%s) - ${last%.*} ) / 86400 ))
    sz=$(du -sh "$d" 2>/dev/null | cut -f1)
    echo "$age days  $sz  $d"
  fi
done | sort -rn | head -40
echo ""
echo "=== biggest git-history blobs (reclaimable only via history rewrite) ==="
cd "$HOME_DIR/Amol" && git rev-list --objects --all 2>/dev/null | \
  git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' 2>/dev/null | \
  awk '$1=="blob"{print $2, $3}' | sort -rn | uniq | head -15 | awk '{printf "%.1fM %s\n",$1/1048576,$2}'
echo ""
echo "=== DEEP SCAN COMPLETE ==="
} >> "$REPORT" 2>&1

# remove own cron line so it runs only once
crontab -l 2>/dev/null | grep -v "disk_deep_scan.sh" | crontab -
echo "[$(TZ=Asia/Kolkata date '+%H:%M IST')] deep scan done, cron line removed" >> "$HOME_DIR/Amol/disk_deep_scan.log"
