"""wx_hand_matched.py -- is the left / right gap in the altitude response of RIDE a shape effect?

RESEARCH ONLY. Unit = one (pitcher, pitch type, season) group with 25+ pitches in a high
park and 25+ elsewhere. Response = exponent that closes that group's ride gap,
ln(ride high / ride low) / ln(rho high / rho low), for groups with mean ride of 5 in or more.
Weighted regression of the response on a right-hander flag:
    raw       no control
    matched   fixed effect for spin-axis 15-degree sector x speed band x spin-efficiency third
    +linear   matched, plus mean ride, mean run, velocity, spin rate and release height
If the right-hander coefficient goes to zero under matching, shape was the cause.
MLB: Coors, 2021-2026. Triple-A: parks at 3,000 ft or more against parks under 1,500 ft, 2023-2026.
"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, COORS
from wx_aaa_validate import load_aaa


def units(d, hi, lo, relz=None):
    ok = np.isfinite(d['axis']) & np.isfinite(d['velo']) & np.isfinite(d['spin']) & (hi | lo)
    d = {k: v[ok] for k, v in d.items()}; hi = hi[ok]; lo = lo[ok]
    g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]; ng = g.max() + 1
    B = lambda w: np.bincount(g, weights=w, minlength=ng)
    nH, nL = B(hi), B(lo)
    lr = np.log(d['rho_w50'] / RHO0)
    with np.errstate(all='ignore'):
        rH = B(d['ivb'] * hi) / nH; rL = B(d['ivb'] * lo) / nL
        dl = B(lr * hi) / nH - B(lr * lo) / nL
        n = B(np.ones(len(g)))
        phi = np.radians(d['axis'])
        ux = np.where(d['rhp'], -np.sin(phi), np.sin(phi)); uz = -np.cos(phi)
        ang = (np.degrees(np.arctan2(B(uz * lo) / nL, B(ux * lo) / nL)) + 360) % 360
        velo = B(d['velo'] * lo) / nL; spin = B(d['spin'] * lo) / nL
        run = B(d['hb_arm'] * lo) / nL
        eff = np.hypot(rL, run) / (spin / 1000.0) / (velo / 90.0)      # break per 1000 rpm, speed-normalised (low parks only)
        y = np.log(rH / rL) / dl
    first = np.zeros(ng, int); first[g] = np.arange(len(g))
    keep = (nH >= 25) & (nL >= 25) & (np.abs(rL) >= 5) & (rH * rL > 0) & np.isfinite(y)
    w = 1 / (1 / nH + 1 / nL)
    return dict(y=y[keep], w=w[keep] * dl[keep] ** 2, rhp=d['rhp'][first][keep].astype(float), ang=ang[keep],
                velo=velo[keep], spin=spin[keep], ride=rL[keep], run=run[keep], eff=eff[keep],
                pt=d['pt'][first][keep], pid=d['pid'][first][keep])


def wreg(y, X, w, cl):
    """Weighted least squares, SE clustered by pitcher."""
    Xw = X * w[:, None]
    A = X.T @ Xw; b = np.linalg.solve(A + 1e-9 * np.eye(X.shape[1]), Xw.T @ y)
    r = y - X @ b
    u, ci = np.unique(cl, return_inverse=True)
    S = np.zeros((len(u), X.shape[1])); np.add.at(S, ci, Xw * r[:, None])
    inv = np.linalg.inv(A + 1e-9 * np.eye(X.shape[1]))
    return b, np.sqrt(np.diag(inv @ S.T @ S @ inv))


def demean(v, key, w):
    u, ci = np.unique(key, return_inverse=True)
    m = np.bincount(ci, weights=v * w) / np.bincount(ci, weights=w)
    return v - m[ci]


def report(U, name):
    U = {k: np.concatenate([u[k] for u in U]) for k in U[0]}
    n = len(U['y'])
    print(f'\n{name}: {n} pitcher x pitch groups ({int(U["rhp"].sum())} right, {int(n - U["rhp"].sum())} left)')
    band = np.digitize(U['velo'], [84.0, 90.0])
    et = np.zeros(n, int)
    for b_ in range(3):
        m = band == b_
        if m.sum() >= 6:
            et[m] = np.digitize(U['eff'][m], np.quantile(U['eff'][m], [1 / 3, 2 / 3]))
    cell = (U['ang'] // 15).astype(int) * 9 + band * 3 + et
    out = {}
    for lab, sel in (('all pitch types', np.ones(n, bool)), ('four-seam only', U['pt'] == 0)):
        y, w, r, pid = U['y'][sel], U['w'][sel], U['rhp'][sel], U['pid'][sel]
        b0, s0 = wreg(y, np.column_stack([np.ones(sel.sum()), r]), w, pid)
        c = cell[sel]
        # matched: keep cells that hold both hands
        both = np.array([len(np.unique(r[c == k])) == 2 for k in c])
        yb, wb, rb, cb, pb = y[both], w[both], r[both], c[both], pid[both]
        b1, s1 = wreg(demean(yb, cb, wb), demean(rb, cb, wb)[:, None], wb, pb)
        Z = np.column_stack([demean(rb, cb, wb)] + [demean(U[k][sel][both], cb, wb) for k in ('ride', 'run', 'velo', 'spin')])
        b2, s2 = wreg(demean(yb, cb, wb), Z, wb, pb)
        out[lab] = dict(raw=[float(b0[1]), float(s0[1])], matched=[float(b1[0]), float(s1[0])], linear=[float(b2[0]), float(s2[0])],
                        n=int(sel.sum()), n_matched=int(both.sum()))
        print(f'  {lab:16s} right minus left in the exponent:  raw {b0[1]:+.3f} (se {s0[1]:.3f})   matched {b1[0]:+.3f} (se {s1[0]:.3f}, '
              f'{both.sum()} of {sel.sum()} groups in cells with both hands)   +linear {b2[0]:+.3f} (se {s2[0]:.3f})')
    return out


if __name__ == '__main__':
    R = {}
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    U = []
    for yr in YEARS:
        d = load(yr, obs); U.append(units(d, d['venue'] == COORS, d['venue'] != COORS)); del d
    R['mlb_coors'] = report(U, 'MLB, Coors against all other parks, 2021-2026')
    obsA = json.load(open(os.path.join(OUT, 'game_obs_aaa.json')))
    U = []
    for yr in (2023, 2024, 2025, 2026):
        d = load_aaa(yr, obsA); U.append(units(d, d['elev'] >= 3000, d['elev'] < 1500)); del d
    R['aaa'] = report(U, 'Triple-A, parks at 3,000 ft or more against parks under 1,500 ft, 2023-2026')
    json.dump(R, open(os.path.join(OUT, 'hand_matched.json'), 'w'), indent=1)
