#!/bin/bash
# Auto-pull: watches for new pipeline commits and pulls automatically.
# Runs every 2 minutes. Only pulls when origin/main has new commits.
# --autostash handles a dirty working tree by stashing → rebasing → restoring.
# Stderr on git pull is NOT suppressed so failures are visible in the log.

REPO_DIR="$HOME/Huronalytics"
INTERVAL=120  # seconds between checks
PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3  # same as the launchd jobs

cd "$REPO_DIR" || exit 1

while true; do
  git fetch origin main --quiet 2>/dev/null

  # Only pull when origin/main has commits we don't have. Comparing hashes
  # directly (the previous check) treats local-ahead and remote-ahead the
  # same, so unpushed local commits made every cycle a no-op pull that still
  # touched the working tree via --autostash.
  if [ "$(git rev-list HEAD..origin/main --count)" -gt 0 ]; then
    echo "[$(date '+%H:%M:%S')] New commits detected, pulling..."
    if git pull --rebase --autostash origin main --quiet; then
      echo "[$(date '+%H:%M:%S')] Updated to $(git rev-parse --short HEAD)"
      # Daily pitcher scan: once per calendar day, after the FIRST pull that
      # carries a pipeline update (data/metadata_rs.json moved). The script
      # keeps its own marker (data/_daily_scan/last_run_date), so a second
      # pipeline run the same day is a no-op. Backgrounded: it reads Sheets
      # for ~2m30s and must not hold the pull loop.
      if git diff --name-only ORIG_HEAD HEAD 2>/dev/null | grep -q '^data/metadata_rs.json$' \
         && [ "$(cat data/_daily_scan/last_run_date 2>/dev/null)" != "$(date '+%Y-%m-%d')" ]; then
        echo "[$(date '+%H:%M:%S')] Pipeline update detected; starting daily pitcher scan"
        mkdir -p data/_daily_scan
        nohup "$PYTHON" scripts/tools/daily_pitcher_scan.py >> data/_daily_scan/run.log 2>&1 &
      fi
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
