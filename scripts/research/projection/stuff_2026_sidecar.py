"""stuff_2026_sidecar.py: season-held-out Stuff+ for 2026, written beside data/_era_internal_stuff.json, not into it.

The 2027 pitcher projection reads Stuff+ history for 2026, 2025, 2024, but data/_era_internal_stuff.json ends at 2025, so its
Stuff+ channel has no 2026. era_stuff_loso_v2 protocol: SHIPPED gate features fit on 2021-2025 (five seasons, the others used
four), scoring 2026, pitcher score = mean per-pitch stuff, MIN_N 50. Separate file because era_weights_final reads the main file
and falls back to the battery's production Stuff+ for 2026, so adding 2026 there would change the ERA harness's ROS 2026 replicate.

Usage: python3 scripts/research/projection/stuff_2026_sidecar.py
Output: data/_proj/stuff_2026_loso.json {pid: {stuff_full, n_full, stuff_h1, n_h1}}
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
import era_stuff_loso_v2 as E

G = E.G
OUT = os.path.join(ROOT, 'data', '_proj', 'stuff_2026_loso.json')


def main():
    Y = 2026
    train = [2021, 2022, 2023, 2024, 2025]
    frames = {y: G.load_frame(y) for y in train + [Y]}
    G.set_arm_side_sign(list(frames.values()))
    feats = G.variant_feats({})
    slopes = G.fit_vaa_slopes([frames[y] for y in train])
    P = {y: G.prepare(frames[y], slopes, 'true') for y in train + [Y]}
    Xtr = pd.concat([G.design(P[y], {}, feats) for y in train], ignore_index=True)
    ytr = np.concatenate([P[y]['target_xrv'].values for y in train])
    keep = np.isfinite(ytr)
    dY = P[Y]
    pred = G.fit_predict(Xtr[keep], ytr[keep], G.design(dY, {}, feats), {}, 0)
    dY = dY.assign(stuff=-pred.astype('float32'))
    asg = E.TARGETS[str(Y)]['asg']; nm = E.name_map(Y)
    # Multi-word surnames and pitchers absent from _era_targets: every surname split over the season lines. An ambiguous key is
    # dropped, never guessed; the printed list below is what stays unmatched.
    extra, amb = {}, set()
    for r in json.load(open(os.path.join(ROOT, 'data', '_proj', f'lines_pitching_{Y}.json'))):
        w = (r.get('name') or '').split()
        for i in range(1, len(w)):
            k = (' '.join(w[i:]) + ', ' + ' '.join(w[:i])).lower()
            if k in extra and extra[k] != r['id']:
                amb.add(k)
            extra[k] = r['id']
    for k in amb:
        del extra[k]
    nm = {**extra, **nm}
    rec, unmatched = {}, []
    dates = dY['date'].astype(str).str[:10]
    for name, g in dY.groupby('pitcher'):
        pid = nm.get(str(name).lower())
        if pid is None:
            unmatched.append((str(name), len(g))); continue
        gh = g[dates.loc[g.index] <= asg]
        r = {}
        if len(g) >= E.MIN_N:
            r['stuff_full'] = float(g['stuff'].mean()); r['n_full'] = int(len(g))
        if len(gh) >= E.MIN_N:
            r['stuff_h1'] = float(gh['stuff'].mean()); r['n_h1'] = int(len(gh))
        if r:
            rec[str(pid)] = r
    print(f'{len(rec)} pitchers; {len(unmatched)} unmatched names, largest: {sorted(unmatched, key=lambda x: -x[1])[:8]}')
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(rec, f)
    os.replace(tmp, OUT)


if __name__ == '__main__':
    main()
