/* Player Page — full-page pitcher/hitter profile view */
var PlayerPage = {
  chart: null,
  isOpen: false,
  _playerType: null, // 'pitcher' or 'hitter'

  // Percentile stat definitions for the pitching section
  PITCHING_STATS: [
    { key: 'fbVelo',            label: 'Fastball Velo',    format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'avgEVAgainst',      label: 'Avg Exit Velo',    format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'chasePct',          label: 'Chase %',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'swStrPct',          label: 'Whiff %',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'kPct',              label: 'K %',              format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct',             label: 'BB %',             format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPctAgainst',  label: 'Barrel %',         format: function(v) { return Utils.formatPct(v); } },
    { key: 'hardHitPct',        label: 'Hard-Hit %',       format: function(v) { return Utils.formatPct(v); } },
    { key: 'gbPct',             label: 'GB %',             format: function(v) { return Utils.formatPct(v); } },
    { key: 'extension',         label: 'Extension',        format: function(v) { return v != null ? Utils.formatFeetInches(v) : '—'; } },
  ],

  // Percentile stat definitions for the hitting section
  HITTING_STATS: [
    { key: 'medEV',        label: 'Avg Exit Velo',  format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'ev75',         label: 'EV75',            format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'maxEV',        label: 'Max Exit Velo',   format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'hardHitPct',   label: 'Hard-Hit %',      format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPct',    label: 'Barrel %',         format: function(v) { return Utils.formatPct(v); } },
    { key: 'kPct',         label: 'K %',              format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct',        label: 'BB %',             format: function(v) { return Utils.formatPct(v); } },
    { key: 'chasePct',     label: 'Chase %',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'whiffPct',     label: 'Whiff %',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'contactPct',   label: 'Contact %',        format: function(v) { return Utils.formatPct(v); } },
  ],

  // Pitch usage table columns
  PITCH_TABLE_COLS: [
    { key: 'pitchType', label: 'Pitch' },
    { key: 'usagePct', label: 'Usage', format: function(v) { return Utils.formatPct(v); } },
    { key: 'velocity', label: 'MPH',   format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'spinRate', label: 'Spin',   format: function(v) { return v != null ? Math.round(v) : '—'; } },
    { key: 'breakTilt', label: 'Tilt',  format: function(v) { return v || '—'; } },
    { key: 'indVertBrk', label: 'IVB',  format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
    { key: 'horzBrk',    label: 'HB',   format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
  ],

  _savedScrollY: 0,

  open: function (mlbId) {
    // Try pitcher first, then hitter
    var pitcherData = this._findPitcherByMlbId(mlbId);
    var hitterData = !pitcherData ? this._findHitterByMlbId(mlbId) : null;

    if (!pitcherData && !hitterData) {
      console.warn('Player not found for mlbId:', mlbId);
      return;
    }

    // Save current route for back navigation
    var curHash = window.location.hash.replace(/^#/, '');
    if (curHash.indexOf('player=') === -1) {
      this._lastRoute = curHash;
    }

    // Save scroll position so we can restore it when closing
    this._savedScrollY = window.scrollY;

    this.isOpen = true;
    this._playerType = pitcherData ? 'pitcher' : 'hitter';

    // Hide leaderboard, show player page
    var hideEls = ['tab-bar', 'controls', 'toolbar', 'table-wrapper', 'pagination', 'side-panel', 'panel-overlay', 'home-page'];
    hideEls.forEach(function (cls) {
      var els = document.querySelectorAll('.' + cls + ', #' + cls + ', nav.' + cls + ', section.' + cls);
      els.forEach(function (el) { el.style.display = 'none'; });
    });
    document.getElementById('player-page').style.display = 'block';

    if (pitcherData) {
      this._renderPitcherPage(pitcherData);
    } else {
      this._renderHitterPage(hitterData);
    }

    // Update URL
    window.location.hash = 'player=' + mlbId;

    // Scroll to top of player page
    window.scrollTo(0, 0);

    // Click-outside-to-close: listen on the player-page backdrop
    this._bindClickOutside();
  },

  _renderPitcherPage: function (data) {
    // Show pitcher-specific sections, hide hitter-specific
    this._showPitcherLayout();
    this._renderIdentity(data);
    this._renderUsage(data);
    document.getElementById('player-percentiles').innerHTML = '';
    this._renderPitchRunValues(data);
    this._renderPercentiles(data, this.PITCHING_STATS, true);
    this._renderMovementChart(data);
    this._renderPitchTable(data);
  },

  _renderHitterPage: function (data) {
    // Show hitter-specific sections, hide pitcher-specific
    this._showHitterLayout();
    this._renderHitterIdentity(data);
    this._renderPercentiles(data, this.HITTING_STATS);
    this._renderBattedBallChart(data);
    this._renderHitterStatsTable(data);
  },

  _showPitcherLayout: function () {
    var usageSection = document.querySelector('.player-usage-section');
    var movementCol = document.querySelector('.player-col-movement');
    if (usageSection) usageSection.style.display = '';
    if (movementCol) movementCol.style.display = '';
    // Reset section title
    var title = document.querySelector('.player-col-movement .section-title');
    if (title) title.textContent = 'Movement Profile';
  },

  _showHitterLayout: function () {
    // Hide pitcher-only usage section
    var usageSection = document.querySelector('.player-usage-section');
    if (usageSection) usageSection.style.display = 'none';
    // Show movement column (reused for batted ball chart)
    var movementCol = document.querySelector('.player-col-movement');
    if (movementCol) movementCol.style.display = '';
    var title = document.querySelector('.player-col-movement .section-title');
    if (title) title.textContent = 'Batted Ball Profile';
  },

  close: function () {
    this.isOpen = false;
    this.destroyChart();
    this._unbindClickOutside();

    document.getElementById('player-page').style.display = 'none';

    // Show leaderboard elements
    document.querySelector('nav.tab-bar').style.display = '';
    document.querySelector('section.controls').style.display = '';
    document.querySelector('section.toolbar').style.display = '';
    document.querySelector('section.table-wrapper').style.display = '';
    document.querySelector('section.pagination').style.display = '';

    // Navigate back — use history if available, otherwise go home
    var hash = window.location.hash.replace(/^#/, '');
    if (hash.indexOf('player=') !== -1) {
      if (this._lastRoute) {
        window.location.hash = this._lastRoute;
      } else {
        window.location.hash = 'pitchers/stats';
      }
    }

    // Restore scroll position to where user was in the leaderboard
    var savedY = this._savedScrollY;
    requestAnimationFrame(function () {
      window.scrollTo(0, savedY);
    });
  },

  // Click outside player-page-inner to close
  _bindClickOutside: function () {
    var self = this;
    this._clickOutsideHandler = function (e) {
      var inner = document.querySelector('.player-page-inner');
      // If click is on the player-page backdrop but NOT inside the inner content
      if (!inner.contains(e.target)) {
        self.close();
      }
    };
    document.getElementById('player-page').addEventListener('click', this._clickOutsideHandler);
  },

  _unbindClickOutside: function () {
    if (this._clickOutsideHandler) {
      document.getElementById('player-page').removeEventListener('click', this._clickOutsideHandler);
      this._clickOutsideHandler = null;
    }
  },

  destroyChart: function () {
    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
    }
  },

  // --- Data Lookup ---

  _findPitcherByMlbId: function (mlbId) {
    mlbId = parseInt(mlbId, 10);
    var pitcherData = window.PITCHER_DATA || [];
    for (var i = 0; i < pitcherData.length; i++) {
      if (pitcherData[i].mlbId === mlbId) return pitcherData[i];
    }
    return null;
  },

  _getPitchRows: function (pitcherName, team) {
    var pitchData = window.PITCH_DATA || [];
    var rows = [];
    for (var i = 0; i < pitchData.length; i++) {
      if (pitchData[i].pitcher === pitcherName && pitchData[i].team === team) {
        rows.push(pitchData[i]);
      }
    }
    // Sort by usage descending
    rows.sort(function (a, b) { return (b.usagePct || 0) - (a.usagePct || 0); });
    return rows;
  },

  // --- Render: Identity ---

  _renderIdentity: function (data) {
    // Headshot — request larger image for zoomed-out display
    var img = document.getElementById('player-headshot');
    if (data.mlbId) {
      img.src = 'https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_426,q_auto:best/v1/people/' + data.mlbId + '/headshot/67/current';
      img.alt = data.pitcher;
    } else {
      img.src = '';
      img.alt = '';
    }
    img.onerror = function () {
      this.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160"><rect fill="%23333" width="160" height="160"/><text fill="%23888" font-size="40" x="50%" y="55%" text-anchor="middle" dominant-baseline="middle">?</text></svg>');
    };

    // Name
    var nameParts = data.pitcher.split(', ');
    var displayName = nameParts.length === 2 ? nameParts[1] + ' ' + nameParts[0] : data.pitcher;
    document.getElementById('player-name').textContent = displayName;

    // Position (RHP/LHP) | Team | Age (fetched from MLB API)
    var pos = (data.throws === 'L' ? 'LHP' : 'RHP');
    var posEl = document.getElementById('player-position');
    var ageEl = document.getElementById('player-age');
    posEl.textContent = pos + ' | ' + (data.team || '');
    ageEl.textContent = '';

    if (data.mlbId) {
      fetch('https://statsapi.mlb.com/api/v1/people/' + data.mlbId)
        .then(function (res) { return res.json(); })
        .then(function (json) {
          var person = json.people && json.people[0];
          if (person && person.currentAge != null) {
            posEl.textContent = pos + ' | ' + (data.team || '') + ' | Age: ' + person.currentAge;
          }
        })
        .catch(function () { /* silently ignore */ });
    }
  },

  _renderHitterIdentity: function (data) {
    // Headshot
    var img = document.getElementById('player-headshot');
    if (data.mlbId) {
      img.src = 'https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people/' + data.mlbId + '/headshot/67/current';
      img.alt = data.hitter;
    } else {
      img.src = '';
      img.alt = '';
    }
    img.onerror = function () {
      this.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120"><rect fill="%23333" width="120" height="120"/><text fill="%23888" font-size="40" x="50%" y="55%" text-anchor="middle" dominant-baseline="middle">?</text></svg>');
    };

    // Name
    var nameParts = data.hitter.split(', ');
    var displayName = nameParts.length === 2 ? nameParts[1] + ' ' + nameParts[0] : data.hitter;
    document.getElementById('player-name').textContent = displayName;

    // Bats | Team
    var batsLabel = data.stands === 'S' ? 'Switch' : (data.stands === 'L' ? 'Bats Left' : 'Bats Right');
    document.getElementById('player-position').textContent = batsLabel + ' | ' + (data.team || '');

    // Show PA count
    document.getElementById('player-age').textContent = (data.pa || 0) + ' PA | ' + (data.count || 0) + ' pitches seen';
  },

  // --- Render: Pitch Usage (vs LHH / vs RHH) ---

  _renderUsage: function (data) {
    var microData = window.MICRO_DATA;
    if (!microData || !microData.pitchMicro) return;

    var pitcherName = data.pitcher;
    var team = data.team;

    // Find pitcher/team indices from micro data lookups
    var lookups = microData.lookups || {};
    var pitcherIdx = (lookups.pitchers || []).indexOf(pitcherName);
    var teamIdx = (lookups.teams || []).indexOf(team);
    if (pitcherIdx < 0 || teamIdx < 0) return;

    var pitchTypes = lookups.pitchTypes || [];

    // Aggregate usage from pitchMicro by batter hand
    var usageByHand = { L: {}, R: {} };
    var totalByHand = { L: 0, R: 0 };

    var cols = microData.pitchCols;
    var piIdx = cols.indexOf('pitcherIdx');
    var tiIdx = cols.indexOf('teamIdx');
    var ptIdx = cols.indexOf('pitchTypeIdx');
    var bhIdx = cols.indexOf('batterHand');
    var nIdx = cols.indexOf('n');

    var rows = microData.pitchMicro;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r[piIdx] === pitcherIdx && r[tiIdx] === teamIdx) {
        var bh = r[bhIdx]; // 'L' or 'R' string
        var ptI = r[ptIdx];
        var n = r[nIdx];
        var pt = pitchTypes[ptI];
        if (!usageByHand[bh]) usageByHand[bh] = {};
        if (!usageByHand[bh][pt]) usageByHand[bh][pt] = 0;
        usageByHand[bh][pt] += n;
        if (!totalByHand[bh]) totalByHand[bh] = 0;
        totalByHand[bh] += n;
      }
    }

    this._renderUsageBars('player-usage-lhh', usageByHand.L || {}, totalByHand.L || 0);
    this._renderUsageBars('player-usage-rhh', usageByHand.R || {}, totalByHand.R || 0);
  },

  _renderUsageBars: function (containerId, usageMap, total) {
    var container = document.getElementById(containerId);
    container.innerHTML = '';

    if (total === 0) {
      container.innerHTML = '<p class="no-data">No data</p>';
      return;
    }

    // Sort by usage descending
    var entries = [];
    for (var pt in usageMap) {
      entries.push({ pt: pt, count: usageMap[pt], pct: usageMap[pt] / total });
    }
    entries.sort(function (a, b) { return b.pct - a.pct; });

    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      var row = document.createElement('div');
      row.className = 'usage-bar-row';

      var label = document.createElement('span');
      label.className = 'usage-label';
      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      badge.style.backgroundColor = Utils.getPitchColor(e.pt);
      badge.textContent = e.pt;
      label.appendChild(badge);

      var barWrap = document.createElement('div');
      barWrap.className = 'usage-bar-track';
      var bar = document.createElement('div');
      bar.className = 'usage-bar-fill';
      bar.style.width = Math.round(e.pct * 100) + '%';
      bar.style.backgroundColor = Utils.getPitchColor(e.pt);
      barWrap.appendChild(bar);

      var pct = document.createElement('span');
      pct.className = 'usage-pct';
      pct.textContent = Math.round(e.pct * 100) + '%';

      row.appendChild(label);
      row.appendChild(barWrap);
      row.appendChild(pct);
      container.appendChild(row);
    }
  },

  // --- Render: Percentile Bars ---

  _renderPercentiles: function (data, statsDef, append) {
    var container = document.getElementById('player-percentiles');
    if (!append) container.innerHTML = '';

    var isDark = document.body.classList.contains('dark-mode');

    for (var i = 0; i < statsDef.length; i++) {
      var stat = statsDef[i];
      var val = data[stat.key];
      var pctl = data[stat.key + '_pctl'];

      var row = document.createElement('div');
      row.className = 'pctl-row';

      // Label
      var labelEl = document.createElement('span');
      labelEl.className = 'pctl-label';
      labelEl.textContent = stat.label;

      // Value
      var valEl = document.createElement('span');
      valEl.className = 'pctl-value';
      valEl.textContent = stat.format(val);

      // Percentile circle
      var circleWrap = document.createElement('div');
      circleWrap.className = 'pctl-circle-wrap';

      if (pctl != null) {
        var circle = document.createElement('div');
        circle.className = 'pctl-circle';
        var bgColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
        var textColor = isDark ? '#fff' : Utils.percentileTextColor(pctl);
        circle.style.backgroundColor = bgColor;
        circle.style.color = textColor;
        circle.textContent = Math.round(pctl);
        circleWrap.appendChild(circle);
      }

      // Bar
      var barTrack = document.createElement('div');
      barTrack.className = 'pctl-bar-track';
      var barFill = document.createElement('div');
      barFill.className = 'pctl-bar-fill';
      if (pctl != null) {
        barFill.style.width = Math.round(pctl) + '%';
        var barColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
        barFill.style.backgroundColor = barColor;
      }
      barTrack.appendChild(barFill);

      row.appendChild(labelEl);
      row.appendChild(barTrack);
      row.appendChild(circleWrap);
      row.appendChild(valEl);
      container.appendChild(row);
    }
  },

  // --- Render: Pitch Run Values (per-pitch-type percentile bars) ---

  _renderPitchRunValues: function (data) {
    var container = document.getElementById('player-percentiles');
    var isDark = document.body.classList.contains('dark-mode');

    // Get this pitcher's pitch rows
    var pitchRows = this._getPitchRows(data.pitcher, data.team);
    if (pitchRows.length === 0) return;

    // Section label
    var sectionLabel = document.createElement('div');
    sectionLabel.style.cssText = 'font-size: 12px; font-weight: 700; text-transform: uppercase; color: var(--text-muted, #888); margin-bottom: 6px; letter-spacing: 0.5px;';
    sectionLabel.textContent = 'Pitch Run Value';
    container.appendChild(sectionLabel);

    // Compute overall RV (sum of all pitch run values)
    var overallRV = null;
    var overallPctl = null;  // will need its own percentile eventually
    var hasAnyRV = false;
    for (var j = 0; j < pitchRows.length; j++) {
      if (pitchRows[j].runValue != null) {
        overallRV = (overallRV || 0) + pitchRows[j].runValue;
        hasAnyRV = true;
      }
    }

    // Helper to build a single percentile row
    function buildPctlRow(labelContent, displayVal, pctl) {
      var row = document.createElement('div');
      row.className = 'pctl-row';

      // Label
      var labelEl = document.createElement('span');
      labelEl.className = 'pctl-label';
      if (typeof labelContent === 'string') {
        labelEl.textContent = labelContent;
      } else {
        labelEl.appendChild(labelContent);
      }

      // Value
      var valEl = document.createElement('span');
      valEl.className = 'pctl-value';
      valEl.textContent = (displayVal != null) ? displayVal.toFixed(1) : '—';

      // Percentile circle
      var circleWrap = document.createElement('div');
      circleWrap.className = 'pctl-circle-wrap';
      if (pctl != null) {
        var circle = document.createElement('div');
        circle.className = 'pctl-circle';
        var bgColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
        var textColor = isDark ? '#fff' : Utils.percentileTextColor(pctl);
        circle.style.backgroundColor = bgColor;
        circle.style.color = textColor;
        circle.textContent = Math.round(pctl);
        circleWrap.appendChild(circle);
      }

      // Bar
      var barTrack = document.createElement('div');
      barTrack.className = 'pctl-bar-track';
      var barFill = document.createElement('div');
      barFill.className = 'pctl-bar-fill';
      if (pctl != null) {
        barFill.style.width = Math.round(pctl) + '%';
        var barColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
        barFill.style.backgroundColor = barColor;
      }
      barTrack.appendChild(barFill);

      row.appendChild(labelEl);
      row.appendChild(barTrack);
      row.appendChild(circleWrap);
      row.appendChild(valEl);
      return row;
    }

    // Overall row (sum of all pitch RVs, negated for display)
    var overallDisplay = hasAnyRV ? -overallRV : null;
    container.appendChild(buildPctlRow('Overall', overallDisplay, overallPctl));

    // Per-pitch-type rows
    for (var i = 0; i < pitchRows.length; i++) {
      var pitch = pitchRows[i];
      var rawRV = pitch.runValue;
      var displayVal = (rawRV != null) ? -rawRV : null;
      var pctl = pitch.runValue_pctl;

      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      badge.style.backgroundColor = Utils.getPitchColor(pitch.pitchType);
      badge.textContent = pitch.pitchType;

      container.appendChild(buildPctlRow(badge, displayVal, pctl));
    }

    // Divider before the stat percentiles that follow
    var divider = document.createElement('div');
    divider.style.cssText = 'border-top: 1px solid var(--border, #ddd); margin: 12px 0 8px 0;';
    container.appendChild(divider);
  },

  // --- Render: Movement Chart ---

  _renderMovementChart: function (data) {
    this.destroyChart();

    var pitcherName = data.pitcher;
    var team = data.team;

    // Reuse ScatterChart's data building
    var groups = ScatterChart._buildMovementData(pitcherName, team);
    if (!groups) return;

    var datasets = [];
    var ellipseMeta = [];
    var pitchTypes = Object.keys(groups).sort();

    for (var j = 0; j < pitchTypes.length; j++) {
      var pt = pitchTypes[j];
      var pts = groups[pt];
      var color = ScatterChart.getColor(pt);
      var label = pt + ' - ' + (Utils.pitchTypeLabel(pt) || pt);

      datasets.push({
        label: label,
        data: pts,
        backgroundColor: color.bg,
        borderColor: color.border,
        borderWidth: 1.5,
        pointRadius: 5,
        pointHoverRadius: 7,
      });

      var ellipse = ScatterChart.computeEllipse(pts);
      ellipseMeta.push({ color: color.border, ellipse: ellipse });
    }

    var canvas = document.getElementById('player-pitch-chart');
    var ctx = canvas.getContext('2d');

    var isDark = document.body.classList.contains('dark-mode');
    var gridColor = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)';
    var tickColor = isDark ? '#aaa' : '#666';
    var crossColor = isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.15)';

    this.chart = new Chart(ctx, {
      type: 'scatter',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 1,
        scales: {
          x: {
            title: { display: true, text: 'Horizontal Break (in)', color: tickColor },
            min: -25, max: 25,
            grid: { color: gridColor },
            ticks: { color: tickColor, stepSize: 6 },
          },
          y: {
            title: { display: true, text: 'Induced Vertical Break (in)', color: tickColor },
            min: -25, max: 25,
            grid: { color: gridColor },
            ticks: { color: tickColor, stepSize: 6 },
          },
        },
        plugins: {
          legend: { display: true, position: 'bottom', labels: { color: tickColor, usePointStyle: true, padding: 10, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ': HB ' + ctx.parsed.x.toFixed(1) + ', IVB ' + ctx.parsed.y.toFixed(1);
              },
            },
          },
        },
      },
      plugins: [{
        id: 'crosshairs-ellipses-player',
        beforeDatasetsDraw: function (chart) {
          var ctx = chart.ctx;
          var xAxis = chart.scales.x;
          var yAxis = chart.scales.y;

          // Crosshairs
          ctx.save();
          ctx.strokeStyle = crossColor;
          ctx.lineWidth = 1;
          ctx.setLineDash([4, 4]);
          var cx = xAxis.getPixelForValue(0);
          var cy = yAxis.getPixelForValue(0);
          ctx.beginPath();
          ctx.moveTo(cx, yAxis.top);
          ctx.lineTo(cx, yAxis.bottom);
          ctx.moveTo(xAxis.left, cy);
          ctx.lineTo(xAxis.right, cy);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.restore();

          // Ellipses
          for (var i = 0; i < ellipseMeta.length; i++) {
            var em = ellipseMeta[i];
            if (!em.ellipse) continue;
            var e = em.ellipse;
            var ecx = xAxis.getPixelForValue(e.cx);
            var ecy = yAxis.getPixelForValue(e.cy);
            var rx = Math.abs(xAxis.getPixelForValue(e.rx) - xAxis.getPixelForValue(0));
            var ry = Math.abs(yAxis.getPixelForValue(0) - yAxis.getPixelForValue(e.ry));
            ctx.save();
            ctx.strokeStyle = em.color;
            ctx.globalAlpha = 0.35;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.translate(ecx, ecy);
            ctx.rotate(-e.angle);
            ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
            ctx.stroke();
            ctx.restore();
          }
        },
      }],
    });
  },

  // --- Render: Pitch Usage Table (below chart) ---

  _renderPitchTable: function (data) {
    var container = document.getElementById('player-pitch-usage-table');
    container.innerHTML = '';

    var pitchRows = this._getPitchRows(data.pitcher, data.team);
    if (pitchRows.length === 0) return;

    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table';

    // Header
    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    for (var i = 0; i < this.PITCH_TABLE_COLS.length; i++) {
      var th = document.createElement('th');
      th.textContent = this.PITCH_TABLE_COLS[i].label;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body
    var tbody = document.createElement('tbody');
    for (var r = 0; r < pitchRows.length; r++) {
      var row = pitchRows[r];
      var tr = document.createElement('tr');
      for (var c = 0; c < this.PITCH_TABLE_COLS.length; c++) {
        var col = this.PITCH_TABLE_COLS[c];
        var td = document.createElement('td');
        if (col.key === 'pitchType') {
          var badge = document.createElement('span');
          badge.className = 'pitch-badge-sm';
          badge.style.backgroundColor = Utils.getPitchColor(row.pitchType);
          badge.textContent = row.pitchType;
          td.appendChild(badge);
        } else {
          var val = row[col.key];
          td.textContent = col.format ? col.format(val) : (val != null ? val : '—');
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    container.appendChild(table);
  },

  // --- Hitter: Batted Ball Chart (donut) ---

  _renderBattedBallChart: function (data) {
    this.destroyChart();

    var canvas = document.getElementById('player-pitch-chart');
    var ctx = canvas.getContext('2d');

    var gb = data.gbPct || 0;
    var ld = data.ldPct || 0;
    var fb = data.fbPct || 0;
    var pu = data.puPct || 0;

    var isDark = document.body.classList.contains('dark-mode');
    var labelColor = isDark ? '#ccc' : '#333';

    this.chart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['GB', 'LD', 'FB', 'PU'],
        datasets: [{
          data: [
            Math.round(gb * 1000) / 10,
            Math.round(ld * 1000) / 10,
            Math.round(fb * 1000) / 10,
            Math.round(pu * 1000) / 10
          ],
          backgroundColor: ['#4e79a7', '#59a14f', '#f28e2b', '#e15759'],
          borderWidth: 2,
          borderColor: isDark ? '#1a1a2e' : '#fff'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: '55%',
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            labels: { color: labelColor, usePointStyle: true, padding: 12, font: { size: 12 } }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.label + ': ' + ctx.parsed.toFixed(1) + '%';
              }
            }
          }
        }
      }
    });
  },

  // --- Hitter: Stats Table (below chart) ---

  _renderHitterStatsTable: function (data) {
    var container = document.getElementById('player-pitch-usage-table');
    container.innerHTML = '';

    var statRows = [
      { label: 'AVG', value: data.avg != null ? data.avg.toFixed(3).replace(/^0/, '') : '—' },
      { label: 'OBP', value: data.obp != null ? data.obp.toFixed(3).replace(/^0/, '') : '—' },
      { label: 'SLG', value: data.slg != null ? data.slg.toFixed(3).replace(/^0/, '') : '—' },
      { label: 'OPS', value: data.ops != null ? data.ops.toFixed(3).replace(/^0/, '') : '—' },
      { label: 'ISO', value: data.iso != null ? data.iso.toFixed(3).replace(/^0/, '') : '—' },
      { label: 'BABIP', value: data.babip != null ? data.babip.toFixed(3).replace(/^0/, '') : '—' },
      { label: 'HR', value: data.hr != null ? data.hr : '—' },
      { label: 'XBH', value: data.xbh != null ? data.xbh : '—' },
      { label: 'Pull%', value: data.pullPct != null ? (data.pullPct * 100).toFixed(1) + '%' : '—' },
      { label: 'Oppo%', value: data.oppoPct != null ? (data.oppoPct * 100).toFixed(1) + '%' : '—' },
    ];

    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table';
    var thead = document.createElement('thead');
    var hrow = document.createElement('tr');
    var th1 = document.createElement('th'); th1.textContent = 'Stat'; hrow.appendChild(th1);
    var th2 = document.createElement('th'); th2.textContent = 'Value'; hrow.appendChild(th2);
    thead.appendChild(hrow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    for (var i = 0; i < statRows.length; i++) {
      var tr = document.createElement('tr');
      var tdLabel = document.createElement('td');
      tdLabel.textContent = statRows[i].label;
      tdLabel.style.fontWeight = '600';
      var tdVal = document.createElement('td');
      tdVal.textContent = statRows[i].value;
      tr.appendChild(tdLabel);
      tr.appendChild(tdVal);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    container.appendChild(table);
  },

  // --- Hitter lookup ---

  _findHitterByMlbId: function (mlbId) {
    mlbId = parseInt(mlbId, 10);
    var hitterData = window.HITTER_DATA || [];
    for (var i = 0; i < hitterData.length; i++) {
      if (hitterData[i].mlbId === mlbId) return hitterData[i];
    }
    return null;
  },

  // --- URL Routing ---

  checkURL: function () {
    var hash = window.location.hash.replace(/^#/, '');
    var match = hash.match(/player=(\d+)/);
    if (match) {
      this.open(match[1]);
      return true;
    }
    return false;
  },
};
