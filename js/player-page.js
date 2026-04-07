/* Player Page — full-page pitcher/hitter profile view */
var PlayerPage = {
  chart: null,
  isOpen: false,
  _playerType: null, // 'pitcher' or 'hitter'

  // Percentile stat definitions for the pitching section
  PITCHING_STATS: [
    // Expected stats
    { key: 'xBA',               label: 'xBA',              format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    { key: 'xSLG',              label: 'xSLG',             format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    { key: 'xwOBA',             label: 'xwOBA',            format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    { key: 'xwOBAcon',          label: 'xwOBAcon',         format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    // Stuff & command — velo rows injected dynamically before this point
    { key: '_veloPlaceholder',  label: '',                  format: function() { return ''; }, _dynamic: true },
    { key: 'strikePct',         label: 'Strike%',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'chasePct',          label: 'Chase%',           format: function(v) { return Utils.formatPct(v); } },
    { key: 'swStrPct',          label: 'Whiff%',           format: function(v) { return Utils.formatPct(v); } },
    { key: 'izWhiffPct',        label: 'IZ Whiff%',        format: function(v) { return Utils.formatPct(v); } },
    // Results
    { key: 'kPct',              label: 'K%',               format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct',             label: 'BB%',              format: function(v) { return Utils.formatPct(v); } },
    { key: 'kbbPct',            label: 'K-BB%',            format: function(v) { return Utils.formatPct(v, true); } },
    { key: 'siera',             label: 'SIERA',            format: function(v) { return v != null ? v.toFixed(2) : '—'; }, rocHide: true },
    // Contact quality
    { key: 'barrelPctAgainst',  label: 'Barrel%',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'gbPct',             label: 'GB%',              format: function(v) { return Utils.formatPct(v); } },
  ],

  // Percentile stat definitions for the hitting section
  HITTING_STATS: [
    { key: 'xBA',             label: 'xBA',              format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    { key: 'xSLG',            label: 'xSLG',             format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    { key: 'xwOBA',           label: 'xwOBA',            format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    { key: 'xwOBAsp',         label: 'xwOBASp',          format: function(v) { return v != null ? v.toFixed(3) : '—'; }, rocHide: true },
    { key: 'xWRCplus',        label: 'xWRC+',            format: function(v) { return v != null ? Math.round(v) : '—'; }, rocHide: true, noPercentile: true },
    { key: 'avgEVAll',        label: 'Avg EV',           format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'ev75',            label: 'EV75',             format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'hardHitPct',      label: 'Hard-Hit%',       format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPct',       label: 'Barrel%',         format: function(v) { return Utils.formatPct(v); } },
    { key: 'sacqPct',         label: 'SACQ%',           format: function(v) { return Utils.formatPct(v); } },
    { key: 'kPct',            label: 'K%',              format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct',           label: 'BB%',             format: function(v) { return Utils.formatPct(v); } },
    { key: 'whiffPct',        label: 'Whiff%',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'chasePct',        label: 'Chase%',          format: function(v) { return Utils.formatPct(v); } },
    { key: 'batSpeed',        label: 'Bat Speed',        format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; }, rocHide: true },
    { key: 'sprintSpeed',   label: 'Sprint Speed',     format: function(v) { return v != null ? v.toFixed(1) + ' ft/s' : '—'; }, rocHide: true, sprintQual: true },
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
    { key: 'wRCplus', label: 'wRC+', format: function(v) { return v != null ? v : '—'; }, rocHide: true },
    { key: 'xWRCplus', label: 'xWRC+', format: function(v) { return v != null ? v : '—'; } },
    { key: 'kPct', label: 'K%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'bbPct', label: 'BB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'doubles', label: '2B', format: function(v) { return v != null ? v : '—'; } },
    { key: 'triples', label: '3B', format: function(v) { return v != null ? v : '—'; } },
    { key: 'hr', label: 'HR', format: function(v) { return v != null ? v : '—'; } },
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
    { key: 'hardHitPct', label: 'Hard-Hit%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPct', label: 'Barrel%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'laSweetSpotPct', label: 'Sweet-Spot%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'gbPct', label: 'GB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'ldPct', label: 'LD%', format: function(v) { return Utils.formatPct(v); }, noPctl: true },
    { key: 'fbPct', label: 'FB%', format: function(v) { return Utils.formatPct(v); }, noPctl: true },
    { key: 'puPct', label: 'PU%', format: function(v) { return Utils.formatPct(v); }, noPctl: true },
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
    { key: 'firstPitchSwingPct', label: 'FPSw%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'contactPct', label: 'Contact%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'izContactPct', label: 'IZ Contact%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'whiffPct', label: 'Whiff%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'twoStrikeWhiffPct', label: '2K Whiff%', format: function(v) { return Utils.formatPct(v); } },
  ],

  // Hitter Bat Tracking table columns (placeholder)
  HITTER_BAT_TRACKING_COLS: [
    { key: 'batSpeed', label: 'Bat Speed', format: function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; } },
    { key: 'swingLength', label: 'Swing Length', format: function(v) { return v != null ? v.toFixed(1) + ' ft' : '—'; } },
    { key: 'attackAngle', label: 'Attack Angle', format: function(v) { return v != null ? v.toFixed(1) + '°' : '—'; } },
    { key: 'attackDirection', label: 'Attack Dir', format: function(v) { return v != null ? v.toFixed(1) + '°' : '—'; } },
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
    { key: 'armAngle',  label: 'Arm\u00B0', format: function(v) { return v != null ? v.toFixed(1) + '\u00B0' : '—'; } },
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
    { key: 'xIVB', label: 'xIVB', format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
    { key: 'ivbOE', label: 'IVBOE', format: function(v) { return v != null ? (v > 0 ? '+' : '') + v.toFixed(1) + '"' : '—'; } },
    { key: 'horzBrk', label: 'HB', format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
    { key: 'xHB', label: 'xHB', format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
    { key: 'hbOE', label: 'HBOE', format: function(v) { return v != null ? (v > 0 ? '+' : '') + v.toFixed(1) + '"' : '—'; } },
    { key: 'extension', label: 'Ext', format: function(v) { return v != null ? Utils.formatFeetInches(v) : '—'; } },
    { key: 'armAngle', label: 'Arm Angle', format: function(v) { return v != null ? v.toFixed(1) + '°' : '—'; } },
    { key: 'nVAA', label: 'nVAA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
    { key: 'nHAA', label: 'nHAA', format: function(v) { return v != null ? v.toFixed(2) + '°' : '—'; } },
    { key: 'tunnelDist', label: 'Tunnel', format: function(v) { return v != null ? v.toFixed(1) + '"' : '—'; } },
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
    { key: 'hardHitPct', label: 'Hard-Hit%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'barrelPctAgainst', label: 'Barrel%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'gbPct', label: 'GB%', format: function(v) { return Utils.formatPct(v); } },
    { key: 'ldPct', label: 'LD%', format: function(v) { return Utils.formatPct(v); }, noPctl: true },
    { key: 'fbPct', label: 'FB%', format: function(v) { return Utils.formatPct(v); }, noPctl: true },
    { key: 'puPct', label: 'PU%', format: function(v) { return Utils.formatPct(v); }, noPctl: true },
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
    { key: 'swStrPct', label: 'Whiff%', format: function(v) { return Utils.formatPct(v); } },
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
    var pctlLeg = document.getElementById('pctl-legend');
    if (pctlLeg) pctlLeg.style.display = 'none';

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
    this._zoneHand = 'R';
    this._zoneMetric = 'usage';
    this._platoonHand = 'all';
    this._gameDate = null; // null = all games
    this._playerGameType = 'RS';
    this._currentData = data;
    this._renderGameLog(data);
    this._renderPitcherContent(data);
    this._bindHandToggles();
    this._bindPlatoonToggle('pitcher');
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
    this._platoonHand = 'all';
    this._resetPlatoonToggleUI('pitcher-platoon-toggle');
    document.getElementById('player-percentiles').innerHTML = '';
    // Clear all content sections
    var sections = ['player-pitch-usage-table', 'player-stats-table', 'player-expanded-pitch-table',
                    'player-batted-ball-table', 'player-plate-discipline-table',
                    'player-heat-maps', 'player-zone-profiles', 'player-count-table'];
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

    // Check if ROC player
    var rocTeams = (DataStore.metadata && DataStore.metadata.rocTeams) || [];
    var isROCPlayer = rocTeams.indexOf(data.team) !== -1;

    if (!isROCPlayer) {
      this._renderPitchRunValues(filteredData);
    }

    var pitchingStats = this.PITCHING_STATS;
    if (isROCPlayer) {
      pitchingStats = pitchingStats.filter(function (s) { return !s.rocHide; });
    }
    this._renderPercentiles(filteredData, pitchingStats, true);
    this._renderMovementChart(data); // uses PITCH_DETAILS, already filtered
    this._renderPitchTable(data); // uses PITCH_DETAILS, already filtered
    this._renderStatsTable(filteredData);
    this._renderExpandedPitchTable(data); // will use _filteredPitchRows
    this._renderPlateDisciplineTable(data); // will use _filteredPitchRows
    this._renderBattedBallTable(data); // will use _filteredPitchRows
    this._renderHeatMaps(data);
    this._renderZoneProfiles(data);
    this._renderCountTable(data);
  },

  // Get PITCH_DETAILS for this pitcher (already game-type-specific), optionally filtered by _gameDate and _platoonDetailHand
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
    // Filter by batter hand when platoon toggle is active
    if (this._platoonDetailHand) {
      var bh = this._platoonDetailHand;
      pitches = pitches.filter(function (p) { return p.bh === bh; });
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
    this._platoonHand = 'all';
    this._playerGameType = 'RS';
    this._currentData = data;
    this._sprayMode = 'all';
    this._sprayBatSide = (data.stands === 'S') ? 'L' : null; // null = not switch hitter
    this._renderHitterContent(data);
    this._bindSprayToggle();
    this._bindSprayBatSideToggle(data);
    this._bindPlatoonToggle('hitter');
  },

  _renderHitterContent: function (data) {
    this._platoonHand = 'all';
    this._resetPlatoonToggleUI('hitter-platoon-toggle');
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
    // Check if this is a ROC/AAA player (no run value, bat speed, or expected stats)
    var rocTeams = (DataStore.metadata && DataStore.metadata.rocTeams) || [];
    var isROCPlayer = rocTeams.indexOf(data.team) !== -1;

    if (!isROCPlayer) {
      this._renderHitterRunValue(data);
    }

    // Filter out stats unavailable for ROC players
    var hittingStats = this.HITTING_STATS;
    if (isROCPlayer) {
      hittingStats = hittingStats.filter(function (s) { return !s.rocHide; });
    }
    this._renderPercentiles(data, hittingStats, true);
    this._renderSprayChart(data);
    this._renderLASprayChart(data);
    this._renderHitterSmallStats(data);
    this._renderHitterStatsFullTable(data, isROCPlayer);
    this._renderHitterPlateDisciplineTable(data);
    this._renderHitterBattedBallTable(data, isROCPlayer);
    if (!isROCPlayer) {
      this._renderHitterBatTrackingTable(data);
    }
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
    var hitterSections = ['player-spray-section', 'player-la-spray-section', 'player-hitter-stats-section',
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
    var aaLabel = document.getElementById('player-arm-angle');
    if (aaLabel) aaLabel.style.display = 'none';
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
    var hitterSections = ['player-la-spray-section', 'player-hitter-stats-section',
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


  close: function () {
    this.isOpen = false;
    this._heatMapHand = 'R';
    this._countHand = 'R';
    this._gameDate = null;
    this._currentData = null;
    this.destroyChart();
    this._unbindClickOutside();
    this._unbindHandToggles();
    this._unbindPlatoonToggle();
    this._unbindGameLog();
    this._playerGameType = null;

    // Hide new sections
    var sections = ['player-expanded-pitch-section', 'player-location-section', 'player-zone-profile-section', 'player-count-section',
      'player-spray-section', 'player-la-spray-section', 'player-hitter-stats-section', 'player-hitter-batted-ball-section',
      'player-hitter-plate-discipline-section', 'player-hitter-bat-tracking-section'];
    for (var i = 0; i < sections.length; i++) {
      var el = document.getElementById(sections[i]);
      if (el) el.style.display = 'none';
    }
    this._unbindSprayToggle();

    document.getElementById('player-page').style.display = 'none';
    var pctlLeg = document.getElementById('pctl-legend');
    if (pctlLeg) pctlLeg.style.display = '';
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

    // Bats/Throws | Team | Age (fetched from MLB API)
    var batHand = data.stands === 'S' ? 'S' : (data.stands === 'L' ? 'L' : 'R');
    var posEl = document.getElementById('player-position');
    var ageEl = document.getElementById('player-age');
    posEl.textContent = 'Bats: ' + batHand + ' | ' + (data.team || '');
    ageEl.textContent = '';

    if (data.mlbId) {
      fetch('https://statsapi.mlb.com/api/v1/people/' + data.mlbId)
        .then(function (res) { return res.json(); })
        .then(function (json) {
          var person = json.people && json.people[0];
          if (person) {
            var throwHand = person.pitchHand && person.pitchHand.code ? person.pitchHand.code : '';
            var btLabel = 'Bats/Throws: ' + batHand + '/' + throwHand;
            var agePart = person.currentAge != null ? ' | Age: ' + person.currentAge : '';
            posEl.textContent = btLabel + ' | ' + (data.team || '') + agePart;
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
      var _bc = Utils.getPitchColor(e.pt);
      badge.style.backgroundColor = _bc;
      badge.style.color = Utils.badgeTextColor(_bc);
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
    var alwaysColorKeys = isPitcher ? { ffVelo: true, siVelo: true } : { maxEV: true };

    // Build dynamic velo rows for pitchers from pitch data
    var dynamicVeloStats = [];
    if (isPitcher) {
      var pitchRows = this._filteredPitchRows || this._getPitchRows(data.pitcher, data.team);
      var veloFormat = function(v) { return v != null ? v.toFixed(1) + ' mph' : '—'; };
      for (var vi = 0; vi < pitchRows.length; vi++) {
        var pr = pitchRows[vi];
        if (pr.pitchType === 'FF') {
          dynamicVeloStats.push({ key: 'ffVelo', label: 'Fastball Velo', format: veloFormat,
            _val: pr.velocity, _pctl: pr.velocity_pctl });
        }
        if (pr.pitchType === 'SI') {
          dynamicVeloStats.push({ key: 'siVelo', label: 'Sinker Velo', format: veloFormat,
            _val: pr.velocity, _pctl: pr.velocity_pctl });
        }
      }
      // Sort: FF/CF first, then SI
      dynamicVeloStats.sort(function(a, b) { return a.key === 'ffVelo' ? -1 : 1; });
    }

    // BIP-dependent stats that show gray when bipQual is false
    var HITTER_BIP_STATS = {
      avgEVAll: true, medEV: true, ev75: true, maxEV: true,
      hardHitPct: true, barrelPct: true, laSweetSpotPct: true, sacqPct: true,
      xBA: true, xSLG: true, xwOBA: true, xwOBAcon: true, xwOBAsp: true, xWRCplus: true,
      babip: true, hrFbPct: true, airPullPct: true
    };
    var PITCHER_BIP_STATS = {
      barrelPctAgainst: true, gbPct: true,
      xBA: true, xSLG: true, xwOBA: true, xwOBAcon: true
    };

    // Build effective stats list, replacing _veloPlaceholder with dynamic velo rows
    var effectiveStats = [];
    for (var si2 = 0; si2 < statsDef.length; si2++) {
      if (statsDef[si2]._dynamic) {
        for (var dv = 0; dv < dynamicVeloStats.length; dv++) {
          effectiveStats.push(dynamicVeloStats[dv]);
        }
      } else {
        effectiveStats.push(statsDef[si2]);
      }
    }

    for (var i = 0; i < effectiveStats.length; i++) {
      var stat = effectiveStats[i];
      var val = stat._val !== undefined ? stat._val : data[stat.key];
      var pctl = stat._pctl !== undefined ? stat._pctl : data[stat.key + '_pctl'];
      // BIP qualification: <20 BIP → show gray outline
      var bipStats = isPitcher ? PITCHER_BIP_STATS : HITTER_BIP_STATS;
      var bipUnqual = bipStats[stat.key] && data.bipQual === false;
      // Sprint speed: has its own qualification (10 competitive runs from Savant)
      var sprintUnqual = stat.sprintQual && val == null;
      // noPercentile stats: show gray-hatched bar with value, no colored bar or circle
      var noPercentile = stat.noPercentile === true;
      var showColor = (isQualified || alwaysColorKeys[stat.key]) && !bipUnqual && !sprintUnqual && !noPercentile;

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

      if (pctl != null && !noPercentile) {
        var circle = document.createElement('div');
        circle.className = 'pctl-circle';
        if (showColor) {
          var bgColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
          var textColor = isDark ? '#fff' : Utils.percentileTextColor(pctl);
          circle.style.backgroundColor = bgColor;
          circle.style.color = textColor;
          var qualPool = isPitcher ? 'qualified pitchers' : 'qualified hitters';
          circle.title = Utils.ordinal(Math.round(pctl)) + ' percentile among ' + qualPool;
        } else {
          // Unqualified: outline ring instead of filled circle
          circle.style.backgroundColor = 'transparent';
          circle.style.border = isDark ? '2px solid rgba(160,160,160,0.5)' : '2px solid #bbb';
          circle.style.color = isDark ? 'rgba(160,160,160,0.7)' : '#999';
          circle.title = 'Below minimum qualification threshold';
        }
        circle.textContent = Math.round(pctl);
        circleWrap.appendChild(circle);
      }

      // Bar
      var barTrack = document.createElement('div');
      barTrack.className = 'pctl-bar-track';
      var barFill = document.createElement('div');
      barFill.className = 'pctl-bar-fill';
      if (pctl != null || sprintUnqual || noPercentile) {
        barFill.style.width = pctl != null ? Math.round(pctl) + '%' : '100%';
        if (showColor) {
          var barColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
          barFill.style.backgroundColor = barColor;
        } else {
          // Unqualified / no percentile: gray bar with white diagonal hatching
          var barBg = isDark ? 'rgba(140,140,140,0.25)' : 'rgba(180,180,180,0.5)';
          var stripColor = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.5)';
          barFill.style.background = barBg + ' repeating-linear-gradient(135deg, ' + stripColor + ', ' + stripColor + ' 2px, transparent 2px, transparent 6px)';
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
    sectionLabel.textContent = 'Pitch Run Value / 100';
    container.appendChild(sectionLabel);

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
          circle.style.backgroundColor = 'transparent';
          circle.style.border = isDark ? '2px solid rgba(160,160,160,0.5)' : '2px solid #bbb';
          circle.style.color = isDark ? 'rgba(160,160,160,0.7)' : '#999';
          circle.title = 'Below minimum qualification threshold';
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
          var barBg = isDark ? 'rgba(140,140,140,0.25)' : 'rgba(180,180,180,0.5)';
          var stripColor = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.5)';
          barFill.style.background = barBg + ' repeating-linear-gradient(135deg, ' + stripColor + ', ' + stripColor + ' 2px, transparent 2px, transparent 6px)';
        }
      }
      barTrack.appendChild(barFill);

      row.appendChild(labelEl);
      row.appendChild(barTrack);
      row.appendChild(circleWrap);
      row.appendChild(valEl);
      return row;
    }

    // Overall row (RV/100 — positive = good for pitcher)
    var overallRV100 = data.rv100;
    container.appendChild(buildPctlRow('Overall', overallRV100, data.rv100_pctl, null));

    // Per-pitch-type rows (fixed order)
    var PITCH_ORDER = ['FF','SI','FC','SL','ST','CU','SV','CH','FS','KN'];
    var sortedPitchRows = pitchRows.slice().sort(function(a, b) {
      var ai = PITCH_ORDER.indexOf(a.pitchType);
      var bi = PITCH_ORDER.indexOf(b.pitchType);
      if (ai === -1) ai = 999;
      if (bi === -1) bi = 999;
      return ai - bi;
    });
    for (var i = 0; i < sortedPitchRows.length; i++) {
      var pitch = sortedPitchRows[i];
      var displayVal = pitch.rv100;
      var pctl = pitch.rv100_pctl;

      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      var _bc = Utils.getPitchColor(pitch.pitchType);
      badge.style.backgroundColor = _bc;
      badge.style.color = Utils.badgeTextColor(_bc);
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
    barWrap.className = 'pctl-bar-track';
    barWrap.style.position = 'relative';
    // Center marker
    var centerLine = document.createElement('div');
    centerLine.style.cssText = 'position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(255,255,255,0.3);z-index:1;';
    barWrap.appendChild(centerLine);
    // Fill bar
    if (rv != null && rv !== 0) {
      var bar = document.createElement('div');
      bar.style.position = 'absolute';
      bar.style.top = '0';
      bar.style.bottom = '0';
      bar.style.borderRadius = '3px';
      var pct = Math.min(Math.abs(rv) / 15, 1) * 50;
      if (rv > 0) {
        bar.style.left = '50%';
        bar.style.width = pct + '%';
        bar.style.backgroundColor = 'rgba(0, 180, 100, 0.6)';
      } else {
        bar.style.left = (50 - pct) + '%';
        bar.style.width = pct + '%';
        bar.style.backgroundColor = 'rgba(220, 60, 60, 0.6)';
      }
      barWrap.appendChild(bar);
    }
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

    // Compute and display average arm angle
    var aaLabel = document.getElementById('player-arm-angle');
    if (aaLabel) {
      var aaVals = [];
      for (var ai = 0; ai < filteredPitches.length; ai++) {
        if (filteredPitches[ai].aa != null) aaVals.push(filteredPitches[ai].aa);
      }
      if (aaVals.length > 0) {
        var avgAA = (aaVals.reduce(function(a,b){return a+b;},0) / aaVals.length).toFixed(1);
        aaLabel.textContent = 'Arm Angle = ' + avgAA + '\u00B0';
        aaLabel.style.display = '';
      } else {
        aaLabel.style.display = 'none';
      }
    }
    var groups = {};
    for (var fi = 0; fi < filteredPitches.length; fi++) {
      var fp = filteredPitches[fi];
      if (fp.ivb == null || fp.hb == null) continue;
      if (!groups[fp.pt]) groups[fp.pt] = [];
      groups[fp.pt].push({ x: fp.hb, y: fp.ivb });
    }
    if (Object.keys(groups).length === 0) return;

    // Build expected movement from per-pitch xivb/xhb (dynamic by arm angle)
    var expectedMovement = {};
    var xAccum = {};  // { pitchType: { sumIVB, sumHB, n } }
    for (var xi = 0; xi < filteredPitches.length; xi++) {
      var xp = filteredPitches[xi];
      if (xp.xivb != null && xp.xhb != null) {
        if (!xAccum[xp.pt]) xAccum[xp.pt] = { sumIVB: 0, sumHB: 0, n: 0 };
        xAccum[xp.pt].sumIVB += xp.xivb;
        xAccum[xp.pt].sumHB += xp.xhb;
        xAccum[xp.pt].n++;
      }
    }
    for (var xpt in xAccum) {
      var xa = xAccum[xpt];
      expectedMovement[xpt] = { xHB: xa.sumHB / xa.n, xIVB: xa.sumIVB / xa.n };
    }

    var datasets = [];
    var expectedMeta = [];
    var PITCH_ORDER = ['FF','SI','FC','SL','ST','CU','SV','CH','FS','KN','SC','CS'];
    var pitchTypes = Object.keys(groups).sort(function(a, b) {
      var ai = PITCH_ORDER.indexOf(a); if (ai === -1) ai = 999;
      var bi = PITCH_ORDER.indexOf(b); if (bi === -1) bi = 999;
      return ai - bi;
    });

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

      // Expected movement ellipse (from xIVB/xHB regressions)
      if (expectedMovement[pt]) {
        expectedMeta.push({
          color: color.border,
          cx: expectedMovement[pt].xHB,
          cy: expectedMovement[pt].xIVB,
          label: pt,
          xIVB: expectedMovement[pt].xIVB,
          xHB: expectedMovement[pt].xHB,
        });
      }
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
        maintainAspectRatio: false,
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

          // Expected movement zones (hatched ellipses at xIVB/xHB, drawn first)
          var expRadiusX = Math.abs(xAxis.getPixelForValue(3.5) - xAxis.getPixelForValue(0));
          var expRadiusY = Math.abs(yAxis.getPixelForValue(0) - yAxis.getPixelForValue(3.5));
          for (var ei = 0; ei < expectedMeta.length; ei++) {
            var exp = expectedMeta[ei];
            var expCx = xAxis.getPixelForValue(exp.cx);
            var expCy = yAxis.getPixelForValue(exp.cy);

            // Create diagonal hatch pattern for this color
            var patCanvas = document.createElement('canvas');
            patCanvas.width = 8;
            patCanvas.height = 8;
            var patCtx = patCanvas.getContext('2d');
            patCtx.strokeStyle = exp.color;
            patCtx.lineWidth = 1.5;
            patCtx.globalAlpha = 0.4;
            patCtx.beginPath();
            patCtx.moveTo(0, 8);
            patCtx.lineTo(8, 0);
            patCtx.moveTo(-2, 2);
            patCtx.lineTo(2, -2);
            patCtx.moveTo(6, 10);
            patCtx.lineTo(10, 6);
            patCtx.stroke();
            var hatchPattern = ctx.createPattern(patCanvas, 'repeat');

            ctx.save();
            // Hatched fill
            ctx.fillStyle = hatchPattern;
            ctx.beginPath();
            ctx.ellipse(expCx, expCy, expRadiusX, expRadiusY, 0, 0, Math.PI * 2);
            ctx.fill();
            // Solid border
            ctx.strokeStyle = exp.color;
            ctx.globalAlpha = 0.4;
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.restore();
          }

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

          // Annotation: "Shaded = expected movement"
          if (expectedMeta.length > 0) {
            ctx.save();
            ctx.font = '10px Barlow, sans-serif';
            ctx.fillStyle = crossColor;
            ctx.textAlign = 'left';
            ctx.fillText('Shaded = expected movement', xAxis.left + 6, yAxis.bottom - 6);
            ctx.restore();
          }

          // Store pixel positions for ellipse hover detection
          chart._ellipseHitAreas = [];
          for (var hi = 0; hi < expectedMeta.length; hi++) {
            var he = expectedMeta[hi];
            chart._ellipseHitAreas.push({
              px: xAxis.getPixelForValue(he.cx),
              py: yAxis.getPixelForValue(he.cy),
              rx: expRadiusX,
              ry: expRadiusY,
              label: he.label,
              xIVB: he.xIVB,
              xHB: he.xHB,
              color: he.color,
            });
          }
        },
      }],
    });

    // Ellipse hover tooltip
    var ellipseTooltip = document.getElementById('ellipse-tooltip');
    if (!ellipseTooltip) {
      ellipseTooltip = document.createElement('div');
      ellipseTooltip.id = 'ellipse-tooltip';
      ellipseTooltip.style.cssText = 'position:absolute;pointer-events:none;display:none;padding:6px 10px;border-radius:4px;font:12px Barlow,sans-serif;z-index:1000;white-space:nowrap;';
      document.body.appendChild(ellipseTooltip);
    }
    var chartRef = this.chart;
    canvas.addEventListener('mousemove', function (e) {
      var rect = canvas.getBoundingClientRect();
      var mx = e.clientX - rect.left;
      var my = e.clientY - rect.top;
      var areas = chartRef._ellipseHitAreas;
      if (!areas) return;
      var hit = null;
      for (var ai = 0; ai < areas.length; ai++) {
        var a = areas[ai];
        var dx = (mx - a.px) / a.rx;
        var dy = (my - a.py) / a.ry;
        if (dx * dx + dy * dy <= 1) {
          hit = a;
          break;
        }
      }
      // Hide ellipse tooltip if hovering over an actual data point
      var nearPoint = chartRef.getElementsAtEventForMode(e, 'nearest', { intersect: true }, false);
      if (hit && nearPoint.length === 0) {
        var isDk = document.body.classList.contains('dark');
        ellipseTooltip.style.background = isDk ? 'rgba(30,33,40,0.95)' : 'rgba(255,255,255,0.95)';
        ellipseTooltip.style.color = isDk ? '#eee' : '#333';
        ellipseTooltip.style.border = '1px solid ' + hit.color;
        ellipseTooltip.innerHTML = '<b>' + hit.label + ' Expected</b><br>xIVB: ' + hit.xIVB.toFixed(1) + '"<br>xHB: ' + hit.xHB.toFixed(1) + '"';
        ellipseTooltip.style.display = 'block';
        ellipseTooltip.style.left = (e.pageX + 12) + 'px';
        ellipseTooltip.style.top = (e.pageY - 10) + 'px';
        canvas.style.cursor = 'pointer';
      } else {
        ellipseTooltip.style.display = 'none';
        canvas.style.cursor = '';
      }
    });
    canvas.addEventListener('mouseleave', function () {
      ellipseTooltip.style.display = 'none';
      canvas.style.cursor = '';
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
      if (!byType[p.pt]) byType[p.pt] = { count: 0, velos: [], spins: [], ivbs: [], hbs: [], tiltSins: [], tiltCoss: [], armAngles: [] };
      var g = byType[p.pt];
      g.count++;
      if (p.v != null) g.velos.push(p.v);
      if (p.sp != null) g.spins.push(p.sp);
      if (p.ivb != null) g.ivbs.push(p.ivb);
      if (p.hb != null) g.hbs.push(p.hb);
      if (p.aa != null) g.armAngles.push(p.aa);
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
        armAngle: avg(g.armAngles),
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
          var _bc = Utils.getPitchColor(row.pitchType);
          badge.style.backgroundColor = _bc;
          badge.style.color = Utils.badgeTextColor(_bc);
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

  /**
   * Create a small SVG sparkline from an array of {date, avgVelo} points.
   * Returns an SVG element (inline, ~120×28px).
   */
  _createVeloSparkline: function (points, color) {
    if (!points || points.length < 2) return null;
    var W = 160, H = 44, PAD_TOP = 4, PAD_BOT = 14, PAD_L = 4, PAD_R = 4;
    var plotW = W - PAD_L - PAD_R;
    var plotH = H - PAD_TOP - PAD_BOT;
    var velos = points.map(function(p) { return p.avgVelo; });
    var avgV = velos.reduce(function(a, b) { return a + b; }, 0) / velos.length;
    var dataMin = Math.min.apply(null, velos);
    var dataMax = Math.max.apply(null, velos);
    // Use at least ±3 mph from mean for consistent scale across pitch types
    var minV = Math.min(dataMin, avgV - 3);
    var maxV = Math.max(dataMax, avgV + 3);
    var range = maxV - minV || 1;

    var ns = 'http://www.w3.org/2000/svg';

    // Wrapper div for sparkline + tooltip
    var wrapper = document.createElement('div');
    wrapper.style.cssText = 'display:inline-block;position:relative;vertical-align:middle;';

    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('width', W);
    svg.setAttribute('height', H);
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.style.display = 'block';
    svg.style.cursor = 'crosshair';

    // Season average reference line (dashed)
    var avgY = PAD_TOP + (1 - (avgV - minV) / range) * plotH;
    var avgLine = document.createElementNS(ns, 'line');
    avgLine.setAttribute('x1', PAD_L);
    avgLine.setAttribute('y1', avgY.toFixed(1));
    avgLine.setAttribute('x2', PAD_L + plotW);
    avgLine.setAttribute('y2', avgY.toFixed(1));
    avgLine.setAttribute('stroke', '#555');
    avgLine.setAttribute('stroke-width', '0.75');
    avgLine.setAttribute('stroke-dasharray', '3,2');
    svg.appendChild(avgLine);

    // Build path and compute coordinates
    var coords = [];
    var pathParts = [];
    for (var i = 0; i < points.length; i++) {
      var x = PAD_L + (i / (points.length - 1)) * plotW;
      var y = PAD_TOP + (1 - (points[i].avgVelo - minV) / range) * plotH;
      coords.push({ x: x, y: y });
      pathParts.push((i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1));
    }

    var path = document.createElementNS(ns, 'path');
    path.setAttribute('d', pathParts.join(' '));
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', color || '#888');
    path.setAttribute('stroke-width', '1.5');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(path);

    // End dot
    var lastCoord = coords[coords.length - 1];
    var dot = document.createElementNS(ns, 'circle');
    dot.setAttribute('cx', lastCoord.x.toFixed(1));
    dot.setAttribute('cy', lastCoord.y.toFixed(1));
    dot.setAttribute('r', '2.5');
    dot.setAttribute('fill', color || '#888');
    svg.appendChild(dot);

    // Date axis labels (first and last date, formatted as M/D)
    var formatDate = function(d) {
      var parts = d.split('-');
      return parseInt(parts[1]) + '/' + parseInt(parts[2]);
    };
    var startLabel = document.createElementNS(ns, 'text');
    startLabel.setAttribute('x', PAD_L);
    startLabel.setAttribute('y', H - 1);
    startLabel.setAttribute('fill', '#666');
    startLabel.setAttribute('font-size', '9');
    startLabel.setAttribute('font-family', 'Barlow, sans-serif');
    startLabel.textContent = formatDate(points[0].date);
    svg.appendChild(startLabel);

    var endLabel = document.createElementNS(ns, 'text');
    endLabel.setAttribute('x', PAD_L + plotW);
    endLabel.setAttribute('y', H - 1);
    endLabel.setAttribute('text-anchor', 'end');
    endLabel.setAttribute('fill', '#666');
    endLabel.setAttribute('font-size', '9');
    endLabel.setAttribute('font-family', 'Barlow, sans-serif');
    endLabel.textContent = formatDate(points[points.length - 1].date);
    svg.appendChild(endLabel);

    // Invisible hover rects for each data point (tooltip targets)
    var tooltip = document.createElement('div');
    tooltip.style.cssText = 'position:absolute;display:none;background:#1e2127;border:1px solid #444;border-radius:4px;padding:3px 7px;font-size:11px;color:#ddd;white-space:nowrap;pointer-events:none;z-index:10;font-family:JetBrains Mono,monospace;';
    wrapper.appendChild(tooltip);

    var segW = plotW / (points.length - 1 || 1);
    for (var j = 0; j < points.length; j++) {
      (function(idx) {
        var hoverRect = document.createElementNS(ns, 'rect');
        var rx = coords[idx].x - segW / 2;
        hoverRect.setAttribute('x', Math.max(0, rx).toFixed(1));
        hoverRect.setAttribute('y', '0');
        hoverRect.setAttribute('width', segW.toFixed(1));
        hoverRect.setAttribute('height', H);
        hoverRect.setAttribute('fill', 'transparent');
        hoverRect.style.cursor = 'crosshair';

        // Visible hover dot
        var hDot = document.createElementNS(ns, 'circle');
        hDot.setAttribute('cx', coords[idx].x.toFixed(1));
        hDot.setAttribute('cy', coords[idx].y.toFixed(1));
        hDot.setAttribute('r', '3');
        hDot.setAttribute('fill', color || '#888');
        hDot.setAttribute('stroke', '#fff');
        hDot.setAttribute('stroke-width', '1');
        hDot.style.display = 'none';
        svg.appendChild(hDot);

        hoverRect.addEventListener('mouseenter', function() {
          hDot.style.display = '';
          tooltip.style.display = 'block';
          tooltip.textContent = formatDate(points[idx].date) + '  ' + points[idx].avgVelo.toFixed(1) + ' mph';
          // Position tooltip above the point
          var tipX = coords[idx].x - 30;
          if (tipX < 0) tipX = 0;
          if (tipX > W - 80) tipX = W - 80;
          tooltip.style.left = tipX + 'px';
          tooltip.style.top = (coords[idx].y - 22) + 'px';
        });
        hoverRect.addEventListener('mouseleave', function() {
          hDot.style.display = 'none';
          tooltip.style.display = 'none';
        });
        svg.appendChild(hoverRect);
      })(j);
    }

    // Overall tooltip on the SVG (range + avg)
    svg.setAttribute('title', 'Range: ' + minV.toFixed(1) + '–' + maxV.toFixed(1) + ' mph | Avg: ' + avgV.toFixed(1) + ' mph');

    wrapper.appendChild(svg);
    return wrapper;
  },

  _renderExpandedPitchTable: function (data) {
    var section = document.getElementById('player-expanded-pitch-section');
    var container = document.getElementById('player-expanded-pitch-table');
    container.innerHTML = '';

    var pitchRows = this._filteredPitchRows || this._getPitchRows(data.pitcher, data.team);
    if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }

    section.style.display = '';

    // Get velocity trend data for sparklines
    var veloTrend = Aggregator.loaded ? Aggregator.getVeloTrend(data.pitcher) : {};

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
    // Add Velo Trend column header
    var thVt = document.createElement('th');
    thVt.textContent = 'Velo Trend';
    thVt.style.minWidth = '130px';
    headerRow.appendChild(thVt);
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
          var _bc = Utils.getPitchColor(row.pitchType);
          badge.style.backgroundColor = _bc;
          badge.style.color = Utils.badgeTextColor(_bc);
          badge.textContent = row.pitchType;
          td.appendChild(badge);
        } else {
          var val = row[col.key];
          td.textContent = col.format ? col.format(val) : (val != null ? val : '—');
        }
        tr.appendChild(td);
      }
      // Add sparkline cell
      var tdVt = document.createElement('td');
      tdVt.style.textAlign = 'center';
      var trendData = veloTrend[row.pitchType];
      var sparkColor = Utils.getPitchColor(row.pitchType);
      var sparkline = this._createVeloSparkline(trendData, sparkColor);
      if (sparkline) {
        tdVt.appendChild(sparkline);
      } else {
        tdVt.textContent = '—';
      }
      tr.appendChild(tdVt);
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

    // Compute total row from filtered pitcher-level data (include _pctl keys)
    var totalRow = { pitchType: 'Total' };
    var fd = this._filteredData || data;
    for (var k = 0; k < this.BATTED_BALL_COLS.length; k++) {
      var key = this.BATTED_BALL_COLS[k].key;
      if (key !== 'pitchType') {
        totalRow[key] = fd[key];
        if (fd[key + '_pctl'] != null) totalRow[key + '_pctl'] = fd[key + '_pctl'];
      }
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

    // Compute total row from filtered pitcher-level data (include _pctl keys)
    var totalRow = { pitchType: 'Total' };
    var fd = this._filteredData || data;
    for (var k = 0; k < this.PLATE_DISCIPLINE_COLS.length; k++) {
      var key = this.PLATE_DISCIPLINE_COLS[k].key;
      if (key !== 'pitchType') {
        totalRow[key] = fd[key];
        if (fd[key + '_pctl'] != null) totalRow[key + '_pctl'] = fd[key + '_pctl'];
      }
    }

    this._renderPerPitchTable(container, this.PLATE_DISCIPLINE_COLS, pitchRows, totalRow);
  },

  // --- Shared: Render per-pitch-type table with total row ---

  _renderPerPitchTable: function (container, cols, pitchRows, totalRow) {
    var isDark = document.body.classList.contains('dark');
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
          var _bc = Utils.getPitchColor(row.pitchType);
          badge.style.backgroundColor = _bc;
          badge.style.color = Utils.badgeTextColor(_bc);
          badge.textContent = row.pitchType;
          td.appendChild(badge);
        } else {
          var val = row[col.key];
          td.textContent = col.format ? col.format(val) : (val != null ? val : '—');
          // Apply percentile coloring if a _pctl value exists for this key
          var pctl = col.noPctl ? null : row[col.key + '_pctl'];
          if (pctl != null && val != null) {
            var bgColor = isDark ? Utils.percentileColorDark(pctl) : Utils.percentileColor(pctl);
            var txtColor = isDark ? Utils.percentileTextColorDark(pctl) : Utils.percentileTextColor(pctl);
            td.style.backgroundColor = bgColor;
            td.style.color = txtColor;
            td.title = Math.round(pctl) + 'th percentile';
          }
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }

    // Total row
    if (totalRow) {
      var totalTr = document.createElement('tr');
      totalTr.style.fontWeight = '700';
      totalTr.style.borderTop = '2px solid #333840';
      for (var c2 = 0; c2 < cols.length; c2++) {
        var col2 = cols[c2];
        var td2 = document.createElement('td');
        if (col2.key === 'pitchType') {
          td2.textContent = 'Total';
        } else {
          var val2 = totalRow[col2.key];
          td2.textContent = col2.format ? col2.format(val2) : (val2 != null ? val2 : '—');
          // Apply percentile coloring to total row (league-wide percentiles)
          var pctl2 = col2.noPctl ? null : totalRow[col2.key + '_pctl'];
          if (pctl2 != null && val2 != null) {
            var bgColor2 = isDark ? Utils.percentileColorDark(pctl2) : Utils.percentileColor(pctl2);
            var txtColor2 = isDark ? Utils.percentileTextColorDark(pctl2) : Utils.percentileTextColor(pctl2);
            td2.style.backgroundColor = bgColor2;
            td2.style.color = txtColor2;
            td2.title = Math.round(pctl2) + 'th percentile';
          }
        }
        totalTr.appendChild(td2);
      }
      tbody.appendChild(totalTr);
    }

    table.appendChild(tbody);
    container.appendChild(table);

    // Horizontal scroll fade indicator
    container.style.position = 'relative';
    var fadeDiv = document.createElement('div');
    fadeDiv.style.cssText = 'position:absolute;right:0;top:0;bottom:0;width:24px;background:linear-gradient(to right, transparent, #1a1d21);pointer-events:none;z-index:1;opacity:0;transition:opacity 0.2s;';
    container.appendChild(fadeDiv);
    container.addEventListener('scroll', function() {
      var maxScroll = container.scrollWidth - container.clientWidth;
      fadeDiv.style.opacity = (container.scrollLeft >= maxScroll - 2) ? '0' : '1';
    });
    setTimeout(function() {
      if (container.scrollWidth > container.clientWidth) fadeDiv.style.opacity = '1';
    }, 100);
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
    var PITCH_ORDER = ['FF','SI','FC','SL','ST','CU','SV','CH','FS','KN'];
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
      var _bc = Utils.getPitchColor(pt);
      badge.style.backgroundColor = _bc;
      badge.style.color = Utils.badgeTextColor(_bc);
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

    // Legend removed — blue-to-red heat scale is intuitive
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
    // Blue (cold) → white (mid) → red (hot), like Baseball Savant
    // Uses HSL interpolation for perceptually uniform gradients
    var h, s, l;
    if (t < 0.5) {
      // Blue (h=220) → white: increase lightness, decrease saturation
      var p = t / 0.5;
      h = 220;
      s = Math.round(80 - p * 80);
      l = Math.round(35 + p * 65);
    } else {
      // White → red (h=5): increase saturation, decrease lightness
      var p = (t - 0.5) / 0.5;
      h = 5;
      s = Math.round(p * 85);
      l = Math.round(100 - p * 55);
    }
    return 'hsl(' + h + ',' + s + '%,' + l + '%)';
  },

  // --- Render: Zone Profile (5×5 grid per pitch type: chase zones + strike zone) ---

  _renderZoneProfiles: function(data) {
    var section = document.getElementById('player-zone-profile-section');
    var container = document.getElementById('player-zone-profiles');
    if (!section || !container) return;
    container.innerHTML = '';

    var pitches = this._getFilteredDetails(data);
    if (!pitches || pitches.length === 0) { section.style.display = 'none'; return; }

    section.style.display = '';
    var hand = this._zoneHand || 'R';
    var metric = this._zoneMetric || 'usage';

    // Compute average strike zone
    var szTopSum = 0, szBotSum = 0, szCount = 0;
    for (var i = 0; i < pitches.length; i++) {
      if (pitches[i].szt != null && pitches[i].szb != null) {
        szTopSum += pitches[i].szt;
        szBotSum += pitches[i].szb;
        szCount++;
      }
    }
    var szTop = szCount > 0 ? szTopSum / szCount : 3.5;
    var szBot = szCount > 0 ? szBotSum / szCount : 1.5;
    var szHeight = szTop - szBot;
    var szThird = szHeight / 3;

    // 5×5 grid: inner 3×3 = strike zone, outer ring = chase/waste zones
    // Horizontal: plate half-width = 0.83 ft, chase zone extends another ~0.55 ft (one plate-third)
    var PX_EDGE = 0.83;
    var PX_CHASE = 1.38;  // chase zone outer edge (~16.5 inches from center)
    var pxThird = PX_EDGE * 2 / 3;

    // Vertical chase zone extends one szThird above/below strike zone
    var pzChaseTop = szTop + szThird;
    var pzChaseBot = szBot - szThird;

    // Group by pitch type, filter by hand
    var byType = {};
    var totalByType = {};
    for (var i = 0; i < pitches.length; i++) {
      var p = pitches[i];
      if (p.bh !== hand) continue;
      var pt = p.pt;
      if (!pt) continue;
      if (!totalByType[pt]) totalByType[pt] = 0;
      totalByType[pt]++;
      if (p.px == null || p.pz == null) continue;
      if (!byType[pt]) byType[pt] = [];
      byType[pt].push(p);
    }

    var ptOrder = Object.keys(totalByType).sort(function(a, b) { return totalByType[b] - totalByType[a]; });

    for (var ti = 0; ti < ptOrder.length; ti++) {
      var pt = ptOrder[ti];
      var ptPitches = byType[pt] || [];
      if (ptPitches.length < 5) continue;

      // 5×5 grid: [row][col], row 0=high chase, 1=high, 2=mid, 3=low, 4=low chase
      //            col 0=in chase, 1=in, 2=mid, 3=away, 4=away chase
      var zones = [];
      for (var r = 0; r < 5; r++) {
        zones[r] = [];
        for (var c = 0; c < 5; c++) {
          zones[r][c] = { n: 0, swings: 0, whiffs: 0, csw: 0 };
        }
      }

      for (var pi = 0; pi < ptPitches.length; pi++) {
        var pp = ptPitches[pi];
        var px = pp.px;
        var pz = pp.pz;

        // Determine column (0=chase-in, 1=in, 2=mid, 3=away, 4=chase-away)
        var col;
        if (px < -PX_EDGE) col = 0;
        else if (px < -PX_EDGE + pxThird) col = 1;
        else if (px < PX_EDGE - pxThird) col = 2;
        else if (px <= PX_EDGE) col = 3;
        else col = 4;

        // Determine row (0=chase-high, 1=high, 2=mid, 3=low, 4=chase-low)
        var row;
        if (pz > szTop) row = 0;
        else if (pz > szTop - szThird) row = 1;
        else if (pz > szBot + szThird) row = 2;
        else if (pz >= szBot) row = 3;
        else row = 4;

        // Clamp extreme outliers to chase zones
        if (row < 0) row = 0;
        if (row > 4) row = 4;
        if (col < 0) col = 0;
        if (col > 4) col = 4;

        var z = zones[row][col];
        z.n++;
        var desc = pp.d;
        if (desc === 'SS' || desc === 'F' || desc === 'IP') {
          z.swings++;
          if (desc === 'SS') z.whiffs++;
        }
        if (desc === 'CS' || desc === 'SS') {
          z.csw++;
        }
      }

      // Create zone grid SVG
      var wrapper = document.createElement('div');
      wrapper.className = 'zone-profile-card';
      var header = document.createElement('div');
      header.className = 'zone-profile-header';
      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      var bc = Utils.getPitchColor(pt);
      badge.style.backgroundColor = bc;
      badge.style.color = Utils.badgeTextColor(bc);
      badge.textContent = pt;
      header.appendChild(badge);
      var countSpan = document.createElement('span');
      countSpan.className = 'zone-profile-count';
      countSpan.textContent = ' ' + ptPitches.length;
      header.appendChild(countSpan);
      wrapper.appendChild(header);

      // SVG dimensions: inner cells = 32px, outer chase cells = 22px
      var INNER = 32, OUTER = 22, GAP = 1;
      var TOTAL_W = 2 * OUTER + 3 * INNER + 4 * GAP;
      var TOTAL_H = TOTAL_W;
      var SVG_PAD = 2;
      var ns = 'http://www.w3.org/2000/svg';
      var svg = document.createElementNS(ns, 'svg');
      svg.setAttribute('width', TOTAL_W + 2 * SVG_PAD);
      svg.setAttribute('height', TOTAL_H + 2 * SVG_PAD);
      svg.setAttribute('viewBox', '0 0 ' + (TOTAL_W + 2 * SVG_PAD) + ' ' + (TOTAL_H + 2 * SVG_PAD));

      // Compute cell positions
      var colWidths = [OUTER, INNER, INNER, INNER, OUTER];
      var rowHeights = [OUTER, INNER, INNER, INNER, OUTER];
      var colX = [SVG_PAD];
      for (var ci = 1; ci <= 4; ci++) colX[ci] = colX[ci - 1] + colWidths[ci - 1] + GAP;
      var rowY = [SVG_PAD];
      for (var ri = 1; ri <= 4; ri++) rowY[ri] = rowY[ri - 1] + rowHeights[ri - 1] + GAP;

      // Find max value for color scaling
      var maxVal = 0;
      for (var r = 0; r < 5; r++) {
        for (var c = 0; c < 5; c++) {
          var val;
          if (metric === 'usage') {
            val = zones[r][c].n / ptPitches.length;
          } else if (metric === 'whiff') {
            val = zones[r][c].swings > 0 ? zones[r][c].whiffs / zones[r][c].swings : 0;
          } else {
            val = zones[r][c].n > 0 ? zones[r][c].csw / zones[r][c].n : 0;
          }
          if (val > maxVal) maxVal = val;
        }
      }

      for (var r = 0; r < 5; r++) {
        for (var c = 0; c < 5; c++) {
          var z = zones[r][c];
          var isChase = r === 0 || r === 4 || c === 0 || c === 4;
          var val, displayVal;
          if (metric === 'usage') {
            val = z.n / ptPitches.length;
            displayVal = (val * 100).toFixed(0) + '%';
          } else if (metric === 'whiff') {
            val = z.swings > 0 ? z.whiffs / z.swings : 0;
            displayVal = z.swings > 2 ? (val * 100).toFixed(0) + '%' : '—';
          } else {
            val = z.n > 0 ? z.csw / z.n : 0;
            displayVal = z.n > 2 ? (val * 100).toFixed(0) + '%' : '—';
          }

          var intensity = maxVal > 0 ? val / maxVal : 0;
          var fillColor;
          if (metric === 'usage') {
            // Dark-to-red intensity scale for usage (matches heat map palette)
            fillColor = this._heatColor(intensity);
          } else {
            // Blue-white-red diverging scale for rate metrics (whiff%, CSW%)
            fillColor = this._heatColor(intensity);
          }
          // Dim chase zones slightly
          if (isChase) {
            fillColor = fillColor.replace(/hsl\((\d+),\s*(\d+)%,\s*(\d+)%\)/, function(m, h, s, l) {
              return 'hsl(' + h + ',' + Math.round(s * 0.6) + '%,' + Math.round(l * 0.8) + '%)';
            });
          }

          var rect = document.createElementNS(ns, 'rect');
          rect.setAttribute('x', colX[c]);
          rect.setAttribute('y', rowY[r]);
          rect.setAttribute('width', colWidths[c]);
          rect.setAttribute('height', rowHeights[r]);
          rect.setAttribute('fill', fillColor);
          rect.setAttribute('rx', isChase ? '2' : '0');
          svg.appendChild(rect);

          // Show text only if cell is large enough and has data
          var cellW = colWidths[c];
          var cellH = rowHeights[r];
          if (z.n > 0 && (cellW >= 28 || !isChase)) {
            var text = document.createElementNS(ns, 'text');
            text.setAttribute('x', colX[c] + cellW / 2);
            text.setAttribute('y', rowY[r] + cellH / 2 + (isChase ? 3 : 4));
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('fill', intensity > 0.3 ? '#fff' : '#aaa');
            text.setAttribute('font-size', isChase ? '9' : '11');
            text.setAttribute('font-family', 'Barlow, sans-serif');
            text.textContent = displayVal;
            svg.appendChild(text);
          }
        }
      }

      // Strike zone border (around inner 3×3)
      var szX = colX[1];
      var szY = rowY[1];
      var szW = colX[3] + colWidths[3] - colX[1];
      var szH = rowY[3] + rowHeights[3] - rowY[1];
      var szRect = document.createElementNS(ns, 'rect');
      szRect.setAttribute('x', szX);
      szRect.setAttribute('y', szY);
      szRect.setAttribute('width', szW);
      szRect.setAttribute('height', szH);
      szRect.setAttribute('fill', 'none');
      szRect.setAttribute('stroke', '#888');
      szRect.setAttribute('stroke-width', '1.5');
      svg.appendChild(szRect);

      wrapper.appendChild(svg);
      container.appendChild(wrapper);
    }

    // Add zone labels
    if (ptOrder.length > 0) {
      var labelDiv = document.createElement('div');
      labelDiv.className = 'zone-profile-labels';
      labelDiv.innerHTML = '<span class="zone-label-row zone-label-chase">Chase</span><span class="zone-label-row">High</span><span class="zone-label-row">Mid</span><span class="zone-label-row">Low</span><span class="zone-label-row zone-label-chase">Chase</span>';
      container.insertBefore(labelDiv, container.firstChild);
    }
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

    // Compute overall total pitches for usage% column
    var overallTotal = 0;
    for (var t = 0; t < types.length; t++) overallTotal += pitchTypes[types[t]].total;

    // Build HTML table
    var table = document.createElement('table');
    table.className = 'count-table';

    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    var th0 = document.createElement('th');
    th0.textContent = 'Pitch';
    headRow.appendChild(th0);
    var thUsage = document.createElement('th');
    thUsage.textContent = 'Usage%';
    headRow.appendChild(thUsage);
    for (var g = 0; g < groupNames.length; g++) {
      var th = document.createElement('th');
      th.textContent = groupNames[g];
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    var isDark = document.body.classList.contains('dark');
    var tbody = document.createElement('tbody');
    for (var t = 0; t < types.length; t++) {
      var pt = types[t];
      var tr = document.createElement('tr');

      var tdLabel = document.createElement('td');
      tdLabel.style.textAlign = 'center';
      var badge = document.createElement('span');
      badge.className = 'pitch-badge-sm';
      var _bc = Utils.getPitchColor(pt);
      badge.style.backgroundColor = _bc;
      badge.style.color = Utils.badgeTextColor(_bc);
      badge.textContent = pt;
      tdLabel.appendChild(badge);
      tr.appendChild(tdLabel);

      // Baseline usage for this pitch type
      var baselinePct = overallTotal > 0 ? (pitchTypes[pt].total / overallTotal * 100) : 0;

      // Overall usage% column (no coloring — this is the reference)
      var tdUsage = document.createElement('td');
      if (overallTotal > 0) {
        tdUsage.textContent = baselinePct.toFixed(1) + '%';
      } else {
        tdUsage.textContent = '—';
      }
      tdUsage.style.fontWeight = '600';
      tr.appendChild(tdUsage);

      for (var g = 0; g < groupNames.length; g++) {
        var gn = groupNames[g];
        var td = document.createElement('td');
        var total = groupTotals[gn];
        if (total > 0) {
          var pct = (pitchTypes[pt][gn] / total * 100);
          td.textContent = pct.toFixed(1) + '%';
          // Color based on deviation from pitcher's own baseline usage
          if (baselinePct > 0) {
            var ratio = pct / baselinePct;
            // Map ratio to 0-100 scale: 0x=0, 1x=50, 2x=100
            var devPctl = Math.max(0, Math.min(100, 50 + (ratio - 1) * 50));
            var bgColor = isDark ? Utils.percentileColorDark(devPctl) : Utils.percentileColor(devPctl);
            var txtColor = isDark ? Utils.percentileTextColorDark(devPctl) : Utils.percentileTextColor(devPctl);
            td.style.backgroundColor = bgColor;
            td.style.color = txtColor;
          }
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

    // Zone profile hand toggle
    this._zoneHandToggleHandler = function(e) {
      var btn = e.target.closest('.hand-toggle-btn');
      if (!btn) return;
      var hand = btn.getAttribute('data-hand');
      if (hand === self._zoneHand) return;
      self._zoneHand = hand;
      var btns = document.querySelectorAll('#zone-hand-toggle .hand-toggle-btn');
      for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
      btn.classList.add('active');
      if (self._currentData) self._renderZoneProfiles(self._currentData);
    };
    var zoneHandToggle = document.getElementById('zone-hand-toggle');
    if (zoneHandToggle) zoneHandToggle.addEventListener('click', this._zoneHandToggleHandler);

    // Zone profile metric toggle
    this._zoneMetricToggleHandler = function(e) {
      var btn = e.target.closest('.hand-toggle-btn');
      if (!btn) return;
      var metric = btn.getAttribute('data-metric');
      if (metric === self._zoneMetric) return;
      self._zoneMetric = metric;
      var btns = document.querySelectorAll('#zone-metric-toggle .hand-toggle-btn');
      for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
      btn.classList.add('active');
      if (self._currentData) self._renderZoneProfiles(self._currentData);
    };
    var zoneMetricToggle = document.getElementById('zone-metric-toggle');
    if (zoneMetricToggle) zoneMetricToggle.addEventListener('click', this._zoneMetricToggleHandler);
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
    if (this._zoneHandToggleHandler) {
      var el = document.getElementById('zone-hand-toggle');
      if (el) el.removeEventListener('click', this._zoneHandToggleHandler);
      this._zoneHandToggleHandler = null;
    }
    if (this._zoneMetricToggleHandler) {
      var el = document.getElementById('zone-metric-toggle');
      if (el) el.removeEventListener('click', this._zoneMetricToggleHandler);
      this._zoneMetricToggleHandler = null;
    }
  },

  // --- Platoon Split Toggle (vs L / vs R / All for stats tables) ---

  _bindPlatoonToggle: function(type) {
    var self = this;
    var mainToggleId = type === 'pitcher' ? 'pitcher-platoon-toggle' : 'hitter-platoon-toggle';
    // All synced toggle IDs for pitchers
    var syncedIds = type === 'pitcher'
      ? ['pitcher-platoon-toggle', 'pitcher-platedisc-toggle', 'pitcher-battedball-toggle']
      : ['hitter-platoon-toggle'];

    this._platoonSyncedIds = syncedIds;

    this._platoonToggleHandler = function(e) {
      var btn = e.target.closest('.hand-toggle-btn');
      if (!btn) return;
      var hand = btn.getAttribute('data-hand');
      if (hand === self._platoonHand) return;
      self._platoonHand = hand;
      // Sync all toggles
      for (var si = 0; si < syncedIds.length; si++) {
        var btns = document.querySelectorAll('#' + syncedIds[si] + ' .hand-toggle-btn');
        for (var i = 0; i < btns.length; i++) {
          btns[i].classList.toggle('active', btns[i].getAttribute('data-hand') === hand);
        }
      }
      self._refreshPlatoonStats(type);
    };

    for (var ti = 0; ti < syncedIds.length; ti++) {
      var toggle = document.getElementById(syncedIds[ti]);
      if (toggle) toggle.addEventListener('click', this._platoonToggleHandler);
    }
  },

  _resetPlatoonToggleUI: function(toggleId) {
    // Reset all synced toggles
    var syncedIds = this._platoonSyncedIds || [toggleId];
    for (var si = 0; si < syncedIds.length; si++) {
      var btns = document.querySelectorAll('#' + syncedIds[si] + ' .hand-toggle-btn');
      for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('active', btns[i].getAttribute('data-hand') === 'all');
      }
    }
  },

  _unbindPlatoonToggle: function() {
    if (this._platoonToggleHandler) {
      var syncedIds = this._platoonSyncedIds || ['pitcher-platoon-toggle', 'hitter-platoon-toggle'];
      for (var si = 0; si < syncedIds.length; si++) {
        var el = document.getElementById(syncedIds[si]);
        if (el) el.removeEventListener('click', this._platoonToggleHandler);
      }
      this._platoonToggleHandler = null;
      this._platoonSyncedIds = null;
    }
  },

  _refreshPlatoonStats: function(type) {
    var data = this._currentData;
    if (!data) return;

    var hand = this._platoonHand;
    var rocTeams = (DataStore.metadata && DataStore.metadata.rocTeams) || [];
    var isROC = rocTeams.indexOf(data.team) !== -1;

    if (hand === 'all') {
      // Use pre-computed data (no aggregation needed)
      if (type === 'pitcher') {
        var filteredData = this._getFilteredPlayerData(data, true) || data;
        var filteredPitchRows = this._getFilteredPitchRows(data);
        this._filteredData = filteredData;
        this._filteredPitchRows = filteredPitchRows;
        this._renderStatsTable(filteredData);
        this._renderExpandedPitchTable(data);
        this._renderBattedBallTable(data);
        this._renderPlateDisciplineTable(data);
        this._renderHeatMaps(data);
        this._renderZoneProfiles(data);
        this._renderCountTable(data);
      } else {
        this._renderHitterStatsFullTable(data, isROC);
        this._renderHitterBattedBallTable(data, isROC);
        this._renderHitterPlateDisciplineTable(data);
        if (!isROC) this._renderHitterBatTrackingTable(data);
      }
      return;
    }

    // Re-aggregate with hand filter
    if (!Aggregator.loaded) return;

    var baseFilters = { vsHand: hand, team: 'all', throws: 'all', search: '', role: 'all' };
    var noDataMsg = '<p style="color:var(--text-secondary);padding:12px;text-align:center;font-size:13px;">No data vs ' +
      (type === 'pitcher' ? (hand === 'L' ? 'LHH' : 'RHH') : (hand === 'L' ? 'LHP' : 'RHP')) + '</p>';

    if (type === 'pitcher') {
      // Re-aggregate pitcher-level stats
      var rows = Aggregator.aggregate('pitcher', baseFilters);
      var found = null;
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].pitcher === data.pitcher && rows[i].team === data.team) {
          found = rows[i];
          break;
        }
      }
      if (!found) {
        var container = document.getElementById('player-stats-table');
        if (container) container.innerHTML = noDataMsg;
        return;
      }
      this._filteredData = found;
      this._renderStatsTable(found);

      // Re-aggregate pitch-type rows with hand filter
      var pitchRows = Aggregator.aggregate('pitch', baseFilters);
      var myPitchRows = [];
      for (var i = 0; i < pitchRows.length; i++) {
        if (pitchRows[i].pitcher === data.pitcher && pitchRows[i].team === data.team) {
          myPitchRows.push(pitchRows[i]);
        }
      }
      myPitchRows.sort(function(a, b) { return (b.usagePct || 0) - (a.usagePct || 0); });
      this._filteredPitchRows = myPitchRows;
      this._renderExpandedPitchTable(data);
      this._renderBattedBallTable(data);
      this._renderPlateDisciplineTable(data);

      // Heat maps, zone profiles, count table use PITCH_DETAILS — filter by batter hand
      this._platoonDetailHand = hand;
      this._renderHeatMaps(data);
      this._renderZoneProfiles(data);
      this._renderCountTable(data);
      this._platoonDetailHand = null;

    } else {
      // Re-aggregate hitter-level stats
      var rows = Aggregator.aggregate('hitter', baseFilters);
      var found = null;
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].hitter === data.hitter && rows[i].team === data.team) {
          found = rows[i];
          break;
        }
      }
      if (!found) {
        var container = document.getElementById('player-hitter-stats-table');
        if (container) container.innerHTML = noDataMsg;
        return;
      }
      this._renderHitterStatsFullTable(found, isROC);

      // Re-aggregate hitter pitch-type rows with hand filter
      var hpRows = Aggregator.aggregate('hitterPitch', baseFilters);
      var myHPRows = [];
      for (var i = 0; i < hpRows.length; i++) {
        if (hpRows[i].hitter === data.hitter && hpRows[i].team === data.team) {
          myHPRows.push(hpRows[i]);
        }
      }
      this._filteredHitterPitchRows = myHPRows;
      this._renderHitterBattedBallTable(found, isROC);
      this._renderHitterPlateDisciplineTable(found);
      if (!isROC) this._renderHitterBatTrackingTable(found);
      this._filteredHitterPitchRows = null;
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

    // Scale: feet to canvas pixels (CF fence at 401ft = maxRadius)
    var fenceScale = maxRadius / 401;

    // Draw infield dirt — 94.5ft radius circle centered on pitcher's mound (60.5ft from home)
    // This gives a dirt boundary 155ft from home toward CF
    var moundDist = 60.5 * fenceScale; // mound distance from home in pixels
    var moundX = canvasHPX;
    var moundY = canvasHPY - moundDist; // mound is straight up from home
    var dirtRadius = 94.5 * fenceScale;
    ctx.save();
    // Clip to foul line wedge so dirt doesn't extend outside fair territory
    ctx.beginPath();
    ctx.moveTo(canvasHPX, canvasHPY);
    ctx.arc(canvasHPX, canvasHPY, maxRadius, foulAngleLeft, foulAngleRight);
    ctx.closePath();
    ctx.clip();
    // Draw dirt circle centered on mound
    ctx.fillStyle = isDark ? '#3a2e1e' : '#d4b896';
    ctx.beginPath();
    ctx.arc(moundX, moundY, dirtRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // Draw distance reference arcs (300, 350, 400 ft)
    var distArcs = [300, 350, 400];
    for (var ai = 0; ai < distArcs.length; ai++) {
      var arcR = distArcs[ai] * fenceScale;
      ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.15)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.arc(canvasHPX, canvasHPY, arcR, foulAngleLeft, foulAngleRight);
      ctx.stroke();
      ctx.setLineDash([]);
      // Label at top of arc
      var labelX = canvasHPX + arcR * Math.cos(-Math.PI / 2);
      var labelY = canvasHPY + arcR * Math.sin(-Math.PI / 2) - 3;
      ctx.fillStyle = isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.3)';
      ctx.font = '10px Barlow, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(distArcs[ai] + 'ft', labelX, labelY);
    }

    // Draw foul lines
    ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.8)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(canvasHPX, canvasHPY);
    ctx.lineTo(canvasHPX + maxRadius * 1.02 * Math.cos(foulAngleLeft), canvasHPY + maxRadius * 1.02 * Math.sin(foulAngleLeft));
    ctx.moveTo(canvasHPX, canvasHPY);
    ctx.lineTo(canvasHPX + maxRadius * 1.02 * Math.cos(foulAngleRight), canvasHPY + maxRadius * 1.02 * Math.sin(foulAngleRight));
    ctx.stroke();

    // Distance markers (300ft, 350ft, 400ft arcs)
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 0.5;
    ctx.fillStyle = 'rgba(255,255,255,0.15)';
    ctx.font = '9px Barlow';
    ctx.textAlign = 'center';
    var distMarks = [300, 350, 400];
    for (var di = 0; di < distMarks.length; di++) {
      var distR = distMarks[di] * fenceScale;
      ctx.beginPath();
      ctx.arc(canvasHPX, canvasHPY, distR, foulAngleLeft, foulAngleRight, false);
      ctx.stroke();
      ctx.fillText(distMarks[di] + "'", canvasHPX, canvasHPY - distR - 3);
    }

    // Draw infield diamond — 90ft between bases
    var baseDist = 90 * fenceScale;
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
    var distIdx = bipCols.indexOf('distance');
    var batSideIdx = bipCols.indexOf('batSide');

    var bips = microData.hitterBip;
    var activeSide = this._sprayBatSide; // 'L', 'R', 'both', or null
    var filteredBips = [];
    for (var bi = 0; bi < bips.length; bi++) {
      if (bips[bi][hiIdx] !== hitterIdx) continue;
      if (activeSide && activeSide !== 'both' && batSideIdx >= 0 && bips[bi][batSideIdx] !== activeSide) continue;
      filteredBips.push(bips[bi]);
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

      // Use angle from HC_X/HC_Y but distance from Distance field when available
      var pos;
      var dist = distIdx >= 0 ? bip[distIdx] : null;
      if (dist != null && dist > 0) {
        // Compute angle from HC_X/HC_Y relative to home plate
        var dx = hcX - HP_X;
        var dy = HP_Y - hcY; // invert: Statcast Y increases downward
        var angle = Math.atan2(dy, dx);
        // Convert distance (feet) to canvas radius
        var r = dist * fenceScale;
        pos = [canvasHPX + r * Math.cos(angle), canvasHPY - r * Math.sin(angle)];
      } else {
        pos = toCanvas(hcX, hcY);
      }
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

  _bindSprayBatSideToggle: function (data) {
    var self = this;
    var isSwitch = data.stands === 'S';
    // Show/hide bat side toggles
    var sprayBSToggle = document.getElementById('spray-bat-side-toggle');
    var laBSToggle = document.getElementById('la-spray-bat-side-toggle');
    if (sprayBSToggle) sprayBSToggle.style.display = isSwitch ? '' : 'none';
    if (laBSToggle) laBSToggle.style.display = isSwitch ? '' : 'none';
    if (!isSwitch) return;

    // Reset active buttons to match default (LHH)
    var allBSBtns = document.querySelectorAll('#spray-bat-side-toggle .spray-toggle-btn, #la-spray-bat-side-toggle .spray-toggle-btn');
    for (var i = 0; i < allBSBtns.length; i++) {
      allBSBtns[i].classList.toggle('active', allBSBtns[i].getAttribute('data-side') === 'L');
    }

    this._sprayBatSideHandler = function (e) {
      var btn = e.target.closest('.spray-toggle-btn');
      if (!btn) return;
      var side = btn.getAttribute('data-side');
      if (!side || side === self._sprayBatSide) return;
      self._sprayBatSide = side === 'both' ? 'both' : side;
      // Sync active state on both toggles
      var allBtns = document.querySelectorAll('#spray-bat-side-toggle .spray-toggle-btn, #la-spray-bat-side-toggle .spray-toggle-btn');
      for (var i = 0; i < allBtns.length; i++) {
        allBtns[i].classList.toggle('active', allBtns[i].getAttribute('data-side') === side);
      }
      if (self._currentData) {
        self._renderSprayChart(self._currentData);
        self._renderLASprayChart(self._currentData);
      }
    };
    if (sprayBSToggle) sprayBSToggle.addEventListener('click', this._sprayBatSideHandler);
    if (laBSToggle) laBSToggle.addEventListener('click', this._sprayBatSideHandler);
  },

  _unbindSprayToggle: function () {
    if (this._sprayToggleHandler) {
      var el = document.getElementById('spray-toggle');
      if (el) el.removeEventListener('click', this._sprayToggleHandler);
      this._sprayToggleHandler = null;
    }
    if (this._laSprayToggleHandler) {
      var el2 = document.getElementById('la-spray-toggle');
      if (el2) el2.removeEventListener('click', this._laSprayToggleHandler);
      this._laSprayToggleHandler = null;
    }
    if (this._sprayBatSideHandler) {
      var el3 = document.getElementById('spray-bat-side-toggle');
      if (el3) el3.removeEventListener('click', this._sprayBatSideHandler);
      var el4 = document.getElementById('la-spray-bat-side-toggle');
      if (el4) el4.removeEventListener('click', this._sprayBatSideHandler);
      this._sprayBatSideHandler = null;
    }
    if (this._laSprayZoneToggleHandler) {
      var el5 = document.getElementById('la-spray-zone-toggle');
      if (el5) el5.removeEventListener('click', this._laSprayZoneToggleHandler);
      this._laSprayZoneToggleHandler = null;
    }
    if (this._laSprayChart) {
      this._laSprayChart.destroy();
      this._laSprayChart = null;
    }
  },

  // --- Hitter: LA × Spray Scatter Plot ---

  _laSprayChart: null,
  _laSprayMode: 'outcome',
  _laSprayZoneMetric: 'xwobacon',

  _renderLASprayChart: function (data) {
    var canvas = document.getElementById('player-la-spray-chart');
    if (!canvas) return;

    var microData = window.MICRO_DATA;
    if (!microData || !microData.hitterBip || !microData.hitterBipCols) return;

    var activeSide = this._sprayBatSide; // 'L', 'R', 'both', or null (non-switch)
    // For pull/oppo labels: use the active side filter (or data.stands for non-switch)
    var bats = (activeSide && activeSide !== 'both') ? activeSide : (data.stands || 'R');
    var bipCols = microData.hitterBipCols;
    var hiIdx = bipCols.indexOf('hitterIdx');
    var laIdx = bipCols.indexOf('launchAngle');
    var hcXIdx = bipCols.indexOf('hcX');
    var hcYIdx = bipCols.indexOf('hcY');
    var evIdx = bipCols.indexOf('exitVelo');
    var bbTypeIdx = bipCols.indexOf('bbType');
    var eventIdx = bipCols.indexOf('event');
    var batSideIdx = bipCols.indexOf('batSide');

    // Find hitter index
    var lookups = microData.lookups;
    var playerIdx = -1;
    for (var i = 0; i < lookups.hitters.length; i++) {
      if (lookups.hitters[i] === data.hitter) { playerIdx = i; break; }
    }
    if (playerIdx === -1) return;

    // Collect BIP data points
    var points = [];
    var totalBip = 0;
    var bipData = microData.hitterBip;
    for (var bi = 0; bi < bipData.length; bi++) {
      var row = bipData[bi];
      if (row[hiIdx] !== playerIdx) continue;
      if (activeSide && activeSide !== 'both' && batSideIdx >= 0 && row[batSideIdx] !== activeSide) continue;
      totalBip++;
      var la = row[laIdx];
      var hcX = row[hcXIdx];
      var hcY = row[hcYIdx];
      if (la == null || hcX == null || hcY == null) continue;
      var sprayAngle = Aggregator.computeSprayAngle(hcX, hcY);
      if (sprayAngle == null) continue;
      // Clamp LA to chart bounds so extreme values appear at edges
      var clampedLA = Math.max(-20, Math.min(60, la));
      points.push({
        x: sprayAngle,
        y: clampedLA,
        realLA: la,
        ev: row[evIdx],
        bbType: row[bbTypeIdx],
        event: row[eventIdx],
        clamped: la !== clampedLA,
      });
    }

    // Show note if some BIP couldn't be plotted (e.g. missing hit coordinates)
    var bipNote = document.getElementById('la-spray-bip-note');
    if (bipNote) {
      if (points.length < totalBip) {
        bipNote.textContent = points.length + ' of ' + totalBip + ' BIP shown';
        bipNote.style.display = '';
      } else {
        bipNote.style.display = 'none';
      }
    }

    // Get SACQ zones for overlay
    var sacqZones = (window.METADATA && window.METADATA.sacqZones) || [];

    var self = this;
    var mode = this._laSprayMode;

    // Color functions
    var OUTCOME_COLORS = { 0: '#666', 1: '#ff8c00', 2: '#7b68ee', 3: '#20b2aa', 4: '#dc143c', 5: '#999' };
    var BBTYPE_COLORS = { 0: '#4e79a7', 1: '#59a14f', 2: '#f28e2b', 3: '#e15759' };

    function evColor(ev) {
      if (ev == null) return 'rgba(150,150,150,0.6)';
      var t = Math.max(0, Math.min(1, (ev - 70) / 45)); // 70–115 range
      var r, g, b;
      if (t < 0.5) {
        var s = t / 0.5;
        r = Math.round(8 + (255 - 8) * s);
        g = Math.round(48 + (255 - 48) * s);
        b = Math.round(107 + (255 - 107) * s);
      } else {
        var s2 = (t - 0.5) / 0.5;
        r = Math.round(255 + (215 - 255) * s2);
        g = Math.round(255 + (48 - 255) * s2);
        b = Math.round(255 + (39 - 255) * s2);
      }
      return 'rgba(' + r + ',' + g + ',' + b + ',0.75)';
    }

    function getPointColor(pt) {
      if (mode === 'ev') return evColor(pt.ev);
      if (mode === 'bbtype') return BBTYPE_COLORS[pt.bbType] || '#999';
      return OUTCOME_COLORS[pt.event] || '#666'; // outcome (default)
    }

    // EV-based dot sizing: 5px (weak) to 10px (barreled)
    function evRadius(ev) {
      if (ev == null) return 5;
      if (ev < 80) return 5;
      if (ev < 90) return 6;
      if (ev < 95) return 7;
      if (ev < 100) return 8;
      if (ev < 105) return 9;
      return 10;
    }

    // Build datasets
    var pointColors = points.map(function (p) { return getPointColor(p); });
    var pointRadii = points.map(function (p) { return evRadius(p.ev); });
    var pointHoverRadii = pointRadii.map(function (r) { return r + 2; });
    var datasets = [{
      data: points,
      backgroundColor: pointColors,
      borderColor: 'rgba(0,0,0,0.5)',
      borderWidth: 1.5,
      pointRadius: pointRadii,
      pointHoverRadius: pointHoverRadii,
    }];

    // Zone overlay plugin — wOBA/xwOBAcon heatmap gradient
    var SACQ_MIN_BIP = 20;
    var zoneMetric = this._laSprayZoneMetric || 'xwobacon';
    var zonePlugin = {
      id: 'sacqZones',
      beforeDatasetsDraw: function (chart) {
        var ctx2 = chart.ctx;
        var xScale = chart.scales.x;
        var yScale = chart.scales.y;
        var sprayBounds = { pull: [-45, -15], center: [-15, 15], oppo: [15, 45] };
        if (bats === 'L') {
          sprayBounds = { pull: [15, 45], center: [-15, 15], oppo: [-45, -15] };
        }
        // Color scale: blue (cold, low wOBA) → yellow (mid) → red (hot, high wOBA)
        // Range: 0.0 → 0.5 → 1.0+
        function wobaColorRGB(woba) {
          var t = Math.max(0, Math.min(1, woba / 1.0));
          var r, g, b;
          if (t < 0.35) {
            var s = t / 0.35;
            r = Math.round(8 + s * 30);
            g = Math.round(48 + s * 100);
            b = Math.round(107 + s * 40);
          } else if (t < 0.55) {
            var s = (t - 0.35) / 0.2;
            r = Math.round(38 + s * 200);
            g = Math.round(148 + s * 80);
            b = Math.round(147 - s * 100);
          } else {
            var s = (t - 0.55) / 0.45;
            r = Math.round(238 - s * 23);
            g = Math.round(228 - s * 180);
            b = Math.round(47 - s * 8);
          }
          return [r, g, b];
        }
        for (var zi = 0; zi < sacqZones.length; zi++) {
          var zone = sacqZones[zi];
          var zoneVal = zoneMetric === 'xwobacon' ? zone.xwobacon : zone.woba;
          if (zoneVal == null) continue;
          var bounds = sprayBounds[zone.spray];
          if (!bounds) continue;
          var laMin = zone.laMin != null ? zone.laMin : -20;
          var laMax = zone.laMax != null ? zone.laMax : 65;
          var x1 = xScale.getPixelForValue(bounds[0]);
          var x2 = xScale.getPixelForValue(bounds[1]);
          var y1 = yScale.getPixelForValue(laMax);
          var y2 = yScale.getPixelForValue(laMin);
          var rgb = wobaColorRGB(zoneVal);
          var lowSample = zone.count < SACQ_MIN_BIP;
          // Improvement 1: stronger opacity (0.25), muted for low-sample zones (0.10)
          var alpha = lowSample ? 0.10 : 0.25;
          ctx2.fillStyle = 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + alpha + ')';
          ctx2.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
          // Improvement 4: diagonal hatch pattern for low-sample zones
          if (lowSample) {
            ctx2.save();
            ctx2.beginPath();
            ctx2.rect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
            ctx2.clip();
            ctx2.strokeStyle = 'rgba(255,255,255,0.08)';
            ctx2.lineWidth = 0.5;
            var rx = Math.min(x1, x2), ry = Math.min(y1, y2);
            var rw = Math.abs(x2 - x1), rh = Math.abs(y2 - y1);
            var step = 6;
            for (var hi = -rh; hi < rw; hi += step) {
              ctx2.beginPath();
              ctx2.moveTo(rx + hi, ry);
              ctx2.lineTo(rx + hi + rh, ry + rh);
              ctx2.stroke();
            }
            ctx2.restore();
          }
          // Improvement 3: stronger grid lines (0.15)
          ctx2.strokeStyle = 'rgba(255,255,255,0.15)';
          ctx2.lineWidth = 0.5;
          ctx2.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
        }
      }
    };

    // Determine pull/oppo labels based on handedness
    var leftLabel = bats === 'L' ? 'Oppo' : 'Pull';
    var rightLabel = bats === 'L' ? 'Pull' : 'Oppo';

    // Destroy previous chart
    if (this._laSprayChart) {
      this._laSprayChart.destroy();
      this._laSprayChart = null;
    }

    this._laSprayChart = new Chart(canvas, {
      type: 'scatter',
      data: { datasets: datasets },
      plugins: [zonePlugin],
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 1.2,
        animation: false,
        clip: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var pt = ctx.raw;
                var evStr = pt.ev != null ? pt.ev.toFixed(1) + ' mph' : '—';
                var laStr = (pt.clamped ? pt.realLA.toFixed(1) : pt.y.toFixed(1)) + '°';
                var sprayStr = pt.x.toFixed(1) + '°';
                var evtNames = ['Out', 'Single', 'Double', 'Triple', 'HR', 'Error/FC'];
                var result = evtNames[pt.event] || 'Out';
                return result + ' | EV: ' + evStr + ' | LA: ' + laStr + ' | Spray: ' + sprayStr;
              }
            }
          }
        },
        scales: {
          x: {
            min: -45,
            max: 45,
            title: {
              display: true,
              text: '← ' + leftLabel + '          Spray Angle          ' + rightLabel + ' →',
              color: '#ccc',
              font: { family: 'Barlow', size: 12 }
            },
            ticks: {
              stepSize: 15,
              color: '#ccc',
              font: { family: 'Barlow', size: 11 },
              callback: function (value) {
                return value + '°';
              }
            },
            grid: { color: 'rgba(255,255,255,0.2)' }
          },
          y: {
            min: -20,
            max: 60,
            title: {
              display: true,
              text: 'Launch Angle',
              color: '#ccc',
              font: { family: 'Barlow', size: 12 }
            },
            ticks: {
              stepSize: 10,
              color: '#ccc',
              font: { family: 'Barlow', size: 11 },
              callback: function (value) {
                return value + '°';
              }
            },
            grid: { color: 'rgba(255,255,255,0.2)' }
          }
        }
      }
    });

    // Render legend
    var legendEl = document.getElementById('player-la-spray-legend');
    if (legendEl) {
      var legendItems = [];
      if (mode === 'outcome') {
        legendItems = [
          { color: '#666', label: 'Out' },
          { color: '#ff8c00', label: '1B' },
          { color: '#7b68ee', label: '2B' },
          { color: '#20b2aa', label: '3B' },
          { color: '#dc143c', label: 'HR' },
        ];
      } else if (mode === 'bbtype') {
        legendItems = [
          { color: '#4e79a7', label: 'GB' },
          { color: '#59a14f', label: 'LD' },
          { color: '#f28e2b', label: 'FB' },
          { color: '#e15759', label: 'PU' },
        ];
      } else if (mode === 'ev') {
        legendItems = [
          { color: 'rgb(8,48,107)', label: '70 mph' },
          { color: 'rgb(255,255,255)', label: '95 mph' },
          { color: 'rgb(215,48,39)', label: '115 mph' },
        ];
      }
      var html = '';
      for (var li = 0; li < legendItems.length; li++) {
        html += '<span class="spray-legend-item"><span class="spray-legend-dot" style="background:' +
          legendItems[li].color + '"></span>' + legendItems[li].label + '</span>';
      }
      // EV → size reference
      html += '<span class="spray-legend-item" style="margin-left:12px;">' +
        '<span class="spray-legend-dot" style="background:#888;width:10px;height:10px;border-radius:50%;"></span>' +
        '<span style="font-size:11px;color:var(--text-muted,#888);">Size = EV</span></span>';
      // Zone gradient legend bar
      var zoneLabel = zoneMetric === 'xwobacon' ? 'Zone xwOBAcon:' : 'Zone wOBA:';
      html += '<div class="la-spray-gradient-legend">' +
        '<span class="la-spray-gradient-label">' + zoneLabel + '</span>' +
        '<span class="la-spray-gradient-low">.000</span>' +
        '<span class="la-spray-gradient-bar"></span>' +
        '<span class="la-spray-gradient-high">1.000+</span>' +
        '</div>';
      legendEl.innerHTML = html;
    }

    // Bind toggle buttons
    this._bindLASprayToggle(data);
  },

  _bindLASprayToggle: function (data) {
    if (this._laSprayToggleHandler) return; // already bound
    var self = this;
    this._laSprayToggleHandler = function (e) {
      var btn = e.target.closest('.spray-toggle-btn');
      if (!btn) return;
      var mode = btn.getAttribute('data-mode');
      if (mode === self._laSprayMode) return;
      self._laSprayMode = mode;
      // Update active state only within la-spray-toggle
      var btns = document.querySelectorAll('#la-spray-toggle .spray-toggle-btn');
      for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
      btn.classList.add('active');
      if (self._currentData) self._renderLASprayChart(self._currentData);
    };
    var toggle = document.getElementById('la-spray-toggle');
    if (toggle) toggle.addEventListener('click', this._laSprayToggleHandler);

    // Zone metric toggle (wOBA / xwOBAcon)
    if (!this._laSprayZoneToggleHandler) {
      this._laSprayZoneToggleHandler = function (e) {
        var btn = e.target.closest('.spray-toggle-btn');
        if (!btn) return;
        var zm = btn.getAttribute('data-zone');
        if (!zm || zm === self._laSprayZoneMetric) return;
        self._laSprayZoneMetric = zm;
        var btns = document.querySelectorAll('#la-spray-zone-toggle .spray-toggle-btn');
        for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
        btn.classList.add('active');
        if (self._currentData) self._renderLASprayChart(self._currentData);
      };
      var zoneToggle = document.getElementById('la-spray-zone-toggle');
      if (zoneToggle) zoneToggle.addEventListener('click', this._laSprayZoneToggleHandler);
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

  _renderHitterStatsFullTable: function (data, isROC) {
    var section = document.getElementById('player-hitter-stats-section');
    var container = document.getElementById('player-hitter-stats-table');
    if (!container) return;
    container.innerHTML = '';

    if (!data) { if (section) section.style.display = 'none'; return; }
    section.style.display = '';

    var cols = this.HITTER_STATS_COLS;
    if (isROC) {
      cols = cols.filter(function (c) { return !c.rocHide; });
    }

    var table = document.createElement('table');
    table.className = 'player-pitch-stats-table expanded-pitch-table';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    for (var i = 0; i < cols.length; i++) {
      var th = document.createElement('th');
      th.textContent = cols[i].label;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var tr = document.createElement('tr');
    for (var c = 0; c < cols.length; c++) {
      var col = cols[c];
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

  // --- Hitter: Get category-level rows (Hard, Breaking, Offspeed) ---
  _getHitterCategoryRows: function (hitterName, team) {
    var hpData = window.HITTER_PITCH_LB || [];
    var CATEGORY_ORDER = ['Hard', 'Breaking', 'Offspeed'];
    var rows = [];
    for (var i = 0; i < hpData.length; i++) {
      var r = hpData[i];
      if (r.hitter === hitterName && r.team === team &&
          CATEGORY_ORDER.indexOf(r.pitchType) !== -1) {
        rows.push(r);
      }
    }
    rows.sort(function (a, b) {
      return CATEGORY_ORDER.indexOf(a.pitchType) - CATEGORY_ORDER.indexOf(b.pitchType);
    });
    return rows;
  },

  // --- Hitter: Get individual pitch rows for a category ---
  _getHitterPitchRowsForCategory: function (hitterName, team, category) {
    var CATS = Aggregator.PITCH_CATEGORIES;
    var pitchTypes = CATS[category] || [];
    var hpData = window.HITTER_PITCH_LB || [];
    var rows = [];
    for (var i = 0; i < hpData.length; i++) {
      var r = hpData[i];
      if (r.hitter === hitterName && r.team === team &&
          pitchTypes.indexOf(r.pitchType) !== -1) {
        rows.push(r);
      }
    }
    rows.sort(function (a, b) { return (b.count || 0) - (a.count || 0); });
    return rows;
  },

  // Category badge colors
  CATEGORY_COLORS: {
    'Hard': '#d62728',
    'Breaking': '#2ca02c',
    'Offspeed': '#ff7f0e'
  },

  // --- Hitter: Render grouped pitch table with expand/collapse ---
  _renderGroupedPitchTable: function (container, cols, categoryRows, totalRow, hitterName, team) {
    var self = this;
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

    // Body
    var tbody = document.createElement('tbody');

    for (var r = 0; r < categoryRows.length; r++) {
      (function (catRow) {
        var tr = document.createElement('tr');
        tr.className = 'category-row';
        tr.style.cursor = 'pointer';
        var expanded = false;
        var subRowEls = [];

        for (var c = 0; c < cols.length; c++) {
          var col = cols[c];
          var td = document.createElement('td');
          if (col.key === 'pitchType') {
            td.style.textAlign = 'left';
            td.style.paddingLeft = '8px';
            var indicator = document.createElement('span');
            indicator.className = 'expand-indicator';
            indicator.textContent = '\u25B6';
            td.appendChild(indicator);
            var badge = document.createElement('span');
            badge.className = 'pitch-badge-sm';
            var catColor = self.CATEGORY_COLORS[catRow.pitchType] || '#888';
            badge.style.backgroundColor = catColor;
            badge.style.color = Utils.badgeTextColor(catColor);
            badge.textContent = catRow.pitchType;
            td.appendChild(badge);
          } else {
            var val = catRow[col.key];
            td.textContent = col.format ? col.format(val) : (val != null ? val : '—');
          }
          tr.appendChild(td);
        }

        tr.addEventListener('click', function () {
          expanded = !expanded;
          var indicator = tr.querySelector('.expand-indicator');
          if (indicator) indicator.textContent = expanded ? '\u25BC' : '\u25B6';

          if (expanded && subRowEls.length === 0) {
            // First expand: create sub-rows
            var pitchRows = self._getHitterPitchRowsForCategory(hitterName, team, catRow.pitchType);
            var nextSibling = tr.nextSibling;
            for (var p = 0; p < pitchRows.length; p++) {
              var subTr = document.createElement('tr');
              subTr.className = 'sub-row';
              for (var sc = 0; sc < cols.length; sc++) {
                var subCol = cols[sc];
                var subTd = document.createElement('td');
                if (subCol.key === 'pitchType') {
                  subTd.style.paddingLeft = '28px';
                  var subBadge = document.createElement('span');
                  subBadge.className = 'pitch-badge-sm';
                  var _bc = Utils.getPitchColor(pitchRows[p].pitchType);
                  subBadge.style.backgroundColor = _bc;
                  subBadge.style.color = Utils.badgeTextColor(_bc);
                  subBadge.textContent = pitchRows[p].pitchType;
                  subTd.appendChild(subBadge);
                } else {
                  var subVal = pitchRows[p][subCol.key];
                  subTd.textContent = subCol.format ? subCol.format(subVal) : (subVal != null ? subVal : '—');
                }
                subTr.appendChild(subTd);
              }
              tbody.insertBefore(subTr, nextSibling);
              subRowEls.push(subTr);
            }
          } else {
            // Toggle visibility
            for (var s = 0; s < subRowEls.length; s++) {
              subRowEls[s].style.display = expanded ? '' : 'none';
            }
          }
        });

        tbody.appendChild(tr);
      })(categoryRows[r]);
    }

    // Total row
    if (totalRow) {
      var isDark = document.body.classList.contains('dark');
      var totalTr = document.createElement('tr');
      totalTr.style.fontWeight = '700';
      totalTr.style.borderTop = '2px solid #333840';
      for (var c2 = 0; c2 < cols.length; c2++) {
        var col2 = cols[c2];
        var td2 = document.createElement('td');
        if (col2.key === 'pitchType') {
          td2.textContent = 'Total';
        } else {
          var val2 = totalRow[col2.key];
          td2.textContent = col2.format ? col2.format(val2) : (val2 != null ? val2 : '—');
          var pctl2 = col2.noPctl ? null : totalRow[col2.key + '_pctl'];
          if (pctl2 != null && val2 != null) {
            var bgColor2 = isDark ? Utils.percentileColorDark(pctl2) : Utils.percentileColor(pctl2);
            var txtColor2 = isDark ? Utils.percentileTextColorDark(pctl2) : Utils.percentileTextColor(pctl2);
            td2.style.backgroundColor = bgColor2;
            td2.style.color = txtColor2;
            td2.title = Math.round(pctl2) + 'th percentile';
          }
        }
        totalTr.appendChild(td2);
      }
      tbody.appendChild(totalTr);
    }

    table.appendChild(tbody);
    container.appendChild(table);

    // Horizontal scroll fade indicator
    container.style.position = 'relative';
    var fadeDiv = document.createElement('div');
    fadeDiv.style.cssText = 'position:absolute;right:0;top:0;bottom:0;width:24px;background:linear-gradient(to right, transparent, #1a1d21);pointer-events:none;z-index:1;opacity:0;transition:opacity 0.2s;';
    container.appendChild(fadeDiv);
    container.addEventListener('scroll', function() {
      var maxScroll = container.scrollWidth - container.clientWidth;
      fadeDiv.style.opacity = (container.scrollLeft >= maxScroll - 2) ? '0' : '1';
    });
    setTimeout(function() {
      if (container.scrollWidth > container.clientWidth) fadeDiv.style.opacity = '1';
    }, 100);
  },

  // --- Hitter: Batted Ball Table ---

  _renderHitterBattedBallTable: function (data, isROC) {
    var section = document.getElementById('player-hitter-batted-ball-section');
    var container = document.getElementById('player-hitter-batted-ball-table');
    if (!container) return;
    container.innerHTML = '';

    // Filter out columns unavailable for ROC players
    var ROC_HIDE_BB = { xBA: true, xSLG: true, xwOBA: true, xwOBAcon: true, xwOBAsp: true };
    var cols = this.HITTER_BATTED_BALL_COLS;
    if (isROC) {
      cols = cols.filter(function (c) { return !ROC_HIDE_BB[c.key]; });
    }

    var totalRow = { pitchType: 'Total' };
    for (var k = 0; k < cols.length; k++) {
      var key = cols[k].key;
      if (key !== 'pitchType') {
        totalRow[key] = data[key];
        if (data[key + '_pctl'] != null) totalRow[key + '_pctl'] = data[key + '_pctl'];
      }
    }

    // Use filtered platoon rows if available, otherwise grouped categories, otherwise individual pitch types
    if (this._filteredHitterPitchRows) {
      var pitchRows = this._filteredHitterPitchRows;
      if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
      section.style.display = '';
      this._renderPerPitchTable(container, cols, pitchRows, totalRow);
    } else {
      var categoryRows = this._getHitterCategoryRows(data.hitter, data.team);
      if (categoryRows.length > 0) {
        section.style.display = '';
        this._renderGroupedPitchTable(container, cols, categoryRows, totalRow, data.hitter, data.team);
      } else {
        var pitchRows = this._getHitterPitchRows(data.hitter, data.team);
        if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
        section.style.display = '';
        this._renderPerPitchTable(container, cols, pitchRows, totalRow);
      }
    }
  },

  // --- Hitter: Plate Discipline Table ---

  _renderHitterPlateDisciplineTable: function (data) {
    var section = document.getElementById('player-hitter-plate-discipline-section');
    var container = document.getElementById('player-hitter-plate-discipline-table');
    if (!container) return;
    container.innerHTML = '';

    var totalRow = { pitchType: 'Total' };
    for (var k = 0; k < this.HITTER_PLATE_DISCIPLINE_COLS.length; k++) {
      var key = this.HITTER_PLATE_DISCIPLINE_COLS[k].key;
      if (key !== 'pitchType') {
        totalRow[key] = data[key];
        if (data[key + '_pctl'] != null) totalRow[key + '_pctl'] = data[key + '_pctl'];
      }
    }

    // Use filtered platoon rows if available, otherwise grouped categories, otherwise individual pitch types
    if (this._filteredHitterPitchRows) {
      var pitchRows = this._filteredHitterPitchRows;
      if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
      section.style.display = '';
      this._renderPerPitchTable(container, this.HITTER_PLATE_DISCIPLINE_COLS, pitchRows, totalRow);
    } else {
      var categoryRows = this._getHitterCategoryRows(data.hitter, data.team);
      if (categoryRows.length > 0) {
        section.style.display = '';
        this._renderGroupedPitchTable(container, this.HITTER_PLATE_DISCIPLINE_COLS, categoryRows, totalRow, data.hitter, data.team);
      } else {
        var pitchRows = this._getHitterPitchRows(data.hitter, data.team);
        if (pitchRows.length === 0) { if (section) section.style.display = 'none'; return; }
        section.style.display = '';
        this._renderPerPitchTable(container, this.HITTER_PLATE_DISCIPLINE_COLS, pitchRows, totalRow);
      }
    }
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
