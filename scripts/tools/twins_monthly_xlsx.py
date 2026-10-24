#!/usr/bin/env python3
"""twins_monthly_xlsx.py — write the Twins month-by-month hitter workbook.

Reads data/_twins_monthly.json (scripts/tools/twins_monthly_tracker.py) for
the Twins rows and data/team_months/ (scripts/builders/build_team_months.py)
for the all-MLB month pool, and writes
~/Downloads/Twins_Monthly_Hitter_Tracker_2026.xlsx.

Layout, signal first (per Wally 2026-10-24):
  * Overview: one row per hitter, seven headline stats ordered from most to
    least stable month to month, each with a block-character trend over the
    months, the season value, the last month and a change flag.
  * All Hitters: one row per hitter; a dropdown picks Season or a month and
    every cell follows it, so a sort ranks hitters for that window.
  * One tab per hitter: every column by month, ordered by block, most stable
    block first, with a navy rule between blocks. The results block is set in
    a lighter ink because one month of it is mostly noise. (The measured r
    lives in Definitions; headers no longer print it, per Wally 2026-10-24.)
  * All Data (with sample counts), Definitions, Read Me.

Measured here, from every MLB hitter-month in data/team_months:
  * month-to-month r: corr(stat in month m, same stat in month m+1) over
    consecutive pairs with STABILITY_MIN_PA in both. It is a stability read,
    not a reliability coefficient: real change lowers it too.
  * flag noise: SD of (month value - that stint's season value) over months
    with SMALL_PA or more. A month is flagged when it sits more than
    FLAG_SD of those SDs from the hitter's season value.

Conventions, not measured constants: SMALL_PA (grey-out; it sits at SD+'s
190-decision floor, about 50 PA), STABILITY_MIN_PA, FLAG_SD (flags the
outer ~13% of normal month-to-season gaps), and the colour ends (MLB average
+/- 2 SD of 2026 season values among hitters with SPREAD_MIN_PA+).

Values are stored at full precision; every rounding is a cell number format.
Colours are static fills, not colour-scale rules, because Numbers and most
viewers drop those.

Usage: python3 scripts/tools/twins_monthly_xlsx.py
"""
import glob
import json
import os
import statistics
import sys

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.datavalidation import DataValidation

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from pipeline.utils import is_combined_team  # noqa: E402

SRC = os.path.join(REPO, 'data', '_twins_monthly.json')
POOL_DIR = os.path.join(REPO, 'data', 'team_months')
OUT = os.path.expanduser('~/Downloads/Twins_Monthly_Hitter_Tracker_2026.xlsx')
SMALL_PA = 50
STABILITY_MIN_PA = 80
SPREAD_MIN_PA = 200
FLAG_SD = 1.5
DATA_THROUGH = '2026-09-27'

PCT, RATE, INT, DEC1 = '0.0%', '.000', '0', '0.0'
# (key, header, number format, direction: 1 higher is better, -1 lower is
# better, 0 not coloured). Blocks run from the most stable to the least.
GROUPS = [
    ('Sample', [('pa', 'PA', INT, 0)]),
    ('Bat Tracking', [('batSpeed', 'Bat Speed', DEC1, 1), ('swingLength', 'Swing Length', DEC1, 0),
                      ('attackAngle', 'Attack Angle', DEC1, 0), ('blastPct', 'Blast%', PCT, 1)]),
    ('Process', [('processPlus', 'Process+', INT, 1), ('bbPlusU', 'BB+', INT, 1),
                 ('ctPlusU', 'CT+', INT, 1), ('sdPlusU', 'SD+', INT, 1)]),
    ('Approach', [('kPct', 'K%', PCT, -1), ('bbPct', 'BB%', PCT, 1),
                  ('izSwingPct', 'Z-Swing%', PCT, 1), ('izContactPct', 'Z-Contact%', PCT, 1),
                  ('chasePct', 'Chase%', PCT, -1), ('whiffPct', 'Whiff%', PCT, -1)]),
    ('Contact', [('ev95', 'EV95', DEC1, 1), ('hardHitPct', 'Hard-Hit%', PCT, 1),
                 ('barrelPct', 'Barrel%', PCT, 1), ('airPullPct', 'AirPull%', PCT, 1),
                 ('gbPct', 'GB%', PCT, -1), ('medLA', 'Med LA', DEC1, 0)]),
    ('Results', [
        ('avg', 'AVG', RATE, 1), ('obp', 'OBP', RATE, 1), ('slg', 'SLG', RATE, 1),
        ('hr', 'HR', INT, 0), ('wRCplus', 'wRC+', INT, 1), ('xWRCplus', 'xwRC+', INT, 1),
        ('wOBAcon', 'wOBAcon', RATE, 1), ('xwOBAcon', 'xwOBAcon', RATE, 1)]),
]
COLS = [c for _, cs in GROUPS for c in cs]
META = {k: (h, fmt, d) for k, h, fmt, d in COLS}
RESULT_KEYS = {k for k, _, _, _ in GROUPS[-1][1]}
SAMPLE_COLS = [('count', 'Pitches', INT, 0), ('nSwings', 'Swings', INT, 0), ('nBip', 'BIP', INT, 0)]
PLUS_LEAGUE = {'processPlus', 'bbPlusU', 'ctPlusU', 'sdPlusU', 'wRCplus', 'xWRCplus'}
SEASON_FROM_RAW = {'bbPlusU', 'ctPlusU', 'sdPlusU', 'wOBAcon'}   # season row reads our Season group
# Overview headline stats, most stable first.
HEADLINE = ['batSpeed', 'ev95', 'whiffPct', 'chasePct', 'processPlus', 'xWRCplus', 'wRCplus']
BLOCKS = '▁▂▃▄▅▆▇█'

GOOD, MID, BAD = 'F4A582', 'FFFFFF', '92C5DE'
GOOD_INK, BAD_INK, NEUTRAL_INK = 'B0402F', '3E6A94', '777777'
NAVY = '002B5C'          # Twins navy, headers only
GREY_FILL = PatternFill('solid', fgColor='EDEDED')
GREY_FONT = Font(color='9A9A9A')
NOISE_INK = '7A7A7A'
HEAD_FILL = PatternFill('solid', fgColor=NAVY)
GROUP_FILL = PatternFill('solid', fgColor='D9DEE8')
WHITE_BOLD = Font(color='FFFFFF', bold=True)
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
MID_ALIGN = Alignment(horizontal='center')
SECTION_RULE = Side(style='medium', color=NAVY)   # left edge of each stat block
ONE_LINE = Alignment(horizontal='center', vertical='center', wrap_text=False)   # column headers never wrap


def shown(v, fmt):
    """The text a cell displays for value v under number format fmt."""
    if v is None or v == '':
        return ''
    if fmt == PCT:
        return f'{v * 100:.1f}%'
    if fmt == RATE:
        t = f'{v:.3f}'
        return t[1:] if t.startswith('0.') else t
    if fmt == INT:
        return f'{v:.0f}'
    if fmt == DEC1:
        return f'{v:.1f}'
    return str(v)


def fit_width(header, longest=0, bold_header=True):
    """Column width that fits its contents on one line: the header (bold, so
    ~15% wider per character) and the longest displayed value (per Wally
    2026-10-24: headers never wrap, columns sized to their contents)."""
    return round(max(len(header) * (1.15 if bold_header else 1.0), longest * 1.05) + 2.2, 1)

DEFS = {
    'pa': ('Plate appearances. Official line from FanGraphs for the month.', 'FanGraphs', 'The sample size behind every rate. Read it first.'),
    'count': ('Pitches seen.', 'Statcast', 'Sample size for the swing-decision stats.'),
    'nSwings': ('Swings, bunts excluded.', 'Statcast', 'Sample size for contact and whiff rates.'),
    'nBip': ('Balls in play, bunts excluded, home runs included.', 'Statcast', 'Sample size for the contact-quality stats.'),
    'batSpeed': ('Average bat speed on competitive swings.', 'Statcast bat tracking', 'A physical tool and the most stable stat here. A drop shows before the results do.'),
    'swingLength': ('Average swing length, feet.', 'Statcast bat tracking', 'Swing shape. A move flags a swing change. Not coloured.'),
    'attackAngle': ('Average vertical bat angle at contact, degrees.', 'Statcast bat tracking', 'Swing plane. A move flags a swing change. Not coloured.'),
    'blastPct': ('Swings that were both fast and squared up.', 'Statcast bat tracking', 'The swing outcome most tied to damage, and stable month to month.'),
    'processPlus': ('Composite of raw BB+ (52%), SD+ (17%) and CT+ (31%), scaled so one point = one percent of wRC+. 100 = league average.', 'Huronalytics', 'One process number, four times as stable month to month as wRC+.'),
    'bbPlusU': ('Batted-ball quality: 60% xwOBAcon, 40% 95th-percentile exit velocity. RAW: not regressed toward 100.', 'Huronalytics', 'Contact quality that stabilizes fast.'),
    'ctPlusU': ('Contact+: contact rate on swings against what the league makes on the same pitches, leverage weighted. RAW.', 'Huronalytics', 'Bat-to-ball skill with pitch difficulty removed.'),
    'sdPlusU': ('Swing Decisions+: the run value of each swing or take for its location and count. RAW.', 'Huronalytics', 'Approach quality, independent of the umpire.'),
    'kPct': ('Strikeouts / PA.', 'FanGraphs', 'Stabilizes fast. An early sign of a change.'),
    'bbPct': ('Walks (including intentional) / PA.', 'FanGraphs', 'Plate discipline outcome.'),
    'izSwingPct': ('Swing rate at pitches in the strike zone.', 'Statcast', 'Aggression on strikes; higher is better.'),
    'izContactPct': ('Contact rate on swings at strikes.', 'Statcast', 'Bat-to-ball on the pitches he should hit.'),
    'chasePct': ('Swing rate at pitches outside the strike zone.', 'Statcast', 'The clearest discipline signal. Stable in one month.'),
    'whiffPct': ('Misses / swings, bunts excluded.', 'Statcast', 'Swing-and-miss. Moves with bat-speed and approach changes.'),
    'ev95': ('95th-percentile exit velocity: his hardest regular contact.', 'Statcast', 'Steadier than max or average EV. A drop can flag fatigue or injury.'),
    'hardHitPct': ('Share of batted balls at 95+ mph.', 'Statcast', 'Contact quality.'),
    'barrelPct': ('Barrels / balls in play (official Statcast barrel).', 'Statcast', 'The best contact type for damage.'),
    'airPullPct': ('Share of batted balls hit in the air to the pull side.', 'Statcast', 'The most productive batted-ball direction.'),
    'gbPct': ('Ground-ball share.', 'Statcast', 'Batted-ball profile; lower is better.'),
    'medLA': ('Median launch angle.', 'Statcast', 'Swing plane on contact. Not coloured.'),
    'avg': ('Batting average.', 'FanGraphs', 'Expected on any sheet; the least stable stat month to month.'),
    'obp': ('On-base percentage.', 'FanGraphs', 'Expected on any sheet.'),
    'slg': ('Slugging percentage.', 'FanGraphs', 'Expected on any sheet.'),
    'hr': ('Home runs.', 'FanGraphs', 'Expected on any sheet.'),
    'wRCplus': ('Weighted runs created plus. Park and league adjusted. 100 = league average.', 'FanGraphs (date range)', 'The standard all-in offense number. Read it beside xwRC+.'),
    'xWRCplus': ('wRC+ built from xwOBA (exit velocity and launch angle) instead of actual outcomes. 100 = league average.', 'Huronalytics', 'What the contact deserved. The wRC+ - xwRC+ gap is mostly luck.'),
    'wOBAcon': ('wOBA on balls in play (bunts out, home runs in), priced with the 2026 wOBA weights.', 'Statcast, computed for this sheet', 'Production on contact only, so K and BB do not hide it.'),
    'xwOBAcon': ('Expected wOBA on balls in play.', 'Statcast', 'Paired with wOBAcon: contact quality without defense or luck.'),
}


def pretty(name):
    last, _, first = name.partition(', ')
    return f'{first} {last}'.strip()


def load_pool():
    rows = []
    for f in sorted(glob.glob(os.path.join(POOL_DIR, '*.json'))):
        if os.path.basename(f) == 'index.json':
            continue
        with open(f) as fh:
            rows.extend(json.load(fh)['rows'])
    if not rows:
        raise SystemExit(f'No rows in {POOL_DIR}. Run scripts/builders/build_team_months.py first.')
    return rows


def corr(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / (sxx * syy) ** 0.5 if sxx > 0 and syy > 0 else None


def pool_measures(pool, months):
    """Month-to-month r and the month-vs-season noise SD per stat."""
    by = {}
    season = {}
    for r in pool:
        if r['month'] == 'Season':
            season[(r['hitter'], r['team'])] = r
        elif r['month'] in months:
            by[(r['hitter'], r['team'], months.index(r['month']))] = r
    stab, noise = {}, {}
    for k, _, _, _ in COLS:
        if k == 'pa':
            continue
        xs, ys = [], []
        for (h, t, i), a in by.items():
            b = by.get((h, t, i + 1))
            if (b is None or (a.get('pa') or 0) < STABILITY_MIN_PA
                    or (b.get('pa') or 0) < STABILITY_MIN_PA
                    or a.get(k) is None or b.get(k) is None):
                continue
            xs.append(a[k])
            ys.append(b[k])
        if len(xs) >= 50:
            stab[k] = (corr(xs, ys), len(xs))
        gaps = [a[k] - season[(h, t)][k] for (h, t, _), a in by.items()
                if (a.get('pa') or 0) >= SMALL_PA and a.get(k) is not None
                and (h, t) in season and season[(h, t)].get(k) is not None]
        if len(gaps) >= 50:
            noise[k] = statistics.pstdev(gaps)
    return stab, noise


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


def scale_t(v, spread):
    """Position of v on the colour scale, -1 (low end) to 1 (high end)."""
    lo, mid, hi = spread
    t = (v - mid) / (hi - mid) if v >= mid else (v - mid) / (mid - lo)
    return max(-1.0, min(1.0, t))


def fill_for(v, spread, direction):
    """Static three-point fill: BAD at the low end, white at the MLB average,
    GOOD at the high end (reversed when lower is better)."""
    if v is None or not direction or spread is None:
        return None
    t = scale_t(v, spread) * direction
    end = GOOD if t > 0 else BAD
    a = abs(t)
    rgb = [round(int(MID[i:i + 2], 16) * (1 - a) + int(end[i:i + 2], 16) * a) for i in (0, 2, 4)]
    return PatternFill('solid', fgColor='%02X%02X%02X' % tuple(rgb))


def header_band(ws, row, col, groups):
    """Group band on `row`, column headers on row + 1, from column `col`."""
    for gname, cs in groups:
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + len(cs) - 1)
        g = ws.cell(row=row, column=col, value=gname)
        g.fill, g.font, g.alignment = GROUP_FILL, Font(bold=True, color=NAVY), CENTER
        for _, h, _, _ in cs:
            cell = ws.cell(row=row + 1, column=col, value=h)
            cell.fill, cell.font, cell.alignment = HEAD_FILL, WHITE_BOLD, ONE_LINE
            col += 1
    return col


def main():
    with open(SRC) as f:
        d = json.load(f)
    with open(os.path.join(REPO, 'data', 'hitter_leaderboard_rs.json')) as f:
        season_all = json.load(f)
    months, lg = d['months'], d['leagueAverages']
    season_rows = {r['hitter']: r for r in d['seasonRows']}
    ours = {(r['hitter'], r['month']): r for r in d['rows']}
    spreads = season_spreads(season_all, lg)
    stab, noise = pool_measures(load_pool(), months)
    hitters = sorted(season_rows, key=lambda h: (-season_rows[h]['pa'], h))
    print('Month-to-month r (pairs):  ' + ', '.join(
        f'{META[k][0]} {stab[k][0]:.2f}' for k in HEADLINE if k in stab))

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

    # One width per stat for every tab: the header or the longest value the
    # stat shows anywhere (any hitter, any month, the season, MLB average).
    stat_width = {}
    for k, h, fmt, _ in COLS:
        vals = [shown(r.get(k), fmt) for r in ours.values()]
        vals += [shown(season_value(hh, k), fmt) for hh in hitters] + [shown(lg_value(k), fmt)]
        stat_width[k] = fit_width(h, max(len(v) for v in vals))
    for gname, cs in GROUPS:          # a one-column block also holds its band label
        if len(cs) == 1:
            stat_width[cs[0][0]] = max(stat_width[cs[0][0]], fit_width(gname))

    wb = Workbook()

    # ── Read Me ──────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = 'Read Me'
    h1, h2 = Font(bold=True, size=16, color=NAVY), Font(bold=True, color=NAVY)
    lines = [
        ('Minnesota Twins: Month-by-Month Hitter Tracker, 2026', h1),
        (f'Regular season, data through {DATA_THROUGH}. Every hitter with a Twins plate appearance ({len(hitters)}).', None),
        ('', None),
        ('THE IDEA', h2),
        ('A tracking sheet answers one question: who changed, and is the change real? One month is about 100 PA, and most results stats are noise at that size.', None),
        (f'So the columns run from the most stable month to month to the least: bat tracking (bat speed r .96), process, approach, contact, then results (wRC+ r .10), which are set in lighter ink. r is how well one month of a stat predicts the next month (all MLB hitter-months, {STABILITY_MIN_PA}+ PA in both); Definitions lists it for every stat.', None),
        ('', None),
        ('TABS', h2),
        ('Overview: the 10-second view. Seven headline stats per hitter, most stable first: a trend across the months, the season value, the latest month, and the change. Hitters with the most real changes are listed first.', None),
        ('All Hitters: one row per hitter with every stat. Pick Season or a month in the yellow cell and the whole page follows; sort with the filter buttons on the MLB Average row. Colours on this tab are live rules: Excel and Google Sheets draw them, Numbers does not.', None),
        ('One tab per hitter (most PA first): every stat by month, with his season line and the MLB average below.', None),
        ('All Data: one row per hitter-month, with sample counts and filters, for sorting and pivots.', None),
        ('Definitions: what each stat is, where it comes from, its month-to-month r, and why it is in the sheet.', None),
        ('', None),
        ('HOW TO READ IT', h2),
        ('Hitter tabs: fill colour compares a value with the MLB average: red better, blue worse, white average. Uncoloured columns describe style, not quality.', None),
        ('The colour ends sit at the MLB average plus or minus two standard deviations of 2026 season values (hitters with 200+ PA).', None),
        (f'Trend (Overview): one mark per month under the letters A M J J A S (Mar/Apr to Sep); taller = higher value on that stat\'s league scale. A dot is a month with no data or under {SMALL_PA} PA.', None),
        (f'Change (Overview): his latest month with {SMALL_PA}+ PA minus his season value. The Overview has only one colour code: a Change cell is filled when it is bigger than {FLAG_SD} standard deviations of normal monthly noise. Red = better, blue = worse. The cutoff is a convention: it flags about the outer 13% of ordinary months.', None),
        (f'Grey rows: fewer than {SMALL_PA} PA in the month. Too small to read; left uncoloured.', None),
        ('', None),
        ('NOTES', h2),
        ('Late-March games (Opening Day 3/26) are counted in April.', None),
        ('BB+, CT+ and SD+ are RAW in every row, including the season row: not regressed toward 100. They differ from the regressed values on the leaderboard.', None),
        ('SD+ needs 190 swing decisions and CT+ needs 65 swings in the month; below that they are blank, and so is Process+.', None),
        ('James Outman also batted for another club in June, so his June line is from Twins pitches only, not the FanGraphs line.', None),
        ('Ryan Jeffers: the monthly FanGraphs PA sum to 368; his official season total is 369.', None),
        ('', None),
        ('SOURCES', h2),
        ('Statcast pitch-level data (Baseball Savant / MLB). FanGraphs date-range lines for PA, slash line, HR, K%, BB% and wRC+.', None),
        ('Huronalytics metrics (Process+, BB+, CT+, SD+, xwRC+): huronalytics.vercel.app. Each month is scored on season league baselines.', None),
    ]
    for i, (text, font) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        if font:
            c.font = font
    ws.column_dimensions['A'].width = 150

    # ── Overview ─────────────────────────────────────────────────────────
    # One colour meaning on this tab: only a Change cell that passes the flag
    # cutoff is filled (red better, blue worse). Season and Latest are plain.
    wo = wb.create_sheet('Overview')
    wo.cell(row=1, column=1, value='Overview: who changed, and is it real?').font = Font(bold=True, size=14, color=NAVY)
    wo.cell(row=2, column=1, value=(
        f'Stats run left to right from most to least stable month to month. Trend: one mark per month, Mar/Apr to Sep '
        f'(dot = no data or under {SMALL_PA} PA). Change = latest month minus his season. A coloured Change is bigger '
        f'than {FLAG_SD} SD of normal monthly noise: red = better, blue = worse. Hitters with the most changes are first.'
    )).font = Font(italic=True, color='666666')
    fixed = [('Hitter', 22), ('PA', 6), ('Better', 7.5), ('Worse', 7.5), ('Latest Month', 9)]
    for j, (t, w) in enumerate(fixed, start=1):
        wo.merge_cells(start_row=4, start_column=j, end_row=5, end_column=j)
        c = wo.cell(row=4, column=j, value=t)
        c.fill, c.font, c.alignment = HEAD_FILL, WHITE_BOLD, CENTER
        wo.column_dimensions[get_column_letter(j)].width = w
    month_letters = ' '.join(m[-3] if m == 'Mar/Apr' else m[0] for m in months)   # A M J J A S
    col = len(fixed) + 1
    starts = {}
    for k in HEADLINE:
        starts[k] = col
        wo.merge_cells(start_row=4, start_column=col, end_row=4, end_column=col + 3)
        g = wo.cell(row=4, column=col, value=META[k][0])
        g.fill, g.font, g.alignment = GROUP_FILL, Font(bold=True, color=NAVY, size=12), CENTER
        for j, t in enumerate([month_letters, 'Season', 'Latest', 'Change']):
            c = wo.cell(row=5, column=col + j, value=t)
            c.fill, c.alignment = HEAD_FILL, CENTER
            c.font = (Font(name='Courier New', bold=True, color='FFFFFF') if j == 0 else WHITE_BOLD)
        for j, w in enumerate([14, 8, 8, 9]):
            wo.column_dimensions[get_column_letter(col + j)].width = w
        col += 4

    def delta_text(v, fmt):
        """Signed, parenthesised vs-season delta (the one place a + sign is
        allowed). Written as text: Numbers double-prints the minus of a
        '(+0.0);(-0.0)' number format, Excel and Sheets do not."""
        if v is None:
            return None
        if fmt == PCT:
            body = f'{abs(v) * 100:.1f}%'
        elif fmt == INT:
            body = f'{abs(v):.0f}'
        else:
            body = f'{abs(v):.1f}'
        if body.strip('0.%') == '':
            return f'({body})'
        return f'({"+" if v > 0 else "-"}{body})'

    entries = []
    for hname in hitters:
        s = season_rows[hname]
        qual = [m for m in months if (ours.get((hname, m)) or {}).get('pa', 0) >= SMALL_PA]
        last_m = qual[-1] if qual else None
        small_season = s['pa'] < SMALL_PA
        cells, better, worse = {}, 0, 0
        for k in HEADLINE:
            _, fmt, dr = META[k]
            spread = spreads.get(k)
            marks = []
            for m in months:
                mr = ours.get((hname, m))
                v = mr.get(k) if mr else None
                if v is None or (mr.get('pa') or 0) < SMALL_PA:
                    marks.append('·')
                else:
                    t = (scale_t(v, spread) + 1) / 2 if spread else 0.5
                    marks.append(BLOCKS[min(len(BLOCKS) - 1, int(t * len(BLOCKS)))])
            sv = season_value(hname, k)
            lv = ours[(hname, last_m)].get(k) if last_m else None
            delta = (lv - sv) if (lv is not None and sv is not None) else None
            flag = 0
            if delta is not None and not small_season and noise.get(k, 0) > 0 and abs(delta) / noise[k] > FLAG_SD:
                flag = 1 if delta * (dr or 1) > 0 else -1
                better += flag > 0
                worse += flag < 0
            cells[k] = (' '.join(marks), sv, lv, delta, flag)
        entries.append((hname, s, last_m, small_season, better, worse, cells))
    entries.sort(key=lambda e: (e[3], -(e[4] + e[5]), -e[1]['pa'], e[0]))

    n_flags = 0
    r = 6
    for hname, s, last_m, small_season, better, worse, cells in entries:
        ink = GREY_FONT if small_season else None
        wo.cell(row=r, column=1, value=pretty(hname)).font = ink or Font(bold=True)
        wo.cell(row=r, column=2, value=s['pa']).alignment = MID_ALIGN
        for cc, n, color in ((3, better, GOOD_INK), (4, worse, BAD_INK)):
            c = wo.cell(row=r, column=cc, value=n)
            c.alignment = MID_ALIGN
            c.font = Font(bold=True, color=color) if n else Font(color='BBBBBB')
        wo.cell(row=r, column=5, value=last_m or '-').alignment = MID_ALIGN
        if small_season:
            for cc in (2, 5):
                wo.cell(row=r, column=cc).font = GREY_FONT
        for k in HEADLINE:
            _, fmt, dr = META[k]
            c0 = starts[k]
            trend, sv, lv, delta, flag = cells[k]
            tc = wo.cell(row=r, column=c0, value=trend)
            tc.font, tc.alignment = Font(name='Courier New', size=11, color=NAVY), MID_ALIGN
            tc.border = Border(left=Side(style='thin', color='B0B0B0'))
            for j, v in ((1, sv), (2, lv)):
                c = wo.cell(row=r, column=c0 + j, value=v)
                c.number_format, c.alignment = fmt, MID_ALIGN
                if small_season:
                    c.font = GREY_FONT
            dc = wo.cell(row=r, column=c0 + 3, value=delta_text(delta, fmt))
            dc.alignment = MID_ALIGN
            if flag:
                dc.fill = PatternFill('solid', fgColor=GOOD if flag > 0 else BAD)
                dc.font = Font(bold=True)
                n_flags += 1
            else:
                dc.font = Font(color='9A9A9A')
        r += 1
    wo.cell(row=r, column=1, value='MLB Average').font = Font(italic=True)
    for k in HEADLINE:
        c = wo.cell(row=r, column=starts[k] + 1, value=lg_value(k))
        c.number_format, c.font, c.alignment = META[k][1], Font(italic=True, color='555555'), MID_ALIGN
    for rr in range(4, 6):
        for k in HEADLINE:
            wo.cell(row=rr, column=starts[k]).border = Border(left=Side(style='thin', color='FFFFFF'))
    wo.freeze_panes = 'F6'
    wo.row_dimensions[5].height = 18
    print(f'Overview: {n_flags} change flags')

    # ── Hitter tables: one writer for the per-hitter tabs and All Hitters ─
    # A Season row closes its hitter's block: thin rule above, navy rule below.
    SEASON_BORDER = Border(top=Side(style='thin', color='8A8A8A'), bottom=Side(style='medium', color=NAVY))

    def section_barriers(ws, c0, r0, r1):
        """A medium navy rule on the left edge of every block after the first
        (Bat Tracking, Process, Approach, Contact, Results), rows r0..r1,
        keeping each cell's top and bottom rules."""
        col = c0
        for i, (_, cs) in enumerate(GROUPS):
            if i:
                for rr in range(r0, r1 + 1):
                    cell = ws.cell(row=rr, column=col)
                    b = cell.border
                    cell.border = Border(left=SECTION_RULE, right=b.right, top=b.top, bottom=b.bottom)
            col += len(cs)

    def write_month_table(ws, title, label_heads, specs):
        """Title, the grouped header, then one row per spec (labels, hitter,
        month). month is a calendar month, 'Season' or 'MLB Average'."""
        ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=14, color=NAVY)
        c0 = len(label_heads) + 1
        for j, t in enumerate(label_heads, start=1):
            ws.cell(row=5, column=j, value=t)
        end = header_band(ws, 4, c0, GROUPS)
        for c in range(1, end):
            ws.cell(row=5, column=c).fill = HEAD_FILL
            ws.cell(row=5, column=c).font = WHITE_BOLD
            ws.cell(row=5, column=c).alignment = ONE_LINE
        r = 6
        for labels, hname, m in specs:
            is_season, is_lg = m == 'Season', m == 'MLB Average'
            row = ours.get((hname, m)) if not (is_season or is_lg) else None
            pa = season_rows[hname]['pa'] if is_season else ((row or {}).get('pa') or 0)
            small = not is_lg and pa < SMALL_PA
            for j, lab in enumerate(labels, start=1):
                lc = ws.cell(row=r, column=j, value=lab)
                lc.font = Font(bold=True, italic=is_lg)
                if small:
                    lc.fill, lc.font = GREY_FILL, GREY_FONT
                if is_season:
                    lc.border = SEASON_BORDER
            for j, (k, _, fmt, dr) in enumerate(COLS):
                if is_lg:
                    v = lg_value(k)
                elif is_season:
                    v = season_value(hname, k)
                else:
                    v = row.get(k) if row else (0 if k == 'pa' else None)
                c = ws.cell(row=r, column=c0 + j, value=v)
                c.number_format, c.alignment = fmt, MID_ALIGN
                if is_lg:
                    c.font = Font(bold=True, italic=True, color='555555')
                elif small:
                    c.fill, c.font = GREY_FILL, GREY_FONT
                else:
                    f = fill_for(v, spreads.get(k), dr)
                    if f:
                        c.fill = f
                    ink = NOISE_INK if k in RESULT_KEYS else '000000'
                    c.font = Font(bold=is_season, color=ink)
                if is_season:
                    c.border = SEASON_BORDER
            r += 1
        section_barriers(ws, c0, 4, r - 1)
        for j, t in enumerate(label_heads, start=1):
            longest = max(len(str(lab[j - 1] or '')) for lab, _, _ in specs)
            ws.column_dimensions[get_column_letter(j)].width = fit_width(t, longest * 1.1)
        for j, (k, _, _, _) in enumerate(COLS):
            ws.column_dimensions[get_column_letter(c0 + j)].width = stat_width[k]
        # Rows 1-6 stay put: title, band, header and MLB Average.
        ws.freeze_panes = ws.cell(row=7, column=c0)

    # ── All Hitters: one row per hitter, Season or a month picked in B3 ──
    # Every stat cell is a lookup into All Data keyed on hitter|month, so one
    # dropdown switches the whole page and a sort ranks hitters, not
    # hitter-months. Colours and the grey-out are conditional-formatting rules
    # so they follow the picked month: Excel and Google Sheets draw them,
    # Numbers does not. Layout per Wally (2026-10-24): row 2 empty, MLB
    # Average in row 6 under the header, hitters from row 7.
    all_cols = [COLS[0]] + SAMPLE_COLS + COLS[1:]
    ad_col = {k: get_column_letter(6 + j) for j, (k, _, _, _) in enumerate(all_cols)}
    ad_key = get_column_letter(6 + len(all_cols))
    ad_last = 1 + sum(1 for h in hitters for m in months + ['Season'] if (h, m) in ours)
    wall = wb.create_sheet('All Hitters')
    wall.cell(row=1, column=1, value='Minnesota Twins').font = Font(bold=True, size=14, color=NAVY)
    wall.cell(row=3, column=1, value='Month').font = Font(bold=True, color=NAVY)
    pick = wall.cell(row=3, column=2, value='Season')
    pick.font, pick.alignment = Font(bold=True, size=12), MID_ALIGN
    pick.fill = PatternFill('solid', fgColor='FFF2CC')
    pick.border = Border(*(Side(style='medium', color=NAVY),) * 4)
    dv = DataValidation(type='list', formula1='"' + ','.join(['Season'] + months) + '"', allow_blank=False,
                        showDropDown=False)
    dv.error, dv.errorTitle = 'Pick Season or a month from the list.', 'Month'
    wall.add_data_validation(dv)
    dv.add('B3')
    wall.cell(row=3, column=3, value='◀ pick a month').font = Font(italic=True, color='666666')
    end = header_band(wall, 4, 2, GROUPS)
    hc = wall.cell(row=5, column=1, value='Hitter')
    hc.fill, hc.font, hc.alignment = HEAD_FILL, WHITE_BOLD, ONE_LINE
    lg_row = 6
    wall.cell(row=lg_row, column=1, value='MLB Average (season)').font = Font(bold=True, italic=True)
    for j, (k, _, fmt, _) in enumerate(COLS):
        c = wall.cell(row=lg_row, column=2 + j, value=lg_value(k))
        c.number_format, c.font, c.alignment = fmt, Font(bold=True, italic=True, color='555555'), MID_ALIGN
    first = 7
    for i, hname in enumerate(hitters):
        r = first + i
        wall.cell(row=r, column=1, value=pretty(hname)).font = Font(bold=True)
        for j, (k, _, fmt, _) in enumerate(COLS):
            col = ad_col[k]
            # A missing value must come back as a TRUE blank, not "": Sheets
            # sorts text above numbers, so "" cells led every Z-to-A sort
            # (Wally 2026-10-24). IF with an empty argument returns a real
            # blank in Sheets, which sorts last; tested in a scratch Sheet.
            # Excel shows that empty argument as 0. Both a hitter-month with
            # no row (MATCH fails) and an empty source cell end up blank.
            m = f"MATCH($A{r}&\"|\"&$B$3,'All Data'!${ad_key}$2:${ad_key}${ad_last},0)"
            ix = f"INDEX('All Data'!${col}$2:${col}${ad_last},{m})"
            c = wall.cell(row=r, column=2 + j, value=f'=IF(ISNA({m}),,IF({ix}="",,{ix}))')
            c.number_format, c.alignment = fmt, MID_ALIGN
            if k in RESULT_KEYS:
                c.font = Font(color=NOISE_INK)
    last = first + len(hitters) - 1
    last_col = get_column_letter(end - 1)
    # Grey-out first, so it wins over the colour scales (Sheets applies the
    # first matching rule; Excel honours stopIfTrue).
    wall.conditional_formatting.add(
        f'A{first}:{last_col}{last}',
        FormulaRule(formula=[f'OR($B{first}="",$B{first}<{SMALL_PA})'], fill=GREY_FILL,
                    font=Font(color='9A9A9A'), stopIfTrue=True))
    for j, (k, _, _, dr) in enumerate(COLS):
        if not dr or k not in spreads:
            continue
        lo, mid, hi = spreads[k]
        lo_c, hi_c = (BAD, GOOD) if dr > 0 else (GOOD, BAD)
        letter = get_column_letter(2 + j)
        wall.conditional_formatting.add(f'{letter}{first}:{letter}{last}', ColorScaleRule(
            start_type='num', start_value=lo, start_color=lo_c,
            mid_type='num', mid_value=mid, mid_color=MID,
            end_type='num', end_value=hi, end_color=hi_c))
    section_barriers(wall, 2, 4, last)
    # The filter's header row is MLB Average (row 6), so a sort moves the
    # hitter rows only and the league row stays put under the header.
    wall.auto_filter.ref = f'A{lg_row}:{last_col}{last}'
    wall.column_dimensions['A'].width = fit_width('Hitter', max(len('MLB Average (season)'),
                                                                max(len(pretty(hh)) for hh in hitters)) * 1.1)
    for j, (k, _, _, _) in enumerate(COLS):
        wall.column_dimensions[get_column_letter(2 + j)].width = stat_width[k]
    wall.freeze_panes = 'B7'

    # ── One tab per hitter ───────────────────────────────────────────────
    used = set()
    for hname in hitters:
        s = season_rows[hname]
        last = hname.split(',')[0][:28]
        title = last if last not in used else pretty(hname)[:31]
        used.add(title)
        write_month_table(
            wb.create_sheet(title),
            f"{pretty(hname)}  |  MIN  |  Bats {s.get('stands') or '-'}  |  "
            f"{s.get('position') or '-'}  |  2026: {s['pa']} PA, {s.get('wRCplus')} wRC+",
            ['Month'], [([m], hname, m) for m in ['MLB Average'] + months + ['Season']])

    # ── All Data ─────────────────────────────────────────────────────────
    wa = wb.create_sheet('All Data')
    heads = ['Hitter', 'Bats', 'Pos', 'Month', 'Line Source'] + [h for _, h, _, _ in all_cols] + ['Key']
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
            for c, v in enumerate([pretty(hname), s.get('stands'), s.get('position'), m, src], start=1):
                wa.cell(row=r, column=c, value=v)
            for j, (key, _, fmt, _) in enumerate(all_cols):
                v = season_value(hname, key) if m == 'Season' else row.get(key)
                cell = wa.cell(row=r, column=6 + j, value=v)
                cell.number_format = fmt
            wa.cell(row=r, column=6 + len(all_cols), value=f'{pretty(hname)}|{m}')   # All Hitters lookup key
            r += 1
    if r - 1 != ad_last:
        raise SystemExit(f'All Data has {r - 2} rows but All Hitters looks up {ad_last - 1}; nothing was written.')
    wa.column_dimensions[ad_key].hidden = True
    wa.auto_filter.ref = f'A1:{get_column_letter(len(heads))}{r - 1}'
    wa.freeze_panes = 'E2'
    wa.column_dimensions['A'].width = 22
    wa.column_dimensions['E'].width = 12
    wa.row_dimensions[1].height = 30

    # ── Definitions ──────────────────────────────────────────────────────
    wd = wb.create_sheet('Definitions')
    for c, t in enumerate(['Stat', 'Block', 'Month-to-month r', 'Definition', 'Source', 'Why it is here'], start=1):
        cell = wd.cell(row=1, column=c, value=t)
        cell.fill, cell.font, cell.alignment = HEAD_FILL, WHITE_BOLD, CENTER
    r = 2
    for gname, cs in GROUPS:
        for key, h, _, _ in cs:
            dfn, src, why = DEFS[key]
            rv = round(stab[key][0], 2) if key in stab else None
            for c, v in enumerate([h, gname, rv, dfn, src, why], start=1):
                cell = wd.cell(row=r, column=c, value=v)
                cell.alignment = Alignment(wrap_text=True, vertical='top',
                                           horizontal='center' if c == 3 else 'left')
            wd.cell(row=r, column=3).number_format = '.00'
            r += 1
    for key, h, _, _ in SAMPLE_COLS:
        dfn, src, why = DEFS[key]
        for c, v in enumerate([h, 'Sample (All Data only)', None, dfn, src, why], start=1):
            wd.cell(row=r, column=c, value=v).alignment = Alignment(wrap_text=True, vertical='top')
        r += 1
    wd.cell(row=r + 1, column=1, value=(
        f'Month-to-month r: correlation of a stat in one month with the same stat in the next month, over every '
        f'2026 MLB hitter with {STABILITY_MIN_PA}+ PA in both months ({stab["batSpeed"][1]} pairs). It reads stability, '
        'not reliability: a real change in a hitter also lowers it.')).font = Font(italic=True, color='555555')
    for col, w in zip('ABCDEF', (13, 22, 10, 62, 22, 58)):
        wd.column_dimensions[col].width = w
    wd.freeze_panes = 'A2'

    # All Hitters is formulas with no cached values; make Excel compute them on open.
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    tmp = OUT + '.tmp.xlsx'
    wb.save(tmp)
    os.replace(tmp, OUT)
    print(f'Wrote {OUT}: {len(hitters)} hitter tabs, {len(COLS)} columns, '
          f'spreads for {len(spreads)} coloured stats')


if __name__ == '__main__':
    main()
