"""How to rank the free agents the shipped projection does not cover (2026-11-09): pitchers
whose base season is mostly MLB (bt_run skips them) and pitchers under the 75-TBF gate.

Same objective and target as rank_backtest.py: within-role weighted r with season Y+1 RA9
(all levels, translated to AAA, sign flipped, weighted by Y+1 batters faced), leave-one-pair-
out over 2021->22 .. 2025->26. Features are the all-level translated averages WITH the MLB rows
(xallm_), shrunk by k on all-level TBF as shipped.

Groups scored (base season Y):
  MLB-primary : more TBF in MLB than in the minors, MLB TBF under 250 (about 60 IP), 30+ total
  small MiLB  : minor-league primary, 30-74 TBF at every level (under the shipped gate), reached AAA
Rankers: the shipped spec on xallm_ (fit on THIS frame), raw translated K-BB%, and for the
MLB-primary group the target-free MLB Stuff+ (data/_proj/_stuff_clean.json: season Y graded by
a model fit without Y+1), alone and added to the spec, on the pairs where it exists.
    python3 scripts/research/milb_fa/rank_small.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_run as BT  # noqa: E402
from rank_backtest import wr  # noqa: E402

STATS = ['K-BB%', 'SwStr%', 'xFIP', 'GB%', 'nRA9']
SPEC = ['xallm_K-BB%', 'xallm_SwStr%', 'xallm_xFIP', 'xallm_GB%', 'isSP', 'age']
K = 25                      # MLB-primary interior optimum (k sweep 2026-11-09: 10-50 per pair)
K_SMALL = 800               # small AAA samples: interior optimum, 400-1600 near flat, beats 25 in 4/5 pairs


def fit_predict_m(train, test, cols, t, k):
    """bt_run.fit_predict on this frame, where nAll already counts the MLB rows. bt_run did not
    shrink xallm_ inputs until 2026-11-09; it now does, on nAll + mlbN."""
    sh = [c for c in cols if c.startswith(('x_', 'xall_', 'xallm_'))]
    tr = train.dropna(subset=cols + ['T_' + t])
    tr = tr[tr.tw > 0]
    mu = {c: np.average(tr[c], weights=tr.tw) for c in sh}

    def shrink(df):
        out = df[cols].copy()
        if k:
            f = df.nAll / (df.nAll + k)
            for c in sh:
                out[c] = mu[c] + (df[c] - mu[c]) * f
        return out
    X = np.column_stack([np.ones(len(tr))] + [shrink(tr)[c] for c in cols])
    sw = np.sqrt(tr.tw.values)
    beta = np.linalg.lstsq(X * sw[:, None], tr['T_' + t].values * sw, rcond=None)[0]
    return np.column_stack([np.ones(len(test))] + [shrink(test)[c] for c in cols]) @ beta, beta
OUT = os.path.join(BT.ROOT, 'data', '_milb_fa', '_rank_small.json')


def heldout_bias(fr, mask, k):
    """Mean held-out (target - prediction) for one group, per pair and pooled. The r objective
    scores order WITHIN a group; a list that mixes groups also needs their levels to agree."""
    train = fr[(fr.tw > 0) & fr.T_nRA9.notna()].dropna(subset=SPEC)
    sc = fr[mask & (fr.tw > 0) & fr.T_nRA9.notna()].dropna(subset=SPEC)
    res = []
    for hp in sorted(sc.pair.unique()):
        te = sc[sc.pair == hp]
        p, _ = fit_predict_m(train[train.pair != hp], te, SPEC, 'nRA9', k)
        res.append(float(np.average(te.T_nRA9 - p, weights=te.tw)))
    return float(np.mean(res)), res


def build():
    data = {y: BT.load(y, 'pit') for y in BT.YEARS}
    offs = {y: {s: BT.offsets(data[y], s)[0] for s in STATS} for y in BT.YEARS}
    rows = []
    for y in list(BT.YEARS)[:-1]:
        base, nxt = data[y], data[y + 1]
        n2 = nxt[nxt.nRA9.notna()].assign(x=lambda q: (q.nRA9 - q.lvl.map(offs[y + 1]['nRA9'])) * q.w)
        tgt = n2.groupby('mlbId')[['x', 'w']].sum().pipe(lambda q: q.x / q.w)
        tk = nxt[nxt['K-BB%'].notna()].assign(x=lambda q: (q['K-BB%'] - q.lvl.map(offs[y + 1]['K-BB%'])) * q.w)
        tgk = tk.groupby('mlbId')[['x', 'w']].sum().pipe(lambda q: q.x / q.w)
        tw = nxt.groupby('mlbId').w.sum()
        for mid, g in base.groupby('mlbId'):
            mlb = g[g.lvl == 'MLB'].w.sum()
            mi = g[g.lvl != 'MLB']
            tot = g.w.sum()
            if tot < 30:
                continue
            if mlb > mi.w.sum():
                grp = 'MLB-primary' if mlb < 250 else None
            else:
                grp = 'small MiLB' if (mi.w.max() < BT.MIN['pit']) else 'gated MiLB'
            if grp is None:
                continue
            gg = g[['G', 'GS']].sum()
            top = mi.assign(_r=mi.lvl.map(BT.RANK)).sort_values('_r').lvl.iloc[0] if len(mi) else 'MLB'
            rec = {'pair': y, 'mlbId': mid, 'grp': grp, 'nAll': tot, 'mlbN': mlb, 'top': top,
                   'age': g.Age.dropna().iloc[0] if g.Age.notna().any() else np.nan,
                   'role': 'SP' if gg.G and gg.GS / gg.G >= BT.SP_GS_SHARE else 'RP',
                   'tw': tw.get(mid, 0), 'T_nRA9': tgt.get(mid, np.nan), 'T_K-BB%': tgk.get(mid, np.nan)}
            for s in STATS:
                q = g[g[s].notna()]
                rec['xallm_' + s] = (np.average(q[s] - q.lvl.map(offs[y][s]), weights=q.w) if len(q) else np.nan)
            rows.append(rec)
    fr = pd.DataFrame(rows)
    fr['isSP'] = (fr.role == 'SP').astype(float)
    st = json.load(open(os.path.join(BT.ROOT, 'data', '_proj', '_stuff_clean.json')))
    for y in sorted(fr.pair.unique()):
        rec = st.get(str(y + 1), {}).get(str(y), {})
        m = fr.pair == y
        fr.loc[m, 'mstuff'] = fr.loc[m, 'mlbId'].astype(str).map({k: v['s_r'] for k, v in rec.items()})
    return fr


def main():
    fr = build()
    print(fr.groupby(['grp', 'pair']).size().unstack())
    train = fr[(fr.tw > 0) & fr.T_nRA9.notna()].dropna(subset=SPEC)
    out = {}
    for t in ('nRA9', 'K-BB%'):
        for grp in ('MLB-primary', 'small MiLB'):
            sc = fr[(fr.grp == grp) & (fr.tw > 0) & fr['T_' + t].notna()].dropna(subset=SPEC)
            if grp == 'small MiLB':
                sc = sc[sc.top == 'AAA']       # the free-agent shape: AAA time on a small sample
            pairs = sorted(sc.pair.unique())
            P = {}
            col = pd.Series(np.nan, index=sc.index)
            for hp in pairs:
                te = sc[sc.pair == hp]
                tr = train[(train.pair != hp)]
                tr = tr[tr['T_' + t].notna()]
                col[te.index], _ = fit_predict_m(tr, te, SPEC, t, K_SMALL if grp == 'small MiLB' else K)
            P['projection spec (xallm)'] = col
            P['raw K-BB% (translated)'] = sc['xallm_K-BB%']
            P['raw own RA9 (translated)'] = sc['xallm_nRA9']
            res = {}
            for name, c in P.items():
                res[name] = [round(wr(c[sc.pair == hp], sc.loc[sc.pair == hp, 'T_' + t], sc.loc[sc.pair == hp, 'tw'],
                                      sc.loc[sc.pair == hp, 'role']), 3) for hp in pairs]
            if grp == 'MLB-primary':
                s2 = sc[sc.mstuff.notna()]
                sp = sorted(s2.pair.unique())
                c2 = pd.Series(np.nan, index=s2.index)
                tr2 = train[train.mstuff.notna()]
                for hp in sp:
                    te = s2[s2.pair == hp]
                    tr = tr2[(tr2.pair != hp) & tr2['T_' + t].notna()]
                    c2[te.index], _ = fit_predict_m(tr, te, SPEC + ['mstuff'], t, K)
                c1 = pd.Series(np.nan, index=s2.index)
                for hp in sp:
                    te = s2[s2.pair == hp]
                    tr = tr2[(tr2.pair != hp) & tr2['T_' + t].notna()]
                    c1[te.index], _ = fit_predict_m(tr, te, SPEC, t, K)
                for name, c in (('spec, Stuff+ subset', c1), ('spec + MLB Stuff+', c2), ('MLB Stuff+ alone', s2.mstuff)):
                    res[name] = [round(wr(c[s2.pair == hp], s2.loc[s2.pair == hp, 'T_' + t], s2.loc[s2.pair == hp, 'tw'],
                                          s2.loc[s2.pair == hp, 'role']), 3) for hp in sp]
                print(f'  {grp} Stuff+ subset n={len(s2)} pairs {sp}')
            print(f'\n== target {t}, {grp}, n={len(sc)}, pairs {pairs} ==')
            for name, v in res.items():
                print(f'  {name:32s} mean {np.mean(v):.3f}  per pair {v}')
            out[f'{t}|{grp}'] = res
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), indent=1)
    os.replace(tmp, OUT)


if __name__ == '__main__':
    main()
