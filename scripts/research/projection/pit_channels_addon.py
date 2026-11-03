"""pit_channels_addon.py: what else adds to the pitcher projection? Screen of channels on honest pools.

Base = the shipped design: pit_rate_backtest features (ra9, fip, kbb, xw history), start share, experience term k 20, Stuff+
history (N0_S 250), age offset; OLS on every pitcher with >= 1 out in T, LOSO over T 2022-2026, IP_T weight. Targets RA9
(primary) and FIP (defense-free). Candidates enter the same joint OLS, one at a time, so both arms get the same fitting freedom.
Each candidate is centered per season (count-weighted), history weighted d^k by its own count, shrunk at N0 (swept).
    battery rates: csw, swstr, zone, chase, fps, gb, hh, brl, ev, ff_velo, velo
    Command+ raw (mean miss), Loc raw, xRV/100
    dvelo: last season's ff_velo minus the season before (0 if either is missing), no shrink.
Reads: mean MSE gain %, SE over seasons, wins /5, best N0. A win must hold for RA9 AND not lose on FIP to count.

Usage: python3 scripts/research/projection/pit_channels_addon.py
Output: console + data/_proj/_pit_channels_addon.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fa_class_calibration as fc
import pit_rate_backtest as pr
import pit_stuff_addon as pst
import pit_experience_test as px

ROOT = pr.ROOT
T_ = fc.PIT_T
N0S = [0, 250, 1000, 4000]
BAT = {'csw_pct': 'pitches', 'swstr_pct': 'pitches', 'zone_pct': 'pitches', 'chase_pct': 'pitches', 'fps_pct': 'pa',
       'gb_pct': 'bip', 'hh_pct': 'bip', 'brl_pct': 'bip', 'ev': 'bip', 'ff_velo': 'pitches', 'velo': 'pitches'}


def main():
    D = fc.pit_build()
    stuff = json.load(open(os.path.join(ROOT, 'data', '_era_internal_stuff.json')))
    Bat = json.load(open(os.path.join(ROOT, 'data', '_era_battery.json')))
    CL = json.load(open(os.path.join(ROOT, 'data', '_era_internal_cmdloc.json')))
    XR = json.load(open(os.path.join(ROOT, 'data', '_era_xrv100.json')))
    # season tables: {channel: {y: {pid: (value, count)}}}
    tab = {c: {} for c in list(BAT) + ['cmd', 'loc', 'xrv']}
    for y in range(2021, 2027):
        ys = str(y)
        for c, n in BAT.items():
            tab[c][y] = {p: (r['full'][c], r['full'][n]) for p, r in Bat[ys].items() if r.get('full') and r['full'].get(c) is not None and r['full'].get(n)}
        tab['cmd'][y] = {p: (r['cmd_full'], r['cmd_n_full']) for p, r in CL[ys].items() if r.get('cmd_n_full')}
        tab['loc'][y] = {p: (r['loc_full'], r['loc_n_full']) for p, r in CL[ys].items() if r.get('loc_n_full')}
        tab['xrv'][y] = {p: (r['full'], r['n_full']) for p, r in XR[ys].items() if r.get('n_full')}
    tab = {c: {y: t for y, t in v.items() if t} for c, v in tab.items()}   # Loc raw has no 2026 row in the cmdloc file
    lg = {c: {y: sum(v * n for v, n in t.values()) / sum(n for _, n in t.values()) for y, t in tab[c].items()} for c in tab}
    sd = {c: float(np.mean([np.std([v for v, n in tab[c][y].values() if n >= 300]) for y in tab[c]])) for c in tab}

    for T in T_:
        z = D[T]
        ch, _ = pst.stuff_channel(z['rows'], T, stuff, px.PAR[0], 250)
        z['F'] = np.column_stack([z['X'][:, :-1], (1 / (1 + z['E'] / 20))[:, None], ch])
        z['age'] = z['X'][:, -1]
        Xf = np.array([pr_fip(r) for r in z['rows']])
        z['yf'] = Xf

    def hist(T, c, n0, d):
        out = []
        for pid, _, _ in D[T]['rows']:
            num = den = 0.0
            for k in range(3):
                y = T - 1 - k
                if y not in tab[c]:
                    continue
                r = tab[c][y].get(str(pid))
                if r:
                    num += d ** k * r[1] * (r[0] - lg[c][y]) / sd[c]
                    den += d ** k * r[1]
            out.append(num / (den + n0) if den + n0 > 0 else 0.0)
        return np.array(out)

    def dvelo(T):
        out = []
        for pid, _, _ in D[T]['rows']:
            a = tab['ff_velo'].get(T - 1, {}).get(str(pid)); b = tab['ff_velo'].get(T - 2, {}).get(str(pid))
            out.append((a[0] - b[0]) if a and b else 0.0)
        return np.array(out)

    def loso(extra, key):
        L = []
        for T in T_:
            tr = [S for S in T_ if S != T]
            build = lambda S: np.column_stack([D[S]['F']] + ([extra[S]] if extra else []) + [D[S]['age']])
            p, _ = pr.fit_predict(np.vstack([build(S) for S in tr]), np.concatenate([D[S][key] for S in tr]),
                                  np.concatenate([D[S]['w'] for S in tr]), build(T))
            L.append(pr.wmse(p, D[T][key], D[T]['w']))
        return np.array(L)

    res = {}
    for key, lab in (('y', 'RA9'), ('yf', 'FIP')):
        base = loso(None, key)
        print(f'\n== target {lab}: base MSE ' + ' '.join(f'{b:.4f}' for b in base))
        res[lab] = {'base': base.tolist()}
        for c in tab:
            best = None
            for n0 in N0S:
                L = loso({T: hist(T, c, n0, px.PAR[0]) for T in T_}, key)
                g = 100 * (1 - L / base)
                if best is None or g.mean() > best[1].mean():
                    best = (n0, g)
                res[lab][f'{c}_{n0}'] = g.tolist()
            n0, g = best
            print(f'  {c:10s} best N0 {n0:>5}: gain {g.mean():+.2f}% se {g.std(ddof=1)/np.sqrt(5):.2f} wins {int((g>0).sum())}/5 {np.round(g,2).tolist()}')
        L = loso({T: dvelo(T) for T in T_}, key); g = 100 * (1 - L / base)
        print(f'  {"dvelo":10s}             gain {g.mean():+.2f}% se {g.std(ddof=1)/np.sqrt(5):.2f} wins {int((g>0).sum())}/5 {np.round(g,2).tolist()}')
        res[lab]['dvelo'] = g.tolist()
    with open(os.path.join(pr.P, '_pit_channels_addon.json'), 'w') as f:
        json.dump(res, f, indent=1)


def pr_fip(row):
    return row[1]['fip']


if __name__ == '__main__':
    main()
