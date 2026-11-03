#!/usr/bin/env python3
"""with_geocal.py — run any research script under a Loc+ geometry-calibration
arm without editing pipeline/locplus.py. (2026-09-19; sibling of
with_bandwidth.py and with_farmiss.py)

  python3 scripts/research/locplus/with_geocal.py 1:1:1:0.09:0.5:0.06:2 -- \\
      scripts/research/locplus/locplus_downstream_bandwidth.py build geoSWCS 6 0.30

The spec is sw:cs:bx:bz:csbx:csbz:kb[:lam[:region]] (locplus_geometry_calibration.py).
`0:0:...` is the control arm. The import patches pipeline.locplus BEFORE the
target loads, so `from pipeline.locplus import score_pitch` binds the patch.
Announced on stderr so a log is never mistaken for a shipped-constant run.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import pipeline.locplus as lp                           # noqa: E402
import locplus_geometry_calibration                     # noqa: E402,F401  (applies the patch)


def main():
    if '--' not in sys.argv or sys.argv.index('--') != 2:
        raise SystemExit(__doc__)
    v = [float(x) for x in sys.argv[1].split(':')]
    target, args = sys.argv[3], sys.argv[4:]
    (lp.GEOCAL_SW, lp.GEOCAL_CS, lp.GEOCAL_BX, lp.GEOCAL_BZ, lp.GEOCAL_CSBX, lp.GEOCAL_CSBZ,
     lp.GEOCAL_KB) = int(v[0]), int(v[1]), v[2], v[3], v[4], v[5], v[6]
    lp.GEOCAL_LAM = v[7] if len(v) > 7 else 1.0
    lp.GEOCAL_REGION = int(v[8]) if len(v) > 8 else 0
    print(f'[with_geocal] pipeline.locplus geometry calibration {sys.argv[1]} for {target}',
          file=sys.stderr, flush=True)
    sys.argv = [target] + args
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    runpy.run_path(target, run_name='__main__')


if __name__ == '__main__':
    main()
