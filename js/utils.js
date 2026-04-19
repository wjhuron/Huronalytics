// ============================================================================
//  JSDoc Type Definitions -- shared data shapes used across the codebase
// ============================================================================

/**
 * A column definition used in leaderboard tables and player-page tables.
 * @typedef {Object} ColumnDef
 * @property {string}   key          - Data-row property name (e.g. 'velocity', 'kPct').
 * @property {string}   label        - Display header text.
 * @property {function} [format]     - Formatter: (value) => string. Omit for pitch-type badge cols.
 * @property {string}   [sortType]   - 'numeric' | 'string' | null (unsortable).
 * @property {string}   [sortKey]    - Alternate row property to sort on (defaults to key).
 * @property {boolean}  [sectionStart] - If true, renders a left-border divider before this column.
 * @property {boolean}  [noPercentile] - If true, skip percentile coloring for this column.
 * @property {string}   [desc]       - Tooltip description for header hover.
 * @property {string}   [group]      - Column group label (e.g. 'metrics', 'ev', 'discipline').
 * @property {boolean}  [rocHide]    - If true, hide this column for ROC/AAA players.
 * @property {boolean}  [noPctl]     - Player-page: skip percentile circle for this stat.
 */

/**
 * A row from the pitcher leaderboard (PITCHER_DATA / Aggregator output).
 * @typedef {Object} PitcherRow
 * @property {string}  pitcher     - Pitcher full name.
 * @property {string}  team        - Team abbreviation (e.g. 'NYY').
 * @property {number}  [mlbId]     - MLB player ID (for linking to player page).
 * @property {string}  throws      - Throwing hand: 'R' or 'L'.
 * @property {number}  count       - Total pitches thrown.
 * @property {number}  [pa]        - Plate appearances (total batters faced).
 * @property {number}  [nSwings]   - Swing count.
 * @property {number}  [nBip]      - Batted balls in play.
 * @property {number}  [g]         - Games.
 * @property {number}  [gs]        - Games started.
 * @property {string}  [ip]        - Innings pitched (baseball notation, e.g. '6.2').
 * @property {number}  [kPct]      - Strikeout rate (0-1).
 * @property {number}  [bbPct]     - Walk rate (0-1).
 * @property {number}  [era]       - Earned run average.
 * @property {number}  [fip]       - Fielding-independent pitching.
 * @property {number}  [xwOBA]     - Expected wOBA against.
 * @property {boolean} [_qualified] - True if IP-qualified for percentile pool.
 * @property {boolean} [bipQual]   - True if BIP >= MIN_BIP_PCTL for batted-ball percentiles.
 */

/**
 * A row from the pitch-type leaderboard (PITCH_DATA / Aggregator output).
 * @typedef {Object} PitchRow
 * @property {string}  pitcher     - Pitcher full name.
 * @property {string}  team        - Team abbreviation.
 * @property {string}  throws      - Throwing hand: 'R' or 'L'.
 * @property {string}  pitchType   - Pitch type code (e.g. 'FF', 'SL', 'CH').
 * @property {number}  count       - Number of pitches of this type.
 * @property {number}  [velocity]  - Average velocity (mph).
 * @property {number}  [spinRate]  - Average spin rate (rpm).
 * @property {number}  [indVertBrk]- Induced vertical break (inches).
 * @property {number}  [horzBrk]   - Horizontal break (inches).
 * @property {string}  [breakTilt] - Break tilt (clock notation, e.g. '1:30').
 * @property {number}  [nVAA]      - Normalized vertical approach angle (degrees).
 * @property {number}  [swStrPct]  - Whiff rate (0-1).
 * @property {number}  [cswPct]    - Called strike + whiff rate (0-1).
 */

/**
 * A row from the hitter leaderboard (HITTER_DATA / Aggregator output).
 * @typedef {Object} HitterRow
 * @property {string}  hitter      - Hitter full name.
 * @property {string}  team        - Team abbreviation.
 * @property {number}  [mlbId]     - MLB player ID.
 * @property {string}  stands      - Batting side: 'R', 'L', or 'S'.
 * @property {number}  [pa]        - Plate appearances.
 * @property {number}  [nSwings]   - Swing count.
 * @property {number}  [nBip]      - Batted balls in play.
 * @property {number}  [avg]       - Batting average.
 * @property {number}  [obp]       - On-base percentage.
 * @property {number}  [slg]       - Slugging percentage.
 * @property {number}  [xwOBA]     - Expected wOBA.
 * @property {number}  [avgEVAll]  - Average exit velocity (all BIP, mph).
 * @property {number}  [barrelPct] - Barrel rate (0-1).
 * @property {number}  [batSpeed]  - Average bat speed (mph).
 * @property {boolean} [_qualified]- True if PA-qualified for percentile pool.
 */

/**
 * Filter state object passed between app.js, data.js, and aggregator.js.
 * @typedef {Object} FilterState
 * @property {string}   team         - Team abbreviation or 'all'.
 * @property {string}   throws       - 'R', 'L', or 'all' (also used as stands filter for hitters).
 * @property {string}   [vsHand]     - Opponent hand filter: 'R', 'L', or 'all'.
 * @property {string}   [role]       - 'SP', 'RP', or 'all'.
 * @property {string[]} pitchTypes   - Array of pitch type codes, or ['all'].
 * @property {number|string} minCount - Minimum pitch/PA count, or 'Q' for qualified.
 * @property {number}   [minSwings]  - Minimum swing count (hitter tabs).
 * @property {number}   [minBip]     - Minimum BIP count.
 * @property {number|string} [minIp] - Minimum IP, or 'Q' for qualified (pitcher tabs).
 * @property {number}   [minTbf]     - Minimum total batters faced.
 * @property {string}   [dateStart]  - YYYY-MM-DD start date filter.
 * @property {string}   [dateEnd]    - YYYY-MM-DD end date filter.
 * @property {string}   [search]     - Name search substring.
 */

const Utils = {
  ordinal: function (n) {
    const s = ['th', 'st', 'nd', 'rd'];
    const v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  },

  formatPct: function (value, _sign) {
    // Convention: bare positives, "-" for negatives only. The sign argument is
    // accepted for back-compat but ignored — negatives include "-" naturally.
    if (value === null || value === undefined) return '--';
    return (value * 100).toFixed(1) + '%';
  },

  formatDecimal: function (places) {
    return function (value) {
      if (value === null || value === undefined) return '--';
      return Number(value).toFixed(places);
    };
  },

  formatSignedDecimal: function (places) {
    return function (value) {
      if (value === null || value === undefined) return '--';
      return (value > 0 ? '+' : '') + Number(value).toFixed(places);
    };
  },

  formatInt: function (value) {
    if (value === null || value === undefined) return '--';
    return Math.round(value).toString();
  },

  formatTilt: function (value) {
    if (!value) return '--';
    return value;
  },

  // Convert decimal feet to feet'inches format (e.g., 5.86 → "5'10", -1.8 → "-1'10")
  formatFeetInches: function (value) {
    if (value === null || value === undefined) return '--';
    const sign = value < 0 ? '-' : '';
    const abs = Math.abs(value);
    let ft = Math.floor(abs);
    let inches = Math.round((abs - ft) * 12);
    if (inches === 12) { ft++; inches = 0; }
    return sign + ft + "'" + inches + '"';
  },

  PITCH_TYPE_LABELS: {
    FF: 'Four-Seam', SI: 'Sinker', FC: 'Cutter', CH: 'Changeup',
    CU: 'Curveball', SL: 'Slider', ST: 'Sweeper', FS: 'Splitter',
    SV: 'Slurve', KN: 'Knuckleball', SC: 'Screwball', CS: 'Slow Curve',
  },

  pitchTypeLabel: function (code) {
    return this.PITCH_TYPE_LABELS[code] || code;
  },

  // Pitch type colors — single source of truth (used by scatter.js, leaderboard, player page)
  PITCH_COLORS: {
    FF: '#4488FF', SI: '#FFD700', FC: '#FFA500', SL: '#DDDDDD',
    ST: '#FF1493', SV: '#32CD32', CU: '#E03030', CH: '#CC66EE',
    FS: '#40E0D0', KN: '#AAAAAA', SC: '#999999', CS: '#666666',
  },

  // Border colors for scatter chart markers (derived from PITCH_COLORS)
  PITCH_BORDER_COLORS: {
    FF: '#3366CC', SI: '#CCB000', FC: '#CC8400', SL: '#BBBBBB',
    ST: '#CC1076', SV: '#28A428', CU: '#B32626', CH: '#A352BE',
    FS: '#33B3A6', KN: '#888888', SC: '#777777', CS: '#4D4D4D',
  },

  getPitchColor: function (pt) {
    return this.PITCH_COLORS[pt] || '#999';
  },

  getPitchBorderColor: function (pt) {
    return this.PITCH_BORDER_COLORS[pt] || '#777';
  },

  // Canonical pitch type sort order — used everywhere pitch types are sorted
  PITCH_ORDER: ['FF','SI','FC','SL','ST','CU','SV','CH','FS','KN','SC','CS'],

  // Sort comparator for pitch type codes (for use with Array.sort)
  pitchTypeSortCompare: function (a, b) {
    var ai = this.PITCH_ORDER.indexOf(a); if (ai === -1) ai = 999;
    var bi = this.PITCH_ORDER.indexOf(b); if (bi === -1) bi = 999;
    return ai - bi;
  },

  // Sort an array of pitch type strings in canonical order
  sortPitchTypes: function (types) {
    var self = this;
    return types.slice().sort(function (a, b) { return self.pitchTypeSortCompare(a, b); });
  },

  // Category colors for grouped pitch type display (Hard/Breaking/Offspeed)
  CATEGORY_COLORS: {
    'Hard': '#d62728',
    'Breaking': '#2ca02c',
    'Offspeed': '#ff7f0e',
  },

  // Parse baseball IP notation (e.g. "5.2" = 5 and 2/3 innings) to a float
  parseIP: function (ipStr) {
    if (ipStr == null) return 0;
    var parts = String(ipStr).split('.');
    return parseInt(parts[0], 10) + (parts[1] ? parseInt(parts[1], 10) / 3 : 0);
  },

  // Determine if a pitcher is a starter based on games / games started
  isStarter: function (g, gs) {
    g = g || 0;
    gs = gs || 0;
    return g > 0 && (gs / g) > QUAL.SP_GS_RATIO;
  },

  // Create a pitch badge <span> element (small or regular size)
  createPitchBadge: function (pitchType, small) {
    var badge = document.createElement('span');
    badge.className = small ? 'pitch-badge-sm' : 'pitch-badge';
    var color = this.getPitchColor(pitchType);
    badge.style.backgroundColor = color;
    badge.style.color = this.badgeTextColor(color);
    badge.textContent = pitchType;
    return badge;
  },

  // Create a category badge (Hard/Breaking/Offspeed) <span> element
  createCategoryBadge: function (category, small) {
    var badge = document.createElement('span');
    badge.className = small ? 'pitch-badge-sm' : 'pitch-badge';
    var color = this.CATEGORY_COLORS[category] || '#888';
    badge.style.backgroundColor = color;
    badge.style.color = this.badgeTextColor(color);
    badge.textContent = category;
    return badge;
  },

  badgeTextColor: function (hexColor) {
    const hex = hexColor.replace('#', '');
    let r = parseInt(hex.substring(0, 2), 16) / 255;
    let g = parseInt(hex.substring(2, 4), 16) / 255;
    let b = parseInt(hex.substring(4, 6), 16) / 255;
    r = r <= 0.03928 ? r / 12.92 : Math.pow((r + 0.055) / 1.055, 2.4);
    g = g <= 0.03928 ? g / 12.92 : Math.pow((g + 0.055) / 1.055, 2.4);
    b = b <= 0.03928 ? b / 12.92 : Math.pow((b + 0.055) / 1.055, 2.4);
    const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    return lum > 0.25 ? 'black' : 'white';
  },

  // Percentile color: blue below 50, neutral gray at 50, red above 50
  percentileColor: function (pctl) {
    if (pctl === null || pctl === undefined) return null;
    let r, g, b;
    if (pctl <= 50) {
      const t = pctl / 50;
      // 0th = rgb(30,80,200) vivid blue, 50th = rgb(180,180,180) neutral gray
      r = Math.round(30 + t * 150);
      g = Math.round(80 + t * 100);
      b = Math.round(200 - t * 20);
    } else {
      const t = (pctl - 50) / 50;
      // 50th = rgb(180,180,180) neutral gray, 100th = rgb(200,45,40) vivid red
      r = Math.round(180 + t * 20);
      g = Math.round(180 - t * 135);
      b = Math.round(180 - t * 140);
    }
    return 'rgb(' + r + ',' + g + ',' + b + ')';
  },

  // Text color for percentile backgrounds
  percentileTextColor: function (pctl) {
    if (pctl === null || pctl === undefined) return null;
    if (pctl < 25 || pctl > 75) return '#fff';
    return '#1a1a2e';
  },

  // Dark mode: vivid blue below 50, neutral gray at 50, vivid red above 50
  percentileColorDark: function (pctl) {
    if (pctl === null || pctl === undefined) return null;
    let r, g, b;
    if (pctl <= 50) {
      const t = pctl / 50;
      // 0th = rgb(0,100,255) pure blue, 50th = rgb(140,140,140) neutral gray
      r = Math.round(0 + t * 140);
      g = Math.round(100 + t * 40);
      b = Math.round(255 - t * 115);
    } else {
      const t = (pctl - 50) / 50;
      // 50th = rgb(140,140,140) neutral gray, 100th = rgb(255,20,20) pure red
      r = Math.round(140 + t * 115);
      g = Math.round(140 - t * 120);
      b = Math.round(140 - t * 120);
    }
    return 'rgb(' + r + ',' + g + ',' + b + ')';
  },

  percentileTextColorDark: function (pctl) {
    if (pctl === null || pctl === undefined) return null;
    return '#e6edf3';
  },

  TOOLTIPS: {
    '#': 'Rank',
    'Pitcher': 'Pitcher name',
    'Team': 'Team abbreviation',
    'Throws': 'Throwing hand (R/L)',
    'Pitch': 'Pitch type',
    'Count': 'Number of pitches',
    'Usage%': 'Usage rate (% of pitcher\'s total pitches)',
    'Velo': 'Average Velocity (mph)',
    'Spin': 'Average Spin Rate (rpm)',
    'Tilt': 'Average Break Tilt (clock notation)',
    'IVB': 'Induced Vertical Break (inches)',
    'HB': 'Horizontal Break (inches)',
    'RelZ': 'Vertical Release Position (feet)',
    'RelX': 'Horizontal Release Position (feet)',
    'Ext': 'Extension (feet)',
    'VAA': 'Vertical Approach Angle (degrees)',
    'nVAA': 'Normalized VAA — location-independent (VAA minus expected VAA at that plate height)',
    'HAA': 'Horizontal Approach Angle (degrees)',
    'IZ%': 'In-Zone Rate',
    'Whiff%': 'Whiff Rate (swinging strikes / swings)',
    'CSW%': 'Called Strike + Whiff Rate',
    'Chase%': 'Out-of-Zone Swing Rate',
    'GB%': 'Ground Ball Rate',
    // Hitter tooltips
    'Hitter': 'Hitter name',
    'Bats': 'Batting side (R/L/S)',
    'Pitches': 'Total pitches seen',
    'Swings': 'Total swings',
    'K%': 'Strikeout Rate (strikeouts / plate appearances)',
    'BB%': 'Walk Rate (walks / plate appearances)',
    'Swing%': 'Swing Rate (swings / total pitches)',
    'IZSw%': 'In-Zone Swing Rate',
    'IZSw-Ch%': 'Discipline Spread (IZ Swing% − Chase%)',
    'Whiff%': 'Whiff Rate (misses / total swings)',
    'Avg EV': 'Average Exit Velocity (mph, all BIP)',
    'Max EV': 'Max Exit Velocity (mph)',
    'Barrel%': 'Barrel Rate (Statcast definition)',
    'LD%': 'Line Drive Rate',
    'FB%': 'Fly Ball Rate',
    'PU%': 'Popup Rate',
    'Med LA': 'Median Launch Angle (degrees)',
    'Pull%': 'Pull Rate (batted balls to pull side)',
    'Cent%': 'Center Rate (batted balls to center)',
    'Oppo%': 'Oppo Rate (batted balls to opposite field)',
    'AirPull%': 'Air Pull Rate (LD + FB + PU to pull side / total BIP)',
  },

  readHash: function () {
    const hash = window.location.hash.replace(/^#/, '');
    if (!hash) return {};
    const params = {};
    hash.split('&').forEach(function (part) {
      const kv = part.split('=');
      if (kv.length === 2) params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1]);
    });
    return params;
  },

  toCSV: function (data, columns) {
    const lines = [];
    // Header
    lines.push(columns.map(function (c) { return '"' + c.label + '"'; }).join(','));
    // Rows
    data.forEach(function (row) {
      const cells = columns.map(function (c) {
        const v = row[c.key];
        if (v === null || v === undefined) return '';
        const formatted = c.format(v);
        return '"' + String(formatted).replace(/"/g, '""') + '"';
      });
      lines.push(cells.join(','));
    });
    return lines.join('\n');
  },

  // Add a horizontal scroll fade indicator to a scrollable container
  addScrollFade: function (container) {
    container.style.position = 'relative';
    var fadeDiv = document.createElement('div');
    fadeDiv.style.cssText = 'position:absolute;right:0;top:0;bottom:0;width:24px;background:linear-gradient(to right, transparent, var(--bg-card, #1a1d21));pointer-events:none;z-index:1;opacity:0;transition:opacity 0.2s;';
    container.appendChild(fadeDiv);
    container.addEventListener('scroll', function() {
      var maxScroll = container.scrollWidth - container.clientWidth;
      fadeDiv.style.opacity = (container.scrollLeft >= maxScroll - 2) ? '0' : '1';
    });
    setTimeout(function() {
      if (container.scrollWidth > container.clientWidth) fadeDiv.style.opacity = '1';
    }, 100);
  },

  downloadFile: function (content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType || 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  },

  copyToClipboard: function (text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(function () {
        Utils._fallbackCopy(text);
      });
    } else {
      Utils._fallbackCopy(text);
    }
  },

  _fallbackCopy: function (text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  },

  toTSV: function (data, columns) {
    const lines = [];
    lines.push(columns.map(function (c) { return c.label; }).join('\t'));
    data.forEach(function (row) {
      const cells = columns.map(function (c) {
        const v = row[c.key];
        if (v === null || v === undefined) return '';
        return String(c.format(v));
      });
      lines.push(cells.join('\t'));
    });
    return lines.join('\n');
  },
};
