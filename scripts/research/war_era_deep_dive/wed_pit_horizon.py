"""wed_pit_horizon.py - test 3b: the hpWAR pitcher level and AGING constants at 1, 3 and 5 seasons out, in the
shipped (integrated-aging) form, with and without the target-season gate.

Shipped: d .65, n0 500, peak 26, yi .09, od .04, one setting for every horizon, chosen by
pit_horizon_backtest.py on pitchers with 30+ IP in the target season. Here the same model runs with the gate at
1 out (IP weighted), and with the starter share taken from the BASE season (the target share is a leak).
.venv/bin/python scripts/research/war_era_deep_dive/wed_pit_horizon.py"""
import sys, os, itertools, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'projection'))
import pit_horizon_backtest as PH
pr = PH.pr
GRID = {'d': [0.5, 0.65, 0.8], 'n0': [300, 500], 'peak': [24, 26, 28, 30], 'yi': [0.0, 0.03, 0.06, 0.09, 0.12], 'od': [0.0, 0.02, 0.04, 0.06, 0.10]}
SHIP = (0.65, 500, 26, 0.09, 0.04)


def main():
    S = {y: pr.season(y) for y in range(2015, 2027)}
    keys = list(GRID); combos = list(itertools.product(*[GRID[k] for k in keys])); si = combos.index(SHIP); res = {}
    for gate, base_gs in ((90, False), (1, True)):
        pr.MIN_OUTS_T = gate
        for h, bases in PH.HORIZONS.items():
            bases = list(bases); R = {}
            for B in bases:
                rows = PH.rows_for(S, B, h)
                if base_gs:
                    rows = [(pid, dict(t, gs=next((x['gs'] for x in hist if x), 0.0)), hist) for pid, t, hist in rows]
                R[B] = rows
            L = np.zeros((len(combos), len(bases)))
            for i, c in enumerate(combos):
                F = {B: PH.feats(R[B], h, *c) for B in bases}
                for j, B in enumerate(bases):
                    tr = [F[b] for b in bases if b != B]
                    p, _ = pr.fit_predict(np.vstack([f[0] for f in tr]), np.concatenate([f[1] for f in tr]), np.concatenate([f[2] for f in tr]), F[B][0])
                    L[i, j] = pr.wmse(p, F[B][1], F[B][2])
            best = int(np.argmin(L.mean(axis=1))); ch = [int(np.argmin(L[:, [k for k in range(len(bases)) if k != j]].mean(axis=1))) for j in range(len(bases))]
            held = np.array([L[ch[j], j] for j in range(len(bases))]); d = (L[si] - held) / held
            print(f"\n gate {gate} outs{' + base-season starter share' if base_gs else ''}, h = {h}: n {[len(R[B]) for B in bases]}")
            print(f"   pooled argmin {dict(zip(keys, combos[best]))} MSE {L[best].mean():.4f} | shipped {L[si].mean():.4f} (+{100*(L[si].mean()/L[best].mean()-1):.2f}%)")
            print(f"   shipped minus held-out refit: {100*d.mean():+.2f}% (SE {100*d.std(ddof=1)/np.sqrt(len(d)):.2f}), shipped better in {int((d < 0).sum())}/{len(d)}")
            for ki, k in enumerate(keys):
                pts = []
                for v in GRID[k]:
                    c = list(combos[best]); c[ki] = v; pts.append(f"{v}:{L[combos.index(tuple(c))].mean():.4f}")
                print(f"     {k:>4}: " + "  ".join(pts))
            res[f'{gate} {h}'] = dict(best=dict(zip(keys, combos[best])), best_mse=float(L[best].mean()), ship=float(L[si].mean()), d=float(d.mean()))
            json.dump(res, open(os.path.join(ROOT, 'data', '_wed', 'res_pit_horizon.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
