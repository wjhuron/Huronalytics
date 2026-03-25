/**
 * Client-side aggregator for micro-aggregate data.
 * Enables filtering by opponent hand and date range by
 * summing pre-computed counts and recomputing final stats + percentiles.
 */
var Aggregator = {
  data: null,
  loaded: false,
  _colIdx: {},

  load: function () {
    // Try embedded data first (for file:// usage)
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
    var tables = ['pitcherCols', 'pitcherBipCols', 'pitchCols', 'hitterCols', 'hitterBipCols', 'hitterPitchCols', 'hitterPitchBipCols'];
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
    return (filters.vsHand && filters.vsHand !== 'all') ||
           !!filters.dateStart || !!filters.dateEnd;
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

  // ---- Percentile computation (replicates Python's compute_percentile_ranks) ----
  // minCount: minimum value of row[countKey] to qualify for percentile pool (0 = no threshold)
  _computePercentiles: function (rows, metricKey, minCount, countKey) {
    minCount = minCount || 0;
    countKey = countKey || 'count';
    var pctlKey = metricKey + '_pctl';
    var valid = [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i][metricKey] !== null && rows[i][metricKey] !== undefined
          && (minCount === 0 || (rows[i][countKey] || 0) >= minCount)) {
        valid.push({ idx: i, val: rows[i][metricKey] });
      }
    }

    if (valid.length < 2) {
      for (var j = 0; j < rows.length; j++) {
        rows[j][pctlKey] = (rows[j][metricKey] !== null && rows[j][metricKey] !== undefined
                            && (minCount === 0 || (rows[j][countKey] || 0) >= minCount)) ? 50 : null;
      }
      return;
    }

    var values = valid.map(function (v) { return v.val; });
    var n = values.length;

    for (var k = 0; k < valid.length; k++) {
      var val = valid[k].val;
      var below = 0, equal = 0;
      for (var m = 0; m < n; m++) {
        if (values[m] < val) below++;
        if (values[m] === val) equal++;
      }
      var pctl = (below + 0.5 * (equal - 1)) / Math.max(1, n - 1) * 100;
      rows[valid[k].idx][pctlKey] = Math.max(0, Math.min(100, Math.round(pctl)));
    }

    for (var j2 = 0; j2 < rows.length; j2++) {
      if (!(pctlKey in rows[j2])) {
        rows[j2][pctlKey] = null;
      }
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
          counts: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
        };
      }
      var c = groups[gk].counts;
      for (var f = 0; f < 26; f++) {
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
      if (ev == null || la == null) return false;
      if (ev < 98) return false;
      var minLA = 26 - (ev - 98);
      var maxLA = 30 + 1.2 * (ev - 98);
      if (minLA < 8) minLA = 8;
      if (maxLA > 50) maxLA = 50;
      return la >= minLA && la <= maxLA;
    }

    // Convert to row objects
    var STAT_KEYS = ['izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'kPct', 'bbPct', 'kbbPct', 'babip', 'fpsPct', 'hrFbPct',
                     'avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'ldPct', 'fbPct', 'puPct'];
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
      var firstPitches = c[20], firstPitchStrikes = c[21], fb_cnt = c[22], nHrBip = c[23], ldHr = c[24], pu_cnt = c[25];
      var ab = pa - bb - hbp - sf - sh - ci_val;

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

      // Apply non-aggregator filters
      if (filters.team !== 'all' && obj.team !== filters.team) continue;
      if (filters.throws !== 'all' && obj.throws !== filters.throws) continue;
      if (obj.count < (filters.minCount || 1)) continue;
      if (filters.minTbf && (obj.pa || 0) < filters.minTbf) continue;
      if (filters.minIp && (obj.ip || 0) < filters.minIp) continue;
      if (filters.minBip && (obj.nBip || 0) < filters.minBip) continue;
      if (filters.minPitcherSwings && (obj.nSwings || 0) < filters.minPitcherSwings) continue;
      if (filters.search && obj.pitcher.toLowerCase().indexOf(filters.search.toLowerCase()) === -1) continue;

      rows.push(obj);
    }

    // Compute percentiles (75-pitch qualifying threshold for rate stats)
    var MIN_PITCHES_PCTL = 75;
    for (var si = 0; si < STAT_KEYS.length; si++) {
      this._computePercentiles(rows, STAT_KEYS[si], MIN_PITCHES_PCTL);
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
      { key: 'vra', sum: 'sumVRA', cnt: 'nVRA', round: 2 },
      { key: 'hra', sum: 'sumHRA', cnt: 'nHRA', round: 2 },
      { key: '_plateZ', sum: 'sumPlateZ', cnt: 'nPlateZ', round: 2 },
      { key: '_plateX', sum: 'sumPlateX', cnt: 'nPlateX', round: 2 },
    ];
    var METRIC_KEYS_LIST = METRIC_MAP.map(function (m) { return m.key; }).filter(function (k) { return k !== '_plateZ' && k !== '_plateX'; });
    var PITCH_STAT_KEYS = ['izPct', 'swStrRate', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'fpsPct'];
    var PITCH_PCTL_KEYS = METRIC_KEYS_LIST.concat(['nVAA', 'nHAA']).concat(PITCH_STAT_KEYS);

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

      // Apply non-aggregator filters
      if (filters.team !== 'all' && obj.team !== filters.team) continue;
      if (filters.throws !== 'all' && obj.throws !== filters.throws) continue;
      if (filters.pitchTypes !== 'all' && filters.pitchTypes.indexOf(obj.pitchType) === -1) continue;
      if (obj.count < (filters.minCount || 1)) continue;
      if (filters.search && obj.pitcher.toLowerCase().indexOf(filters.search.toLowerCase()) === -1) continue;

      rows.push(obj);
    }

    // Percentiles per pitch type
    var ptGroups = {};
    rows.forEach(function (r) {
      if (!ptGroups[r.pitchType]) ptGroups[r.pitchType] = [];
      ptGroups[r.pitchType].push(r);
    });

    var self = this;
    for (var pt in ptGroups) {
      PITCH_PCTL_KEYS.forEach(function (key) {
        self._computePercentiles(ptGroups[pt], key);
      });
    }

    // Invert VAA and nVAA percentiles for non-fastball pitch types
    // FF/FC: closer to 0 (e.g. -3) = red (default: higher value = higher pctl) — no inversion
    // All others: further from 0 (e.g. -10) = red (lower value = red) — invert
    var VAA_NO_INVERT = { FF: true, FC: true };
    for (var ptV in ptGroups) {
      if (!VAA_NO_INVERT[ptV]) {
        ptGroups[ptV].forEach(function (r) {
          if (r.vaa_pctl !== null && r.vaa_pctl !== undefined) {
            r.vaa_pctl = 100 - r.vaa_pctl;
          }
          if (r.nVAA_pctl !== null && r.nVAA_pctl !== undefined) {
            r.nVAA_pctl = 100 - r.nVAA_pctl;
          }
        });
      }
    }

    // Stuff Score
    rows.forEach(function (r) {
      var vp = r.velocity_pctl;
      var sp = r.spinRate_pctl;
      if (vp != null && sp != null) {
        r.stuffScore = Math.round((vp + sp) / 2);
      } else {
        r.stuffScore = null;
      }
    });
    for (var pt2 in ptGroups) {
      self._computePercentiles(ptGroups[pt2], 'stuffScore');
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
      'avg', 'obp', 'slg', 'ops', 'iso', 'babip', 'kPct', 'bbPct',
      'medEV', 'ev75', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct', 'laSweetSpotPct',
      'gbPct', 'ldPct', 'fbPct', 'puPct', 'hrFbPct',
      'pullPct', 'middlePct', 'oppoPct', 'airPullPct',
      'swingPct', 'izSwingPct', 'chasePct', 'izSwChase', 'contactPct', 'izContactPct', 'whiffPct',
    ];
    var HITTER_INVERT = {
      swingPct: true, chasePct: true, whiffPct: true, gbPct: true, kPct: true, puPct: true
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

      // Apply non-aggregator filters
      if (filters.team !== 'all' && obj.team !== filters.team) continue;
      if (filters.throws !== 'all' && obj.stands !== filters.throws) continue;
      if ((obj.pa || 0) < (filters.minCount || 1)) continue;
      if (filters.minSwings && obj.nSwings < filters.minSwings) continue;
      if (filters.search && obj.hitter.toLowerCase().indexOf(filters.search.toLowerCase()) === -1) continue;

      rows.push(obj);
    }

    // Compute percentiles
    var self = this;
    HITTER_STAT_KEYS.forEach(function (key) {
      self._computePercentiles(rows, key);
    });

    // Invert where lower is better
    for (var ri2 = 0; ri2 < rows.length; ri2++) {
      for (var inv2 in HITTER_INVERT) {
        var pk2 = inv2 + '_pctl';
        if (rows[ri2][pk2] !== null && rows[ri2][pk2] !== undefined) {
          rows[ri2][pk2] = 100 - rows[ri2][pk2];
        }
      }
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
      'avg', 'slg', 'iso',
      'medEV', 'ev75', 'maxEV', 'medLA', 'hardHitPct', 'barrelPct', 'laSweetSpotPct',
      'gbPct', 'ldPct', 'fbPct', 'hrFbPct',
      'pullPct', 'oppoPct',
      'swingPct', 'izSwingPct', 'chasePct', 'contactPct', 'izContactPct', 'whiffPct',
    ];
    var HITTER_PITCH_INVERT = {
      swingPct: true, chasePct: true, whiffPct: true, gbPct: true
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
        pullPct: nSpray > 0 ? pull / nSpray : null,
        oppoPct: nSpray > 0 ? oppo / nSpray : null,
        swingPct: n_total > 0 ? swings / n_total : null,
        izSwingPct: izSwingPct,
        chasePct: chasePct_val,
        contactPct: contactPct,
        izContactPct: izContactPct,
        whiffPct: swings > 0 ? whiffs / swings : null,
      };

      // Apply non-aggregator filters
      if (filters.team !== 'all' && obj.team !== filters.team) continue;
      if (filters.throws !== 'all' && obj.stands !== filters.throws) continue;
      if (obj.count < (filters.minCount || 1)) continue;
      if (filters.search && obj.hitter.toLowerCase().indexOf(filters.search.toLowerCase()) === -1) continue;

      rows.push(obj);
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
      HITTER_PITCH_PCTL_KEYS.forEach(function (key) {
        self._computePercentiles(ptRows, key);
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

    return rows;
  },
};
