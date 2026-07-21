"""ABS pipeline orchestrator: keep the challenge matrix current.

Runs, in order (each step consumes the previous step's output):
  1. abs_challenges.py     - append newly-final games to the dataset (~1 min)
  2. abs_value_engine.py   - rebuild RE24 / count values / WP tables (~4 min)
  3. abs_option_model.py   - perception fits + C(k,T,score) DP (~2 min)
  4. abs_player_grades.py  - decision grades + CSVs to ~/Downloads (~2 min)
  5. abs_backtest.py       - only with --backtest (weekly is plenty)

Scheduled via cron (installed 2026-07-20):
  30 7 * * * cd ~/Huronalytics && python3 scripts/abs_daily.py >> ~/Library/Logs/abs_daily.log 2>&1

Usage:
    python3 scripts/abs_daily.py [--backtest] [--skip-tables]
--skip-tables skips steps 2-3 (value tables and option model move slowly day
to day; a few days of lag is harmless if you want a faster refresh).
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime

STEPS = [
    ("dataset", ["abs_challenges.py"]),
    ("value tables", ["abs_value_engine.py"]),
    ("option model", ["abs_option_model.py"]),
    ("player grades", ["abs_player_grades.py"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--skip-tables", action="store_true")
    args = ap.parse_args()

    steps = list(STEPS)
    if args.skip_tables:
        steps = [s for s in steps if s[0] not in ("value tables", "option model")]
    if args.backtest:
        steps.append(("backtest", ["abs_backtest.py"]))

    print(f"=== abs_daily {datetime.now().isoformat(timespec='seconds')} ===")
    for name, cmd in steps:
        t0 = time.time()
        r = subprocess.run([sys.executable, "scripts/" + cmd[0]] + cmd[1:])
        dt = time.time() - t0
        if r.returncode != 0:
            print(f"FAILED at {name} ({dt:.0f}s), stopping")
            sys.exit(r.returncode)
        print(f"--- {name} done in {dt:.0f}s")
    print("=== all steps complete ===")


if __name__ == "__main__":
    main()
