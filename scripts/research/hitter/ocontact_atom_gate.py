"""ocontact_atom_gate.py — STEP 2 of the descriptive Hitter+ build
(2026-09-16): does plain OUT-of-zone contact rate (O-Contact%) earn a
fourth atom, on BOTH constructions and BOTH objectives?

Constructions (atoms from hitterplus_shrinkage_sweep.atoms_lambda):
    lam=1  shipped shrinkage (BB+ 130 / SD+ 190 / CT+ 66; O-Con n0 34)
    lam=0  unshrunk (the descriptive candidate)
    plus any --lam values given
Objectives: same-season wOBA (6 seasons, LOSO) and next-season wOBA
(5 pairs, LOPO). Pool: production computation floors, >=300 PA same
season / >=200 PA next season, 80 BIP on the predictive side (as every
weight derivation).

Per panel, against the 3-atom OLS base:
  partial r of the candidate given (bb, sd, ct)           [gate 0.15]
  held-out gain +ocon, paired bootstrap SE, wins
  the location-adjusted form +ct_oz for comparison (raw rate vs lift)
  PLACEBO: +ocon_r{s}, contact rate on a random subset of the hitter's
      swings sized like his out-of-zone set (3 seeds) — the candidate
      must clear the placebo band, not zero
  sample-size control: log(n_swings) on both sides
  overlap: corr(ocon, sd), corr(ocon, ct), corr(ocon, chase); the gain
      with chase% added to BOTH sides (the RAWRATE-CT lesson: a raw rate
      re-imports swing selection, which SD+ owns)
  calibration: residual of the base vs ocon; residual of +ocon vs chase
      and swing% (does the atom fix a blind spot or create one)
  normalised weights per fold

Usage: python3 scripts/research/hitter/ocontact_atom_gate.py [--lam 0,1]
Output: console + data/_ocontact_atom_gate.json
"""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import izcontact_battery as B
import hitterplus_shrinkage_sweep as S

SEASONS, PAIRS = B.SEASONS, B.PAIRS
OUT = os.path.join(ROOT, 'data', '_ocontact_atom_gate.json')
A3 = ('bb', 'sd', 'ct')
EXTRA = ('ocon', 'chase', 'swing_pct', 'log_nsw')


def loso(frames, cols):
    res = []
    for i, Zt in enumerate(frames):
        train = [Z for j, Z in enumerate(frames) if j != i]
        X = np.vstack([np.column_stack([Z[c] for c in cols]) for Z in train]); y = np.concatenate([Z['y'] for Z in train])
        w = B.ols_w(X, y); comp = B.composite_fixed(Zt, w, cols)
        res.append((B.pear(comp, Zt['y']), comp, w))
    return res


def gain(frames, cols, base):
    rr = loso(frames, cols); d, se, m, sem = B.boot_delta(frames, rr, base)
    return dict(r=[x[0] for x in rr], mean=float(np.mean([x[0] for x in rr])), delta=m, se=sem, wins=sum(1 for x in d if x > 0),
                w=[[round(float(v), 3) for v in x[2] / np.sum(np.abs(x[2]))] for x in rr]), rr


def resid_corr(frames, rr, trait):
    out = []
    for Zt, (r, comp, _) in zip(frames, rr):
        sl, ic = np.polyfit(comp, Zt['y'], 1); out.append(B.pear(Zt['y'] - (sl * comp + ic), Zt['raw_' + trait]))
    return out


def panel(frames, label):
    print(f"\n----- {label}: pools " + ' '.join(str(Z['n']) for Z in frames) + " -----")
    rec = {}
    base_rec, base = gain(frames, A3, loso(frames, A3))
    rec['base'] = dict(mean=base_rec['mean'], r=base_rec['r'])
    print(f"  base (bb,sd,ct) LOSO r mean {base_rec['mean']:.4f}  " + ' '.join(f"{v:.4f}" for v in base_rec['r']))
    pr = [B.partial_r(Z, 'ocon', given=A3) for Z in frames]; rec['partial_ocon'] = pr
    print(f"  partial ocon | bb,sd,ct: mean {np.mean(pr):+.4f}  " + ' '.join(f"{v:+.4f}" for v in pr))
    pr2 = [B.partial_r(Z, 'ocon', given=A3 + ('chase',)) for Z in frames]; rec['partial_ocon_given_chase'] = pr2
    print(f"  partial ocon | bb,sd,ct,chase: mean {np.mean(pr2):+.4f}  " + ' '.join(f"{v:+.4f}" for v in pr2))
    for name, cols in (('+ocon', A3 + ('ocon',)), ('+ct_oz', A3 + ('ct_oz',))):
        g, _ = gain(frames, cols, base); rec[name] = g
        print(f"  {name:8s} d {g['delta']:+.4f} (SE {g['se']:.4f}, wins {g['wins']}/{len(frames)})  w " + '  '.join('/'.join(f"{v:+.2f}" for v in w) for w in g['w'][:3]) + ' ...')
    pl = []
    for s in B.SEEDS:
        g, _ = gain(frames, A3 + (f'ocon_r{s}',), base); pl.append(g['delta'])
    rec['placebo'] = pl
    print(f"  PLACEBO random-subset contact (3 seeds): d " + ' '.join(f"{v:+.4f}" for v in pl) + f"  mean {np.mean(pl):+.4f}  | real +ocon {rec['+ocon']['delta']:+.4f}")
    base_n = loso(frames, A3 + ('log_nsw',)); g, _ = gain(frames, A3 + ('log_nsw', 'ocon'), base_n); rec['+ocon_ctrl_logn'] = g
    print(f"  +ocon with log(n_sw) on both sides: d {g['delta']:+.4f} (SE {g['se']:.4f}, wins {g['wins']}/{len(frames)})")
    base_c = loso(frames, A3 + ('chase',)); g, rr_c = gain(frames, A3 + ('chase', 'ocon'), base_c); rec['+ocon_ctrl_chase'] = g
    gc_, _ = gain(frames, A3 + ('chase',), base); rec['+chase_alone'] = gc_
    print(f"  +ocon with chase% on both sides: d {g['delta']:+.4f} (SE {g['se']:.4f}, wins {g['wins']}/{len(frames)});  +chase alone vs base d {gc_['delta']:+.4f} ({gc_['wins']}/{len(frames)})")
    ov = {t: float(np.mean([B.pear(Z['ocon'], Z[t]) for Z in frames])) for t in ('sd', 'ct', 'bb', 'chase', 'swing_pct')}
    rec['overlap'] = ov
    print("  overlap corr(ocon, .): " + '  '.join(f"{t} {v:+.3f}" for t, v in ov.items()))
    _, rr_o = gain(frames, A3 + ('ocon',), base)
    cal = {'base_vs_ocon': resid_corr(frames, base, 'ocon'), 'base_vs_chase': resid_corr(frames, base, 'chase'), 'base_vs_swing': resid_corr(frames, base, 'swing_pct'),
           'ocon_vs_chase': resid_corr(frames, rr_o, 'chase'), 'ocon_vs_swing': resid_corr(frames, rr_o, 'swing_pct')}
    rec['calibration'] = cal
    print("  calibration (residual r): base vs ocon {:+.3f}; base vs chase {:+.3f} -> +ocon {:+.3f}; base vs swing% {:+.3f} -> +ocon {:+.3f}".format(
        np.mean(cal['base_vs_ocon']), np.mean(cal['base_vs_chase']), np.mean(cal['ocon_vs_chase']), np.mean(cal['base_vs_swing']), np.mean(cal['ocon_vs_swing'])))
    return rec


def main():
    lams = [0.0, 1.0]
    if '--lam' in sys.argv:
        lams = [float(x) for x in sys.argv[sys.argv.index('--lam') + 1].split(',')]
    F = B.load_frames()
    out = {}
    keys = A3 + ('ocon', 'ct_oz', 'chase', 'swing_pct', 'log_nsw') + tuple(f'ocon_r{s}' for s in B.SEEDS)
    for lam in lams:
        AT = {Y: S.atoms_lambda(F[Y], lam) for Y in SEASONS}
        same = [S.pool_same(AT[Y], 300, keys, EXTRA) for Y in SEASONS]
        nxt = [S.pool_next(AT[Y], F[Y1], keys, EXTRA) for Y, Y1 in PAIRS]
        tag = 'unshrunk' if lam == 0 else ('shipped' if lam == 1 else f'lam{lam}')
        out[f'{tag}_descriptive'] = panel(same, f"lam={lam} ({tag}), DESCRIPTIVE same-season wOBA")
        out[f'{tag}_predictive'] = panel(nxt, f"lam={lam} ({tag}), PREDICTIVE next-season wOBA")
    print("\n===== summary: +ocon gain (SE, wins) and placebo mean =====")
    for k, v in out.items():
        print(f"  {k:24s} d {v['+ocon']['delta']:+.4f} (SE {v['+ocon']['se']:.4f}, {v['+ocon']['wins']}/{len(v['+ocon']['r'])})  placebo {np.mean(v['placebo']):+.4f}  partial {np.mean(v['partial_ocon']):+.3f}  |chase ctrl d {v['+ocon_ctrl_chase']['delta']:+.4f}")
    json.dump(out, open(OUT, 'w'), indent=1, default=float)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")


if __name__ == '__main__':
    main()
