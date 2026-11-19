#!/usr/bin/env python3
"""fa_offseason_sheet_sync.py — bring the free-agent pool in line with Wally's "2026/27 MLB
Offseason" sheet. Reads only; it prints what should change and writes a JSON of the changes.

Sheet (xlsx export, one tab per club; "Claude Cache" is skipped). Columns used:
  B Elected MLB FA/Non-tendered | C New Team | D Elected MiLB FA | E New Team | F Released | G New Team
  H MLB Signings | J MiLB Signings
A departure reads "10/29: RHRP Evan Phillips" or "9/29: C Riley Adams (AAA)"; a signing reads
"11/8: LHSP Carlos Peña (DET, AAA)" or "LF Tyler Fitzgerald* (AAA)" (* = re-signed).

Rules (Wally, 2026-11-19):
  OUT   anyone with a New Team next to his name, or in an MLB Signings / MiLB Signings column.
        The two should agree except for deals abroad; every disagreement is listed.
  IN    anyone who elected MLB or MiLB free agency or was released, has MLB time, and did not
        sign anywhere. MLB time = a 2026 MLB leaderboard row (the pool's standing rule).

Players are matched by ID, never by name against the leaderboard: a departure is looked up in
the MLB transactions API on its own date (build_free_agents.transaction_ids). A row with no id
is listed and left out, never guessed. The sheet-internal cross-check (New Team against the
signings columns) compares the sheet's own names with each other.

  .venv/bin/python scripts/research/projection/fa_offseason_sheet_sync.py /path/to/sheet.json
  (sheet.json = {tab: [[cell, ...], ...]} from the xlsx export)
"""
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from scripts.builders import build_free_agents as B  # noqa: E402

OUT = os.path.join(ROOT, 'data', '_proj', '_fa_sheet_sync.json')
DEP_COLS = {1: 'elected MLB FA', 3: 'elected MiLB FA', 5: 'released'}
SIGN_COLS = {7: 'MLB', 9: 'MiLB'}
ENTRY = re.compile(r'^(?:(\d{1,2})/(\d{1,2}):\s*)?(\S+)\s+(.*?)(\*)?\s*(?:\(([^()]*)\))?\s*$')
YEAR = 2026


def parse(cell):
    m = ENTRY.match(cell.strip())
    if not m:
        return None
    mo, da, pos, name, star, paren = m.groups()
    date = f'{YEAR}-{int(mo):02d}-{int(da):02d}' if mo else None
    return {'date': date, 'pos': pos, 'name': name.strip(), 'star': bool(star), 'paren': (paren or '').strip(), 'raw': cell.strip()}


def main():
    sheet = json.load(open(sys.argv[1]))
    deps, signs, bad = [], [], []
    for tab, rows in sheet.items():
        for r in rows[2:]:
            r = r + [''] * (12 - len(r))
            for c, kind in DEP_COLS.items():
                if r[c]:
                    e = parse(r[c])
                    if not e or not e['date']:
                        bad.append((tab, kind, r[c]))
                        continue
                    e.update(tab=tab, kind=kind, new_team=r[c + 1].strip())
                    deps.append(e)
            for c, kind in SIGN_COLS.items():
                if r[c]:
                    e = parse(r[c])
                    if not e:
                        bad.append((tab, kind + ' signing', r[c]))
                        continue
                    e.update(tab=tab, kind=kind)
                    signs.append(e)
    print(f'sheet: {len(deps)} departures ({sum(1 for d in deps if d["new_team"])} with a New Team cell), {len(signs)} signings, {len(bad)} cells not read')
    for b in bad:
        print('   NOT READ:', b)

    idx, by_name = B.mlb_index()
    tx = B.transaction_ids(sorted({d['date'] for d in deps} | {s['date'] for s in signs if s['date']}))
    for e in deps + signs:
        ids = tx.get((e['date'], B.norm_name(e['name']))) if e['date'] else None
        e['id'] = next(iter(ids)) if ids and len(ids) == 1 else None
        e['id_note'] = '' if e['id'] else ('undated' if not e['date'] else ('no transaction on that date' if not ids else 'ambiguous'))
        e['norm'] = B.norm_name(e['name'])

    # ── cross-check inside the sheet: New Team cells against the signings columns ──
    sign_names = defaultdict(list)
    for s in signs:
        sign_names[s['norm']].append(s)
    dep_names = defaultdict(list)
    for d in deps:
        dep_names[d['norm']].append(d)
    retired = [d for d in deps if d['new_team'].lower().startswith('retired')]
    with_team = [d for d in deps if d['new_team'] and d not in retired]
    a_not_b = [d for d in with_team if d['norm'] not in sign_names]
    b_not_a = []
    for n, ss in sign_names.items():
        ds = dep_names.get(n)
        if ds and not any(d['new_team'] for d in ds):
            b_not_a.append((ss, ds))
    print(f'\nCROSS-CHECK: {len(with_team)} departures carry a New Team; {len(retired)} say Retired')
    print(f'  New Team listed, but the player is in NO signings column ({len(a_not_b)}): expected for deals abroad')
    for d in a_not_b:
        print(f'     {d["tab"]:<4s}{d["kind"]:<16s}{d["raw"]:<44s} -> {d["new_team"]}')
    print(f'  In a signings column, but NO New Team next to his departure ({len(b_not_a)}): likely a missed cell')
    for ss, ds in b_not_a:
        for d in ds:
            print(f'     {d["tab"]:<4s}{d["kind"]:<16s}{d["raw"]:<44s} | signed: ' + '; '.join(f'{s["tab"]} {s["kind"]} "{s["raw"]}"' for s in ss))
    # a New Team that names a club, checked against the club tab that lists the signing
    mism = []
    for d in with_team:
        for s in sign_names.get(d['norm'], []):
            club = d['new_team'].split()[0].upper()
            if re.fullmatch(r'[A-Z]{2,3}', club) and club != s['tab']:
                mism.append((d, s))
    print(f'  New Team club differs from the tab that lists the signing ({len(mism)}):')
    for d, s in mism:
        print(f'     {d["tab"]:<4s}{d["raw"]:<44s} New Team "{d["new_team"]}" but the signing is on tab {s["tab"]} ({s["kind"]})')

    # ── the pool ──
    pool = {e['mlbId']: e for e in json.load(open(B.OUT))['players']}
    signed_ids, signed_why = {}, {}
    for d in with_team:
        if d['id']:
            signed_ids[d['id']] = f'{d["name"]}, {d["new_team"]} on the offseason sheet'
    name_only = []
    for s in signs:
        sid = s['id']
        if sid is None:
            ds = [d for d in dep_names.get(s['norm'], []) if d['id']]
            ids = {d['id'] for d in ds}
            if len(ids) == 1:
                sid = next(iter(ids))
        if sid is None:
            cand = [m for m in by_name.get(s['norm'], []) if m in pool]
            if len(cand) == 1:
                name_only.append((s, cand[0]))
            continue
        signed_ids.setdefault(sid, f'{s["name"]}, {s["kind"]} signing with {s["tab"]} on the offseason sheet')
    out_now = {i: w for i, w in signed_ids.items() if i in pool}
    print(f'\nPOOL ({len(pool)} players): {len(out_now)} are signed on the sheet and leave')
    for i, w in sorted(out_now.items(), key=lambda kv: kv[1]):
        print(f'     {i:>7d}  {pool[i]["name"]:<26s} {w}')
    print(f'  pool players matched to a signing by NAME ONLY (undated signing, no departure row): {len(name_only)}. NOT removed; check them')
    for s, i in name_only:
        print(f'     {i:>7d}  {pool[i]["name"]:<26s} {s["tab"]} {s["kind"]} "{s["raw"]}"')
    ret_in = [(d, d['id']) for d in retired if d['id'] in pool]
    print(f'  pool players the sheet marks Retired: {len(ret_in)}')
    for d, i in ret_in:
        print(f'     {i:>7d}  {pool[i]["name"]:<26s} {d["tab"]} {d["raw"]}')

    free = [d for d in deps if not d['new_team'] and d['norm'] not in sign_names]
    add, blocked, noid_mlb = {}, [], []
    for d in free:
        i = d['id']
        if i is None:
            cand = by_name.get(d['norm'], [])
            if cand:
                noid_mlb.append((d, cand))
            continue
        if i not in idx or i in pool:
            continue
        if i in B.SIGNED or i in B.RETIRED or i in B.REMOVED:
            blocked.append((d, i, 'SIGNED' if i in B.SIGNED else 'RETIRED' if i in B.RETIRED else 'REMOVED'))
            continue
        add[i] = (idx[i]['name'], d)
    print(f'\n  unsigned departures with a 2026 MLB row that are NOT in the pool: {len(add)} to add')
    for i, (nm, d) in sorted(add.items(), key=lambda kv: kv[1][0]):
        print(f'     {i:>7d}  {nm:<26s} {d["tab"]:<4s}{d["kind"]:<16s}{d["raw"]}')
    print(f'  unsigned on the sheet but held out by an earlier decision in build_free_agents.py: {len(blocked)}')
    for d, i, why in blocked:
        print(f'     {i:>7d}  {idx[i]["name"]:<26s} {why:<8s} {d["tab"]} {d["raw"]}')
    print(f'  unsigned departures with NO id from the transactions API whose name matches a 2026 MLB player: {len(noid_mlb)} (not added; check)')
    for d, cand in noid_mlb:
        print(f'     {d["tab"]:<4s}{d["kind"]:<16s}{d["raw"]:<44s} ({d["id_note"]}) name matches {[(c, idx[c]["name"]) for c in cand]}')
    unresolved = sum(1 for d in deps if d['id'] is None)
    print(f'\n  departures with no id: {unresolved} of {len(deps)} (most are minor leaguers the API lists under another date or spelling)')
    res = {'remove': {str(i): w for i, w in out_now.items()},
           'add': {str(i): {'name': nm, 'kind': d['kind'], 'tab': d['tab'], 'raw': d['raw']} for i, (nm, d) in add.items()},
           'retired_in_pool': [i for _, i in ret_in]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT + '.tmp', 'w'), indent=1)
    os.replace(OUT + '.tmp', OUT)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
