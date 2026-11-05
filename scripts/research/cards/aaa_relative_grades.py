"""The AAA ruler for hitter cards: every 2026 AAA hitter's stats and grades on one level.

Scores every 2026 AAA regular-season hitter the way a MiLB corpus card does: the card's row
builder and BB+ chain, and SD+/CT+ from the season's MLB cell tables through extra_groups, so the
MLB pool and its anchors do not move. BB+ is scored twice, with and without the AAA bat speed in
its prior. CT+ through extra_groups has no bat prior, so the card's value is the check on that gap.

Writes data/_milb2026/hitter_pool_AAA.json, which cards/milb_corpus.py reads. Batches keep one hitter group in memory at a time: this
machine has 8 GB, so run it alone, with no card build beside it.

    PYTHONHASHSEED=0 .venv/bin/python scripts/research/cards/aaa_relative_grades.py
"""
import json
import os
import sys
from collections import defaultdict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from cards import milb_corpus as mc  # noqa: E402
from cards.hitter import load_metadata, load_pitch_data  # noqa: E402
from pipeline.contact import compute_ct_plus  # noqa: E402
from pipeline.sdplus import compute_sd_plus  # noqa: E402
from pipeline.utils import ALL_TEAMS  # noqa: E402
from pipeline.window_pool import (  # noqa: E402
    bb_plus_chain, build_window_hitter_row, plus_post_chain, process_plus_from_atoms)

OUT = os.path.join(ROOT, 'data', '_milb2026')
N_BATCH = 8
KEEP = ('pa', 'wOBA', 'xwOBA', 'barrelPct', 'airPullPct', 'gbPct', 'kPct', 'bbPct', 'izSwChase', 'izSwingPct',
        'chasePct', 'izContactPct', 'contactPct', 'whiffPct', 'hardHitPct', 'ev95', 'xwOBAcon', 'batSpeed',
        'nCompSwings', 'bbPlus', 'sdPlus', 'ctPlus', 'processPlus', 'sdPlusN', 'ctPlusN')


def split_batches():
    """Write the AAA regular-season rows into N_BATCH files by mlbId. Returns their paths."""
    os.makedirs(OUT, exist_ok=True)
    paths = [os.path.join(OUT, f'_aaa_batch{i}.csv') for i in range(N_BATCH)]
    if all(os.path.exists(p) for p in paths):
        return paths
    man = pd.read_csv(mc.MANIFEST_PATH, usecols=['game_pk', 'level', 'gameType'])
    pks = set(man[(man.level == 'AAA') & (man.gameType == 'R')].game_pk)
    players = pd.read_csv(mc.PLAYERS_PATH, keep_default_na=False)[['game_pk', 'team', 'name', 'mlbId']]
    started = set()
    for chunk in pd.read_csv(mc.CORPUS_PATH, dtype=str, keep_default_na=False, chunksize=100_000):
        chunk['_pk'] = chunk.PitchID.str.split('_').str[0].astype(int)
        chunk = chunk[chunk._pk.isin(pks)]
        chunk = chunk.merge(players, left_on=['_pk', 'BTeam', 'Batter'], right_on=['game_pk', 'team', 'name'])
        chunk = chunk.drop(columns=['game_pk', 'team', 'name', '_pk'])
        for i, g in chunk.groupby(chunk.mlbId.astype(int) % N_BATCH):
            g.to_csv(paths[i], mode='a' if i in started else 'w', header=i not in started, index=False)
            started.add(i)
    return paths


def main():
    paths = split_batches()
    all_pitches = load_pitch_data()
    metadata = load_metadata()
    G = metadata.get('gutsConstants') or {}
    ep = {(p.get('Pitcher'), p.get('PTeam')) for p in all_pitches if p.get('Pitch Type') == 'EP'}
    all_pitches = [p for p in all_pitches if (p.get('Pitcher'), p.get('PTeam')) not in ep]
    by = defaultdict(list)
    for p in all_pitches:
        if not p.get('_roc_pitcher_pitch') and p.get('Batter') and p.get('BTeam') in ALL_TEAMS:
            by[(p['Batter'], p['BTeam'])].append(p)
    by = dict(by)
    print(f'{len(all_pitches)} league pitches, {len(by)} season groups', flush=True)

    out = {}
    for i, path in enumerate(paths):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df['_level'], df['_gameType'] = 'AAA', 'R'
        groups = {}
        for mid, g in df.groupby('mlbId'):
            rows = g.drop(columns=['mlbId']).to_dict('records')
            mc._to_mlb_currency(rows)
            rows.sort(key=lambda r: (r['Game Date'], r['PitchID']))
            groups[mid] = [q for q in mc.as_pickle_rows(rows, all_pitches)
                           if (q.get('Pitcher'), q.get('PTeam')) not in ep]
        del df
        recs = {}
        for mid, pl in groups.items():
            name, club = pl[-1].get('Batter'), pl[-1].get('BTeam')
            row = build_window_hitter_row(pl, metadata, {'hitter': name, 'team': club, '_isROC': club == 'ROC'})
            free = dict(row, batSpeed=None)
            bb_plus_chain(row, metadata)
            bb_plus_chain(free, metadata)
            row['_bbPlusNoBat'] = free.get('bbPlus')
            recs[mid] = (name, club, row)
        _, _, sd = compute_sd_plus(all_pitches, by, lg_woba=G.get('lgWOBA'), woba_scale=G.get('wOBAScale'),
                                   extra_groups=groups)
        _, _, ct = compute_ct_plus(all_pitches, by, lg_woba=G.get('lgWOBA'), woba_scale=G.get('wOBAScale'),
                                   extra_groups=groups)
        for mid, (name, club, row) in recs.items():
            s, c = sd.get(mid), ct.get(mid)
            row['sdPlus'] = s['sdPlus'] if s else None
            row['_procSd'] = s['raw_sd'] if s else None
            row['sdPlusN'] = s['n_decisions'] if s else 0
            row['ctPlus'] = c['ctPlus'] if c else None
            row['_procCt'] = c['raw_ct'] if c else None
            row['ctPlusN'] = c['n_swings'] if c else 0
            plus_post_chain(row, metadata)
            process_plus_from_atoms(row, metadata)
            out[mid] = {'name': name, 'club': club, 'bbPlusNoBat': row['_bbPlusNoBat'],
                        **{k: row.get(k) for k in KEEP}}
        print(f'batch {i + 1}/{N_BATCH}: {len(recs)} hitters, {len(out)} so far', flush=True)
        del groups, recs

    tmp = os.path.join(OUT, 'hitter_pool_AAA.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f)
    os.replace(tmp, os.path.join(OUT, 'hitter_pool_AAA.json'))
    fur = out.get('801501') or {}
    print('Furman check, card reads Process+ 107, BB+ 86, CT+ 111, SD+ 113:',
          {k: fur.get(k) for k in ('processPlus', 'bbPlus', 'bbPlusNoBat', 'ctPlus', 'sdPlus')})
    for p in paths:
        os.remove(p)


if __name__ == '__main__':
    main()
