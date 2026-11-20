"""wx_axis_form.py -- a tag-free form for the altitude response (stage 2).

RESEARCH ONLY. The per-pitch-type shift (wx_exponent_sweep.py, design `add`)
fits best but reads the pitch tag. This tests a form that reads no tag:
split each pitch's movement along its own measured SPIN direction and across it.

    along = movement in the direction the spin pushes the ball (Magnus)
    cross = movement the spin direction does not explain (seam effects, gyro)

    adjusted = (along / f**eA) * u + (cross / f**eC) * w,   f = (rho / rho0)

u comes from the measured spin axis (Statcast spin_axis; the sheet RTilt in
2026), so a retag cannot move the result.

Every design predicts the same target (raw ride and raw run) from one neutral
movement vector per (pitcher, pitch type) group, so the held-out errors compare
directly:  raw_i = B_i(design, rho_i) @ n_g.
Exponents come from five seasons and are scored on the sixth.

Usage: .venv/bin/python scripts/research/weather/wx_axis_form.py [model|obsPH]
"""
import os, sys, json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wx_exponent_sweep import load, OUT, RHO0, YEARS, PT, COORS, MIN_N

EA = [round(0.70 + 0.05 * i, 2) for i in range(23)]        # 0.70 .. 1.80
EC = [round(0.00 + 0.10 * i, 2) for i in range(51)]        # 0.00 .. 5.00
EALL = sorted(set(EA) | set(EC))


def prep(d, dens):
    ok = np.isfinite(d['axis'])
    d = {k: v[ok] for k, v in d.items()}
    g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    big = (np.bincount(g)[g] >= MIN_N)
    d = {k: v[big] for k, v in d.items()}
    g = np.unique(d['pid'].astype(np.int64) * 16 + d['pt'], return_inverse=True)[1]
    phi = np.radians(d['axis'])
    ux = np.where(d['rhp'], -np.sin(phi), np.sin(phi)); uz = -np.cos(phi)     # (run_arm, ride)
    x, z = d['hb_arm'], d['ivb']
    d.update(g=g, ux=ux, uz=uz, a=ux * x + uz * z, c=-uz * x + ux * z,
             lr=np.log(d[f'rho_{dens}'] / RHO0))
    return d


def season_tables(d):
    """Group-level sums for every exponent on the grid; the 2-D grid is then cheap."""
    g, ng = d['g'], d['g'].max() + 1
    B = lambda w: np.bincount(g, weights=w, minlength=ng)
    ux, uz, a, c, lr = d['ux'], d['uz'], d['a'], d['c'], d['lr']
    T = {}
    for e in EALL:
        f = np.exp(e * lr); f2 = f * f
        T[e] = dict(P=(B(f2 * ux * ux), B(f2 * ux * uz), B(f2 * uz * uz)),
                    q=(B(f * a * ux), B(f * a * uz)),
                    t=(B(f * c * -uz), B(f * c * ux)),
                    # componentwise sums for the ride / run designs
                    sx=(B(f * d['hb_arm']), B(f * d['ivb'])), sf=B(f2))
    T['tot'] = float(np.sum(d['hb_arm'] ** 2 + d['ivb'] ** 2))
    T['n'] = len(g)
    return T


def sse_ac(T, ea, ec):
    P, Q = T[ea]['P'], T[ec]['P']
    m11 = P[0] + Q[2]; m12 = P[1] - Q[1]; m22 = P[2] + Q[0]      # cross projector = swap and negate
    v1 = T[ea]['q'][0] + T[ec]['t'][0]; v2 = T[ea]['q'][1] + T[ec]['t'][1]
    det = m11 * m22 - m12 * m12
    return T['tot'] - float(np.sum((m22 * v1 * v1 - 2 * m12 * v1 * v2 + m11 * v2 * v2) / det))


def sse_rr(T, e_run, e_ride):
    return T['tot'] - float(np.sum(T[e_run]['sx'][0] ** 2 / T[e_run]['sf'])
                            + np.sum(T[e_ride]['sx'][1] ** 2 / T[e_ride]['sf']))


def gaps(d, adj_run, adj_ride, hi_mask, min_each=25):
    """Adjusted movement in the high park minus the same group elsewhere, by pitch type."""
    g, ng = d['g'], d['g'].max() + 1
    nC = np.bincount(g, weights=hi_mask, minlength=ng); nE = np.bincount(g, weights=~hi_mask, minlength=ng)
    ok = (nC >= min_each) & (nE >= min_each)
    w = np.where(ok, 1 / (1 / np.maximum(nC, 1) + 1 / np.maximum(nE, 1)), 0.0)
    ptg = np.zeros(ng, int); ptg[g] = d['pt']
    out = {}
    for lab, v in (('run', adj_run), ('ride', adj_ride)):
        dd = (np.bincount(g, weights=v * hi_mask, minlength=ng) / np.maximum(nC, 1)
              - np.bincount(g, weights=v * ~hi_mask, minlength=ng) / np.maximum(nE, 1))
        for i, p in enumerate(PT):
            m = ok & (ptg == i)
            if m.sum() >= 5:
                out[f'{lab}_{p}'] = float(np.sum(w[m] * dd[m]) / w[m].sum())
    return out


def adjust(d, design, par):
    f = lambda e: np.exp(e * d['lr'])
    if design == 'ac':
        a = d['a'] / f(par[0]); c = d['c'] / f(par[1])
        return a * d['ux'] - c * d['uz'], a * d['uz'] + c * d['ux']
    return d['hb_arm'] / f(par[0]), d['ivb'] / f(par[1])


def main():
    dens = sys.argv[1] if len(sys.argv) > 1 else 'obsPH'
    obs = json.load(open(os.path.join(OUT, 'game_obs.json')))
    TT = {}
    for yr in YEARS:
        d = prep(load(yr, obs), dens)
        TT[yr] = season_tables(d)
        print(f'{yr}: {TT[yr]["n"]} pitches with a spin axis', flush=True)
        del d
    R = dict(density=dens, EA=EA, EC=EC)

    def grid_ac(years):
        return np.array([[sum(sse_ac(TT[y], ea, ec) for y in years) for ec in EC] for ea in EA])

    def grid_rr(years):
        return np.array([[sum(sse_rr(TT[y], er, ez) for y in years) for ez in EA] for er in EA])

    N = sum(TT[y]['n'] for y in YEARS)
    Gac = grid_ac(YEARS); i, j = np.unravel_index(np.argmin(Gac), Gac.shape)
    Grr = grid_rr(YEARS); k, l = np.unravel_index(np.argmin(Grr), Grr.shape)
    print(f'\nFULL SAMPLE ({dens} density)')
    print(f' along/cross: eA {EA[i]}  eC {EC[j]}   edge: {i in (0, len(EA)-1) or j in (0, len(EC)-1)}')
    print('   along curve at best cross (MSE x1000 minus min): ' +
          ' '.join(f'{e}:{1000*(v-Gac[:, j].min())/N:.1f}' for e, v in zip(EA, Gac[:, j]) if 0.85 <= e <= 1.45))
    print('   cross curve at best along: ' +
          ' '.join(f'{e}:{1000*(v-Gac[i].min())/N:.1f}' for e, v in list(zip(EC, Gac[i]))[::3]))
    print(f' ride/run:    run {EA[k]}  ride {EA[l]}')
    R['full'] = dict(eA=EA[i], eC=EC[j], run=EA[k], ride=EA[l],
                     along_curve=[float(v / N) for v in Gac[:, j]], cross_curve=[float(v / N) for v in Gac[i]])

    print('\nLEAVE ONE SEASON OUT: held-out MSE minus shipped (1.05 on this density), x1000 in^2')
    rows = {k_: [] for k_ in ('one', 'comp', 'ac')}
    picks = {k_: [] for k_ in ('one', 'comp', 'ac')}
    for y in YEARS:
        tr = [t for t in YEARS if t != y]
        base = sse_rr(TT[y], 1.05, 1.05)
        Gtr = grid_rr(tr); d1 = int(np.argmin(np.diag(Gtr)))
        rows['one'].append(1000 * (sse_rr(TT[y], EA[d1], EA[d1]) - base) / TT[y]['n']); picks['one'].append(EA[d1])
        k_, l_ = np.unravel_index(np.argmin(Gtr), Gtr.shape)
        rows['comp'].append(1000 * (sse_rr(TT[y], EA[k_], EA[l_]) - base) / TT[y]['n']); picks['comp'].append((EA[k_], EA[l_]))
        Ga = grid_ac(tr); i_, j_ = np.unravel_index(np.argmin(Ga), Ga.shape)
        rows['ac'].append(1000 * (sse_ac(TT[y], EA[i_], EC[j_]) - base) / TT[y]['n']); picks['ac'].append((EA[i_], EC[j_]))
    for k_ in rows:
        print(f' {k_:5s} ' + ' '.join(f'{v:+7.2f}' for v in rows[k_]) + f'   mean {np.mean(rows[k_]):+.2f}  wins '
              f'{sum(v < 0 for v in rows[k_])}/6   picks {picks[k_]}')
    R['loso'] = dict(rows=rows, picks=picks)

    print('\nHELD-OUT COORS GAP by pitch type, inches (exponents from the other five seasons)')
    G = {k_: {} for k_ in ('ship', 'one', 'ac')}
    for n_, y in enumerate(YEARS):
        d = prep(load(y, obs), dens)
        hi = d['venue'] == COORS
        for k_, par, des in (('ship', (1.05, 1.05), 'rr'), ('one', (picks['one'][n_],) * 2, 'rr'),
                             ('ac', picks['ac'][n_], 'ac')):
            r_, z_ = adjust(d, des, par)
            for key, v in gaps(d, r_, z_, hi).items():
                G[k_].setdefault(key, []).append(v)
        del d
    for key in sorted(G['ship']):
        if len(G['ship'][key]) < 4:
            continue
        print(f' {key:8s} ' + '   '.join(
            f'{k_}: {np.mean(G[k_][key]):+.2f} (sd {np.std(G[k_][key]):.2f})' for k_ in ('ship', 'one', 'ac')))
    R['coors'] = G
    json.dump(R, open(os.path.join(OUT, f'axis_form_{dens}.json'), 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
