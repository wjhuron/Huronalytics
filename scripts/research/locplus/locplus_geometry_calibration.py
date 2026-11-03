#!/usr/bin/env python3
"""locplus_geometry_calibration.py — can the Loc+ surface be made ACCURATE in
the chase and waste regions without giving up its 6 in / 0.30 smoothing?
(2026-09-19, follow-up to locplus_farmiss_rule.py)

DIAGNOSIS (measured the same day). Two causes make an outer-region grade
wrong, and a far-miss cutoff treats neither:
  1. the 6 in / 0.30 kernel pulls the zone's swing and called-strike rates out
     into the chase and waste cells (14-16 in from centre: actual hitter RV
     0.029, shipped 0.005, a 2 in / 0.12 model 0.031);
  2. beyond the grid every pitch is clamped into an edge cell.
Swing probability and called-strike probability are the two GEOMETRY terms;
out there a take is a ball, so they carry nearly the whole error.

CANDIDATE. Keep every shipped surface and constant. Add a SHARP pooled
baseline for each geometry term on an EXTENDED grid (no clamp), and let the
shipped wide-kernel surface supply only its DEVIATION from that baseline:

  swing   B(cell | bats, throws): all pitch types and counts pooled, narrow
          kernel, extended grid. For a (group, hands, count) surface p~ the
          smoother is re-run on the baseline itself with the SAME pitches,
          kernel, priors and K's, giving B~ = "what the wide smoother returns
          when the truth is exactly B". Then
              logit p^ = logit B(true cell) + [logit p~ - logit B~](clamped cell)
          The bracket is a slowly varying logit shift (count and pitch-type
          effects), which a wide kernel estimates without the geometry bias.
  cstrike the shipped surface is already pooled per batter hand, so the
          calibrated version is simply the sharp baseline on the extended grid,
          with the per-(hand, count) logit shifts re-calibrated against it the
          way CS_COUNT_TRANSFORM does.
Whiff, foul and contact surfaces are untouched (they act only after a swing).

TWO OBJECTIVES (failure log 2026-09-02: say which one you are reading).
  calib   PITCH level, out of sample (even dates score odd dates and the
          reverse), squared error against actual hitter RV, paired per pitch
          against shipped, by distance band, by region and over ALL pitches.
          This is the cell-fit objective: it decides the baseline constants
          and it is the accuracy claim.
  run     PITCHER level through locplus_target_audit (next season and within,
          Stuff+ partialled, paired bootstrap). For a DESCRIPTIVE atom this is
          the no-harm check, not the decider (Wally 2026-09-17: displayed
          atoms describe, the composites forecast).

Usage (repo root):
  python3 scripts/research/locplus/locplus_geometry_calibration.py selftest
  python3 scripts/research/locplus/locplus_geometry_calibration.py calib --stage sw|cs|kb|final
  python3 scripts/research/locplus/locplus_geometry_calibration.py run --arm name=sw:cs:bx:bz:csbx:csbz:kb
  python3 scripts/research/locplus/locplus_geometry_calibration.py summary
"""
import argparse
import gc
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline.locplus as lp                           # noqa: E402
import locplus_fullseason_replicate as FR               # noqa: E402
import locplus_target_audit as TA                       # noqa: E402

CACHE = os.path.join(ROOT, 'data', '_loc_geocal')
TA.CACHE = CACHE
TA.OUT = os.path.join(CACHE, 'summary.json')

# Knobs live on the lp module so the audit's config setter can flip and restore
# them. All off = the shipped model, bit for bit (see selftest).
lp.GEOCAL_SW = 0
lp.GEOCAL_CS = 0
lp.GEOCAL_BX, lp.GEOCAL_BZ = 1.5, 0.12          # swing baseline bandwidth (in, zone-heights)
lp.GEOCAL_CSBX, lp.GEOCAL_CSBZ = 1.5, 0.12      # called-strike baseline bandwidth
lp.GEOCAL_KB = 10.0                             # baseline pseudo-count toward its wide-kernel self
lp.GEOCAL_LAM = 1.0        # 0 = shipped, 1 = fully calibrated; blended on the logit scale (a FRONTIER knob, no optimum)
lp.GEOCAL_REGION = 0       # 1 = calibrate only pitches outside the shipped grid (the clamped ones)
_ORIG_SCORE = lp.score_pitch
_ORIG_BUILD = lp.build_surfaces

# Extended grid: same bins as the shipped grid, aligned to it, far enough that
# nothing scorable is left to clamp (checked in selftest).
EX_MIN, EX_MAX = -4.0, 4.0
EZ_MIN, EZ_MAX = -3.0, 4.0
ENX = int(round((EX_MAX - EX_MIN) / lp.BIN_X))
ENZ = int(round((EZ_MAX - EZ_MIN) / lp.BIN_Z))
EPS = 1e-4
HANDS4 = [(b, t) for b in lp.HANDS for t in lp.HANDS]
H4 = {h: i for i, h in enumerate(HANDS4)}
H2 = {h: i for i, h in enumerate(lp.HANDS)}
CIDX = {c: i for i, c in enumerate(lp.COUNTS)}


def exbin(px):
    return min(max(int((px - EX_MIN) / lp.BIN_X), 0), ENX - 1)


def ezbin(zn):
    return min(max(int((zn - EZ_MIN) / lp.BIN_Z), 0), ENZ - 1)


def _W(n, sig_cells):
    """n x n weights of pipeline.locplus._k1d: exp(-0.5 (d / sig)^2), cut at
    ceil(3 sig) cells, unnormalized (every use is a ratio), zero past the edge."""
    win = max(1, int(math.ceil(3 * sig_cells)))
    d = np.arange(n)[:, None] - np.arange(n)[None, :]
    return np.where(np.abs(d) <= win, np.exp(-0.5 * (d / sig_cells) ** 2), 0.0)


def _sm2(a, sx, sz):
    """Separable smoothing over the last two axes (x, z); sx / sz in CELLS."""
    Wx, Wz = _W(a.shape[-2], sx), _W(a.shape[-1], sz)
    return np.einsum('ik,...kl,jl->...ij', Wx, a, Wz)


def _logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def sharp_baseline(num, den, bx_in, bz, kb):
    """Narrow-kernel rate on the extended grid, shrunk by kb pseudo-pitches
    toward the SAME data under the shipped wide kernel (0 where even that is
    empty: nobody swings, nothing is called, four feet off the plate)."""
    sxw, szw = lp.PHYS_X_IN / lp.BIN_X_IN, lp.PHYS_Z_FRAC / lp.BIN_Z
    nw, dw = _sm2(num, sxw, szw), _sm2(den, sxw, szw)
    wide = np.where(dw > 1e-9, nw / np.maximum(dw, 1e-9), 0.0)
    sxn, szn = bx_in / lp.BIN_X_IN, bz / lp.BIN_Z
    nn, dn = _sm2(num, sxn, szn), _sm2(den, sxn, szn)
    s = dn + kb
    return np.where(s > 1e-9, (nn + kb * wide) / np.maximum(s, 1e-9), wide)


# ── per-pitch arrays ─────────────────────────────────────────────────────
def prep(pitches, keys=None):
    """Index arrays for a pitch list. keys: fixed key->index map (scoring), or
    None to build one (baseline)."""
    own = keys is None
    keys = {} if own else keys
    cols = defaultdict(list)
    kept = []
    for n, p in enumerate(pitches):
        key = (lp.group_of(p), p.get('Bats'), p.get('Throws'))
        c = lp.get_count(p)
        px = lp.safe_float(p.get('PlateX')); zn = lp._znorm(p)
        if c is None or px is None or zn is None or key[1] not in H2 or key[2] not in H2:
            continue
        if key not in keys:
            if not own:
                continue
            keys[key] = len(keys)
        d = p.get('Description')
        cols['k'].append(keys[key]); cols['c'].append(CIDX[c])
        cols['i'].append(lp._xbin(px)); cols['j'].append(lp._zbin(zn))
        cols['ei'].append(exbin(px)); cols['ej'].append(ezbin(zn))
        cols['h4'].append(H4[(key[1], key[2])]); cols['h2'].append(H2[key[1]])
        cols['sw'].append(1.0 if d in lp.SWING_DESC else 0.0)
        cols['tk'].append(1.0 if d in lp.TAKE_DESC else 0.0)
        cols['cs'].append(1.0 if d == 'Called Strike' else 0.0)
        cols['dx'].append(abs(px) * 12.0); cols['zn'].append(zn)
        kept.append(n)
    out = {k: np.asarray(v, dtype=(float if k in ('sw', 'tk', 'cs', 'dx', 'zn') else np.int64))
           for k, v in cols.items()}
    out['row'] = np.asarray(kept, dtype=np.int64)
    out['keys'] = keys
    return out


def fit(P, S, arm):
    """Calibration arrays for one arm on one baseline (P = prep(baseline))."""
    nk = len(P['keys'])
    G = {'keys': P['keys'], 'sw': bool(arm['sw']), 'cs': bool(arm['cs']),
         'lam': float(arm.get('lam', 1.0)), 'region': int(arm.get('region', 0))}
    assert not lp.PHYS_BW_PT, 'per-group bandwidths are not mirrored here'
    kx, kz = lp.PHYS_X_IN / lp.BIN_X_IN, lp.PHYS_Z_FRAC / lp.BIN_Z      # the shipped kernel, in cells
    if arm['sw']:
        num = np.zeros((4, ENX, ENZ)); den = np.zeros((4, ENX, ENZ))
        np.add.at(num, (P['h4'], P['ei'], P['ej']), P['sw'])
        np.add.at(den, (P['h4'], P['ei'], P['ej']), 1.0)
        B = sharp_baseline(num, den, arm['bx'], arm['bz'], arm['kb'])
        e = B[P['h4'], P['ei'], P['ej']]                     # expected swings per pitch under B
        Ek = np.zeros((nk, lp.NX, lp.NZ)); Dk = np.zeros((nk, lp.NX, lp.NZ))
        Ekc = np.zeros((nk, 12, lp.NX, lp.NZ)); Dkc = np.zeros((nk, 12, lp.NX, lp.NZ))
        np.add.at(Ek, (P['k'], P['i'], P['j']), e); np.add.at(Dk, (P['k'], P['i'], P['j']), 1.0)
        np.add.at(Ekc, (P['k'], P['c'], P['i'], P['j']), e)
        np.add.at(Dkc, (P['k'], P['c'], P['i'], P['j']), 1.0)
        # mirror of build_surfaces' swing block: coll, then the per-count surface
        b0 = (Ek.sum((1, 2)) / np.maximum(Dk.sum((1, 2)), 1.0))[:, None, None]
        Bt_coll = (_sm2(Ek, kx, kz) + lp.K_SWING_COLL * b0) / (_sm2(Dk, kx, kz) + lp.K_SWING_COLL)
        Bt = (_sm2(Ekc, kx, kz) + lp.K_SWING_COUNT * Bt_coll[:, None]) / (_sm2(Dkc, kx, kz) + lp.K_SWING_COUNT)
        SW = np.zeros((nk, 12, lp.NX, lp.NZ))
        for key, ki in P['keys'].items():
            for c, ci in CIDX.items():
                SW[ki, ci] = np.asarray(S['SW'][key][c])
        G['Bsw'] = B
        G['dsw'] = _logit(SW) - _logit(Bt)
    if arm['cs']:
        tk = P['tk'] > 0
        num = np.zeros((2, ENX, ENZ)); den = np.zeros((2, ENX, ENZ))
        np.add.at(num, (P['h2'][tk], P['ei'][tk], P['ej'][tk]), P['cs'][tk])
        np.add.at(den, (P['h2'][tk], P['ei'][tk], P['ej'][tk]), 1.0)
        Bc = sharp_baseline(num, den, arm['csbx'], arm['csbz'], arm['kb'])
        d = np.zeros((2, 12))
        if lp.CS_COUNT_TRANSFORM:
            pred = np.zeros((2, 12)); obs = np.zeros((2, 12)); n = np.zeros((2, 12))
            np.add.at(pred, (P['h2'][tk], P['c'][tk]), Bc[P['h2'][tk], P['ei'][tk], P['ej'][tk]])
            np.add.at(obs, (P['h2'][tk], P['c'][tk]), P['cs'][tk])
            np.add.at(n, (P['h2'][tk], P['c'][tk]), 1.0)
            ok = (n >= 50) & (obs > 0) & (obs < n) & (pred > 0)
            d[ok] = _logit(obs[ok] / n[ok]) - _logit(pred[ok] / n[ok])
        G['Bcs'] = Bc
        G['dcs'] = d
    return G


def arm_now():
    return {'sw': lp.GEOCAL_SW, 'cs': lp.GEOCAL_CS, 'bx': lp.GEOCAL_BX, 'bz': lp.GEOCAL_BZ,
            'csbx': lp.GEOCAL_CSBX, 'csbz': lp.GEOCAL_CSBZ, 'kb': lp.GEOCAL_KB,
            'lam': lp.GEOCAL_LAM, 'region': lp.GEOCAL_REGION}


# ── production-path patch (target audit, downstream builders) ───────────
def build_surfaces(baseline, lg_woba, woba_scale):
    S = _ORIG_BUILD(baseline, lg_woba, woba_scale)
    if lp.GEOCAL_SW or lp.GEOCAL_CS:
        S['GEO'] = fit(prep(baseline), S, arm_now())
    return S


def parts(p, S):
    """score_pitch's terms, unrecombined: (key, c, i, j, px, zn, psw, swing_val, pcs, rv_cs, rv_ball)."""
    key = (lp.group_of(p), p.get('Bats'), p.get('Throws'))
    if key not in S['WH']:
        return None
    c = lp.get_count(p)
    px = lp.safe_float(p.get('PlateX')); zn = lp._znorm(p)
    if c is None or px is None or zn is None:
        return None
    i = lp._xbin(px); j = lp._zbin(zn)
    pwh = S['WH'][key][c][i][j]; pfl = S['FL'][key][i][j]
    pbip = max(0.0, 1.0 - pwh - pfl)
    vbip = S['XW'][key][i][j] + S['XWOFF'].get(c, 0.0) + S['BIPOFF'].get(c, 0.0)
    RV = S['RV']
    sv = pwh * RV['whiff'].get(c, 0.0) + pfl * RV['foul'].get(c, 0.0) + pbip * vbip
    return (key, c, i, j, px, zn, S['SW'][key][c][i][j], sv, S['PCS'][p['Bats']][c][i][j],
            RV['cs'].get(c, 0.0), RV['ball'].get(c, 0.0))


def score_pitch(p, S):
    G = S.get('GEO')
    if G is None:
        return _ORIG_SCORE(p, S)
    t = parts(p, S)
    if t is None:
        return None
    key, c, i, j, px, zn, psw, sv, pcs, rcs, rball = t
    ei, ej = exbin(px), ezbin(zn)
    lam = G.get('lam', 1.0)
    if G.get('region') and not (abs(px) * 12.0 > 18.0 or zn < -0.6 or zn > 1.6):
        lam = 0.0

    def _blend(p_ship, x_cal):
        q = min(max(p_ship, EPS), 1 - EPS)
        return 1.0 / (1.0 + math.exp(-((1 - lam) * math.log(q / (1 - q)) + lam * x_cal)))
    if G['sw'] and lam > 0:
        b = min(max(float(G['Bsw'][H4[(key[1], key[2])], ei, ej]), EPS), 1 - EPS)
        psw = _blend(psw, math.log(b / (1 - b)) + float(G['dsw'][G['keys'][key], CIDX[c], i, j]))
    if G['cs'] and lam > 0:
        h = H2[key[1]]
        b = min(max(float(G['Bcs'][h, ei, ej]), EPS), 1 - EPS)
        pcs = _blend(pcs, math.log(b / (1 - b)) + float(G['dcs'][h, CIDX[c]]))
    return psw * sv + (1 - psw) * (pcs * rcs + (1 - pcs) * rball)


lp.score_pitch = score_pitch
lp.build_surfaces = build_surfaces


# ── calib: pitch level, out of sample, many arms in one pass ────────────
X_BANDS = [0, 4, 8, 10, 12, 14, 16, 18, 20, 22, 24, 27, 30, 36, 1e9]
M_BANDS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0, 1e9]


def dims_of(dx, zn, strikes):
    """{dim name: integer band index per pitch, -1 = not in this dim}."""
    in_z = (zn >= -0.6) & (zn <= 1.6); in_x = dx <= 18.0
    out = {'x': np.where(in_z, np.digitize(dx, X_BANDS) - 1, -1),
           'lo': np.where(in_x & (zn < 0), np.digitize(-zn, M_BANDS) - 1, -1),
           'hi': np.where(in_x & (zn > 1), np.digitize(zn - 1.0, M_BANDS) - 1, -1)}
    core = (dx <= 12.0) & (zn >= -0.2) & (zn <= 1.2)
    beyond = (dx > 18.0) | (zn < -0.6) | (zn > 1.6)
    reg = np.where(core, 0, np.where(beyond, 2, 1))
    out['region'] = reg                                   # 0 core, 1 chase ring (in grid), 2 beyond the grid
    out['region_2k'] = np.where(strikes == 2, reg, -1)
    out['region_01k'] = np.where(strikes < 2, reg, -1)
    out['all'] = np.zeros(len(dx), dtype=np.int64)
    return out


REG = ['core: within 12 in and 0.2 zone-heights', 'chase ring: rest of the grid', 'beyond the grid (clamped)']


def label(dim, b):
    if dim == 'x':
        return f'{X_BANDS[b]:g}-{X_BANDS[b + 1]:g} in' if X_BANDS[b + 1] < 1e8 else f'{X_BANDS[b]:g}+ in'
    if dim in ('lo', 'hi'):
        return f'{M_BANDS[b]:g}-{M_BANDS[b + 1]:g}' if M_BANDS[b + 1] < 1e8 else f'{M_BANDS[b]:g}+'
    if dim.startswith('region'):
        return REG[b]
    return 'ALL pitches'


def calib(arms, seasons, tag):
    os.makedirs(CACHE, exist_ok=True)
    acc = defaultdict(lambda: np.zeros(6))          # (arm, dim, band, yr) -> n, y, v_ship, v_arm, e, e^2
    for yr in seasons:
        t0 = time.time()
        pitches = FR.load_season(yr)
        base_p = [p for p in pitches if lp.is_eligible_baseline(p)]
        dates = sorted({p['Game Date'] for p in base_p if p['Game Date']})
        par = {d: i % 2 for i, d in enumerate(dates)}
        for fold in (0, 1):
            train = [p for p in base_p if par.get(p['Game Date']) != fold]
            test = [p for p in base_p if par.get(p['Game Date']) == fold
                    and lp.safe_float(p.get('RunExp')) is not None]
            S = _ORIG_BUILD(train, FR.LG, FR.SCALE)
            Ptr = prep(train)
            Pte = prep(test, keys=Ptr['keys'])
            rows = [test[n] for n in Pte['row']]
            pr = [parts(p, S) for p in rows]
            ok = np.array([t is not None for t in pr])
            assert ok.all(), 'prep kept a pitch parts() cannot score'
            psw = np.array([t[6] for t in pr]); sv = np.array([t[7] for t in pr])
            pcs = np.array([t[8] for t in pr]); rcs = np.array([t[9] for t in pr]); rb = np.array([t[10] for t in pr])
            y = np.array([-lp.safe_float(p['RunExp']) for p in rows])
            strikes = np.array([t[1][1] for t in pr])
            v_ship = psw * sv + (1 - psw) * (pcs * rcs + (1 - pcs) * rb)
            D = dims_of(Pte['dx'], Pte['zn'], strikes)
            for arm in arms:
                G = fit(Ptr, S, arm)
                q, r = psw, pcs
                lam = np.full(len(psw), G['lam'])
                if G['region']:
                    lam = np.where((Pte['dx'] > 18.0) | (Pte['zn'] < -0.6) | (Pte['zn'] > 1.6), lam, 0.0)
                if arm['sw']:
                    q = _sig((1 - lam) * _logit(psw) + lam * (_logit(G['Bsw'][Pte['h4'], Pte['ei'], Pte['ej']])
                                                            + G['dsw'][Pte['k'], Pte['c'], Pte['i'], Pte['j']]))
                if arm['cs']:
                    r = _sig((1 - lam) * _logit(pcs) + lam * (_logit(G['Bcs'][Pte['h2'], Pte['ei'], Pte['ej']])
                                                            + G['dcs'][Pte['h2'], Pte['c']]))
                v = q * sv + (1 - q) * (r * rcs + (1 - r) * rb)
                e = (y - v) ** 2 - (y - v_ship) ** 2           # < 0: the arm fits better
                for dim, b in D.items():
                    m = b >= 0
                    nb = int(b[m].max()) + 1 if m.any() else 0
                    for col, w in enumerate((None, y, v_ship, v, e, e * e)):
                        s = np.bincount(b[m], weights=None if w is None else w[m], minlength=nb)
                        for bi in range(nb):
                            acc[(arm['name'], dim, bi, yr)][col] += s[bi]
        print(f'=== {yr}: {len(arms)} arms, both folds ({time.time() - t0:.0f}s)', flush=True)
        del pitches, base_p
        gc.collect()
    out = {}
    for (name, dim, b, yr), t in acc.items():
        out.setdefault(name, {}).setdefault(dim, {}).setdefault(b, {})[yr] = t
    res = {}
    for name in [a['name'] for a in arms]:
        res[name] = {}
        for dim in out[name]:
            for b in sorted(out[name][dim]):
                per = out[name][dim][b]
                t = sum(per.values()); n = t[0]
                if n < 1:
                    continue
                e = t[4] / n
                se = math.sqrt(max(t[5] / n - e * e, 0.0) / n)
                res[name][f'{dim}|{label(dim, b)}'] = {
                    'n': int(n), 'actual': t[1] / n, 'shipped': t[2] / n, 'arm': t[3] / n,
                    'e': e, 'se': se, 'z': e / se if se else float('nan'),
                    'wins': sum(1 for v in per.values() if v[0] and v[4] < 0), 'k': len(per)}
    dest = os.path.join(CACHE, f'calib_{tag}.json')
    json.dump({'arms': arms, 'res': res}, open(dest + '.tmp', 'w'), indent=1)
    os.replace(dest + '.tmp', dest)
    print('\n===== ALL pitches: MSE(arm) - MSE(shipped) x 1e4 per pitch; negative = the arm fits better =====')
    for a in arms:
        r = res[a['name']]['all|ALL pitches']
        rr = [res[a['name']].get(f'region|{x}') for x in REG]
        print(f"  {a['name']:>26s}  all {r['e'] * 1e4:>+8.3f} (z {r['z']:>+6.1f}, {r['wins']}/{r['k']})   "
              + '   '.join(f"{lab} {x['e'] * 1e4:>+7.2f} (z {x['z']:>+5.1f})" for lab, x in zip(('core', 'ring', 'beyond'), rr)))
    print(f'\nwrote {dest}')
    return res


def show(tag, name):
    d = json.load(open(os.path.join(CACHE, f'calib_{tag}.json')))['res'][name]
    print(f'===== {name}: actual vs shipped vs arm (mean hitter RV), e x 1e4, z, seasons won =====')
    for k, v in d.items():
        print(f"  {k:<58s} n {v['n']:>8d}  actual {v['actual']:>+.4f}  shipped {v['shipped']:>+.4f}  arm {v['arm']:>+.4f}  "
              f"e {v['e'] * 1e4:>+8.2f}  z {v['z']:>+6.1f}  {v['wins']}/{v['k']}")


def mk(name, sw=1, cs=0, bx=1.5, bz=0.12, csbx=1.5, csbz=0.12, kb=10.0, lam=1.0, region=0):
    return {'name': name, 'sw': sw, 'cs': cs, 'bx': bx, 'bz': bz, 'csbx': csbx, 'csbz': csbz, 'kb': kb,
            'lam': lam, 'region': region}


def stage_arms(stage, best):
    b = dict(best)
    if stage == 'sw':
        return [mk(f'sw_x{x:g}_z{z:g}', bx=x, bz=z, kb=b['kb']) for x in (1, 1.5, 2, 3, 4.5) for z in (0.06, 0.12, 0.18, 0.30)]
    if stage == 'sw2':      # x was monotone toward the 1 in edge of the first grid: extend below it
        return [mk(f'sw_x{x:g}_z{z:g}', bx=x, bz=z, kb=b['kb']) for x in (0.5, 0.75, 1, 1.5) for z in (0.06, 0.09, 0.12)]
    if stage == 'cs':
        return [mk(f'cs_x{x:g}_z{z:g}', sw=0, cs=1, csbx=x, csbz=z, kb=b['kb']) for x in (1, 1.5, 2, 3) for z in (0.04, 0.06, 0.09, 0.12, 0.18)]
    if stage == 'cs2':      # both axes were monotone toward the narrow edge of the first grid: extend below it
        return [mk(f'cs_x{x:g}_z{z:g}', sw=0, cs=1, csbx=x, csbz=z, kb=b['kb']) for x in (0.25, 0.5, 0.75, 1) for z in (0.02, 0.04, 0.06)]
    if stage == 'kb':
        return [mk(f'kb{k:g}', sw=1, cs=1, bx=b['bx'], bz=b['bz'], csbx=b['csbx'], csbz=b['csbz'], kb=k) for k in (0, 2, 5, 10, 20, 50, 150)]
    if stage == 'frontier':
        return ([mk(f'lam{l:g}', sw=1, cs=1, lam=l, **b) for l in (0.25, 0.5, 0.75, 1.0)]
                + [mk('beyond_only', sw=1, cs=1, region=1, **b)])
    return [mk('SW', sw=1, cs=0, **{k: b[k] for k in ('bx', 'bz', 'kb')}),
            mk('CS', sw=0, cs=1, **{k: b[k] for k in ('csbx', 'csbz', 'kb')}),
            mk('SW+CS', sw=1, cs=1, **b)]


def selftest():
    P = FR.load_season(2024)
    base_p = [p for p in P if lp.is_eligible_baseline(p)]
    sc = [p for p in P if lp._is_scorable(p)]
    S = _ORIG_BUILD(base_p, FR.LG, FR.SCALE)
    S['GEO'] = {'sw': False, 'cs': False, 'keys': {}}
    bad = sum(1 for p in sc if score_pitch(p, S) != _ORIG_SCORE(p, S))
    print(f'recombined parts() vs production score_pitch: {bad} mismatches on {len(sc)} pitches')
    pe = prep(sc)
    edge = ((pe['ei'] == 0) | (pe['ei'] == ENX - 1) | (pe['ej'] == 0) | (pe['ej'] == ENZ - 1)).sum()
    print(f'pitches on the extended grid\'s own edge cells (still clamped): {int(edge)} of {len(pe["ei"])}')
    del S['GEO']
    G = fit(prep(base_p), S, mk('t', sw=1, cs=1))
    print(f'swing baseline range {G["Bsw"].min():.4f}..{G["Bsw"].max():.4f}; dsw logit shift mean '
          f'{G["dsw"].mean():+.3f} sd {G["dsw"].std():.3f}; cs count shifts {np.round(G["dcs"][1], 2).tolist()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['selftest', 'calib', 'show', 'run', 'run-cut', 'summary'])
    ap.add_argument('--stage', default='final')
    ap.add_argument('--best', default='1.5:0.12:1.5:0.12:10', help='bx:bz:csbx:csbz:kb carried between stages')
    ap.add_argument('--arm', action='append', default=[], help='run: name=sw:cs:bx:bz:csbx:csbz:kb[:lam[:region]]')
    ap.add_argument('--name', default=None)
    ap.add_argument('--seasons', default=None)
    ap.add_argument('--fracs', default='0.25,0.5,0.75')
    ap.add_argument('--cut', type=float, default=None)
    a = ap.parse_args()
    seasons = [int(s) for s in a.seasons.split(',')] if a.seasons else sorted(FR.SEASONS)
    best = dict(zip(('bx', 'bz', 'csbx', 'csbz', 'kb'), (float(x) for x in a.best.split(':'))))
    if a.cmd == 'selftest':
        return selftest()
    if a.cmd == 'calib':
        return calib(stage_arms(a.stage, best), seasons, a.stage)
    if a.cmd == 'show':
        return show(a.stage, a.name)
    if a.cmd == 'summary':
        import locplus_farmiss_rule as FM
        FM.TA.CACHE, FM.TA.OUT = CACHE, TA.OUT          # that import re-points the shared audit module
        TA.summarize(only='geo', cut=a.cut)
        return FM.compact(TA.OUT.replace('.json', f'_shipped@c{a.cut:g}_geo.json' if a.cut is not None
                                         else '_shipped_geo.json'))
    configs = {'shipped': {**FR.SHIPPED, 'GEOCAL_SW': 0, 'GEOCAL_CS': 0, 'GEOCAL_LAM': 1.0, 'GEOCAL_REGION': 0}}
    for spec in a.arm:
        name, vals = spec.split('=', 1)
        v = [float(x) for x in vals.split(':')]
        configs[name] = {**FR.SHIPPED, 'GEOCAL_SW': int(v[0]), 'GEOCAL_CS': int(v[1]), 'GEOCAL_BX': v[2],
                         'GEOCAL_BZ': v[3], 'GEOCAL_CSBX': v[4], 'GEOCAL_CSBZ': v[5], 'GEOCAL_KB': v[6],
                         'GEOCAL_LAM': v[7] if len(v) > 7 else 1.0, 'GEOCAL_REGION': int(v[8]) if len(v) > 8 else 0}
    if a.cmd == 'run-cut':
        return TA.run_cut(configs, seasons, [float(x) for x in a.fracs.split(',')])
    TA.run(configs, seasons)


if __name__ == '__main__':
    main()
