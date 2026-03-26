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
    { key: 'kbbPct',            label: 'K-BB %',           format: function(v) { return Utils.formatPct(v, true); } },
    { key: 'barrelPctAgainst',  label: 'Barrel %',         format: function(v) { return Utils.formatPct(v); } },
    { key: 'hardHitPct',        label: 'Hard-Hit %',       format: function(v) { return Utils.formatPct(v); } },
    { key: 'gbPct',             label: 'GB %',             format: function(v) { return Utils.formatPct(v); } },
    { key: 'extension',         label: 'Extension',        format: function(v) { return v != null ? Utils.formatFeetInches(v) : '—'; } },
  ],

  // Percentile stat definitions for the hitting section
  HITTING_STATS: [
    { key: 'avgEVAll',        label: 'Avg EV (All)',     format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'medEV',           label: 'Avg EV (LA > 0)',  format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'ev75',            label: 'EV75',             format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'maxEV',           label: 'Max EV',           format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'hardHitPct',      label: 'Hard-Hit %',       format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPct',       label: 'Barrel %',         format: function(v) { return Utils.formatPct(v); } },
    { key: 'laSweetSpotPct',  label: 'Sweet-Spot %',     format: function(v) { return Utils.formatPct(v); } },
    { key: 'kPct',            label: 'K %',              format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct',           label: 'BB %',             format: function(v) { return Utils.formatPct(v); } },
    { key: 'izContactPct',    label: 'IZ Contact %',     format: function(v) { return Utils.formatPct(v); } },
    { key: 'whiffPct',        label: 'Whiff %',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'chasePct',        label: 'Chase %',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'batSpeed',        label: 'Bat Speed',        format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
  ],

  // Hitter Stats table columns (single row)
  HITTER_STATS_COLS: [
    { key: 'g', label: 'G', format: function(v) { return v != null ? v : '—'; } },
    { key: 'pa', label: 'PA', format: function(v) { return v != null ? v : '—'; } },
    { key: 'ab', label: 'AB', format: function(v) { return v != null ? v : '—'; } },
    { key: 'avg', label: 'AVG', format: function(v) { return v != null ? v.toFixed(3).replace(/^0/, '') : '—'; } },
    { key: 'obp', label: 'OBP', format: function(v) { return v != null ? v.toFixed(3).replace(/^0/, '') : '—'; } },
    { key: 'slg', label: 'SLG', format: function(v) { return v != null ? v.toFixed(3).replace(/^0/, '') : '—'; } },
    { key: 'ops', label: 'OPS', format: function(v) { return v != null ? v.toFixed(3).replace(/^0/, '') : '—'; } },
    { key: 'iso', label: 'ISO', format: function(v) { return v != null ? v.toFixed(3).replace(/^0/, '') : '—'; } },
    { key: 'babip', label: 'BABIP', format: function(v) { return v != null ? v.toFixed(3).replace(/^0/, '') : '—'; } },
    { key: 'hrFbPct', label: 'HR/FB', format: function(v) { return Utils.formatPct(v); } },
    { key: 'kPct', label: 'K%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct', label: 'BB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'doubles', label: '2B', format: function(v) { return v != null ? v : '—'; } },
    { key: 'triples', label: '3B', format: function(v) { return v != null ? v : '—'; } },
    { key: 'hr', label: 'HR', format: function(v) { return v != null ? v : '—'; } },
    { key: 'xbh', label: 'XBH', format: function(v) { return v != null ? v : '—'; } },
    { key: 'tb', label: 'TB', format: function(v) { return v != null ? v : '—'; } },
    { key: 'sb', label: 'SB', format: function(v) { return v != null ? v : '—'; } },
    { key: 'cs', label: 'CS', format: function(v) { return v != null ? v : '—'; } },
    { key: 'sbPct', label: 'SB%', format: function(v) { return v != null ? v.toFixed(1) + '%' : '—'; } },
  ],

  // Hitter Batted Ball table columns (per pitch type + total)
  HITTER_BATTED_BALL_COLS: [
    { key: 'pitchType', label: 'Pitch' },
    { key: 'count', label: 'Count', format: function(v) { return v != null ? v : '—'; } },
    { key: 'nBip', label: 'BIP', format: function(v) { return v != null ? v : '—'; } },
    { key: 'babip', label: 'BABIP', format: function(v) { return v != null ? v.toFixed(3) : '—'; } },
    { key: 'avgEVAll', label: 'Avg EV', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'medEV', label: 'Avg EV (LA>0)', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'ev75', label: 'EV75', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'maxEV', label: 'Max EV', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'hardHitPct', label: 'HardHit%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPct', label: 'Barrel%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'laSweetSpotPct', label: 'Sweet-Spot%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'gbPct', label: 'GB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'ldPct', label: 'LD%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'fbPct', label: 'FB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'puPct', label: 'PU%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'hrFbPct', label: 'HR/FB', format: function(v) { return Utils.formatPct(v); } },
    { key: 'pullPct', label: 'Pull%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'middlePct', label: 'Mid%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'oppoPct', label: 'Oppo%', format: function(v) { return Utils.formatPct(v); } },
  ],

  // Hitter Plate Discipline table columns (per pitch type + total)
  HITTER_PLATE_DISCIPLINE_COLS: [
    { key: 'pitchType', label: 'Pitch' },
    { key: 'count', label: 'Count', format: function(v) { return v != null ? v : '—'; } },
    { key: 'nSwings', label: 'Swings', format: function(v) { return v != null ? v : '—'; } },
    { key: 'swingPct', label: 'Swing%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'izSwingPct', label: 'IZ Swing%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'chasePct', label: 'Chase%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'izSwChase', label: 'IZ Sw-Chase%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'contactPct', label: 'Contact%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'izContactPct', label: 'IZ Contact%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'whiffPct', label: 'Whiff%', format: function(v) { return Utils.formatPct(v); } },
  ],

  // Hitter Bat Tracking table columns (placeholder)
  HITTER_BAT_TRACKING_COLS: [
    { key: 'batSpeed', label: 'Bat Speed', format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'swingLength', label: 'Swing Length', format: function(v) { return v != null ? v.toFixed(1) + ' ft' : '—'; } },
    { key: 'attackAngle', label: 'Attack Angle', format: function(v) { return v != null ? v.toFixed(1) + '°' : '—'; } },
    { key: 'attackDir', label: 'Attack Dir', format: function(v) { return v != null ? v.toFixed(1) + '°' : '—'; } },
    { key: 'swingPathTilt', label: 'Swing Path Tilt', format: function(v) { return v != null ? v.toFixed(1) + '°' : '—'; } },
  ],

  // Pitch usage table columns
  PITCH_TABLE_COLS: [
    { key: 'pitchType', label: 'Pitch' },
    { key: 'count', label: 'Count', format: function(v) { return v != null ? v : '—'; } },
    { key: 'usagePct', label: 'Usage', format: function(v) { return Utils.formatPct(v); } },
    { key: 'velocity', label: 'MPH',   format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'spinRate', label: 'Spin',   format: function(v) { return v != null ? Math.round(v) : '—'; } },
    { key: 'breakTilt', label: 'OTilt', format: function(v) { return v || '—'; } },
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
    { key: 'breakTilt', label: 'OTilt', format: function(v) { return v || '—'; } },
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

  // Stats table (single row, pitcher-level) — matches leaderboard column order
  STATS_COLS: [
    { key: 'g', label: 'G', format: function(v) { return v != null ? v : '—'; } },
    { key: 'gs', label: 'GS', format: function(v) { return v != null ? v : '—'; } },
    { key: 'ip', label: 'IP', format: function(v) { return v != null ? v : '—'; } },
    { key: 'w', label: 'W', format: function(v) { return v != null ? v : '—'; } },
    { key: 'l', label: 'L', format: function(v) { return v != null ? v : '—'; } },
    { key: 'sv', label: 'SV', format: function(v) { return v != null ? v : '—'; } },
    { key: 'hld', label: 'HLD', format: function(v) { return v != null ? v : '—'; } },
    { key: 'kPct', label: 'K%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct', label: 'BB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'kbbPct', label: 'K-BB%', format: function(v) { return Utils.formatPct(v, true); } },
    { key: 'era', label: 'ERA', format: function(v) { return v != null ? v.toFixed(2) : '—'; } },
    { key: 'fip', label: 'FIP', format: function(v) { return v != null ? v.toFixed(2) : '—'; } },
    { key: 'xFIP', label: 'xFIP', format: function(v) { return v != null ? v.toFixed(2) : '—'; } },
    { key: 'siera', label: 'SIERA', format: function(v) { return v != null ? v.toFixed(2) : '—'; } },
  ],

  // Batted Ball table (per pitch type + total)
  BATTED_BALL_COLS: [
    { key: 'pitchType', label: 'Pitch' },
    { key: 'count', label: 'Count', format: function(v) { return v != null ? v : '—'; } },
    { key: 'nBip', label: 'BIP', format: function(v) { return v != null ? v : '—'; } },
    { key: 'babip', label: 'BABIP', format: function(v) { return v != null ? v.toFixed(3) : '—'; } },
    { key: 'avgEVAgainst', label: 'Avg EV', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'maxEVAgainst', label: 'Max EV', format: function(v) { return v != null ? v.toFixed(1) : '—'; } },
    { key: 'hardHitPct', label: 'HardHit%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPctAgainst', label: 'Barrel%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'gbPct', label: 'GB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'ldPct', label: 'LD%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'fbPct', label: 'FB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'puPct', label: 'PU%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'hrFbPct', label: 'HR/FB', format: function(v) { return Utils.formatPct(v); } },
  ],

  // Plate Discipline table (per pitch type + total)
  PLATE_DISCIPLINE_COLS: [
    { key: 'pitchType', label: 'Pitch' },
    { key: 'count', label: 'Count', format: function(v) { return v != null ? v : '—'; } },
    { key: 'nSwings', label: 'Swings', format: function(v) { return v != null ? v : '—'; } },
    { key: 'strikePct', label: 'Strike%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'izPct', label: 'Zone%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'cswPct', label: 'CSW%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'swStrPct', label: 'SwStr%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'swStrRate', label: 'Whiff%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'izWhiffPct', label: 'IZ Whiff%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'chasePct', label: 'Chase%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'fpsPct', label: 'FPS%', format: function(v) { return Utils.formatPct(v); } },
  ],

  // Get player data for current game type (data is already game-type-specific via DataStore)
  _getFilteredPlayerData: function (data, isPitcher) {
    // Data is already filtered to the active game type via DataStore/updateGlobals
    // Just look up the player in the current dataset
    var nameKey = isPitcher ? 'pitcher' : 'hitter';
    var source = isPitcher ? window.PITCHER_DATA : window.HITTER_DATA;
    if (!source) return data;

    var name = data[nameKey];
    var team = data.team;
    for (var i = 0; i < source.length; i++) {
      if (source[i][nameKey] === name && source[i].team === team) return source[i];
    }
    return null;
  },

  // Get pitch-level rows for current game type (data is already game-type-specific)
  _getFilteredPitchRows: function (data) {
    // Data is already filtered to the active game type via DataStore/updateGlobals
    var result = this._getPitchRows(data.pitcher, data.team);
    return result;
  },

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
    this._playerGameType = DataStore.gameType || 'RS';
    this._currentData = data;
    this._renderPlayerGameTypeToggle();
    this._renderGameLog(data);
    this._renderPitcherContent(data);
    this._bindHandToggles();
    this._bindGameLog();
  },

  // Check if there is data for the current game type (data is already game-type-specific)
  _hasDataForGameType: function (data) {
    var isPitcher = !!(data.pitcher);
    if (isPitcher) {
      var details = window.PITCH_DETAILS || {};
      var key = data.pitcher + '|' + data.team;
      var pitches = details[key];
      return pitches && pitches.length > 0;
    } else {
      // For hitters, check if they exist in the current dataset
      var hitterData = window.HITTER_DATA || [];
      for (var i = 0; i < hitterData.length; i++) {
        if (hitterData[i].hitter === data.hitter && hitterData[i].team === data.team) return true;
      }
      return false;
    }
  },

  // Render game-date-sensitive sections (called on initial load and game date change)
  _renderPitcherContent: function (data) {
    document.getElementById('player-percentiles').innerHTML = '';
    // Clear all content sections
    var sections = ['player-pitch-usage-table', 'player-stats-table', 'player-expanded-pitch-table',
                    'player-batted-ball-table', 'player-plate-discipline-table',
                    'player-heat-maps', 'player-count-table'];
    for (var i = 0; i < sections.length; i++) {
      var el = document.getElementById(sections[i]);
      if (el) el.innerHTML = '';
    }
    this.destroyChart();
    // Update pitch usage (left column) based on game date filter
    this._renderUsage(data);

    if (!this._hasDataForGameType(data)) {
      var container = document.getElementById('player-percentiles');
      container.innerHTML = '<p style="color:var(--text-secondary);padding:20px;text-align:center;">No data available for this period.</p>';
      return;
    }
    // Get aggregator-filtered data for stats/percentiles
    var filteredData = this._getFilteredPlayerData(data, true) || data;
    var filteredPitchRows = this._getFilteredPitchRows(data);
    // Store for use by table renderers
    this._filteredData = filteredData;
    this._filteredPitchRows = filteredPitchRows;

    this._renderPitchRunValues(filteredData);
    this._renderPercentiles(filteredData, this.PITCHING_STATS, true);
    this._renderMovementChart(data); // uses PITCH_DETAILS, already filtered
    this._renderPitchTable(data); // uses PITCH_DETAILS, already filtered
    this._renderStatsTable(filteredData);
    this._renderExpandedPitchTable(data); // will use _filteredPitchRows
    this._renderPlateDisciplineTable(data); // will use _filteredPitchRows
    this._renderBattedBallTable(data); // will use _filteredPitchRows
    this._renderHeatMaps(data);
    this._renderCountTable(data);
  },

  // Get PITCH_DETAILS for this pitcher (already game-type-specific), optionally filtered by _gameDate
  _getFilteredDetails: function (data) {
    var details = window.PITCH_DETAILS || {};
    var key = data.pitcher + '|' + data.team;
    var pitches = details[key];
    if (!pitches || pitches.length === 0) return [];

    // Filter by specific game date if set
    if (this._gameDate) {
      var gd = this._gameDate;
      pitches = pitches.filter(function (p) { return p.gd === gd; });
    }
    return pitches;
  },

  // Get unique game dates for this pitcher from PITCH_DETAILS (already game-type-specific)
  _getGameDates: function (data) {
    var details = window.PITCH_DETAILS || {};
    var key = data.pitcher + '|' + data.team;
    var pitches = details[key];
    if (!pitches) return [];

    var dateSet = {};
    for (var i = 0; i < pitches.length; i++) {
      var gd = pitches[i].gd;
      if (gd) dateSet[gd] = true;
    }
    return Object.keys(dateSet).sort();
  },

  _renderGameLog: function (data) {
    var container = document.getElementById('player-game-log');
    container.innerHTML = '';
    var dates = this._getGameDates(data);
    if (dates.length === 0) { container.style.display = 'none'; return; }

    container.style.display = '';
    var label = document.createElement('span');
    label.className = 'game-log-label';
    label.textContent = 'Game:';
    container.appendChild(label);

    var select = document.createElement('select');
    select.id = 'player-game-select';
    select.className = 'game-log-select';

    var allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = 'All Games';
    select.appendChild(allOpt);

    for (var i = 0; i < dates.length; i++) {
      var opt = document.createElement('option');
      opt.value = dates[i];
      var parts = dates[i].split('-');
      opt.textContent = parseInt(parts[1]) + '/' + parseInt(parts[2]) + '/' + parts[0];
      select.appendChild(opt);
    }

    if (this._gameDate) select.value = this._gameDate;
    container.appendChild(select);
  },

  _bindGameLog: function () {
    var self = this;
    this._gameLogHandler = function () {
      var select = document.getElementById('player-game-select');
      if (!select) return;
      var date = select.value || null;
      if (date === (self._gameDate || '')) return;
      self._gameDate = date || null;
      if (self._currentData) self._renderPitcherContent(self._currentData);
    };
    var select = document.getElementById('player-game-select');
    if (select) select.addEventListener('change', this._gameLogHandler);
  },

  _unbindGameLog: function () {
    if (this._gameLogHandler) {
      var select = document.getElementById('player-game-select');
      if (select) select.removeEventListener('change', this._gameLogHandler);
      this._gameLogHandler = null;
    }
  },

  _renderHitterPage: function (data) {
    this._showHitterLayout();
    this._renderHitterIdentity(data);
    this._playerGameType = DataStore.gameType || 'RS';
    this._currentData = data;
    this._sprayMode = 'all';
    this._renderPlayerGameTypeToggle();
    this._renderHitterContent(data);
    this._bindSprayToggle();
  },

  _renderHitterContent: function (data) {
    document.getElementById('player-percentiles').innerHTML = '';
    // Clear hitter content sections
    var sections = ['player-hitter-stats-table', 'player-hitter-batted-ball-table',
                    'player-hitter-plate-discipline-table', 'player-hitter-bat-tracking-table'];
    for (var i = 0; i < sections.length; i++) {
      var el = document.getElementById(sections[i]);
      if (el) el.innerHTML = '';
    }

    if (!this._hasDataForGameType(data)) {
      var container = document.getElementById('player-percentiles');
      container.innerHTML = '<p style="color:var(--text-secondary);padding:20px;text-align:center;">No data available for this period.</p>';
      return;
    }
    this._renderHitterRunValue(data);
    this._renderPercentiles(data, this.HITTING_STATS, true);
    this._renderSprayChart(data);
    this._renderHitterSmallStats(data);
    this._renderHitterStatsFullTable(data);
    this._renderHitterPlateDisciplineTable(data);
    this._renderHitterBattedBallTable(data);
    this._renderHitterBatTrackingTable(data);
  },

  _showPitcherLayout: function () {
    var usageSection = document.querySelector('.player-usage-section');
    var movementCol = document.querySelector('.player-col-movement');
    if (usageSection) usageSection.style.display = '';
    if (movementCol) movementCol.style.display = '';
    // Reset section title
    var title = document.querySelector('.player-col-movement .section-title');
    if (title) title.textContent = 'Movement Profile';
    // Show pitcher pitch table, hide spray elements
    var pitchTable = document.getElementById('player-pitch-usage-table');
    if (pitchTable) pitchTable.style.display = '';
    var sprayToggle = document.getElementById('spray-toggle-inline');
    if (sprayToggle) sprayToggle.style.display = 'none';
    var sprayLegend = document.getElementById('spray-legend-inline');
    if (sprayLegend) sprayLegend.style.display = 'none';
    // Hide hitter-specific sections
    var hitterSections = ['player-spray-section', 'player-hitter-stats-section',
      'player-hitter-batted-ball-section', 'player-hitter-plate-discipline-section',
      'player-hitter-bat-tracking-section'];
    for (var i = 0; i < hitterSections.length; i++) {
      var el = document.getElementById(hitterSections[i]);
      if (el) el.style.display = 'none';
    }
    // Show pitcher sections
    var pitcherSections = ['player-stats-section', 'player-expanded-pitch-section',
      'player-batted-ball-section', 'player-plate-discipline-section',
      'player-location-section', 'player-count-section'];
    for (var j = 0; j < pitcherSections.length; j++) {
      var el2 = document.getElementById(pitcherSections[j]);
      if (el2) el2.style.display = '';
    }
  },

  _showHitterLayout: function () {
    // Hide pitcher-only sections
    var usageSection = document.querySelector('.player-usage-section');
    if (usageSection) usageSection.style.display = 'none';
    // Show movement column — repurpose for spray chart
    var movementCol = document.querySelector('.player-col-movement');
    if (movementCol) movementCol.style.display = '';
    var title = document.querySelector('.player-col-movement .section-title');
    if (title) title.textContent = 'Spray Chart';
    // Hide pitcher pitch table below chart, show spray toggle + legend
    var pitchTable = document.getElementById('player-pitch-usage-table');
    if (pitchTable) pitchTable.style.display = 'none';
    var sprayToggle = document.getElementById('spray-toggle-inline');
    if (sprayToggle) sprayToggle.style.display = '';
    var sprayLegend = document.getElementById('spray-legend-inline');
    if (sprayLegend) sprayLegend.style.display = '';
    var pitcherSections = ['player-stats-section', 'player-expanded-pitch-section',
      'player-batted-ball-section', 'player-plate-discipline-section',
      'player-location-section', 'player-count-section'];
    for (var i = 0; i < pitcherSections.length; i++) {
      var el = document.getElementById(pitcherSections[i]);
      if (el) el.style.display = 'none';
    }
    // Hide game log for hitters
    var gameLog = document.getElementById('player-game-log');
    if (gameLog) gameLog.style.display = 'none';
    // Show hitter-specific full-width sections
    var hitterSections = ['player-hitter-stats-section',
      'player-hitter-batted-ball-section', 'player-hitter-plate-discipline-section',
      'player-hitter-bat-tracking-section'];
    for (var j = 0; j < hitterSections.length; j++) {
      var el2 = document.getElementById(hitterSections[j]);
      if (el2) el2.style.display = '';
    }
    // Hide full-width spray section (it's in the column now)
    var spraySec = document.getElementById('player-spray-section');
    if (spraySec) spraySec.style.display = 'none';
  },

  // --- Render: Player Game Type Toggle ---
  _renderPlayerGameTypeToggle: function () {
    // Remove any existing toggle
    var existing = document.querySelector('.player-game-type-toggle');
    if (existing) existing.remove();

    var self = this;
    var gt = this._playerGameType || 'RS';

    var toggleContainer = document.createElement('div');
    toggleContainer.className = 'player-game-type-toggle game-type-toggle';
    toggleContainer.innerHTML = '<button class="game-type-btn ' + (gt === 'ST' ? 'active' : '') + '" data-type="ST">Spring Training</button>' +
      '<button class="game-type-btn ' + (gt === 'RS' ? 'active' : '') + '" data-type="RS">Regular Season</button>';

    // Insert after the back button in the nav area
    var nav = document.querySelector('.player-page-nav');
    var backBtn = document.getElementById('player-back');
    if (nav && backBtn) {
      // Insert after back button but before game log
      backBtn.parentNode.insertBefore(toggleContainer, backBtn.nextSibling);
    }

    this._playerGameTypeHandler = function (e) {
      var btn = e.target.closest('.game-type-btn');
      if (!btn) return;
      var type = btn.getAttribute('data-type');
      if (type === self._playerGameType) return;
      self._playerGameType = type;
      self._gameDate = null; // reset game date filter when switching

      // Switch DataStore to new game type and reload globals + aggregator
      DataStore.gameType = type;
      DataStore.updateGlobals();
      var microData = DataStore.active().microData;
      if (microData) {
        Aggregator.load(microData);
      } else {
        Aggregator.loaded = false;
      }

      // Update active state
      var btns = toggleContainer.querySelectorAll('.game-type-btn');
      for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('active', btns[i].getAttribute('data-type') === type);
      }

      // Re-find the player in the new dataset
      var mlbId = self._currentData ? self._currentData.mlbId : null;
      if (mlbId) {
        var newData = self._playerType === 'pitcher'
          ? self._findPitcherByMlbId(mlbId)
          : self._findHitterByMlbId(mlbId);
        if (newData) self._currentData = newData;
      }

      // Re-render content
      if (self._currentData) {
        if (self._playerType === 'pitcher') {
          self._renderGameLog(self._currentData);
          self._bindGameLog();
          self._renderPitcherContent(self._currentData);
        } else {
          self._renderHitterContent(self._currentData);
        }
      }
    };
    toggleContainer.addEventListener('click', this._playerGameTypeHandler);
  },

  _unbindPlayerGameTypeToggle: function () {
    var existing = document.querySelector('.player-game-type-toggle');
    if (existing && this._playerGameTypeHandler) {
      existing.removeEventListener('click', this._playerGameTypeHandler);
      this._playerGameTypeHandler = null;
    }
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
    this._unbindPlayerGameTypeToggle();

    // Restore DataStore to the main leaderboard's game type
    var mainGameType = (typeof window.getCurrentGameType === 'function' ? window.getCurrentGameType() : null) || 'RS';
    if (DataStore.gameType !== mainGameType) {
      DataStore.gameType = mainGameType;
      DataStore.updateGlobals();
      var microData = DataStore.active().microData;
      if (microData) {
        Aggregator.load(microData);
      } else {
        Aggregator.loaded = false;
      }
    }
    this._playerGameType = null;

    // Hide new sections
    var sections = ['player-expanded-pitch-section', 'player-location-section', 'player-count-section',
      'player-spray-section', 'player-hitter-stats-section', 'player-hitter-batted-ball-section',
      'player-hitter-plate-discipline-section', 'player-hitter-bat-tracking-section'];
    for (var i = 0; i < sections.length; i++) {
      var el = document.getElementById(sections[i]);
      if (el) el.style.display = 'none';
    }
    this._unbindSprayToggle();

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
      img.src = 'https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_426,q_auto:best/v1/people/' + data.mlbId + '/headshot/67/current';
      img.alt = data.hitter;
    } else {
      img.src = '';
      img.alt = '';
    }
    img.onerror = function () {
      this.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160"><rect fill="%23333" width="160" height="160"/><text fill="%23888" font-size="40" x="50%" y="55%" text-anchor="middle" dominant-baseline="middle">?</text></svg>');
    };

    // Name
    var nameParts = data.hitter.split(', ');
    var displayName = nameParts.length === 2 ? nameParts[1] + ' ' + nameParts[0] : data.hitter;
    document.getElementById('player-name').textContent = displayName;

    // Bats | Team | Age (fetched from MLB API)
    var batsLabel = data.stands === 'S' ? 'Switch' : (data.stands === 'L' ? 'Bats: L' : 'Bats: R');
    var posEl = document.getElementById('player-position');
    var ageEl = document.getElementById('player-age');
    posEl.textContent = batsLabel + ' | ' + (data.team || '');
    ageEl.textContent = '';

    if (data.mlbId) {
      fetch('https://statsapi.mlb.com/api/v1/people/' + data.mlbId)
        .then(function (res) { return res.json(); })
        .then(function (json) {
          var person = json.people && json.people[0];
          if (person && person.currentAge != null) {
            posEl.textContent = batsLabel + ' | ' + (data.team || '') + ' | Age: ' + person.currentAge;
          }
        })
        .catch(function () { /* silently ignore */ });
    }
  },

  // --- Render: Pitch Usage (vs LHH / vs RHH) ---

  _renderUsage: function (data) {
    // Use filtered pitch details (respects game date filter)
    var pitches = this._getFilteredDetails(data);

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
    var isPitcher = !!(data.pitcher);

    // Determine if player qualifies based on team games played
    // Micro data is already game-type-specific, so no date range needed
    var teamGames = Aggregator.loaded ? Aggregator.getTeamGamesPlayed() : {};
    var tg = teamGames[data.team] || 0;
    var isQualified;
    if (isPitcher) {
      // Parse IP string (e.g., "6.1" = 6⅓ innings) to float
      var ipStr = data.ip;
      var ipFloat = 0;
      if (ipStr != null) {
        var parts = String(ipStr).split('.');
        ipFloat = parseInt(parts[0], 10) + (parts[1] ? parseInt(parts[1], 10) / 3 : 0);
      }
      // Starter (GS/G > 0.5) needs 1.0 IP/game, reliever needs 0.1 IP/game
      var g = data.g || 0;
      var gs = data.gs || 0;
      var isStarter = g > 0 && (gs / g) > 0.5;
      var ipThreshold = isStarter ? tg * 1.0 : tg * 0.1;
      isQualified = ipFloat >= ipThreshold;
    } else {
      isQualified = (data.pa || 0) >= tg * 3.1;
    }
    var alwaysColorKeys = isPitcher ? { fbVelo: true, extension: true } : { maxEV: true };

    for (var i = 0; i < statsDef.length; i++) {
      var stat = statsDef[i];
      var val = data[stat.key];
      var pctl = data[stat.key + '_pctl'];
      var showColor = isQualified || alwaysColorKeys[stat.key];

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
        if (showColor) {
          var bgColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
          var textColor = isDark ? '#fff' : Utils.percentileTextColor(pctl);
          circle.style.backgroundColor = bgColor;
          circle.style.color = textColor;
        } else {
          circle.style.backgroundColor = isDark ? 'rgba(150,150,150,0.3)' : '#ccc';
          circle.style.color = isDark ? '#aaa' : '#666';
        }
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
        if (showColor) {
          var barColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
          barFill.style.backgroundColor = barColor;
        } else {
          barFill.style.backgroundColor = isDark ? 'rgba(150,150,150,0.3)' : '#ccc';
        }
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

    // Get this pitcher's pitch rows (use filtered if available)
    var pitchRows = this._filteredPitchRows || this._getPitchRows(data.pitcher, data.team);
    if (pitchRows.length === 0) return;

    // Section label
    var sectionLabel = document.createElement('div');
    sectionLabel.className = 'pctl-section-label';
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

    // Compute total pitches for overall RV qualifying
    var totalPitches = 0;
    for (var tp = 0; tp < pitchRows.length; tp++) {
      totalPitches += (pitchRows[tp].count || 0);
    }

    // Helper to build a single percentile row
    // pitchCount: number of pitches for this row (null = use totalPitches for overall)
    function buildPctlRow(labelContent, displayVal, pctl, pitchCount) {
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
      // Determine if this row qualifies for coloring
      // Per-pitch: 50 pitches. Overall: 100 pitches.
      var rvQualified;
      if (pitchCount === null) {
        rvQualified = totalPitches >= 100; // overall
      } else {
        rvQualified = (pitchCount || 0) >= 50; // per-pitch
      }

      var circleWrap = document.createElement('div');
      circleWrap.className = 'pctl-circle-wrap';
      if (pctl != null) {
        var circle = document.createElement('div');
        circle.className = 'pctl-circle';
        if (rvQualified) {
          var bgColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
          var textColor = isDark ? '#fff' : Utils.percentileTextColor(pctl);
          circle.style.backgroundColor = bgColor;
          circle.style.color = textColor;
        } else {
          circle.style.backgroundColor = isDark ? 'rgba(150,150,150,0.3)' : '#ccc';
          circle.style.color = isDark ? '#aaa' : '#666';
        }
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
        if (rvQualified) {
          var barColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
          barFill.style.backgroundColor = barColor;
        } else {
          barFill.style.backgroundColor = isDark ? 'rgba(150,150,150,0.3)' : '#ccc';
        }
      }
      barTrack.appendChild(barFill);

      row.appendChild(labelEl);
      row.appendChild(barTrack);
      row.appendChild(circleWrap);
      row.appendChild(valEl);
      return row;
    }

    // Overall row (sum of all pitch RVs — positive = good for pitcher)
    var overallDisplay = hasAnyRV ? overallRV : null;
    container.appendChild(buildPctlRow('Overall', overallDisplay, data.runValue_pctl, null));

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
      var displayVal = rawRV;
      var pctl = pitch.runValue_pctl;

      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      badge.style.backgroundColor = Utils.getPitchColor(pitch.pitchType);
      badge.textContent = pitch.pitchType;

      container.appendChild(buildPctlRow(badge, displayVal, pctl, pitch.count));
    }

    // Divider before the stat percentiles that follow
    var divider = document.createElement('div');
    divider.style.cssText = 'border-top: 1px solid var(--border, #ddd); margin: 12px 0 8px 0;';
    container.appendChild(divider);
  },

  // --- Render: Hitter Run Value (overall only) ---

  _renderHitterRunValue: function (data) {
    var container = document.getElementById('player-percentiles');

    var sectionLabel = document.createElement('div');
    sectionLabel.className = 'pctl-section-label';
    sectionLabel.style.cssText = 'font-size: 12px; font-weight: 700; text-transform: uppercase; color: var(--text-muted, #888); margin-bottom: 6px; letter-spacing: 0.5px;';
    sectionLabel.textContent = 'Batter Run Value';
    container.appendChild(sectionLabel);

    var rv = data.runValue;
    var row = document.createElement('div');
    row.className = 'pctl-row';
    var label = document.createElement('span');
    label.className = 'pctl-label';
    label.textContent = 'Overall';
    var barWrap = document.createElement('div');
    barWrap.className = 'pctl-bar-wrap';
    var bar = document.createElement('div');
    bar.className = 'pctl-bar';
    bar.style.width = '0%';
    bar.style.backgroundColor = '#ccc';
    barWrap.appendChild(bar);
    var valSpan = document.createElement('span');
    valSpan.className = 'pctl-value';
    valSpan.textContent = rv != null ? rv.toFixed(1) : '—';
    row.appendChild(label);
    row.appendChild(barWrap);
    row.appendChild(valSpan);
    container.appendChild(row);

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
    var gridColor = isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.08)';
    var tickColor = isDark ? '#ccc' : '#666';
    var crossColor = isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.15)';

    this.chart = new Chart(ctx, {
      type: 'scatter',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 1,
        animation: false,
        scales: {
          x: {
            title: { display: true, text: 'Horizontal Break (in)', color: tickColor },
            min: -25, max: 25,
            grid: { color: gridColor },
            ticks: { color: tickColor, stepSize: 5 },
          },
          y: {
            title: { display: true, text: 'Induced Vertical Break (in)', color: tickColor },
            min: -25, max: 25,
            grid: { color: gridColor },
            ticks: { color: tickColor, stepSize: 5 },
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

  // Aggregate PITCH_DETAILS into per-pitch-type rows (same format as PITCH_DATA)
  _aggregateDetailsToRows: function (pitches) {
    var byType = {};
    var total = pitches.length;
    for (var i = 0; i < pitches.length; i++) {
      var p = pitches[i];
      if (!p.pt) continue;
      if (!byType[p.pt]) byType[p.pt] = { count: 0, velos: [], spins: [], ivbs: [], hbs: [], tiltSins: [], tiltCoss: [] };
      var g = byType[p.pt];
      g.count++;
      if (p.v != null) g.velos.push(p.v);
      if (p.sp != null) g.spins.push(p.sp);
      if (p.ivb != null) g.ivbs.push(p.ivb);
      if (p.hb != null) g.hbs.push(p.hb);
      // Tilt: convert H:MM to angle for circular mean
      if (p.tl) {
        var parts = p.tl.split(':');
        if (parts.length === 2) {
          var h = parseInt(parts[0], 10);
          var m = parseInt(parts[1], 10);
          if (h === 12) h = 0;
          var totalMin = h * 60 + m;
          var angle = totalMin * 2 * Math.PI / 720;
          g.tiltSins.push(Math.sin(angle));
          g.tiltCoss.push(Math.cos(angle));
        }
      }
    }
    var rows = [];
    for (var pt in byType) {
      var g = byType[pt];
      var avg = function(arr) { return arr.length > 0 ? arr.reduce(function(a,b){return a+b;},0) / arr.length : null; };
      // Circular mean for tilt
      var tiltStr = null;
      if (g.tiltSins.length > 0) {
        var avgSin = avg(g.tiltSins);
        var avgCos = avg(g.tiltCoss);
        var avgAngle = Math.atan2(avgSin, avgCos);
        var avgMin = ((avgAngle * 720 / (2 * Math.PI)) % 720 + 720) % 720;
        var tH = Math.floor(avgMin / 60);
        var tM = Math.round(avgMin % 60);
        if (tM === 60) { tH++; tM = 0; }
        if (tH === 0) tH = 12;
        tiltStr = tH + ':' + (tM < 10 ? '0' : '') + tM;
      }
      rows.push({
        pitchType: pt,
        count: g.count,
        usagePct: total > 0 ? g.count / total : null,
        velocity: avg(g.velos),
        spinRate: avg(g.spins),
        breakTilt: tiltStr,
        indVertBrk: avg(g.ivbs),
        horzBrk: avg(g.hbs),
      });
    }
    rows.sort(function(a, b) { return (b.usagePct || 0) - (a.usagePct || 0); });
    return rows;
  },

  _renderPitchTable: function (data) {
    var container = document.getElementById('player-pitch-usage-table');
    container.innerHTML = '';

    // Always compute from filtered details (respects game type + game date)
    var filtered = this._getFilteredDetails(data);
    var pitchRows = filtered.length > 0 ? this._aggregateDetailsToRows(filtered) : [];
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

    var pitchRows = this._filteredPitchRows || this._getPitchRows(data.pitcher, data.team);
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

  // --- Render: Stats Table (single pitcher row) ---

  _renderStatsTable: function (data) {
    var section = document.getElementById('player-stats-section');
    var container = document.getElementById('player-stats-table');
    container.innerHTML = '';

    if (!data) { if (section) section.style.display = 'none'; return; }
    section.style.display = '';

    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table expanded-pitch-table';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    for (var i = 0; i < this.STATS_COLS.length; i++) {
      var th = document.createElement('th');
      th.textContent = this.STATS_COLS[i].label;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var tr = document.createElement('tr');
    for (var c = 0; c < this.STATS_COLS.length; c++) {
      var col = this.STATS_COLS[c];
      var td = document.createElement('td');
      var val = data[col.key];
      td.textContent = col.format ? col.format(val) : (val != null ? val : '—');
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
    table.appendChild(tbody);
    container.appendChild(table);
  },

  // --- Render: Batted Ball Table (per pitch type + total) ---

  _renderBattedBallTable: function (data) {
    var section = document.getElementById('player-batted-ball-section');
    var container = document.getElementById('player-batted-ball-table');
    container.innerHTML = '';

    var pitchRows = this._filteredPitchRows || this._getPitchRows(data.pitcher, data.team);
    if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
    section.style.display = '';

    // Compute total row from filtered pitcher-level data
    var totalRow = { pitchType: 'Total' };
    var fd = this._filteredData || data;
    for (var k = 0; k < this.BATTED_BALL_COLS.length; k++) {
      var key = this.BATTED_BALL_COLS[k].key;
      if (key !== 'pitchType') totalRow[key] = fd[key];
    }

    this._renderPerPitchTable(container, this.BATTED_BALL_COLS, pitchRows, totalRow);
  },

  // --- Render: Plate Discipline Table (per pitch type + total) ---

  _renderPlateDisciplineTable: function (data) {
    var section = document.getElementById('player-plate-discipline-section');
    var container = document.getElementById('player-plate-discipline-table');
    container.innerHTML = '';

    var pitchRows = this._filteredPitchRows || this._getPitchRows(data.pitcher, data.team);
    if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
    section.style.display = '';

    // Compute total row from filtered pitcher-level data
    var totalRow = { pitchType: 'Total' };
    var fd = this._filteredData || data;
    for (var k = 0; k < this.PLATE_DISCIPLINE_COLS.length; k++) {
      var key = this.PLATE_DISCIPLINE_COLS[k].key;
      if (key !== 'pitchType') totalRow[key] = fd[key];
    }

    this._renderPerPitchTable(container, this.PLATE_DISCIPLINE_COLS, pitchRows, totalRow);
  },

  // --- Shared: Render per-pitch-type table with total row ---

  _renderPerPitchTable: function (container, cols, pitchRows, totalRow) {
    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table expanded-pitch-table';

    // Header
    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    for (var i = 0; i < cols.length; i++) {
      var th = document.createElement('th');
      th.textContent = cols[i].label;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body — pitch type rows
    var tbody = document.createElement('tbody');
    for (var r = 0; r < pitchRows.length; r++) {
      var row = pitchRows[r];
      var tr = document.createElement('tr');
      for (var c = 0; c < cols.length; c++) {
        var col = cols[c];
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

    // Total row
    if (totalRow) {
      var totalTr = document.createElement('tr');
      totalTr.style.fontWeight = 'bold';
      totalTr.style.borderTop = '2px solid var(--border-color, #ccc)';
      for (var c2 = 0; c2 < cols.length; c2++) {
        var col2 = cols[c2];
        var td2 = document.createElement('td');
        if (col2.key === 'pitchType') {
          td2.textContent = 'Total';
        } else {
          var val2 = totalRow[col2.key];
          td2.textContent = col2.format ? col2.format(val2) : (val2 != null ? val2 : '—');
        }
        totalTr.appendChild(td2);
      }
      tbody.appendChild(totalTr);
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
    th0.textContent = 'Pitch';
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
      tdLabel.style.textAlign = 'center';
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

  // --- Hitter: Spray Chart ---

  _renderSprayChart: function (data) {
    var canvas = document.getElementById('player-pitch-chart');
    if (!canvas) return;
    // Set canvas size for spray chart — wider than tall to fit foul lines
    canvas.width = 500;
    canvas.height = 420;
    var ctx = canvas.getContext('2d');
    var W = canvas.width;
    var H = canvas.height;
    var isDark = document.body.classList.contains('dark');

    ctx.clearRect(0, 0, W, H);

    // Home plate in Statcast coords
    var HP_X = 125.42;
    var HP_Y = 198.27;

    // Canvas mapping: HP at bottom center, field fills canvas with padding
    var canvasHPX = W / 2;
    var canvasHPY = H - 15;
    // Max radius so foul lines don't clip: W/2 / cos(45°) with padding
    var maxRadius = (W / 2 - 15) / 0.707;
    var scale = 1.8; // pixels per statcast unit

    function toCanvas(hcX, hcY) {
      var dx = hcX - HP_X;
      var dy = HP_Y - hcY; // Statcast Y increases downward, field Y increases upward
      return [canvasHPX + dx * scale, canvasHPY - dy * scale];
    }

    // Clear to transparent
    ctx.clearRect(0, 0, W, H);

    // Draw outfield grass (only inside foul lines — no background fill)
    ctx.fillStyle = isDark ? '#1a3a1a' : '#c8e6c8';
    ctx.beginPath();
    ctx.moveTo(canvasHPX, canvasHPY);
    // Foul lines angle: LF line at ~135 deg from right, RF line at ~45 deg
    var foulAngleLeft = -Math.PI * 3 / 4;
    var foulAngleRight = -Math.PI / 4;
    ctx.arc(canvasHPX, canvasHPY, maxRadius, foulAngleLeft, foulAngleRight);
    ctx.closePath();
    ctx.fill();

    // Draw infield dirt
    ctx.fillStyle = isDark ? '#3a2e1e' : '#d4b896';
    ctx.beginPath();
    ctx.arc(canvasHPX, canvasHPY, maxRadius * 0.28, foulAngleLeft, foulAngleRight);
    ctx.lineTo(canvasHPX, canvasHPY);
    ctx.closePath();
    ctx.fill();

    // Draw fence outline using average distances
    // Convert feet to statcast-ish units (roughly 2.5 statcast units per foot)
    var fenceDistances = [
      { angle: foulAngleLeft, dist: 330 },      // LF
      { angle: -Math.PI * 5 / 8, dist: 379 },   // LF gap
      { angle: -Math.PI / 2, dist: 401 },        // CF
      { angle: -Math.PI * 3 / 8, dist: 379 },    // RF gap
      { angle: foulAngleRight, dist: 329 },       // RF
    ];
    var fenceScale = maxRadius / 401; // normalize so CF = max radius on canvas
    ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.3)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (var fi = 0; fi < fenceDistances.length; fi++) {
      var fd = fenceDistances[fi];
      var r = fd.dist * fenceScale;
      var fx = canvasHPX + r * Math.cos(fd.angle);
      var fy = canvasHPY + r * Math.sin(fd.angle);
      if (fi === 0) ctx.moveTo(fx, fy);
      else ctx.lineTo(fx, fy);
    }
    ctx.stroke();

    // Draw foul lines
    ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.8)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(canvasHPX, canvasHPY);
    ctx.lineTo(canvasHPX + maxRadius * 1.02 * Math.cos(foulAngleLeft), canvasHPY + maxRadius * 1.02 * Math.sin(foulAngleLeft));
    ctx.moveTo(canvasHPX, canvasHPY);
    ctx.lineTo(canvasHPX + maxRadius * 1.02 * Math.cos(foulAngleRight), canvasHPY + maxRadius * 1.02 * Math.sin(foulAngleRight));
    ctx.stroke();

    // Draw infield diamond
    var baseDist = maxRadius * 0.13; // approximate base distance scaled to field
    ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.7)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(canvasHPX, canvasHPY); // home
    ctx.lineTo(canvasHPX + baseDist * 0.707, canvasHPY - baseDist * 0.707); // 1B
    ctx.lineTo(canvasHPX, canvasHPY - baseDist * 1.414); // 2B
    ctx.lineTo(canvasHPX - baseDist * 0.707, canvasHPY - baseDist * 0.707); // 3B
    ctx.closePath();
    ctx.stroke();

    // Draw home plate
    ctx.fillStyle = isDark ? '#ddd' : '#fff';
    ctx.beginPath();
    ctx.moveTo(canvasHPX - 5, canvasHPY);
    ctx.lineTo(canvasHPX + 5, canvasHPY);
    ctx.lineTo(canvasHPX + 4, canvasHPY + 4);
    ctx.lineTo(canvasHPX, canvasHPY + 6);
    ctx.lineTo(canvasHPX - 4, canvasHPY + 4);
    ctx.closePath();
    ctx.fill();

    // Get BIP data
    var microData = window.MICRO_DATA;
    if (!microData || !microData.hitterBip) {
      this._renderSprayLegend('all');
      return;
    }

    var lookups = microData.lookups || {};
    var hitterIdx = (lookups.hitters || []).indexOf(data.hitter);
    if (hitterIdx < 0) {
      this._renderSprayLegend('all');
      return;
    }

    var bipCols = microData.hitterBipCols;
    var hiIdx = bipCols.indexOf('hitterIdx');
    var hcXIdx = bipCols.indexOf('hcX');
    var hcYIdx = bipCols.indexOf('hcY');
    var bbTypeIdx = bipCols.indexOf('bbType');
    var eventIdx = bipCols.indexOf('event');
    var evIdx = bipCols.indexOf('exitVelo');

    var bips = microData.hitterBip;
    var filteredBips = [];
    for (var bi = 0; bi < bips.length; bi++) {
      if (bips[bi][hiIdx] === hitterIdx) {
        filteredBips.push(bips[bi]);
      }
    }

    var mode = this._sprayMode || 'all';
    var bbTypeColors = { 0: '#4e79a7', 1: '#59a14f', 2: '#f28e2b', 3: '#e15759' };
    var hitEventColors = { 1: '#ff8c00', 2: '#7b68ee', 3: '#20b2aa', 4: '#dc143c' };

    // Plot BIP dots
    for (var di = 0; di < filteredBips.length; di++) {
      var bip = filteredBips[di];
      var hcX = bip[hcXIdx];
      var hcY = bip[hcYIdx];
      if (hcX == null || hcY == null) continue;

      var bbType = bip[bbTypeIdx];
      var evtCode = bip[eventIdx];
      var ev = bip[evIdx];

      var color = null;
      if (mode === 'all') {
        color = bbTypeColors[bbType] || '#888';
      } else if (mode === 'hits') {
        if (evtCode >= 1 && evtCode <= 4) {
          color = hitEventColors[evtCode] || '#888';
        } else {
          continue;
        }
      } else if (mode === 'hard') {
        if (ev != null && ev >= 95) {
          color = bbTypeColors[bbType] || '#888';
        } else {
          continue;
        }
      }

      var pos = toCanvas(hcX, hcY);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.75;
      ctx.beginPath();
      ctx.arc(pos[0], pos[1], 4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1.0;

    this._renderSprayLegend(mode);
  },

  _renderSprayLegend: function (mode) {
    var container = document.getElementById('spray-legend-inline') || document.getElementById('player-spray-legend');
    if (!container) return;
    container.innerHTML = '';

    var items = [];
    if (mode === 'all' || mode === 'hard') {
      items = [
        { color: '#4e79a7', label: 'GB' },
        { color: '#59a14f', label: 'LD' },
        { color: '#f28e2b', label: 'FB' },
        { color: '#e15759', label: 'PU' },
      ];
    } else if (mode === 'hits') {
      items = [
        { color: '#ff8c00', label: 'Single' },
        { color: '#7b68ee', label: 'Double' },
        { color: '#20b2aa', label: 'Triple' },
        { color: '#dc143c', label: 'HR' },
      ];
    }

    for (var i = 0; i < items.length; i++) {
      var item = document.createElement('span');
      item.className = 'spray-legend-item';
      var dot = document.createElement('span');
      dot.className = 'spray-legend-dot';
      dot.style.backgroundColor = items[i].color;
      item.appendChild(dot);
      item.appendChild(document.createTextNode(items[i].label));
      container.appendChild(item);
    }
  },

  _bindSprayToggle: function () {
    var self = this;
    this._sprayToggleHandler = function (e) {
      var btn = e.target.closest('.spray-toggle-btn');
      if (!btn) return;
      var mode = btn.getAttribute('data-mode');
      if (mode === self._sprayMode) return;
      self._sprayMode = mode;
      var btns = document.querySelectorAll('.spray-toggle-btn');
      for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
      btn.classList.add('active');
      if (self._currentData) self._renderSprayChart(self._currentData);
    };
    var toggle = document.getElementById('spray-toggle-inline') || document.getElementById('spray-toggle');
    if (toggle) toggle.addEventListener('click', this._sprayToggleHandler);
  },

  _unbindSprayToggle: function () {
    if (this._sprayToggleHandler) {
      var el = document.getElementById('spray-toggle');
      if (el) el.removeEventListener('click', this._sprayToggleHandler);
      this._sprayToggleHandler = null;
    }
  },

  // --- Hitter: Small Stats (AVG/OBP/SLG/OPS/ISO below spray chart) ---

  _renderHitterSmallStats: function (data) {
    // Render into the movement col's table area (reuse player-pitch-usage-table)
    var container = document.getElementById('player-pitch-usage-table');
    container.innerHTML = '';
    // Small stats not shown for hitters since we have full table; leave empty
  },

  // --- Hitter: Full Stats Table ---

  _renderHitterStatsFullTable: function (data) {
    var section = document.getElementById('player-hitter-stats-section');
    var container = document.getElementById('player-hitter-stats-table');
    if (!container) return;
    container.innerHTML = '';

    if (!data) { if (section) section.style.display = 'none'; return; }
    section.style.display = '';

    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table expanded-pitch-table';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    for (var i = 0; i < this.HITTER_STATS_COLS.length; i++) {
      var th = document.createElement('th');
      th.textContent = this.HITTER_STATS_COLS[i].label;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var tr = document.createElement('tr');
    for (var c = 0; c < this.HITTER_STATS_COLS.length; c++) {
      var col = this.HITTER_STATS_COLS[c];
      var td = document.createElement('td');
      var val = data[col.key];
      td.textContent = col.format ? col.format(val) : (val != null ? val : '—');
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
    table.appendChild(tbody);
    container.appendChild(table);
  },

  // --- Hitter: Get pitch rows from HITTER_PITCH_LB ---

  _getHitterPitchRows: function (hitterName, team) {
    var hpData = window.HITTER_PITCH_LB || [];
    var rows = [];
    for (var i = 0; i < hpData.length; i++) {
      var r = hpData[i];
      if (r.hitter === hitterName && r.team === team &&
          r.pitchType !== 'All' && r.pitchType !== 'Hard' &&
          r.pitchType !== 'Breaking' && r.pitchType !== 'Offspeed') {
        rows.push(r);
      }
    }
    rows.sort(function (a, b) { return (b.count || 0) - (a.count || 0); });
    return rows;
  },

  // --- Hitter: Batted Ball Table ---

  _renderHitterBattedBallTable: function (data) {
    var section = document.getElementById('player-hitter-batted-ball-section');
    var container = document.getElementById('player-hitter-batted-ball-table');
    if (!container) return;
    container.innerHTML = '';

    var pitchRows = this._getHitterPitchRows(data.hitter, data.team);
    if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
    section.style.display = '';

    var totalRow = { pitchType: 'Total' };
    for (var k = 0; k < this.HITTER_BATTED_BALL_COLS.length; k++) {
      var key = this.HITTER_BATTED_BALL_COLS[k].key;
      if (key !== 'pitchType') totalRow[key] = data[key];
    }

    this._renderPerPitchTable(container, this.HITTER_BATTED_BALL_COLS, pitchRows, totalRow);
  },

  // --- Hitter: Plate Discipline Table ---

  _renderHitterPlateDisciplineTable: function (data) {
    var section = document.getElementById('player-hitter-plate-discipline-section');
    var container = document.getElementById('player-hitter-plate-discipline-table');
    if (!container) return;
    container.innerHTML = '';

    var pitchRows = this._getHitterPitchRows(data.hitter, data.team);
    if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
    section.style.display = '';

    var totalRow = { pitchType: 'Total' };
    for (var k = 0; k < this.HITTER_PLATE_DISCIPLINE_COLS.length; k++) {
      var key = this.HITTER_PLATE_DISCIPLINE_COLS[k].key;
      if (key !== 'pitchType') totalRow[key] = data[key];
    }

    this._renderPerPitchTable(container, this.HITTER_PLATE_DISCIPLINE_COLS, pitchRows, totalRow);
  },

  // --- Hitter: Bat Tracking Table (placeholder) ---

  _renderHitterBatTrackingTable: function (data) {
    var section = document.getElementById('player-hitter-bat-tracking-section');
    var container = document.getElementById('player-hitter-bat-tracking-table');
    if (!container) return;
    container.innerHTML = '';

    section.style.display = '';

    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table expanded-pitch-table';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    for (var i = 0; i < this.HITTER_BAT_TRACKING_COLS.length; i++) {
      var th = document.createElement('th');
      th.textContent = this.HITTER_BAT_TRACKING_COLS[i].label;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var tr = document.createElement('tr');
    for (var c = 0; c < this.HITTER_BAT_TRACKING_COLS.length; c++) {
      var col = this.HITTER_BAT_TRACKING_COLS[c];
      var td = document.createElement('td');
      var val = data[col.key];
      td.textContent = col.format ? col.format(val) : (val != null ? val : '—');
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
    table.appendChild(tbody);
    container.appendChild(table);
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
