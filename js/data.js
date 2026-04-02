var DataStore = {
  st: {},
  rs: {},
  gameType: 'RS',

  active: function () {
    return this.gameType === 'ST' ? this.st : this.rs;
  },

  getMetadata: function () {
    return this.active().metadata;
  },

  load: function () {
    // Load from new dual-dataset structure
    if (window.ST_DATA) {
      this.st = {
        pitcherData: window.ST_DATA.pitcherData || [],
        pitchData: window.ST_DATA.pitchData || [],
        hitterData: window.ST_DATA.hitterData || [],
        hitterPitchData: window.ST_DATA.hitterPitchData || [],
        metadata: window.ST_DATA.metadata || {},
        microData: window.ST_DATA.microData || null,
        pitchDetails: window.ST_DATA.pitchDetails || {},
        hitterPitchDetails: window.ST_DATA.hitterPitchDetails || {},
      };
    }
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

    // Backwards compat: if old flat globals exist and new ones don't
    if (!window.ST_DATA && !window.RS_DATA && window.PITCHER_DATA && window.METADATA) {
      this.rs = {
        pitcherData: window.PITCHER_DATA || [],
        pitchData: window.PITCH_DATA || [],
        hitterData: window.HITTER_DATA || [],
        hitterPitchData: window.HITTER_PITCH_LB || [],
        metadata: window.METADATA || {},
        microData: window.MICRO_DATA || null,
        pitchDetails: window.PITCH_DETAILS || {},
        hitterPitchDetails: window.HITTER_PITCH_DETAILS || {},
      };
    }

    // Set flat globals for backwards compatibility
    this.updateGlobals();

    // Expose convenience properties from active dataset
    this.metadata = this.active().metadata;
    this.pitcherData = this.active().pitcherData;
    this.pitchData = this.active().pitchData;
    this.hitterData = this.active().hitterData;
    this.hitterPitchData = this.active().hitterPitchData;

    return Promise.resolve();
  },

  updateGlobals: function () {
    var d = this.active();
    window.PITCHER_DATA = d.pitcherData;
    window.PITCH_DATA = d.pitchData;
    window.HITTER_DATA = d.hitterData;
    window.HITTER_PITCH_LB = d.hitterPitchData;
    window.METADATA = d.metadata;
    window.MICRO_DATA = d.microData;
    window.PITCH_DETAILS = d.pitchDetails;
    window.HITTER_PITCH_DETAILS = d.hitterPitchDetails;

    // Also update convenience properties
    this.metadata = d.metadata;
    this.pitcherData = d.pitcherData;
    this.pitchData = d.pitchData;
    this.hitterData = d.hitterData;
    this.hitterPitchData = d.hitterPitchData;
  },

  /**
   * Smart filter: uses Aggregator when date/hand filters are active,
   * otherwise falls back to pre-aggregated data.
   */
  getFilteredDataV2: function (tab, filters) {
    if (Aggregator.needsReaggregation(filters)) {
      return Aggregator.aggregate(tab, filters);
    }
    return this.getFilteredData(tab, filters);
  },

  /**
   * Filter data based on current filters.
   * pitchTypes can be an array for multi-select: ['FF', 'SI'] or 'all'
   */
  getFilteredData: function (tab, filters) {
    var d = this.active();
    var source;
    if (tab === 'pitch') source = d.pitchData;
    else if (tab === 'pitcher') source = d.pitcherData;
    else if (tab === 'hitter') source = d.hitterData;
    else if (tab === 'hitterPitch') source = d.hitterPitchData;
    if (!source) return [];

    var isHitter = (tab === 'hitter' || tab === 'hitterPitch');
    var hasPitchType = (tab === 'pitch' || tab === 'hitterPitch');
    var selectedPitchTypes = filters.pitchTypes; // array or 'all'

    return source.filter(function (row) {
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
        var g = row.g, gs = row.gs;
        // For pitch-level rows without G/GS, look up from pitcher data
        if (g == null && row.pitcher) {
          var pitcherData = DataStore.active().pitcherData || [];
          for (var pi = 0; pi < pitcherData.length; pi++) {
            if (pitcherData[pi].pitcher === row.pitcher && pitcherData[pi].team === row.team) {
              g = pitcherData[pi].g; gs = pitcherData[pi].gs; break;
            }
          }
        }
        g = g || 0; gs = gs || 0;
        var isStarter = g > 0 && (gs / g) > 0.5;
        if (filters.role === 'SP' && !isStarter) return false;
        if (filters.role === 'RP' && isStarter) return false;
      }

      if (hasPitchType && selectedPitchTypes !== 'all') {
        if (selectedPitchTypes.indexOf(row.pitchType) === -1) return false;
      }
      // Min count: use PA for hitters, pitch count for pitchers and hitterPitch
      if (tab === 'hitter') {
        if ((row.pa || 0) < filters.minCount) return false;
      } else {
        if (row.count < filters.minCount) return false;
      }
      if (tab === 'hitter' && filters.minSwings && row.nSwings < filters.minSwings) return false;
      if (tab === 'pitcher' && filters.minTbf && (row.pa || 0) < filters.minTbf) return false;
      if (tab === 'pitcher' && filters.minIp && (row.ip || 0) < filters.minIp) return false;
      if ((tab === 'pitcher' || tab === 'hitter') && filters.minBip && row.nBip != null && row.nBip < filters.minBip) return false;
      if (tab === 'pitcher' && filters.minPitcherSwings && row.nSwings != null && row.nSwings < filters.minPitcherSwings) return false;
      if (filters.search) {
        var name = (row.pitcher || row.hitter || '').toLowerCase();
        if (name.indexOf(filters.search.toLowerCase()) === -1) return false;
      }
      return true;
    });
  },
};
