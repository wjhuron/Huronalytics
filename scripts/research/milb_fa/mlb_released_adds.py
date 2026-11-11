"""Pitchers with 2026 MLB time who were released or elected free agency BEFORE 2026-10-28,
are still free, and are not yet on Wally's target list (2026-11-11, per Wally: "go through all
the players who played in MLB and were either released or elected free agency BEFORE 10/28 and
add them to this potential list"; his example is Sam Moll).

The target list was built from players with a 2026 minor-league line, so a pitcher who only
pitched in MLB after an in-season release never entered it.

Sources:
  * MLB time: the Sheets pitch data, read through the season leaderboard
    (data/pitcher_leaderboard_rs.json), which aggregates every team tab of the six division
    workbooks and carries the mlbId. A combined (2TM..) row is taken when it exists, otherwise
    the single MLB stint; ROC/AAA rows are minor league and are left out.
  * Transactions: data/_milb_fa/resolved.csv (ids from resolve_ids.py) and the free / not-free
    verdict in data/_milb_fa/not_free.csv (fa_check.py, 2026-11-09). The last list move must be
    before 2026-10-28.
  * A fresh pass over the MLB transactions API from 2026-11-09 to today drops anyone who has
    signed since not_free.csv was built.
  * Already listed: the ids in data/_milb_fa/_rank_live.csv (Wally's targets plus the four adds).

Writes data/_milb_fa/mlb_adds.csv.
    python3 scripts/research/milb_fa/mlb_released_adds.py
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = os.path.join(ROOT, 'data', '_milb_fa')
CUTOFF = '2026-10-28'
BIND = ('signed', 'selected the contract', 'claimed', 'traded', 'acquired', 'purchased', 'retired')
PITCH_POS = {'RHP', 'LHP', 'P'}


def mlb_lines():
    lb = pd.DataFrame(json.load(open(os.path.join(ROOT, 'data', 'pitcher_leaderboard_rs.json'))))
    lb = lb[~lb.team.isin(['ROC', 'AAA'])].copy()
    lb['combined'] = lb.team.str.fullmatch(r'\d+TM')
    keep = []
    for mid, g in lb.groupby('mlbId'):
        c = g[g.combined]
        keep.append(c.iloc[0] if len(c) else g.iloc[0])
        if not len(c) and len(g) > 1:
            sys.exit(f'{mid}: {len(g)} MLB stints and no combined row; the leaderboard shape changed')
    out = pd.DataFrame(keep)
    cols = {'mlbId': 'mlbId', 'pitcher': 'sheetName', 'team': 'mlbTeam', 'g': 'MLB_G', 'gs': 'MLB_GS',
            'ip': 'MLB_IP', 'tbf': 'MLB_TBF', 'count': 'MLB_pitches', 'kPct': 'MLB_K%', 'bbPct': 'MLB_BB%',
            'stuffScore': 'MLB_Stuff+', 'hpERA': 'MLB_hpERA', 'era': 'MLB_ERA'}
    return out[[c for c in cols if c in out]].rename(columns=cols)


def signed_since(ids, start='2026-11-09'):
    end = date.today().isoformat()
    u = f'https://statsapi.mlb.com/api/v1/transactions?startDate={start}&endDate={end}'
    with urllib.request.urlopen(u, timeout=60) as r:
        tx = json.load(r)['transactions']
    hit = {}
    for t in tx:
        pid = (t.get('person') or {}).get('id')
        d = (t.get('description') or '').lower()
        # whole words: 'assigned' (a winter-league assignment) contains 'signed'
        if pid in ids and re.search(r'\b(' + '|'.join(BIND) + r')\b', d) and 'free agency' not in d:
            hit[pid] = f"{t.get('date', '')[:10]} {t.get('description')}"
    print(f'API {start}..{end}: {len(tx)} transactions, {len(hit)} candidates signed or moved since')
    return hit


def main():
    res = pd.read_csv(os.path.join(D, 'resolved.csv'), dtype={'mlbId': 'Int64'})
    res = res[res.mlbId.notna()]
    nf = pd.read_csv(os.path.join(D, 'not_free.csv')).set_index('mlbId')
    last = res.sort_values('Date').groupby('mlbId').tail(1).set_index('mlbId')
    free = last[last.index.map(lambda i: i in nf.index and not bool(nf.loc[i, 'notFree']))]
    early = free[free.Date < CUTOFF]
    pit = early[early.Position.isin(PITCH_POS)]
    lines = mlb_lines().set_index('mlbId')
    cand = pit[pit.index.isin(lines.index)].join(lines)
    listed = set(pd.read_csv(os.path.join(D, '_rank_live.csv')).mlbId)
    already = cand[cand.index.isin(listed)]
    cand = cand[~cand.index.isin(listed)]
    print(f'free pitchers with last move before {CUTOFF}: {len(pit)}; with 2026 MLB time in Sheets: '
          f'{len(cand) + len(already)}; already on the target list: {len(already)} '
          f'({", ".join(already.Player)})')
    moved = signed_since(set(int(i) for i in cand.index))
    cand['signedSince'] = cand.index.map(lambda i: moved.get(int(i), ''))
    out = cand.reset_index()[['mlbId', 'Player', 'Position', 'Date', 'Transaction Type', 'Team', 'Level',
                              'signedSince'] + [c for c in lines.columns]]
    out = out.rename(columns={'Date': 'lastMoveDate', 'Transaction Type': 'lastMove',
                              'Team': 'lastMoveTeam', 'Level': 'lastMoveLevel'})
    out = out.sort_values('MLB_TBF', ascending=False)
    tmp = os.path.join(D, 'mlb_adds.csv.tmp')
    out.to_csv(tmp, index=False)
    os.replace(tmp, os.path.join(D, 'mlb_adds.csv'))
    print(out[['Player', 'lastMoveDate', 'lastMove', 'lastMoveTeam', 'MLB_G', 'MLB_IP', 'MLB_TBF',
               'signedSince']].to_string(index=False))


if __name__ == '__main__':
    main()
