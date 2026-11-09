"""abrams_team_fit.py: which clubs gain the most from CJ Abrams at shortstop and at second base.

Gain = Abrams' projected WAR per 600 PA at the position minus the club's incumbent's, for 2027 and
2028 (his two arbitration years). Research, for the Nats offseason article.

Projection: the even blend of ours (data/_proj/projections_hitters.csv, WAR600_2027) and Steamer 2027
(data/_proj/fg/steamer_2027_bat.json, WAR scaled to 600 PA), the hitter blend the FA rankings measured
(fa_rank_blend.py: even ours + Steamer, interior, 7/7). 2028 has no projection of its own: each blended
2027 value moves by half of our 2027-to-2029 change (linear between the horizons, a convention).

Incumbent: the club's current 40-man player (MLB Stats API, today) with the most 2026 MLB innings at
the position, each player counted at only the one of SS/2B where he logged more innings. A prospect
with no MLB innings is invisible here; clubs whose incumbent logged under 300 innings are flagged.

Abrams at 2B: our side swaps his positional runs (shipped hWAR table) and adds the measured SS-to-2B
fielding gain (scripts/research/fielding/ss_to_2b_conversion.py, >= 100 innings at each); Steamer's
side swaps fWAR's positional runs and adds the same gain. Both scale by his 2026 innings per PA.

Usage: python3 scripts/research/projection/abrams_team_fit.py
Output: console + ~/Downloads/abrams_team_fit_2027.csv
"""
import csv
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
P = os.path.join(ROOT, 'data', '_proj')
FB = os.path.join(ROOT, 'data', '_fielding_battery')
ABRAMS = '682928'
WSH = 120
FULL = 1458.0
LOW_INN = 300


def api(url):
    r = subprocess.run(['curl', '-sfL', '--retry', '3', url], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f'fetch failed ({r.returncode}): {url}')
    return json.loads(r.stdout)


def main():
    meta = json.load(open(os.path.join(ROOT, 'data', 'metadata_rs.json')))['hwarConstants']
    rpw = meta['rpw']
    pos_h = meta['posAdj']
    pos_f = meta['posAdjBase']
    conv = json.load(open(os.path.join(FB, 'ss_to_2b_conversion.json')))['floors']['100']['gain']

    ours = {r['mlbId']: r for r in csv.DictReader(open(os.path.join(P, 'projections_hitters.csv')))}
    st = {}
    for r in json.load(open(os.path.join(P, 'fg', 'steamer_2027_bat.json'))):
        mid = str(r.get('xMLBAMID') or r.get('MLBAMID') or '')
        if mid and r.get('PA'):
            st[mid] = 600.0 * r['WAR'] / r['PA']

    def proj(mid):
        """(2027, 2028) blended WAR per 600, or None. One source alone stands in when the other is absent."""
        o = ours.get(mid)
        o27 = float(o['WAR600_2027']) if o else None
        s27 = st.get(mid)
        vals = [v for v in (o27, s27) if v is not None]
        if not vals:
            return None
        b27 = sum(vals) / len(vals)
        d = (float(o['WAR600_2029']) - o27) / 2 if o else 0.0
        return b27, b27 + d

    inn = {}
    for s in json.load(open(os.path.join(FB, 'fielding_innings_2026.json')))['stats'][0]['splits']:
        p = s['position']['abbreviation']
        if p in ('SS', '2B'):
            k = str(s['player']['id'])
            inn.setdefault(k, {'SS': 0.0, '2B': 0.0})[p] += float(s['stat'].get('innings') or 0)

    teams = api('https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026')['teams']
    stand = {}
    for rec in api('https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season=2026')['records']:
        for t in rec['teamRecords']:
            stand[t['team']['id']] = (t['wins'], t['losses'])

    # Abrams at each position.
    ab = proj(ABRAMS)
    a_pa = float(ours[ABRAMS]['pa_2026'])
    a_inn = inn[ABRAMS]['SS'] + inn[ABRAMS]['2B']
    k = (a_inn / a_pa) * 600.0 / FULL            # full seasons of innings per 600 PA
    d_ours = k * (pos_h['2B'] - pos_h['SS'] + conv) / rpw
    d_st = k * (pos_f['2B'] - pos_f['SS'] + conv) / rpw
    d2b = (d_ours + d_st) / 2
    abr = {'SS': ab, '2B': (ab[0] + d2b, ab[1] + d2b)}
    print(f'Abrams WAR/600: SS {ab[0]:.2f} (2027) {ab[1]:.2f} (2028); 2B {abr["2B"][0]:.2f} / {abr["2B"][1]:.2f}'
          f'  [2B move: ours {d_ours:+.2f}, Steamer {d_st:+.2f}; SS-to-2B fielding gain {conv:+.2f} runs/1458]')

    rows = []
    for t in teams:
        if t['id'] == WSH:
            continue
        roster = api(f"https://statsapi.mlb.com/api/v1/teams/{t['id']}/roster?rosterType=40Man&season=2027")['roster']
        ids = [str(x['person']['id']) for x in roster]
        names = {str(x['person']['id']): x['person']['fullName'] for x in roster}
        cand = {'SS': [], '2B': []}
        for mid in ids:
            i = inn.get(mid)
            if not i or max(i.values()) <= 0:
                continue
            home = 'SS' if i['SS'] >= i['2B'] else '2B'
            cand[home].append((i[home], mid))
        for pos in ('SS', '2B'):
            c = sorted(cand[pos], reverse=True)
            if not c:
                rows.append({'team': t['abbreviation'], 'pos': pos, 'incumbent': '(none on 40-man)', 'inc_inn': 0})
                continue
            i_inn, mid = c[0]
            pj = proj(mid)
            if pj is None:
                continue
            w, l = stand.get(t['id'], (None, None))
            rows.append({'team': t['abbreviation'], 'pos': pos, 'w2026': w, 'l2026': l,
                         'incumbent': names[mid], 'inc_inn': round(i_inn), 'inc_age': ours.get(mid, {}).get('age_2027'),
                         'inc_2027': round(pj[0], 2), 'inc_2028': round(pj[1], 2),
                         'abrams_2027': round(abr[pos][0], 2), 'abrams_2028': round(abr[pos][1], 2),
                         'gain_2027': round(abr[pos][0] - pj[0], 2),
                         'gain_2yr': round(abr[pos][0] - pj[0] + abr[pos][1] - pj[1], 2),
                         'flag': 'incumbent under 300 inn' if i_inn < LOW_INN else ''})

    rows = [r for r in rows if 'gain_2yr' in r]
    rows.sort(key=lambda r: -r['gain_2yr'])
    out = os.path.expanduser('~/Downloads/abrams_team_fit_2027.csv')
    cols = ['team', 'pos', 'w2026', 'l2026', 'incumbent', 'inc_age', 'inc_inn', 'inc_2027', 'inc_2028',
            'abrams_2027', 'abrams_2028', 'gain_2027', 'gain_2yr', 'flag']
    tmp = out + '.tmp'
    with open(tmp, 'w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)
    os.replace(tmp, out)
    for r in rows[:25]:
        print(f"{r['team']:4s} {r['pos']:2s} {r['w2026']}-{r['l2026']}  {r['incumbent']:24s} inn {r['inc_inn']:5d}  "
              f"inc {r['inc_2027']:+.2f}  gain27 {r['gain_2027']:+.2f}  gain2y {r['gain_2yr']:+.2f}  {r['flag']}")


if __name__ == '__main__':
    main()
