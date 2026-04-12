"""
Pitcher Card Generator — 4 Aesthetic Concepts
Generates 4 visually distinct versions of the same pitcher stat card.
Data is loaded once, rendered 4 times with different styling.
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Ellipse, FancyBboxPatch, Rectangle
from matplotlib.font_manager import FontProperties
from PIL import Image
from io import BytesIO
import urllib.request
import numpy as np
from collections import defaultdict
from math import atan2, sin, cos
import gspread
from google.oauth2.service_account import Credentials

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
PITCHER_NAME = 'Fried, Max'
SHEET_KEY = '1hzAtZ_Wqi8ZuUHaGvgjJcQMU5jj5CzGXuBtjYmPOj9U'
WORKSHEET_NAME = 'NYY'
PLAYER_ID = '608331'
DISPLAY_NAME = 'Max Fried'
HAND = 'LHP'
TEAM = 'NYY'
AGE = '31'
GAME_DATE = 'March 25, 2026'
STAT_HEADERS = ['IP', 'TBF', 'R', 'ER', 'H', 'K', 'BB', 'HR']
STAT_VALUES = ['6.1', '23', '0', '0', '3', '4', '1', '0']

PITCH_COLORS = {
    'FF': '#0000FF', 'SI': '#FFD700', 'CF': '#8B4513', 'FC': '#FFA500',
    'SL': '#006400', 'ST': '#FF1493', 'CU': '#B22222', 'SV': '#32CD32',
    'CH': '#800080', 'FS': '#40E0D0', 'KN': '#000000'
}
PITCH_NAMES = {
    'FF': 'Fastball', 'SI': 'Sinker', 'CF': 'Cut-Fastball', 'FC': 'Cutter',
    'SL': 'Slider', 'ST': 'Sweeper', 'CU': 'Curveball', 'SV': 'Slurve',
    'CH': 'Changeup', 'FS': 'Splitter', 'KN': 'Knuckleball'
}
PITCH_ORDER = ['FF', 'SI', 'CF', 'FC', 'SL', 'ST', 'CU', 'SV', 'CH', 'FS', 'KN']
SWING_DESC = ['Swinging Strike', 'Foul', 'Foul Bunt', 'In Play', 'Missed Bunt']
STRIKE_DESC = ['Called Strike', 'Swinging Strike', 'Foul', 'Foul Bunt', 'In Play']

# Layout constants (preserved from v23)
TABLE_LEFT_FIG = 0.01
TABLE_RIGHT_FIG = 0.99
PLOT_AXES_RIGHT = 1.07
USAGE_SHIFT = 0.18
DIVIDER_COL = 14
FIG_W, FIG_H = 16, 15
DPI = 100
SAVE_DPI = 150


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (unchanged from v23)
# ═══════════════════════════════════════════════════════════════
def sf(v):
    if v is None or v == '': return None
    try: return float(v)
    except: return None

def avg_tilt(tilts):
    valid = [t for t in tilts if t and t != '']
    if not valid: return '—'
    sins, coss = [], []
    for t in valid:
        parts = str(t).split(':')
        if len(parts) != 2: continue
        h, m = int(parts[0]), int(parts[1])
        if h == 12: h = 0
        a = (h * 60 + m) / 720 * 2 * 3.14159
        sins.append(sin(a)); coss.append(cos(a))
    if not sins: return '—'
    am = (atan2(sum(sins)/len(sins), sum(coss)/len(coss)) * 720 / (2*3.14159)) % 720
    h, m = int(am // 60), int(am % 60)
    if h == 0: h = 12
    return f'{h}:{m:02d}'

def fmt_fi(v):
    if v is None: return '—'
    neg = v < 0; av = abs(v); ft = int(av); inc = round((av - ft) * 12)
    if inc == 12: ft += 1; inc = 0
    s = f"{ft}'{inc}\""; return f"-{s}" if neg else s

def compute_iz(p):
    px, pz, st, sb = sf(p.get('PlateX')), sf(p.get('PlateZ')), sf(p.get('SzTop')), sf(p.get('SzBot'))
    if any(v is None for v in [px, pz, st, sb]): return None
    return abs(px) <= 0.83 and pz >= sb - 0.121 and pz <= st + 0.121


# ═══════════════════════════════════════════════════════════════
# DATA LOADING (shared across all concepts)
# ═══════════════════════════════════════════════════════════════
print("Loading data from Google Sheets...")
creds = Credentials.from_service_account_file('service_account.json',
    scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
gc = gspread.authorize(creds)
fried = [r for r in gc.open_by_key(SHEET_KEY).worksheet(WORKSHEET_NAME).get_all_records()
         if r.get('Pitcher') == PITCHER_NAME]

print("Fetching headshot...")
headshot_raw = Image.open(BytesIO(urllib.request.urlopen(urllib.request.Request(
    f'https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/{PLAYER_ID}/headshot/67/current',
    headers={'User-Agent': 'Mozilla/5.0'})).read()))
ha = np.array(headshot_raw.convert('RGBA'))
gm = ((np.abs(ha[:,:,0].astype(int)-ha[:,:,1].astype(int))<15) &
      (np.abs(ha[:,:,1].astype(int)-ha[:,:,2].astype(int))<15) &
      (ha[:,:,0]>170) & (ha[:,:,0]<230))
ha[gm] = [255,255,255,255]
headshot = Image.fromarray(ha)

# ═══════════════════════════════════════════════════════════════
# COMPUTE STATS (shared across all concepts)
# ═══════════════════════════════════════════════════════════════
print("Computing stats...")
tc = len(fried)
groups = defaultdict(list)
for p in fried:
    pt, hb, ivb = p.get('Pitch Type', ''), p.get('HorzBrk'), p.get('IndVertBrk')
    if pt and hb != '' and ivb != '':
        try: groups[pt].append((float(hb), float(ivb)))
        except: pass

usage = {'L': defaultdict(int), 'R': defaultdict(int)}
tots = {'L': 0, 'R': 0}
for p in fried:
    bh, pt = p.get('Bats', ''), p.get('Pitch Type', '')
    if bh in ('L', 'R') and pt: usage[bh][pt] += 1; tots[bh] += 1

pitch_stats = []
all_iz_wh = 0; all_iz_sw = 0; all_ooz_sw = 0; all_ooz_n = 0; all_bip = []; all_hard = 0
for pt in PITCH_ORDER:
    pp = [p for p in fried if p.get('Pitch Type') == pt]
    if not pp: continue
    n = len(pp)
    velos = [v for v in (sf(p.get('Velocity')) for p in pp) if v]
    spins = [v for v in (sf(p.get('Spin Rate')) for p in pp) if v]
    ivbs = [v for v in (sf(p.get('IndVertBrk')) for p in pp) if v is not None]
    hbs = [v for v in (sf(p.get('HorzBrk')) for p in pp) if v is not None]
    relzs = [v for v in (sf(p.get('RelPosZ')) for p in pp) if v is not None]
    relxs = [v for v in (sf(p.get('RelPosX')) for p in pp) if v is not None]
    exts = [v for v in (sf(p.get('Extension')) for p in pp) if v is not None]
    vaas = [v for v in (sf(p.get('VAA')) for p in pp) if v is not None]
    haas = [v for v in (sf(p.get('HAA')) for p in pp) if v is not None]
    tilts = [p.get('OTilt', '') for p in pp]
    swings = [p for p in pp if p.get('Description') in SWING_DESC]
    whiffs = [p for p in pp if p.get('Description') == 'Swinging Strike']
    strikes = [p for p in pp if p.get('Description') in STRIKE_DESC]
    csw = [p for p in pp if p.get('Description') in ['Called Strike', 'Swinging Strike']]
    iz_n = iz_sw = ooz_n = ooz_sw = iz_wh = 0
    for p in pp:
        r = compute_iz(p)
        if r is None: continue
        if r:
            iz_n += 1
            if p.get('Description') in SWING_DESC: iz_sw += 1
            if p.get('Description') == 'Swinging Strike': iz_wh += 1
        else:
            ooz_n += 1
            if p.get('Description') in SWING_DESC: ooz_sw += 1
    all_iz_wh += iz_wh; all_iz_sw += iz_sw; all_ooz_sw += ooz_sw; all_ooz_n += ooz_n
    bip = [p for p in pp if p.get('Description') == 'In Play' and p.get('BBType')
           and not str(p.get('BBType', '')).startswith('bunt')]
    hard = sum(1 for p in bip if sf(p.get('ExitVelo')) and float(p['ExitVelo']) >= 95)
    all_bip.extend(bip); all_hard += hard
    rvs = [v for v in (sf(p.get('RunExp')) for p in pp) if v is not None]
    rv = round(sum(rvs), 1) if rvs else None
    pt_name = 'Fastball' if pt == 'FF' else PITCH_NAMES.get(pt, pt)
    row = [pt_name, str(n), f"{n/tc*100:.1f}%",
        f"{sum(velos)/len(velos):.1f}" if velos else '—', f"{max(velos):.1f}" if velos else '—',
        f"{int(sum(spins)/len(spins))}" if spins else '—', avg_tilt(tilts),
        f'{sum(ivbs)/len(ivbs):.1f}"' if ivbs else '—', f'{sum(hbs)/len(hbs):.1f}"' if hbs else '—',
        fmt_fi(sum(relzs)/len(relzs)) if relzs else '—', fmt_fi(sum(relxs)/len(relxs)) if relxs else '—',
        fmt_fi(sum(exts)/len(exts)) if exts else '—',
        f"{sum(vaas)/len(vaas):.2f}°" if vaas else '—', f"{sum(haas)/len(haas):.2f}°" if haas else '—',
        f"{len(strikes)/n*100:.1f}%", f"{iz_n/n*100:.1f}%" if n else '—',
        f"{len(csw)/n*100:.1f}%", f"{len(whiffs)/len(swings)*100:.1f}%" if swings else '—',
        f"{iz_wh/iz_sw*100:.1f}%" if iz_sw else '—', f"{ooz_sw/ooz_n*100:.1f}%" if ooz_n else '—',
        f"{hard/len(bip)*100:.1f}%" if bip else '—', '0.0%',
        str(rv) if rv is not None else '—']
    pitch_stats.append((pt, row))

t_str = [p for p in fried if p.get('Description') in STRIKE_DESC]
t_csw = [p for p in fried if p.get('Description') in ['Called Strike', 'Swinging Strike']]
t_sw = [p for p in fried if p.get('Description') in SWING_DESC]
t_wh = [p for p in fried if p.get('Description') == 'Swinging Strike']
t_iz = sum(1 for p in fried if compute_iz(p) == True)
t_rv = [v for v in (sf(p.get('RunExp')) for p in fried) if v is not None]
total_row = ['Total', str(tc), '', '—','—','—','—','—','—','—','—','—','—','—',
    f"{len(t_str)/tc*100:.1f}%", f"{t_iz/tc*100:.1f}%",
    f"{len(t_csw)/tc*100:.1f}%", f"{len(t_wh)/len(t_sw)*100:.1f}%" if t_sw else '—',
    f"{all_iz_wh/all_iz_sw*100:.1f}%" if all_iz_sw else '—',
    f"{all_ooz_sw/all_ooz_n*100:.1f}%" if all_ooz_n else '—',
    f"{all_hard/len(all_bip)*100:.1f}%" if all_bip else '—', '0.0%',
    str(round(sum(t_rv), 1)) if t_rv else '—']

col_headers = ['Pitch Type','Count','Usage','Velocity','Max Velo','Spin Rate','OTilt',
    'IVB','HB','RelZ','RelX','Ext','VAA','HAA',
    'Strike%','Zone%','CSW%','Whiff%','IZWhiff%','Chase%','HardHit%','Barrel%','PitchRV']
cell_data = [r[1] for r in pitch_stats] + [total_row]
pt_codes = [r[0] for r in pitch_stats] + [None]
sorted_types = [pt for pt in PITCH_ORDER if pt in groups]


# ═══════════════════════════════════════════════════════════════
# SHARED RENDERING HELPERS
# ═══════════════════════════════════════════════════════════════
def draw_movement_plot(ax, style):
    """Draw the pitch movement scatter plot with style-specific aesthetics."""
    bg = style.get('plot_bg', 'white')
    text_color = style.get('text_color', 'black')
    grid_color = style.get('grid_color', '#999')
    grid_alpha = style.get('grid_alpha', 0.15)
    spine_color = style.get('spine_color', '#ccc')
    dot_size = style.get('dot_size', 35)
    ellipse_width = style.get('ellipse_width', 1.2)
    colors = style.get('pitch_colors', PITCH_COLORS)

    ax.set_xlim(-25, 25); ax.set_ylim(-25, 25); ax.set_aspect('equal')
    ax.axhline(y=0, color=grid_color, linestyle='--', linewidth=0.5)
    ax.axvline(x=0, color=grid_color, linestyle='--', linewidth=0.5)
    ax.set_xlabel('Horizontal Break (in)', fontsize=10, color=text_color, fontweight='bold',
                  fontfamily=style.get('body_font', 'sans-serif'))
    ax.set_ylabel('Induced Vertical Break (in)', fontsize=10, color=text_color, fontweight='bold',
                  fontfamily=style.get('body_font', 'sans-serif'))
    ax.tick_params(labelsize=8, colors=text_color)
    ax.set_xticks(range(-25, 26, 5)); ax.set_yticks(range(-25, 26, 5))
    ax.grid(True, alpha=grid_alpha, color=grid_color)
    ax.set_facecolor(bg)
    for spine in ax.spines.values(): spine.set_color(spine_color)

    for pt in PITCH_ORDER:
        if pt not in groups: continue
        xs, ys = zip(*groups[pt]); color = colors.get(pt, PITCH_COLORS[pt])
        edge = 'white' if bg != 'white' else 'white'
        ax.scatter(xs, ys, c=color, s=dot_size, alpha=0.9, edgecolors=edge, linewidths=0.4, zorder=3)
        if len(groups[pt]) >= 4:
            cov = np.cov(xs, ys); vals, vecs = np.linalg.eigh(cov)
            ax.add_patch(Ellipse((np.mean(xs), np.mean(ys)),
                2*1.5*np.sqrt(vals[1]), 2*1.5*np.sqrt(vals[0]),
                angle=np.degrees(np.arctan2(vecs[1,1], vecs[0,1])),
                fill=False, edgecolor=color, linewidth=ellipse_width, alpha=0.6))

    legend_handles = [mpatches.Patch(color=colors.get(pt, PITCH_COLORS[pt]),
        label=f'{pt} - {"Fastball" if pt == "FF" else PITCH_NAMES[pt]}') for pt in sorted_types]
    leg = ax.legend(handles=legend_handles, loc='upper center', bbox_to_anchor=(0.5, -0.08),
        ncol=min(len(sorted_types), 4), fontsize=7.5, frameon=False, handlelength=1.2, columnspacing=1.2)
    for t in leg.get_texts(): t.set_color(text_color)


def draw_usage_bars(ax, data, total, title, style):
    """Draw pitch usage bars with style-specific aesthetics."""
    text_color = style.get('text_color', 'black')
    bar_bg = style.get('bar_bg', '#e0e0e0')
    colors = style.get('pitch_colors', PITCH_COLORS)
    body_font = style.get('body_font', 'sans-serif')

    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    ax.text(0.5, 0.96, title, fontsize=11, fontweight='bold', ha='center', va='top',
            color=text_color, fontfamily=body_font)
    spts = sorted(data.keys(), key=lambda x: data[x], reverse=True)
    n = len(spts)
    if n == 0: return
    rh = min(0.10, 0.78 / n); gap = 0.012
    S = USAGE_SHIFT
    for i, pt in enumerate(spts):
        y = 0.84 - i * (rh + gap)
        pct = data[pt] / total if total > 0 else 0
        color = colors.get(pt, PITCH_COLORS.get(pt, '#999'))
        ax.add_patch(FancyBboxPatch((0.04+S, y-rh*0.4), 0.08, rh*0.8,
            boxstyle="round,pad=0.008", facecolor=color, edgecolor='none'))
        ax.text(0.08+S, y, pt, fontsize=7, ha='center', va='center', color='white', fontweight='bold')
        ax.add_patch(Rectangle((0.15+S, y-rh*0.275), 0.55, rh*0.55, facecolor=bar_bg, edgecolor='none'))
        if pct > 0:
            ax.add_patch(Rectangle((0.15+S, y-rh*0.275), 0.55*pct, rh*0.55, facecolor=color, edgecolor='none'))
        ax.text(0.74+S, y, f'{pct*100:.0f}%', fontsize=9, va='center', ha='left',
                color=text_color, fontweight='bold', fontfamily=body_font)


def draw_metrics_table(ax_table, style):
    """Draw the metrics table with style-specific aesthetics."""
    text_color = style.get('text_color', 'black')
    header_bg = style.get('header_bg', '#2a2a3e')
    header_text = style.get('header_text', 'white')
    row_bg = style.get('row_bg', 'white')
    alt_row_bg = style.get('alt_row_bg', None)
    total_bg = style.get('total_bg', '#f0f0f0')
    edge_color = style.get('table_edge', '#ddd')
    divider_color = style.get('divider_color', 'black')
    colors = style.get('pitch_colors', PITCH_COLORS)

    ax_table.axis('off')
    table = ax_table.table(cellText=cell_data, colLabels=col_headers, loc='upper center', cellLoc='center')
    table.auto_set_font_size(False); table.set_fontsize(8); table.scale(1, 1.6)

    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(edge_color); cell.set_linewidth(0.5)
        if r == 0:
            cell.set_facecolor(header_bg)
            cell.set_text_props(color=header_text, fontweight='bold', fontsize=7)
        elif r == len(cell_data):
            cell.set_facecolor(total_bg)
            cell.set_text_props(fontweight='bold', color=text_color)
        else:
            bg = row_bg
            if alt_row_bg and r % 2 == 0: bg = alt_row_bg
            cell.set_facecolor(bg)
            cell.set_text_props(color=text_color, fontweight='bold')
        if c == 0 and r > 0:
            pc = pt_codes[r - 1]
            if pc:
                cell.set_facecolor(colors.get(pc, '#999'))
                cell.set_text_props(color='white', fontweight='bold')

    return table


def add_divider_line(fig, table, style):
    """Add vertical divider line between HAA and Strike% columns."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig_bbox = fig.get_window_extent(renderer)
    strike_cell = table.get_celld()[0, DIVIDER_COL]
    x_fig = strike_cell.get_window_extent(renderer).x0 / fig_bbox.width
    top_y = strike_cell.get_window_extent(renderer).y1 / fig_bbox.height - 0.001
    bot_cell = table.get_celld()[len(cell_data), DIVIDER_COL]
    bot_y = bot_cell.get_window_extent(renderer).y0 / fig_bbox.height
    fig.add_artist(plt.Line2D([x_fig, x_fig], [bot_y, top_y],
        transform=fig.transFigure, color=style.get('divider_color', 'black'),
        linewidth=2, zorder=10))


# ═══════════════════════════════════════════════════════════════
# CONCEPT A: EDITORIAL / MAGAZINE
# ═══════════════════════════════════════════════════════════════
def render_editorial(output_file):
    print(f"  Rendering Editorial...")
    S = {
        'bg': '#F8F6F1', 'text_color': '#1a1a1a', 'accent': '#8B0000',
        'display_font': 'Bodoni 72', 'body_font': 'Charter',
        'header_bg': '#1a1a1a', 'header_text': '#F8F6F1',
        'row_bg': '#F8F6F1', 'alt_row_bg': 'white', 'total_bg': '#eae6dd',
        'table_edge': '#c5bfb3', 'divider_color': '#1a1a1a',
        'plot_bg': '#F8F6F1', 'grid_color': '#c5bfb3', 'grid_alpha': 0.3,
        'spine_color': '#a09888', 'dot_size': 30, 'ellipse_width': 1.0,
        'bar_bg': '#d9d3c7', 'stat_header_bg': '#1a1a1a', 'stat_header_text': '#F8F6F1',
        'pitch_colors': PITCH_COLORS,
    }

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    fig.patch.set_facecolor(S['bg'])
    ax_main = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax_main.set_xlim(0, FIG_W); ax_main.set_ylim(0, FIG_H); ax_main.axis('off')
    ax_main.set_facecolor(S['bg'])

    # Photo
    photo_left = TABLE_LEFT_FIG * FIG_W
    photo_w = 1.4; photo_h = photo_w * headshot.size[1] / headshot.size[0]
    photo_top = 14.85; photo_bottom = photo_top - photo_h
    ax_main.imshow(np.array(headshot), extent=[photo_left, photo_left+photo_w, photo_bottom, photo_top],
        aspect='auto', zorder=2, interpolation='antialiased')

    # Thin border around photo
    ax_main.add_patch(Rectangle((photo_left, photo_bottom), photo_w, photo_h,
        fill=False, edgecolor='#a09888', linewidth=0.8, zorder=3))

    photo_right = photo_left + photo_w; text_x = photo_right + 0.3

    # Player name — elegant serif
    ax_main.text(text_x, photo_top - 0.15, DISPLAY_NAME, fontsize=28,
        fontfamily='Bodoni 72', fontweight='bold', color=S['text_color'], va='top', fontstyle='italic')
    # Thin rule under name
    ax_main.plot([text_x, text_x + 3.5], [photo_top - 0.55, photo_top - 0.55],
        color=S['accent'], linewidth=1.5, zorder=3)
    ax_main.text(text_x, photo_top - 0.75, f'{HAND}  |  {TEAM}  |  Age: {AGE}', fontsize=11,
        fontfamily='Charter', color='#666', va='top')
    ax_main.text(text_x, photo_top - 1.4, GAME_DATE, fontsize=20,
        fontfamily='Charter', fontweight='bold', color=S['text_color'], va='top')

    # Stat line — refined, thin borders
    col_w = 0.6; cell_h = 0.4
    stat_y_header = photo_bottom - 0.5; stat_y_value = stat_y_header - cell_h
    for i in range(len(STAT_HEADERS)):
        x = photo_left + i * col_w
        ax_main.add_patch(Rectangle((x, stat_y_header), col_w, cell_h,
            facecolor=S['stat_header_bg'], edgecolor='#a09888', linewidth=0.5))
        ax_main.text(x+col_w/2, stat_y_header+cell_h/2, STAT_HEADERS[i], fontsize=8,
            ha='center', va='center', color=S['stat_header_text'], fontweight='bold', fontfamily='Charter')
        ax_main.add_patch(Rectangle((x, stat_y_value), col_w, cell_h,
            facecolor=S['bg'], edgecolor='#a09888', linewidth=0.5))
        ax_main.text(x+col_w/2, stat_y_value+cell_h/2, STAT_VALUES[i], fontsize=11,
            ha='center', va='center', color=S['text_color'], fontweight='bold', fontfamily='Charter')

    # Movement plot
    ax_plot = fig.add_axes([0.50, 0.55, PLOT_AXES_RIGHT - 0.50, 0.44])
    draw_movement_plot(ax_plot, S)

    # Usage bars
    usage_left = 0.50; usage_mid = (usage_left + TABLE_RIGHT_FIG) / 2
    ax_ul = fig.add_axes([usage_left, 0.30, usage_mid - usage_left, 0.17])
    ax_ur = fig.add_axes([usage_mid, 0.30, TABLE_RIGHT_FIG - usage_mid, 0.17])
    ax_ul.set_facecolor(S['bg']); ax_ur.set_facecolor(S['bg'])
    draw_usage_bars(ax_ul, usage['L'], tots['L'], 'VS LHH', S)
    draw_usage_bars(ax_ur, usage['R'], tots['R'], 'VS RHH', S)

    # Metrics table
    ax_table = fig.add_axes([TABLE_LEFT_FIG, 0.01, TABLE_RIGHT_FIG - TABLE_LEFT_FIG, 0.27])
    ax_table.set_facecolor(S['bg'])
    table = draw_metrics_table(ax_table, S)
    add_divider_line(fig, table, S)

    fig.text(0.99, 0.005, 'Huronalytics', fontsize=9, ha='right', color='#a09888',
             style='italic', fontfamily='Bodoni 72')
    plt.savefig(output_file, dpi=SAVE_DPI, bbox_inches='tight', facecolor=S['bg'], pad_inches=0.1)
    plt.close()


# ═══════════════════════════════════════════════════════════════
# CONCEPT B: DARK / MODERN (BROADCAST)
# ═══════════════════════════════════════════════════════════════
def render_dark(output_file):
    print(f"  Rendering Dark/Modern...")
    S = {
        'bg': '#141619', 'text_color': '#e8e8e8', 'accent': '#00d4ff',
        'display_font': 'DIN Condensed', 'body_font': 'Avenir Next',
        'header_bg': '#0d0f12', 'header_text': '#00d4ff',
        'row_bg': '#1e2127', 'alt_row_bg': '#252930', 'total_bg': '#0d0f12',
        'table_edge': '#333840', 'divider_color': '#00d4ff',
        'plot_bg': '#1a1d21', 'grid_color': '#333840', 'grid_alpha': 0.4,
        'spine_color': '#444', 'dot_size': 40, 'ellipse_width': 1.5,
        'bar_bg': '#333840', 'stat_header_bg': '#0d0f12', 'stat_header_text': '#00d4ff',
        'pitch_colors': PITCH_COLORS,
    }

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    fig.patch.set_facecolor(S['bg'])
    ax_main = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax_main.set_xlim(0, FIG_W); ax_main.set_ylim(0, FIG_H); ax_main.axis('off')
    ax_main.set_facecolor(S['bg'])

    # Accent line at top
    ax_main.plot([TABLE_LEFT_FIG * FIG_W, FIG_W * 0.99], [14.95, 14.95],
        color=S['accent'], linewidth=3, zorder=5)

    # Photo
    photo_left = TABLE_LEFT_FIG * FIG_W
    photo_w = 1.4; photo_h = photo_w * headshot.size[1] / headshot.size[0]
    photo_top = 14.85; photo_bottom = photo_top - photo_h
    ax_main.imshow(np.array(headshot), extent=[photo_left, photo_left+photo_w, photo_bottom, photo_top],
        aspect='auto', zorder=2, interpolation='antialiased')
    # Glow border
    ax_main.add_patch(Rectangle((photo_left-0.02, photo_bottom-0.02), photo_w+0.04, photo_h+0.04,
        fill=False, edgecolor=S['accent'], linewidth=1.5, alpha=0.4, zorder=3))

    photo_right = photo_left + photo_w; text_x = photo_right + 0.3
    ax_main.text(text_x, photo_top - 0.2, DISPLAY_NAME.upper(), fontsize=30,
        fontfamily='DIN Condensed', color='white', va='top', fontweight='bold')
    ax_main.text(text_x, photo_top - 0.9, f'{HAND}  |  {TEAM}  |  Age: {AGE}', fontsize=11,
        fontfamily='Avenir Next', color='#888', va='top')
    ax_main.text(text_x, photo_top - 1.5, GAME_DATE, fontsize=22,
        fontfamily='DIN Condensed', color=S['accent'], va='top')

    # Stat line — dark cells
    col_w = 0.6; cell_h = 0.4
    stat_y_header = photo_bottom - 0.5; stat_y_value = stat_y_header - cell_h
    for i in range(len(STAT_HEADERS)):
        x = photo_left + i * col_w
        ax_main.add_patch(Rectangle((x, stat_y_header), col_w, cell_h,
            facecolor=S['stat_header_bg'], edgecolor='#333840', linewidth=0.5))
        ax_main.text(x+col_w/2, stat_y_header+cell_h/2, STAT_HEADERS[i], fontsize=8,
            ha='center', va='center', color=S['accent'], fontweight='bold', fontfamily='Avenir Next')
        ax_main.add_patch(Rectangle((x, stat_y_value), col_w, cell_h,
            facecolor=S['row_bg'], edgecolor='#333840', linewidth=0.5))
        ax_main.text(x+col_w/2, stat_y_value+cell_h/2, STAT_VALUES[i], fontsize=11,
            ha='center', va='center', color='white', fontweight='bold', fontfamily='Avenir Next')

    # Movement plot
    ax_plot = fig.add_axes([0.50, 0.55, PLOT_AXES_RIGHT - 0.50, 0.44])
    draw_movement_plot(ax_plot, S)

    # Usage bars
    usage_left = 0.50; usage_mid = (usage_left + TABLE_RIGHT_FIG) / 2
    ax_ul = fig.add_axes([usage_left, 0.30, usage_mid - usage_left, 0.17])
    ax_ur = fig.add_axes([usage_mid, 0.30, TABLE_RIGHT_FIG - usage_mid, 0.17])
    ax_ul.set_facecolor(S['bg']); ax_ur.set_facecolor(S['bg'])
    draw_usage_bars(ax_ul, usage['L'], tots['L'], 'VS LHH', S)
    draw_usage_bars(ax_ur, usage['R'], tots['R'], 'VS RHH', S)

    # Metrics table
    ax_table = fig.add_axes([TABLE_LEFT_FIG, 0.01, TABLE_RIGHT_FIG - TABLE_LEFT_FIG, 0.27])
    ax_table.set_facecolor(S['bg'])
    table = draw_metrics_table(ax_table, S)
    add_divider_line(fig, table, S)

    fig.text(0.99, 0.005, 'Huronalytics', fontsize=9, ha='right', color='#555',
             style='italic', fontfamily='DIN Condensed')
    plt.savefig(output_file, dpi=SAVE_DPI, bbox_inches='tight', facecolor=S['bg'], pad_inches=0.1)
    plt.close()


# ═══════════════════════════════════════════════════════════════
# CONCEPT C: MINIMALIST / REFINED
# ═══════════════════════════════════════════════════════════════
def render_minimal(output_file):
    print(f"  Rendering Minimalist...")
    NAVY = '#1B2A4A'
    S = {
        'bg': 'white', 'text_color': NAVY, 'accent': NAVY,
        'display_font': 'Futura', 'body_font': 'Avenir',
        'header_bg': NAVY, 'header_text': 'white',
        'row_bg': 'white', 'alt_row_bg': '#f7f8fa', 'total_bg': '#eef0f4',
        'table_edge': '#e0e3e8', 'divider_color': NAVY,
        'plot_bg': 'white', 'grid_color': '#e0e3e8', 'grid_alpha': 0.5,
        'spine_color': '#d0d3d8', 'dot_size': 28, 'ellipse_width': 0.8,
        'bar_bg': '#e8eaef', 'stat_header_bg': NAVY, 'stat_header_text': 'white',
        'pitch_colors': {k: NAVY for k in PITCH_COLORS},  # all navy for minimal
    }

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    fig.patch.set_facecolor('white')
    ax_main = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax_main.set_xlim(0, FIG_W); ax_main.set_ylim(0, FIG_H); ax_main.axis('off')

    # Photo
    photo_left = TABLE_LEFT_FIG * FIG_W
    photo_w = 1.4; photo_h = photo_w * headshot.size[1] / headshot.size[0]
    photo_top = 14.85; photo_bottom = photo_top - photo_h
    ax_main.imshow(np.array(headshot), extent=[photo_left, photo_left+photo_w, photo_bottom, photo_top],
        aspect='auto', zorder=2, interpolation='antialiased')

    photo_right = photo_left + photo_w; text_x = photo_right + 0.3
    ax_main.text(text_x, photo_top - 0.2, DISPLAY_NAME, fontsize=26,
        fontfamily='Futura', color=NAVY, va='top')
    ax_main.text(text_x, photo_top - 0.9, f'{HAND}  |  {TEAM}  |  Age: {AGE}', fontsize=10,
        fontfamily='Avenir', color='#8896a8', va='top')
    ax_main.text(text_x, photo_top - 1.5, GAME_DATE, fontsize=18,
        fontfamily='Avenir', color=NAVY, va='top', fontweight='bold')

    # Stat line — clean, thin
    col_w = 0.6; cell_h = 0.4
    stat_y_header = photo_bottom - 0.5; stat_y_value = stat_y_header - cell_h
    for i in range(len(STAT_HEADERS)):
        x = photo_left + i * col_w
        ax_main.add_patch(Rectangle((x, stat_y_header), col_w, cell_h,
            facecolor=NAVY, edgecolor='none'))
        ax_main.text(x+col_w/2, stat_y_header+cell_h/2, STAT_HEADERS[i], fontsize=8,
            ha='center', va='center', color='white', fontfamily='Avenir')
        # No box for value, just thin bottom line
        ax_main.plot([x, x+col_w], [stat_y_value, stat_y_value], color='#d0d3d8', linewidth=0.5)
        ax_main.text(x+col_w/2, stat_y_value+cell_h/2, STAT_VALUES[i], fontsize=11,
            ha='center', va='center', color=NAVY, fontweight='bold', fontfamily='Avenir')

    # Movement plot — use real pitch colors for the plot only
    S_plot = dict(S)
    S_plot['pitch_colors'] = PITCH_COLORS  # real colors for the scatter
    ax_plot = fig.add_axes([0.50, 0.55, PLOT_AXES_RIGHT - 0.50, 0.44])
    draw_movement_plot(ax_plot, S_plot)

    # Usage bars — navy only
    usage_left = 0.50; usage_mid = (usage_left + TABLE_RIGHT_FIG) / 2
    ax_ul = fig.add_axes([usage_left, 0.30, usage_mid - usage_left, 0.17])
    ax_ur = fig.add_axes([usage_mid, 0.30, TABLE_RIGHT_FIG - usage_mid, 0.17])
    # Use real colors for usage bars too (navy-only is too monotone)
    S_usage = dict(S)
    S_usage['pitch_colors'] = PITCH_COLORS
    draw_usage_bars(ax_ul, usage['L'], tots['L'], 'VS LHH', S_usage)
    draw_usage_bars(ax_ur, usage['R'], tots['R'], 'VS RHH', S_usage)

    # Metrics table
    ax_table = fig.add_axes([TABLE_LEFT_FIG, 0.01, TABLE_RIGHT_FIG - TABLE_LEFT_FIG, 0.27])
    S_table = dict(S)
    S_table['pitch_colors'] = PITCH_COLORS  # real colors for pitch type column
    table = draw_metrics_table(ax_table, S_table)
    add_divider_line(fig, table, S)

    fig.text(0.99, 0.005, 'Huronalytics', fontsize=9, ha='right', color='#b0b8c4',
             fontfamily='Avenir')
    plt.savefig(output_file, dpi=SAVE_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.1)
    plt.close()


# ═══════════════════════════════════════════════════════════════
# CONCEPT D: BOLD / DATA-VIZ
# ═══════════════════════════════════════════════════════════════
def render_dataviz(output_file):
    print(f"  Rendering Bold/Data-viz...")
    # Saturated, vibrant pitch colors
    VIV_COLORS = {
        'FF': '#0055FF', 'SI': '#FFB800', 'CF': '#A0522D', 'FC': '#FF8C00',
        'SL': '#00AA00', 'ST': '#FF1493', 'CU': '#DD0000', 'SV': '#00DD00',
        'CH': '#AA00AA', 'FS': '#00CCAA', 'KN': '#222222'
    }
    S = {
        'bg': 'white', 'text_color': '#111', 'accent': '#FF1493',
        'display_font': 'DIN Condensed', 'body_font': 'Helvetica Neue',
        'header_bg': '#111', 'header_text': 'white',
        'row_bg': 'white', 'alt_row_bg': '#f5f5f5', 'total_bg': '#e8e8e8',
        'table_edge': '#ccc', 'divider_color': '#111',
        'plot_bg': '#fafafa', 'grid_color': '#ddd', 'grid_alpha': 0.4,
        'spine_color': '#999', 'dot_size': 50, 'ellipse_width': 2.0,
        'bar_bg': '#e0e0e0', 'stat_header_bg': '#111', 'stat_header_text': 'white',
        'pitch_colors': VIV_COLORS,
    }

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    fig.patch.set_facecolor('white')
    ax_main = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax_main.set_xlim(0, FIG_W); ax_main.set_ylim(0, FIG_H); ax_main.axis('off')

    # Bold colored accent bar at top
    photo_left = TABLE_LEFT_FIG * FIG_W
    ax_main.add_patch(Rectangle((photo_left, 14.9), FIG_W * 0.98, 0.12,
        facecolor='#111', edgecolor='none', zorder=5))
    # Colored stripe within
    stripe_x = photo_left
    for pt in sorted_types:
        w = 0.98 * FIG_W / len(sorted_types)
        ax_main.add_patch(Rectangle((stripe_x, 14.9), w, 0.12,
            facecolor=VIV_COLORS.get(pt, '#999'), edgecolor='none', zorder=6, alpha=0.9))
        stripe_x += w

    # Photo
    photo_w = 1.4; photo_h = photo_w * headshot.size[1] / headshot.size[0]
    photo_top = 14.8; photo_bottom = photo_top - photo_h
    ax_main.imshow(np.array(headshot), extent=[photo_left, photo_left+photo_w, photo_bottom, photo_top],
        aspect='auto', zorder=2, interpolation='antialiased')
    # Bold frame
    ax_main.add_patch(Rectangle((photo_left, photo_bottom), photo_w, photo_h,
        fill=False, edgecolor='#111', linewidth=2, zorder=3))

    photo_right = photo_left + photo_w; text_x = photo_right + 0.3
    ax_main.text(text_x, photo_top - 0.1, DISPLAY_NAME.upper(), fontsize=32,
        fontfamily='DIN Condensed', color='#111', va='top', fontweight='bold')
    ax_main.text(text_x, photo_top - 0.85, f'{HAND}  |  {TEAM}  |  Age: {AGE}', fontsize=12,
        fontfamily='Helvetica Neue', color='#666', va='top', fontweight='bold')
    ax_main.text(text_x, photo_top - 1.5, GAME_DATE, fontsize=24,
        fontfamily='DIN Condensed', color='#111', va='top', fontweight='bold')

    # Stat line — bold geometric cells
    col_w = 0.6; cell_h = 0.42
    stat_y_header = photo_bottom - 0.5; stat_y_value = stat_y_header - cell_h
    for i in range(len(STAT_HEADERS)):
        x = photo_left + i * col_w
        ax_main.add_patch(Rectangle((x, stat_y_header), col_w, cell_h,
            facecolor='#111', edgecolor='white', linewidth=1))
        ax_main.text(x+col_w/2, stat_y_header+cell_h/2, STAT_HEADERS[i], fontsize=9,
            ha='center', va='center', color='white', fontweight='bold', fontfamily='Helvetica Neue')
        ax_main.add_patch(Rectangle((x, stat_y_value), col_w, cell_h,
            facecolor='white', edgecolor='#111', linewidth=1))
        ax_main.text(x+col_w/2, stat_y_value+cell_h/2, STAT_VALUES[i], fontsize=12,
            ha='center', va='center', color='#111', fontweight='bold', fontfamily='Helvetica Neue')

    # Movement plot — large dots, thick ellipses
    ax_plot = fig.add_axes([0.50, 0.55, PLOT_AXES_RIGHT - 0.50, 0.44])
    draw_movement_plot(ax_plot, S)

    # Usage bars
    usage_left = 0.50; usage_mid = (usage_left + TABLE_RIGHT_FIG) / 2
    ax_ul = fig.add_axes([usage_left, 0.30, usage_mid - usage_left, 0.17])
    ax_ur = fig.add_axes([usage_mid, 0.30, TABLE_RIGHT_FIG - usage_mid, 0.17])
    draw_usage_bars(ax_ul, usage['L'], tots['L'], 'VS LHH', S)
    draw_usage_bars(ax_ur, usage['R'], tots['R'], 'VS RHH', S)

    # Metrics table
    ax_table = fig.add_axes([TABLE_LEFT_FIG, 0.01, TABLE_RIGHT_FIG - TABLE_LEFT_FIG, 0.27])
    table = draw_metrics_table(ax_table, S)
    add_divider_line(fig, table, S)

    fig.text(0.99, 0.005, 'Huronalytics', fontsize=10, ha='right', color='#999',
             fontweight='bold', fontfamily='DIN Condensed')
    plt.savefig(output_file, dpi=SAVE_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.1)
    plt.close()


# ═══════════════════════════════════════════════════════════════
# GENERATE ALL 4
# ═══════════════════════════════════════════════════════════════
print("\nGenerating 4 concepts...")
_dl = os.path.expanduser('~/Downloads')
render_editorial(os.path.join(_dl, 'fried_card_editorial.png'))
render_dark(os.path.join(_dl, 'fried_card_dark.png'))
render_minimal(os.path.join(_dl, 'fried_card_minimal.png'))
render_dataviz(os.path.join(_dl, 'fried_card_dataviz.png'))
print("\nDone! All 4 cards saved to Downloads.")
