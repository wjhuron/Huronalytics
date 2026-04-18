const DataStore = {
  rs: {},

  active: function () {
    return this.rs;
  },

  load: function () {
    if (window.RS_DATA) {
      this.rs = {
        pitcherData: window.RS_DATA.pitcherData || [],
        pitchData: window.RS_DATA.pitchData || [],
        hitterData: window.RS_DATA.hitterData || [],
        hitterPitchData: window.RS_DATA.hitterPitchData || [],
        metadata: window.RS_DATA.metadata || {},
        microData: window.RS_DATA.microData || null,
        pitchDetails: window.RS_DATA.pitchDetails || {},
        hitterPitchDetails: window.RS_DATA.hitterPitchDetails || {},
      };
    }

    // Set flat globals so aggregator.js, player-page.js, scatter.js can access data
    this.updateGlobals();

    this.metadata = this.rs.metadata;
    this.pitcherData = this.rs.pitcherData;
    this.pitchData = this.rs.pitchData;
    this.hitterData = this.rs.hitterData;
    this.hitterPitchData = this.rs.hitterPitchData;

    return Promise.resolve();
  },

  updateGlobals: function () {
    const d = this.rs;
    window.PITCHER_DATA = d.pitcherData;
    window.PITCH_DATA = d.pitchData;
    window.HITTER_DATA = d.hitterData;
    window.HITTER_PITCH_LB = d.hitterPitchData;
    window.METADATA = d.metadata;
    window.MICRO_DATA = d.microData;
    window.PITCH_DETAILS = d.pitchDetails;
    window.HITTER_PITCH_DETAILS = d.hitterPitchDetails;

    this.metadata = d.metadata;
    this.pitcherData = d.pitcherData;
    this.pitchData = d.pitchData;
    this.hitterData = d.hitterData;
    this.hitterPitchData = d.hitterPitchData;
  },

  /**
   * Smart filter: uses Aggregator when date/hand filters are active,
   * otherwise falls back to pre-aggregated data.
   * @param {'pitcher'|'pitch'|'hitter'|'hitterPitch'} tab - Data source tab.
   * @param {FilterState} filters - Current filter state.
   * @returns {(PitcherRow|PitchRow|HitterRow)[]} Filtered row array.
   */
  getFilteredDataV2: function (tab, filters) {
    if (Aggregator.needsReaggregation(filters)) {
      return Aggregator.aggregate(tab, filters);
    }
    return this.getFilteredData(tab, filters);
  },

  /**
   * Filter pre-aggregated data based on current filters.
   * @param {'pitcher'|'pitch'|'hitter'|'hitterPitch'} tab - Data source tab.
   * @param {FilterState} filters - Current filter state (pitchTypes is always an array).
   * @returns {(PitcherRow|PitchRow|HitterRow)[]} Filtered row array.
   */
  getFilteredData: function (tab, filters) {
    const d = this.rs;
    let source;
    if (tab === 'pitch') source = d.pitchData;
    else if (tab === 'pitcher') source = d.pitcherData;
    else if (tab === 'hitter') source = d.hitterData;
    else if (tab === 'hitterPitch') source = d.hitterPitchData;
    if (!source) return [];

    const isHitter = (tab === 'hitter' || tab === 'hitterPitch');
    const hasPitchType = (tab === 'pitch' || tab === 'hitterPitch');
    const selectedPitchTypes = filters.pitchTypes; // always array

    const rocTeamsArr = (this.metadata && this.metadata.rocTeams) || [];
    var rocTeamSet = {};
    for (var ri = 0; ri < rocTeamsArr.length; ri++) rocTeamSet[rocTeamsArr[ri]] = true;
    // Team games for per-team qualifying thresholds
    var _teamGames = (filters.minIp === 'Q' || filters.minCount === 'Q')
      ? (Aggregator.loaded ? Aggregator.getTeamGamesPlayed() : {}) : {};

    // Multi-team support: scan once to build player→combined-row map and cumulative team games.
    // When "All Teams" is selected, per-team rows of multi-team players are hidden; the 2TM/3TM
    // row stands in. Qualification for multi-team players uses combined IP/PA and summed team games.
    var combinedByPlayer = {};
    var isCombinedRe = /^\d+TM$/;
    for (var di2 = 0; di2 < source.length; di2++) {
      var drow = source[di2];
      if (isCombinedRe.test(drow.team)) {
        var pname = drow.pitcher || drow.hitter;
        if (pname) combinedByPlayer[pname] = drow;
      }
    }
    var cumTeamGames = {};
    if (filters.minIp === 'Q' || filters.minCount === 'Q') {
      for (var di3 = 0; di3 < source.length; di3++) {
        var drow2 = source[di3];
        var pn = drow2.pitcher || drow2.hitter;
        if (pn && combinedByPlayer[pn] && !isCombinedRe.test(drow2.team)) {
          cumTeamGames[pn] = (cumTeamGames[pn] || 0) + (_teamGames[drow2.team] || 0);
        }
      }
    }
    return source.filter(function (row) {
      // Hide ROC players unless user explicitly selected their team
      if (rocTeamSet[row.team] && filters.team !== row.team) return false;
      // Multi-team: "All Teams" view shows only the combined row for multi-team players.
      // Specific-team view shows only per-team rows (combined row hidden).
      var pkey = row.pitcher || row.hitter;
      var isCombinedRow = isCombinedRe.test(row.team);
      if (filters.team === 'all') {
        if (combinedByPlayer[pkey] && !isCombinedRow) return false;
      } else {
        if (isCombinedRow) return false;
      }
      if (filters.team !== 'all' && row.team !== filters.team) return false;

      // Throws filter applies to pitchers; stands filter applies to hitters (same dropdown)
      if (filters.throws !== 'all') {
        if (isHitter) {
          if (row.stands !== filters.throws) return false;
        } else {
          if (row.throws !== filters.throws) return false;
        }
      }

      // SP/RP role filter (pitcher tabs only)
      if (filters.role && filters.role !== 'all' && !isHitter) {
        let g = row.g, gs = row.gs;
        // For pitch-level rows without G/GS, look up from pitcher role cache
        if (g == null && row.pitcher) {
          if (!DataStore._roleCache) {
            DataStore._roleCache = {};
            const pData = DataStore.rs.pitcherData || [];
            for (let pi = 0; pi < pData.length; pi++) {
              const rk = pData[pi].pitcher + '|' + pData[pi].team;
              DataStore._roleCache[rk] = { g: pData[pi].g, gs: pData[pi].gs };
            }
          }
          const cached = DataStore._roleCache[row.pitcher + '|' + row.team];
          if (cached) { g = cached.g; gs = cached.gs; }
        }
        g = g || 0; gs = gs || 0;
        const isStarter = g > 0 && (gs / g) > QUAL.SP_GS_RATIO;
        if (filters.role === 'SP' && !isStarter) return false;
        if (filters.role === 'RP' && isStarter) return false;
      }

      if (hasPitchType && selectedPitchTypes.indexOf('all') === -1) {
        if (selectedPitchTypes.indexOf(row.pitchType) === -1) return false;
      }
      // For multi-team players, qualification uses the combined row's stats and
      // the cumulative team games across their MLB teams.
      var mtRow = combinedByPlayer[pkey];
      var _tg = (mtRow && !isCombinedRow) ? (cumTeamGames[pkey] || 0) : (_teamGames[row.team] || 0);
      var _qPa = (mtRow && !isCombinedRow) ? (mtRow.pa || 0) : (row.pa || 0);
      var _qIp = (mtRow && !isCombinedRow) ? mtRow.ip : row.ip;
      var _qG = (mtRow && !isCombinedRow) ? mtRow.g : row.g;
      var _qGs = (mtRow && !isCombinedRow) ? mtRow.gs : row.gs;
      // Min count: use PA for hitters, pitch count for pitchers and hitterPitch
      if (tab === 'hitter') {
        if (filters.minCount === 'Q') {
          if (_qPa < _tg * QUAL.PA_PER_GAME) return false;
        } else if ((row.pa || 0) < filters.minCount) return false;
      } else {
        if (row.count < filters.minCount) return false;
      }
      if (tab === 'hitter' && filters.minSwings && row.nSwings < filters.minSwings) return false;
      if (tab === 'pitcher' && filters.minTbf && (row.pa || 0) < filters.minTbf) return false;
      if (tab === 'pitcher' && filters.minIp) {
        if (filters.minIp === 'Q') {
          var ipFloat = Utils.parseIP(_qIp);
          var isStarter = Utils.isStarter(_qG, _qGs);
          var ipThresh = isStarter ? _tg * 1.0 : _tg / 3;
          if (ipFloat < ipThresh) return false;
        } else if ((row.ip || 0) < filters.minIp) return false;
      }
      if ((tab === 'pitcher' || tab === 'hitter') && filters.minBip && row.nBip != null && row.nBip < filters.minBip) return false;
      if (tab === 'pitcher' && filters.minPitcherSwings && row.nSwings != null && row.nSwings < filters.minPitcherSwings) return false;
      if (filters.search) {
        const name = (row.pitcher || row.hitter || '').toLowerCase();
        if (name.indexOf(filters.search.toLowerCase()) === -1) return false;
      }
      return true;
    });
  },
};
