#!/usr/bin/env python3
"""with_handneutral.py: run any research script with the hand-neutral Loc+
patch installed (2026-11-11; sibling of with_geocal.py). The patch is inert
until the target sets pipeline.locplus.HANDNEU, e.g. through the target
audit's --flag:

  python3 scripts/research/locplus/with_handneutral.py -- \\
      scripts/research/locplus/locplus_target_audit.py run \\
      --flag ctl1111=HANDNEU_TAG:1 --flag handNeu1111=HANDNEU:1

Announced on stderr so a log is never mistaken for a shipped-constant run.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import locplus_handneutral  # noqa: E402,F401  (installs the inert patch)


def main():
    if '--' not in sys.argv or sys.argv.index('--') != 1:
        raise SystemExit(__doc__)
    target, args = sys.argv[2], sys.argv[3:]
    print(f'[with_handneutral] pipeline.locplus hand-neutral patch installed for {target}',
          file=sys.stderr, flush=True)
    sys.argv = [target] + args
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    runpy.run_path(target, run_name='__main__')


if __name__ == '__main__':
    main()
