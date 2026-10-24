/* Team by Month section (hidden, ?roc=1 only, per Wally 2026-10-24): every
   hitter on one club, month by month, in the four hitter stat groups. Renders
   into #tm-page from committed data/team_months/<TEAM>.json, built by
   scripts/builders/build_team_months.py. Self-contained like ABS: it does not
   touch the leaderboard engine. Exposed as window.TeamMonths.

   VALUES come from the month, PERCENTILE colors from the season pool of all
   MLB players (the date-window rule). BB+ / CT+ / SD+ are RAW (not regressed
   toward 100) in every row, including Season. Rows under SMALL_PA (Season
   rows too) are muted and uncolored. */
window.TeamMonths = (function () {
  const SMALL_PA = 50;
  const DEFAULT_TEAM = 'MIN';
  let styled = false, index = null, indexPromise = null;
  const cache = {};
  const state = { view: 'stats', team: DEFAULT_TEAM, month: 'All', hideSmall: false, sort: null, dir: -1 };

  const F = {
    int: function (v) { return Utils.formatInt(v); },
    rate: Utils.formatDecimal(3),
    pct: function (v) { return Utils.formatPct(v); },
    d1: Utils.formatDecimal(1)
  };
  // key -> [label, formatter]
  const COL = {
    pa: ['PA', F.int], count: ['Pitches', F.int], nSwings: ['Swings', F.int], nBip: ['BIP', F.int],
    nCompSwings: ['Comp Swings', F.int],
    avg: ['AVG', F.rate], obp: ['OBP', F.rate], slg: ['SLG', F.rate], hr: ['HR', F.int],
    babip: ['BABIP', F.rate], wOBA: ['wOBA', F.rate], xwOBA: ['xwOBA', F.rate],
    wRCplus: ['wRC+', F.int], xWRCplus: ['xwRC+', F.int],
    wOBAcon: ['wOBAcon', F.rate], xwOBAcon: ['xwOBAcon', F.rate],
    processPlus: ['Process+', F.int], bbPlusU: ['BB+', F.int], ctPlusU: ['CT+', F.int], sdPlusU: ['SD+', F.int],
    kPct: ['K%', F.pct], bbPct: ['BB%', F.pct], izSwingPct: ['Z-Swing%', F.pct], chasePct: ['Chase%', F.pct],
    izContactPct: ['Z-Contact%', F.pct], whiffPct: ['Whiff%', F.pct], twoStrikeWhiffPct: ['2K Whiff%', F.pct],
    firstPitchSwingPct: ['FPSw%', F.pct],
    avgEVAll: ['Avg EV', F.d1], ev95: ['EV95', F.d1], hardHitPct: ['Hard-Hit%', F.pct],
    barrelPct: ['Barrel%', F.pct], medLA: ['Med LA', F.d1], gbPct: ['GB%', F.pct], fbPct: ['FB%', F.pct],
    pullPct: ['Pull%', F.pct], airPullPct: ['AirPull%', F.pct],
    batSpeed: ['Bat Speed', F.d1], swingLength: ['Swing Length', F.d1], attackAngle: ['Attack Angle', F.d1],
    squaredUpPct: ['Squared-Up%', F.pct], blastPct: ['Blast%', F.pct]
  };
  // Column groups per sub-tab; a group's first column gets a divider.
  const VIEWS = {
    stats: { label: 'Stats', sort: 'wRCplus', groups: [
      ['pa'], ['avg', 'obp', 'slg', 'hr', 'babip'], ['wOBA', 'xwOBA'], ['wRCplus', 'xWRCplus'],
      ['wOBAcon', 'xwOBAcon'], ['processPlus', 'bbPlusU', 'ctPlusU', 'sdPlusU'], ['kPct', 'bbPct']] },
    'plate-discipline': { label: 'Plate Discipline', sort: 'sdPlusU', groups: [
      ['pa', 'count', 'nSwings'], ['sdPlusU', 'ctPlusU'], ['kPct', 'bbPct'],
      ['izSwingPct', 'chasePct', 'izContactPct', 'whiffPct', 'twoStrikeWhiffPct', 'firstPitchSwingPct']] },
    'batted-ball': { label: 'Batted Ball', sort: 'bbPlusU', groups: [
      ['pa', 'nBip'], ['bbPlusU', 'wOBAcon', 'xwOBAcon'], ['avgEVAll', 'ev95', 'hardHitPct', 'barrelPct'],
      ['medLA', 'gbPct', 'fbPct', 'pullPct', 'airPullPct']] },
    'bat-tracking': { label: 'Bat Tracking', sort: 'batSpeed', groups: [
      ['pa', 'nCompSwings'], ['batSpeed', 'swingLength', 'attackAngle', 'squaredUpPct', 'blastPct']] }
  };
  const OWN_DESC = {
    bbPlusU: 'BB+ RAW: batted-ball quality (60% xwOBAcon, 40% 95th-percentile EV), NOT regressed toward 100, so a month shows what happened. The Hitters leaderboard shows the regressed value.',
    ctPlusU: 'CT+ RAW: leverage-weighted contact rate on swings against the league on the same pitches, NOT regressed toward 100. Blank under 65 swings.',
    sdPlusU: 'SD+ RAW: run value of each swing or take for its location and count, NOT regressed toward 100. Blank under 190 decisions.',
    wOBAcon: 'wOBA on balls in play (bunts out, home runs in). Read beside xwOBAcon: the gap is luck and defense.',
    processPlus: 'Process+: the raw BB+ / SD+ / CT+ composite (52/17/31) on the wRC+ scale. Blank when SD+ or CT+ is blank.',
    nCompSwings: 'Competitive swings: the bat-tracking sample.'
  };

  function desc(k) {
    if (OWN_DESC[k]) return OWN_DESC[k];
    if (typeof COLUMNS === 'undefined') return '';
    const tabs = ['hitterStats', 'hitterBattedBall', 'hitterSwingDecisions', 'hitterBatTracking'];
    for (let i = 0; i < tabs.length; i++) {
      const cs = COLUMNS[tabs[i]] || [];
      for (let j = 0; j < cs.length; j++) if (cs[j].key === k && cs[j].desc) return cs[j].desc;
    }
    return '';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function pretty(name) {
    const i = name.indexOf(', ');
    return i < 0 ? name : name.slice(i + 2) + ' ' + name.slice(0, i);
  }

  function injectStyles() {
    if (styled) return; styled = true;
    const css = `
#tm-page{max-width:1280px;margin:0 auto;padding:8px 4px 60px;color:var(--text-primary);font-family:'IBM Plex Sans',system-ui,sans-serif}
#tm-page h2{font-family:'Bitter',Georgia,serif;font-size:22px;margin:0 0 4px}
#tm-page .tm-sub{color:var(--text-muted);max-width:90ch;margin:0 0 14px;font-size:14px;line-height:1.5}
#tm-page .tm-bar{display:flex;align-items:flex-end;gap:14px 20px;flex-wrap:wrap;margin-bottom:10px}
#tm-page .tm-ctl label{display:block;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:5px}
#tm-page select{border:1px solid var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-primary);font:14px 'IBM Plex Sans';padding:6px 10px}
#tm-page .seg{display:inline-flex;flex-wrap:wrap;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--bg-card)}
#tm-page .seg button{border:0;background:transparent;color:var(--text-secondary);font:600 13px 'IBM Plex Sans';padding:6px 11px;cursor:pointer}
#tm-page .seg button[aria-pressed="true"]{background:var(--text-primary);color:var(--bg-primary)}
#tm-page .tm-chk{font-size:13px;color:var(--text-secondary);display:inline-flex;gap:6px;align-items:center;padding-bottom:6px}
#tm-page .tm-count{color:var(--text-muted);font-size:12px;margin-left:auto;padding-bottom:6px}
#tm-page .tm-tblwrap{overflow:auto;max-height:74vh;border:1px solid var(--border);border-radius:10px;background:var(--bg-card);-webkit-overflow-scrolling:touch}
#tm-page table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
#tm-page th{position:sticky;top:0;z-index:2;background:var(--bg-th);font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--text-th);text-align:right;padding:9px 8px;border-bottom:1px solid var(--border);cursor:pointer;white-space:nowrap}
#tm-page th.l,#tm-page td.l{text-align:left}
#tm-page th[aria-sort]:not([aria-sort="none"]){color:var(--accent)}
#tm-page td{padding:5px 8px;text-align:right;border-bottom:1px solid var(--border-light);font-size:13px;white-space:nowrap}
#tm-page td.who{font-weight:600}
#tm-page td.mo{color:var(--text-secondary)}
#tm-page .div{border-left:1px solid var(--border)}
#tm-page tr.season td{font-weight:700;border-top:1px solid var(--text-muted)}
#tm-page tr.grp-end td{border-bottom:2px solid var(--border)}
#tm-page tr.small td{color:var(--text-muted);background:transparent !important}
#tm-page tr.lg td{font-style:italic;color:var(--text-muted);position:sticky;z-index:1;background:var(--bg-card);border-bottom:2px solid var(--border)}
#tm-page .tm-foot{color:var(--text-muted);font-size:12.5px;max-width:95ch;margin-top:14px;line-height:1.5}
#tm-page .empty{padding:30px;text-align:center;color:var(--text-muted)}
@media (max-width:640px){#tm-page .tm-count{margin-left:0}}
`;
    const el = document.createElement('style');
    el.textContent = css;
    document.head.appendChild(el);
  }

  function url(path) {
    return 'data/team_months/' + path + (typeof DATA_VERSION !== 'undefined' && DATA_VERSION ? '?v=' + DATA_VERSION : '');
  }

  function loadIndex() {
    if (index) return Promise.resolve(index);
    if (!indexPromise) {
      indexPromise = fetch(url('index.json'), { cache: 'no-cache' }).then(function (r) {
        if (!r.ok) throw new Error('Team by Month index fetch failed: HTTP ' + r.status);
        return r.json();
      }).then(function (d) { index = d; return d; }, function (e) { indexPromise = null; throw e; });
    }
    return indexPromise;
  }

  function loadTeam(team) {
    if (cache[team]) return Promise.resolve(cache[team]);
    return fetch(url(encodeURIComponent(team) + '.json'), { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error('Team by Month rows for ' + team + ' failed: HTTP ' + r.status);
      return r.json();
    }).then(function (d) { cache[team] = d.rows; return d.rows; });
  }

  function cols() {
    const out = [];
    VIEWS[state.view].groups.forEach(function (g) {
      g.forEach(function (k, i) { out.push({ key: k, div: i === 0 }); });
    });
    return out;
  }

  function cell(r, c, colored) {
    const v = r[c.key];
    const p = r[c.key + '_pctl'];
    const bg = colored && p != null ? Utils.percentileColor(p) : null;
    const style = bg ? ' style="background:' + bg + '"' : '';
    const title = p != null ? ' title="' + Utils.ordinal(p) + ' percentile (season pool)"' : '';
    return '<td class="' + (c.div ? 'div' : '') + '"' + style + title + '>' +
      (v == null ? '' : COL[c.key][1](v)) + '</td>';
  }

  function sortVal(r) {
    const v = r[state.sort];
    return v == null ? null : v;
  }

  function cmp(a, b) {
    const va = sortVal(a), vb = sortVal(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return (va < vb ? -1 : va > vb ? 1 : 0) * state.dir;
  }

  function render() {
    injectStyles();
    const page = document.getElementById('tm-page');
    if (!page) return;
    if (!state.sort) state.sort = VIEWS[state.view].sort;
    page.innerHTML = '<div class="empty">Loading…</div>';
    loadIndex().then(function (ix) {
      if (ix.teams.indexOf(state.team) < 0) state.team = ix.teams.indexOf(DEFAULT_TEAM) >= 0 ? DEFAULT_TEAM : ix.teams[0];
      return loadTeam(state.team).then(function (rows) { draw(page, ix, rows); });
    }).catch(function (e) {
      console.error(e);
      page.innerHTML = '<div class="empty"><b>Team by Month data failed to load.</b><br>' + esc(e.message) + '</div>';
    });
  }

  function draw(page, ix, rows) {
    const cs = cols();
    const months = ix.months.slice(0, -1);
    const monthOpts = ['All'].concat(ix.months);
    const shown = rows.filter(function (r) {
      if (state.month !== 'All' && r.month !== state.month) return false;
      if (state.hideSmall && r.month !== 'Season' && (r.pa || 0) < SMALL_PA) return false;
      return true;
    });

    let body = '';
    let nHitters = 0;
    if (state.month === 'All') {
      // Group by hitter: hitters ordered by their Season value of the sort
      // column, months in calendar order inside each group, Season last.
      const byH = {};
      shown.forEach(function (r) { (byH[r.hitter] = byH[r.hitter] || []).push(r); });
      const seasons = rows.filter(function (r) { return r.month === 'Season' && byH[r.hitter]; });
      seasons.sort(cmp);
      nHitters = seasons.length;
      seasons.forEach(function (s) {
        const grp = byH[s.hitter].slice().sort(function (a, b) {
          return ix.months.indexOf(a.month) - ix.months.indexOf(b.month);
        });
        grp.forEach(function (r, i) {
          body += rowHtml(r, cs, i === 0, i === grp.length - 1);
        });
      });
    } else {
      const sorted = shown.slice().sort(cmp);
      nHitters = sorted.length;
      sorted.forEach(function (r) { body += rowHtml(r, cs, true, false); });
    }
    // MLB Average leads the body and sticks under the header, so sorting
    // never moves it (per Wally 2026-10-24).
    body = lgRow(ix, cs) + body;

    const head = '<tr><th class="l" data-k="hitter">Hitter</th><th class="l">Month</th>' +
      cs.map(function (c) {
        const on = state.sort === c.key;
        return '<th data-k="' + c.key + '" class="' + (c.div ? 'div' : '') + '"' +
          ' aria-sort="' + (on ? (state.dir > 0 ? 'ascending' : 'descending') : 'none') + '"' +
          ' title="' + esc(desc(c.key)) + '">' + esc(COL[c.key][0]) + '</th>';
      }).join('') + '</tr>';

    page.innerHTML =
      '<h2>Team by Month</h2>' +
      '<p class="tm-sub">Every hitter on one club, month by month (late-March games count in April). ' +
      'Values are the month\'s; colors rank each value inside the full-season pool of all MLB players. ' +
      'BB+, CT+ and SD+ are <b>raw</b> (not regressed toward 100), so they read wider than on the Hitters leaderboard. ' +
      'Rows under ' + SMALL_PA + ' PA are muted and uncolored.</p>' +
      '<div class="tm-bar">' +
        '<div class="tm-ctl"><label for="tm-team">Team</label><select id="tm-team">' +
          ix.teams.map(function (t) { return '<option' + (t === state.team ? ' selected' : '') + '>' + esc(t) + '</option>'; }).join('') +
        '</select></div>' +
        '<div class="tm-ctl"><label>Month</label><span class="seg" id="tm-month">' +
          monthOpts.map(function (m) { return '<button data-v="' + esc(m) + '" aria-pressed="' + (m === state.month) + '">' + esc(m) + '</button>'; }).join('') +
        '</span></div>' +
        '<label class="tm-chk"><input type="checkbox" id="tm-small"' + (state.hideSmall ? ' checked' : '') + '> Hide months under ' + SMALL_PA + ' PA</label>' +
        '<span class="tm-count">' + nHitters + (state.month === 'All' ? ' hitters' : ' rows') +
          ' &middot; data through ' + esc(ix.dataThrough) + '</span>' +
      '</div>' +
      '<div class="tm-tblwrap"><table><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>' +
      '<p class="tm-foot">Official line (PA, AVG/OBP/SLG, HR, BABIP, wOBA, K%, BB%, wRC+) is FanGraphs\' date-range line; a month split between two clubs uses that club\'s pitches only. ' +
      'Season rows match the Hitters leaderboard except BB+ / CT+ / SD+ (raw here) and wOBAcon. ' +
      'Process+ needs both SD+ (190 decisions) and CT+ (65 swings), so it is blank in short months.</p>';
    wire(page);
    // The pinned row sits right under the sticky header, whatever its height.
    const hh = page.querySelector('thead tr').getBoundingClientRect().height;
    page.querySelectorAll('tr.lg td').forEach(function (td) { td.style.top = hh + 'px'; });
  }

  function rowHtml(r, cs, first, last) {
    const small = (r.pa || 0) < SMALL_PA;
    const cls = [r.month === 'Season' && state.month === 'All' ? 'season' : '', small ? 'small' : '',
      last ? 'grp-end' : ''].join(' ').trim();
    const name = (state.month !== 'All' || first) ? esc(pretty(r.hitter)) : '';
    return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td class="l who">' + name + '</td>' +
      '<td class="l mo">' + esc(r.month) + (r.lineSource === 'pitch' && r.month !== 'Season' ? '*' : '') + '</td>' +
      cs.map(function (c) { return cell(r, c, !small); }).join('') + '</tr>';
  }

  function lgRow(ix, cs) {
    const lg = ix.leagueAverages || {};
    return '<tr class="lg"><td class="l">MLB Average</td><td class="l mo">Season</td>' +
      cs.map(function (c) {
        const v = (c.key === 'pa' || c.key === 'count' || c.key === 'nSwings' || c.key === 'nBip' ||
          c.key === 'nCompSwings' || c.key === 'hr') ? null : lg[c.key];
        return '<td class="' + (c.div ? 'div' : '') + '">' + (v == null ? '' : COL[c.key][1](v)) + '</td>';
      }).join('') + '</tr>';
  }

  function wire(page) {
    const ts = page.querySelector('#tm-team');
    ts.addEventListener('change', function () { state.team = ts.value; pushHash(); render(); });
    page.querySelectorAll('#tm-month button').forEach(function (b) {
      b.addEventListener('click', function () { state.month = b.getAttribute('data-v'); pushHash(); render(); });
    });
    page.querySelector('#tm-small').addEventListener('change', function (e) {
      state.hideSmall = e.target.checked; render();
    });
    page.querySelectorAll('th[data-k]').forEach(function (th) {
      th.addEventListener('click', function () {
        const k = th.getAttribute('data-k');
        if (k === 'hitter') return;
        if (state.sort === k) state.dir = -state.dir; else { state.sort = k; state.dir = -1; }
        render();
      });
    });
  }

  function pushHash() {
    const h = 'team-months/' + state.view + '?team=' + encodeURIComponent(state.team) +
      (state.month !== 'All' ? '&month=' + encodeURIComponent(state.month) : '');
    if (window.location.hash !== '#' + h) history.replaceState(null, '', '#' + h);
  }

  function setView(view, query) {
    if (!VIEWS[view]) view = 'stats';
    if (view !== state.view) { state.view = view; state.sort = null; state.dir = -1; }
    if (query) {
      query.split('&').forEach(function (p) {
        const kv = p.split('=');
        const v = decodeURIComponent(kv[1] || '');
        if (kv[0] === 'team' && /^[A-Z0-9]{2,4}$/.test(v)) state.team = v;
        if (kv[0] === 'month' && v) state.month = v;
      });
    }
  }

  return { setView: setView, render: render, VIEWS: VIEWS, currentTeam: function () { return state.team; } };
})();
