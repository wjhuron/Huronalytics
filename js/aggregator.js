/**
 * Client-side aggregator for micro-aggregate data.
 * Enables filtering by opponent hand and date range by
 * summing pre-computed counts and recomputing final stats + percentiles.
 */
const Aggregator = {
  data: null,
  loaded: false,
  _colIdx: {},

  // --- MVN conditional expected movement utilities ---
  _matInvGeneral: function (M) {
    const n = M.length;
    const aug = [];
    for (let i = 0; i < n; i++) {
      aug[i] = [];
      for (let j = 0; j < n; j++) aug[i][j] = M[i][j];
      for (let j2 = 0; j2 < n; j2++) aug[i][n + j2] = (i === j2) ? 1.0 : 0.0;
    }
    for (let col = 0; col < n; col++) {
      let maxRow = col;
      for (let r = col + 1; r < n; r++) {
        if (Math.abs(aug[r][col]) > Math.abs(aug[maxRow][col])) maxRow = r;
      }
      const tmp = aug[col]; aug[col] = aug[maxRow]; aug[maxRow] = tmp;
      if (Math.abs(aug[col][col]) < 1e-15) return null;
      for (let r2 = col + 1; r2 < n; r2++) {
        const f = aug[r2][col] / aug[col][col];
        for (let c = 0; c < 2 * n; c++) aug[r2][c] -= f * aug[col][c];
      }
    }
    for (let col2 = n - 1; col2 >= 0; col2--) {
      const piv = aug[col2][col2];
      for (let c2 = 0; c2 < 2 * n; c2++) aug[col2][c2] /= piv;
      for (let r3 = 0; r3 < col2; r3++) {
        const f2 = aug[r3][col2];
        for (let c3 = 0; c3 < 2 * n; c3++) aug[r3][c3] -= f2 * aug[col2][c3];
      }
    }
    const inv = [];
    for (let ii = 0; ii < n; ii++) inv[ii] = aug[ii].slice(n);
    return inv;
  },

  _mvnConditional: function (modelParams, relValues) {
    const mu = modelParams.mu;
    const cov = modelParams.cov;
    const nAcc = 2; // IVB, HB
    const nRel = mu.length - nAcc;
    if (relValues.length !== nRel) return null;
    // Extract sub-matrices
    const sigmaRel = [];
    for (let i = 0; i < nRel; i++) {
      sigmaRel[i] = [];
      for (let j = 0; j < nRel; j++) sigmaRel[i][j] = cov[nAcc + i][nAcc + j];
    }
    const sigmaRel_inv = this._matInvGeneral(sigmaRel);
    if (!sigmaRel_inv) return null;
    const rDiff = [];
    for (let k = 0; k < nRel; k++) rDiff[k] = relValues[k] - mu[nAcc + k];
    // sigmaRel_inv * rDiff
    const sriRdiff = [];
    for (let ii = 0; ii < nRel; ii++) {
      let s = 0;
      for (let jj = 0; jj < nRel; jj++) s += sigmaRel_inv[ii][jj] * rDiff[jj];
      sriRdiff[ii] = s;
    }
    // sigmaCross * sriRdiff => adjustment for each acc variable
    const muBar = [];
    for (let a = 0; a < nAcc; a++) {
      let adj = 0;
      for (let b = 0; b < nRel; b++) adj += cov[a][nAcc + b] * sriRdiff[b];
      muBar[a] = mu[a] + adj;
    }
    return muBar;
  },

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
    const self = this;
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
    const d = this.data;
    const tables = ['pitcherCols', 'pitcherBipCols', 'pitchCols', 'hitterCols', 'hitterBipCols', 'hitterPitchCols', 'hitterPitchBipCols', 'veloTrendCols'];
    for (let t = 0; t < tables.length; t++) {
      const key = tables[t];
      this._colIdx[key] = {};
      for (let i = 0; i < d[key].length; i++) {
        this._colIdx[key][d[key][i]] = i;
      }
    }
  },

  /**
   * Returns true if advanced filters are active and re-aggregation is needed.
   */
  needsReaggregation: function (filters) {
    if (!this.loaded) return false;
    // Always reaggregate — qualifying thresholds affect percentile pools
    return true;
  },

  // --- Spray angle utilities for SACQ% ---
  _HP_X: 125.42,
  _HP_Y: 198.27,
  _LA_BINS: [[-999,0],[0,5],[5,10],[10,15],[15,20],[20,25],[25,30],[30,35],[35,40],[40,50],[50,999]],

  computeSprayAngle: function (hcX, hcY) {
    if (hcX == null || hcY == null) return null;
    const dx = hcX - this._HP_X;
    const dy = this._HP_Y - hcY;
    if (dy <= 0) return null;
    return Math.atan2(dx, dy) * (180 / Math.PI);
  },

  sprayDirection: function (angle, bats) {
    if (angle == null || !bats) return null;
    if (bats === 'R') {
      if (angle < -30) return 'pull';
      if (angle < -15) return 'pull_side';
      if (angle < 0) return 'center_pull';
      if (angle < 15) return 'center_oppo';
      if (angle < 30) return 'oppo_side';
      return 'oppo';
    } else {
      if (angle > 30) return 'pull';
      if (angle > 15) return 'pull_side';
      if (angle > 0) return 'center_pull';
      if (angle > -15) return 'center_oppo';
      if (angle > -30) return 'oppo_side';
      return 'oppo';
    }
  },

  getLABinIdx: function (la) {
    const bins = this._LA_BINS;
    for (let i = 0; i < bins.length; i++) {
      if (la >= bins[i][0] && la < bins[i][1]) return i;
    }
    return null;
  },

  // Build hand-specific + pooled zone maps from METADATA.sacqZones.
  // Returns { hand: {key→zone}, pooled: {key→zone} }
  buildSacqZoneMaps: function () {
    var zones = (window.METADATA && window.METADATA.sacqZones) || [];
    var hand = {}, pooled = {};
    for (var i = 0; i < zones.length; i++) {
      var sz = zones[i];
      if (sz.bats) {
        hand[sz.spray + '|' + sz.laBin + '|' + sz.bats] = sz;
      } else {
        pooled[sz.spray + '|' + sz.laBin] = sz;
      }
    }
    return { hand: hand, pooled: pooled };
  },

  // Look up zone wOBA: try hand-specific first, fall back to pooled
  sacqLookup: function (maps, dir, laBin, bats) {
    var info = maps.hand[dir + '|' + laBin + '|' + bats];
    if (info && info.count >= 20 && info.woba != null) return info.woba;
    info = maps.pooled[dir + '|' + laBin];
    if (info && info.count >= 20 && info.woba != null) return info.woba;
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
    const data = type === 'pitcher' ? (window.PITCHER_DATA || []) : (window.HITTER_DATA || []);
    const nameKey = type === 'pitcher' ? 'pitcher' : 'hitter';
    const map = {};
    for (let i = 0; i < data.length; i++) {
      if (data[i].mlbId) {
        map[data[i][nameKey] + '|' + data[i].team] = data[i].mlbId;
      }
    }
    return map;
  },

  // ---- Date filtering helper ----
  _getValidDateSet: function (filters) {
    const dates = this.data.lookups.dates;
    const minDate = filters.dateStart || '';
    const maxDate = filters.dateEnd || '\uffff';
    const valid = {};
    for (let i = 0; i < dates.length; i++) {
      if (dates[i] >= minDate && dates[i] <= maxDate) {
        valid[i] = true;
      }
    }
    return valid;
  },

  // Helper: check if a team is a ROC/AAA team (excluded from MLB percentile pool)
  _rocTeamSet: null,
  _isROCTeam: function (team) {
    if (!this._rocTeamSet) {
      const rocTeams = (window.METADATA && window.METADATA.rocTeams) ||
                     (DataStore && DataStore.metadata && DataStore.metadata.rocTeams) || [];
      this._rocTeamSet = {};
      for (let i = 0; i < rocTeams.length; i++) this._rocTeamSet[rocTeams[i]] = true;
    }
    return !!this._rocTeamSet[team];
  },

  // Binary search: find index of first element >= val in sorted array
  _bisectLeft: function (arr, val) {
    let lo = 0, hi = arr.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid] < val) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  },

  // Binary search: find index of first element > val in sorted array
  _bisectRight: function (arr, val) {
    let lo = 0, hi = arr.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid] <= val) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  },

  // Compute percentile for a value against a sorted MLB array using binary search
  _percentileFromSorted: function (sortedMlb, val, isPool) {
    const n = sortedMlb.length;
    const below = this._bisectLeft(sortedMlb, val);
    const aboveOrEqual = this._bisectRight(sortedMlb, val);
    const equal = aboveOrEqual - below;
    let pctl;
    if (isPool) {
      // Pool member: use (below + 0.5*(equal-1)) / (n-1) formula
      pctl = (below + 0.5 * (equal - 1)) / Math.max(1, n - 1) * 100;
    } else {
      // Non-pool (ROC/sub-minimum): use (below + 0.5*equal) / n formula
      pctl = (below + 0.5 * equal) / n * 100;
    }
    return Math.max(0, Math.min(100, Math.round(pctl)));
  },

  // ---- Unified percentile computation (O(n log n) via sort + binary search) ----
  // ROC-aware: excludes ROC teams from the percentile pool, then interpolates ROC players
  // qualifyFn: function(row) returning true if row qualifies for the pool (replaces both minCount and _qualified modes)
  _computePercentiles: function (rows, metricKey, minCount, countKey, useAbs) {
    minCount = minCount || 0;
    countKey = countKey || 'count';
    this._computePercentilesUnified(rows, metricKey, function (row) {
      return minCount === 0 || (row[countKey] || 0) >= minCount;
    }, useAbs, minCount > 0);
  },

  // Percentile computation using _qualified flag instead of minCount (ROC-aware)
  _computePercentilesQualified: function (rows, metricKey) {
    this._computePercentilesUnified(rows, metricKey, function (row) {
      return !!row._qualified;
    }, false, false);
  },

  // Shared implementation: O(n log n) percentile computation
  _computePercentilesUnified: function (rows, metricKey, qualifyFn, useAbs, interpolateSubMinimum) {
    const pctlKey = metricKey + '_pctl';
    const self = this;

    // Separate qualified MLB and ROC rows
    const mlbValid = [];
    const rocValid = [];
    for (let i = 0; i < rows.length; i++) {
      const rawVal = rows[i][metricKey];
      if (rawVal !== null && rawVal !== undefined && qualifyFn(rows[i])) {
        const entry = { idx: i, val: useAbs ? Math.abs(rawVal) : rawVal };
        if (self._isROCTeam(rows[i].team)) {
          rocValid.push(entry);
        } else {
          mlbValid.push(entry);
        }
      }
    }

    if (mlbValid.length < 2) {
      for (let j = 0; j < rows.length; j++) {
        const rv = rows[j][metricKey];
        rows[j][pctlKey] = (rv !== null && rv !== undefined && qualifyFn(rows[j])) ? 50 : null;
      }
      return;
    }

    // Sort MLB values once: O(n log n) instead of O(n^2)
    const sortedMlb = mlbValid.map(function (v) { return v.val; });
    sortedMlb.sort(function (a, b) { return a - b; });

    // Compute percentiles for MLB rows using binary search: O(n log n)
    for (let k = 0; k < mlbValid.length; k++) {
      rows[mlbValid[k].idx][pctlKey] = self._percentileFromSorted(sortedMlb, mlbValid[k].val, true);
    }

    // Interpolate ROC rows into MLB distribution: O(r log n)
    for (let r = 0; r < rocValid.length; r++) {
      rows[rocValid[r].idx][pctlKey] = self._percentileFromSorted(sortedMlb, rocValid[r].val, false);
    }

    // Interpolate sub-minimum rows: O(s log n)
    if (interpolateSubMinimum) {
      for (let s = 0; s < rows.length; s++) {
        if (pctlKey in rows[s]) continue;
        const sVal = rows[s][metricKey];
        if (sVal === null || sVal === undefined) {
          rows[s][pctlKey] = null;
          continue;
        }
        const sv = useAbs ? Math.abs(sVal) : sVal;
        rows[s][pctlKey] = self._percentileFromSorted(sortedMlb, sv, false);
      }
    }

    // Fill nulls for unprocessed rows
    for (let j2 = 0; j2 < rows.length; j2++) {
      if (!(pctlKey in rows[j2])) {
        rows[j2][pctlKey] = null;
      }
    }
  },

  // ==================================================================
  //  Pitcher aggregation helpers
  // ==================================================================

  /**
   * Group pitcherMicro rows by (pitcherIdx, teamIdx), applying date and hand filters.
   * Returns { groups, bipByPitcher } where groups maps "pitcherIdx|teamIdx" to
   * { pitcherIdx, teamIdx, throws, counts[] } and bipByPitcher maps pitcherIdx
   * to arrays of BIP records.
   */
  _groupPitcherMicro: function (filters) {
    const d = this.data;
    const ci = this._colIdx.pitcherCols;
    const micro = d.pitcherMicro;
    const validDates = this._getValidDateSet(filters);
    const vsHand = filters.vsHand || 'all';

    const groups = {};
    for (let i = 0; i < micro.length; i++) {
      const row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.batterHand] !== vsHand) continue;

      const gk = row[ci.pitcherIdx] + '|' + row[ci.teamIdx];
      if (!groups[gk]) {
        groups[gk] = {
          pitcherIdx: row[ci.pitcherIdx],
          teamIdx: row[ci.teamIdx],
          throws: row[ci.throws],
          counts: new Array(27)
        };
        for (let z = 0; z < 27; z++) groups[gk].counts[z] = 0;
      }
      const c = groups[gk].counts;
      for (let f = 0; f < 27; f++) {
        c[f] += row[ci.n + f];
      }
    }

    // Filter pitcher BIP records for batted ball stats
    const pbci = this._colIdx.pitcherBipCols;
    const pitcherBipData = d.pitcherBip || [];
    const bipByPitcher = {};
    for (let bi = 0; bi < pitcherBipData.length; bi++) {
      const brow = pitcherBipData[bi];
      if (!validDates[brow[pbci.dateIdx]]) continue;
      if (vsHand !== 'all' && brow[pbci.batterHand] !== vsHand) continue;
      const pKey = brow[pbci.pitcherIdx] + '|' + brow[pbci.teamIdx];
      if (!bipByPitcher[pKey]) bipByPitcher[pKey] = [];
      bipByPitcher[pKey].push(brow);
    }

    return { groups: groups, bipByPitcher: bipByPitcher };
  },

  /**
   * Compute batted ball stats (avgEV, maxEV, hardHit%, barrel%, LD/FB/PU%)
   * from the filtered BIP records for a single pitcher.
   * Returns an object with: avgEVAgainst, maxEVAgainst, hardHitPct, barrelPctAgainst,
   *   ldPct, fbPct, puPct.
   */
  _computePitcherBipStats: function (bipRecs) {
    const pbci = this._colIdx.pitcherBipCols;

    function isBarrel(ev, la) {
      if (ev == null || la == null) return false;
      return la >= 8 && la <= 50 && ev >= 98 && ev * 1.5 - la >= 117 && ev + la >= 124;
    }

    const evs = []; let n_hard = 0, n_barrel = 0;
    let n_ld = 0, n_fb_bb = 0, n_pu_bb = 0; const n_bip_total = bipRecs.length;
    for (let bri = 0; bri < bipRecs.length; bri++) {
      const bev = bipRecs[bri][pbci.exitVelo];
      const bla = bipRecs[bri][pbci.launchAngle];
      const bbt = bipRecs[bri][pbci.bbType]; // 0=gb, 1=ld, 2=fb, 3=pu
      if (bev !== null) { evs.push(bev); if (bev >= 95) n_hard++; }
      if (isBarrel(bev, bla)) n_barrel++;
      if (bbt === 1) n_ld++;
      if (bbt === 2) n_fb_bb++;
      if (bbt === 3) n_pu_bb++;
    }

    // xwOBAsp: average league zone wOBA for BIP against this pitcher (hand-specific with pooled fallback)
    var xwOBAsp = null;
    var sacqMaps = Aggregator.buildSacqZoneMaps();
    if (bipRecs.length > 0) {
      var xsp_sum = 0, xsp_count = 0;
      for (var sri = 0; sri < bipRecs.length; sri++) {
        var sla = bipRecs[sri][pbci.launchAngle];
        var shcX = bipRecs[sri][pbci.hcX];
        var shcY = bipRecs[sri][pbci.hcY];
        var sBats = bipRecs[sri][pbci.bats];
        if (sla == null || shcX == null || shcY == null || !sBats) continue;
        var sAngle = Aggregator.computeSprayAngle(shcX, shcY);
        var sDir = Aggregator.sprayDirection(sAngle, sBats);
        if (!sDir) continue;
        var sLaBin = Aggregator.getLABinIdx(sla);
        if (sLaBin == null) continue;
        var zWoba = Aggregator.sacqLookup(sacqMaps, sDir, sLaBin, sBats);
        if (zWoba != null) {
          xsp_sum += zWoba;
          xsp_count++;
        }
      }
      xwOBAsp = xsp_count > 0 ? xsp_sum / xsp_count : null;
    }

    return {
      avgEVAgainst: evs.length > 0 ? Math.round(evs.reduce(function(a,b){return a+b;},0) / evs.length * 10) / 10 : null,
      maxEVAgainst: evs.length > 0 ? Math.round(Math.max.apply(null, evs) * 10) / 10 : null,
      hardHitPct: evs.length > 0 ? n_hard / evs.length : null,
      barrelPctAgainst: evs.length > 0 ? n_barrel / evs.length : null,
      ldPct: n_bip_total > 0 ? n_ld / n_bip_total : null,
      fbPct: n_bip_total > 0 ? n_fb_bb / n_bip_total : null,
      puPct: n_bip_total > 0 ? n_pu_bb / n_bip_total : null,
      xwOBAsp: xwOBAsp
    };
  },

  /**
   * Convert a single group entry (counts + BIP stats) into a final row object
   * with rate stats (kPct, bbPct, babip, etc.).
   */
  _buildPitcherRow: function (g, lookups, mlbIdMap, bipStats) {
    const c = g.counts;
    const n = c[0], iz = c[1], sw = c[2], wh = c[3], csw = c[4];
    const ooz = c[5], oozSw = c[6], bip = c[7], gb = c[8];
    const pa = c[9], h = c[10], hr = c[11], k = c[12], bb = c[13];
    const hbp = c[14], sf = c[15], sh = c[16], ci_val = c[17];
    const izSw = c[18], izWh = c[19];
    const firstPitches = c[20], firstPitchStrikes = c[21], fb_cnt = c[22], nHrBip = c[23], ldHr = c[24], pu_cnt = c[25], nStrikes = c[26];
    const ab = pa - bb - hbp - sf - sh - ci_val;

    const strikePct = n > 0 ? nStrikes / n : null;
    const kPct = pa > 0 ? k / pa : null;
    const bbPct = pa > 0 ? bb / pa : null;
    const kbbPct = (kPct !== null && bbPct !== null) ? Math.round((kPct - bbPct) * 10000) / 10000 : null;
    const babip_denom = ab - k - hr + sf;
    const babip = babip_denom > 0 ? Math.round((h - hr) / babip_denom * 1000) / 1000 : null;
    const fpsPct = firstPitches > 0 ? firstPitchStrikes / firstPitches : null;
    const fb_for_hrfb = fb_cnt + pu_cnt;
    const hrFbPct = fb_for_hrfb > 0 ? nHrBip / fb_for_hrfb : null;

    const pitcherName = lookups.pitchers[g.pitcherIdx];
    const teamName = lookups.teams[g.teamIdx];
    return {
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
      avgEVAgainst: bipStats.avgEVAgainst,
      maxEVAgainst: bipStats.maxEVAgainst,
      hardHitPct: bipStats.hardHitPct,
      barrelPctAgainst: bipStats.barrelPctAgainst,
      ldPct: bipStats.ldPct,
      fbPct: bipStats.fbPct,
      puPct: bipStats.puPct,
      xwOBAsp: bipStats.xwOBAsp,
    };
  },

  // ==================================================================
  //  Pitcher aggregation
  // ==================================================================
  _aggregatePitcher: function (filters) {
    const d = this.data;
    const lookups = d.lookups;
    const vsHand = filters.vsHand || 'all';

    // Group micro data and BIP records by pitcher/team
    const grouped = this._groupPitcherMicro(filters);
    const groups = grouped.groups;
    const bipByPitcher = grouped.bipByPitcher;

    // MLB ID lookup for clickable names
    const mlbIdMap = this._getMlbIdMap('pitcher');

    // Convert to row objects
    const STAT_KEYS = ['strikePct', 'izPct', 'cswPct', 'izWhiffPct', 'swStrPct', 'chasePct', 'gbPct', 'kPct', 'bbPct', 'kbbPct', 'babip', 'fpsPct', 'hrFbPct',
                     'avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'xwOBAsp'];
    const INVERT = { bbPct: true, babip: true, hrFbPct: true, avgEVAgainst: true, maxEVAgainst: true, hardHitPct: true, barrelPctAgainst: true, xwOBAsp: true };
    let rows = [];

    for (let gk2 in groups) {
      const g = groups[gk2];
      const bipRecs = bipByPitcher[g.pitcherIdx + '|' + g.teamIdx] || [];
      const bipStats = this._computePitcherBipStats(bipRecs);
      const obj = this._buildPitcherRow(g, lookups, mlbIdMap, bipStats);

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
    const boxFields = ['g', 'gs', 'ip', 'w', 'l', 'sv', 'hld', 'tbf', 'era', 'hr9', 'runValue', 'rv100', 'xRunValue', 'xRv100',
                     'era_pctl', 'hr9_pctl', 'runValue_pctl', 'rv100_pctl', 'xRunValue_pctl', 'xRv100_pctl', 'fip', 'fip_pctl', 'xFIP', 'xFIP_pctl', 'siera', 'siera_pctl',
                     'wOBA', 'wOBA_pctl', 'xBA', 'xBA_pctl', 'xSLG', 'xSLG_pctl', 'xwOBA', 'xwOBA_pctl',
                     'xwOBAcon', 'xwOBAcon_pctl',
                     'xwOBAsp', 'xwOBAsp_pctl',
                     'twoStrikeWhiffPct', 'twoStrikeWhiffPct_pctl',
                     'armAngle'];
    const preAgg = window.PITCHER_DATA || [];
    const preAggMap = {};
    for (let bi = 0; bi < preAgg.length; bi++) {
      preAggMap[preAgg[bi].pitcher + '|' + preAgg[bi].team] = preAgg[bi];
    }
    // Fields that have per-hand splits (stored as field_vsL / field_vsR in PITCHER_DATA)
    const handSplitFields = ['twoStrikeWhiffPct', 'fpsPct',
      'strikePct', 'izPct', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct',
      'kPct', 'bbPct', 'kbbPct', 'babip', 'gbPct',
      'avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst',
      'gbPct_bb', 'ldPct', 'fbPct', 'puPct', 'hrFbPct',
      'wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon'];
    const handSuffix = vsHand !== 'all' ? '_vs' + vsHand : '';
    for (let mi = 0; mi < rows.length; mi++) {
      const key2 = rows[mi].pitcher + '|' + rows[mi].team;
      const pre = preAggMap[key2];
      if (pre) {
        for (let fi = 0; fi < boxFields.length; fi++) {
          const bf = boxFields[fi];
          // If filtering by hand and this field has per-hand split, use it
          if (handSuffix && handSplitFields.indexOf(bf) >= 0) {
            const handKey = bf + handSuffix;
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
        const pg = r.g || 0, pgs = r.gs || 0;
        const isSP = pg > 0 && (pgs / pg) > 0.5;
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
    const teamGames = this.getTeamGamesPlayed();
    // Mark each row as qualified or not
    for (let qi = 0; qi < rows.length; qi++) {
      const r = rows[qi];
      const tg = teamGames[r.team] || 0;
      const ipStr = r.ip;
      let ipFloat = 0;
      if (ipStr != null) {
        const ipp = String(ipStr).split('.');
        ipFloat = parseInt(ipp[0], 10) + (ipp[1] ? parseInt(ipp[1], 10) / 3 : 0);
      }
      const pg = r.g || 0, pgs = r.gs || 0;
      const isStarter = pg > 0 && (pgs / pg) > 0.5;
      r._qualified = ipFloat >= (isStarter ? tg * 1.0 : tg * 0.1);
    }
    // Set bipQual flag BEFORE percentiles so BIP stats can use it
    const BIP_STATS = { avgEVAgainst: true, maxEVAgainst: true, hardHitPct: true, barrelPctAgainst: true, xwOBAsp: true };
    for (let bqi = 0; bqi < rows.length; bqi++) {
      rows[bqi].bipQual = (rows[bqi].nBip || 0) >= 20;
    }
    // Use _qualified flag for percentile pool: only qualified pitchers get percentiles
    // BIP-dependent stats additionally require bipQual (≥20 BIP)
    for (let si = 0; si < STAT_KEYS.length; si++) {
      if (BIP_STATS[STAT_KEYS[si]]) {
        // Temporarily narrow _qualified to also require bipQual
        const savedQual = [];
        for (let sq = 0; sq < rows.length; sq++) {
          savedQual.push(rows[sq]._qualified);
          rows[sq]._qualified = rows[sq]._qualified && rows[sq].bipQual;
        }
        this._computePercentilesQualified(rows, STAT_KEYS[si]);
        // Restore original _qualified
        for (let rq = 0; rq < rows.length; rq++) {
          rows[rq]._qualified = savedQual[rq];
        }
      } else {
        this._computePercentilesQualified(rows, STAT_KEYS[si]);
      }
    }
    // Invert where lower is better
    for (let ri = 0; ri < rows.length; ri++) {
      for (let inv in INVERT) {
        const pk = inv + '_pctl';
        if (rows[ri][pk] !== null && rows[ri][pk] !== undefined) {
          rows[ri][pk] = 100 - rows[ri][pk];
        }
      }
    }

    // Apply view-narrowing filters AFTER percentiles (don't change comparison group)
    // Always exclude ROC from "All Teams" view
    const self = this;
    if (filters.team !== 'all') {
      rows = rows.filter(function (r) { return r.team === filters.team; });
    } else {
      rows = rows.filter(function (r) { return !self._isROCTeam(r.team); });
    }
    if (filters.search) {
      const searchLower = filters.search.toLowerCase();
      rows = rows.filter(function (r) { return r.pitcher.toLowerCase().indexOf(searchLower) !== -1; });
    }

    return rows;
  },

  // ==================================================================
  //  Pitch aggregation
  // ==================================================================
  _aggregatePitch: function (filters) {
    const self = this;
    const d = this.data;
    const ci = this._colIdx.pitchCols;
    const micro = d.pitchMicro;
    const lookups = d.lookups;
    const validDates = this._getValidDateSet(filters);
    const vsHand = filters.vsHand || 'all';
    const mlbIdMap = this._getMlbIdMap('pitcher');

    const METRIC_MAP = [
      { key: 'velocity', sum: 'sumVelo', cnt: 'nVelo', round: 1 },
      { key: 'effectiveVelo', sum: 'sumEffVelo', cnt: 'nEffVelo', round: 1 },
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
    const METRIC_KEYS_LIST = METRIC_MAP.map(function (m) { return m.key; }).filter(function (k) { return k !== '_plateZ' && k !== '_plateX'; });
    const NO_PCTL_METRICS = { relPosZ: true, relPosX: true, extension: true, armAngle: true };
    const METRIC_PCTL_KEYS = METRIC_KEYS_LIST.filter(function (k) { return !NO_PCTL_METRICS[k]; });
    const PITCH_STAT_KEYS = ['izPct', 'swStrPct', 'cswPct', 'izWhiffPct', 'chasePct', 'gbPct', 'fpsPct'];
    const PITCH_BB_KEYS = ['avgEVAgainst', 'maxEVAgainst', 'hardHitPct', 'barrelPctAgainst', 'hrFbPct', 'ldPct', 'fbPct', 'puPct'];
    const PITCH_BB_INVERT = { avgEVAgainst: true, maxEVAgainst: true, hardHitPct: true, barrelPctAgainst: true, hrFbPct: true };
    const PITCH_EXPECTED_KEYS = ['wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp'];
    const PITCH_EXPECTED_INVERT = { wOBA: true, xBA: true, xSLG: true, xwOBA: true, xwOBAcon: true, xwOBAsp: true };
    const PITCH_PCTL_KEYS = METRIC_PCTL_KEYS.concat(['nVAA', 'nHAA', 'ivbOE', 'hbOE', 'stuffScore']).concat(PITCH_STAT_KEYS).concat(PITCH_BB_KEYS).concat(PITCH_EXPECTED_KEYS);

    // Group by (pitcherIdx, teamIdx, pitchTypeIdx)
    const groups = {};
    const pitcherTotals = {};

    for (let i = 0; i < micro.length; i++) {
      const row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.batterHand] !== vsHand) continue;

      const pitcherKey = row[ci.pitcherIdx] + '|' + row[ci.teamIdx];
      const gk = pitcherKey + '|' + row[ci.pitchTypeIdx];

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

      const g = groups[gk];
      for (let f = 0; f < 22; f++) {
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
    let rows = [];
    for (let gk2 in groups) {
      const g = groups[gk2];
      const c = g.counts;
      const ms = g.metricSums;
      const n = c[0], iz = c[1], sw = c[2], wh = c[3], csw = c[4];
      const ooz = c[5], oozSw = c[6], bip = c[7], gb = c[8];
      const pa = c[9], h = c[10], hr = c[11], k = c[12], bb = c[13];
      const hbp = c[14], sf = c[15], sh = c[16], ci_val = c[17];
      const izSw = c[18], izWh = c[19];
      const firstPitches = c[20], firstPitchStrikes = c[21];
      const ab = pa - bb - hbp - sf - sh - ci_val;
      const pitcherKey = g.pitcherIdx + '|' + g.teamIdx;
      const pitcherTotal = pitcherTotals[pitcherKey] || 0;

      const kPct = pa > 0 ? k / pa : null;
      const bbPct = pa > 0 ? bb / pa : null;
      const kbbPct = (kPct !== null && bbPct !== null) ? Math.round((kPct - bbPct) * 10000) / 10000 : null;
      const babip_denom = ab - k - hr + sf;
      const babip_val = babip_denom > 0 ? Math.round((h - hr) / babip_denom * 1000) / 1000 : null;
      const fpsPct_val = firstPitches > 0 ? firstPitchStrikes / firstPitches : null;

      const pitcherName2 = lookups.pitchers[g.pitcherIdx];
      const teamName2 = lookups.teams[g.teamIdx];
      const obj = {
        pitcher: pitcherName2,
        team: teamName2,
        mlbId: mlbIdMap[pitcherName2 + '|' + teamName2] || null,
        throws: g.throws,
        pitchType: lookups.pitchTypes[g.pitchTypeIdx],
        count: n,
        nSwings: sw,
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
        const cnt = ms[m.cnt];
        if (cnt > 0) {
          obj[m.key] = Number((ms[m.sum] / cnt).toFixed(m.round));
        } else {
          obj[m.key] = null;
        }
      });

      // Normalized VAA (location-independent, per pitch type):
      // nVAA = VAA - slope * (pitcher_avgPlateZ - league_avgPlateZ)
      // Per-pitch-type slopes capture different VAA~PlateZ relationships by pitch type
      const vaaRegs = DataStore.metadata && DataStore.metadata.vaaRegressions;
      const vaaReg = vaaRegs && vaaRegs[obj.pitchType];
      if (obj.vaa !== null && obj._plateZ !== null && vaaReg && vaaReg.leagueAvgPlateZ != null) {
        obj.nVAA = Number((obj.vaa - vaaReg.slope * (obj._plateZ - vaaReg.leagueAvgPlateZ)).toFixed(2));
      } else {
        obj.nVAA = null;
      }
      // Normalized HAA (location-independent, per pitch type):
      // nHAA = HAA - slope * (pitcher_avgPlateX - league_avgPlateX)
      // Per-pitch-type slopes are critical: breaking balls (SL ~3.6) vs fastballs (SI ~0.17)
      const haaRegs = DataStore.metadata && DataStore.metadata.haaRegressions;
      const haaReg = haaRegs && haaRegs[obj.pitchType];
      if (obj.haa !== null && obj._plateX !== null && haaReg && haaReg.leagueAvgPlateX != null) {
        obj.nHAA = Number((obj.haa - haaReg.slope * (obj._plateX - haaReg.leagueAvgPlateX)).toFixed(2));
      } else {
        obj.nHAA = null;
      }
      delete obj._plateZ;  // internal, not displayed
      delete obj._plateX;  // internal, not displayed

      // xIVB/xHB + IVBOE/HBOE from MVN conditional model (per pitch type + handedness)
      const mvnModels = DataStore.metadata && DataStore.metadata.mvnModels;
      const mvnKey = obj.pitchType + '_' + obj.throws;
      const ptModel = mvnModels && mvnModels[mvnKey];
      let xIVB_val = null, xHB_val = null;
      // Try MLB model first: condition on [ArmAngle, Extension, Velocity]
      if (ptModel && ptModel.mlb && obj.armAngle !== null && obj.extension !== null && obj.velocity !== null) {
        const muBar = self._mvnConditional(ptModel.mlb, [obj.armAngle, obj.extension, obj.velocity]);
        if (muBar) { xIVB_val = muBar[0]; xHB_val = muBar[1]; }
      }
      // Fallback to ROC model if no MLB model or missing ArmAngle: [RelPosZ, RelPosX, Extension, Velocity]
      if (xIVB_val === null && ptModel && ptModel.roc && obj.relPosZ !== null && obj.relPosX !== null && obj.extension !== null && obj.velocity !== null) {
        const muBar2 = self._mvnConditional(ptModel.roc, [obj.relPosZ, obj.relPosX, obj.extension, obj.velocity]);
        if (muBar2) { xIVB_val = muBar2[0]; xHB_val = muBar2[1]; }
      }
      if (xIVB_val !== null) {
        obj.xIVB = Number(xIVB_val.toFixed(1));
        obj.ivbOE = obj.indVertBrk !== null ? Number((obj.indVertBrk - xIVB_val).toFixed(1)) : null;
      } else {
        obj.xIVB = null;
        obj.ivbOE = null;
      }
      if (xHB_val !== null) {
        obj.xHB = Number(xHB_val.toFixed(1));
        obj.hbOE = obj.horzBrk !== null ? Number((obj.horzBrk - xHB_val).toFixed(1)) : null;
      } else {
        obj.xHB = null;
        obj.hbOE = null;
      }

      // Break Tilt (circular mean)
      if (ms.nTilt > 0) {
        const sinAvg = ms.sumTiltSin / ms.nTilt;
        const cosAvg = ms.sumTiltCos / ms.nTilt;
        let avgAngle = Math.atan2(sinAvg, cosAvg);
        if (avgAngle < 0) avgAngle += 2 * Math.PI;
        const avgMinutes = Math.round(avgAngle / (2 * Math.PI) * 720);
        let thh = Math.floor(avgMinutes / 60);
        const tmm = avgMinutes % 60;
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
        const pitcherKey2 = obj.pitcher + '|' + obj.team;
        if (!this._roleCache) this._roleCache = {};
        if (!(pitcherKey2 in this._roleCache)) {
          const pd = window.PITCHER_DATA || [];
          for (let ri3 = 0; ri3 < pd.length; ri3++) {
            if (pd[ri3].pitcher === obj.pitcher && pd[ri3].team === obj.team) {
              const pg2 = pd[ri3].g || 0, pgs2 = pd[ri3].gs || 0;
              this._roleCache[pitcherKey2] = pg2 > 0 && (pgs2 / pg2) > 0.5 ? 'SP' : 'RP';
              break;
            }
          }
          if (!(pitcherKey2 in this._roleCache)) this._roleCache[pitcherKey2] = 'RP';
        }
        if (this._roleCache[pitcherKey2] !== filters.role) continue;
      }
      if (filters.pitchTypes && filters.pitchTypes.indexOf('all') === -1 && filters.pitchTypes.indexOf(obj.pitchType) === -1) continue;
      if (obj.count < (filters.minCount || 1)) continue;
      if (filters.minPitcherSwings && (obj.nSwings || 0) < filters.minPitcherSwings) continue;
      if (filters.minBip && (obj.nBip || 0) < filters.minBip) continue;

      rows.push(obj);
    }

    // Merge fields from pre-aggregated PITCH_DATA that aren't computed from micro counters
    const pitchPreAgg = window.PITCH_DATA || [];
    const pitchPreMap = {};
    for (let ppi = 0; ppi < pitchPreAgg.length; ppi++) {
      const ppk = pitchPreAgg[ppi].pitcher + '|' + pitchPreAgg[ppi].team + '|' + pitchPreAgg[ppi].pitchType;
      pitchPreMap[ppk] = pitchPreAgg[ppi];
    }
    for (let pmi = 0; pmi < rows.length; pmi++) {
      const pmk = rows[pmi].pitcher + '|' + rows[pmi].team + '|' + rows[pmi].pitchType;
      const ppre = pitchPreMap[pmk];
      if (ppre) {
        // Run value (always merge — not hand-dependent at pitch level)
        if (ppre.runValue !== undefined) rows[pmi].runValue = ppre.runValue;
        if (ppre.runValue_pctl !== undefined) rows[pmi].runValue_pctl = ppre.runValue_pctl;
        if (ppre.rv100 !== undefined) rows[pmi].rv100 = ppre.rv100;
        if (ppre.rv100_pctl !== undefined) rows[pmi].rv100_pctl = ppre.rv100_pctl;
        if (ppre.xRunValue !== undefined) rows[pmi].xRunValue = ppre.xRunValue;
        if (ppre.xRunValue_pctl !== undefined) rows[pmi].xRunValue_pctl = ppre.xRunValue_pctl;
        if (ppre.xRv100 !== undefined) rows[pmi].xRv100 = ppre.xRv100;
        if (ppre.xRv100_pctl !== undefined) rows[pmi].xRv100_pctl = ppre.xRv100_pctl;
        // Plate discipline fields not in micro counters
        if (ppre.strikePct !== undefined) rows[pmi].strikePct = ppre.strikePct;
        if (ppre.strikePct_pctl !== undefined) rows[pmi].strikePct_pctl = ppre.strikePct_pctl;
        if (ppre.twoStrikeWhiffPct !== undefined) rows[pmi].twoStrikeWhiffPct = ppre.twoStrikeWhiffPct;
        if (ppre.twoStrikeWhiffPct_pctl !== undefined) rows[pmi].twoStrikeWhiffPct_pctl = ppre.twoStrikeWhiffPct_pctl;
        // Batted ball and expected stats: use per-hand values when hand filter active
        const handSfx = (vsHand === 'L') ? '_vsL' : (vsHand === 'R') ? '_vsR' : '';
        // Batted ball fields
        for (let bbfi = 0; bbfi < PITCH_BB_KEYS.length; bbfi++) {
          const bbf = PITCH_BB_KEYS[bbfi];
          const bbSrc = (handSfx && ppre[bbf + handSfx] !== undefined) ? bbf + handSfx : bbf;
          if (ppre[bbSrc] !== undefined) rows[pmi][bbf] = ppre[bbSrc];
        }
        // Expected stats
        const xKeys = ['wOBA', 'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp'];
        for (let xi = 0; xi < xKeys.length; xi++) {
          const xk = xKeys[xi];
          const xSrc = (handSfx && ppre[xk + handSfx] !== undefined) ? xk + handSfx : xk;
          if (ppre[xSrc] !== undefined) rows[pmi][xk] = ppre[xSrc];
          // Percentiles are only meaningful for overall (not per-hand)
          if (!handSfx && ppre[xk + '_pctl'] !== undefined) rows[pmi][xk + '_pctl'] = ppre[xk + '_pctl'];
        }
        // Max velo
        if (ppre.maxVelo !== undefined) rows[pmi].maxVelo = ppre.maxVelo;
        // Stuff+ (pre-computed, always merge from JSON — not recomputable in browser)
        if (ppre.stuffScore !== undefined) rows[pmi].stuffScore = ppre.stuffScore;
        if (ppre.stuffScore_pctl !== undefined) rows[pmi].stuffScore_pctl = ppre.stuffScore_pctl;
      }
    }

    // Percentiles per pitch type
    const ptGroups = {};
    rows.forEach(function (r) {
      if (!ptGroups[r.pitchType]) ptGroups[r.pitchType] = [];
      ptGroups[r.pitchType].push(r);
    });

    const MIN_PITCH_TYPE_PCTL = 50;  // minimum pitches for outcome metrics
    const ABS_PCTL_KEYS = { horzBrk: true, haa: true, nHAA: true, hbOE: true };  // use |value| for RHP/LHP fairness
    // Shape metrics: physical measurements, no minimum needed
    const SHAPE_METRICS = { velocity: true, spinRate: true, indVertBrk: true, horzBrk: true, vaa: true, haa: true, nVAA: true, nHAA: true, ivbOE: true, hbOE: true, stuffScore: true };
    PITCH_PCTL_KEYS.forEach(function (key) {
      const minPctl = SHAPE_METRICS[key] ? 0 : MIN_PITCH_TYPE_PCTL;
      for (let pt in ptGroups) {
        self._computePercentiles(ptGroups[pt], key, minPctl, 'count', ABS_PCTL_KEYS[key] || false);
      }
    });

    // --- Pitch-type-specific percentile inversions ---

    // IVB: FF/FC = higher is better (default). SI/CU/CH/FS = lower is better (invert).
    // SL/ST/SV = IVB not meaningful, suppress percentile.
    const IVB_INVERT = { SI: true, CU: true, CH: true, FS: true };
    const IVB_SUPPRESS = { SL: true, ST: true, SV: true };
    for (let ptIVB in ptGroups) {
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
    const SPIN_INVERT = { CH: true, FS: true };
    for (let ptSpin in ptGroups) {
      if (SPIN_INVERT[ptSpin]) {
        ptGroups[ptSpin].forEach(function (r) {
          if (r.spinRate_pctl !== null && r.spinRate_pctl !== undefined) {
            r.spinRate_pctl = 100 - r.spinRate_pctl;
          }
        });
      }
    }

    // VAA/nVAA: FF/FC = closer to 0 is better (default higher = higher pctl, no inversion)
    // All others: further from 0 = better (invert)
    const VAA_NO_INVERT = { FF: true, FC: true };
    for (let ptV in ptGroups) {
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

    // HAA/nHAA: uses absolute values, so further from 0 = higher pctl by default
    // FF/FC: closer to 0 = better, so invert for fastballs
    for (let ptH in ptGroups) {
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
    for (let ptBB in ptGroups) {
      ptGroups[ptBB].forEach(function (r) {
        for (let bbInv in PITCH_BB_INVERT) {
          const bbPk = bbInv + '_pctl';
          if (r[bbPk] !== null && r[bbPk] !== undefined) {
            r[bbPk] = 100 - r[bbPk];
          }
        }
        for (let xInv in PITCH_EXPECTED_INVERT) {
          const xPk = xInv + '_pctl';
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
      const searchLower2 = filters.search.toLowerCase();
      rows = rows.filter(function (r) { return r.pitcher.toLowerCase().indexOf(searchLower2) !== -1; });
    }

    return rows;
  },

  // ==================================================================
  //  Hitter aggregation
  // ==================================================================
  _aggregateHitter: function (filters) {
    const d = this.data;
    const ci = this._colIdx.hitterCols;
    const bci = this._colIdx.hitterBipCols;
    const micro = d.hitterMicro;
    const hitterMlbIdMap = this._getMlbIdMap('hitter');
    const bipData = d.hitterBip;
    const lookups = d.lookups;
    const validDates = this._getValidDateSet(filters);
    const vsHand = filters.vsHand || 'all';

    // Group by (hitterIdx, teamIdx)
    const groups = {};
    for (let i = 0; i < micro.length; i++) {
      const row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.pitcherHand] !== vsHand) continue;

      const gk = row[ci.hitterIdx] + '|' + row[ci.teamIdx];
      if (!groups[gk]) {
        groups[gk] = {
          hitterIdx: row[ci.hitterIdx],
          teamIdx: row[ci.teamIdx],
          batsSet: {},
          counts: new Array(49)
        };
        for (let z = 0; z < 49; z++) groups[gk].counts[z] = 0;
      }

      const g = groups[gk];
      g.batsSet[row[ci.bats]] = true;

      for (let f = 0; f < 49; f++) {
        g.counts[f] += row[5 + f];
      }
    }

    // Filter BIP records for medians
    const bipByHitter = {};
    for (let bi = 0; bi < bipData.length; bi++) {
      const brow = bipData[bi];
      if (!validDates[brow[bci.dateIdx]]) continue;
      if (vsHand !== 'all' && brow[bci.pitcherHand] !== vsHand) continue;

      const hKey = brow[bci.hitterIdx] + '|' + brow[bci.teamIdx];
      if (!bipByHitter[hKey]) bipByHitter[hKey] = [];
      bipByHitter[hKey].push(brow);
    }

    function median(arr) {
      if (arr.length === 0) return null;
      arr.sort(function (a, b) { return a - b; });
      const mid = Math.floor(arr.length / 2);
      return arr.length % 2 === 1 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
    }

    const HITTER_STAT_KEYS = [
      'avg', 'obp', 'slg', 'ops', 'iso', 'wOBA', 'babip', 'kPct', 'bbPct',
      'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp',
      'avgEVAll', 'ev50', 'maxEV', 'hardHitPct', 'barrelPct',
      'gbPct', 'ldPct', 'fbPct', 'puPct', 'hrFbPct',
      'pullPct', 'airPullPct',
      'swingPct', 'izSwingPct', 'chasePct', 'izSwChase', 'contactPct', 'izContactPct', 'whiffPct',
      'batSpeed', 'swingLength', 'blastPct', 'idealAAPct',
      'twoStrikeWhiffPct', 'firstPitchSwingPct',
      'avgFbDist', 'avgHrDist',
      'sprintSpeed', 'runValue',
      'wRCplus', 'xWRCplus',
    ];
    const HITTER_INVERT = {
      swingPct: true, chasePct: true, whiffPct: true, gbPct: true, kPct: true, puPct: true, twoStrikeWhiffPct: true, firstPitchSwingPct: true
    };

    let rows = [];
    for (let gk2 in groups) {
      const g = groups[gk2];
      const c = g.counts;
      const batsKeys = Object.keys(g.batsSet);
      const stands = batsKeys.length > 1 ? 'S' : (batsKeys[0] || null);

      const n_total = c[0], pa = c[1], h = c[2], db = c[3], tp = c[4], hr = c[5];
      const bb = c[6], hbp = c[7], sf = c[8], sh = c[9], ci_v = c[10], k = c[11];
      const swings = c[12], whiffs = c[13];
      const izPitches = c[14], oozPitches = c[15];
      const izSwings = c[16], oozSwings = c[17], contact = c[18];
      const izSwNonBunt = c[19], izContact = c[20];
      const bip = c[21], gb_c = c[22], ld = c[23], fb = c[24], pu = c[25];
      const barrels = c[26], nSpray = c[27], pull = c[28], center = c[29], oppo = c[30], airPull = c[31];
      const hardHit = c[32], nHrBip = c[33], ldHr = c[34];
      const twoStrikeSwings = c[35], twoStrikeWhiffs = c[36];
      const firstPitchAppearances = c[37], firstPitchSwings = c[38];
      const xBA_sum = c[39], xBA_count = c[40], xSLG_sum = c[41], xSLG_count = c[42];
      const xwOBA_sum = c[43], xwOBA_count = c[44], xwOBAcon_sum = c[45], xwOBAcon_count = c[46];
      const swingsNonBunt = c[47], contactNonBunt = c[48];

      const ab = pa - bb - hbp - sf - sh - ci_v;
      const singles = h - db - tp - hr;
      const tb_val = singles + 2 * db + 3 * tp + 4 * hr;
      const xbh = db + tp + hr;

      const batting_avg = ab > 0 ? Math.round(h / ab * 1000) / 1000 : null;
      const obp_denom = ab + bb + hbp + sf;
      const obp_val = obp_denom > 0 ? Math.round((h + bb + hbp) / obp_denom * 1000) / 1000 : null;
      const slg_val = ab > 0 ? Math.round(tb_val / ab * 1000) / 1000 : null;
      const ops_val = (obp_val !== null && slg_val !== null) ? Math.round((obp_val + slg_val) * 1000) / 1000 : null;
      const iso_val = (slg_val !== null && batting_avg !== null) ? Math.round((slg_val - batting_avg) * 1000) / 1000 : null;
      const babip_denom = ab - k - hr + sf;
      const babip_val = babip_denom > 0 ? Math.round((h - hr) / babip_denom * 1000) / 1000 : null;

      const kPct = pa > 0 ? k / pa : null;
      const bbPct = pa > 0 ? bb / pa : null;
      const izSwingPct = izPitches > 0 ? izSwings / izPitches : null;
      const chasePct_val = oozPitches > 0 ? oozSwings / oozPitches : null;
      const izSwChase = (izSwingPct !== null && chasePct_val !== null)
        ? Math.round((izSwingPct - chasePct_val) * 10000) / 10000 : null;
      const contactPct = swingsNonBunt > 0 ? contactNonBunt / swingsNonBunt : null;
      const izContactPct = izSwNonBunt > 0 ? izContact / izSwNonBunt : null;
      const fb_for_hrfb = fb + pu;
      const hrFbPct_val = fb_for_hrfb > 0 ? nHrBip / fb_for_hrfb : null;

      // BIP medians
      const bipRecords = bipByHitter[g.hitterIdx + '|' + g.teamIdx] || [];
      const evsAll = [], allLA = [];
      for (let bri = 0; bri < bipRecords.length; bri++) {
        const bev = bipRecords[bri][bci.exitVelo];
        const bla = bipRecords[bri][bci.launchAngle];
        if (bev !== null) evsAll.push(bev);
        if (bla !== null) allLA.push(bla);
      }

      const avgEVAll = evsAll.length > 0 ? Math.round(evsAll.reduce(function(a,b){return a+b;},0) / evsAll.length * 10) / 10 : null;
      const maxEV = evsAll.length > 0 ? Math.round(Math.max.apply(null, evsAll) * 10) / 10 : null;
      const medLA = allLA.length > 0 ? Math.round(median(allLA.slice()) * 10) / 10 : null;

      // EV50: average of top 50% hardest-hit balls across ALL BIP (no LA filter)
      // Matches Savant's "Best Speed" / EV50 — weak contact is noise
      let ev50 = null;
      if (evsAll.length > 0) {
        const sorted = evsAll.slice().sort(function (a, b) { return b - a; });
        const topHalf = sorted.slice(0, Math.max(1, Math.floor(sorted.length / 2)));
        ev50 = Math.round(topHalf.reduce(function (s, v) { return s + v; }, 0) / topHalf.length * 10) / 10;
      }

      // hardHitPct and barrelPct: use EV-valid count as denominator (not total BIP)
      const hardHitPct = evsAll.length > 0 ? hardHit / evsAll.length : null;

      // xwOBAsp — compute from BIP records using hand-specific zone table with pooled fallback
      let xwOBAsp_val = null;
      const sacqMaps = Aggregator.buildSacqZoneMaps();
      if (bipRecords.length > 0) {
        let xwOBAsp_sum = 0, xwOBAsp_count = 0;
        for (let sri = 0; sri < bipRecords.length; sri++) {
          const sla = bipRecords[sri][bci.launchAngle];
          const shcX = bipRecords[sri][bci.hcX];
          const shcY = bipRecords[sri][bci.hcY];
          if (sla == null || shcX == null || shcY == null) continue;
          const sAngle = Aggregator.computeSprayAngle(shcX, shcY);
          const sDir = Aggregator.sprayDirection(sAngle, stands);
          if (!sDir) continue;
          const sLaBin = Aggregator.getLABinIdx(sla);
          if (sLaBin == null) continue;
          const zWoba = Aggregator.sacqLookup(sacqMaps, sDir, sLaBin, stands);
          if (zWoba != null) {
            xwOBAsp_sum += zWoba;
            xwOBAsp_count++;
          }
        }
        xwOBAsp_val = xwOBAsp_count > 0 ? xwOBAsp_sum / xwOBAsp_count : null;
      }

      const hitterName = lookups.hitters[g.hitterIdx];
      const hitterTeam = lookups.teams[g.teamIdx];
      const obj = {
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
        ev50: ev50,
        maxEV: maxEV,
        medLA: medLA,
        hardHitPct: hardHitPct,
        barrelPct: evsAll.length > 0 ? barrels / evsAll.length : null,
        xwOBAsp: xwOBAsp_val,
        gbPct: bip > 0 ? gb_c / bip : null,
        ldPct: bip > 0 ? ld / bip : null,
        fbPct: bip > 0 ? fb / bip : null,
        puPct: bip > 0 ? pu / bip : null,
        hrFbPct: hrFbPct_val,
        pullPct: nSpray > 0 ? pull / nSpray : null,
        middlePct: nSpray > 0 ? center / nSpray : null,
        oppoPct: nSpray > 0 ? oppo / nSpray : null,
        airPullPct: (ld + fb + pu) > 0 ? airPull / (ld + fb + pu) : null,
        swingPct: n_total > 0 ? swings / n_total : null,
        izSwingPct: izSwingPct,
        chasePct: chasePct_val,
        izSwChase: izSwChase,
        contactPct: contactPct,
        izContactPct: izContactPct,
        whiffPct: swings > 0 ? whiffs / swings : null,
        twoStrikeWhiffPct: twoStrikeSwings > 0 ? twoStrikeWhiffs / twoStrikeSwings : null,
        firstPitchSwingPct: firstPitchAppearances > 0 ? firstPitchSwings / firstPitchAppearances : null,
        xBA: ab > 0 && xBA_count > 0 ? xBA_sum / ab : null,
        xSLG: ab > 0 && xSLG_count > 0 ? xSLG_sum / ab : null,
        xwOBA: xwOBA_count > 0 ? xwOBA_sum / xwOBA_count : null,
        xwOBAcon: xwOBAcon_count > 0 ? xwOBAcon_sum / xwOBAcon_count : null,
      };

      // Compute avgFbDist and avgHrDist from BIP records
      if (bipRecords.length > 0 && bci.distance !== undefined) {
        const fbDists = [], hrDists = [];
        for (let dri = 0; dri < bipRecords.length; dri++) {
          const dr = bipRecords[dri];
          const dist = dr[bci.distance];
          if (dist == null) continue;
          if (dr[bci.bbType] === 2) fbDists.push(dist); // fly_ball = 2
          if (dr[bci.event] === 4) hrDists.push(dist);   // HR = 4
        }
        obj.avgFbDist = fbDists.length > 0 ? Math.round(fbDists.reduce(function(a,b){return a+b;},0) / fbDists.length) : null;
        obj.avgHrDist = hrDists.length > 0 ? Math.round(hrDists.reduce(function(a,b){return a+b;},0) / hrDists.length) : null;
      }

      // Apply baseball-context filters (comparison group — affects percentiles)
      if (filters.throws !== 'all' && obj.stands !== filters.throws) continue;
      if ((obj.pa || 0) < (filters.minCount || 1)) continue;
      if (filters.minSwings && obj.nSwings < filters.minSwings) continue;
      if (filters.minBip && (obj.nBip || 0) < filters.minBip) continue;

      rows.push(obj);
    }

    // Merge boxscore stats from pre-aggregated HITTER_DATA
    // When contextual filters (vsHand, date range) are active, skip rate stats
    // that micro data already computed correctly for the filtered subset.
    const hasHitterContextFilter = (vsHand !== 'all') ||
                                    (filters.dateStart || filters.dateEnd);
    // Stats that only boxscore/external data can provide (always merge)
    // wOBA/wRC/wRCplus/xWRCplus need FanGraphs weights + park factors, not computable from micro
    const hBoxAlways = ['g', 'tb', 'sb', 'cs', 'sbPct', 'runValue',
                        'batSpeed', 'swingLength', 'attackAngle', 'attackDirection', 'swingPathTilt', 'nCompSwings', 'blastPct', 'idealAAPct',
                        'sprintSpeed', 'nCompRuns', 'sprintQual',
                        'wOBA', 'wRC', 'wRCplus', 'xWRCplus'];
    // Rate stats that micro data computes (skip when filtered)
    const hBoxRateStats = ['avg', 'obp', 'slg', 'ops', 'iso', 'babip', 'kPct', 'bbPct',
                           'doubles', 'triples', 'hr', 'xbh'];
    const hBoxFields = hasHitterContextFilter ? hBoxAlways : hBoxAlways.concat(hBoxRateStats);
    const hPreAgg = window.HITTER_DATA || [];
    const hPreAggMap = {};
    for (let hbi = 0; hbi < hPreAgg.length; hbi++) {
      hPreAggMap[hPreAgg[hbi].hitter + '|' + hPreAgg[hbi].team] = hPreAgg[hbi];
    }
    for (let hmi = 0; hmi < rows.length; hmi++) {
      const hKey = rows[hmi].hitter + '|' + rows[hmi].team;
      const hPre = hPreAggMap[hKey];
      if (hPre) {
        for (let hfi = 0; hfi < hBoxFields.length; hfi++) {
          const hbf = hBoxFields[hfi];
          if (hPre[hbf] !== undefined) rows[hmi][hbf] = hPre[hbf];
        }
        // Override PA/AB with boxscore values only when unfiltered
        if (!hasHitterContextFilter) {
          if (hPre.pa !== undefined) rows[hmi].pa = hPre.pa;
          if (hPre.ab !== undefined) rows[hmi].ab = hPre.ab;
        }
      }
    }

    // Mark hitter qualification: 3.1 PA per team game
    const teamGames = this.getTeamGamesPlayed();
    for (let qi = 0; qi < rows.length; qi++) {
      const r = rows[qi];
      const tg = teamGames[r.team] || 0;
      r._qualified = (r.pa || 0) >= tg * 3.1;
    }

    // Compute percentiles — all players in pool, qualification handled by frontend
    const self = this;
    HITTER_STAT_KEYS.forEach(function (key) {
      self._computePercentiles(rows, key);
    });

    // Set bipQual flag for each hitter
    for (let bqi = 0; bqi < rows.length; bqi++) {
      rows[bqi].bipQual = (rows[bqi].nBip || 0) >= 20;
    }

    // Invert where lower is better
    for (let ri2 = 0; ri2 < rows.length; ri2++) {
      for (let inv2 in HITTER_INVERT) {
        const pk2 = inv2 + '_pctl';
        if (rows[ri2][pk2] !== null && rows[ri2][pk2] !== undefined) {
          rows[ri2][pk2] = 100 - rows[ri2][pk2];
        }
      }
    }

    // Apply view-narrowing filters AFTER percentiles (don't change comparison group)
    const self3 = this;
    if (filters.team !== 'all') {
      rows = rows.filter(function (r) { return r.team === filters.team; });
    } else {
      rows = rows.filter(function (r) { return !self3._isROCTeam(r.team); });
    }
    if (filters.search) {
      const searchLower = filters.search.toLowerCase();
      rows = rows.filter(function (r) { return r.hitter.toLowerCase().indexOf(searchLower) !== -1; });
    }

    return rows;
  },

  // Category definitions for hitter pitch type grouping
  PITCH_CATEGORIES: {
    'Hard': ['FF', 'SI'],
    'Breaking': ['FC', 'SL', 'ST', 'CU', 'SV'],
    'Offspeed': ['CH', 'FS', 'KN']
  },

  _aggregateHitterPitch: function (filters) {
    const d = this.data;
    const ci = this._colIdx.hitterPitchCols;
    const bci = this._colIdx.hitterPitchBipCols;
    const micro = d.hitterPitchMicro;
    const hpMlbIdMap = this._getMlbIdMap('hitter');
    const bipData = d.hitterPitchBip;
    const lookups = d.lookups;
    const validDates = this._getValidDateSet(filters);
    const vsHand = filters.vsHand || 'all';

    if (!micro || !ci) return [];

    const selectedPitchTypes = filters.pitchTypes; // always array (e.g. ['all'], ['FF','SL'])
    const CATS = this.PITCH_CATEGORIES;

    // Build reverse lookup: pitch type name -> set of pitchTypeIdx values
    const ptNameToIdx = {};
    for (let pi = 0; pi < lookups.pitchTypes.length; pi++) {
      ptNameToIdx[lookups.pitchTypes[pi]] = pi;
    }

    // Build category -> set of pitchTypeIdx
    const catIdxSets = {};
    for (let catName in CATS) {
      catIdxSets[catName] = {};
      for (let ci2 = 0; ci2 < CATS[catName].length; ci2++) {
        const idx = ptNameToIdx[CATS[catName][ci2]];
        if (idx !== undefined) catIdxSets[catName][idx] = true;
      }
    }

    // Determine which output groups we need
    // Each selected chip becomes an output group with its own grouping logic
    const outputGroups = []; // { name, type: 'all'|'category'|'individual', idxSet }
    if (selectedPitchTypes.length === 1 && selectedPitchTypes[0] === 'all') {
      // Default: show all individual pitch types
      outputGroups.push({ name: 'all_individual', type: 'all_individual' });
    } else {
      for (let si = 0; si < selectedPitchTypes.length; si++) {
        const sel = selectedPitchTypes[si];
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
    const perPT = {}; // hitterIdx|teamIdx|pitchTypeIdx -> { counts, batsSet }
    const hitterTotals = {};

    for (let i = 0; i < micro.length; i++) {
      const row = micro[i];
      if (!validDates[row[ci.dateIdx]]) continue;
      if (vsHand !== 'all' && row[ci.pitcherHand] !== vsHand) continue;

      const hk = row[ci.hitterIdx] + '|' + row[ci.teamIdx];
      if (!hitterTotals[hk]) hitterTotals[hk] = { total: 0, batsSet: {} };
      hitterTotals[hk].total += row[6];
      hitterTotals[hk].batsSet[row[ci.bats]] = true;

      const gk = row[ci.hitterIdx] + '|' + row[ci.teamIdx] + '|' + row[ci.pitchTypeIdx];
      if (!perPT[gk]) {
        perPT[gk] = {
          hitterIdx: row[ci.hitterIdx],
          teamIdx: row[ci.teamIdx],
          pitchTypeIdx: row[ci.pitchTypeIdx],
          counts: new Array(49)
        };
        for (let z = 0; z < 49; z++) perPT[gk].counts[z] = 0;
      }
      for (let f = 0; f < 49; f++) {
        perPT[gk].counts[f] += row[6 + f];
      }
    }

    // BIP records by hitter+pitchTypeIdx
    const bipByKey = {};
    if (bipData && bci) {
      for (let bi = 0; bi < bipData.length; bi++) {
        const brow = bipData[bi];
        if (!validDates[brow[bci.dateIdx]]) continue;
        if (vsHand !== 'all' && brow[bci.pitcherHand] !== vsHand) continue;

        const bipKey = brow[bci.hitterIdx] + '|' + brow[bci.teamIdx] + '|' + brow[bci.pitchTypeIdx];
        if (!bipByKey[bipKey]) bipByKey[bipKey] = [];
        bipByKey[bipKey].push(brow);
      }
    }

    function median(arr) {
      if (arr.length === 0) return null;
      arr.sort(function (a, b) { return a - b; });
      const mid = Math.floor(arr.length / 2);
      return arr.length % 2 === 1 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
    }

    // Second pass: build output rows per output group
    // For 'all' and 'category', we combine multiple perPT entries per hitter
    const groups = {}; // outputGroupName|hitterIdx|teamIdx -> combined counts + bipRecords

    for (let gk2 in perPT) {
      const entry = perPT[gk2];
      const ptIdx = entry.pitchTypeIdx;
      const ptName = lookups.pitchTypes[ptIdx];

      for (let oi = 0; oi < outputGroups.length; oi++) {
        const og = outputGroups[oi];
        let match = false;

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
          const outKey = og.name + '|' + entry.hitterIdx + '|' + entry.teamIdx;
          if (!groups[outKey]) {
            groups[outKey] = {
              hitterIdx: entry.hitterIdx,
              teamIdx: entry.teamIdx,
              outputName: og.name,
              counts: new Array(49),
              bipPtIdxs: []
            };
            for (let z2 = 0; z2 < 49; z2++) groups[outKey].counts[z2] = 0;
          }
          const gg = groups[outKey];
          for (let f2 = 0; f2 < 49; f2++) {
            gg.counts[f2] += entry.counts[f2];
          }
          if (gg.bipPtIdxs.indexOf(ptIdx) === -1) gg.bipPtIdxs.push(ptIdx);
        }
      }

      // Handle all_individual: each perPT entry is its own output row
      if (outputGroups.length === 1 && outputGroups[0].type === 'all_individual') {
        const outKey2 = ptName + '|' + entry.hitterIdx + '|' + entry.teamIdx;
        if (!groups[outKey2]) {
          groups[outKey2] = {
            hitterIdx: entry.hitterIdx,
            teamIdx: entry.teamIdx,
            outputName: ptName,
            counts: new Array(49),
            bipPtIdxs: [ptIdx]
          };
          for (let z3 = 0; z3 < 49; z3++) groups[outKey2].counts[z3] = 0;
        }
        for (let f3 = 0; f3 < 49; f3++) {
          groups[outKey2].counts[f3] += entry.counts[f3];
        }
      }
    }

    const HITTER_PITCH_PCTL_KEYS = [
      'avg', 'slg', 'iso', 'wOBA',
      'xBA', 'xSLG', 'xwOBA', 'xwOBAcon', 'xwOBAsp',
      'ev50', 'maxEV', 'hardHitPct', 'barrelPct',
      'gbPct', 'ldPct', 'fbPct', 'hrFbPct',
      'pullPct', 'airPullPct',
      'swingPct', 'izSwingPct', 'chasePct', 'contactPct', 'izContactPct', 'whiffPct',
    ];
    const HITTER_PITCH_INVERT = {
      swingPct: true, chasePct: true, whiffPct: true, gbPct: true
    };

    let rows = [];

    for (let gk3 in groups) {
      const gg2 = groups[gk3];
      const c = gg2.counts;
      const hk2 = gg2.hitterIdx + '|' + gg2.teamIdx;
      const ht = hitterTotals[hk2];
      const hTotal = ht ? ht.total : 1;
      const batsKeys = ht ? Object.keys(ht.batsSet) : [];
      const stands = batsKeys.length > 1 ? 'S' : (batsKeys[0] || null);

      const n_total = c[0], pa = c[1], h = c[2], db = c[3], tp = c[4], hr = c[5];
      const bb = c[6], hbp = c[7], sf = c[8], sh = c[9], ci_v = c[10], k = c[11];
      const swings = c[12], whiffs = c[13];
      const izPitches = c[14], oozPitches = c[15];
      const izSwings = c[16], oozSwings = c[17], contact = c[18];
      const izSwNonBunt = c[19], izContact = c[20];
      const bip = c[21], gb_c = c[22], ld = c[23], fb = c[24], pu = c[25];
      const barrels = c[26], nSpray = c[27], pull = c[28], center = c[29], oppo = c[30], airPull = c[31];
      const hardHit = c[32], nHrBip = c[33], ldHr = c[34];
      const twoStrikeSwings = c[35], twoStrikeWhiffs = c[36];
      const firstPitchAppearances = c[37], firstPitchSwings = c[38];
      const xBA_sum = c[39], xBA_count = c[40], xSLG_sum = c[41], xSLG_count = c[42];
      const xwOBA_sum = c[43], xwOBA_count = c[44], xwOBAcon_sum = c[45], xwOBAcon_count = c[46];
      const swingsNonBunt = c[47], contactNonBunt = c[48];

      const ab = pa - bb - hbp - sf - sh - ci_v;
      const singles = h - db - tp - hr;
      const tb_val = singles + 2 * db + 3 * tp + 4 * hr;

      const batting_avg = ab > 0 ? Math.round(h / ab * 1000) / 1000 : null;
      const slg_val = ab > 0 ? Math.round(tb_val / ab * 1000) / 1000 : null;
      const iso_val = (slg_val !== null && batting_avg !== null) ? Math.round((slg_val - batting_avg) * 1000) / 1000 : null;
      const babip_denom3 = ab - k - hr + sf;
      const babip_val3 = babip_denom3 > 0 ? Math.round((h - hr) / babip_denom3 * 1000) / 1000 : null;

      const izSwingPct = izPitches > 0 ? izSwings / izPitches : null;
      const chasePct_val = oozPitches > 0 ? oozSwings / oozPitches : null;
      const contactPct = swingsNonBunt > 0 ? contactNonBunt / swingsNonBunt : null;
      const izContactPct = izSwNonBunt > 0 ? izContact / izSwNonBunt : null;
      const fb_for_hrfb = fb + pu;
      const hrFbPct_val = fb_for_hrfb > 0 ? nHrBip / fb_for_hrfb : null;

      // BIP medians — combine BIP records from all pitch types in this group
      const evsAll2 = [], allLA = [];
      for (let bpi = 0; bpi < gg2.bipPtIdxs.length; bpi++) {
        const bpKey = gg2.hitterIdx + '|' + gg2.teamIdx + '|' + gg2.bipPtIdxs[bpi];
        const bipRecords = bipByKey[bpKey] || [];
        for (let bri = 0; bri < bipRecords.length; bri++) {
          const bev = bipRecords[bri][bci.exitVelo];
          const bla = bipRecords[bri][bci.launchAngle];
          if (bev !== null) evsAll2.push(bev);
          if (bla !== null) allLA.push(bla);
        }
      }

      const avgEVAll2 = evsAll2.length > 0 ? Math.round(evsAll2.reduce(function(a,b){return a+b;},0) / evsAll2.length * 10) / 10 : null;
      const maxEV = evsAll2.length > 0 ? Math.round(Math.max.apply(null, evsAll2) * 10) / 10 : null;
      const medLA = allLA.length > 0 ? Math.round(median(allLA.slice()) * 10) / 10 : null;

      // EV50: average of top 50% hardest-hit balls across ALL BIP (no LA filter)
      let ev50 = null;
      if (evsAll2.length > 0) {
        const sorted = evsAll2.slice().sort(function (a, b) { return b - a; });
        const topHalf = sorted.slice(0, Math.max(1, Math.floor(sorted.length / 2)));
        ev50 = Math.round(topHalf.reduce(function (s, v) { return s + v; }, 0) / topHalf.length * 10) / 10;
      }

      // hardHitPct and barrelPct: use EV-valid count as denominator (not total BIP)
      const hardHitPct = evsAll2.length > 0 ? hardHit / evsAll2.length : null;

      const hpName = lookups.hitters[gg2.hitterIdx];
      const hpTeam = lookups.teams[gg2.teamIdx];
      const obj = {
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
        babip: babip_val3,
        avgEVAll: avgEVAll2,
        ev50: ev50,
        maxEV: maxEV,
        medLA: medLA,
        hardHitPct: hardHitPct,
        barrelPct: evsAll2.length > 0 ? barrels / evsAll2.length : null,
        gbPct: bip > 0 ? gb_c / bip : null,
        ldPct: bip > 0 ? ld / bip : null,
        fbPct: bip > 0 ? fb / bip : null,
        hrFbPct: hrFbPct_val,
        puPct: bip > 0 ? pu / bip : null,
        pullPct: nSpray > 0 ? pull / nSpray : null,
        middlePct: nSpray > 0 ? center / nSpray : null,
        oppoPct: nSpray > 0 ? oppo / nSpray : null,
        airPullPct: (ld + fb + pu) > 0 ? airPull / (ld + fb + pu) : null,
        swingPct: n_total > 0 ? swings / n_total : null,
        izSwingPct: izSwingPct,
        chasePct: chasePct_val,
        contactPct: contactPct,
        izContactPct: izContactPct,
        whiffPct: swings > 0 ? whiffs / swings : null,
        xBA: ab > 0 && xBA_count > 0 ? xBA_sum / ab : null,
        xSLG: ab > 0 && xSLG_count > 0 ? xSLG_sum / ab : null,
        xwOBA: xwOBA_count > 0 ? xwOBA_sum / xwOBA_count : null,
        xwOBAcon: xwOBAcon_count > 0 ? xwOBAcon_sum / xwOBAcon_count : null,
        twoStrikeWhiffPct: twoStrikeSwings > 0 ? twoStrikeWhiffs / twoStrikeSwings : null,
        firstPitchSwingPct: firstPitchAppearances > 0 ? firstPitchSwings / firstPitchAppearances : null,
        izSwChase: (izSwingPct !== null && chasePct_val !== null) ? Math.round((izSwingPct - chasePct_val) * 10000) / 10000 : null,
      };

      // Apply baseball-context filters (comparison group — affects percentiles)
      if (filters.throws !== 'all' && obj.stands !== filters.throws) continue;
      if (obj.count < (filters.minCount || 1)) continue;
      if (filters.minSwings && (obj.nSwings || 0) < filters.minSwings) continue;
      if (filters.minBip && (obj.nBip || 0) < filters.minBip) continue;

      rows.push(obj);
    }

    // Merge expected stats from pre-aggregated HITTER_PITCH_LB
    const hpPreAgg = window.HITTER_PITCH_LB || [];
    const hpPreMap = {};
    for (let hpi = 0; hpi < hpPreAgg.length; hpi++) {
      const hpk = hpPreAgg[hpi].hitter + '|' + hpPreAgg[hpi].team + '|' + hpPreAgg[hpi].pitchType;
      hpPreMap[hpk] = hpPreAgg[hpi];
    }
    const hpXKeys = ['wOBA', 'runValue', 'rv100', 'avgFbDist', 'avgHrDist', 'xwOBAsp'];
    for (let hpmi = 0; hpmi < rows.length; hpmi++) {
      const hpmk = rows[hpmi].hitter + '|' + rows[hpmi].team + '|' + rows[hpmi].pitchType;
      const hpPre = hpPreMap[hpmk];
      if (hpPre) {
        for (let hpxi = 0; hpxi < hpXKeys.length; hpxi++) {
          const hpxk = hpXKeys[hpxi];
          if (hpPre[hpxk] !== undefined) rows[hpmi][hpxk] = hpPre[hpxk];
          if (hpPre[hpxk + '_pctl'] !== undefined) rows[hpmi][hpxk + '_pctl'] = hpPre[hpxk + '_pctl'];
        }
      }
      // Compute rv100 client-side if not in pre-agg data
      if (rows[hpmi].runValue != null && rows[hpmi].rv100 == null && rows[hpmi].count > 0) {
        rows[hpmi].rv100 = Math.round(rows[hpmi].runValue / rows[hpmi].count * 10000) / 100;
      }
    }

    // Compute percentiles per pitch type (output group name)
    const ptGroups = {};
    for (let ri = 0; ri < rows.length; ri++) {
      const pt = rows[ri].pitchType;
      if (!ptGroups[pt]) ptGroups[pt] = [];
      ptGroups[pt].push(rows[ri]);
    }

    const self = this;
    for (let ptKey in ptGroups) {
      const ptRows = ptGroups[ptKey];
      HITTER_PITCH_PCTL_KEYS.forEach(function (key) {
        self._computePercentiles(ptRows, key);
      });
    }

    // Invert where lower is better
    for (let ri2 = 0; ri2 < rows.length; ri2++) {
      for (let inv in HITTER_PITCH_INVERT) {
        const pk = inv + '_pctl';
        if (rows[ri2][pk] !== null && rows[ri2][pk] !== undefined) {
          rows[ri2][pk] = 100 - rows[ri2][pk];
        }
      }
    }

    // Apply view-narrowing filters AFTER percentiles (don't change comparison group)
    const self4 = this;
    if (filters.team !== 'all') {
      rows = rows.filter(function (r) { return r.team === filters.team; });
    } else {
      rows = rows.filter(function (r) { return !self4._isROCTeam(r.team); });
    }
    if (filters.search) {
      const searchLower = filters.search.toLowerCase();
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
  getVeloTrend: function(pitcherName, teamName) {
    const d = this.data;
    if (!d || !d.veloTrend) return {};
    const lookups = d.lookups;
    const ci = this._colIdx.veloTrendCols;
    const piIdx = lookups.pitchers.indexOf(pitcherName);
    if (piIdx < 0) return {};
    const tiIdx = teamName ? lookups.teams.indexOf(teamName) : -1;

    const result = {};
    const rows = d.veloTrend;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r[ci.pitcherIdx] !== piIdx) continue;
      if (tiIdx >= 0 && r[ci.teamIdx] !== tiIdx) continue;
      const pt = lookups.pitchTypes[r[ci.pitchTypeIdx]];
      const date = lookups.dates[r[ci.dateIdx]];
      const sumV = r[ci.sumVelo];
      const nV = r[ci.nVelo];
      if (nV <= 0) continue;
      if (!result[pt]) result[pt] = [];
      result[pt].push({ date: date, avgVelo: Math.round(sumV / nV * 10) / 10 });
    }
    // Sort each pitch type's entries by date
    for (let pt2 in result) {
      result[pt2].sort(function(a, b) { return a.date < b.date ? -1 : 1; });
    }
    return result;
  },

  getTeamGamesPlayed: function(dateStart, dateEnd) {
    const d = this.data;
    if (!d) return {};
    const dates = d.lookups.dates;
    const teams = d.lookups.teams;
    const ci = this._colIdx.pitcherCols;
    const micro = d.pitcherMicro;

    // Build valid date set based on optional range
    const validDates = {};
    for (let di = 0; di < dates.length; di++) {
      const dt = dates[di];
      if (dateStart && dt < dateStart) continue;
      if (dateEnd && dt > dateEnd) continue;
      validDates[di] = true;
    }

    const teamDates = {};  // teamIdx -> { dateIdx: true }
    for (let i = 0; i < micro.length; i++) {
      const row = micro[i];
      const ti = row[ci.teamIdx];
      const dIdx = row[ci.dateIdx];
      if (!validDates[dIdx]) continue;
      if (!teamDates[ti]) teamDates[ti] = {};
      teamDates[ti][dIdx] = true;
    }

    const result = {};
    for (let ti2 in teamDates) {
      result[teams[ti2]] = Object.keys(teamDates[ti2]).length;
    }
    return result;
  },
};
