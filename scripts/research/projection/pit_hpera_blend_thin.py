"""pit_hpera_blend_thin.py: does the hpERA blend hold for arms with a thin base season?

pit_hpera_h2h.py found that a nested one-input blend, the hpWAR run model plus a LOSO-refit hpERA
score, beats the run model alone by 1.4 percent (z -2.2, 5/5) on pitchers with >= 30 IP in both B
and T. Production projects every pitcher, and hpERA scores every pitcher (shrunk channels, z against
the 30+ IP pool, the SIERA convention). This tests the arms the first test could not see.

Channels for EVERY pitcher in B: era_weights_final's shrinkage, league means and z moments taken
from the 30+ IP pool of B exactly as production does, applied to all arms with >= 1 out.

Pool: every pitcher with >= 1 out in T (the projection's fit pool), IP_T weighted, T 2022-2026, all
eight hpERA channels present. Groups by base-season IP: thin (< 30) and full (>= 30).
Arms, every weight fit leaving the target season out (score weights nested inside the blend fit):
  proj      the production run model alone
  blendA    score and blend weights fit on the full group only (the tested blend), applied to everyone
  blendB    score and blend weights fit on every pitcher

Usage: python3 scripts/research/projection/pit_hpera_blend_thin.py
Output: console + data/_proj/_pit_hpera_blend_thin.json
"""
import contextlib
import io
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pit_hpera_h2h as h  # noqa: E402

ewf = h.ewf
FULL_OUTS = 90


def shrunk_all(season):
    """era_weights_final.shrunk_features, but channels for EVERY arm (league and z from the pool)."""
    raw = ewf.raw_features(season, 'full')
    pool = {p: r for p, r in raw.items() if r['outs'] >= FULL_OUTS}
    N0 = ewf.N0

    def lg_mean(v, n):
        s = sum(r[v] * r[n] for r in pool.values() if v in r); d = sum(r[n] for r in pool.values() if v in r)
        return s / d if d else 0.0
    lg_k = sum(r['k_n'] for r in pool.values()) / sum(r['bf'] for r in pool.values())
    lg_st, lg_lo, lg_xrv, lg_gb = lg_mean('stuff', 'stuff_n'), lg_mean('loc', 'loc_n'), lg_mean('xrv100', 'xrv_n'), lg_mean('gb_pct', 'bip_n')
    _izw = [(r['izwhiff'], r.get('pitches') or 0) for r in pool.values() if 'izwhiff' in r]
    lg_iz = sum(v * w for v, w in _izw) / sum(w for _, w in _izw)

    def feats(r):
        f = {'k': -(r['k_n'] + N0['k'] * lg_k) / (r['bf'] + N0['k'])}
        if 'stuff' in r:
            f['stuff'] = -(r['stuff'] * r['stuff_n'] + N0['stuff'] * lg_st) / (r['stuff_n'] + N0['stuff'])
        if 'loc' in r:
            f['loc'] = -(r['loc'] * r['loc_n'] + N0['loc'] * lg_lo) / (r['loc_n'] + N0['loc'])
        if 'xrv100' in r:
            f['xrv'] = (r['xrv100'] * r['xrv_n'] + N0['xrv'] * lg_xrv) / (r['xrv_n'] + N0['xrv'])
        if 'gb_pct' in r:
            nb = r.get('bip_n') or 0
            f['gb'] = -((r['gb_pct'] * nb + N0['gb'] * lg_gb) / (nb + N0['gb']))
        if 'izwhiff' in r:
            niz = (r.get('pitches') or 0) * ewf.IZSW_PER_PITCH
            f['izwh'] = -((r['izwhiff'] * niz + N0['izwh'] * lg_iz) / (niz + N0['izwh']))
        f['gs_share'] = r['gs_share']; f['park'] = r['park']
        return f
    F = {p: feats(r) for p, r in raw.items()}
    mu_sd = {}
    for c in h.CH:
        v = [F[p][c] for p in pool if c in F[p]]
        m = sum(v) / len(v); s = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
        mu_sd[c] = (m, s)
    return {p: ({c: (f[c] - mu_sd[c][0]) / mu_sd[c][1] for c in h.CH if c in f}, raw[p]['outs']) for p, f in F.items()}


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        recs = h.pcc.heldout_records(min_ip_t=0)
    proj = {(r['T'], r['pid']): r for r in recs}
    data, miss = {}, {}
    for B in h.BASES:
        with contextlib.redirect_stdout(io.StringIO()):
            Z = shrunk_all(B)
        rows = []
        n_t = sum(1 for (T, _) in proj if T == B + 1)
        for pid, (z, outs) in Z.items():
            r = proj.get((B + 1, int(pid)))
            if r is None:
                continue
            if not all(c in z for c in h.CH):
                miss[B + 1] = miss.get(B + 1, 0) + 1
                continue
            rows.append({'z': [z[c] for c in h.CH], 'proj': r['pred'], 'act': r['act'], 'ip': r['ip'],
                         'thin': outs < FULL_OUTS, 'fullT': r['ip'] >= h.MIN_IP})
        data[B + 1] = rows
        print(f"T {B + 1}: {len(rows)} scored ({sum(x['thin'] for x in rows)} thin in B) of {n_t} in the "
              f"projection pool; {miss.get(B + 1, 0)} lack an hpERA channel")
    Ts = sorted(data)

    def arr(T, sel, key):
        return np.array([x[key] for x in data[T] if sel(x)])

    def Zm(T, sel):
        return np.array([x['z'] for x in data[T] if sel(x)])

    def fit_blend(train, sel):
        """nested: out-of-fold score for each training season, then the blend weights"""
        def sw(S):
            return h.ols_fit(np.vstack([Zm(t, sel) for t in S]), np.concatenate([arr(t, sel, 'act') for t in S]),
                             np.concatenate([arr(t, sel, 'ip') for t in S]))
        X = [np.column_stack([arr(t, sel, 'proj'), h.ols_pred(sw([u for u in train if u != t]), Zm(t, sel))]) for t in train]
        bl = h.ols_fit(np.vstack(X), np.concatenate([arr(t, sel, 'act') for t in train]),
                       np.concatenate([arr(t, sel, 'ip') for t in train]))
        return sw(train), bl

    fitsel = {'blendA': lambda x: (not x['thin']) and x['fullT'], 'blendB': lambda x: True}
    groups = {'thin B (<30 IP), all T': lambda x: x['thin'],
              'thin B, 30+ IP in T': lambda x: x['thin'] and x['fullT'],
              'full B (30+), all T': lambda x: not x['thin'],
              'everyone': lambda x: True}
    preds = {T: {} for T in Ts}
    for T in Ts:
        tr = [t for t in Ts if t != T]
        preds[T]['proj'] = arr(T, lambda x: True, 'proj')
        for arm, sel in fitsel.items():
            sw, bl = fit_blend(tr, sel)
            s = h.ols_pred(sw, Zm(T, lambda x: True))
            preds[T][arm] = h.ols_pred(bl, np.column_stack([preds[T]['proj'], s]))
            if arm == 'blendB':
                print(f'  fold {T}: blendB weights proj {bl[1]:.2f}, score {bl[2]:.2f}')
    rng = np.random.default_rng(0)
    out = {}
    print('\nIP-weighted MSE of next-season RA9 delta, held out by target season; change vs proj')
    for gname, gsel in groups.items():
        print(f'  {gname}')
        for arm in ('blendA', 'blendB'):
            per, tot_a, tot_p = [], 0.0, 0.0
            idx = {T: np.array([gsel(x) for x in data[T]]) for T in Ts}
            for T in Ts:
                m = idx[T]; y = arr(T, lambda x: True, 'act')[m]; w = arr(T, lambda x: True, 'ip')[m]
                a = h.wmse(preds[T][arm][m], y, w); p = h.wmse(preds[T]['proj'][m], y, w)
                per.append(a < p); tot_a += a; tot_p += p
            g = []
            for _ in range(1000):
                sa = sp = 0.0
                for T in Ts:
                    m = np.where(idx[T])[0]; i = rng.choice(m, len(m))
                    y = arr(T, lambda x: True, 'act')[i]; w = arr(T, lambda x: True, 'ip')[i]
                    sa += h.wmse(preds[T][arm][i], y, w); sp += h.wmse(preds[T]['proj'][i], y, w)
                g.append(100 * (sa / sp - 1))
            ch = 100 * (tot_a / tot_p - 1); se = float(np.std(g))
            n = int(sum(idx[T].sum() for T in Ts))
            print(f'    {arm}  n {n:5d}  {ch:+.2f}%  SE {se:.2f}  z {ch / se:+.2f}  wins {sum(per)}/{len(Ts)}')
            out[f'{gname}|{arm}'] = {'change_pct': ch, 'se': se, 'wins': int(sum(per)), 'n': n}
    with open(os.path.join(h.pcc.P, '_pit_hpera_blend_thin.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
