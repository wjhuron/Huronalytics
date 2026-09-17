#!/usr/bin/env python3
"""with_bandwidth.py — run any research script under a candidate Loc+
smoothing bandwidth without editing pipeline/locplus.py. (2026-09-17)

  python3 scripts/research/locplus/with_bandwidth.py 9 0.55 -- \\
      scripts/research/locplus/locplus_stabilize_celllevel.py [args...]

It imports pipeline.locplus, sets PHYS_X_IN / PHYS_Z_FRAC and rebuilds the
two kernels (_KX, _KZ) exactly as the module does at import, then runs the
target with runpy under __main__. Every later `import pipeline.locplus` in
the target gets the same, already-patched module object. A target that
caches Loc+ scores on disk writes them under the candidate bandwidth: point
it at a scratch path, or move the cache back afterwards.

The patch is announced on stderr so a log can never be mistaken for a
shipped-constant run.
"""
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import pipeline.locplus as lp                           # noqa: E402


def main():
    if '--' not in sys.argv or sys.argv.index('--') != 3:
        raise SystemExit(__doc__)
    bx, bz = float(sys.argv[1]), float(sys.argv[2])
    target, args = sys.argv[4], sys.argv[5:]
    was = (lp.PHYS_X_IN, lp.PHYS_Z_FRAC)
    lp.PHYS_X_IN, lp.PHYS_Z_FRAC = bx, bz
    lp._KX = lp._k1d(lp.PHYS_X_IN / lp.BIN_X_IN)
    lp._KZ = lp._k1d(lp.PHYS_Z_FRAC / lp.BIN_Z)
    print(f'[with_bandwidth] pipeline.locplus PHYS_X_IN/PHYS_Z_FRAC {was[0]}/{was[1]} '
          f'-> {bx}/{bz} for {target}', file=sys.stderr, flush=True)
    sys.argv = [target] + args
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    runpy.run_path(target, run_name='__main__')


if __name__ == '__main__':
    main()
