#!/bin/bash
# Auto-pull: watches for new pipeline commits and pulls automatically.
# Runs every 2 minutes. Only pulls when origin/main has new commits.
# --autostash handles a dirty working tree by stashing → rebasing → restoring.
# Stderr on git pull is NOT suppressed so failures are visible in the log.

REPO_DIR="$HOME/Huronalytics"
INTERVAL=120  # seconds between checks

cd "$REPO_DIR" || exit 1

while true; do
  git fetch origin main --quiet 2>/dev/null
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse origin/main)

  if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date '+%H:%M:%S')] New commits detected, pulling..."
    if git pull --rebase --autostash origin main --quiet; then
      echo "[$(date '+%H:%M:%S')] Updated to $(git rev-parse --short HEAD)"
    else
      echo "[$(date '+%H:%M:%S')] PULL FAILED — aborting rebase. Manual intervention needed."
      git rebase --abort 2>/dev/null
      # Recover any autostash that didn't get popped due to the failed rebase
      git stash list | grep -q 'autostash' && \
        echo "[$(date '+%H:%M:%S')] Autostash still present; run 'git stash pop' manually when ready."
    fi
  fi

  sleep $INTERVAL
done
