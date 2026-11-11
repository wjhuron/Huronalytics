"""Which ranker orders free-agent AAA pitchers best, WITHIN role? (2026-11-09, per Wally:
"a deep dive into testing how to optimally rank these players").

Frames: data/_milb_fa/backtest/_bt_pit_h1.csv (bt_run.py), one row per pitcher-season Y with a
primary minor league level; target T_nRA9 = season Y+1 RA9 (sign flipped, higher is better)
over EVERY level he pitched, MLB included, each level translated to the AAA scale, weighted by
Y+1 batters faced (tw). Every Y+1 outcome counts; a pitcher with no Y+1 line cannot be scored.

Pool: primary level AAA, age 25+ (the free-agent shape). Role = SP if starts >= half of games.

Objective: weighted Pearson r of the score with the target, computed WITHIN role (SP and RP
separately; 'within' = both roles demeaned on score and target, then pooled), per held-out
replicate pair. Wally ranks starters and relievers on separate lists, so a ranker that only
sorts the two roles apart must not win. Secondary target: Y+1 translated K-BB%.

Fitted rankers are leave-one-pair-out. Stuff+ / fastball velocity exist for AAA only from 2023
(Hawk-Eye), so every ranker is ALSO scored on the three Stuff+ pairs (2023, 2024, 2025 bases),
trained on the other two of them, so the comparison with Stuff+ is like for like. Stuff+ comes
from rank_stuff_clean.py: a model fit without the target season.

Deltas against the shipped projection carry a paired bootstrap SE (players resampled within
pair). A config is preferred only if it wins most held-out pairs AND the pooled delta clears
about two SE.
    python3 scripts/research/milb_fa/rank_backtest.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_run as BT  # noqa: E402
import bt_features as BF  # noqa: E402

D = os.path.join(BT.ROOT, 'data', '_milb_fa')
K = 25                      # shipped shrinkage pseudo-count (flat 0-50 in bt_run)
STATS = ['K-BB%', 'SwStr%', 'xFIP', 'GB%']
SHIP = ['xall_' + s for s in STATS] + ['isSP', 'age', 'agerel']
B = 1000
STUFF_SRC = os.environ.get('STUFF_SRC', '_rank_stuff_clean.json')   # or _aaa_stuff_shipped.json (leaky check)
OUT = os.path.join(D, '_rank_backtest' + ('' if STUFF_SRC == '_rank_stuff_clean.json' else '_shippedstuff') + '.json')


def frame():
    fr = pd.read_csv(os.path.join(D, 'backtest', '_bt_pit_h1.csv'))
    fr['isSP'] = (fr.role == 'SP').astype(float)
    data = {y: BT.load(y, 'pit') for y in sorted(fr.pair.unique())}
    fr = BF.add_agerel(fr, data)
    fr = BF.add_xallm(fr, STATS + ['nRA9'], data)
    # MLB-only diagnostic target: season Y+1 MLB RA9, weighted by Y+1 MLB batters faced. It
    # conditions on reaching MLB (a target-period gate), so it is a diagnostic, never the objective.
    for y in sorted(fr.pair.unique()):
        n = BT.load(y + 1, 'pit')
        n = n[(n.lvl == 'MLB') & n.nRA9.notna()].groupby('mlbId').apply(
            lambda g: pd.Series({'r': np.average(g.nRA9, weights=g.w), 'w': g.w.sum()}))
        m = fr.pair == y
        fr.loc[m, 'T_mlbRA9'] = fr.loc[m, 'mlbId'].map(n.r)
        fr.loc[m, 'tw_mlb'] = fr.loc[m, 'mlbId'].map(n.w).fillna(0)
    st = json.load(open(os.path.join(D, STUFF_SRC)))
    if 'AAA' in st:                    # aaa_stuff_pass.py format {level: {season: {pid: {v, n}}}}
        st = {y: {k: {'s_r': v['v'], 'fb': None} for k, v in r.items()} for y, r in st['AAA'].items()}
        fb = json.load(open(os.path.join(D, '_rank_stuff_clean.json')))
        for y, r in st.items():
            for k in r:
                r[k]['fb'] = fb.get(y, {}).get(k, {}).get('fb')
    for y, rec in st.items():
        m = fr.pair == int(y)
        ids = fr.loc[m, 'mlbId'].astype(str)
        fr.loc[m, 'stuff'] = ids.map({k: v['s_r'] for k, v in rec.items()})
        fr.loc[m, 'fb'] = ids.map({k: v['fb'] for k, v in rec.items()})
    return fr


def predict(train, test, cols, t, split_role=False):
    """Shipped recipe: one model on cols; a pitcher with MLB time in Y is predicted by the
    same spec on the all-level-WITH-MLB inputs (xallm_). split_role fits SP and RP apart."""
    out = pd.Series(np.nan, index=test.index)
    groups = [('SP', 'RP')] if not split_role else [('SP',), ('RP',)]
    for roles in groups:
        tr, te = train[train.role.isin(roles)], test[test.role.isin(roles)]
        c = [x for x in cols if not (split_role and x == 'isSP')]
        mc = [x.replace('xall_', 'xallm_') for x in c]
        tr0 = tr.dropna(subset=c + mc)
        tr0 = tr0[(tr0.tw > 0) & tr0['T_' + t].notna()]
        te0 = te.dropna(subset=c)
        if len(te0):
            out[te0.index], _ = BT.fit_predict(tr0, te0, c, t, k=K, nkey='nAll')
        tm = te0[te0.mlbN > 0].dropna(subset=mc)
        if len(tm):
            out[tm.index], _ = BT.fit_predict(tr0, tm, mc, t, k=K, nkey='nAll')
    return out


def wr(s, t, w, role):
    """Weighted r within role: demean score and target by role (weighted), then pool."""
    s, t, w = np.asarray(s, float), np.asarray(t, float), np.asarray(w, float)
    m = np.isfinite(s) & np.isfinite(t) & np.isfinite(w) & (w > 0)
    s, t, w, role = s[m], t[m], w[m], np.asarray(role)[m]
    for r in np.unique(role):
        k = role == r
        s[k] -= np.average(s[k], weights=w[k])
        t[k] -= np.average(t[k], weights=w[k])
    return np.sum(w * s * t) / np.sqrt(np.sum(w * s * s) * np.sum(w * t * t))


def score_table(sc, preds, t, pairs, base_name):
    rows = {}
    rng = np.random.default_rng(0)
    for name, col in preds.items():
        rec = {}
        for grp, gm in (('within', None), ('SP', 'SP'), ('RP', 'RP')):
            per, dl = [], []
            for hp in pairs:
                m = (sc.pair == hp) & col.notna() & preds[base_name].notna()
                if gm:
                    m &= sc.role == gm
                d = sc[m]
                r = wr(col[m], d['T_' + t], d.tw, d.role)
                rb = wr(preds[base_name][m], d['T_' + t], d.tw, d.role)
                per.append(r)
                dl.append(r - rb)
            # paired bootstrap of the mean delta: resample players within each pair
            boots = []
            for _ in range(B):
                ds = []
                for hp in pairs:
                    m = (sc.pair == hp) & col.notna() & preds[base_name].notna()
                    if gm:
                        m &= sc.role == gm
                    idx = np.flatnonzero(m.values)
                    i = rng.choice(idx, len(idx))
                    d = sc.iloc[i]
                    ds.append(wr(col.iloc[i], d['T_' + t], d.tw, d.role)
                              - wr(preds[base_name].iloc[i], d['T_' + t], d.tw, d.role))
                boots.append(np.mean(ds))
            rec[grp] = dict(r=[round(x, 3) for x in per], mean=round(float(np.mean(per)), 3),
                            d=round(float(np.mean(dl)), 3), se=round(float(np.std(boots)), 3),
                            wins=int(sum(x > 0 for x in dl)))
        rows[name] = rec
    return rows


def show(title, rows, pairs):
    print(f'\n== {title} (pairs {pairs}) ==')
    print(f'{"ranker":44s} {"within r":>8s} {"d vs ship":>9s} {"SE":>5s} {"wins":>4s} | '
          f'{"SP r":>6s} {"d":>6s} {"SE":>5s} {"w":>2s} | {"RP r":>6s} {"d":>6s} {"SE":>5s} {"w":>2s}')
    for name, rec in rows.items():
        a, s, r = rec['within'], rec['SP'], rec['RP']
        print(f'{name:44s} {a["mean"]:8.3f} {a["d"]:+9.3f} {a["se"]:5.3f} {a["wins"]:>2d}/{len(pairs)} | '
              f'{s["mean"]:6.3f} {s["d"]:+6.3f} {s["se"]:5.3f} {s["wins"]:>2d} | '
              f'{r["mean"]:6.3f} {r["d"]:+6.3f} {r["se"]:5.3f} {r["wins"]:>2d}')


def main():
    fr = frame()
    pool = fr[(fr.lvl == 'AAA') & (fr.age >= 25)]
    out = {}
    for t in os.environ.get('TARGETS', 'nRA9,K-BB%,mlbRA9').split(','):
        if t == 'mlbRA9':
            # the fits still learn the all-level RA9; only the scoring moves to MLB innings
            pool = pool.assign(tw_all=pool.tw)
            sc = pool[(pool.tw_mlb > 0) & pool.T_mlbRA9.notna() & (pool.tw > 0)].dropna(subset=SHIP).copy()
            fit_t = 'nRA9'
        else:
            sc = pool[(pool.tw > 0) & pool['T_' + t].notna()].dropna(subset=SHIP).copy()
            fit_t = t
        # ---- part 1: box-score rankers, all five pairs, trained on the other four (full frame) ----
        cands = {
            'SHIPPED projection': (SHIP, False),
            'raw K-BB% (translated, all levels)': (['xall_K-BB%'], None),
            'SHIPPED + own RA9': (SHIP + ['xall_nRA9'], False),
            'SHIPPED, separate SP / RP fits': (SHIP, True),
            'K-BB% + SwStr% only': (['xall_K-BB%', 'xall_SwStr%', 'isSP'], False),
        }
        pairs = sorted(sc.pair.unique())
        train_all = fr[(fr.tw > 0)]
        preds = {}
        for name, (cols, split) in cands.items():
            col = pd.Series(np.nan, index=sc.index)
            for hp in pairs:
                te = sc[sc.pair == hp]
                if split is None:
                    col[te.index] = te[cols[0]]
                else:
                    col[te.index] = predict(train_all[train_all.pair != hp], te, cols, fit_t, split)
            preds[name] = col
        if t == 'mlbRA9':
            sc = sc.assign(tw=sc.tw_mlb)
        rows = score_table(sc, preds, t, pairs, 'SHIPPED projection')
        show(f'target {t}: box-score rankers, n={len(sc)}', rows, pairs)
        out[f'{t}|boxscore'] = rows
        # ---- part 2: Stuff+ pairs, every ranker trained on the OTHER Stuff+ pairs only ----
        s3 = sc[sc.stuff.notna() & sc.fb.notna()].copy()
        sp = sorted(s3.pair.unique())
        cov = {int(p): f'{(sc[sc.pair == p].stuff.notna()).mean():.1%}' for p in sp}
        tr3 = fr[(fr.tw > 0) & fr.pair.isin(sp)]
        c2 = {
            'SHIPPED projection': (SHIP, False),
            'raw K-BB% (translated, all levels)': (['xall_K-BB%'], None),
            'Stuff+ alone': (['stuff'], None),
            'SHIPPED + Stuff+': (SHIP + ['stuff'], False),
            'SHIPPED + fastball velo': (SHIP + ['fb'], False),
            'SHIPPED + Stuff+ + fastball velo': (SHIP + ['stuff', 'fb'], False),
            'SHIPPED + Stuff+, separate SP / RP fits': (SHIP + ['stuff'], True),
            'K-BB% + SwStr% + Stuff+': (['xall_K-BB%', 'xall_SwStr%', 'isSP', 'stuff'], False),
            'K-BB% + Stuff+': (['xall_K-BB%', 'isSP', 'stuff'], False),
        }
        p2 = {}
        for name, (cols, split) in c2.items():
            col = pd.Series(np.nan, index=s3.index)
            for hp in sp:
                te = s3[s3.pair == hp]
                if split is None:
                    col[te.index] = te[cols[0]]
                else:
                    col[te.index] = predict(tr3[tr3.pair != hp].dropna(subset=['stuff', 'fb']), te, cols, fit_t, split)
            p2[name] = col
        # convention comparator, no fit: equal-weight z of K-BB% and Stuff+ within pair and role
        z = pd.Series(np.nan, index=s3.index)
        for (hp, rl), g in s3.groupby(['pair', 'role']):
            z[g.index] = ((g['xall_K-BB%'] - g['xall_K-BB%'].mean()) / g['xall_K-BB%'].std()
                          + (g.stuff - g.stuff.mean()) / g.stuff.std())
        p2['z(K-BB%) + z(Stuff+), equal weight'] = z
        if t == 'mlbRA9':
            s3 = s3.assign(tw=s3.tw_mlb)
        rows2 = score_table(s3, p2, t, sp, 'SHIPPED projection')
        show(f'target {t}: Stuff+ pairs, n={len(s3)}, Stuff+ coverage {cov}', rows2, sp)
        out[f'{t}|stuff'] = rows2
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)


if __name__ == '__main__':
    main()
