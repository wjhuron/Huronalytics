"""Expected movement: xIVB / xHB and the IVBOE / HBOE residuals.

What a pitch "should" do, judged the way a HITTER judges it. One ridge fit per
(pitch type, throwing hand), fit on the season's MLB pitches, on the three
things a hitter can read before the ball moves:

    arm angle, extension, velocity.

Spin rate and the release spin axis are deliberately NOT inputs. Both are in
the data and a basis on them (BASIS = 'physics' below: two axis harmonics plus
a spin x axis tensor) explains far more of the movement itself, 0.49 / 0.42
within-type R^2 against 0.27 / 0.18. It shipped for about four hours on
2026-09-03 and was pulled the same day, because it answers the wrong question
for the chart it sits on. Measured across 2021-2025, each season predicted from
the other four (scripts/research/xmove/xmove_residual_value.py):

    residual measured against      whiff r   run-value r   whiff r with raw movement in
    slot only                        0.11        0.02              0.15
    slot + extension + velocity      0.13        0.07              0.22
    slot + ext + velo + spin + axis  0.05        0.05              0.15

Extra spin and a clean axis ARE the weapon. A physics expectation credits them
away, so its residual explains results worse than raw movement does. The
hitter expectation leaves them in the residual, where they read as surprise.
So the chart's ghost is "what a pitcher who looks like this usually throws",
and the arrow to the actual pitch is what the hitter did not see coming. Per
Wally, 2026-09-03: "put the hitter model back on the chart." The physics
basis stays in this module for research and scouting use; it is not scored.

The 'roc' variant swaps arm angle for the release point (RelPosZ, RelPosX) and
serves only pitches with no arm angle; both variants are fit on MLB pitches so
a ROC arm is measured against the MLB baseline.

Scoring is per pitch and the site sums the per-pitch expectations (micro rows
sumXIVB/nXIVB/sumXHB/nXHB). For the hitter basis that is exact either way; it
is kept per pitch so the physics basis, which is nonlinear in tilt, can be
switched in without touching a consumer.

Since 2026-11-19 a SECOND model is scored beside this one: the per-pitch
physics expectation at the bottom of this module (`fit_physics`,
`score_physics_all`). It reads no pitch type and answers a different question
(where should a pitch with this velocity, spin, axis and slot go), on a
different objective (held-out movement fit). It is not the per-type
BASIS = 'physics' form described above, and it does not replace the hitter
basis: the site and the cards offer both.
"""
import math

import numpy as np

from pipeline.utils import break_tilt_to_minutes, safe_float

BASIS = 'hitter'          # 'hitter' (shipped) or 'physics' (research only)

# Ridge penalty on the standardised columns (intercept unpenalised) and the
# per-(type, hand) pool floor, swept JOINTLY per basis on 2025
# (scripts/research/xmove/xmove_ridge_sweep.py: four groups incl. FS_L, held-out
# RMSE excess over the full-pool OLS fit, median of 20 draws, after the MAD
# screen).
#   hitter (shipped): the excess is FLAT in lambda from 0 to 3e-2 at every n
#     (worst group 0.046" at n=150, 0.025" at 300), so 0 is a convention on a
#     flat region, i.e. plain least squares; the floor stays at the original
#     150 because the worst group is already under the 0.10" bar there (0.10"
#     = display rounding, itself a convention).
#   physics (research): 3e-3 is an interior optimum (0 and 1.0 both worse at
#     every n) because the harmonic columns go collinear in narrow-tilt groups
#     (CH_L: 1.8" excess at n=1000 unpenalised); floor 300 = first n under
#     0.10" on the worst group.
XMOVE_RIDGE = {'hitter': 0.0, 'physics': 3e-3}[BASIS]
XMOVE_MIN_N = {'hitter': 150, 'physics': 300}[BASIS]
MAD_THRESH = 6.0
SPIN_SCALE = 1000.0

HARMONIC_TERMS = ['spin', 'h1s', 'h1c', 'h2s', 'h2c', 'sp1s', 'sp1c', 'sp2s', 'sp2c']
TERMS_MLB = ['aa', 'ext', 'velo'] + (HARMONIC_TERMS if BASIS == 'physics' else [])
TERMS_ROC = ['rz', 'rx', 'ext', 'velo'] + (HARMONIC_TERMS if BASIS == 'physics' else [])


def hand_sign(throws):
    return 1.0 if throws == 'R' else -1.0


def release_theta(rtilt, throws):
    """Hand-signed release axis in radians from a clock string. None if absent."""
    minutes = break_tilt_to_minutes(rtilt)
    if minutes is None:
        return None
    return minutes / 720.0 * 2.0 * math.pi * hand_sign(throws)


def _spin_theta(p, throws):
    """Spin rate and hand-signed release axis for the physics basis. The
    hitter basis reads neither, so it returns placeholders that never gate a
    pitch out (coverage then matches the pre-2026-09-03 model exactly)."""
    if BASIS != 'physics':
        return 0.0, 0.0
    return safe_float(p.get('Spin Rate')), release_theta(p.get('RTilt'), throws)


def _design(cols, theta):
    """cols: dict of 1-D arrays (aa or rz/rx, ext, velo, and spin for the
    physics basis); theta: hand-signed release axis, read only by the physics
    basis. Returns the design matrix with an intercept column first."""
    n = len(cols['ext'])
    parts = [np.ones(n)]
    for k in ('rz', 'rx', 'aa'):
        if k in cols:
            parts.append(cols[k])
    parts += [cols['ext'], cols['velo']]
    if BASIS == 'physics':
        sp = cols['spin'] / SPIN_SCALE
        parts.append(cols['spin'])
        for k in (1, 2):
            s, c = np.sin(k * theta), np.cos(k * theta)
            parts += [s, c]
        for k in (1, 2):
            s, c = np.sin(k * theta), np.cos(k * theta)
            parts += [sp * s, sp * c]
    return np.column_stack(parts)


def _mad_keep(X):
    """Rows within MAD_THRESH MADs of the column median on every column."""
    med = np.median(X, axis=0)
    mad = np.median(np.abs(X - med), axis=0)
    ok = np.ones(len(X), dtype=bool)
    for j in range(X.shape[1]):
        if mad[j] > 1e-9:
            ok &= np.abs(X[:, j] - med[j]) <= MAD_THRESH * mad[j]
    return ok


def _fit(rows, use_relpt):
    """rows: list of (ivb, hb_s, aa, rz, rx, ext, velo, spin, theta)."""
    A = np.asarray(rows, dtype='f8')
    screen_cols = [0, 1, 5, 6] + ([7] if BASIS == 'physics' else []) + ([3, 4] if use_relpt else [2])
    keep = _mad_keep(A[:, screen_cols])
    if keep.sum() < XMOVE_MIN_N:
        keep[:] = True
    A = A[keep]
    cols = {'ext': A[:, 5], 'velo': A[:, 6], 'spin': A[:, 7]}
    if use_relpt:
        cols['rz'], cols['rx'] = A[:, 3], A[:, 4]
    else:
        cols['aa'] = A[:, 2]
    X = _design(cols, A[:, 8])
    return {'ivb': _ridge(X, A[:, 0]).tolist(), 'hb': _ridge(X, A[:, 1]).tolist(),
            'n': int(len(A))}


def _ridge(X, y, lam=None):
    """Ridge on standardised columns (intercept, column 0, unpenalised).
    Returns coefficients in RAW units with the intercept first, so scoring is
    one dot product with the design row."""
    lam = XMOVE_RIDGE if lam is None else lam
    Z = X[:, 1:]
    mu, sd = Z.mean(axis=0), Z.std(axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    Zs = (Z - mu) / sd
    ym = y.mean()
    n, k = Zs.shape
    b = np.linalg.solve(Zs.T @ Zs + lam * n * np.eye(k), Zs.T @ (y - ym))
    braw = b / sd
    return np.concatenate([[ym - braw @ mu], braw])


def fit_models(all_pitches):
    """One model per 'PT_H' key, MLB pitches only. Each key holds an 'mlb'
    variant (arm angle) and, where the pool allows, a 'roc' variant (release
    point) for pitches with no arm angle."""
    pools_mlb, pools_roc = {}, {}
    for p in all_pitches:
        if p.get('_source', 'MLB') != 'MLB':
            continue
        pt = p.get('Pitch Type')
        throws = p.get('Throws')
        if not pt or throws not in ('L', 'R'):
            continue
        ivb = safe_float(p.get('xIndVrtBrk'))
        hb = safe_float(p.get('xHorzBrk'))
        ext = safe_float(p.get('Extension'))
        velo = safe_float(p.get('Velocity'))
        spin, theta = _spin_theta(p, throws)
        if None in (ivb, hb, ext, velo, spin, theta):
            continue
        s = hand_sign(throws)
        aa = safe_float(p.get('ArmAngle'))
        rz = safe_float(p.get('RelPosZ'))
        rx = safe_float(p.get('RelPosX'))
        key = pt + '_' + throws
        if aa is not None:
            pools_mlb.setdefault(key, []).append((ivb, hb * s, aa, 0.0, 0.0, ext, velo, spin, theta))
        if rz is not None and rx is not None:
            pools_roc.setdefault(key, []).append((ivb, hb * s, 0.0, rz, rx * s, ext, velo, spin, theta))
    models = {}
    for key in sorted(set(pools_mlb) | set(pools_roc)):
        m = {}
        if len(pools_mlb.get(key, ())) >= XMOVE_MIN_N:
            m['mlb'] = _fit(pools_mlb[key], use_relpt=False)
        if len(pools_roc.get(key, ())) >= XMOVE_MIN_N:
            m['roc'] = _fit(pools_roc[key], use_relpt=True)
        if m:
            models[key] = m
    return models


def score_pitch(models, p):
    """(xIVB, xHB) for one pitch dict, HB in the display frame. (None, None)
    when the group has no model or the pitch lacks an input. Arm-angle
    variant first, release-point variant as the fallback."""
    pt = p.get('Pitch Type')
    throws = p.get('Throws')
    m = models.get((pt or '') + '_' + (throws or ''))
    if not m:
        return None, None
    ext = safe_float(p.get('Extension'))
    velo = safe_float(p.get('Velocity'))
    spin, theta = _spin_theta(p, throws)
    if None in (ext, velo, spin, theta):
        return None, None
    s = hand_sign(throws)
    aa = safe_float(p.get('ArmAngle'))
    rz = safe_float(p.get('RelPosZ'))
    rx = safe_float(p.get('RelPosX'))
    if m.get('mlb') and aa is not None:
        cols = {'aa': np.array([aa])}
        variant = m['mlb']
    elif m.get('roc') and rz is not None and rx is not None:
        cols = {'rz': np.array([rz]), 'rx': np.array([rx * s])}
        variant = m['roc']
    else:
        return None, None
    cols.update({'ext': np.array([ext]), 'velo': np.array([velo]), 'spin': np.array([spin])})
    X = _design(cols, np.array([theta]))
    xivb = float(X @ np.asarray(variant['ivb']))
    xhb = float(X @ np.asarray(variant['hb'])) * s
    return xivb, xhb


def score_all(models, all_pitches):
    """Vectorised score_pitch over a list of pitch dicts. Writes '_xivb' and
    '_xhb' onto each dict (absent when unscored) and returns the count scored."""
    by_key = {}
    for i, p in enumerate(all_pitches):
        pt = p.get('Pitch Type')
        throws = p.get('Throws')
        key = (pt or '') + '_' + (throws or '')
        if key not in models:
            continue
        ext = safe_float(p.get('Extension'))
        velo = safe_float(p.get('Velocity'))
        spin, theta = _spin_theta(p, throws)
        if None in (ext, velo, spin, theta):
            continue
        aa = safe_float(p.get('ArmAngle'))
        rz = safe_float(p.get('RelPosZ'))
        rx = safe_float(p.get('RelPosX'))
        s = hand_sign(throws)
        if models[key].get('mlb') and aa is not None:
            by_key.setdefault((key, 'mlb'), []).append((i, aa, 0.0, 0.0, ext, velo, spin, theta, s))
        elif models[key].get('roc') and rz is not None and rx is not None:
            by_key.setdefault((key, 'roc'), []).append((i, 0.0, rz, rx * s, ext, velo, spin, theta, s))
    scored = 0
    for (key, variant), rows in by_key.items():
        A = np.asarray(rows, dtype='f8')
        cols = {'ext': A[:, 4], 'velo': A[:, 5], 'spin': A[:, 6]}
        if variant == 'mlb':
            cols['aa'] = A[:, 1]
        else:
            cols['rz'], cols['rx'] = A[:, 2], A[:, 3]
        X = _design(cols, A[:, 7])
        xi = X @ np.asarray(models[key][variant]['ivb'])
        xh = (X @ np.asarray(models[key][variant]['hb'])) * A[:, 8]
        for r, i in enumerate(A[:, 0].astype(int)):
            all_pitches[i]['_xivb'] = float(xi[r])
            all_pitches[i]['_xhb'] = float(xh[r])
        scored += len(rows)
    return scored


def export(models):
    """JSON-ready copy for metadata_rs.json (coefficients at 6 decimals)."""
    out = {}
    for key, m in models.items():
        out[key] = {}
        for variant, v in m.items():
            out[key][variant] = {
                'terms': TERMS_ROC if variant == 'roc' else TERMS_MLB,
                'ivb': [round(c, 6) for c in v['ivb']],
                'hb': [round(c, 6) for c in v['hb']],
                'n': v['n'],
            }
    return out


# ════════════════════════════════════════════════════════════════════════
# Per-pitch physics expectation (2026-11-19, per Wally). Lives BESIDE the
# hitter basis above; neither replaces the other.
#
# Question it answers: given what a pitch IS at release (velocity, spin rate,
# release spin axis, arm slot, extension), where should it go? No pitch type
# and no pitcher grouping enter, so the expectation of "his sweeper" is only
# the mean over the pitches that carry the name. A rename or a regroup cannot
# move any pitch's expectation, which the per-type basis above cannot say
# (median 5.1 in on a slider-to-sweeper relabel).
#
# Objective: held-out-PITCHER 2D miss of the movement itself, in inches. It is
# not the results test that decides the hitter basis; the two answer different
# questions (scripts/research/xmove/xmove_physics_fit.py holds the search).
#   settings  10 leaves, 200 rounds at learning rate 0.1: every leaves row has
#             an interior optimum in rounds; the curve is FLAT across 5-22
#             leaves at each row's own best rounds (2022: 5.570-5.580 in), and
#             5 leaves is worse in 6/6 seasons at 200 rounds. Min leaf 200 sits
#             on a flat region (20-600).
#   inputs    slot helps (.14 in), one model for both hands on hand-signed
#             inputs helps (.05-.07); release height and side HURT (.02-.03),
#             so they serve only the no-arm-angle fallback; extension is flat.
#             Velocity against the pitcher's own top velocity helps .08-.09 in
#             and is left out on purpose: it reads his OTHER pitches.
#   result    the tuned form beats the untuned one in 6/6 seasons 2021-2026
#             (four never tuned on), 5.3-5.5 in RMSE, R^2 .81 ride / .85 run.
#
# Every pitcher is scored by a model that never saw him: PHYS_FOLDS models,
# each fit without one fold of pitchers (fold = crc32 of the name). One model
# fit on everyone learns the most unusual arms and shortens their arrows (99th
# percentile 2.2 in, max 7.3 in on 2026). A pitcher who is in no training set
# (ROC, the NEW tab, the MiLB corpus) takes his name's fold too; that model
# never saw him either.
#
# The observed tilt (OTilt) and spin efficiency are calculated FROM the
# movement and must never become inputs: expected would equal actual.
#
# The fitted trees are exported as plain arrays and scored with numpy alone
# (`score_physics_all`), in the pipeline and on the cards alike, so a card
# needs neither scikit-learn nor the same version of it. The export equals
# scikit-learn's own predict exactly (xmove_physics_release_checks.py).
# ════════════════════════════════════════════════════════════════════════
import zlib

PHYS_LEAVES = 10
PHYS_ROUNDS = 200
PHYS_LR = 0.1
PHYS_MIN_LEAF = 200
PHYS_FOLDS = 5
PHYS_MIN_TRAIN = 20000          # a guard on the pool, not a tuned value: below it no model is fit
PHYS_TERMS = {'aa': ['velo', 'spin', 'ct', 'st', 'aa', 'ext'],
              'relpt': ['velo', 'spin', 'ct', 'st', 'ext', 'rz', 'rx']}
PHYS_VERSION = 1


def pitcher_fold(name):
    return zlib.crc32(str(name or '').encode('utf-8')) % PHYS_FOLDS


def _phys_frame(all_pitches, mlb_only):
    """Column arrays for the pitches that carry velocity, spin and a release
    axis. NaN marks an absent optional input (arm angle, release point,
    movement); nothing is imputed."""
    idx, cols = [], {k: [] for k in ('fold', 's', 'velo', 'spin', 'theta', 'aa', 'ext', 'rz', 'rx', 'ivb', 'hb')}
    nan = float('nan')
    for i, p in enumerate(all_pitches):
        if mlb_only and p.get('_source', 'MLB') != 'MLB':
            continue
        throws = p.get('Throws')
        if throws not in ('L', 'R'):
            continue
        velo = safe_float(p.get('Velocity'))
        spin = safe_float(p.get('Spin Rate'))
        theta = release_theta(p.get('RTilt'), throws)
        ext = safe_float(p.get('Extension'))
        if None in (velo, spin, theta, ext):
            continue
        s = hand_sign(throws)
        aa = safe_float(p.get('ArmAngle'))
        rz = safe_float(p.get('RelPosZ'))
        rx = safe_float(p.get('RelPosX'))
        ivb = safe_float(p.get('xIndVrtBrk'))
        hb = safe_float(p.get('xHorzBrk'))
        idx.append(i)
        cols['fold'].append(pitcher_fold(p.get('Pitcher')))
        cols['s'].append(s)
        cols['velo'].append(velo)
        cols['spin'].append(spin)
        cols['theta'].append(theta)
        cols['ext'].append(ext)
        cols['aa'].append(nan if aa is None else aa)
        cols['rz'].append(nan if rz is None else rz)
        cols['rx'].append(nan if rx is None else rx * s)
        cols['ivb'].append(nan if ivb is None else ivb)
        cols['hb'].append(nan if hb is None else hb * s)
    F = {k: np.asarray(v, dtype='f8') for k, v in cols.items()}
    F['idx'] = np.asarray(idx, dtype=np.int64)
    F['fold'] = F['fold'].astype(np.int64)
    F['ct'], F['st'] = np.cos(F['theta']), np.sin(F['theta'])
    return F


def _export_trees(model):
    """Plain arrays of a fitted HistGradientBoostingRegressor: the baseline and
    one node table per tree. Inputs never carry a missing value, so the
    missing-value branch is not exported."""
    trees = []
    for (pred,) in model._predictors:
        nd = pred.nodes
        trees.append({'f': nd['feature_idx'].astype(int).tolist(),
                      't': nd['num_threshold'].astype(float).tolist(),
                      'l': nd['left'].astype(int).tolist(),
                      'r': nd['right'].astype(int).tolist(),
                      'v': nd['value'].astype(float).tolist(),
                      'leaf': nd['is_leaf'].astype(int).tolist()})
    return {'base': float(np.ravel(model._baseline_prediction)[0]), 'trees': trees}


def _predict_trees(ex, X):
    out = np.full(len(X), ex['base'], dtype='f8')
    rows = np.arange(len(X))
    for t in ex['trees']:
        f, th, lf, rt = np.asarray(t['f']), np.asarray(t['t']), np.asarray(t['l']), np.asarray(t['r'])
        v, leaf = np.asarray(t['v']), np.asarray(t['leaf'])
        node = np.zeros(len(X), dtype=np.int64)
        live = leaf[node] == 0
        while live.any():
            ix = rows[live]
            n = node[ix]
            node[ix] = np.where(X[ix, f[n]] <= th[n], lf[n], rt[n])
            live = leaf[node] == 0
        out += v[node]
    return out


def fit_physics(all_pitches):
    """PHYS_FOLDS pitcher-held-out models per variant, MLB pitches only.
    Returns {} (and the caller logs it) when the pool is under PHYS_MIN_TRAIN."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    F = _phys_frame(all_pitches, mlb_only=True)
    out = {'version': PHYS_VERSION, 'folds': PHYS_FOLDS, 'variants': {},
           'settings': {'leaves': PHYS_LEAVES, 'rounds': PHYS_ROUNDS, 'lr': PHYS_LR, 'minLeaf': PHYS_MIN_LEAF}}
    has_move = np.isfinite(F['ivb']) & np.isfinite(F['hb'])
    for variant, terms in PHYS_TERMS.items():
        X = np.column_stack([F[c] for c in terms])
        ok = has_move & np.isfinite(X).all(axis=1)
        if ok.sum() < PHYS_MIN_TRAIN:
            continue
        v = {'terms': terms, 'n': int(ok.sum()), 'ivb': [], 'hb': []}
        for fold in range(PHYS_FOLDS):
            tr = ok & (F['fold'] != fold)
            for tgt in ('ivb', 'hb'):
                m = HistGradientBoostingRegressor(max_iter=PHYS_ROUNDS, learning_rate=PHYS_LR, max_leaf_nodes=PHYS_LEAVES,
                                                  min_samples_leaf=PHYS_MIN_LEAF, early_stopping=False, random_state=0)
                m.fit(X[tr], F[tgt][tr])
                v[tgt].append(_export_trees(m))
        out['variants'][variant] = v
    return out if out['variants'] else {}


def score_physics_all(model, all_pitches):
    """Writes '_xivbP' and '_xhbP' (display frame) onto each pitch dict that
    carries the inputs; absent when unscored. Arm-angle variant first, the
    release-point variant only for a pitch with no arm angle. Returns
    (scored, scored through the fallback)."""
    variants = (model or {}).get('variants') or {}
    if not variants:
        return 0, 0
    F = _phys_frame(all_pitches, mlb_only=False)
    n = len(F['idx'])
    xi, xh = np.full(n, np.nan), np.full(n, np.nan)
    todo = np.ones(n, dtype=bool)
    n_fallback = 0
    for variant in ('aa', 'relpt'):
        v = variants.get(variant)
        if not v:
            continue
        X = np.column_stack([F[c] for c in v['terms']])
        use = todo & np.isfinite(X).all(axis=1)
        for fold in range(len(v['ivb'])):
            m = use & (F['fold'] == fold)
            if m.any():
                xi[m] = _predict_trees(v['ivb'][fold], X[m])
                xh[m] = _predict_trees(v['hb'][fold], X[m])
        if variant == 'relpt':
            n_fallback = int(use.sum())
        todo &= ~use
    xh = xh * F['s']
    done = np.isfinite(xi) & np.isfinite(xh)
    for i, a, b in zip(F['idx'][done].tolist(), xi[done].tolist(), xh[done].tolist()):
        all_pitches[i]['_xivbP'] = a
        all_pitches[i]['_xhbP'] = b
    return int(done.sum()), n_fallback
