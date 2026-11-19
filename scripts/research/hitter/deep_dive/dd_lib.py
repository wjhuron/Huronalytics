"""dd_lib.py - shared helpers for the 2026-11 hitter deep dive (frames from dd_build.py)."""
import os, pickle, sys, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
HDD = os.path.join(ROOT, 'data', '_hdd')
SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
PAIRS = [(y, y + 1) for y in SEASONS[:-1]]
W = (0.52, 0.17, 0.31)
N0 = dict(bb=130, sd=190, ct=66)
FLOOR = dict(nbip=30, n_dec=190, n_sw=66)     # research populated rule (shipped floors)
QUAL_PA = 502
_cache = {}


def load(Y):
    if Y not in _cache:
        _cache[Y] = pickle.load(open(os.path.join(HDD, f'pitch_{Y}.pkl'), 'rb'))
        d = _cache[Y]['df']
        d['dv'] = np.where(d.dec == 'swing', d.sw_rv - d.tk_rv, d.tk_rv - d.sw_rv).astype('float32')
        d.loc[~d.sd_el, 'dv'] = np.nan
        hp_x, hp_y = 125.42, 198.27
        ang = np.degrees(np.arctan2(d.hcx - hp_x, hp_y - d.hcy))
        ang = np.where((hp_y - d.hcy) > 0, ang, np.nan)
        d['spray'] = np.where(d.bats == 'L', -ang, ang).astype('float32')   # negative = pull side
    return _cache[Y]


def drop(Y):
    _cache.pop(Y, None)


def sd_raw(d, lgz, key='bid', col='dv'):
    e = d[d.sd_el & d[col].notna()]
    zm = e.groupby([key, 'zone'], observed=True)[col].mean().unstack()
    w = pd.Series(lgz).reindex(zm.columns)
    out = (zm * w).sum(axis=1) / (zm.notna() * w).sum(axis=1)
    return out, e.groupby(key, observed=True).size()


def ct_raw(d, key='bid', pwh='pwh', lev='lev'):
    s = d[d.ct_el & (d[lev] > 0)]
    a = (s[lev] * s.con).groupby(s[key], observed=True).sum()
    x = (s[lev] * (1 - s[pwh])).groupby(s[key], observed=True).sum()
    return a / x, d[d.ct_el].groupby(key, observed=True).size()


def atoms(d, lgz, key='bid'):
    """Per-hitter raw atoms and outcome lines from a pitch frame (or any subset of one)."""
    A = pd.DataFrame(index=pd.Index(d[key].dropna().unique(), name=key))
    A['sd_raw'], A['n_dec'] = sd_raw(d, lgz, key)
    A['ct_raw'], A['n_sw'] = ct_raw(d, key)
    b = d[d.bip]
    g = b.groupby(key, observed=True)
    A['nbip'] = g.size()
    A['xwcon'] = b[b.xw.notna()].groupby(key, observed=True).xw.mean()
    A['ev95'] = b[b.ev.notna()].groupby(key, observed=True).ev.quantile(0.95)
    A['la'] = g.la.mean()
    air = b[b.la >= 20]
    A['n_air'] = air.groupby(key, observed=True).size()
    A['n_pullair'] = (air.spray < -15).groupby(air[key]).sum()
    A['airpull'] = A.n_pullair / A.n_air
    A['pullair_rate'] = A.n_pullair / A.nbip
    A['gb'] = (b.la < 10).groupby(b[key]).mean()
    pa = d[d.wd == 1]
    gp = pa.groupby(key, observed=True)
    A['pa'] = gp.size(); A['woba'] = gp.wv.mean()
    ev = pa.event.astype(str)
    A['k'] = ev.str.contains('strikeout').groupby(pa[key]).mean()
    A['bbr'] = (ev == 'walk').groupby(pa[key]).mean()
    A['hr'] = (ev == 'home_run').groupby(pa[key]).mean()
    # xwOBA at the PA level: Savant xwOBA on BIP (actual value when missing), actual on the rest
    xv = np.where(pa.bip.values & pa.xw.notna().values, pa.xw.values, pa.wv.values)
    A['xwoba'] = pd.Series(xv, index=pa.index).groupby(pa[key]).mean()
    sw = d.dec == 'swing'
    el = d.sd_el
    A['swing'] = (sw & el).groupby(d[key]).sum() / el.groupby(d[key]).sum()
    oz = el & ~d.iz; izm = el & d.iz
    A['chase'] = (sw & oz).groupby(d[key]).sum() / oz.groupby(d[key]).sum()
    A['zswing'] = (sw & izm).groupby(d[key]).sum() / izm.groupby(d[key]).sum()
    A['bats_L'] = (d.bats == 'L').groupby(d[key]).mean()
    for c in ('n_dec', 'n_sw', 'nbip', 'pa'):
        A[c] = A[c].fillna(0)
    return A


def lg_mean(v, w):
    m = v.notna() & (w > 0)
    return float((v[m] * w[m]).sum() / w[m].sum())


def add_plus(A, anc=None, beta_frozen=4.205):
    """BB (prior-free, unshrunk), the unshrunk Process z-composite and the shrunk displayed atoms.
    anc: anchors of another frame (the full season) to score a subset against; None = own pool."""
    own = anc is None
    anc = dict(anc or {})
    pool = A[(A.nbip >= FLOOR['nbip']) & A.xwcon.notna() & A.ev95.notna()]
    if own:
        lgx, lge = lg_mean(pool.xwcon, pool.nbip), lg_mean(pool.ev95, pool.nbip)
        g = pool[pool.nbip >= 80]
        beta = beta_frozen
        if len(g) >= 40:
            x = 100 * g.ev95 / lge; y = 100 * g.xwcon / lgx
            c = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum())
            if 3.0 <= c <= 6.0:
                beta = c
        anc.update(lgx=lgx, lge=lge, beta=beta)
    lgx, lge, beta = anc['lgx'], anc['lge'], anc['beta']
    con = 100 * A.xwcon / lgx; evp = 100 * A.ev95 / lge
    A['con'] = con; A['evc'] = 100 + (evp - 100) * beta
    A['bb_raw'] = 0.6 * A.con + 0.4 * A.evc
    A['bb_shr'] = 0.6 * (A.nbip * A.con + N0['bb'] * 100) / (A.nbip + N0['bb']) + 0.4 * A.evc
    ok = (A.nbip >= FLOOR['nbip']) & (A.n_dec >= FLOOR['n_dec']) & (A.n_sw >= FLOOR['n_sw']) & A.bb_raw.notna() & A.sd_raw.notna() & A.ct_raw.notna()
    A['ok'] = ok
    if own:
        anc.update(lsd=lg_mean(A.sd_raw[ok], A.n_dec[ok]), lct=lg_mean(A.ct_raw[ok], A.n_sw[ok]))
    lsd, lct = anc['lsd'], anc['lct']
    A['sd_shr'] = (A.n_dec * A.sd_raw + N0['sd'] * lsd) / (A.n_dec + N0['sd'])
    A['ct_shr'] = (A.n_sw * A.ct_raw + N0['ct'] * lct) / (A.n_sw + N0['ct'])
    q = ok & (A.pa >= QUAL_PA)
    if q.sum() < 30:
        q = ok & (A.pa >= A.pa[ok].quantile(0.6))
    for pre, srcs in (('z_', (('bb', 'bb_raw'), ('sd', 'sd_raw'), ('ct', 'ct_raw'))), ('zs_', (('bb', 'bb_shr'), ('sd', 'sd_shr'), ('ct', 'ct_shr')))):
        for a, src in srcs:
            if own:
                anc[pre + a] = (float(A.loc[q, src].mean()), float(A.loc[q, src].std()))
            A[pre + a] = (A[src] - anc[pre + a][0]) / anc[pre + a][1]
    A['proc'] = W[0] * A.z_bb + W[1] * A.z_sd + W[2] * A.z_ct
    A['proc_shr'] = W[0] * A.zs_bb + W[1] * A.zs_sd + W[2] * A.zs_ct
    A.loc[~ok, ['proc', 'proc_shr']] = np.nan
    A.attrs['anc'] = anc
    return A


def season_atoms(Y):
    S = load(Y)
    return add_plus(atoms(S['df'], S['lgz']))


def all_atoms(rebuild=False):
    """{Y: full-season atom frame}, cached."""
    f = os.path.join(HDD, 'atoms.pkl')
    if os.path.exists(f) and not rebuild:
        return pickle.load(open(f, 'rb'))
    out = {}
    for Y in SEASONS:
        A = season_atoms(Y); out[Y] = (A, A.attrs['anc']); drop(Y)
    pickle.dump(out, open(f, 'wb'))
    return out


def wcorr(x, y, w=None):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if w is None:
        w = np.ones(len(x))
    w = np.asarray(w, float); m = np.isfinite(x) & np.isfinite(y) & (w > 0)
    x, y, w = x[m], y[m], w[m]
    if len(x) < 8:
        return np.nan
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    cx, cy = x - mx, y - my
    return float((w * cx * cy).sum() / np.sqrt((w * cx * cx).sum() * (w * cy * cy).sum()))


def paired(folds, fa, fb, n_boot=400, seed=0):
    """folds: list of (X-dict-or-frame, y, w). fa/fb: functions frame -> score vector.
    Returns mean r of each, mean delta, bootstrap SE of the mean delta, wins."""
    rng = np.random.default_rng(seed)
    ra, rb, ds, boots = [], [], [], []
    for F in folds:
        a, b, y, w = np.asarray(fa(F), float), np.asarray(fb(F), float), np.asarray(F['y'], float), np.asarray(F['w'], float)
        m = np.isfinite(a) & np.isfinite(b) & np.isfinite(y) & (w > 0)
        a, b, y, w = a[m], b[m], y[m], w[m]
        r1, r2 = wcorr(a, y, w), wcorr(b, y, w)
        ra.append(r1); rb.append(r2); ds.append(r2 - r1)
        n = len(y); bd = []
        for _ in range(n_boot):
            i = rng.integers(0, n, n)
            bd.append(wcorr(b[i], y[i], w[i]) - wcorr(a[i], y[i], w[i]))
        boots.append(bd)
    boots = np.array(boots)
    se = float(np.nanstd(np.nanmean(boots, axis=0)))
    return dict(ra=float(np.mean(ra)), rb=float(np.mean(rb)), d=float(np.mean(ds)), se=se,
                wins=int(sum(d > 0 for d in ds)), n=len(ds), per=[round(float(d), 4) for d in ds])


def fmt(res):
    return f"{res['ra']:.4f} -> {res['rb']:.4f}  d {res['d']:+.4f} (SE {res['se']:.4f}, z {res['d']/res['se'] if res['se'] else float('nan'):+.1f}) wins {res['wins']}/{res['n']} {res['per']}"


def zc(v, ref=None):
    v = np.asarray(v, float); r = v if ref is None else np.asarray(ref, float)
    return (v - np.nanmean(r)) / np.nanstd(r)


def save(name, obj):
    json.dump(obj, open(os.path.join(HDD, name), 'w'), indent=1, default=float)


# ── variant evaluation: swap one atom, keep the other two, shipped weights ──
def _zq(v, q):
    return (v - v[q].mean()) / v[q].std()


def var_folds(AT, kind, var, nvar=None, mode='DESC', min_pa=300, shr=None):
    """kind in ('bb','sd','ct'); var {Y: Series of the raw variant atom by bid}; nvar {Y: Series n} for
    shrinkage in PRED (defaults to the atom's own count column). Returns folds for paired()."""
    ncol = dict(bb='nbip', sd='n_dec', ct='n_sw')[kind]
    shr = (mode == 'PRED') if shr is None else shr
    F = []
    years = SEASONS if mode == 'DESC' else [p[0] for p in PAIRS]
    for Y in years:
        A = AT[Y][0]
        a = A[A.ok & (A.pa >= (min_pa if mode == 'DESC' else 200))]
        v = var[Y].reindex(a.index)
        base_src = dict(bb='bb_raw', sd='sd_raw', ct='ct_raw')[kind]
        b = a[base_src]
        if shr:
            n = (nvar[Y].reindex(a.index) if nvar else a[ncol])
            n0 = N0[kind]
            if kind == 'bb':
                b = a.bb_raw       # BB variants compare unshrunk against unshrunk (other two atoms stay shrunk)
            else:
                v = (n * v + n0 * np.average(v[v.notna()], weights=n[v.notna()])) / (n + n0)
                b = a[dict(sd='sd_shr', ct='ct_shr')[kind]]
        q = (a.pa >= QUAL_PA) & v.notna()
        pre = 'zs_' if shr else 'z_'
        Z = {k: a[pre + k].values for k in ('bb', 'sd', 'ct')}
        zb = dict(Z); zv = dict(Z); zv[kind] = _zq(v, q).values; zb[kind] = _zq(b, q).values
        if mode == 'DESC':
            y, w = a.woba.values, np.ones(len(a))
        else:
            B = AT[Y + 1][0]; y = B.woba.reindex(a.index).values; w = B.pa.reindex(a.index).fillna(0).values
        F.append(dict(base=W[0] * zb['bb'] + W[1] * zb['sd'] + W[2] * zb['ct'], var=W[0] * zv['bb'] + W[1] * zv['sd'] + W[2] * zv['ct'],
                      atom_b=zb[kind], atom_v=zv[kind], y=y, w=w, A=a))
    return F


def eval_var(AT, kind, var, nvar=None, label=''):
    out = {}
    for mode, mp in (('DESC', 300), ('DESC', 100), ('PRED', 200)):
        F = var_folds(AT, kind, var, nvar, mode, mp)
        res = paired(F, lambda f: f['base'], lambda f: f['var'])
        out[f'{mode}{mp}'] = res
        print(f"   {label:26s} {mode} pa>={mp}: {fmt(res)}", flush=True)
    return out


def yy(var, AT=None, min_n=None, ncol=None):
    """mean year-to-year r of a per-season Series dict."""
    rs = []
    for y0, y1 in PAIRS:
        a, b = var[y0], var[y1]
        k = a.dropna().index.intersection(b.dropna().index)
        if AT is not None and ncol:
            k = [i for i in k if AT[y0][0].loc[i, ncol] >= min_n and AT[y1][0].loc[i, ncol] >= min_n]
        rs.append(wcorr(a[k], b[k]))
    return float(np.nanmean(rs)), [round(float(r), 3) for r in rs]
