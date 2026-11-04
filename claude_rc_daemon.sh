#!/usr/bin/env bash
set -u
cd "$HOME/Amol" || exit 1
export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"
while true; do
  echo "[claude-rc] starting $(date -u '+%F %T UTC')"
  script -qec "claude remote-control --spawn same-dir --permission-mode bypassPermissions --name amolorion-vm --remote-control-session-name-prefix amolorion" /dev/null
  echo "[claude-rc] exited $(date -u '+%F %T UTC'); restart in 10s"
  sleep 10
done
