"""pit_hpera_h2h.py: hpERA against the hpWAR run model, forecasting next season's runs.

Prompted by Sonny Gray (2026-10-07): hpERA 4.93 against an hpWAR run rate of 4.05 RA9 (about a 3.7
ERA). Both are projections of the same thing, each backtested on its own (hpERA against SIERA, the
hpWAR model against Marcel), and never against each other.

Pool: pitchers with >= 30 IP in base season B (the hpERA z pool) and >= 30 IP in T = B + 1, B
2021-2025. CAUTION (2026-10-07): the >= 30 IP gate on T selects on the outcome, and the blend's 5/5
gain here did NOT survive the honest pool (every arm with >= 1 out in T): see pit_hpera_blend_thin.py.
The hpERA_ship arm applies the shipped weights with the research harness's reversed xRV sign corrected. Truth: actual RA9 in T relative to that season's league (the hpWAR target), IP_T weighted.
Every arm is scored on target seasons it was not fit on (leave one target season out):

  proj        the production 1-year hpWAR run model (pit_class_calibration.heldout_records), which
              conditions on the target-season start share (it projects "if he starts / relieves")
  hpERA_ship  the SHIPPED hpERA formula (W_PH on the season-B z channels), linearly calibrated to the
              target leaving T out. Its weights were fit on 2021-2026, so this arm saw the test
              seasons: an upper bound for hpERA, not a fair score.
  hpERA_refit the hpERA channel set (Stuff+, Loc+, K%, in-zone whiff, xRV, GB%, start share, park),
              OLS-refit to the target leaving T out, plus the target-season start share, so it gets
              the same role information as proj. The fair hpERA arm.
  blend       proj + hpERA_refit channels in one LOSO OLS: does hpERA's information add to proj?

Not modeled: hpERA's hand term (W_LHP; pitcher hand is not in the research battery). It is a level
shift of .21 ERA by hand and the refit arm cannot learn it.

Usage: python3 scripts/research/projection/pit_hpera_h2h.py
Output: console + data/_proj/_pit_hpera_h2h.json
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pit_class_calibration as pcc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'era'))
import era_weights_final as ewf  # noqa: E402

BASES = [2021, 2022, 2023, 2024, 2025]
MIN_IP = 30
# shipped hpERA weights, pipeline/eraplus.py W_PH (z units, ERA direction); research key names
W_PH = {'stuff': 0.315, 'loc': 0.105, 'k': 0.053, 'izwh': 0.101, 'xrv': 0.16, 'gb': 0.151,
        'gs_share': 0.298, 'park': 0.152}
CH = list(W_PH)


def wmse(p, y, w):
    return float((w * (p - y) ** 2).sum() / w.sum())


def ols_fit(X, y, w):
    A = np.column_stack([np.ones(len(X)), X])
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)
    return beta


def ols_pred(beta, X):
    return np.column_stack([np.ones(len(X)), X]) @ beta


def main():
    recs = pcc.heldout_records(min_ip_t=MIN_IP)
    proj = {(r['T'], r['pid']): r for r in recs}
    data = {}
    for B in BASES:
        z = ewf.shrunk_features(B, 'full')        # the 30+ IP pool of B, z-scored, ERA direction
        rows = []
        for pid, f in z.items():
            r = proj.get((B + 1, int(pid)))
            if r is None or not all(c in f for c in CH):
                continue
            rows.append({'pid': int(pid), 'z': [f[c] for c in CH], 'ship': sum(W_PH[c] * (-f[c] if c == 'xrv' else f[c]) for c in CH),
                         'proj': r['pred'], 'act': r['act'], 'ip': r['ip'], 'gsT': r['gs']})
        data[B + 1] = rows
        print(f'T {B + 1}: {len(rows)} pitchers (30+ IP in both seasons, full hpERA coverage)')

    def arrays(T, kind):
        R = data[T]
        y = np.array([r['act'] for r in R]); w = np.array([r['ip'] for r in R])
        if kind == 'ship':
            X = np.array([[r['ship']] for r in R])
        elif kind == 'refit':
            X = np.array([r['z'] + [r['gsT']] for r in R])
        elif kind == 'blend':
            X = np.array([[r['proj']] + r['z'] + [r['gsT']] for r in R])
        else:
            X = None
        return X, y, w

    Ts = sorted(data)
    res = {k: {} for k in ('proj', 'hpERA_ship', 'hpERA_refit', 'blend')}
    blend_w = []
    for T in Ts:
        tr = [t for t in Ts if t != T]
        _, y, w = arrays(T, None)
        res['proj'][T] = wmse(np.array([r['proj'] for r in data[T]]), y, w)
        for kind, name in (('ship', 'hpERA_ship'), ('refit', 'hpERA_refit'), ('blend', 'blend')):
            Xs, ys, ws = zip(*[arrays(t, kind) for t in tr])
            beta = ols_fit(np.vstack(Xs), np.concatenate(ys), np.concatenate(ws))
            X, _, _ = arrays(T, kind)
            res[name][T] = wmse(ols_pred(beta, X), y, w)
            if kind == 'blend':
                blend_w.append(beta[1])
    print('\nIP-weighted MSE of next-season RA9 (runs/9 squared), held out by target season')
    base = res['proj']
    for k, v in res.items():
        m = np.mean(list(v.values()))
        wins = sum(v[T] < base[T] for T in Ts)
        print(f'  {k:12s} {m:.3f}  ' + ' '.join(f'{T % 100}:{v[T]:.3f}' for T in Ts) +
              ('' if k == 'proj' else f'   beats proj {wins}/{len(Ts)}  ({100 * (m / np.mean(list(base.values())) - 1):+.1f}%)'))
    print(f'  blend coefficient on proj (per fold): ' + ' '.join(f'{b:.2f}' for b in blend_w))

    # where they disagree: pitchers whose hpERA-refit forecast is far above proj (the Gray pattern)
    allrows = []
    for T in Ts:
        tr = [t for t in Ts if t != T]
        Xs, ys, ws = zip(*[arrays(t, 'refit') for t in tr])
        beta = ols_fit(np.vstack(Xs), np.concatenate(ys), np.concatenate(ws))
        X, _, _ = arrays(T, 'refit')
        for r, h in zip(data[T], ols_pred(beta, X)):
            allrows.append((h - r['proj'], r['proj'], h, r['act'], r['ip']))
    a = np.array(allrows)
    print('\nby disagreement, refit hpERA minus proj (runs/9); mean actual minus each forecast, IP weighted')
    for lo, hi in ((-9, -0.5), (-0.5, -0.2), (-0.2, 0.2), (0.2, 0.5), (0.5, 9)):
        m = (a[:, 0] >= lo) & (a[:, 0] < hi)
        if not m.any():
            continue
        w = a[m, 4]
        rp = (w * (a[m, 3] - a[m, 1])).sum() / w.sum(); rh = (w * (a[m, 3] - a[m, 2])).sum() / w.sum()
        print(f'  gap [{lo:+.1f}, {hi:+.1f})  n {m.sum():4d}   actual-proj {rp:+.2f}   actual-hpERA {rh:+.2f}')
    with open(os.path.join(pcc.P, '_pit_hpera_h2h.json'), 'w') as f:
        json.dump({k: {str(T): v for T, v in d.items()} for k, d in res.items()}, f, indent=1)


if __name__ == '__main__':
    main()
