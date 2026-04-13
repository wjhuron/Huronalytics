const Utils = {
  ordinal: function (n) {
    const s = ['th', 'st', 'nd', 'rd'];
    const v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  },

  formatPct: function (value, sign) {
    if (value === null || value === undefined) return '--';
    var str = (value * 100).toFixed(1) + '%';
    if (sign && value > 0) str = '+' + str;
    return str;
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

  formatStuff: function (value) {
    if (value === null || value === undefined) return '--';
    return Math.round(value).toString();
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

  // Pitch type colors (matches scatter.js)
  PITCH_COLORS: {
    FF: '#4488FF', SI: '#FFD700', FC: '#FFA500', SL: '#DDDDDD',
    ST: '#FF1493', SV: '#32CD32', CU: '#E03030', CH: '#CC66EE',
    FS: '#40E0D0', KN: '#AAAAAA', SC: '#999999', CS: '#666666',
  },

  getPitchColor: function (pt) {
    return this.PITCH_COLORS[pt] || '#999';
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

  // URL state helpers
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

  writeHash: function (params) {
    const parts = [];
    Object.keys(params).forEach(function (k) {
      if (params[k] !== undefined && params[k] !== null && params[k] !== '') {
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
      }
    });
    const newHash = parts.join('&');
    if (window.location.hash.replace(/^#/, '') !== newHash) {
      history.replaceState(null, '', '#' + newHash);
    }
  },

  // Export data as CSV string
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

  // Download text as file
  downloadFile: function (content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType || 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  },

  // Copy text to clipboard
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

  // Tab-separated for clipboard (pastes into Excel/Sheets nicely)
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
