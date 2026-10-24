#!/usr/bin/env python3
"""twins_monthly_xlsx.py — write the Twins month-by-month hitter workbook.

Reads data/_twins_monthly.json (scripts/tools/twins_monthly_tracker.py) and
writes ~/Downloads/Twins_Monthly_Hitter_Tracker_2026.xlsx.

Values are stored at full precision; every rounding is a cell number format.
Colours are static fills on a three-point scale per column, centred on the MLB average, with
the ends at the MLB average +/- 2 SD of 2026 season values among hitters with
200+ PA (a display convention, not a measured constant). Months under
SMALL_PA plate appearances are greyed and left uncoloured (also a convention:
it sits at SD+'s 190-decision computation floor, about 50 PA).

Usage: python3 scripts/tools/twins_monthly_xlsx.py
"""
import json
import os
import statistics
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from pipeline.utils import is_combined_team  # noqa: E402

SRC = os.path.join(REPO, 'data', '_twins_monthly.json')
OUT = os.path.expanduser('~/Downloads/Twins_Monthly_Hitter_Tracker_2026.xlsx')
SMALL_PA = 50
SPREAD_MIN_PA = 200
DATA_THROUGH = '2026-09-27'

PCT, RATE, INT, DEC1 = '0.0%', '.000', '0', '0.0'
# (key, header, number format, direction: 1 higher is better, -1 lower is
# better, 0 not coloured). Season-row BB+/SD+/CT+ read the raw keys too.
GROUPS = [
    ('Sample', [('pa', 'PA', INT, 0), ('count', 'Pitches', INT, 0),
                ('nSwings', 'Swings', INT, 0), ('nBip', 'BIP', INT, 0)]),
    ('Results', [('avg', 'AVG', RATE, 1), ('obp', 'OBP', RATE, 1), ('slg', 'SLG', RATE, 1),
                 ('hr', 'HR', INT, 0), ('babip', 'BABIP', RATE, 0)]),
    ('Actual vs Expected', [('wOBA', 'wOBA', RATE, 1), ('xwOBA', 'xwOBA', RATE, 1),
                            ('wRCplus', 'wRC+', INT, 1), ('xWRCplus', 'xwRC+', INT, 1),
                            ('wOBAcon', 'wOBAcon', RATE, 1), ('xwOBAcon', 'xwOBAcon', RATE, 1)]),
    ('Process', [('processPlus', 'Process+', INT, 1), ('bbPlusU', 'BB+', INT, 1),
                 ('ctPlusU', 'CT+', INT, 1), ('sdPlusU', 'SD+', INT, 1)]),
    ('Plate Discipline', [('kPct', 'K%', PCT, -1), ('bbPct', 'BB%', PCT, 1),
                          ('izSwingPct', 'Z-Swing%', PCT, 0), ('chasePct', 'Chase%', PCT, -1),
                          ('izContactPct', 'Z-Contact%', PCT, 1), ('whiffPct', 'Whiff%', PCT, -1),
                          ('twoStrikeWhiffPct', '2K Whiff%', PCT, -1),
                          ('firstPitchSwingPct', 'FPSw%', PCT, 0)]),
    ('Batted Ball', [('avgEVAll', 'Avg EV', DEC1, 1), ('ev95', 'EV95', DEC1, 1),
                     ('hardHitPct', 'Hard-Hit%', PCT, 1), ('barrelPct', 'Barrel%', PCT, 1),
                     ('medLA', 'Med LA', DEC1, 0), ('gbPct', 'GB%', PCT, 0),
                     ('fbPct', 'FB%', PCT, 0), ('pullPct', 'Pull%', PCT, 0),
                     ('airPullPct', 'AirPull%', PCT, 1)]),
    ('Bat Tracking', [('batSpeed', 'Bat Speed', DEC1, 1), ('swingLength', 'Swing Length', DEC1, 0),
                      ('attackAngle', 'Attack Angle', DEC1, 0),
                      ('squaredUpPct', 'Squared-Up%', PCT, 1), ('blastPct', 'Blast%', PCT, 1)]),
]
COLS = [c for _, cs in GROUPS for c in cs]
PLUS_LEAGUE = {'processPlus', 'bbPlusU', 'ctPlusU', 'sdPlusU', 'wRCplus', 'xWRCplus'}
SEASON_FROM_RAW = {'bbPlusU', 'ctPlusU', 'sdPlusU', 'wOBAcon'}   # season row reads our Season group

TRENDS = ['wRCplus', 'xWRCplus', 'processPlus', 'kPct', 'bbPct', 'chasePct', 'whiffPct',
          'barrelPct', 'ev95', 'batSpeed']

GOOD, MID, BAD = 'F4A582', 'FFFFFF', '92C5DE'
NAVY = '002B5C'          # Twins navy, headers only
GREY_FILL = PatternFill('solid', fgColor='EDEDED')
GREY_FONT = Font(color='9A9A9A')
HEAD_FILL = PatternFill('solid', fgColor=NAVY)
GROUP_FILL = PatternFill('solid', fgColor='D9DEE8')
WHITE_BOLD = Font(color='FFFFFF', bold=True)
THIN = Side(style='thin', color='B0B0B0')
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)

DEFS = {
    'pa': ('Plate appearances. Official line from FanGraphs for the month.', 'FanGraphs', 'The sample size behind every rate. Read it first.'),
    'count': ('Pitches seen.', 'Statcast', 'Sample size for the swing-decision stats.'),
    'nSwings': ('Swings, bunts excluded.', 'Statcast', 'Sample size for contact and whiff rates.'),
    'nBip': ('Balls in play, bunts excluded, home runs included.', 'Statcast', 'Sample size for the contact-quality stats.'),
    'avg': ('Batting average.', 'FanGraphs', 'Expected on any sheet. Least reliable in one month.'),
    'obp': ('On-base percentage.', 'FanGraphs', 'Expected on any sheet.'),
    'slg': ('Slugging percentage.', 'FanGraphs', 'Expected on any sheet.'),
    'hr': ('Home runs.', 'FanGraphs', 'Expected on any sheet.'),
    'babip': ('Batting average on balls in play.', 'FanGraphs', 'Luck flag. A month far from his season BABIP is mostly luck.'),
    'wOBA': ('Weighted on-base average: every outcome weighted by its run value.', 'FanGraphs', 'One number for total offense. Read it beside xwOBA.'),
    'xwOBA': ('Expected wOBA from exit velocity and launch angle (with a pulled-air-ball term), plus actual K, BB, HBP.', 'Statcast, Huronalytics', 'What the contact deserved. The wOBA - xwOBA gap is the luck read.'),
    'wRCplus': ('Weighted runs created plus. Park and league adjusted. 100 = league average.', 'FanGraphs (date range)', 'The standard all-in offense number.'),
    'xWRCplus': ('wRC+ built from xwOBA instead of wOBA. 100 = league average.', 'Huronalytics', 'Paired with wRC+: the gap shows luck.'),
    'wOBAcon': ('wOBA on balls in play (bunts out, home runs in), priced with the 2026 wOBA weights.', 'Statcast, computed for this sheet', 'Production on contact only, so K and BB do not hide it.'),
    'xwOBAcon': ('Expected wOBA on balls in play.', 'Statcast', 'Paired with wOBAcon: contact quality without defense or luck.'),
    'processPlus': ('Composite of raw BB+ (52%), SD+ (17%) and CT+ (31%), scaled so one point = one percent of wRC+. 100 = league average.', 'Huronalytics', 'One process number: is the hitter doing the things that create runs?'),
    'bbPlusU': ('Batted-ball quality: 60% xwOBAcon, 40% 95th-percentile exit velocity. RAW: not regressed toward 100.', 'Huronalytics', 'Contact quality that stabilizes fast.'),
    'ctPlusU': ('Contact+: contact rate on swings against what the league makes on the same pitches, leverage weighted. RAW.', 'Huronalytics', 'Bat-to-ball skill with pitch difficulty removed.'),
    'sdPlusU': ('Swing Decisions+: the run value of each swing or take for its location and count. RAW.', 'Huronalytics', 'Approach quality, independent of the umpire.'),
    'kPct': ('Strikeouts / PA.', 'FanGraphs', 'Stabilizes fast. An early sign of a change.'),
    'bbPct': ('Walks (including intentional) / PA.', 'FanGraphs', 'Stabilizes fast. An early sign of a change.'),
    'izSwingPct': ('Swing rate at pitches in the strike zone.', 'Statcast', 'Aggression on strikes. Not good or bad by itself, so it is not coloured.'),
    'chasePct': ('Swing rate at pitches outside the strike zone.', 'Statcast', 'The clearest discipline signal. Reliable in one month.'),
    'izContactPct': ('Contact rate on swings at strikes.', 'Statcast', 'Bat-to-ball on the pitches he should hit.'),
    'whiffPct': ('Misses / swings, bunts excluded.', 'Statcast', 'Swing-and-miss. Moves with bat-speed and approach changes.'),
    'twoStrikeWhiffPct': ('Whiff rate on two-strike swings.', 'Statcast', 'How well he battles with two strikes.'),
    'firstPitchSwingPct': ('Share of PA with a swing at 0-0.', 'Statcast', 'Approach style. Not coloured.'),
    'avgEVAll': ('Average exit velocity on batted balls.', 'Statcast', 'Simple strength-of-contact read.'),
    'ev95': ('95th-percentile exit velocity: his hardest regular contact.', 'Statcast', 'Steadier than max or average EV. A drop can flag fatigue or injury.'),
    'hardHitPct': ('Share of batted balls at 95+ mph.', 'Statcast', 'Contact quality.'),
    'barrelPct': ('Barrels / balls in play (official Statcast barrel).', 'Statcast', 'The best contact type for damage.'),
    'medLA': ('Median launch angle.', 'Statcast', 'Swing plane on contact. Not coloured.'),
    'gbPct': ('Ground-ball share.', 'Statcast', 'Batted-ball profile. Not coloured.'),
    'fbPct': ('Fly-ball share.', 'Statcast', 'Batted-ball profile. Not coloured.'),
    'pullPct': ('Pulled share of batted balls.', 'Statcast', 'Spray profile. Not coloured.'),
    'airPullPct': ('Share of batted balls hit in the air to the pull side.', 'Statcast', 'The most productive batted-ball direction.'),
    'batSpeed': ('Average bat speed on competitive swings.', 'Statcast bat tracking', 'A physical tool. A drop shows before the results do.'),
    'swingLength': ('Average swing length, feet.', 'Statcast bat tracking', 'Swing shape. Not coloured.'),
    'attackAngle': ('Average vertical bat angle at contact, degrees.', 'Statcast bat tracking', 'Shows a swing change. Not coloured.'),
    'squaredUpPct': ('Share of swings that got the most exit velocity the bat speed allowed.', 'Statcast bat tracking', 'Quality of contact on the swing itself.'),
    'blastPct': ('Swings that were both fast and squared up.', 'Statcast bat tracking', 'The swing outcome most tied to damage.'),
}


def pretty(name):
    last, _, first = name.partition(', ')
    return f'{first} {last}'.strip()


def season_spreads(season_all, lg):
    """Colour-scale ends: league average +/- 2 SD of 200+ PA season values."""
    pool = [r for r in season_all if r.get('team') not in ('ROC', 'AAA')
            and not is_combined_team(r.get('team')) and (r.get('pa') or 0) >= SPREAD_MIN_PA]
    out = {}
    for key, _, _, d in COLS:
        if not d:
            continue
        src = {'bbPlusU': 'bbPlus', 'ctPlusU': 'ctPlus', 'sdPlusU': 'sdPlus'}.get(key, key)
        vals = [r[src] for r in pool if r.get(src) is not None]
        mid = 100.0 if key in PLUS_LEAGUE else lg.get(key)
        if mid is None or len(vals) < 30:
            continue
        sd = statistics.pstdev(vals)
        out[key] = (mid - 2 * sd, mid, mid + 2 * sd)
    return out


def fill_for(v, spread, direction):
    """Static three-point fill: BAD at the low end, white at the MLB average,
    GOOD at the high end (reversed when lower is better). Baked as a cell fill,
    not a colour-scale rule, because Numbers and most viewers drop those."""
    lo, mid, hi = spread
    if v is None:
        return None
    t = (v - mid) / (hi - mid) if v >= mid else (v - mid) / (mid - lo)
    t = max(-1.0, min(1.0, t)) * direction
    end = GOOD if t > 0 else BAD
    a = abs(t)
    rgb = [round(int(MID[i:i + 2], 16) * (1 - a) + int(end[i:i + 2], 16) * a) for i in (0, 2, 4)]
    return PatternFill('solid', fgColor='%02X%02X%02X' % tuple(rgb))


def write_header(ws, row, first_label, extra_cols=0):
    """Group band on `row`, column headers on row + 1. Returns first stat column."""
    c0 = 2 + extra_cols
    ws.cell(row=row + 1, column=1, value=first_label)
    col = c0
    for gname, cs in GROUPS:
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + len(cs) - 1)
        g = ws.cell(row=row, column=col, value=gname)
        g.fill, g.font, g.alignment = GROUP_FILL, Font(bold=True, color=NAVY), CENTER
        for k, h, _, _ in cs:
            cell = ws.cell(row=row + 1, column=col, value=h)
            col += 1
    for c in range(1, col):
        cell = ws.cell(row=row + 1, column=c)
        cell.fill, cell.font, cell.alignment = HEAD_FILL, WHITE_BOLD, CENTER
    return c0


def main():
    with open(SRC) as f:
        d = json.load(f)
    with open(os.path.join(REPO, 'data', 'hitter_leaderboard_rs.json')) as f:
        season_all = json.load(f)
    months, lg = d['months'], d['leagueAverages']
    season_rows = {r['hitter']: r for r in d['seasonRows']}
    ours = {(r['hitter'], r['month']): r for r in d['rows']}
    spreads = season_spreads(season_all, lg)
    hitters = sorted(season_rows, key=lambda h: (-season_rows[h]['pa'], h))

    def season_value(h, key):
        if key in SEASON_FROM_RAW:
            return ours[(h, 'Season')].get(key)
        return season_rows[h].get(key)

    def lg_value(key):
        if key in PLUS_LEAGUE:
            return 100
        if key in ('pa', 'count', 'nSwings', 'nBip', 'hr'):
            return None
        return lg.get(key)

    wb = Workbook()

    # ── Read Me ──────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = 'Read Me'
    lines = [
        ('Minnesota Twins: Month-by-Month Hitter Tracker, 2026', Font(bold=True, size=16, color=NAVY)),
        (f'Regular season, data through {DATA_THROUGH}. Every hitter with a Twins plate appearance ({len(hitters)}).', None),
        ('', None),
        ('TABS', Font(bold=True, color=NAVY)),
        ('Team Trends: ten headline stats, every hitter by month on one page.', None),
        ('One tab per hitter (most PA first): every stat by month, with his season line and the MLB average below.', None),
        ('All Data: one row per hitter-month, with filters, for sorting and pivots.', None),
        ('Definitions: what each stat is, where it comes from, and why it is in the sheet.', None),
        ('', None),
        ('HOW TO READ IT', Font(bold=True, color=NAVY)),
        ('Red = better than the MLB average. Blue = worse. White = average. Uncoloured columns describe style, not quality.', None),
        ('The colour ends sit at the MLB average plus or minus two standard deviations of 2026 season values (hitters with 200+ PA).', None),
        (f'Grey rows: fewer than {SMALL_PA} PA in the month. Too small to read; left uncoloured.', None),
        ('Read the pairs side by side: wOBA vs xwOBA, wRC+ vs xwRC+, wOBAcon vs xwOBAcon. A big gap is mostly luck.', None),
        ('Discipline and bat-tracking stats stabilize in a month. Results do not. A change in Chase%, Whiff% or bat speed is a signal before the slash line moves.', None),
        ('', None),
        ('NOTES', Font(bold=True, color=NAVY)),
        ('Late-March games (Opening Day 3/26) are counted in April.', None),
        ('BB+, CT+ and SD+ are RAW in every row, including the season row: not regressed toward 100. They differ from the regressed values on the leaderboard.', None),
        ('SD+ needs 190 swing decisions and CT+ needs 65 swings in the month; below that they are blank, and so is Process+.', None),
        ('James Outman also batted for another club in June, so his June line is from Twins pitches only, not the FanGraphs line.', None),
        ('Ryan Jeffers: the monthly FanGraphs PA sum to 368; his official season total is 369.', None),
        ('', None),
        ('SOURCES', Font(bold=True, color=NAVY)),
        ('Statcast pitch-level data (Baseball Savant / MLB). FanGraphs date-range lines for PA, slash line, wOBA, BABIP, K%, BB% and wRC+.', None),
        ('Huronalytics metrics (Process+, BB+, CT+, SD+, xwRC+): huronalytics.vercel.app. Each month is scored on season league baselines.', None),
    ]
    for i, (text, font) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        if font:
            c.font = font
    ws.column_dimensions['A'].width = 130

    # ── Team Trends ──────────────────────────────────────────────────────
    wt = wb.create_sheet('Team Trends')
    meta = {k: (h, fmt, dr) for k, h, fmt, dr in COLS}
    r = 1
    wt.cell(row=r, column=1, value='Team Trends: every hitter by month').font = Font(bold=True, size=14, color=NAVY)
    r += 2
    for key in TRENDS:
        h, fmt, dr = meta[key]
        wt.cell(row=r, column=1, value=h).font = Font(bold=True, size=12, color=NAVY)
        r += 1
        heads = ['Hitter', 'Season PA'] + months + ['Season']
        for c, t in enumerate(heads, start=1):
            cell = wt.cell(row=r, column=c, value=t)
            cell.fill, cell.font, cell.alignment = HEAD_FILL, WHITE_BOLD, CENTER
        r += 1
        for hname in hitters:
            wt.cell(row=r, column=1, value=pretty(hname))
            wt.cell(row=r, column=2, value=season_rows[hname]['pa'])
            for j, m in enumerate(months + ['Season']):
                col = 3 + j
                row = ours.get((hname, m))
                v = season_value(hname, key) if m == 'Season' else (row.get(key) if row else None)
                pa = season_rows[hname]['pa'] if m == 'Season' else (row.get('pa') if row else 0)
                cell = wt.cell(row=r, column=col, value=v)
                cell.number_format = fmt
                cell.alignment = Alignment(horizontal='center')
                if (pa or 0) < SMALL_PA:
                    cell.fill, cell.font = GREY_FILL, GREY_FONT
                elif dr and key in spreads and v is not None:
                    cell.fill = fill_for(v, spreads[key], dr)
            r += 1
        wt.cell(row=r, column=1, value='MLB Average').font = Font(italic=True)
        cell = wt.cell(row=r, column=3 + len(months), value=lg_value(key))
        cell.number_format, cell.font = fmt, Font(italic=True)
        cell.alignment = Alignment(horizontal='center')
        r += 2
    wt.column_dimensions['A'].width = 22
    wt.column_dimensions['B'].width = 10
    for j in range(len(months) + 1):
        wt.column_dimensions[get_column_letter(3 + j)].width = 10
    wt.freeze_panes = 'C1'

    # ── One tab per hitter ───────────────────────────────────────────────
    used = set()
    for hname in hitters:
        s = season_rows[hname]
        last = hname.split(',')[0][:28]
        title = last if last not in used else pretty(hname)[:31]
        used.add(title)
        ws = wb.create_sheet(title)
        ws.cell(row=1, column=1, value=f"{pretty(hname)}  |  MIN  |  Bats {s.get('stands') or '-'}  |  "
                                       f"{s.get('position') or '-'}  |  2026: {s['pa']} PA, "
                                       f"{s.get('wRCplus')} wRC+").font = Font(bold=True, size=14, color=NAVY)
        ws.cell(row=2, column=1, value=f'Grey rows: under {SMALL_PA} PA. Red = better than MLB average, '
                                       'blue = worse. BB+, CT+, SD+ are raw (not regressed).'
                ).font = Font(italic=True, color='666666')
        c0 = write_header(ws, 4, 'Month')
        r = 6
        color_rows = []
        for m in months:
            row = ours.get((hname, m))
            ws.cell(row=r, column=1, value=m).font = Font(bold=True)
            pa = row.get('pa') if row else 0
            for j, (key, _, fmt, _) in enumerate(COLS):
                v = row.get(key) if row else None
                if not row and key == 'pa':
                    v = 0
                cell = ws.cell(row=r, column=c0 + j, value=v)
                cell.number_format = fmt
                cell.alignment = Alignment(horizontal='center')
            if (pa or 0) < SMALL_PA:
                for c in range(1, c0 + len(COLS)):
                    ws.cell(row=r, column=c).fill = GREY_FILL
                    ws.cell(row=r, column=c).font = GREY_FONT
            else:
                color_rows.append(r)
            r += 1
        season_r, lg_r = r, r + 1
        ws.cell(row=season_r, column=1, value='Season').font = Font(bold=True)
        ws.cell(row=lg_r, column=1, value='MLB Average').font = Font(italic=True)
        for j, (key, _, fmt, _) in enumerate(COLS):
            sc = ws.cell(row=season_r, column=c0 + j, value=season_value(hname, key))
            sc.number_format, sc.font = fmt, Font(bold=True)
            sc.alignment = Alignment(horizontal='center')
            sc.border = Border(top=Side(style='medium', color=NAVY))
            lc = ws.cell(row=lg_r, column=c0 + j, value=lg_value(key))
            lc.number_format, lc.font = fmt, Font(italic=True, color='555555')
            lc.alignment = Alignment(horizontal='center')
        ws.cell(row=season_r, column=1).border = Border(top=Side(style='medium', color=NAVY))
        if s['pa'] >= SMALL_PA:
            color_rows.append(season_r)
        for rr in color_rows:
            for j, (key, _, _, dr) in enumerate(COLS):
                if dr and key in spreads:
                    f = fill_for(ws.cell(row=rr, column=c0 + j).value, spreads[key], dr)
                    if f:
                        ws.cell(row=rr, column=c0 + j).fill = f
        ws.column_dimensions['A'].width = 12
        for j in range(len(COLS)):
            ws.column_dimensions[get_column_letter(c0 + j)].width = 9.5
        ws.row_dimensions[5].height = 30
        ws.freeze_panes = ws.cell(row=6, column=c0)

    # ── All Data ─────────────────────────────────────────────────────────
    wa = wb.create_sheet('All Data')
    heads = ['Hitter', 'Bats', 'Pos', 'Month', 'Line Source'] + [h for _, h, _, _ in COLS]
    for c, t in enumerate(heads, start=1):
        cell = wa.cell(row=1, column=c, value=t)
        cell.fill, cell.font, cell.alignment = HEAD_FILL, WHITE_BOLD, CENTER
    r = 2
    for hname in hitters:
        s = season_rows[hname]
        for m in months + ['Season']:
            row = ours.get((hname, m))
            if not row:
                continue
            src = row.get('lineSource') if m != 'Season' else 'Leaderboard'
            vals = [pretty(hname), s.get('stands'), s.get('position'), m, src]
            for c, v in enumerate(vals, start=1):
                wa.cell(row=r, column=c, value=v)
            for j, (key, _, fmt, _) in enumerate(COLS):
                v = season_value(hname, key) if m == 'Season' else row.get(key)
                cell = wa.cell(row=r, column=6 + j, value=v)
                cell.number_format = fmt
            r += 1
    wa.auto_filter.ref = f'A1:{get_column_letter(len(heads))}{r - 1}'
    wa.freeze_panes = 'E2'
    wa.column_dimensions['A'].width = 22
    wa.column_dimensions['E'].width = 12
    wa.row_dimensions[1].height = 30

    # ── Definitions ──────────────────────────────────────────────────────
    wd = wb.create_sheet('Definitions')
    for c, t in enumerate(['Stat', 'Group', 'Definition', 'Source', 'Why it is here'], start=1):
        cell = wd.cell(row=1, column=c, value=t)
        cell.fill, cell.font = HEAD_FILL, WHITE_BOLD
    r = 2
    for gname, cs in GROUPS:
        for key, h, _, _ in cs:
            dfn, src, why = DEFS[key]
            for c, v in enumerate([h, gname, dfn, src, why], start=1):
                cell = wd.cell(row=r, column=c, value=v)
                cell.alignment = Alignment(wrap_text=True, vertical='top')
            r += 1
    for col, w in zip('ABCDE', (13, 18, 70, 24, 60)):
        wd.column_dimensions[col].width = w
    wd.freeze_panes = 'A2'

    tmp = OUT + '.tmp.xlsx'
    wb.save(tmp)
    os.replace(tmp, OUT)
    print(f'Wrote {OUT}: {len(hitters)} hitter tabs, spreads for {len(spreads)} coloured stats')


if __name__ == '__main__':
    main()
