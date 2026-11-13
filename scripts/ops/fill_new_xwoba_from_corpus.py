#!/usr/bin/env python3
"""fill_new_xwoba_from_corpus.py — write the MiLB corpus xwOBA into blank NEW-tab cells.

The NEW tab (NLE2026 workbook) leaves some xwOBA cells blank that Savant has since
priced, and the MiLB corpus (data/_milb2026/milb2026_pitches.csv.gz) pulled them later.
On 2026-11-13 two such balls in play put Cornielle's NEW-card hdERA at 3.93 against 4.00
on his corpus card. The NEW card fills them at read time (cards/pitcher.py); this script
writes the same values into the tab, so the R reports and every other reader see them.

Only a BLANK xwOBA cell is written, and only with the corpus value for the same PitchID.
A filled cell is never overwritten. xBA and xSLG are left alone: the card reads neither.
Run it again after each time pitchers are added to NEW.

Before writing, the script re-reads the PitchID column and refuses any row whose PitchID
moved, so a row shift can never write into the wrong row.

Usage:
    python3 scripts/ops/fill_new_xwoba_from_corpus.py            # DRY RUN
    python3 scripts/ops/fill_new_xwoba_from_corpus.py --apply    # write for real
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cards.milb_corpus import corpus_xwoba, CORPUS_PATH
from scrapers.sheet_precision import fmt, domain_problem
from scrapers.sheets_append import _get_client, _col_letter, _sheets_retry

NLE2026 = '1BypxxlWgQAltETOLqccOYigeo8nXX-FIuVv6rhT4anA'
TAB = 'NEW'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true',
                    help='write the cells; without it nothing is written')
    a = ap.parse_args()

    ws = _sheets_retry(lambda: _get_client().open_by_key(NLE2026).worksheet(TAB),
                       label=f'{TAB} open')
    values = _sheets_retry(lambda: ws.get_all_values(), label=f'{TAB} read')
    header = values[0]
    for col in ('PitchID', 'xwOBA'):
        if col not in header:
            raise SystemExit(f'{TAB} header has no {col} column. Nothing written.')
    i_pid, i_xw = header.index('PitchID'), header.index('xwOBA')
    i_p = header.index('Pitcher') if 'Pitcher' in header else None

    blank = {}   # PitchID -> sheet row (1-based)
    for r1, row in enumerate(values[1:], start=2):
        pid = row[i_pid].strip() if i_pid < len(row) else ''
        xw = row[i_xw].strip() if i_xw < len(row) else ''
        if pid and not xw:
            blank[pid] = r1
    print(f'{TAB}: {len(values) - 1} rows, {len(blank)} with a blank xwOBA')

    try:
        cx = corpus_xwoba(blank)
    except FileNotFoundError:
        raise SystemExit(f'The MiLB corpus is absent ({CORPUS_PATH}). Rebuild it with '
                         f'scripts/builders/milb2026_pull.py. Nothing written.')
    if not cx:
        print('The corpus prices none of them. Nothing to do.')
        return

    targets = []
    for pid, v in sorted(cx.items()):
        val = fmt('xwOBA', v)
        bad = domain_problem('xwOBA', val)
        r1 = blank[pid]
        who = values[r1 - 1][i_p] if i_p is not None else ''
        if not val or bad:
            print(f'  *** REFUSED {pid} ({who}): corpus value {v!r} {bad or "is not a number"}')
            continue
        targets.append((pid, r1, val, who))

    # Rows can shift between the read and the write. Re-read the PitchID column and
    # refuse any target whose row no longer holds its PitchID.
    col = _sheets_retry(lambda: ws.col_values(i_pid + 1), label=f'{TAB} PitchID column')
    ok, n_refused = [], 0
    for pid, r1, val, who in targets:
        present = col[r1 - 1] if r1 - 1 < len(col) else ''
        if present != pid:
            print(f'  *** REFUSED {pid} ({who}): sheet row {r1} now holds {present!r}. Re-run.')
            n_refused += 1
            continue
        print(f'  row {r1}  {pid}  {who}  xwOBA -> {val}')
        ok.append({'range': f'{_col_letter(i_xw + 1)}{r1}', 'values': [[val]]})

    print(f'\n{len(ok)} cell(s) to write, {n_refused + len(cx) - len(targets)} refused, '
          f'{len(blank) - len(cx)} blank cell(s) the corpus does not price')
    if not a.apply:
        print('DRY RUN: nothing was written. Re-run with --apply.')
        return
    if ok:
        _sheets_retry(lambda: ws.batch_update(ok, value_input_option='USER_ENTERED'),
                      label=f'{TAB} xwOBA write')
        print(f'Wrote {len(ok)} xwOBA cell(s) to {TAB}.')


if __name__ == '__main__':
    main()
