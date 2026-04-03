/**
 * Client-side aggregator for micro-aggregate data.
 * Enables filtering by opponent hand and date range by
 * summing pre-computed counts and recomputing final stats + percentiles.
 */
var Aggregator = {
  data: null,
  loaded: false,
  _colIdx: {},

  load: function (microData) {
    this._roleCache = null;  // Clear role cache on reload
    // Accept micro data directly (from DataStore)
    if (microData) {
      this.data = microData;
      this._buildIndexes();
      this.loaded = true;
      return Promise.resolve();
    }
    // Try embedded data (for file:// usage, backwards compat)
    if (window.MICRO_DATA) {
      this.data = window.MICRO_DATA;
      this._buildIndexes();
      this.loaded = true;
      return Promise.resolve();
    }
    // Fallback: fetch JSON
    var self = this;
    return fetch('data/micro_data.json')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        self.data = d;
        self._buildIndexes();
        self.loaded = true;
      })
      .catch(function (e) {
        console.warn('Micro data not available (advanced filters disabled):', e);
        self.loaded = false;
      });
  },

  _buildIndexes: function () {
    var d = this.data;
    var tables = ['pitcherCols', 'pitcherBipCols', 'pitchCols', 'hitterCols', 'hitterBipCols', 'hitterPitchCols', 'hitterPitchBipCols', 'veloTrendCols'];
    for (var t = 0; t < tables.length; t++) {
      var key = tables[t];
      this._colIdx[key] = {};
      for (var i = 0; i < d[key].length; i++) {
        this._colIdx[key][d[key][i]] = i;
      }
    }
  },

  /**
   * Returns true if advanced filters are active and re-aggregation is needed.
   */
  needsReaggregation: function (filters) {
    if (!this.loaded) return false;
    // Always reaggregate — ensures correct qualifying-based percentiles
    return true;
  },

  // --- Spray angle utilities for SACQ% ---
  _HP_X: 125.42,
  _HP_Y: 198.27,
  _LA_BINS: [[-999,0],[0,5],[5,10],[10,15],[15,20],[20,25],[25,30],[30,35],[35,40],[40,50],[50,999]],

  computeSprayAngle: function (hcX, hcY) {
    if (hcX == null || hcY == null) return null;
    var dx = hcX - this._HP_X;
    var dy = this._HP_Y - hcY;
    if (dy <= 0) return null;
    return Math.atan2(dx, dy) * (180 / Math.PI);
  },

  sprayDirection: function (angle, bats) {
    if (angle == null || !bats) return null;
    if (bats === 'R') {
      return angle < -15 ? 'pull' : (angle > 15 ? 'oppo' : 'center');
    } else {
      return angle > 15 ? 'pull' : (angle < -15 ? 'oppo' : 'center');
    }
  },

  getLABinIdx: function (la) {
    var bins = this._LA_BINS;
    for (var i = 0; i < bins.length; i++) {
      if (la >= bins[i][0] && la < bins[i][1]) return i;
    }
    return null;
  },

  /**
   * Main entry: aggregate micro data for the given tab and filters.
   * Returns an array of row objects matching the pre-aggregated format.
   */
  aggregate: function (tab, filters) {
    if (tab === 'pitcher') return this._aggregatePitcher(filters);
    if (tab === 'pitch') return this._aggregatePitch(filters);
    if (tab === 'hitter') return this._aggregateHitter(filters);
    if (tab === 'hitterPitch') return this._aggregateHitterPitch(filters);
    return [];
  },

  // ---- MLB ID lookup helper (from static pre-aggregated data) ----
  _getMlbIdMap: function (type) {
    var data = type === 'pitcher' ? (window.PITCHER_DATA || []) : (window.HITTER_DATA || []);
    var nameKey = type === 'pitcher' ? 'pitcher' : 'hitter';
    var map = {};
    for (var i = 0; i < data.length; i++) {
      if (data[i].mlbId) {
        map[data[i][nameKey] + '|' + data[i].team] = data[i].mlbId;
      }
    }
    return map;
  },

  // ---- Date filtering helper ----
  _getValidDateSet: function (filters) {
    var dates = this.data.lookups.dates;
    var minDate = filters.dateStart || '';
    var maxDate = filters.dateEnd || '\uffff';
    var valid = {};
    for (var i = 0; i < dates.length; i++) {
      if (dates[i] >= minDate && dates[i] <= maxDate) {
        valid[i] = true;
      }
    }
    return valid;
  },

  // Helper: check if a team is a ROC/AAA team (excluded from MLB percentile pool)
  _isROCTeam: function (team) {
    var rocTeams = (window.METADATA && window.METADATA.rocTeams) ||
                   (DataStore && DataStore.metadata && DataStore.metadata.rocTeams) || [];
    return rocTeams.indexOf(team) !== -1;
  },

  // ---- Percentile computation (replicates Python's compute_percentile_ranks) ----
  // ROC-aware: excludes ROC teams from the percentile pool, then interpolates ROC players
  // minCount: minimum value of row[countKey] to qualify for percentile pool (0 = no threshold)
  _computePercentiles: function (rows, metricKey, minCount, countKey, useAbs) {
    minCount = minCount || 0;
    countKey = countKey || 'count';
    var pctlKey = metricKey + '_pctl';
    var self = this;

    // Separate MLB and ROC rows
    var mlbValid = [];
    var rocValid = [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i][metricKey] !== null && rows[i][metricKey] !== undefined
          && (minCount === 0 || (rows[i][countKey] || 0) >= minCount)) {
        var rawVal = rows[i][metricKey];
        var entry = { idx: i, val: useAbs ? Math.abs(rawVal) : rawVal };
        if (self._isROCTeam(rows[i].team)) {
          rocValid.push(entry);
        } else {
          mlbValid.push(entry);
        }
      }
    }

    if (mlbValid.length < 2) {
      for (var j = 0; j < rows.length; j++) {
        rows[j][pctlKey] = (rows[j][metricKey] !== null && rows[j][metricKey] !== undefined
                            && (minCount === 0 || (rows[j][countKey] || 0) >= minCount)) ? 50 : null;
      }
      return;
    }

    // Compute percentiles for MLB rows
    var mlbValues = mlbValid.map(function (v) { return v.val; });
    var n = mlbValues.length;
    for (var k = 0; k < mlbValid.length; k++) {
      var val = mlbValid[k].val;
      var below = 0, equal = 0;
      for (var m = 0; m < n; m++) {
        if (mlbValues[m] < val) below++;
        if (mlbValues[m] === val) equal++;
      }
      var pctl = (below + 0.5 * (equal - 1)) / Math.max(1, n - 1) * 100;
      rows[mlbValid[k].idx][pctlKey] = Math.max(0, Math.min(100, Math.round(pctl)));
    }

    // Interpolate ROC rows into MLB distribution
    for (var r = 0; r < rocValid.length; r++) {
      var rVal = rocValid[r].val;
      var rBelow = 0, rEqual = 0;
      for (var m2 = 0; m2 < n; m2++) {
        if (mlbValues[m2] < rVal) rBelow++;
        if (mlbValues[m2] === rVal) rEqual++;
      }
      var rPctl = (rBelow + 0.5 * rEqual) / n * 100;
      rows[rocValid[r].idx][pctlKey] = Math.max(0, Math.min(100, Math.round(rPctl)));
    }

    // Interpolate sub-minimum rows into the qualified pool (they get percentiles but are "unqualified")
    if (minCount > 0) {
      for (var s = 0; s < rows.length; s++) {
        if (pctlKey in rows[s]) continue; // Already computed above
        var sVal = rows[s][metricKey];
        if (sVal === null || sVal === undefined) {
          rows[s][pctlKey] = null;
          continue;
        }
        var sv = useAbs ? Math.abs(sVal) : sVal;
        var sBelow = 0, sEqual = 0;
        for (var sm = 0; sm < n; sm++) {
          if (mlbValues[sm] < sv) sBelow++;
          if (mlbValues[sm] === sv) sEqual++;
        }
        var sPctl = (sBelow + 0.5 * sEqual) / n * 100;
        rows[s][pctlKey] = Math.max(0, Math.min(100, Math.round(sPctl)));
      }
    }

    for (var j2 = 0; j2 < rows.length; j2++) {
      if (!(pctlKey in rows[j2])) {
        rows[j2][pctlKey] = null;
      }
    }
  },

  // Percentile computation using _qualified flag instead of minCount (ROC-aware)
  _computePercentilesQualified: function (rows, metricKey) {
    var pctlKey = metricKey + '_pctl';
    var self = this;
    var mlbValid = [];
    var rocValid = [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i][metricKey] !== null && rows[i][metricKey] !== undefined && rows[i]._qualified) {
        var entry = { idx: i, val: rows[i][metricKey] };
        if (self._isROCTeam(rows[i].team)) {
          rocValid.push(entry);
        } else {
          mlbValid.push(entry);
        }
      }
    }
    if (mlbValid.length < 2) {
      for (var j = 0; j < rows.length; j++) {
        rows[j][pctlKey] = (rows[j][metricKey] !== null && rows[j][metricKey] !== undefined && rows[j]._qualified) ? 50 : null;
      }
      return;
    }
    var mlbValues = mlbValid.map(function (v) { return v.val; });
    var n = mlbValues.length;
    for (var k = 0; k < mlbValid.length; k++) {
      var val = mlbValid[k].val;
      var below = 0, equal = 0;
      for (var m = 0; m < n; m++) {
        if (mlbValues[m] < val) below++;
        if (mlbValues[m] === val) equal++;
      }
      var pctl = (below + 0.5 * (equal - 1)) / Math.max(1, n - 1) * 100;
      rows[mlbValid[k].idx][pctlKey] = Math.max(0, Math.min(100, Math.round(pctl)));
    }
    // Interpolate ROC rows into MLB distribution
    for (var r = 0; r < rocValid.length; r++) {
      var rVal = rocValid[r].val;
      var rBelow = 0, rEqual = 0;
      for (var m2 = 0; m2 < n; m2++) {
        if (mlbValues[m2] < rVal) rBelow++;
        if (mlbValues[m2] === rVal) rEqual++;
      }
      var rPctl = (rBelow + 0.5 * rEqual) / n * 100;
      rows[rocValid[r].idx][pctlKey] = Math.max(0, Math.min(100, Math.round(rPctl)));
    }
    for (var j2 = 0; j2 < rows.length; j2++) {
      if (!(pctlKey in rows[j2])) rows[j2][pctlKey] = null;
    }
  },

  // ==================================================================
  //  Pitcher aggregation
  // ==================================================================
  _aggregatePitcher: function (filters) {
    var d = this.data;
    var ci = this._colIdx.pitcherCols;
    var micro = d.pitcherMicro;
    var lookups = d.lookups;
    var validDates = this._getValidDateSet(filters);
    var vsHand = filters.vsHand || 'all';

    // Group by (pitcherIdx, teamIdx)
    var groups = {};
    for (var i = 0; i < micro.length; i++) {
      var row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.batterHand] !== vsHand) continue;

      var gk = row[ci.pitcherIdx] + '|' + row[ci.teamIdx];
      if (!groups[gk]) {
        groups[gk] = {
          pitcherIdx: row[ci.pitcherIdx],
          teamIdx: row[ci.teamIdx],
          throws: row[ci.throws],
          counts: new Array(27)
        };
        for (var z = 0; z < 27; z++) groups[gk].counts[z] = 0;
      }
      var c = groups[gk].counts;
      for (var f = 0; f < 27; f++) {
        c[f] += row[ci.n + f];
      }
    }

    // MLB ID lookup for clickable names
    var mlbIdMap = this._getMlbIdMap('pitcher');

    // Filter pitcher BIP records for batted ball stats
    var pbci = this._colIdx.pitcherBipCols;
    var pitcherBipData = d.pitcherBip || [];
    var bipByPitcher = {};
    for (var bi = 0; bi < pitcherBipData.length; bi++) {
      var brow = pitcherBipData[bi];
      if (!validDates[brow[pbci.dateIdx]]) continue;
      if (vsHand !== 'all' && brow[pbci.batterHand] !== vsHand) continue;
      var pIdx = brow[pbci.pitcherIdx];
      if (!bipByPitcher[pIdx]) bipByPitcher[pIdx] = [];
      bipByPitcher[pIdx].push(brow);
    }

    function isBarrel(ev, la) {
      // Statcast barrel: LA in [8,50], EV>=98, EV*1.5-LA>=117, EV+LA>=124
      if (ev == null || la == null) return false;
      return la >= 8 && la <= 50 && ev >= 98 && ev * 1.5 - la >= 117 && ev + la >= 124;
    }

    // Convert to row objects
    var STAT_KEYS = ['strikePct', 'izPct', 'cswPct', 'izWhiffPct', 'swStrPct', 'chasePct', 'gbPct', 'kPct', 'bbPct', 'kbbPct', 'babip', 'fpsPct', 'hrFbPct',
                     'avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst'];
    var INVERT = { bbPct: true, babip: true, hrFbPct: true, avgEVAgainst: true, maxEVAgainst: true, hardHitPct: true, barrelPctAgainst: true };
    var rows = [];

    for (var gk2 in groups) {
      var g = groups[gk2];
      var c = g.counts;
      var n = c[0], iz = c[1], sw = c[2], wh = c[3], csw = c[4];
      var ooz = c[5], oozSw = c[6], bip = c[7], gb = c[8];
      var pa = c[9], h = c[10], hr = c[11], k = c[12], bb = c[13];
      var hbp = c[14], sf = c[15], sh = c[16], ci_val = c[17];
      var izSw = c[18], izWh = c[19];
      var firstPitches = c[20], firstPitchStrikes = c[21], fb_cnt = c[22], nHrBip = c[23], ldHr = c[24], pu_cnt = c[25], nStrikes = c[26];
      var ab = pa - bb - hbp - sf - sh - ci_val;

      var strikePct = n > 0 ? nStrikes / n : null;
      var kPct = pa > 0 ? k / pa : null;
      var bbPct = pa > 0 ? bb / pa : null;
      var kbbPct = (kPct !== null && bbPct !== null) ? Math.round((kPct - bbPct) * 10000) / 10000 : null;
      var babip_denom = ab - k - hr + sf;
      var babip = babip_denom > 0 ? Math.round((h - hr) / babip_denom * 1000) / 1000 : null;
      var fpsPct = firstPitches > 0 ? firstPitchStrikes / firstPitches : null;
      var fb_for_hrfb = fb_cnt + pu_cnt + ldHr;
      var hrFbPct = fb_for_hrfb > 0 ? nHrBip / fb_for_hrfb : null;

      // Compute batted ball stats from pitcher BIP records
      var bipRecs = bipByPitcher[g.pitcherIdx] || [];
      var evs = [], n_bip_ev = 0, n_hard = 0, n_barrel = 0;
      var n_ld = 0, n_fb_bb = 0, n_pu_bb = 0, n_bip_total = bipRecs.length;
      for (var bri = 0; bri < bipRecs.length; bri++) {
        var bev = bipRecs[bri][pbci.exitVelo];
        var bla = bipRecs[bri][pbci.launchAngle];
        var bbt = bipRecs[bri][pbci.bbType]; // 0=gb, 1=ld, 2=fb, 3=pu
        if (bev !== null) { evs.push(bev); if (bev >= 95) n_hard++; }
        if (isBarrel(bev, bla)) n_barrel++;
        if (bbt === 1) n_ld++;
        if (bbt === 2) n_fb_bb++;
        if (bbt === 3) n_pu_bb++;
      }
      var avgEVAgainst = evs.length > 0 ? Math.round(evs.reduce(function(a,b){return a+b;},0) / evs.length * 10) / 10 : null;
      var maxEVAgainst = evs.length > 0 ? Math.round(Math.max.apply(null, evs) * 10) / 10 : null;
      var hardHitPct_val = n_bip_total > 0 ? n_hard / n_bip_total : null;
      var barrelPctAgainst = n_bip_total > 0 ? n_barrel / n_bip_total : null;
      var ldPct_val = n_bip_total > 0 ? n_ld / n_bip_total : null;
      var fbPct_val = n_bip_total > 0 ? n_fb_bb / n_bip_total : null;
      var puPct_val = n_bip_total > 0 ? n_pu_bb / n_bip_total : null;

      var pitcherName = lookups.pitchers[g.pitcherIdx];
      var teamName = lookups.teams[g.teamIdx];
      var obj = {
        pitcher: pitcherName,
        team: teamName,
        mlbId: mlbIdMap[pitcherName + '|' + teamName] || null,
        throws: g.throws,
        count: n,
        pa: pa,
        nSwings: sw,
        nBip: bip,
        strikePct: strikePct,
        izPct: n > 0 ? iz / n : null,
        swStrRate: n > 0 ? wh / n : null,
        swStrPct: sw > 0 ? wh / sw : null,
        cswPct: n > 0 ? csw / n : null,
        izWhiffPct: izSw > 0 ? izWh / izSw : null,
        chasePct: ooz > 0 ? oozSw / ooz : null,
        gbPct: bip > 0 ? gb / bip : null,
        kPct: kPct,
        bbPct: bbPct,
        kbbPct: kbbPct,
        babip: babip,
        fpsPct: fpsPct,
        hrFbPct: hrFbPct,
        avgEVAgainst: avgEVAgainst,
        maxEVAgainst: maxEVAgainst,
        hardHitPct: hardHitPct_val,
        barrelPctAgainst: barrelPctAgainst,
        ldPct: ldPct_val,
        fbPct: fbPct_val,
        puPct: puPct_val,
      };

      // Apply baseball-context filters (comparison group — affects percentiles)
      if (filters.throws !== 'all' && obj.throws !== filters.throws) continue;
      if (obj.count < (filters.minCount || 1)) continue;
      if (filters.minTbf && (obj.pa || 0) < filters.minTbf) continue;
      if (filters.minBip && (obj.nBip || 0) < filters.minBip) continue;
      if (filters.minPitcherSwings && (obj.nSwings || 0) < filters.minPitcherSwings) continue;

      rows.push(obj);
    }

    // Merge boxscore stats (G, GS, IP, W, L, SV, HLD, TBF, ERA, HR/9, runValue)
    // from pre-aggregated PITCHER_DATA — these aren't in micro-data
    var boxFields = ['g', 'gs', 'ip', 'w', 'l', 'sv', 'hld', 'tbf', 'era', 'hr9', 'runValue', 'rv100',
                     'era_pctl', 'hr9_pctl', 'runValue_pctl', 'rv100_pctl', 'fip', 'fip_pctl', 'xFIP', 'xFIP_pctl', 'siera', 'siera_pctl',
                     'wOBA', 'wOBA_pctl', 'xBA', 'xBA_pctl', 'xSLG', 'xSLG_pctl', 'xwOBA', 'xwOBA_pctl',
                     'xwOBAcon', 'xwOBAcon_pctl',
                     'twoStrikeWhiffPct', 'twoStrikeWhiffPct_pctl',
                     'armAngle'];
    var preAgg = window.PITCHER_DATA || [];
    var preAggMap = {};
    for (var bi = 0; bi < preAgg.length; bi++) {
      preAggMap[preAgg[bi].pitcher + '|' + preAgg[bi].team] = preAgg[bi];
    }
    // Fields that have per-hand splits (stored as field_vsL / field_vsR in PITCHER_DATA)
    var handSplitFields = ['twoStrikeWhiffPct', 'fpsPct',
      'strikePct', 'izPct', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct',
      'kPct', 'bbPct', 'kbbPct', 'babip', 'gbPct',
      'avgEV', 'maxEV', 'hardHitPct', 'barrelPct',
      'gbPct_bb', 'ldPct', 'fbPct', 'puPct', 'hrFbPct', 'medEV',
      'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon'];
    var handSuffix = vsHand !== 'all' ? '_vs' + vsHand : '';
    for (var mi = 0; mi < rows.length; mi++) {
      var key2 = rows[mi].pitcher + '|' + rows[mi].team;
      var pre = preAggMap[key2];
      if (pre) {
        for (var fi = 0; fi < boxFields.length; fi++) {
          var bf = boxFields[fi];
          // If filtering by hand and this field has per-hand split, use it
          if (handSuffix && handSplitFields.indexOf(bf) >= 0) {
            var handKey = bf + handSuffix;
            if (pre[handKey] !== undefined) {
              rows[mi][bf] = pre[handKey];
              continue;
            }
          }
          if (pre[bf] !== undefined) rows[mi][bf] = pre[bf];
        }
      }
    }

    // Apply role filter AFTER boxscore merge so G/GS are available
    if (filters.role && filters.role !== 'all') {
      rows = rows.filter(function (r) {
        var pg = r.g || 0, pgs = r.gs || 0;
        var isSP = pg > 0 && (pgs / pg) > 0.5;
        if (filters.role === 'SP') return isSP;
        if (filters.role === 'RP') return !isSP;
        return true;
      });
    }
    if (filters.minIp) {
      rows = rows.filter(function (r) { return (r.ip || 0) >= filters.minIp; });
    }

    // Compute percentiles with IP-based qualifying
    // Starter (GS/G > 0.5): 1.0 IP/team game. Reliever: 0.1 IP/team game.
    var teamGames = this.getTeamGamesPlayed();
    // Mark each row as qualified or not
    for (var qi = 0; qi < rows.length; qi++) {
      var r = rows[qi];
      var tg = teamGames[r.team] || 0;
      var ipStr = r.ip;
      var ipFloat = 0;
      if (ipStr != null) {
        var ipp = String(ipStr).split('.');
        ipFloat = parseInt(ipp[0], 10) + (ipp[1] ? parseInt(ipp[1], 10) / 3 : 0);
      }
      var pg = r.g || 0, pgs = r.gs || 0;
      var isStarter = pg > 0 && (pgs / pg) > 0.5;
      r._qualified = ipFloat >= (isStarter ? tg * 1.0 : tg * 0.1);
    }
    // Set bipQual flag BEFORE percentiles so BIP stats can use it
    var BIP_STATS = { avgEVAgainst: true, maxEVAgainst: true, hardHitPct: true, barrelPctAgainst: true };
    for (var bqi = 0; bqi < rows.length; bqi++) {
      rows[bqi].bipQual = (rows[bqi].nBip || 0) >= 20;
    }
    // Use _qualified flag for percentile pool: only qualified pitchers get percentiles
    // BIP-dependent stats additionally require bipQual (≥20 BIP)
    for (var si = 0; si < STAT_KEYS.length; si++) {
      if (BIP_STATS[STAT_KEYS[si]]) {
        // Temporarily narrow _qualified to also require bipQual
        var savedQual = [];
        for (var sq = 0; sq < rows.length; sq++) {
          savedQual.push(rows[sq]._qualified);
          rows[sq]._qualified = rows[sq]._qualified && rows[sq].bipQual;
        }
        this._computePercentilesQualified(rows, STAT_KEYS[si]);
        // Restore original _qualified
        for (var rq = 0; rq < rows.length; rq++) {
          rows[rq]._qualified = savedQual[rq];
        }
      } else {
        this._computePercentilesQualified(rows, STAT_KEYS[si]);
      }
    }
    // Invert where lower is better
    for (var ri = 0; ri < rows.length; ri++) {
      for (var inv in INVERT) {
        var pk = inv + '_pctl';
        if (rows[ri][pk] !== null && rows[ri][pk] !== undefined) {
          rows[ri][pk] = 100 - rows[ri][pk];
        }
      }
    }

    // Apply view-narrowing filters AFTER percentiles (don't change comparison group)
    // Always exclude ROC from "All Teams" view
    var self = this;
    if (filters.team !== 'all') {
      rows = rows.filter(function (r) { return r.team === filters.team; });
    } else {
      rows = rows.filter(function (r) { return !self._isROCTeam(r.team); });
    }
    if (filters.search) {
      var searchLower = filters.search.toLowerCase();
      rows = rows.filter(function (r) { return r.pitcher.toLowerCase().indexOf(searchLower) !== -1; });
    }

    return rows;
  },

  // ==================================================================
  //  Pitch aggregation
  // ==================================================================
  _aggregatePitch: function (filters) {
    var d = this.data;
    var ci = this._colIdx.pitchCols;
    var micro = d.pitchMicro;
    var lookups = d.lookups;
    var validDates = this._getValidDateSet(filters);
    var vsHand = filters.vsHand || 'all';
    var mlbIdMap = this._getMlbIdMap('pitcher');

    var METRIC_MAP = [
      { key: 'velocity', sum: 'sumVelo', cnt: 'nVelo', round: 1 },
      { key: 'spinRate', sum: 'sumSpin', cnt: 'nSpin', round: 0 },
      { key: 'indVertBrk', sum: 'sumIVB', cnt: 'nIVB', round: 1 },
      { key: 'horzBrk', sum: 'sumHB', cnt: 'nHB', round: 1 },
      { key: 'relPosZ', sum: 'sumRelZ', cnt: 'nRelZ', round: 1 },
      { key: 'relPosX', sum: 'sumRelX', cnt: 'nRelX', round: 1 },
      { key: 'extension', sum: 'sumExt', cnt: 'nExt', round: 1 },
      { key: 'armAngle', sum: 'sumArmAngle', cnt: 'nArmAngle', round: 1 },
      { key: 'vaa', sum: 'sumVAA', cnt: 'nVAA', round: 2 },
      { key: 'haa', sum: 'sumHAA', cnt: 'nHAA', round: 2 },
      { key: '_plateZ', sum: 'sumPlateZ', cnt: 'nPlateZ', round: 2 },
      { key: '_plateX', sum: 'sumPlateX', cnt: 'nPlateX', round: 2 },
    ];
    var METRIC_KEYS_LIST = METRIC_MAP.map(function (m) { return m.key; }).filter(function (k) { return k !== '_plateZ' && k !== '_plateX'; });
    var NO_PCTL_METRICS = { relPosZ: true, relPosX: true, extension: true, armAngle: true };
    var METRIC_PCTL_KEYS = METRIC_KEYS_LIST.filter(function (k) { return !NO_PCTL_METRICS[k]; });
    var PITCH_STAT_KEYS = ['izPct', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'fpsPct'];
    var PITCH_BB_KEYS = ['avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'hrFbPct'];
    var PITCH_BB_INVERT = { avgEVAgainst: true, maxEVAgainst: true, hardHitPct: true, barrelPctAgainst: true, hrFbPct: true };
    var PITCH_EXPECTED_KEYS = ['wOBA', 'xBA', 'xSLG', 'xwOBA'];
    var PITCH_EXPECTED_INVERT = { wOBA: true, xBA: true, xSLG: true, xwOBA: true };
    var PITCH_PCTL_KEYS = METRIC_PCTL_KEYS.concat(['nVAA', 'nHAA']).concat(PITCH_STAT_KEYS).concat(PITCH_BB_KEYS).concat(PITCH_EXPECTED_KEYS);

    // Group by (pitcherIdx, teamIdx, pitchTypeIdx)
    var groups = {};
    var pitcherTotals = {};

    for (var i = 0; i < micro.length; i++) {
      var row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.batterHand] !== vsHand) continue;

      var pitcherKey = row[ci.pitcherIdx] + '|' + row[ci.teamIdx];
      var gk = pitcherKey + '|' + row[ci.pitchTypeIdx];

      pitcherTotals[pitcherKey] = (pitcherTotals[pitcherKey] || 0) + row[ci.n];

      if (!groups[gk]) {
        groups[gk] = {
          pitcherIdx: row[ci.pitcherIdx],
          teamIdx: row[ci.teamIdx],
          throws: row[ci.throws],
          pitchTypeIdx: row[ci.pitchTypeIdx],
          counts: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
          metricSums: {}
        };
        METRIC_MAP.forEach(function (m) {
          groups[gk].metricSums[m.sum] = 0;
          groups[gk].metricSums[m.cnt] = 0;
        });
        groups[gk].metricSums.sumTiltSin = 0;
        groups[gk].metricSums.sumTiltCos = 0;
        groups[gk].metricSums.nTilt = 0;
      }

      var g = groups[gk];
      for (var f = 0; f < 22; f++) {
        g.counts[f] += row[ci.n + f];
      }
      METRIC_MAP.forEach(function (m) {
        g.metricSums[m.sum] += row[ci[m.sum]];
        g.metricSums[m.cnt] += row[ci[m.cnt]];
      });
      g.metricSums.sumTiltSin += row[ci.sumTiltSin];
      g.metricSums.sumTiltCos += row[ci.sumTiltCos];
      g.metricSums.nTilt += row[ci.nTilt];
    }

    // Convert to row objects
    var rows = [];
    for (var gk2 in groups) {
      var g = groups[gk2];
      var c = g.counts;
      var ms = g.metricSums;
      var n = c[0], iz = c[1], sw = c[2], wh = c[3], csw = c[4];
      var ooz = c[5], oozSw = c[6], bip = c[7], gb = c[8];
      var pa = c[9], h = c[10], hr = c[11], k = c[12], bb = c[13];
      var hbp = c[14], sf = c[15], sh = c[16], ci_val = c[17];
      var izSw = c[18], izWh = c[19];
      var firstPitches = c[20], firstPitchStrikes = c[21];
      var ab = pa - bb - hbp - sf - sh - ci_val;
      var pitcherKey = g.pitcherIdx + '|' + g.teamIdx;
      var pitcherTotal = pitcherTotals[pitcherKey] || 0;

      var kPct = pa > 0 ? k / pa : null;
      var bbPct = pa > 0 ? bb / pa : null;
      var kbbPct = (kPct !== null && bbPct !== null) ? Math.round((kPct - bbPct) * 10000) / 10000 : null;
      var babip_denom = ab - k - hr + sf;
      var babip_val = babip_denom > 0 ? Math.round((h - hr) / babip_denom * 1000) / 1000 : null;
      var fpsPct_val = firstPitches > 0 ? firstPitchStrikes / firstPitches : null;

      var pitcherName2 = lookups.pitchers[g.pitcherIdx];
      var teamName2 = lookups.teams[g.teamIdx];
      var obj = {
        pitcher: pitcherName2,
        team: teamName2,
        mlbId: mlbIdMap[pitcherName2 + '|' + teamName2] || null,
        throws: g.throws,
        pitchType: lookups.pitchTypes[g.pitchTypeIdx],
        count: n,
        nBip: bip,
        usagePct: pitcherTotal > 0 ? Math.round(n / pitcherTotal * 10000) / 10000 : null,
        pa: pa,
        izPct: n > 0 ? iz / n : null,
        swStrRate: n > 0 ? wh / n : null,
        swStrPct: sw > 0 ? wh / sw : null,
        cswPct: n > 0 ? csw / n : null,
        izWhiffPct: izSw > 0 ? izWh / izSw : null,
        chasePct: ooz > 0 ? oozSw / ooz : null,
        gbPct: bip > 0 ? gb / bip : null,
        kPct: kPct,
        bbPct: bbPct,
        kbbPct: kbbPct,
        babip: babip_val,
        fpsPct: fpsPct_val,
      };

      // Metric averages
      METRIC_MAP.forEach(function (m) {
        var cnt = ms[m.cnt];
        if (cnt > 0) {
          obj[m.key] = Number((ms[m.sum] / cnt).toFixed(m.round));
        } else {
          obj[m.key] = null;
        }
      });

      // Normalized VAA (location-independent):
      // nVAA = VAA - slope * (pitcher_avgPlateZ - league_avgPlateZ)
      // Adjusts VAA to what it would be at league-average pitch height
      var vaaReg = DataStore.metadata && DataStore.metadata.vaaRegression;
      if (obj.vaa !== null && obj._plateZ !== null && vaaReg && vaaReg.leagueAvgPlateZ != null) {
        obj.nVAA = Number((obj.vaa - vaaReg.slope * (obj._plateZ - vaaReg.leagueAvgPlateZ)).toFixed(2));
      } else {
        obj.nVAA = null;
      }
      // Normalized HAA (location-independent):
      // nHAA = HAA - slope * (pitcher_avgPlateX - league_avgPlateX)
      var haaReg = DataStore.metadata && DataStore.metadata.haaRegression;
      if (obj.haa !== null && obj._plateX !== null && haaReg && haaReg.leagueAvgPlateX != null) {
        obj.nHAA = Number((obj.haa - haaReg.slope * (obj._plateX - haaReg.leagueAvgPlateX)).toFixed(2));
      } else {
        obj.nHAA = null;
      }
      delete obj._plateZ;  // internal, not displayed
      delete obj._plateX;  // internal, not displayed

      // xIVB + IVBOE from arm angle regression (per pitch type)
      var ivbRegs = DataStore.metadata && DataStore.metadata.ivbRegressions;
      var ivbReg = ivbRegs && ivbRegs[obj.pitchType];
      if (ivbReg && obj.armAngle !== null) {
        var expIVB = ivbReg.slope * obj.armAngle + ivbReg.intercept;
        obj.xIVB = Number(expIVB.toFixed(1));
        obj.ivbOE = obj.indVertBrk !== null ? Number((obj.indVertBrk - expIVB).toFixed(1)) : null;
      } else {
        obj.xIVB = null;
        obj.ivbOE = null;
      }
      // xHB + HBOE from arm angle regression (handedness-keyed, e.g. "FF_R")
      var hbRegs = DataStore.metadata && DataStore.metadata.hbRegressions;
      var hbReg = hbRegs && hbRegs[obj.pitchType + '_' + obj.throws];
      if (hbReg && obj.armAngle !== null) {
        var expHB = hbReg.slope * obj.armAngle + hbReg.intercept;
        obj.xHB = Number(expHB.toFixed(1));
        obj.hbOE = obj.horzBrk !== null ? Number((obj.horzBrk - expHB).toFixed(1)) : null;
      } else {
        obj.xHB = null;
        obj.hbOE = null;
      }

      // Break Tilt (circular mean)
      if (ms.nTilt > 0) {
        var sinAvg = ms.sumTiltSin / ms.nTilt;
        var cosAvg = ms.sumTiltCos / ms.nTilt;
        var avgAngle = Math.atan2(sinAvg, cosAvg);
        if (avgAngle < 0) avgAngle += 2 * Math.PI;
        var avgMinutes = Math.round(avgAngle / (2 * Math.PI) * 720);
        var thh = Math.floor(avgMinutes / 60);
        var tmm = avgMinutes % 60;
        if (thh === 0) thh = 12;
        obj.breakTilt = thh + ':' + (tmm < 10 ? '0' : '') + tmm;
        obj.breakTiltMinutes = avgMinutes;
      } else {
        obj.breakTilt = null;
        obj.breakTiltMinutes = null;
      }

      // Apply baseball-context filters (comparison group — affects percentiles)
      if (filters.throws !== 'all' && obj.throws !== filters.throws) continue;
      if (filters.role && filters.role !== 'all') {
        // Pitch rows don't have G/GS — look up from pitcher leaderboard
        var pitcherKey2 = obj.pitcher + '|' + obj.team;
        if (!this._roleCache) this._roleCache = {};
        if (!(pitcherKey2 in this._roleCache)) {
          var pd = window.PITCHER_DATA || [];
          for (var ri3 = 0; ri3 < pd.length; ri3++) {
            if (pd[ri3].pitcher === obj.pitcher && pd[ri3].team === obj.team) {
              var pg2 = pd[ri3].g || 0, pgs2 = pd[ri3].gs || 0;
              this._roleCache[pitcherKey2] = pg2 > 0 && (pgs2 / pg2) > 0.5 ? 'SP' : 'RP';
              break;
            }
          }
          if (!(pitcherKey2 in this._roleCache)) this._roleCache[pitcherKey2] = 'RP';
        }
        if (this._roleCache[pitcherKey2] !== filters.role) continue;
      }
      if (filters.pitchTypes !== 'all' && filters.pitchTypes.indexOf(obj.pitchType) === -1) continue;
      if (obj.count < (filters.minCount || 1)) continue;

      rows.push(obj);
    }

    // Merge fields from pre-aggregated PITCH_DATA that aren't computed from micro counters
    var pitchPreAgg = window.PITCH_DATA || [];
    var pitchPreMap = {};
    for (var ppi = 0; ppi < pitchPreAgg.length; ppi++) {
      var ppk = pitchPreAgg[ppi].pitcher + '|' + pitchPreAgg[ppi].team + '|' + pitchPreAgg[ppi].pitchType;
      pitchPreMap[ppk] = pitchPreAgg[ppi];
    }
    for (var pmi = 0; pmi < rows.length; pmi++) {
      var pmk = rows[pmi].pitcher + '|' + rows[pmi].team + '|' + rows[pmi].pitchType;
      var ppre = pitchPreMap[pmk];
      if (ppre) {
        // Run value (always merge — not hand-dependent at pitch level)
        if (ppre.runValue !== undefined) rows[pmi].runValue = ppre.runValue;
        if (ppre.runValue_pctl !== undefined) rows[pmi].runValue_pctl = ppre.runValue_pctl;
        if (ppre.rv100 !== undefined) rows[pmi].rv100 = ppre.rv100;
        if (ppre.rv100_pctl !== undefined) rows[pmi].rv100_pctl = ppre.rv100_pctl;
        // Plate discipline fields not in micro counters
        if (ppre.strikePct !== undefined) rows[pmi].strikePct = ppre.strikePct;
        if (ppre.strikePct_pctl !== undefined) rows[pmi].strikePct_pctl = ppre.strikePct_pctl;
        if (ppre.nSwings !== undefined) rows[pmi].nSwings = ppre.nSwings;
        // Batted ball and expected stats: use per-hand values when hand filter active
        var handSfx = (vsHand === 'L') ? '_vsL' : (vsHand === 'R') ? '_vsR' : '';
        // Batted ball fields
        for (var bbfi = 0; bbfi < PITCH_BB_KEYS.length; bbfi++) {
          var bbf = PITCH_BB_KEYS[bbfi];
          var bbSrc = (handSfx && ppre[bbf + handSfx] !== undefined) ? bbf + handSfx : bbf;
          if (ppre[bbSrc] !== undefined) rows[pmi][bbf] = ppre[bbSrc];
        }
        // Expected stats
        var xKeys = ['wOBA', 'xBA', 'xSLG', 'xwOBA'];
        for (var xi = 0; xi < xKeys.length; xi++) {
          var xk = xKeys[xi];
          var xSrc = (handSfx && ppre[xk + handSfx] !== undefined) ? xk + handSfx : xk;
          if (ppre[xSrc] !== undefined) rows[pmi][xk] = ppre[xSrc];
          // Percentiles are only meaningful for overall (not per-hand)
          if (!handSfx && ppre[xk + '_pctl'] !== undefined) rows[pmi][xk + '_pctl'] = ppre[xk + '_pctl'];
        }
        // Max velo and tunnel distance
        if (ppre.maxVelo !== undefined) rows[pmi].maxVelo = ppre.maxVelo;
        if (ppre.tunnelDist !== undefined) rows[pmi].tunnelDist = ppre.tunnelDist;
      }
    }

    // Percentiles per pitch type
    var ptGroups = {};
    rows.forEach(function (r) {
      if (!ptGroups[r.pitchType]) ptGroups[r.pitchType] = [];
      ptGroups[r.pitchType].push(r);
    });

    var self = this;
    var MIN_PITCH_TYPE_PCTL = 50;  // minimum pitches for outcome metrics
    var ABS_PCTL_KEYS = { horzBrk: true, haa: true, nHAA: true };  // use |value| for RHP/LHP fairness
    // Shape metrics: physical measurements, no minimum needed
    var SHAPE_METRICS = { velocity: true, spinRate: true, indVertBrk: true, horzBrk: true, vaa: true, haa: true, nVAA: true, nHAA: true };
    // CF pairs with FF for velocity, spin rate, VAA, HAA percentiles
    var CF_FF_PAIRED = { velocity: true, spinRate: true, vaa: true, haa: true, nVAA: true, nHAA: true };
    PITCH_PCTL_KEYS.forEach(function (key) {
      var minPctl = SHAPE_METRICS[key] ? 0 : MIN_PITCH_TYPE_PCTL;
      if (CF_FF_PAIRED[key]) {
        // Combined FF+CF pool
        var ffCfRows = (ptGroups['FF'] || []).concat(ptGroups['CF'] || []);
        if (ffCfRows.length) {
          self._computePercentiles(ffCfRows, key, minPctl, 'count', ABS_PCTL_KEYS[key] || false);
        }
        // All other pitch types in their own pool
        for (var pt2 in ptGroups) {
          if (pt2 !== 'FF' && pt2 !== 'CF') {
            self._computePercentiles(ptGroups[pt2], key, minPctl, 'count', ABS_PCTL_KEYS[key] || false);
          }
        }
      } else {
        for (var pt in ptGroups) {
          self._computePercentiles(ptGroups[pt], key, minPctl, 'count', ABS_PCTL_KEYS[key] || false);
        }
      }
    });

    // --- Pitch-type-specific percentile inversions ---

    // IVB: FF/CF/FC = higher is better (default). SI/CU/CH/FS = lower is better (invert).
    // SL/ST/SV = IVB not meaningful, suppress percentile.
    var IVB_INVERT = { SI: true, CU: true, CH: true, FS: true };
    var IVB_SUPPRESS = { SL: true, ST: true, SV: true };
    for (var ptIVB in ptGroups) {
      if (IVB_INVERT[ptIVB]) {
        ptGroups[ptIVB].forEach(function (r) {
          if (r.indVertBrk_pctl !== null && r.indVertBrk_pctl !== undefined) {
            r.indVertBrk_pctl = 100 - r.indVertBrk_pctl;
          }
        });
      } else if (IVB_SUPPRESS[ptIVB]) {
        ptGroups[ptIVB].forEach(function (r) {
          r.indVertBrk_pctl = null;
        });
      }
    }

    // Spin: higher is better for all EXCEPT CH/FS where lower spin = better (invert)
    var SPIN_INVERT = { CH: true, FS: true };
    for (var ptSpin in ptGroups) {
      if (SPIN_INVERT[ptSpin]) {
        ptGroups[ptSpin].forEach(function (r) {
          if (r.spinRate_pctl !== null && r.spinRate_pctl !== undefined) {
            r.spinRate_pctl = 100 - r.spinRate_pctl;
          }
        });
      }
    }

    // VAA/nVAA/nHAA: FF/FC/CF = closer to 0 is better (default higher = higher pctl, no inversion)
    // All others: further from 0 = better (invert)
    var VAA_NO_INVERT = { FF: true, FC: true, CF: true };
    for (var ptV in ptGroups) {
      if (!VAA_NO_INVERT[ptV]) {
        ptGroups[ptV].forEach(function (r) {
          if (r.vaa_pctl !== null && r.vaa_pctl !== undefined) {
            r.vaa_pctl = 100 - r.vaa_pctl;
          }
          if (r.nVAA_pctl !== null && r.nVAA_pctl !== undefined) {
            r.nVAA_pctl = 100 - r.nVAA_pctl;
          }
          if (r.nHAA_pctl !== null && r.nHAA_pctl !== undefined) {
            r.nHAA_pctl = 100 - r.nHAA_pctl;
          }
        });
      }
    }

    // HAA/nHAA: uses absolute values, so further from 0 = higher pctl by default
    // FF/CF/FC: closer to 0 = better, so invert for fastballs
    for (var ptH in ptGroups) {
      if (VAA_NO_INVERT[ptH]) {
        ptGroups[ptH].forEach(function (r) {
          if (r.haa_pctl !== null && r.haa_pctl !== undefined) {
            r.haa_pctl = 100 - r.haa_pctl;
          }
          if (r.nHAA_pctl !== null && r.nHAA_pctl !== undefined) {
            r.nHAA_pctl = 100 - r.nHAA_pctl;
          }
        });
      }
    }

    // Invert batted ball + expected stat percentiles where lower is better for pitchers
    for (var ptBB in ptGroups) {
      ptGroups[ptBB].forEach(function (r) {
        for (var bbInv in PITCH_BB_INVERT) {
          var bbPk = bbInv + '_pctl';
          if (r[bbPk] !== null && r[bbPk] !== undefined) {
            r[bbPk] = 100 - r[bbPk];
          }
        }
        for (var xInv in PITCH_EXPECTED_INVERT) {
          var xPk = xInv + '_pctl';
          if (r[xPk] !== null && r[xPk] !== undefined) {
            r[xPk] = 100 - r[xPk];
          }
        }
      });
    }

    // Apply view-narrowing filters AFTER percentiles (don't change comparison group)
    if (filters.team !== 'all') {
      rows = rows.filter(function (r) { return r.team === filters.team; });
    } else {
      rows = rows.filter(function (r) { return !self._isROCTeam(r.team); });
    }
    if (filters.search) {
      var searchLower2 = filters.search.toLowerCase();
      rows = rows.filter(function (r) { return r.pitcher.toLowerCase().indexOf(searchLower2) !== -1; });
    }

    return rows;
  },

  // ==================================================================
  //  Hitter aggregation
  // ==================================================================
  _aggregateHitter: function (filters) {
    var d = this.data;
    var ci = this._colIdx.hitterCols;
    var bci = this._colIdx.hitterBipCols;
    var micro = d.hitterMicro;
    var hitterMlbIdMap = this._getMlbIdMap('hitter');
    var bipData = d.hitterBip;
    var lookups = d.lookups;
    var validDates = this._getValidDateSet(filters);
    var vsHand = filters.vsHand || 'all';

    // Group by (hitterIdx, teamIdx)
    var groups = {};
    for (var i = 0; i < micro.length; i++) {
      var row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.pitcherHand] !== vsHand) continue;

      var gk = row[ci.hitterIdx] + '|' + row[ci.teamIdx];
      if (!groups[gk]) {
        groups[gk] = {
          hitterIdx: row[ci.hitterIdx],
          teamIdx: row[ci.teamIdx],
          batsSet: {},
          counts: new Array(37)
        };
        for (var z = 0; z < 37; z++) groups[gk].counts[z] = 0;
      }

      var g = groups[gk];
      g.batsSet[row[ci.bats]] = true;

      for (var f = 0; f < 37; f++) {
        g.counts[f] += row[5 + f];
      }
    }

    // Filter BIP records for medians
    var bipByHitter = {};
    for (var bi = 0; bi < bipData.length; bi++) {
      var brow = bipData[bi];
      if (!validDates[brow[bci.dateIdx]]) continue;
      if (vsHand !== 'all' && brow[bci.pitcherHand] !== vsHand) continue;

      var hIdx = brow[bci.hitterIdx];
      if (!bipByHitter[hIdx]) bipByHitter[hIdx] = [];
      bipByHitter[hIdx].push(brow);
    }

    function median(arr) {
      if (arr.length === 0) return null;
      arr.sort(function (a, b) { return a - b; });
      var mid = Math.floor(arr.length / 2);
      return arr.length % 2 === 1 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
    }

    var HITTER_STAT_KEYS = [
      'avg', 'obp', 'slg', 'ops', 'iso', 'wOBA', 'babip', 'kPct', 'bbPct',
      'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp',
      'avgEVAll', 'medEV', 'ev75', 'maxEV', 'hardHitPct', 'barrelPct', 'laSweetSpotPct', 'sacqPct',
      'gbPct', 'hrFbPct',
      'airPullPct',
      'swingPct', 'izSwingPct', 'chasePct', 'izSwChase', 'contactPct', 'izContactPct', 'whiffPct',
      'batSpeed', 'swingLength',
      'wRCplus', 'xWRCplus',
    ];
    var HITTER_INVERT = {
      swingPct: true, chasePct: true, whiffPct: true, gbPct: true, kPct: true, puPct: true, twoStrikeWhiffPct: true
    };

    var rows = [];
    for (var gk2 in groups) {
      var g = groups[gk2];
      var c = g.counts;
      var batsKeys = Object.keys(g.batsSet);
      var stands = batsKeys.length > 1 ? 'S' : (batsKeys[0] || null);

      var n_total = c[0], pa = c[1], h = c[2], db = c[3], tp = c[4], hr = c[5];
      var bb = c[6], hbp = c[7], sf = c[8], sh = c[9], ci_v = c[10], k = c[11];
      var swings = c[12], whiffs = c[13];
      var izPitches = c[14], oozPitches = c[15];
      var izSwings = c[16], oozSwings = c[17], contact = c[18];
      var izSwNonBunt = c[19], izContact = c[20];
      var bip = c[21], gb_c = c[22], ld = c[23], fb = c[24], pu = c[25];
      var barrels = c[26], nSpray = c[27], pull = c[28], center = c[29], oppo = c[30], airPull = c[31];
      var hardHit = c[32], laSweetSpot = c[33], nLaValid = c[34], nHrBip = c[35], ldHr = c[36];

      var ab = pa - bb - hbp - sf - sh - ci_v;
      var singles = h - db - tp - hr;
      var tb_val = singles + 2 * db + 3 * tp + 4 * hr;
      var xbh = db + tp + hr;

      var batting_avg = ab > 0 ? Math.round(h / ab * 1000) / 1000 : null;
      var obp_denom = ab + bb + hbp + sf;
      var obp_val = obp_denom > 0 ? Math.round((h + bb + hbp) / obp_denom * 1000) / 1000 : null;
      var slg_val = ab > 0 ? Math.round(tb_val / ab * 1000) / 1000 : null;
      var ops_val = (obp_val !== null && slg_val !== null) ? Math.round((obp_val + slg_val) * 1000) / 1000 : null;
      var iso_val = (slg_val !== null && batting_avg !== null) ? Math.round((slg_val - batting_avg) * 1000) / 1000 : null;
      var babip_denom = ab - k - hr + sf;
      var babip_val = babip_denom > 0 ? Math.round((h - hr) / babip_denom * 1000) / 1000 : null;

      var kPct = pa > 0 ? k / pa : null;
      var bbPct = pa > 0 ? bb / pa : null;
      var izSwingPct = izPitches > 0 ? izSwings / izPitches : null;
      var chasePct_val = oozPitches > 0 ? oozSwings / oozPitches : null;
      var izSwChase = (izSwingPct !== null && chasePct_val !== null)
        ? Math.round((izSwingPct - chasePct_val) * 10000) / 10000 : null;
      var contactPct = swings > 0 ? contact / swings : null;
      var izContactPct = izSwNonBunt > 0 ? izContact / izSwNonBunt : null;
      var hardHitPct = bip > 0 ? hardHit / bip : null;
      var laSweetSpotPct = nLaValid > 0 ? laSweetSpot / nLaValid : null;
      var fb_for_hrfb = fb + pu + ldHr;
      var hrFbPct_val = fb_for_hrfb > 0 ? nHrBip / fb_for_hrfb : null;

      // BIP medians
      var bipRecords = bipByHitter[g.hitterIdx] || [];
      var evsAll = [], evsPos = [], allLA = [];
      for (var bri = 0; bri < bipRecords.length; bri++) {
        var bev = bipRecords[bri][bci.exitVelo];
        var bla = bipRecords[bri][bci.launchAngle];
        if (bev !== null) evsAll.push(bev);
        if (bla !== null && bla > 0 && bev !== null) evsPos.push(bev);
        if (bla !== null) allLA.push(bla);
      }

      var avgEVAll = evsAll.length > 0 ? Math.round(evsAll.reduce(function(a,b){return a+b;},0) / evsAll.length * 10) / 10 : null;
      var medEV = evsPos.length > 0 ? Math.round(evsPos.reduce(function(a,b){return a+b;},0) / evsPos.length * 10) / 10 : null;
      var maxEV = evsPos.length > 0 ? Math.round(Math.max.apply(null, evsPos) * 10) / 10 : null;
      var medLA = allLA.length > 0 ? Math.round(median(allLA.slice()) * 10) / 10 : null;

      // EV75: average of top 25% hardest-hit balls
      var ev75 = null;
      if (evsPos.length > 0) {
        var sorted = evsPos.slice().sort(function (a, b) { return b - a; });
        var topQuarter = sorted.slice(0, Math.max(1, Math.floor(sorted.length / 4)));
        ev75 = Math.round(topQuarter.reduce(function (s, v) { return s + v; }, 0) / topQuarter.length * 10) / 10;
      }

      // SACQ% — compute from BIP records using zone table
      var sacqPct_val = null;
      var sacqZones = (window.METADATA && window.METADATA.sacqZones) || [];
      if (sacqZones.length > 0 && bipRecords.length > 0) {
        var sacqZoneMap = {};
        for (var szi = 0; szi < sacqZones.length; szi++) {
          var sz = sacqZones[szi];
          sacqZoneMap[sz.spray + '|' + sz.laBin] = sz;
        }
        var sacqQuality = 0, sacqEligible = 0;
        var xwOBAsp_sum = 0, xwOBAsp_count = 0;
        for (var sri = 0; sri < bipRecords.length; sri++) {
          var sla = bipRecords[sri][bci.launchAngle];
          var shcX = bipRecords[sri][bci.hcX];
          var shcY = bipRecords[sri][bci.hcY];
          if (sla == null || shcX == null || shcY == null) continue;
          var sAngle = Aggregator.computeSprayAngle(shcX, shcY);
          var sDir = Aggregator.sprayDirection(sAngle, stands);
          if (!sDir) continue;
          var sLaBin = Aggregator.getLABinIdx(sla);
          if (sLaBin == null) continue;
          var szInfo = sacqZoneMap[sDir + '|' + sLaBin];
          if (szInfo && szInfo.count >= 20 && szInfo.woba != null) {
            sacqEligible++;
            if (szInfo.quality) sacqQuality++;
            xwOBAsp_sum += szInfo.woba;
            xwOBAsp_count++;
          }
        }
        sacqPct_val = sacqEligible > 0 ? sacqQuality / sacqEligible : null;
        var xwOBAsp_val = xwOBAsp_count > 0 ? xwOBAsp_sum / xwOBAsp_count : null;
      }

      var hitterName = lookups.hitters[g.hitterIdx];
      var hitterTeam = lookups.teams[g.teamIdx];
      var obj = {
        hitter: hitterName,
        team: hitterTeam,
        mlbId: hitterMlbIdMap[hitterName + '|' + hitterTeam] || null,
        stands: stands,
        count: n_total,
        pa: pa,
        ab: ab,
        nSwings: swings,
        nBip: bip,
        avg: batting_avg,
        obp: obp_val,
        slg: slg_val,
        ops: ops_val,
        doubles: db,
        triples: tp,
        hr: hr,
        xbh: xbh,
        kPct: kPct,
        bbPct: bbPct,
        iso: iso_val,
        babip: babip_val,
        avgEVAll: avgEVAll,
        medEV: medEV,
        ev75: ev75,
        maxEV: maxEV,
        medLA: medLA,
        hardHitPct: hardHitPct,
        barrelPct: bip > 0 ? barrels / bip : null,
        laSweetSpotPct: laSweetSpotPct,
        sacqPct: sacqPct_val,
        xwOBAsp: xwOBAsp_val,
        gbPct: bip > 0 ? gb_c / bip : null,
        ldPct: bip > 0 ? ld / bip : null,
        fbPct: bip > 0 ? fb / bip : null,
        puPct: bip > 0 ? pu / bip : null,
        hrFbPct: hrFbPct_val,
        pullPct: nSpray > 0 ? pull / nSpray : null,
        middlePct: nSpray > 0 ? center / nSpray : null,
        oppoPct: nSpray > 0 ? oppo / nSpray : null,
        airPullPct: nSpray > 0 ? airPull / nSpray : null,
        swingPct: n_total > 0 ? swings / n_total : null,
        izSwingPct: izSwingPct,
        chasePct: chasePct_val,
        izSwChase: izSwChase,
        contactPct: contactPct,
        izContactPct: izContactPct,
        whiffPct: swings > 0 ? whiffs / swings : null,
      };

      // Apply baseball-context filters (comparison group — affects percentiles)
      if (filters.throws !== 'all' && obj.stands !== filters.throws) continue;
      if ((obj.pa || 0) < (filters.minCount || 1)) continue;
      if (filters.minSwings && obj.nSwings < filters.minSwings) continue;
      if (filters.minBip && (obj.nBip || 0) < filters.minBip) continue;

      rows.push(obj);
    }

    // Merge boxscore stats from pre-aggregated HITTER_DATA
    // Includes batting stats recomputed from boxscore (fixes IBB not in pitch data)
    var hBoxFields = ['g', 'tb', 'sb', 'cs', 'sbPct', 'runValue',
                      'avg', 'obp', 'slg', 'ops', 'iso', 'babip', 'kPct', 'bbPct',
                      'doubles', 'triples', 'hr', 'xbh',
                      'batSpeed', 'swingLength', 'attackAngle', 'attackDirection', 'swingPathTilt', 'nCompSwings',
                      'wOBA', 'wOBA_pctl', 'xBA', 'xBA_pctl', 'xSLG', 'xSLG_pctl', 'xwOBA', 'xwOBA_pctl',
                      'xwOBAcon', 'xwOBAcon_pctl',
                      'twoStrikeWhiffPct', 'twoStrikeWhiffPct_pctl',
                      'firstPitchSwingPct', 'firstPitchSwingPct_pctl',
                      'avgFbDist', 'avgHrDist',
                      'squaredUpPct', 'squaredUpPct_pctl',
                      'sprintSpeed', 'sprintSpeed_pctl',
                      'wRC', 'wRCplus', 'xWRCplus'];
    var hPreAgg = window.HITTER_DATA || [];
    var hPreAggMap = {};
    for (var hbi = 0; hbi < hPreAgg.length; hbi++) {
      hPreAggMap[hPreAgg[hbi].hitter + '|' + hPreAgg[hbi].team] = hPreAgg[hbi];
    }
    for (var hmi = 0; hmi < rows.length; hmi++) {
      var hKey = rows[hmi].hitter + '|' + rows[hmi].team;
      var hPre = hPreAggMap[hKey];
      if (hPre) {
        for (var hfi = 0; hfi < hBoxFields.length; hfi++) {
          var hbf = hBoxFields[hfi];
          if (hPre[hbf] !== undefined) rows[hmi][hbf] = hPre[hbf];
        }
        // Also override PA and AB with boxscore values
        if (hPre.pa !== undefined) rows[hmi].pa = hPre.pa;
        if (hPre.ab !== undefined) rows[hmi].ab = hPre.ab;
      }
    }

    // Compute percentiles — BIP-dependent stats require min 20 BIP
    var self = this;
    var HITTER_BIP_PCTL = {
      avg: true, obp: true, slg: true, ops: true, iso: true, wOBA: true, babip: true,
      xBA: true, xSLG: true, xwOBA: true, xwOBAcon: true, xwOBAsp: true,
      avgEVAll: true, medEV: true, ev75: true, maxEV: true,
      hardHitPct: true, barrelPct: true, laSweetSpotPct: true, sacqPct: true,
      hrFbPct: true, airPullPct: true
    };
    HITTER_STAT_KEYS.forEach(function (key) {
      if (HITTER_BIP_PCTL[key]) {
        self._computePercentiles(rows, key, 20, 'nBip');
      } else {
        self._computePercentiles(rows, key);
      }
    });

    // Set bipQual flag for each hitter
    for (var bqi = 0; bqi < rows.length; bqi++) {
      rows[bqi].bipQual = (rows[bqi].nBip || 0) >= 20;
    }

    // Invert where lower is better
    for (var ri2 = 0; ri2 < rows.length; ri2++) {
      for (var inv2 in HITTER_INVERT) {
        var pk2 = inv2 + '_pctl';
        if (rows[ri2][pk2] !== null && rows[ri2][pk2] !== undefined) {
          rows[ri2][pk2] = 100 - rows[ri2][pk2];
        }
      }
    }

    // Apply view-narrowing filters AFTER percentiles (don't change comparison group)
    var self3 = this;
    if (filters.team !== 'all') {
      rows = rows.filter(function (r) { return r.team === filters.team; });
    } else {
      rows = rows.filter(function (r) { return !self3._isROCTeam(r.team); });
    }
    if (filters.search) {
      var searchLower = filters.search.toLowerCase();
      rows = rows.filter(function (r) { return r.hitter.toLowerCase().indexOf(searchLower) !== -1; });
    }

    return rows;
  },

  // Category definitions for hitter pitch type grouping
  PITCH_CATEGORIES: {
    'Hard': ['FF', 'SI', 'CF'],
    'Breaking': ['FC', 'SL', 'ST', 'CU', 'SV'],
    'Offspeed': ['CH', 'FS', 'KN']
  },

  _aggregateHitterPitch: function (filters) {
    var d = this.data;
    var ci = this._colIdx.hitterPitchCols;
    var bci = this._colIdx.hitterPitchBipCols;
    var micro = d.hitterPitchMicro;
    var hpMlbIdMap = this._getMlbIdMap('hitter');
    var bipData = d.hitterPitchBip;
    var lookups = d.lookups;
    var validDates = this._getValidDateSet(filters);
    var vsHand = filters.vsHand || 'all';

    if (!micro || !ci) return [];

    var selectedPitchTypes = filters.pitchTypes; // array or 'all'
    var CATS = this.PITCH_CATEGORIES;

    // Build reverse lookup: pitch type name -> set of pitchTypeIdx values
    var ptNameToIdx = {};
    for (var pi = 0; pi < lookups.pitchTypes.length; pi++) {
      ptNameToIdx[lookups.pitchTypes[pi]] = pi;
    }

    // Build category -> set of pitchTypeIdx
    var catIdxSets = {};
    for (var catName in CATS) {
      catIdxSets[catName] = {};
      for (var ci2 = 0; ci2 < CATS[catName].length; ci2++) {
        var idx = ptNameToIdx[CATS[catName][ci2]];
        if (idx !== undefined) catIdxSets[catName][idx] = true;
      }
    }

    // Determine which output groups we need
    // Each selected chip becomes an output group with its own grouping logic
    var outputGroups = []; // { name, type: 'all'|'category'|'individual', idxSet }
    if (selectedPitchTypes === 'all') {
      // Default: show all individual pitch types
      outputGroups.push({ name: 'all_individual', type: 'all_individual' });
    } else {
      for (var si = 0; si < selectedPitchTypes.length; si++) {
        var sel = selectedPitchTypes[si];
        if (sel === 'All') {
          outputGroups.push({ name: 'All', type: 'all' });
        } else if (CATS[sel]) {
          outputGroups.push({ name: sel, type: 'category', idxSet: catIdxSets[sel] });
        } else {
          outputGroups.push({ name: sel, type: 'individual', idx: ptNameToIdx[sel] });
        }
      }
    }

    // First pass: accumulate per-hitter-team-pitchType micro rows
    // and track hitter totals
    var perPT = {}; // hitterIdx|teamIdx|pitchTypeIdx -> { counts, batsSet }
    var hitterTotals = {};

    for (var i = 0; i < micro.length; i++) {
      var row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.pitcherHand] !== vsHand) continue;

      var hk = row[ci.hitterIdx] + '|' + row[ci.teamIdx];
      if (!hitterTotals[hk]) hitterTotals[hk] = { total: 0, batsSet: {} };
      hitterTotals[hk].total += row[6];
      hitterTotals[hk].batsSet[row[ci.bats]] = true;

      var gk = row[ci.hitterIdx] + '|' + row[ci.teamIdx] + '|' + row[ci.pitchTypeIdx];
      if (!perPT[gk]) {
        perPT[gk] = {
          hitterIdx: row[ci.hitterIdx],
          teamIdx: row[ci.teamIdx],
          pitchTypeIdx: row[ci.pitchTypeIdx],
          counts: new Array(37)
        };
        for (var z = 0; z < 37; z++) perPT[gk].counts[z] = 0;
      }
      for (var f = 0; f < 37; f++) {
        perPT[gk].counts[f] += row[6 + f];
      }
    }

    // BIP records by hitter+pitchTypeIdx
    var bipByKey = {};
    if (bipData && bci) {
      for (var bi = 0; bi < bipData.length; bi++) {
        var brow = bipData[bi];
        if (!validDates[brow[bci.dateIdx]]) continue;
        if (vsHand !== 'all' && brow[bci.pitcherHand] !== vsHand) continue;

        var bipKey = brow[bci.hitterIdx] + '|' + brow[bci.pitchTypeIdx];
        if (!bipByKey[bipKey]) bipByKey[bipKey] = [];
        bipByKey[bipKey].push(brow);
      }
    }

    function median(arr) {
      if (arr.length === 0) return null;
      arr.sort(function (a, b) { return a - b; });
      var mid = Math.floor(arr.length / 2);
      return arr.length % 2 === 1 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
    }

    // Second pass: build output rows per output group
    // For 'all' and 'category', we combine multiple perPT entries per hitter
    var groups = {}; // outputGroupName|hitterIdx|teamIdx -> combined counts + bipRecords

    for (var gk2 in perPT) {
      var entry = perPT[gk2];
      var ptIdx = entry.pitchTypeIdx;
      var ptName = lookups.pitchTypes[ptIdx];

      for (var oi = 0; oi < outputGroups.length; oi++) {
        var og = outputGroups[oi];
        var match = false;

        if (og.type === 'all') {
          match = true;
        } else if (og.type === 'category') {
          match = !!og.idxSet[ptIdx];
        } else if (og.type === 'individual') {
          match = (ptIdx === og.idx);
        } else if (og.type === 'all_individual') {
          // For 'all_individual', each pitch type becomes its own output row
          // handled differently below
          match = false;
        }

        if (match) {
          var outKey = og.name + '|' + entry.hitterIdx + '|' + entry.teamIdx;
          if (!groups[outKey]) {
            groups[outKey] = {
              hitterIdx: entry.hitterIdx,
              teamIdx: entry.teamIdx,
              outputName: og.name,
              counts: new Array(37),
              bipPtIdxs: []
            };
            for (var z2 = 0; z2 < 37; z2++) groups[outKey].counts[z2] = 0;
          }
          var gg = groups[outKey];
          for (var f2 = 0; f2 < 37; f2++) {
            gg.counts[f2] += entry.counts[f2];
          }
          if (gg.bipPtIdxs.indexOf(ptIdx) === -1) gg.bipPtIdxs.push(ptIdx);
        }
      }

      // Handle all_individual: each perPT entry is its own output row
      if (outputGroups.length === 1 && outputGroups[0].type === 'all_individual') {
        var outKey2 = ptName + '|' + entry.hitterIdx + '|' + entry.teamIdx;
        if (!groups[outKey2]) {
          groups[outKey2] = {
            hitterIdx: entry.hitterIdx,
            teamIdx: entry.teamIdx,
            outputName: ptName,
            counts: new Array(37),
            bipPtIdxs: [ptIdx]
          };
          for (var z3 = 0; z3 < 37; z3++) groups[outKey2].counts[z3] = 0;
        }
        for (var f3 = 0; f3 < 37; f3++) {
          groups[outKey2].counts[f3] += entry.counts[f3];
        }
      }
    }

    var HITTER_PITCH_PCTL_KEYS = [
      'avg', 'slg', 'iso', 'wOBA',
      'xBA', 'xSLG', 'xwOBA',
      'medEV', 'ev75', 'maxEV', 'hardHitPct', 'barrelPct', 'laSweetSpotPct',
      'hrFbPct',
      'airPullPct',
      'swingPct', 'izSwingPct', 'chasePct', 'contactPct', 'izContactPct', 'whiffPct',
    ];
    var HITTER_PITCH_INVERT = {
      swingPct: true, chasePct: true, whiffPct: true
    };

    var rows = [];

    for (var gk3 in groups) {
      var gg2 = groups[gk3];
      var c = gg2.counts;
      var hk2 = gg2.hitterIdx + '|' + gg2.teamIdx;
      var ht = hitterTotals[hk2];
      var hTotal = ht ? ht.total : 1;
      var batsKeys = ht ? Object.keys(ht.batsSet) : [];
      var stands = batsKeys.length > 1 ? 'S' : (batsKeys[0] || null);

      var n_total = c[0], pa = c[1], h = c[2], db = c[3], tp = c[4], hr = c[5];
      var bb = c[6], hbp = c[7], sf = c[8], sh = c[9], ci_v = c[10], k = c[11];
      var swings = c[12], whiffs = c[13];
      var izPitches = c[14], oozPitches = c[15];
      var izSwings = c[16], oozSwings = c[17], contact = c[18];
      var izSwNonBunt = c[19], izContact = c[20];
      var bip = c[21], gb_c = c[22], ld = c[23], fb = c[24], pu = c[25];
      var barrels = c[26], nSpray = c[27], pull = c[28], center = c[29], oppo = c[30], airPull = c[31];
      var hardHit = c[32], laSweetSpot = c[33], nLaValid = c[34], nHrBip = c[35], ldHr = c[36];

      var ab = pa - bb - hbp - sf - sh - ci_v;
      var singles = h - db - tp - hr;
      var tb_val = singles + 2 * db + 3 * tp + 4 * hr;

      var batting_avg = ab > 0 ? Math.round(h / ab * 1000) / 1000 : null;
      var slg_val = ab > 0 ? Math.round(tb_val / ab * 1000) / 1000 : null;
      var iso_val = (slg_val !== null && batting_avg !== null) ? Math.round((slg_val - batting_avg) * 1000) / 1000 : null;

      var izSwingPct = izPitches > 0 ? izSwings / izPitches : null;
      var chasePct_val = oozPitches > 0 ? oozSwings / oozPitches : null;
      var contactPct = swings > 0 ? contact / swings : null;
      var izContactPct = izSwNonBunt > 0 ? izContact / izSwNonBunt : null;
      var hardHitPct = bip > 0 ? hardHit / bip : null;
      var laSweetSpotPct = nLaValid > 0 ? laSweetSpot / nLaValid : null;
      var fb_for_hrfb = fb + pu + ldHr;
      var hrFbPct_val = fb_for_hrfb > 0 ? nHrBip / fb_for_hrfb : null;

      // BIP medians — combine BIP records from all pitch types in this group
      var evsAll2 = [], evsPos = [], allLA = [];
      for (var bpi = 0; bpi < gg2.bipPtIdxs.length; bpi++) {
        var bpKey = gg2.hitterIdx + '|' + gg2.bipPtIdxs[bpi];
        var bipRecords = bipByKey[bpKey] || [];
        for (var bri = 0; bri < bipRecords.length; bri++) {
          var bev = bipRecords[bri][bci.exitVelo];
          var bla = bipRecords[bri][bci.launchAngle];
          if (bev !== null) evsAll2.push(bev);
          if (bla !== null && bla > 0 && bev !== null) evsPos.push(bev);
          if (bla !== null) allLA.push(bla);
        }
      }

      var avgEVAll2 = evsAll2.length > 0 ? Math.round(evsAll2.reduce(function(a,b){return a+b;},0) / evsAll2.length * 10) / 10 : null;
      var medEV = evsPos.length > 0 ? Math.round(evsPos.reduce(function(a,b){return a+b;},0) / evsPos.length * 10) / 10 : null;
      var maxEV = evsPos.length > 0 ? Math.round(Math.max.apply(null, evsPos) * 10) / 10 : null;
      var medLA = allLA.length > 0 ? Math.round(median(allLA.slice()) * 10) / 10 : null;

      // EV75: average of top 25% hardest-hit balls
      var ev75 = null;
      if (evsPos.length > 0) {
        var sorted = evsPos.slice().sort(function (a, b) { return b - a; });
        var topQuarter = sorted.slice(0, Math.max(1, Math.floor(sorted.length / 4)));
        ev75 = Math.round(topQuarter.reduce(function (s, v) { return s + v; }, 0) / topQuarter.length * 10) / 10;
      }

      var hpName = lookups.hitters[gg2.hitterIdx];
      var hpTeam = lookups.teams[gg2.teamIdx];
      var obj = {
        hitter: hpName,
        team: hpTeam,
        mlbId: hpMlbIdMap[hpName + '|' + hpTeam] || null,
        stands: stands,
        pitchType: gg2.outputName,
        count: n_total,
        seenPct: Math.round(n_total / hTotal * 10000) / 10000,
        pa: pa,
        nSwings: swings,
        nBip: bip,
        avg: batting_avg,
        slg: slg_val,
        iso: iso_val,
        avgEVAll: avgEVAll2,
        medEV: medEV,
        ev75: ev75,
        maxEV: maxEV,
        medLA: medLA,
        hardHitPct: hardHitPct,
        barrelPct: bip > 0 ? barrels / bip : null,
        laSweetSpotPct: laSweetSpotPct,
        gbPct: bip > 0 ? gb_c / bip : null,
        ldPct: bip > 0 ? ld / bip : null,
        fbPct: bip > 0 ? fb / bip : null,
        hrFbPct: hrFbPct_val,
        puPct: bip > 0 ? pu / bip : null,
        pullPct: nSpray > 0 ? pull / nSpray : null,
        middlePct: nSpray > 0 ? center / nSpray : null,
        oppoPct: nSpray > 0 ? oppo / nSpray : null,
        airPullPct: nSpray > 0 ? airPull / nSpray : null,
        swingPct: n_total > 0 ? swings / n_total : null,
        izSwingPct: izSwingPct,
        chasePct: chasePct_val,
        contactPct: contactPct,
        izContactPct: izContactPct,
        whiffPct: swings > 0 ? whiffs / swings : null,
      };

      // Apply baseball-context filters (comparison group — affects percentiles)
      if (filters.throws !== 'all' && obj.stands !== filters.throws) continue;
      if (obj.count < (filters.minCount || 1)) continue;

      rows.push(obj);
    }

    // Merge expected stats from pre-aggregated HITTER_PITCH_LB
    var hpPreAgg = window.HITTER_PITCH_LB || [];
    var hpPreMap = {};
    for (var hpi = 0; hpi < hpPreAgg.length; hpi++) {
      var hpk = hpPreAgg[hpi].hitter + '|' + hpPreAgg[hpi].team + '|' + hpPreAgg[hpi].pitchType;
      hpPreMap[hpk] = hpPreAgg[hpi];
    }
    var hpXKeys = ['wOBA', 'xBA', 'xSLG', 'xwOBA'];
    for (var hpmi = 0; hpmi < rows.length; hpmi++) {
      var hpmk = rows[hpmi].hitter + '|' + rows[hpmi].team + '|' + rows[hpmi].pitchType;
      var hpPre = hpPreMap[hpmk];
      if (hpPre) {
        for (var hpxi = 0; hpxi < hpXKeys.length; hpxi++) {
          var hpxk = hpXKeys[hpxi];
          if (hpPre[hpxk] !== undefined) rows[hpmi][hpxk] = hpPre[hpxk];
          if (hpPre[hpxk + '_pctl'] !== undefined) rows[hpmi][hpxk + '_pctl'] = hpPre[hpxk + '_pctl'];
        }
      }
    }

    // Compute percentiles per pitch type (output group name)
    var ptGroups = {};
    for (var ri = 0; ri < rows.length; ri++) {
      var pt = rows[ri].pitchType;
      if (!ptGroups[pt]) ptGroups[pt] = [];
      ptGroups[pt].push(rows[ri]);
    }

    var self = this;
    for (var ptKey in ptGroups) {
      var ptRows = ptGroups[ptKey];
      var HP_BIP_PCTL = {
        avg: true, slg: true, iso: true, wOBA: true,
        xBA: true, xSLG: true, xwOBA: true,
        medEV: true, ev75: true, maxEV: true, hardHitPct: true, barrelPct: true,
        laSweetSpotPct: true, hrFbPct: true, airPullPct: true
      };
      HITTER_PITCH_PCTL_KEYS.forEach(function (key) {
        if (HP_BIP_PCTL[key]) {
          self._computePercentiles(ptRows, key, 20, 'nBip');
        } else {
          self._computePercentiles(ptRows, key);
        }
      });
    }

    // Invert where lower is better
    for (var ri2 = 0; ri2 < rows.length; ri2++) {
      for (var inv in HITTER_PITCH_INVERT) {
        var pk = inv + '_pctl';
        if (rows[ri2][pk] !== null && rows[ri2][pk] !== undefined) {
          rows[ri2][pk] = 100 - rows[ri2][pk];
        }
      }
    }

    // Apply view-narrowing filters AFTER percentiles (don't change comparison group)
    var self4 = this;
    if (filters.team !== 'all') {
      rows = rows.filter(function (r) { return r.team === filters.team; });
    } else {
      rows = rows.filter(function (r) { return !self4._isROCTeam(r.team); });
    }
    if (filters.search) {
      var searchLower = filters.search.toLowerCase();
      rows = rows.filter(function (r) { return r.hitter.toLowerCase().indexOf(searchLower) !== -1; });
    }

    return rows;
  },

  // ==================================================================
  //  Team games played (distinct game dates per team)
  // ==================================================================
  /**
   * Get velocity trend data for a pitcher, grouped by pitch type.
   * Returns { pitchType: [{ date: 'YYYY-MM-DD', avgVelo: N }, ...], ... }
   */
  getVeloTrend: function(pitcherName) {
    var d = this.data;
    if (!d || !d.veloTrend) return {};
    var lookups = d.lookups;
    var ci = this._colIdx.veloTrendCols;
    var piIdx = lookups.pitchers.indexOf(pitcherName);
    if (piIdx < 0) return {};

    var result = {};
    var rows = d.veloTrend;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r[ci.pitcherIdx] !== piIdx) continue;
      var pt = lookups.pitchTypes[r[ci.pitchTypeIdx]];
      var date = lookups.dates[r[ci.dateIdx]];
      var sumV = r[ci.sumVelo];
      var nV = r[ci.nVelo];
      if (nV <= 0) continue;
      if (!result[pt]) result[pt] = [];
      result[pt].push({ date: date, avgVelo: Math.round(sumV / nV * 10) / 10 });
    }
    // Sort each pitch type's entries by date
    for (var pt2 in result) {
      result[pt2].sort(function(a, b) { return a.date < b.date ? -1 : 1; });
    }
    return result;
  },

  getTeamGamesPlayed: function(dateStart, dateEnd) {
    var d = this.data;
    if (!d) return {};
    var dates = d.lookups.dates;
    var teams = d.lookups.teams;
    var ci = this._colIdx.pitcherCols;
    var micro = d.pitcherMicro;

    // Build valid date set based on optional range
    var validDates = {};
    for (var di = 0; di < dates.length; di++) {
      var dt = dates[di];
      if (dateStart && dt < dateStart) continue;
      if (dateEnd && dt > dateEnd) continue;
      validDates[di] = true;
    }

    var teamDates = {};  // teamIdx -> { dateIdx: true }
    for (var i = 0; i < micro.length; i++) {
      var row = micro[i];
      var ti = row[ci.teamIdx];
      var dIdx = row[ci.dateIdx];
      if (!validDates[dIdx]) continue;
      if (!teamDates[ti]) teamDates[ti] = {};
      teamDates[ti][dIdx] = true;
    }

    var result = {};
    for (var ti2 in teamDates) {
      result[teams[ti2]] = Object.keys(teamDates[ti2]).length;
    }
    return result;
  },
};
