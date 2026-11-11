"""Every free-agent pitcher on one list, in tiers (2026-11-11, per Wally: "rank every single
pitcher, not just the targets. put them in tiers", "if players do not have enough data/sample,
note that", plus the pre-10/28 released / elected-FA pitchers with 2026 MLB time).

Pool: every pitcher in ~/Downloads/stuff/milb_fa_2026_pitchers.csv who is still free
(data/_milb_fa/not_free.csv, then the MLB transactions API since 2026-11-09), plus
data/_milb_fa/mlb_adds.csv (mlb_released_adds.py: last move before 2026-10-28, 2026 MLB time
in Sheets).

Projection (next-season RA9 on the MLB scale): ONE model for everyone, the xallm spec of
rank_small.py (K-BB%, SwStr%, xFIP, GB% over every level, MLB included, translated to AAA;
role; age; k 25, small samples k 800) FIT ON THE FREE-AGENT POOL ONLY (age 25+, AAA top level
or mostly MLB, 250+ MLB BF included). rank_sample_check.py part F: the all-level fit gave age
.09-.13 runs a year, partly measuring level; the pool fit gives .03 and orders a mixed list
better (5/5 pairs, +.006 r, 3.7 SE). The shipped projection is not used because it carries the
all-level age slope. Then the per-group MIXED-LIST CALIBRATION (target = a + s * prediction,
groups: no MLB, MLB under half, mostly MLB, 250+ MLB, small minor sample), fit in part F and
read from data/_milb_fa/_rank_sample_check.json.
Prior seasons are NOT used (part B/C: under 2 SE where it would apply, lost to shipped).

Scope: pitchers with 2026 MLB or AAA batters faced only; under MIN_MLBAAA MLB + AAA BF they are
listed at the end without a tier. Tiers: natural breaks in projected RA9 within role (SP if
starts are 40%+ of 2026 AAA + MLB games), N_TIERS each, the MLB free-agent class ranked but not
tiered. The tier count is a CONVENTION.

P(MLB deal) (deal_prob.py): the contract model's probability of a guaranteed MLB deal, blank under
20 MLB innings 2024-2026 (out of the model's range). Pitchers at 1.00 are removed before tiering.

Writes ~/Downloads/milb_fa_pitcher_tiers_2026-11-11.csv.
    python3 scripts/research/milb_fa/rank_all.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_run as BT  # noqa: E402
import rank_small as RS  # noqa: E402
from mlb_released_adds import mlb_lines, signed_since  # noqa: E402
from deal_prob import p_mlb_deal  # noqa: E402

CERTAIN = 0.995
from rank_live import disp  # noqa: E402
from rank_sample_check import build_big  # noqa: E402

D = os.path.join(BT.ROOT, 'data', '_milb_fa')
OUT = os.path.expanduser('~/Downloads/milb_fa_pitcher_tiers_2026-11-11.csv')
# Scope (Wally, 2026-11-11): rank only pitchers with 2026 MLB or AAA batters faced; a pitcher
# whose MLB + AAA sample is under MIN_MLBAAA is listed at the END, not tiered. 100 BF is a
# CONVENTION taken from the low end of the measured raw K-BB% break-even (100-145 BF,
# card_min_breakeven.py); the projection has no cliff there (held-out r .31 at 30-99 total BF).
# The projection still reads every level he pitched at; only the gate looks at MLB + AAA.
MIN_MLBAAA = 100
# Calibration (a, s) per group, target and prediction in AAA nRA9 units: rank_sample_check.py
# part F (the POOL-FIT spec, 2026-11-11), read from its JSON so no constant is copied by hand.
# Part F refused to adopt -> stop rather than fall back.
_SC = json.load(open(os.path.join(D, '_rank_sample_check.json')))
if not _SC.get('F_age_pool', {}).get('adopt'):
    sys.exit('rank_sample_check.py part F did not adopt the pool fit; rerun it before ranking')
CAL = {k: tuple(v) for k, v in _SC['F_age_pool']['cal_pool_fit'].items()}
# Tiers: natural breaks in projected RA9 within each role (optimal 1-D partition, minimum
# within-tier squared deviation), N_TIERS per role. The count is a CONVENTION matching the
# earlier chat list Wally found easy to read; no objective sets it.
N_TIERS = 7
ORDER = ['MLB', 'AAA', 'AA', 'A+', 'A']


def pitch_metrics(ids, mlb_team):
    """Tracked pitch metrics per pitcher, MLB and AAA only (Single-A tracking is ignored, per
    Wally). Every grade reads on the MLB ruler so the two levels compare.
      AAA: data/_milb2026/pitcher_pool_AAA.json (AAA regular season, corpus tags). Its per-type
           grades are on the AAA ruler; the pool's own per-type shift puts them back on MLB.
      MLB: the Sheets season leaderboards (pitcher and pitch rows), the combined row when the
           pitcher had one."""
    import json
    pool = json.load(open(os.path.join(BT.ROOT, 'data', '_milb2026', 'pitcher_pool_AAA.json')))
    sh = pool['shift']
    lb = pd.DataFrame(json.load(open(os.path.join(BT.ROOT, 'data', 'pitcher_leaderboard_rs.json'))))
    pt = pd.DataFrame(json.load(open(os.path.join(BT.ROOT, 'data', 'pitch_leaderboard_rs.json'))))
    lb = lb.set_index(['mlbId', 'team'])
    ptg = {k: g for k, g in pt.groupby(['mlbId', 'team'])}

    def fmt(t, usage, velo, st, lo):
        parts = [t, f'{velo:.1f}' if pd.notna(velo) else '', f'{usage:.0%}']
        if pd.notna(st):
            parts.append(f'St {st:.0f}')
        if pd.notna(lo):
            parts.append(f'Loc {lo:.0f}')
        return ' '.join(x for x in parts if x)
    out = {}
    for mid in ids:
        r = {}
        a = pool['pitchers'].get(str(mid))
        if a:
            r.update({'AAA_pitches': a.get('count'), 'AAA_Stuff+': a.get('stuffScoreMLB'),
                      'AAA_Loc+': a.get('locPlusMLB'), 'AAA_FBvelo': a.get('fbVelo'),
                      'AAA_Ext': a.get('extension'), 'AAA_SwStr%': a.get('swStrPct'),
                      'AAA_Chase%': a.get('chasePct'), 'AAA_IZWhiff%': a.get('izWhiffPct'),
                      'AAA_GB%': a.get('gbPct')})
            ty = pool['pitchTypes'].get(str(mid), {})
            n = sum(v['count'] for v in ty.values()) or 1
            r['AAA_arsenal'] = '; '.join(
                fmt(t, v['count'] / n, v.get('velocity'),
                    v['stuffScore'] + sh['stuff'].get(t, 0) if v.get('stuffScore') is not None else np.nan,
                    v['locPlus'] + sh['loc'].get(t, 0) if v.get('locPlus') is not None else np.nan)
                for t, v in sorted(ty.items(), key=lambda kv: -kv[1]['count']) if v['count'] / n >= 0.02)
        tm = mlb_team.get(mid)
        if tm is not None and (mid, tm) in lb.index:
            m = lb.loc[(mid, tm)]
            r.update({'MLB_pitches': m.get('count'), 'MLB_Stuff+': m.get('stuffScore'),
                      'MLB_Loc+': m.get('locPlus'), 'MLB_SwStr%': m.get('swStrPct'),
                      'MLB_Chase%': m.get('chasePct'), 'MLB_GB%': m.get('gbPct')})
            g = ptg.get((mid, tm))
            if g is not None:
                g = g.sort_values('count', ascending=False)
                n = g['count'].sum() or 1
                r['MLB_arsenal'] = '; '.join(fmt(x.pitchType, x['count'] / n, x.velocity, x.stuffScore, x.locPlus)
                                             for _, x in g.iterrows() if x['count'] / n >= 0.02)
        out[mid] = r
    return pd.DataFrame.from_dict(out, orient='index')


def natural_breaks(x, k):
    """Tier labels 1..k for sorted values x: the partition into k contiguous groups with the
    least total within-group squared deviation (Fisher's exact 1-D method)."""
    x = np.asarray(x, float)
    n = len(x)
    k = min(k, n)
    cs, cs2 = np.concatenate([[0], np.cumsum(x)]), np.concatenate([[0], np.cumsum(x * x)])

    def sse(i, j):            # x[i:j]
        m = j - i
        return cs2[j] - cs2[i] - (cs[j] - cs[i]) ** 2 / m
    cost = np.full((k + 1, n + 1), np.inf)
    back = np.zeros((k + 1, n + 1), int)
    cost[0, 0] = 0
    for t in range(1, k + 1):
        for j in range(t, n + 1):
            best, arg = np.inf, t - 1
            for i in range(t - 1, j):
                c = cost[t - 1, i] + sse(i, j)
                if c < best:
                    best, arg = c, i
            cost[t, j], back[t, j] = best, arg
    lab = np.zeros(n, int)
    j = n
    for t in range(k, 0, -1):
        i = back[t, j]
        lab[i:j] = t
        j = i
    return lab


def main():
    csv = pd.read_csv(os.path.expanduser('~/Downloads/stuff/milb_fa_2026_pitchers.csv'))
    nf = pd.read_csv(os.path.join(D, 'not_free.csv')).set_index('mlbId')
    ma = pd.read_csv(os.path.join(D, 'mlb_adds.csv'))
    ma = ma[ma.signedSince.isna()]
    base = csv.drop_duplicates('mlbId').set_index('mlbId')
    ids = [i for i in base.index if i in nf.index and not bool(nf.loc[i, 'notFree'])]
    names = {i: base.loc[i, 'Name'] for i in ids}
    names.update({int(r.mlbId): disp(r.Player) for r in ma.itertuples()})
    moved = signed_since(set(names))
    for i in moved:
        names.pop(i, None)
    print(f'pool: {len(ids)} free in the FA CSV + {len(ma)} MLB adds; {len(moved)} signed since 11-09 '
          f'({", ".join(moved.values()) or "none"}); {len(names)} pitchers')

    data = BT.load(2026, 'pit')
    offs = {s: BT.offsets(data, s)[0] for s in RS.STATS}
    sheet = mlb_lines().set_index('mlbId')
    rows = []
    for mid, nm in names.items():
        g = data[data.mlbId == mid]
        mi = g[g.lvl != 'MLB']
        rec = {'mlbId': mid, 'Name': nm, 'nAll': g.w.sum(), 'mlbN': g[g.lvl == 'MLB'].w.sum(),
               'minorMax': mi.w.max() if len(mi) else 0.0,
               'mlbaaaN': g[g.lvl.isin(['MLB', 'AAA'])].w.sum(),
               'age': g.Age.dropna().iloc[0] if g.Age.notna().any() else base.Age.get(mid, np.nan)}
        gg = g[g.lvl.isin(['AAA', 'MLB'])][['G', 'GS']].sum()
        if not gg.G:
            gg = g[['G', 'GS']].sum()
        rec['gs_share'] = gg.GS / gg.G if gg.G else np.nan
        rec['isSP'] = float(bool(gg.G) and gg.GS / gg.G >= BT.SP_GS_SHARE)
        rec['Role'] = 'SP' if gg.G and gg.GS / gg.G >= 0.4 else 'RP'
        for s in RS.STATS:
            q = g[g[s].notna()]
            rec['xallm_' + s] = np.average(q[s] - q.lvl.map(offs[s]), weights=q.w) if len(q) else np.nan
        per = g.groupby('lvl').w.sum()
        rec['Levels2026'] = ', '.join(f'{l} {int(per[l])}' for l in ORDER if l in per)
        rec['SheetsMLB_BF'] = sheet.MLB_TBF.get(mid, 0)
        rec['MLB_Stuff+'] = sheet['MLB_Stuff+'].get(mid, np.nan)
        rec['AAA_Stuff+'] = base['AAA_Stuff+'].get(mid, np.nan) if 'AAA_Stuff+' in base else np.nan
        rows.append(rec)
    f = pd.DataFrame(rows)
    dropped = f[f.mlbaaaN <= 0]
    print(f'scope: {len(dropped)} pitchers with no 2026 MLB or AAA batters faced left out; '
          f'{len(f) - len(dropped)} kept')
    f = f[f.mlbaaaN > 0].reset_index(drop=True)
    f['small'] = (f.minorMax < BT.MIN['pit']) & (f.mlbN <= f.nAll - f.mlbN)
    f['G'] = np.select([f.small, f.mlbN == 0, f.mlbN <= f.nAll / 2, f.mlbN >= 250],
                       ['small', 'noMLB', 'MLBminor', 'MLBbig'], 'MLBprimary')

    # base prediction in AAA nRA9 units: shipped where it exists, else the xallm spec
    # POOL FIT (part F): train only on the free-agent shape, age 25+, AAA top level or mostly MLB
    # (250+ MLB BF included); the all-level fit's age slope partly measured level
    fr = pd.concat([RS.build(), build_big()], ignore_index=True)
    fr['top'] = fr['top'].fillna('MLB')
    tr = fr[(fr.tw > 0) & fr.T_nRA9.notna() & (fr.age >= 25)
            & ((fr.top == 'AAA') | fr.grp.isin(['MLB-primary', 'MLB-big']))].dropna(subset=RS.SPEC)
    ok = f.dropna(subset=RS.SPEC)
    f.loc[ok.index, 'p_x'], beta = RS.fit_predict_m(tr, ok, RS.SPEC, 'nRA9', RS.K)
    print('pool-fit spec', dict(zip(['const'] + RS.SPEC, np.round(beta, 3))))
    sm = ok[f.loc[ok.index, 'small']]
    if len(sm):
        f.loc[sm.index, 'p_x'], _ = RS.fit_predict_m(tr, sm, RS.SPEC, 'nRA9', RS.K_SMALL)
    off = offs['nRA9']['MLB']
    # one model for everyone: the shipped projection carries the all-level age slope too
    f['p'] = f.p_x
    f['Source'] = np.where(f.p_x.notna(), 'pool-fit spec', 'none')
    a = f.G.map(lambda g: CAL[g][0])
    s = f.G.map(lambda g: CAL[g][1])
    f['projRA9_uncal'] = -(f.p + off)
    f['projRA9'] = -(a + s * f.p + off)

    # sheets vs FanGraphs MLB batters faced
    dis = f[(f.SheetsMLB_BF - f.mlbN).abs() > 5]
    print(f'MLB BF, Sheets vs FanGraphs: {len(dis)} pitchers differ by more than 5 BF')
    if len(dis):
        print(dis[['Name', 'SheetsMLB_BF', 'mlbN']].to_string(index=False))

    notes = []
    for r in f.itertuples():
        n = []
        if r.Source == 'none':
            n.append('NO PROJECTION: no 2026 line at MLB, AAA, AA, A+ or A')
        elif r.mlbaaaN < MIN_MLBAAA:
            n.append(f'not enough MLB/AAA data ({int(r.mlbaaaN)} BF, under {MIN_MLBAAA})')
        elif r.mlbaaaN < 150:
            n.append(f'thin MLB/AAA sample ({int(r.mlbaaaN)} BF)')
        if r.G in ('MLBminor', 'MLBprimary', 'MLBbig'):
            n.append('MLB time: projection pulled toward average')
        if r.small and r.nAll >= 30:
            n.append('heavy shrinkage (under 75 BF at every minor level)')
        notes.append('; '.join(n))
    f['Note'] = notes
    # P(MLB deal) (deal_prob.py, 2026-11-11, per Wally: "remove any guy you think is 100%"). A
    # pitcher at CERTAIN or above is gone before tiering: he is not a depth signing. CERTAIN is
    # the probability that prints as 1.00 at two decimals, read literally from "100%".
    f = f.join(p_mlb_deal(f)[['p_mlb']])
    gone = f[f.p_mlb >= CERTAIN]
    print(f'removed {len(gone)} at P(MLB deal) >= {CERTAIN}: {", ".join(gone.Name)}')
    f = f[~(f.p_mlb >= CERTAIN)].reset_index(drop=True)
    # MLB free-agent class: elected free agency at the MLB level on or after 2026-10-28 (the
    # six-year and outrighted class). They stay on the list and in RoleRank but are not tiered
    # with the depth pool, so they do not take its tier-1 slots.
    res = pd.read_csv(os.path.join(D, 'resolved.csv'), dtype={'mlbId': 'Int64'})
    lastr = res[res.mlbId.notna()].sort_values('Date').groupby('mlbId').tail(1).set_index('mlbId')
    mlbclass = set(lastr[(lastr.Date >= '2026-10-28') & (lastr.Level == 'MLB')
                         & (lastr['Transaction Type'] == 'elected free agency')].index)
    f['MLBclass'] = f.mlbId.isin(mlbclass)
    f['tiered'] = (f.Source != 'none') & (f.mlbaaaN >= MIN_MLBAAA)
    f['Tier'] = ''
    f['RoleRank'] = np.nan
    for role, g in f[f.tiered].groupby('Role'):
        g = g.sort_values('projRA9')
        f.loc[g.index, 'RoleRank'] = np.arange(1, len(g) + 1)
        d = g[~g.MLBclass]
        f.loc[d.index, 'Tier'] = natural_breaks(d.projRA9.values, N_TIERS)
        f.loc[g.index[g.MLBclass], 'Tier'] = 'MLB FA'
    f['MLBadd'] = f.mlbId.isin(ma.mlbId)
    last = {int(r.mlbId): f"{r.lastMoveDate} {r.lastMove} ({r.lastMoveTeam})" for r in ma.itertuples()}
    f['LastMove'] = [last.get(i) or nf.lastListMove.get(i, '') for i in f.mlbId]
    f.loc[f.MLBclass, 'Note'] = (f.loc[f.MLBclass, 'Note'] + '; MLB free-agent class (elected at MLB level on/after 10/28): ranked, not tiered').str.lstrip('; ')
    f.loc[~f.tiered & (f.Source != 'none'), 'Tier'] = 'not enough MLB/AAA data'
    f.loc[~f.tiered, 'RoleRank'] = np.nan
    f.loc[f.Source == 'none', 'Tier'] = 'no projection'
    pm = pitch_metrics(list(f.mlbId), sheet.mlbTeam.to_dict())
    for c in [c for c in ('AAA_Stuff+', 'MLB_Stuff+') if c in f]:
        f = f.drop(columns=c)
    f = f.join(pm, on='mlbId')
    for c in ('AAA_SwStr%', 'AAA_Chase%', 'AAA_IZWhiff%', 'AAA_GB%', 'MLB_SwStr%', 'MLB_Chase%', 'MLB_GB%'):
        if c in f:
            f[c] = (100 * pd.to_numeric(f[c], errors='coerce')).round(1)
    for c in ('AAA_Stuff+', 'AAA_Loc+', 'MLB_Stuff+', 'MLB_Loc+'):
        if c in f:
            f[c] = pd.to_numeric(f[c], errors='coerce').round(0)
    nt = f[(f.mlbaaaN > 0) & f.get('AAA_arsenal', pd.Series(index=f.index)).isna() & f.get('MLB_arsenal', pd.Series(index=f.index)).isna()]
    print(f'pitch metrics: {len(f) - len(nt)} of {len(f)} have MLB or AAA tracking; none for {len(nt)}: '
          f'{", ".join(nt.Name.head(15))}')
    f['K-BB% (all-level, AAA scale)'] = (100 * f['xallm_K-BB%']).round(1)
    f['SwStr% (all-level, AAA scale)'] = (100 * f['xallm_SwStr%']).round(1)
    out = f.assign(Age=f.age.round(0), BF2026=f.nAll.astype(int), MLB_AAA_BF=f.mlbaaaN.astype(int), projRA9=f.projRA9.round(2),
                   projRA9_uncal=f.projRA9_uncal.round(2), Group=f.G)
    out = out.sort_values(['Role', 'tiered', 'projRA9'], ascending=[False, False, True])
    out['Tier'] = out.Tier.astype(str)
    # columns kept to what a signing decision reads (Wally: "only list columns that offer
    # relevant information"); mlbId stays last for matching by id
    out.loc[out.MLBadd, 'Note'] = ('added: MLB time, let go before 10/28; '
                                   + out.loc[out.MLBadd, 'Note'].fillna('')).str.rstrip('; ')
    out['P(MLB deal)'] = f.loc[out.index, 'p_mlb'].round(2)
    cols = ['Role', 'Tier', 'RoleRank', 'Name', 'Age', 'projRA9', 'P(MLB deal)', 'MLB_AAA_BF', 'Levels2026',
            'K-BB% (all-level, AAA scale)', 'SwStr% (all-level, AAA scale)',
            'MLB_Stuff+', 'MLB_Loc+', 'MLB_arsenal', 'AAA_Stuff+', 'AAA_Loc+', 'AAA_FBvelo', 'AAA_arsenal',
            'LastMove', 'Note', 'mlbId']
    out = out[cols]
    out['RoleRank'] = out.RoleRank.astype('Int64')
    tmp = OUT + '.tmp'
    out.to_csv(tmp, index=False)
    os.replace(tmp, OUT)
    print(f'wrote {OUT}: {len(out)} pitchers, {int(f.tiered.sum())} tiered')
    print(out.groupby(['Role', 'Tier']).size().to_string())
    for role in ('SP', 'RP'):
        print(f'\n{role} tier 1-2:')
        print(out[(out.Role == role) & out.Tier.isin(['1', '2'])][['RoleRank', 'Tier', 'Name', 'Age', 'projRA9', 'MLB_AAA_BF',
                                                              'Levels2026', 'Note']].to_string(index=False))


if __name__ == '__main__':
    main()
