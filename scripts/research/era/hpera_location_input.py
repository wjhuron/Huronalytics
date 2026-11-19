#!/usr/bin/env python3
"""hpera_location_input.py — the hpERA loc input on the RELEASE Loc+ code.

hpera_new_inputs_build.py built `loc_part` on the shipped kernel (6 in / 0.30).
The Loc+ release (branch locplus-location) grades `location_value`: kernel
2 in / 0.12, ball in play in count currency, minus the league mean for (group,
batter hand, pitcher hand, count). Production hpERA reads locPlusRaw, which on
that branch is the pitcher's mean location value. This script computes that same
quantity with the BRANCH module itself, per season on the season's own surfaces,
and adds it to data/_era_new_inputs.json:

    loc_new_{full,h1}   hitter-positive mean per pitch (the harness convention)
    n_locnew_{full,h1}  pitches

  PYTHONHASHSEED=0 .venv/bin/python scripts/research/era/hpera_location_input.py \
      /Users/wallyhuron/Huronalytics-locplus

A second argument names the output key (default loc_new). Any other key, for
example loc_shape for the branch locplus-shape, also switches the season loader to
locplus_shape_loader, which carries the movement fields that grade reads.
"""
import gc
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'locplus'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'stuff'))
sys.path.insert(0, HERE)
import locplus_fullseason_replicate as FR  # noqa: E402
from era_stuff_loso_v2 import name_map, TARGETS  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_era_new_inputs.json')
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
MIN_N = 50


def main():
    path = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else 'loc_new'
    nkey = 'n_' + key.replace('_', '')
    load = FR.load_season
    if key != 'loc_new':
        import locplus_shape_loader as SL
        load = SL.load_season
    spec = importlib.util.spec_from_file_location('pipeline.locplus_branch', os.path.join(path, 'pipeline', 'locplus.py'))
    BR = importlib.util.module_from_spec(spec)
    sys.modules['pipeline.locplus_branch'] = BR
    spec.loader.exec_module(BR)
    if not hasattr(BR, 'location_value'):
        sys.exit(f'{path} has no location_value: not the Loc+ release branch. Nothing written.')
    print(f'branch kernel {BR.PHYS_X_IN:g} in / {BR.PHYS_Z_FRAC:g}, BIP count anchor {BR.BIP_COUNT_ANCHOR}', flush=True)
    res = json.load(open(OUT))
    for Y in YEARS:
        pitches = load(Y)
        base_p = [p for p in pitches if BR.is_eligible_baseline(p)]
        S = BR.build_surfaces(base_p, FR.LG, FR.SCALE)
        asg, nm = TARGETS[str(Y)]['asg'], name_map(Y)
        rows = []
        for p in pitches:
            if not BR._is_scorable(p):
                continue
            v = BR.location_value(p, S)
            if v is not None:
                rows.append((p.get('Pitcher'), str(p.get('Game Date'))[:10] <= asg, v))
        del pitches, base_p, S
        gc.collect()
        d = pd.DataFrame(rows, columns=['pitcher', 'h1', 'v'])
        for scope, sub in (('full', d), ('h1', d[d['h1']])):
            g = sub.groupby('pitcher')['v'].agg(['mean', 'size'])
            g = g[g['size'] >= MIN_N]
            miss = 0
            for name, r in g.iterrows():
                pid = nm.get(str(name).lower())
                if pid is None:
                    miss += 1
                    continue
                res.setdefault(str(Y), {}).setdefault(str(pid), {}).update(
                    {f'{key}_{scope}': float(r['mean']), f'{nkey}_{scope}': int(r['size'])})
        a, b = [], []
        for r in res[str(Y)].values():
            ref = 'loc_part_full' if key == 'loc_new' else 'loc_new_full'
            if f'{key}_full' in r and ref in r and r[f'{nkey}_full'] >= 300:
                a.append(r[f'{key}_full']); b.append(r[ref])
        print(f'{Y}: league mean location value {d["v"].mean() * 100:+.4f} runs/100 on {len(d)} pitches; '
              f'{len(g)} pitchers (h1), {miss} unmatched names; r with the reference location input (loc_part for loc_new, else loc_new) '
              f'{np.corrcoef(a, b)[0, 1]:.3f} (n {len(a)})', flush=True)
        del d
        gc.collect()
    tmp = OUT + '.tmp'
    json.dump(res, open(tmp, 'w'))
    os.replace(tmp, OUT)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
