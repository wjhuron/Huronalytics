"""wx_hand_coors.py -- is the left / right gap in the density response real?
RESEARCH ONLY. Coors against elsewhere, same pitcher and pitch type, pooled 2021-2026,
split by hand and by Rockies staff / visitors. e = exponent that closes the gap.
Also splits visitors' run by the Coors crosswind sign."""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, PT, COORS

if __name__ == '__main__':
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    rows = []
    for yr in YEARS:
        d = load(yr, obs)
        g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]; ng = g.max() + 1
        at = d['venue'] == COORS; lr = np.log(d['rho_w50'] / RHO0)
        B = lambda w: np.bincount(g, weights=w, minlength=ng)
        nC, nE = B(at), B(~at)
        ok = (nC >= 25) & (nE >= 25)
        first = np.zeros(ng, int); first[g] = np.arange(len(g))
        for comp in ('ivb', 'hb_arm'):
            rC = B(d[comp] * at) / np.maximum(nC, 1); rE = B(d[comp] * ~at) / np.maximum(nE, 1)
            dl = B(lr * at) / np.maximum(nC, 1) - B(lr * ~at) / np.maximum(nE, 1)
            for j in np.where(ok)[0]:
                rows.append((yr, comp == 'ivb', d['pt'][first[j]], d['rhp'][first[j]], nC[j] / (nC[j] + nE[j]) >= .35,
                             nC[j], nE[j], rC[j], rE[j], dl[j]))
        del d
    a = np.array(rows, dtype=float)
    print('Coors response by hand: exponent that closes the gap (groups), pooled 2021-2026, |mean elsewhere| >= 5 in')
    for i, p in enumerate(PT[:7]):
        for ride, lab in ((1, 'ride'), (0, 'run')):
            out = []
            for who, hm in (('visitors', 0), ('Rockies', 1)):
                for hand, r in (('R', 1), ('L', 0)):
                    m = (a[:, 1] == ride) & (a[:, 2] == i) & (a[:, 3] == r) & (a[:, 4] == hm) & (np.abs(a[:, 8]) >= 5) & (a[:, 7] * a[:, 8] > 0)
                    if m.sum() < 8:
                        out.append(f'{who} {hand}   n/a      '); continue
                    w = 1 / (1 / a[m, 5] + 1 / a[m, 6])
                    e = np.sum(w * np.log(a[m, 7] / a[m, 8])) / np.sum(w * a[m, 9])
                    # bootstrap se over groups
                    rng = np.random.default_rng(0); idx = np.where(m)[0]; bs = []
                    for _ in range(300):
                        s = rng.choice(idx, len(idx)); ww = 1 / (1 / a[s, 5] + 1 / a[s, 6])
                        bs.append(np.sum(ww * np.log(a[s, 7] / a[s, 8])) / np.sum(ww * a[s, 9]))
                    out.append(f'{who} {hand} {e:.2f} ({np.std(bs):.2f}, k{m.sum()})')
            print(f' {p} {lab:4s} ' + ' | '.join(out))
