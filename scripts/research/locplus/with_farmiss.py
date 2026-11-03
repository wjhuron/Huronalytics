#!/usr/bin/env python3
"""with_farmiss.py — run any research script under a candidate Loc+ far-miss
rule without editing pipeline/locplus.py. (2026-09-19; sibling of
with_bandwidth.py)

  python3 scripts/research/locplus/with_farmiss.py 27 - - -- \\
      scripts/research/locplus/locplus_downstream_bandwidth.py build fm27 6 0.30

Arguments are X_IN Z_LO Z_HI (`-` = that cutoff off; all three `-` is the
control arm, rule off). Importing locplus_farmiss_rule patches
pipeline.locplus.score_pitch / build_surfaces BEFORE the target is loaded,
so a target that does `from pipeline.locplus import score_pitch` binds the
patched function as well. Score-only (mode A); the surfaces are untouched.

The patch is announced on stderr so a log can never be mistaken for a
shipped-constant run.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import pipeline.locplus as lp                           # noqa: E402
import locplus_farmiss_rule                             # noqa: E402,F401  (applies the patch)


def main():
    if '--' not in sys.argv or sys.argv.index('--') != 4:
        raise SystemExit(__doc__)
    x, lo, hi = (None if s == '-' else float(s) for s in sys.argv[1:4])
    target, args = sys.argv[5], sys.argv[6:]
    lp.FARMISS_X_IN, lp.FARMISS_Z_LO, lp.FARMISS_Z_HI, lp.FARMISS_BUILD = x, lo, hi, 0
    print(f'[with_farmiss] pipeline.locplus far-miss rule x {x} in / lo {lo} / hi {hi} '
          f'(score-only) for {target}', file=sys.stderr, flush=True)
    sys.argv = [target] + args
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    runpy.run_path(target, run_name='__main__')


if __name__ == '__main__':
    main()
