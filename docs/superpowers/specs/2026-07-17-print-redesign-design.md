# Huronalytics Front-End Redesign — Print Identity ("The Annual")

**Date:** 2026-07-17
**Status:** Approved (avenue, sinker color, and type pair confirmed by Wally)
**Mockups:** `~/Downloads/huronalytics_redesign_mockups.html` (Avenue A) and
`~/Downloads/huronalytics_pitchcolors_type.html` (pitch color + type comparisons)

## Decision

Rebuild the site's visual identity around the pitcher-card design (Cards.py cream/terracotta
"vintage print" palette). The card is the design source of truth; the site adopts its language.
Chosen over: (B) refined dark site with print cards as contrast artifacts, and (C) warm-dark
"ink" inversion.

This is a **pure visual re-skin**. No changes to: layout structure, columns, sorting,
qualification gating (3.1 PA / render-only coloring gate), percentile *math* or pools,
data pipeline, Cards.py, R scripts, or URLs.

## Design tokens (css/styles.css `:root`)

| Token | Value | Source |
|---|---|---|
| --bg-primary | `#f0e8d8` | card BG (warm cream paper) |
| --bg-card | `#e8dfcb` | card ALT_ROW_BG (panels, home cards, plot panels) |
| --bg-header | `#f0e8d8` | header is paper — identity from masthead + rules, not a dark bar |
| --bg-tab-bar | `#f0e8d8` | |
| --bg-th | `#d8ccb4` | card DARKER |
| --bg-th-hover | `#cfc2a6` | slightly deeper tan |
| --text-primary | `#1a1612` | card TEXT_PRIMARY (warm near-black ink) |
| --text-secondary | `#3a3530` | card TEXT_SECONDARY |
| --text-th | `#1a1612` | headers are ink; accent reserved for active/sort states |
| --text-muted | `#6a5f55` | card TEXT_MUTED |
| --border | `#c5b89f` | card SUBTLE_BORDER |
| --border-light | `#d9cdb3` | row hairlines |
| --row-alt | `#e8dfcb` | zebra |
| --row-hover | `#e2d8c4` | card DARK_CELL |
| --row-active | `rgba(159,48,38,0.10)` | terracotta tint |
| --accent | `#9f3026` | card ACCENT (deep terracotta) |
| --accent-light | `rgba(159,48,38,0.12)` | |
| --shadow / --panel-shadow | warm, light: `rgba(58,48,38,0.15)` / `rgba(58,48,38,0.25)` | print has no heavy shadows |
| --grid-line | `#ddd2bb` | |

## Typography

- **Bitter** (slab serif): masthead (900, letterspaced), page/section titles, section tabs
  (Pitchers/Hitters), italic 400 for subtitles and footnotes.
- **IBM Plex Sans** (400–700): all data, table cells, UI labels, buttons.
  `font-variant-numeric: tabular-nums` on all numeric table content.
- **IBM Plex Sans Condensed** (500–700): subtabs and table column headers.
- Barlow, Barlow Condensed, JetBrains Mono removed (JetBrains Mono only if verified unused).
- **No CSS `text-transform: uppercase` on stat column headers** — labels keep true case
  (xwOBA, nVAA, xFIP, xRV/100). Nav/subtab uppercase styling is fine (plain words).
- Considered and rejected for masthead: Fraunces (too opinionated next to dense data),
  Source Serif (too neutral). May revisit later per Wally.

## Brand chrome

- **Pitch stripe**: full-width bar (~6px) at top of page in Okabe-Ito pitch colors
  (SI amber `#E0A81E`, CH `#009E73`, FF `#0072B2`, SL `#D55E00`, FC `#8B5A2B`) — the card's
  signature element, shared across site/cards/reports.
- **Newspaper double rule** under the header (2.5px + 1px ink lines).
- Loading overlay: cream with ink text.

## Tables

2px terracotta outer frame; header row on `#d8ccb4` with 2px terracotta bottom border;
1px `#d9cdb3` row separators; `#e8dfcb` zebra. Sticky columns keep opaque paper backgrounds.

## Percentile color scale (js/utils.js)

Replaces `Utils.percentileColor` (the light path, which becomes the live path):

```
t = |pctl − 50| / 50
target = pctl ≥ 50 ? rgb(176,64,47)   // brick (good)
                   : rgb(86,120,155)  // slate (bad)
base = rgb(236,227,209)               // mid-paper (between row and zebra)
bg = mix(base, target, t^1.3 × 0.72)
text = #1a1612 always (no white-text flips)
```

`percentileTextColor` → always `#1a1612`. `setupDarkMode()` in app.js stops adding the
`dark` body class (site was hard-coded dark; no user toggle exists — the light path was dead
code and now becomes the only path). `percentileColorDark` and `isDark` branches left in
place as dead code until Phase 3 cleanup.

Same scale drives player-page Savant-style bars/bubbles; bar track becomes card TRACK `#d8ccb4`.

## Pitch colors

Web `PITCH_COLORS.SI`: `#FFD700` → **`#E0A81E`** (card amber). Rationale: the bright-gold
variant existed for dark-background contrast; the background is now cream, where gold washes
out (verified visually in comparison mockup). SI border color darkened to match. All other
pitch colors unchanged — the Okabe-Ito colorblind-safe structure is preserved exactly.
This supersedes the old "amber on cards / bright on web" split; one palette everywhere.
(Wally confirmed 2026-07-17; noted palette may be revisited later.)

## Charts (Chart.js, scatter.js, player-page plots)

Plot panels `#e8dfcb` (like card movement/location panels), tan grid, warm-gray axis labels
(`#6a5f55`), titles in Plex Condensed. Chart logic untouched.

## Phasing

1. **Phase 1** — tokens, fonts, chrome (stripe/masthead/rules/tabs/controls), leaderboard
   tables, percentile functions, amber sinker, un-force dark mode. Site coherent after this.
2. **Phase 2** — player page (percentile bars/bubbles, movement/location charts, command-map
   heatmap ramp — highest-risk item), scatter view, compare drawer, home page, tooltips,
   percentile legend.
3. **Phase 3** — polish: mobile spacing, favicon/social meta, delete dead dark-mode code
   (`percentileColorDark`, `isDark` branches, `.dark` class).

Commit + push after each approved phase (pipeline/site serve from origin/main).

## Risks / notes

- Command-map heatmap ramp was tuned for dark; most likely to need iteration (Phase 2).
- Elite-heavy views legitimately render red-dominant (default sorts show top players).
- Team badge colors (JS-set) reviewed in Phase 2 for cream-background contrast.
