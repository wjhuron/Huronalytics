"""locplus_handneutral.py: a hand-neutral Loc+ arm, applied as a patch to
pipeline.locplus (2026-11-11). Importing this module installs the patch; it
is a no-op until lp.HANDNEU is set true.

Shipped Loc+ scores a pitch on its (group, batter hand, pitcher hand) surface
and standardizes within the group only, so a group that is worse against
opposite-hand hitters at every location (the sinker: 23-28 Loc+ points per
pitch at a FIXED location, locplus_platoon_level.py) loses Loc+ in proportion
to its opposite-hand share. The arm removes that level:

    v' = v - [ L(g, b, t) - L(g, t) ]

L(g, b, t) is the mean ExpRV of the season's BASELINE pitches (the ones that
build the surfaces) in that group and hand pair, L(g, t) the same over both
batter hands. Location, count and the surfaces themselves are untouched, and
the group anchors are rebuilt on v' by whatever caller computes them.

lp.HANDNEU_TAG does nothing. It exists so the target audit's --flag mechanism
can produce a fresh same-session CONTROL table under its own name.

Use through with_handneutral.py:
    python3 scripts/research/locplus/with_handneutral.py -- \\
        scripts/research/locplus/locplus_target_audit.py run \\
        --flag ctl1111=HANDNEU_TAG:1 --flag handNeu1111=HANDNEU:1
"""
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

import pipeline.locplus as lp  # noqa: E402

if not getattr(lp, '_HANDNEU_PATCHED', False):
    lp.HANDNEU = False
    lp.HANDNEU_TAG = False
    _orig_build = lp.build_surfaces
    _orig_score = lp.score_pitch

    def build_surfaces(baseline, lg_woba, woba_scale):
        S = _orig_build(baseline, lg_woba, woba_scale)
        if lp.HANDNEU:
            s_gbt = defaultdict(lambda: [0.0, 0])
            s_gt = defaultdict(lambda: [0.0, 0])
            for p in baseline:
                v = _orig_score(p, S)
                if v is None:
                    continue
                g, b, t = lp.group_of(p), p.get('Bats'), p.get('Throws')
                a = s_gbt[(g, b, t)]; a[0] += v; a[1] += 1
                a = s_gt[(g, t)]; a[0] += v; a[1] += 1
            off = {}
            for (g, b, t), (s, n) in s_gbt.items():
                sg, ng = s_gt[(g, t)]
                off[(g, b, t)] = s / n - sg / ng
            S['_HANDOFF'] = off
        return S

    def score_pitch(p, S):
        v = _orig_score(p, S)
        off = S.get('_HANDOFF')
        if v is None or off is None:
            return v
        # a (group, hand) pair absent from the baseline has no surface either,
        # so _orig_score already returned None for it; KeyError here is a bug
        return v - off[(lp.group_of(p), p.get('Bats'), p.get('Throws'))]

    lp.build_surfaces = build_surfaces
    lp.score_pitch = score_pitch
    lp._HANDNEU_PATCHED = True
