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
    { key: 'count', label: 'Count', format: function(v) { return v != null ? v : '—'; } },
    { key: 'usagePct', label: 'Usage', format: function(v) { return Utils.formatPct(v); } },
    { key: 'velocity', label: 'MPH',   format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'spinRate', label: 'Spin',   format: function(v) { return v != null ? Math.round(v) : '—'; } },
    { key: 'breakTilt', label: 'Tilt',  format: function(v) { return v || '—'; } },
    { key: 'indVertBrk', label: 'IVB',  format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
    { key: 'horzBrk',    label: 'HB',   format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
  ],

  // Expanded pitch metrics table (full detail view)
  EXPANDED_PITCH_COLS: [
    { key: 'pitchType', label: 'Pitch' },
    { key: 'count', label: 'Count', format: function(v) { return v != null ? v : '—'; } },
    { key: 'usagePct', label: 'Usage', format: function(v) { return Utils.formatPct(v); } },
    { key: 'velocity', label: 'Velo', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'maxVelo', label: 'Max Velo', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'spinRate', label: 'Spin', format: function(v) { return v != null ? Math.round(v) : '—'; } },
    { key: 'breakTilt', label: 'Tilt', format: function(v) { return v || '—'; } },
    { key: 'indVertBrk', label: 'IVB', format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
    { key: 'horzBrk', label: 'HB', format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
    { key: 'relPosZ', label: 'RelZ', format: function(v) { return v != null ? Utils.formatFeetInches(v) : '—'; } },
    { key: 'relPosX', label: 'RelX', format: function(v) { return v != null ? Utils.formatFeetInches(v) : '—'; } },
    { key: 'extension', label: 'Ext', format: function(v) { return v != null ? Utils.formatFeetInches(v) : '—'; } },
    { key: 'armAngle', label: 'Arm Angle', format: function(v) { return v != null ? v.toFixed(1) + '°' : '—'; } },
    { key: 'vaa', label: 'VAA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
    { key: 'nVAA', label: 'nVAA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
    { key: 'haa', label: 'HAA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
    { key: 'nHAA', label: 'nHAA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
    { key: 'vra', label: 'VRA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
    { key: 'hra', label: 'HRA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
  ],

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

    this.isOpen = true;
    this._playerType = pitcherData ? 'pitcher' : 'hitter';

    // Show player page as fixed overlay (leaderboard stays rendered underneath)
    document.getElementById('player-page').style.display = 'block';

    if (pitcherData) {
      this._renderPitcherPage(pitcherData);
    } else {
      this._renderHitterPage(hitterData);
    }

    // Scroll overlay to top
    document.getElementById('player-page').scrollTop = 0;

    // Click-outside-to-close: listen on the player-page backdrop
    this._bindClickOutside();
  },

  _renderPitcherPage: function (data) {
    this._showPitcherLayout();
    this._renderIdentity(data);
    this._heatMapHand = 'R';
    this._countHand = 'R';
    this._gameDate = null; // null = all games
    this._currentData = data;
    this._renderGameLog(data);
    this._renderPitcherContent(data);
    this._bindHandToggles();
    this._bindGameLog();
  },

  // Render all pitcher content sections (called on initial load and game date change)
  _renderPitcherContent: function (data) {
    this._renderUsage(data);
    document.getElementById('player-percentiles').innerHTML = '';
    this._renderPitchRunValues(data);
    this._renderPercentiles(data, this.PITCHING_STATS, true);
    this._renderMovementChart(data);
    this._renderPitchTable(data);
    this._renderExpandedPitchTable(data);
    this._renderHeatMaps(data);
    this._renderCountTable(data);
  },

  // Get PITCH_DETAILS for this pitcher, optionally filtered by _gameDate
  _getFilteredDetails: function (data) {
    var details = window.PITCH_DETAILS || {};
    var key = data.pitcher + '|' + data.team;
    var pitches = details[key];
    if (!pitches || pitches.length === 0) return [];
    if (!this._gameDate) return pitches;
    var gd = this._gameDate;
    return pitches.filter(function (p) { return p.gd === gd; });
  },

  // Get unique game dates for this pitcher from PITCH_DETAILS
  _getGameDates: function (data) {
    var details = window.PITCH_DETAILS || {};
    var key = data.pitcher + '|' + data.team;
    var pitches = details[key];
    if (!pitches) return [];
    var dateSet = {};
    for (var i = 0; i < pitches.length; i++) {
      if (pitches[i].gd) dateSet[pitches[i].gd] = true;
    }
    return Object.keys(dateSet).sort();
  },

  _renderGameLog: function (data) {
    var container = document.getElementById('player-game-log');
    container.innerHTML = '';
    var dates = this._getGameDates(data);
    if (dates.length <= 1) { container.style.display = 'none'; return; }

    container.style.display = '';
    var label = document.createElement('span');
    label.className = 'game-log-label';
    label.textContent = 'Game:';
    container.appendChild(label);

    // "All" chip
    var allChip = document.createElement('button');
    allChip.className = 'game-log-chip active';
    allChip.setAttribute('data-date', '');
    allChip.textContent = 'All';
    container.appendChild(allChip);

    // Date chips
    for (var i = 0; i < dates.length; i++) {
      var chip = document.createElement('button');
      chip.className = 'game-log-chip';
      chip.setAttribute('data-date', dates[i]);
      // Format date nicely: "3/5" from "2026-03-05"
      var parts = dates[i].split('-');
      chip.textContent = parseInt(parts[1]) + '/' + parseInt(parts[2]);
      container.appendChild(chip);
    }
  },

  _bindGameLog: function () {
    var self = this;
    this._gameLogHandler = function (e) {
      var chip = e.target.closest('.game-log-chip');
      if (!chip) return;
      var date = chip.getAttribute('data-date') || null;
      if (date === (self._gameDate || '')) return;
      self._gameDate = date || null;
      // Update active state
      var chips = document.querySelectorAll('#player-game-log .game-log-chip');
      for (var i = 0; i < chips.length; i++) chips[i].classList.remove('active');
      chip.classList.add('active');
      // Re-render content
      if (self._currentData) self._renderPitcherContent(self._currentData);
    };
    var container = document.getElementById('player-game-log');
    if (container) container.addEventListener('click', this._gameLogHandler);
  },

  _unbindGameLog: function () {
    if (this._gameLogHandler) {
      var container = document.getElementById('player-game-log');
      if (container) container.removeEventListener('click', this._gameLogHandler);
      this._gameLogHandler = null;
    }
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
    this._heatMapHand = 'R';
    this._countHand = 'R';
    this._gameDate = null;
    this._currentData = null;
    this.destroyChart();
    this._unbindClickOutside();
    this._unbindHandToggles();
    this._unbindGameLog();

    // Hide new sections
    var sections = ['player-expanded-pitch-section', 'player-location-section', 'player-count-section'];
    for (var i = 0; i < sections.length; i++) {
      var el = document.getElementById(sections[i]);
      if (el) el.style.display = 'none';
    }

    document.getElementById('player-page').style.display = 'none';
    if (this._lastRoute) {
      history.replaceState(null, '', '#' + this._lastRoute);
    }
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
    var pitches = this._getFilteredDetails(data);

    // Aggregate usage from pitch details by batter hand
    var usageByHand = { L: {}, R: {} };
    var totalByHand = { L: 0, R: 0 };

    for (var i = 0; i < pitches.length; i++) {
      var p = pitches[i];
      var bh = p.bh;
      var pt = p.pt;
      if (!bh || !pt) continue;
      if (!usageByHand[bh]) usageByHand[bh] = {};
      if (!usageByHand[bh][pt]) usageByHand[bh][pt] = 0;
      usageByHand[bh][pt]++;
      if (!totalByHand[bh]) totalByHand[bh] = 0;
      totalByHand[bh]++;
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

    var isDark = document.body.classList.contains('dark');

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
    var isDark = document.body.classList.contains('dark');

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

    // Per-pitch-type rows (fixed order)
    var PITCH_ORDER = ['FF','SI','CF','FC','SL','ST','CU','SV','CH','FS','KN'];
    var sortedPitchRows = pitchRows.slice().sort(function(a, b) {
      var ai = PITCH_ORDER.indexOf(a.pitchType);
      var bi = PITCH_ORDER.indexOf(b.pitchType);
      if (ai === -1) ai = 999;
      if (bi === -1) bi = 999;
      return ai - bi;
    });
    for (var i = 0; i < sortedPitchRows.length; i++) {
      var pitch = sortedPitchRows[i];
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

    // Build movement data from filtered pitch details
    var filteredPitches = this._getFilteredDetails(data);
    if (filteredPitches.length === 0) return;
    var groups = {};
    for (var fi = 0; fi < filteredPitches.length; fi++) {
      var fp = filteredPitches[fi];
      if (fp.ivb == null || fp.hb == null) continue;
      if (!groups[fp.pt]) groups[fp.pt] = [];
      groups[fp.pt].push({ x: fp.hb, y: fp.ivb });
    }
    if (Object.keys(groups).length === 0) return;

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

    var isDark = document.body.classList.contains('dark');
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

  // --- Render: Expanded Pitch Table (full detail view) ---

  _renderExpandedPitchTable: function (data) {
    var section = document.getElementById('player-expanded-pitch-section');
    var container = document.getElementById('player-expanded-pitch-table');
    container.innerHTML = '';

    var pitchRows = this._getPitchRows(data.pitcher, data.team);
    if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }

    section.style.display = '';

    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table expanded-pitch-table';

    // Header
    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    for (var i = 0; i < this.EXPANDED_PITCH_COLS.length; i++) {
      var th = document.createElement('th');
      th.textContent = this.EXPANDED_PITCH_COLS[i].label;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body
    var tbody = document.createElement('tbody');
    for (var r = 0; r < pitchRows.length; r++) {
      var row = pitchRows[r];
      var tr = document.createElement('tr');
      for (var c = 0; c < this.EXPANDED_PITCH_COLS.length; c++) {
        var col = this.EXPANDED_PITCH_COLS[c];
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

  // --- Render: Heat Maps (pitch location density) ---

  _renderHeatMaps: function(data) {
    var section = document.getElementById('player-location-section');
    var grid = document.getElementById('player-heatmap-grid');
    grid.innerHTML = '';

    var pitches = this._getFilteredDetails(data);
    if (!pitches || pitches.length === 0) { section.style.display = 'none'; return; }

    section.style.display = '';
    var hand = this._heatMapHand || 'R';

    // Compute average strike zone across ALL pitches (not per-type)
    var szTopSum = 0, szBotSum = 0, szCount = 0;
    for (var i = 0; i < pitches.length; i++) {
      if (pitches[i].szt != null && pitches[i].szb != null) {
        szTopSum += pitches[i].szt;
        szBotSum += pitches[i].szb;
        szCount++;
      }
    }
    var avgSzTop = szCount > 0 ? szTopSum / szCount : 3.5;
    var avgSzBot = szCount > 0 ? szBotSum / szCount : 1.5;

    // Group by pitch type, filter by hand
    var byType = {};
    for (var i = 0; i < pitches.length; i++) {
      var p = pitches[i];
      if (p.bh !== hand) continue;
      if (p.px == null || p.pz == null) continue;
      if (!byType[p.pt]) byType[p.pt] = [];
      byType[p.pt].push(p);
    }

    // Sort pitch types by fixed order
    var PITCH_ORDER = ['FF','SI','CF','FC','SL','ST','CU','SV','CH','FS','KN'];
    var types = Object.keys(byType);
    types.sort(function(a, b) {
      var ai = PITCH_ORDER.indexOf(a); if (ai === -1) ai = 999;
      var bi = PITCH_ORDER.indexOf(b); if (bi === -1) bi = 999;
      return ai - bi;
    });

    // Render each pitch type
    for (var t = 0; t < types.length; t++) {
      var pt = types[t];
      var cell = document.createElement('div');
      cell.className = 'heatmap-cell';

      var label = document.createElement('div');
      label.className = 'heatmap-label';
      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      badge.style.backgroundColor = Utils.getPitchColor(pt);
      badge.textContent = pt;
      label.appendChild(badge);
      cell.appendChild(label);

      var canvas = document.createElement('canvas');
      canvas.width = 250;
      canvas.height = 300;
      cell.appendChild(canvas);

      grid.appendChild(cell);
      this._renderSingleHeatMap(canvas, byType[pt], avgSzTop, avgSzBot, hand);
    }
  },

  _renderSingleHeatMap: function(canvas, pitches, szTop, szBot, hand) {
    var ctx = canvas.getContext('2d');
    var W = canvas.width;
    var H = canvas.height;
    var isDark = document.body.classList.contains('dark');

    // Plot bounds in feet
    var xMin = -2.0, xMax = 2.0;
    var zMin = 0.5, zMax = 4.5;

    // Grid resolution
    var gridX = 50, gridZ = 60;
    var cellW = W / gridX;
    var cellH = H / gridZ;
    var bw = 0.25; // bandwidth in feet
    var bw2 = 2 * bw * bw;

    // Compute KDE density grid
    var density = new Array(gridX * gridZ);
    var maxDensity = 0;
    for (var gx = 0; gx < gridX; gx++) {
      for (var gz = 0; gz < gridZ; gz++) {
        var cx = xMin + (gx + 0.5) * (xMax - xMin) / gridX;
        var cz = zMax - (gz + 0.5) * (zMax - zMin) / gridZ; // flip z axis (top = high z)
        var d = 0;
        for (var p = 0; p < pitches.length; p++) {
          var dx = cx - pitches[p].px;
          var dz = cz - pitches[p].pz;
          d += Math.exp(-(dx * dx + dz * dz) / bw2);
        }
        var idx = gx + gz * gridX;
        density[idx] = d;
        if (d > maxDensity) maxDensity = d;
      }
    }

    // Clear canvas
    ctx.fillStyle = isDark ? '#1e1e3a' : '#f8f8f8';
    ctx.fillRect(0, 0, W, H);

    // Draw density
    if (maxDensity > 0) {
      for (var gx = 0; gx < gridX; gx++) {
        for (var gz = 0; gz < gridZ; gz++) {
          var norm = density[gx + gz * gridX] / maxDensity;
          if (norm < 0.05) continue;
          ctx.fillStyle = this._heatColor(norm);
          ctx.fillRect(gx * cellW, gz * cellH, cellW + 0.5, cellH + 0.5);
        }
      }
    }

    // Draw strike zone rectangle
    var zoneLeft = ((-0.83 - xMin) / (xMax - xMin)) * W;
    var zoneRight = ((0.83 - xMin) / (xMax - xMin)) * W;
    var zoneTop = ((zMax - szTop) / (zMax - zMin)) * H;
    var zoneBottom = ((zMax - szBot) / (zMax - zMin)) * H;

    ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)';
    ctx.lineWidth = 2;
    ctx.strokeRect(zoneLeft, zoneTop, zoneRight - zoneLeft, zoneBottom - zoneTop);

    // Draw home plate at bottom
    var plateY = ((zMax - 0.5) / (zMax - zMin)) * H; // approximate bottom
    var plateCX = W / 2;
    ctx.fillStyle = isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.15)';
    ctx.beginPath();
    ctx.moveTo(plateCX - 8, plateY);
    ctx.lineTo(plateCX + 8, plateY);
    ctx.lineTo(plateCX + 5, plateY + 5);
    ctx.lineTo(plateCX, plateY + 8);
    ctx.lineTo(plateCX - 5, plateY + 5);
    ctx.closePath();
    ctx.fill();

  },


  _heatColor: function(t) {
    // Blue (cold) -> white (mid) -> red (hot), like Baseball Savant
    var r, g, b;
    if (t < 0.5) {
      var s = t / 0.5;
      r = Math.round(8 + s * (255 - 8));
      g = Math.round(48 + s * (255 - 48));
      b = Math.round(107 + s * (255 - 107));
    } else {
      var s = (t - 0.5) / 0.5;
      r = Math.round(255 - s * (255 - 215));
      g = Math.round(255 - s * (255 - 48));
      b = Math.round(255 - s * (255 - 39));
    }
    return 'rgb(' + r + ',' + g + ',' + b + ')';
  },

  // --- Render: Count Table (pitch usage by count group) ---

  _renderCountTable: function(data) {
    var section = document.getElementById('player-count-section');
    var container = document.getElementById('player-count-table');
    container.innerHTML = '';

    var pitches = this._getFilteredDetails(data);
    if (pitches.length === 0) { section.style.display = 'none'; return; }

    section.style.display = '';
    var hand = this._countHand || 'R';

    var COUNT_GROUPS = {
      'First Pitch': ['0-0'],
      'Ahead': ['0-1', '0-2', '1-2'],
      'Behind': ['1-0', '2-0', '3-0', '2-1', '3-1'],
      'Even': ['1-1', '2-2'],
      'Two-Strike': ['0-2', '1-2', '2-2', '3-2']
    };
    var groupNames = ['First Pitch', 'Ahead', 'Behind', 'Even', 'Two-Strike'];

    // Build lookup: count string -> array of group names it belongs to
    var countToGroups = {};
    for (var g = 0; g < groupNames.length; g++) {
      var gn = groupNames[g];
      var counts = COUNT_GROUPS[gn];
      for (var c = 0; c < counts.length; c++) {
        if (!countToGroups[counts[c]]) countToGroups[counts[c]] = [];
        countToGroups[counts[c]].push(gn);
      }
    }

    // Filter by hand and group by pitch type and count group
    var pitchTypes = {};
    var groupTotals = {};
    for (var g = 0; g < groupNames.length; g++) groupTotals[groupNames[g]] = 0;

    for (var i = 0; i < pitches.length; i++) {
      var p = pitches[i];
      if (p.bh !== hand) continue;
      if (!p.cnt) continue;
      var groups = countToGroups[p.cnt];
      if (!groups) continue;

      if (!pitchTypes[p.pt]) {
        pitchTypes[p.pt] = { total: 0 };
        for (var g = 0; g < groupNames.length; g++) pitchTypes[p.pt][groupNames[g]] = 0;
      }
      pitchTypes[p.pt].total++;
      for (var g = 0; g < groups.length; g++) {
        pitchTypes[p.pt][groups[g]]++;
        groupTotals[groups[g]]++;
      }
    }

    // Sort pitch types by total count descending
    var types = Object.keys(pitchTypes);
    types.sort(function(a, b) { return pitchTypes[b].total - pitchTypes[a].total; });

    if (types.length === 0) { section.style.display = 'none'; return; }

    // Build HTML table
    var table = document.createElement('table');
    table.className = 'count-table';

    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    var th0 = document.createElement('th');
    th0.textContent = '';
    headRow.appendChild(th0);
    for (var g = 0; g < groupNames.length; g++) {
      var th = document.createElement('th');
      th.textContent = groupNames[g];
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    for (var t = 0; t < types.length; t++) {
      var pt = types[t];
      var tr = document.createElement('tr');

      var tdLabel = document.createElement('td');
      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      badge.style.backgroundColor = Utils.getPitchColor(pt);
      badge.textContent = pt;
      tdLabel.appendChild(badge);
      tr.appendChild(tdLabel);

      for (var g = 0; g < groupNames.length; g++) {
        var gn = groupNames[g];
        var td = document.createElement('td');
        var total = groupTotals[gn];
        if (total > 0) {
          var pct = (pitchTypes[pt][gn] / total * 100);
          td.textContent = pct.toFixed(1) + '%';
        } else {
          td.textContent = '—';
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    container.appendChild(table);
  },

  // --- Hand Toggle (for heat maps and count table) ---

  _bindHandToggles: function() {
    var self = this;
    // Heat map toggle
    this._heatToggleHandler = function(e) {
      var btn = e.target.closest('.hand-toggle-btn');
      if (!btn) return;
      var hand = btn.getAttribute('data-hand');
      if (hand === self._heatMapHand) return;
      self._heatMapHand = hand;
      var btns = document.querySelectorAll('#hand-toggle .hand-toggle-btn');
      for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
      btn.classList.add('active');
      if (self._currentData) self._renderHeatMaps(self._currentData);
    };
    var heatToggle = document.getElementById('hand-toggle');
    if (heatToggle) heatToggle.addEventListener('click', this._heatToggleHandler);

    // Count table toggle
    this._countToggleHandler = function(e) {
      var btn = e.target.closest('.hand-toggle-btn');
      if (!btn) return;
      var hand = btn.getAttribute('data-hand');
      if (hand === self._countHand) return;
      self._countHand = hand;
      var btns = document.querySelectorAll('#count-hand-toggle .hand-toggle-btn');
      for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
      btn.classList.add('active');
      if (self._currentData) self._renderCountTable(self._currentData);
    };
    var countToggle = document.getElementById('count-hand-toggle');
    if (countToggle) countToggle.addEventListener('click', this._countToggleHandler);
  },

  _unbindHandToggles: function() {
    if (this._heatToggleHandler) {
      var el = document.getElementById('hand-toggle');
      if (el) el.removeEventListener('click', this._heatToggleHandler);
      this._heatToggleHandler = null;
    }
    if (this._countToggleHandler) {
      var el = document.getElementById('count-hand-toggle');
      if (el) el.removeEventListener('click', this._countToggleHandler);
      this._countToggleHandler = null;
    }
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

    var isDark = document.body.classList.contains('dark');
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
