/* ABS challenge section: self-contained. Renders three sub-views (Leaderboards,
   Matrix, Film Room) into #abs-page from committed data/abs_*.json at runtime.
   Isolated from the pitch-data leaderboard engine. Exposed as window.ABS. */
window.ABS = (function () {
  let styled = false, core = null, events = null;
  const state = {
    view: 'leaders', tab: 'catchers', sort: 'skill', dir: -1, q: '',
    // matrix state
    k: 2, half: 'top', outs: 0, bases: [false, false, false], lead: 0,
    sel: { b: 1, s: 1, inning: 7 }, side: 'fld', px: 8.95, pz: 29.4,
    ztop: 39.6, zbot: 19.2
  };
  const ZHW = 8.5, THR = 1.4495, PXIN = 8, PLOT_Z0 = 12;

  function injectStyles() {
    if (styled) return; styled = true;
    const css = `
#abs-page{max-width:1080px;margin:0 auto;padding:8px 4px 60px;color:var(--text-primary);font-family:'IBM Plex Sans',system-ui,sans-serif}
#abs-page h2{font-family:'Bitter',Georgia,serif;font-size:22px;margin:0 0 4px}
#abs-page .abs-sub{color:var(--text-muted);max-width:78ch;margin:0 0 16px;font-size:14px;line-height:1.5}
#abs-page .abs-sub b{color:var(--text-primary)}
#abs-page .abs-vtabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
#abs-page .abs-vtabs button{border:1px solid var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-secondary);font:600 13px 'IBM Plex Sans';padding:7px 14px;cursor:pointer}
#abs-page .abs-vtabs button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#f7f2e9}
#abs-page .abs-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
#abs-page input[type=search],#abs-page .abs-inp{border:1px solid var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-primary);font:14px 'IBM Plex Sans';padding:7px 11px}
#abs-page .abs-count{color:var(--text-muted);font-size:12px;margin-left:auto}
#abs-page .abs-tblwrap{overflow:auto;max-height:72vh;border:1px solid var(--border);border-radius:10px;background:var(--bg-card);-webkit-overflow-scrolling:touch}
#abs-page table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;min-width:760px}
#abs-page th{position:sticky;top:0;background:var(--bg-th);font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-th);text-align:right;padding:9px 10px;border-bottom:1px solid var(--border);cursor:pointer;white-space:nowrap}
#abs-page th.l{text-align:left}
#abs-page th[aria-sort]:not([aria-sort="none"]){color:var(--accent)}
#abs-page td{padding:6px 10px;text-align:right;border-bottom:1px solid var(--border-light);font-size:13px;white-space:nowrap}
#abs-page td.l{text-align:left;font-weight:600}
#abs-page td.dim{color:var(--text-muted)}
#abs-page tr:last-child td{border-bottom:0}
#abs-page .pos{color:#3f6b34;font-weight:600}
#abs-page .neg{color:var(--accent);font-weight:600}
#abs-page a.abs-vid{color:var(--accent);font-weight:600;text-decoration:none}
#abs-page .abs-foot{color:var(--text-muted);font-size:12.5px;max-width:80ch;margin-top:14px;line-height:1.5}
#abs-page .mx-ctrls{display:flex;flex-wrap:wrap;gap:14px 22px;align-items:flex-end;margin-bottom:16px}
#abs-page .mx-ctl label{display:block;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-bottom:5px}
#abs-page .seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--bg-card)}
#abs-page .seg button{border:0;background:transparent;color:var(--text-secondary);font:600 13px 'IBM Plex Sans';padding:6px 12px;cursor:pointer}
#abs-page .seg button[aria-pressed="true"]{background:var(--text-primary);color:var(--bg-primary)}
#abs-page .chip{border:1px solid var(--border);border-radius:8px;background:var(--bg-card);color:var(--text-secondary);font:600 13px 'IBM Plex Sans';padding:6px 11px;cursor:pointer}
#abs-page .chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#f7f2e9}
#abs-page .step{display:inline-flex;align-items:center;border:1px solid var(--border);border-radius:8px;background:var(--bg-card)}
#abs-page .step button{border:0;background:transparent;color:var(--text-primary);font:600 15px 'IBM Plex Sans';padding:6px 11px;cursor:pointer}
#abs-page .step .val{min-width:110px;text-align:center;font-weight:600;font-size:13px}
#abs-page .mx-scroll{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--bg-card);padding:12px}
#abs-page .mx-grid{border-collapse:separate;border-spacing:2px;min-width:auto}
#abs-page .mx-grid th{position:static;background:transparent;border:0;cursor:default;color:var(--text-muted);padding:3px 6px}
#abs-page .mx-grid th.rowh{text-align:right;color:var(--text-primary);font-size:12px;font-weight:600;padding-right:9px}
#abs-page .cell{display:block;width:100%;border:0;border-radius:5px;font:600 12px 'IBM Plex Sans';padding:8px 2px;text-align:center;cursor:pointer;min-width:42px}
#abs-page .cell.sel{box-shadow:0 0 0 2px var(--text-primary)}
#abs-page .mx-legend{display:flex;align-items:center;gap:10px;margin-top:10px;font-size:12px;color:var(--text-muted)}
#abs-page .mx-grad{height:9px;border-radius:5px;flex:1;max-width:320px}
#abs-page .panel{border:1px solid var(--border);border-radius:10px;background:var(--bg-card);padding:18px;margin-top:8px}
#abs-page .facts{display:flex;flex-wrap:wrap;gap:9px;margin:14px 0}
#abs-page .fact{border:1px solid var(--border);border-radius:9px;padding:9px 13px;min-width:110px}
#abs-page .fact .k{font-size:10px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--text-muted)}
#abs-page .fact .v{font-family:'Bitter',serif;font-weight:700;font-size:20px;margin-top:2px}
#abs-page .verdict{display:flex;align-items:center;gap:12px;border-radius:9px;padding:12px 16px;margin-top:6px}
#abs-page .verdict.go{background:rgba(63,107,52,.14)}
#abs-page .verdict.hold{background:var(--accent-light)}
#abs-page .verdict .word{font-family:'Bitter',serif;font-weight:700;font-size:21px}
#abs-page .verdict.go .word{color:#3f6b34}
#abs-page .verdict.hold .word{color:var(--accent)}
#abs-page .verdict .why{font-size:13px;color:var(--text-secondary)}
#abs-page .zplot{border:1px solid var(--border);border-radius:9px;background:var(--bg-primary);cursor:crosshair;touch-action:manipulation}
`;
    const s = document.createElement('style'); s.id = 'abs-styles'; s.textContent = css;
    document.head.appendChild(s);
  }

  async function ensureCore() {
    if (core) return;
    const [gr, bt, om, vt, hz] = await Promise.all([
      fetch('data/abs_player_grades_2026.json').then(r => r.json()),
      fetch('data/abs_backtest_2026.json').then(r => r.json()),
      fetch('data/abs_option_model_2026.json').then(r => r.json()),
      fetch('data/abs_value_tables_2026.json').then(r => r.json()),
      fetch('data/abs_hitter_zones_2026.json').then(r => r.json())
    ]);
    const zones = Object.values(hz.zones).map(z => ({ n: z.name, t: z.szTop, b: z.szBot }))
      .sort((a, b) => a.n < b.n ? -1 : 1);
    core = {
      grades: gr, backtest: bt.teams,
      countRV288: vt.countRV288, runDist: vt.runDist, W: vt.W, wExtraTie: vt.wExtraTie,
      G: vt.G, gAvg: vt.meta.gAvg, Cgrid: om.Cgrid, post: om.pLook, zones: zones
    };
  }

  // ---------- shared ----------
  const el = () => document.getElementById('abs-page');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // view switching is handled by the nav sub-tabs (#abs-subtabs) in app.js,
  // so the in-page switcher is intentionally empty
  function viewTabs() { return ''; }
  function bindViewTabs() { }

  // ================= LEADERBOARDS =================
  const COLS = {
    player: [['player', 'Player', 'l'], ['team', 'Tm', 'l'], ['skill', 'Skill+'], ['skci', '95% CI'],
    ['value', 'Value/100'], ['vci', '95% CI'], ['cons', 'Dec'], ['chal', 'Chal'], ['succ', 'Succ%'], ['net', 'NetVal']],
    backtest: [['team', 'Team', 'l'], ['games', 'G'], ['actW', 'ActualWins'], ['optW', 'OptimalWins'], ['gapW', 'LeftOnTable']]
  };
  const NOTES = {
    catchers: 'TWO orthogonal metrics. <b>Skill+</b> = leverage-blind decision quality indexed to 100, independent of the stakes a catcher faced. <b>Value/100</b> = leveraged runs added per 100 consequential decisions (skill x leverage x volume). They rank differently on purpose: the highest-Value catchers are not the highest-Skill ones. Both empirical-Bayes shrunk with 95% CIs, shown only where reliable (reliability &ge; 0.40). Wide Skill+ CIs (~&plusmn;20) mean most catchers are statistically indistinguishable in pure skill with half a season. Sort by either column.',
    hitters: 'DESCRIPTIVE ONLY. Half a season of hitter challenges shows no detectable talent spread yet, so no hitter is a reliable talent estimate. Records of what happened, ranked by NetVal. Expect this to firm up over 2-3 seasons.',
    teams: 'Team totals across all deciders, including pitcher-initiated challenges. Ranked by NetVal (descriptive).',
    backtest: 'Season replay: value captured by actual challenge usage vs the matrix policy run with league-average perception (no hindsight). Wins = leveraged runs times the league run-to-win factor. Negative LeftOnTable = the team already beats the league-perceiver benchmark.'
  };
  const DEFSORT = { catchers: 'skill', hitters: 'net', teams: 'net', backtest: 'gapW' };

  function slimRow(r) {
    const sq = r.skillQual, vq = r.valueQual;
    return {
      player: r.player, team: r.team,
      skill: (r.skill == null || !sq) ? null : Math.round(r.skill),
      skci: (r.skillCI == null || !sq) ? null : Math.round(r.skillCI),
      value: (r.value == null || !vq) ? null : +r.value.toFixed(2),
      vci: (r.valueCI == null || !vq) ? null : +r.valueCI.toFixed(2),
      cons: r.consN || 0, chal: r.challenges,
      succ: r.successPct == null ? null : Math.round(r.successPct), net: +r.netValue.toFixed(2)
    };
  }
  function fmt(v, k) {
    if (v == null) return k === 'skill' ? 'provisional' : '';
    if (k === 'skci' || k === 'vci') return '&plusmn;' + v;
    if (k === 'value' || k === 'net' || k === 'gapW') return v.toFixed(2);
    if (typeof v === 'number' && !Number.isInteger(v)) return v.toFixed(2);
    return v;
  }
  function cellCls(v, k) {
    if ((k === 'net' || k === 'value' || k === 'gapW') && typeof v === 'number') return v > 0.005 ? 'pos' : (v < -0.005 ? 'neg' : '');
    if (k === 'skill' && typeof v === 'number') return v > 100.5 ? 'pos' : (v < 99.5 ? 'neg' : '');
    if (k === 'skill' && v == null) return 'dim';
    if (['player', 'team'].includes(k)) return 'l';
    return ['skci', 'vci', 'cons', 'succ', 'chal'].includes(k) ? 'dim' : '';
  }
  function renderLeaders() {
    const g = core.grades;
    const rowsFor = t => t === 'backtest' ? core.backtest : (g[t] || []).map(slimRow);
    const p = el();
    p.innerHTML = viewTabs() +
      `<h2>Challenge grades</h2><p class="abs-sub" id="abs-note"></p>
       <div class="abs-bar">
         <div class="abs-vtabs" id="abs-ltabs">${['catchers', 'hitters', 'teams', 'backtest'].map(t =>
        `<button data-ltab="${t}" aria-pressed="${state.tab === t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div>
         <input type="search" id="abs-q" placeholder="Search player or team" value="${esc(state.q)}">
         <span class="abs-count" id="abs-cnt"></span>
       </div>
       <div class="abs-tblwrap"><table id="abs-tbl"></table></div>`;
    bindViewTabs();
    p.querySelectorAll('#abs-ltabs button').forEach(b => b.addEventListener('click', () => {
      state.tab = b.dataset.ltab; state.sort = DEFSORT[state.tab]; state.dir = -1; drawTable();
    }));
    p.querySelector('#abs-q').addEventListener('input', e => { state.q = e.target.value; drawTable(); });
    if (!COLS[state.tab] && state.tab !== 'backtest') state.tab = 'catchers';
    drawTable();

    function drawTable() {
      const cols = state.tab === 'backtest' ? COLS.backtest : COLS.player;
      let rows = rowsFor(state.tab).slice();
      if (state.q) { const q = state.q.toLowerCase(); rows = rows.filter(r => (r.player || r.team || '').toLowerCase().includes(q) || String(r.team).toLowerCase().includes(q)); }
      rows.sort((a, b) => {
        const x = a[state.sort], y = b[state.sort];
        if (x == null) return 1; if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * state.dir * (typeof x === 'string' ? -1 : 1);
      });
      let h = '<thead><tr>' + cols.map(c => `<th class="${c[2] || ''}" data-k="${c[0]}" aria-sort="${state.sort === c[0] ? (state.dir < 0 ? 'descending' : 'ascending') : 'none'}">${c[1]}</th>`).join('') + '</tr></thead><tbody>';
      for (const r of rows) h += '<tr>' + cols.map(c => `<td class="${cellCls(r[c[0]], c[0])}">${fmt(r[c[0]], c[0])}</td>`).join('') + '</tr>';
      p.querySelector('#abs-tbl').innerHTML = h + '</tbody>';
      p.querySelector('#abs-cnt').textContent = rows.length + ' rows';
      p.querySelector('#abs-note').innerHTML = NOTES[state.tab];
      p.querySelectorAll('#abs-tbl th').forEach(th => th.addEventListener('click', () => {
        const k = th.dataset.k; if (state.sort === k) state.dir *= -1; else { state.sort = k; state.dir = -1; } drawTable();
      }));
    }
  }

  // ================= MATRIX =================
  const clamp = d => Math.max(-12, Math.min(12, d));
  function contBat(inning, half, d) {
    d = clamp(d);
    if (half === 'top') {
      const home = inning >= 9 ? (d > 0 ? 1 : core.W[Math.min(inning, 10) + '|bottom|' + d]) : core.W[inning + '|bottom|' + d];
      return 1 - home;
    }
    if (inning >= 9) return d > 0 ? 1 : (d < 0 ? 0 : core.wExtraTie);
    return core.W[(inning + 1) + '|top|' + d];
  }
  function wpMid(inning, half, diff, bases, outs) {
    if (outs >= 3) return contBat(inning, half, diff);
    const dist = core.runDist[bases + '|' + outs]; let tot = 0;
    for (const k in dist) { const r = +k, d2 = half === 'top' ? diff - r : diff + r; tot += dist[k] * contBat(inning, half, d2); }
    return tot;
  }
  function walkBases(bases) {
    const f = bases[0] === '1', s2 = bases[1] === '1', t = bases[2] === '1';
    const runs = (f && s2 && t) ? 1 : 0, nt = (f && s2) ? true : t, ns = f ? true : s2;
    return ['1' + (ns ? '1' : '0') + (nt ? '1' : '0'), runs];
  }
  function gainFor(b, s, inning) {
    const bases = state.bases.map(x => x ? '1' : '0').join(''), outs = state.outs;
    const diff = state.half === 'top' ? -state.lead : state.lead;
    const g = core.G[Math.min(inning, 10) + '|' + state.half + '|' + clamp(diff)];
    let wpBase = null, ballWP, strikeWP;
    if (b === 3) { wpBase = wpMid(inning, state.half, diff, bases, outs); const [nb, runs] = walkBases(bases); const d2 = state.half === 'top' ? diff - runs : diff + runs; ballWP = wpMid(inning, state.half, d2, nb, outs) - wpBase; }
    else ballWP = core.countRV288[(b + 1) + '-' + s + '|' + bases + '|' + outs] * g;
    if (s === 2) { if (wpBase === null) wpBase = wpMid(inning, state.half, diff, bases, outs); strikeWP = wpMid(inning, state.half, diff, bases, outs + 1) - wpBase; }
    else strikeWP = core.countRV288[b + '-' + (s + 1) + '|' + bases + '|' + outs] * g;
    return (ballWP - strikeWP) / core.gAvg;
  }
  const Tfor = inning => 2 * (9 - Math.min(inning, 9)) + (state.half === 'top' ? 2 : 1);
  function costFor(inning) { const dTeam = state.side === 'bat' ? state.lead : -state.lead; return core.Cgrid[state.k + '|' + Tfor(inning) + '|' + clamp(dTeam)]; }
  function pstarFor(b, s, inning) { const g = Math.max(gainFor(b, s, inning), 1e-4), c = costFor(inning); return c / (g + c); }
  const RAMP = [[240, 228, 216], [236, 206, 168], [214, 143, 96], [166, 59, 34], [120, 34, 22]];
  function heat(p) {
    const t = Math.max(0, Math.min(1, p / 0.8)), x = t * (RAMP.length - 1), i = Math.min(Math.floor(x), RAMP.length - 2), f = x - i;
    const c = RAMP[i].map((v, j) => Math.round(v + (RAMP[i + 1][j] - v) * f));
    return { bg: `rgb(${c.join(',')})`, dark: (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) < 140 };
  }
  function posterior(key, x) {
    const g = core.post[key]; if (x <= g[0][0]) return g[0][1]; if (x >= g[g.length - 1][0]) return g[g.length - 1][1];
    const st = g[1][0] - g[0][0], i = Math.floor((x - g[0][0]) / st), a = g[i], b = g[Math.min(i + 1, g.length - 1)];
    return a[1] + (b[1] - a[1]) * (x - a[0]) / Math.max(b[0] - a[0], 1e-9);
  }
  function neededInches(key, pstar) {
    const g = core.post[key]; if (g[g.length - 1][1] < pstar) return null;
    for (const [x, p] of g) if (p >= pstar) return Math.max(x, 0); return null;
  }
  function pitchGeom() {
    const ax = Math.abs(state.px), dx = ZHW - ax, dt = state.ztop - state.pz, db = state.pz - state.zbot;
    const dzOut = Math.max(state.pz - state.ztop, state.zbot - state.pz), inside = dx >= 0 && dzOut <= 0;
    const d = inside ? -Math.min(dx, dt, db) : Math.hypot(Math.max(-dx, 0), Math.max(dzOut, 0));
    const mEdge = Math.min(dx, dt, db), reg = mEdge === dx ? 'side' : (mEdge === dt ? 'top' : 'bottom');
    return { loc: THR - d, reg };
  }
  const ordinal = n => n + (['th', 'st', 'nd', 'rd'][(n % 100 > 10 && n % 100 < 14) ? 0 : Math.min(n % 10, 4)] || 'th');
  const COUNTS = [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [2, 0], [2, 1], [2, 2], [3, 0], [3, 1], [3, 2]];
  const INN = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

  function renderMatrix() {
    const p = el();
    p.innerHTML = viewTabs() +
      `<h2>The challenge matrix</h2>
       <p class="abs-sub">Each cell is the break-even confidence: how sure you must be the call was wrong before challenging is worth it, weighing the flip value in this exact spot against the option value of the challenge you might lose.</p>
       <div class="mx-ctrls">
        <div class="mx-ctl"><label>Challenges left</label><span class="seg" id="mK"><button data-v="2" aria-pressed="true">2</button><button data-v="1">1</button></span></div>
        <div class="mx-ctl"><label>Half</label><span class="seg" id="mHalf"><button data-v="top" aria-pressed="true">Top</button><button data-v="bottom">Bottom</button></span></div>
        <div class="mx-ctl"><label>Outs</label><span class="seg" id="mOuts"><button data-v="0" aria-pressed="true">0</button><button data-v="1">1</button><button data-v="2">2</button></span></div>
        <div class="mx-ctl"><label>Runners</label><span id="mBases">${[0, 1, 2].map(i => `<button class="chip" data-b="${i}">${['1B', '2B', '3B'][i]}</button>`).join(' ')}</span></div>
        <div class="mx-ctl"><label>Score</label><span class="step"><button id="mDown">&minus;</button><span class="val" id="mScore">Tie game</span><button id="mUp">+</button></span></div>
        <div class="mx-ctl"><label>Deciding side</label><span class="seg" id="mSide"><button data-v="fld" aria-pressed="true">Catcher</button><button data-v="bat">Hitter</button></span></div>
       </div>
       <div class="mx-scroll"><table class="mx-grid" id="mGrid"></table></div>
       <div class="mx-legend"><span>Challenge freely</span><div class="mx-grad" id="mGrad"></div><span>Hold</span><span style="margin-left:auto">cells = break-even confidence %</span></div>
       <h2 style="margin-top:26px">Price a specific pitch</h2>
       <p class="abs-sub">Click a cell to load that situation, then set where the ball was. Pick a hitter for their exact zone, or type Gameday plate_x / plate_z.</p>
       <div class="panel">
        <p id="mState" class="abs-sub" style="margin-bottom:10px"></p>
        <div class="facts">
          <div class="fact"><div class="k">Flip worth</div><div class="v" id="fG">-</div></div>
          <div class="fact"><div class="k">Challenge value</div><div class="v" id="fC">-</div></div>
          <div class="fact"><div class="k">Break-even</div><div class="v" id="fP">-</div></div>
          <div class="fact"><div class="k">Identifiable as</div><div class="v" id="fConf">-</div></div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start;margin-bottom:10px">
          <div class="mx-ctl"><label>Hitter (exact zone)</label>
            <input list="mHitters" id="mHit" class="abs-inp" placeholder="League average" style="width:200px">
            <datalist id="mHitters"></datalist>
            <div style="font-size:12px;color:var(--text-muted);margin-top:5px" id="mZone"></div>
            <label style="margin-top:12px">Gameday plate_x / plate_z (ft)</label>
            <div style="display:flex;gap:6px"><input id="mX" class="abs-inp" type="number" step="0.01" placeholder="plate_x" style="width:100px"><input id="mZ" class="abs-inp" type="number" step="0.01" placeholder="plate_z" style="width:100px"></div>
          </div>
          <div class="mx-ctl"><label>Or click where the ball crossed - <span id="mLoc" style="color:var(--text-primary)"></span></label>
            <svg id="mPlot" class="zplot" viewBox="0 0 224 288" width="224" height="288">
              <rect id="zEdge" fill="none" stroke="var(--accent)" stroke-dasharray="4 4" stroke-width="1"></rect>
              <rect id="zRect" fill="none" stroke="var(--text-primary)" stroke-width="1.5"></rect>
              <circle id="zBall" fill="none" stroke="var(--accent)" stroke-width="2"></circle>
            </svg></div>
        </div>
        <div class="verdict" id="mVerd"><span class="word">-</span><span class="why"></span></div>
       </div>`;
    bindViewTabs();
    // controls
    const seg = (id, key, parse) => p.querySelectorAll('#' + id + ' button').forEach(btn => btn.addEventListener('click', () => {
      p.querySelectorAll('#' + id + ' button').forEach(x => x.setAttribute('aria-pressed', 'false'));
      btn.setAttribute('aria-pressed', 'true'); state[key] = parse ? parse(btn.dataset.v) : btn.dataset.v; drawGrid(); drawPanel();
    }));
    seg('mK', 'k', v => +v); seg('mHalf', 'half'); seg('mOuts', 'outs', v => +v); seg('mSide', 'side');
    p.querySelectorAll('#mBases .chip').forEach(ch => ch.addEventListener('click', () => {
      const i = +ch.dataset.b; state.bases[i] = !state.bases[i]; ch.setAttribute('aria-pressed', String(state.bases[i])); drawGrid(); drawPanel();
    }));
    const scoreTxt = () => state.lead === 0 ? 'Tie game' : (state.lead > 0 ? 'Batting up ' + state.lead : 'Batting down ' + (-state.lead));
    p.querySelector('#mUp').addEventListener('click', () => { state.lead = Math.min(6, state.lead + 1); p.querySelector('#mScore').textContent = scoreTxt(); drawGrid(); drawPanel(); });
    p.querySelector('#mDown').addEventListener('click', () => { state.lead = Math.max(-6, state.lead - 1); p.querySelector('#mScore').textContent = scoreTxt(); drawGrid(); drawPanel(); });
    // zone plot + hitter + coords
    const zr = p.querySelector('#zRect'), ze = p.querySelector('#zEdge');
    function drawZone() {
      const x0 = 112 - ZHW * PXIN, y0 = 288 - (state.ztop - PLOT_Z0) * PXIN;
      zr.setAttribute('x', x0); zr.setAttribute('y', y0); zr.setAttribute('width', 2 * ZHW * PXIN); zr.setAttribute('height', (state.ztop - state.zbot) * PXIN);
      const off = THR * PXIN; ze.setAttribute('x', x0 - off); ze.setAttribute('y', y0 - off); ze.setAttribute('width', 2 * ZHW * PXIN + 2 * off); ze.setAttribute('height', (state.ztop - state.zbot) * PXIN + 2 * off);
    }
    drawZone();
    p.querySelector('#mPlot').addEventListener('click', e => {
      const r = e.currentTarget.getBoundingClientRect(), sx = (e.clientX - r.left) * 224 / r.width, sy = (e.clientY - r.top) * 288 / r.height;
      state.px = (sx - 112) / PXIN; state.pz = (288 - sy) / PXIN + PLOT_Z0;
      p.querySelector('#mX').value = (state.px / 12).toFixed(2); p.querySelector('#mZ').value = (state.pz / 12).toFixed(2); drawPanel();
    });
    p.querySelector('#mHitters').innerHTML = core.zones.map(z => `<option value="${esc(z.n)}"></option>`).join('');
    p.querySelector('#mZone').textContent = 'zone 3.30 / 1.60 ft (league average)';
    p.querySelector('#mHit').addEventListener('change', e => {
      const z = core.zones.find(x => x.n === e.target.value);
      if (z) { state.ztop = z.t * 12; state.zbot = z.b * 12; p.querySelector('#mZone').textContent = `zone ${z.t.toFixed(2)} / ${z.b.toFixed(2)} ft (${z.n})`; }
      else { state.ztop = 39.6; state.zbot = 19.2; p.querySelector('#mZone').textContent = 'zone 3.30 / 1.60 ft (league average)'; }
      drawZone(); drawPanel();
    });
    const ex = () => { const x = parseFloat(p.querySelector('#mX').value), z = parseFloat(p.querySelector('#mZ').value); if (!isNaN(x)) state.px = x * 12; if (!isNaN(z)) state.pz = z * 12; drawPanel(); };
    p.querySelector('#mX').addEventListener('input', ex); p.querySelector('#mZ').addEventListener('input', ex);
    drawGrid(); drawPanel();

    function drawGrid() {
      const mx = p.querySelector('#mGrid');
      let h = '<thead><tr><th></th>' + INN.map(i => `<th>${i === 10 ? '10+' : i}</th>`).join('') + '</tr></thead><tbody>';
      for (const [b, s] of COUNTS) {
        h += `<tr><th class="rowh">${b}–${s}</th>`;
        for (const inn of INN) {
          const pp = pstarFor(b, s, inn), col = heat(pp), sel = (state.sel.b === b && state.sel.s === s && state.sel.inning === inn) ? ' sel' : '';
          const txt = col.dark ? '#f7f2e9' : '#1a1612';
          h += `<td><button class="cell${sel}" style="background:${col.bg};color:${txt}" data-b="${b}" data-s="${s}" data-i="${inn}">${Math.round(pp * 100)}</button></td>`;
        }
        h += '</tr>';
      }
      mx.innerHTML = h + '</tbody>';
      mx.querySelectorAll('.cell').forEach(c => c.addEventListener('click', () => {
        state.sel = { b: +c.dataset.b, s: +c.dataset.s, inning: +c.dataset.i }; drawGrid(); drawPanel();
      }));
      const stops = []; for (let i = 0; i <= 10; i++) stops.push(heat(0.8 * i / 10).bg + ' ' + (i * 10) + '%');
      p.querySelector('#mGrad').style.background = 'linear-gradient(90deg,' + stops.join(',') + ')';
    }
    function locText(loc) { return loc > 0 ? loc.toFixed(2).replace(/\.?0+$/, '') + ' in INTO the zone' : loc < 0 ? (-loc).toFixed(2).replace(/\.?0+$/, '') + ' in OFF the zone' : 'grazing the edge'; }
    function drawPanel() {
      const { b, s, inning } = state.sel, g = gainFor(b, s, inning), c = costFor(inning), pstar = c / (Math.max(g, 1e-4) + c);
      const { loc, reg } = pitchGeom(), m = state.side === 'fld' ? loc : -loc, conf = posterior(state.side + '|' + reg, m);
      const wouldWin = state.side === 'fld' ? loc >= 0 : loc < 0, ruling = loc >= 0 ? 'strike' : 'ball';
      const lead = state.lead === 0 ? 'tie game' : (state.lead > 0 ? `batting up ${state.lead}` : `batting down ${-state.lead}`);
      const on = ['1B', '2B', '3B'].filter((_, i) => state.bases[i]);
      p.querySelector('#mState').innerHTML = `<b>${b}–${s}</b> · <b>${inning === 10 ? 'extras' : ordinal(inning)}, ${state.half}</b> · ${state.outs} out · ${on.length ? on.join(' & ') + ' on' : 'bases empty'} · ${lead} · <b>${state.k}</b> challenge${state.k > 1 ? 's' : ''} left`;
      p.querySelector('#fG').textContent = g.toFixed(2); p.querySelector('#fC').textContent = c.toFixed(2);
      p.querySelector('#fP').textContent = Math.round(pstar * 100) + '%'; p.querySelector('#fConf').textContent = Math.round(conf * 100) + '%';
      p.querySelector('#mLoc').textContent = locText(loc) + ' · ' + reg + ' edge';
      const ball = p.querySelector('#zBall'); ball.setAttribute('cx', 112 + state.px * PXIN); ball.setAttribute('cy', 288 - (state.pz - PLOT_Z0) * PXIN); ball.setAttribute('r', THR * PXIN);
      const need = neededInches(state.side + '|' + reg, pstar), roleName = state.side === 'fld' ? 'catcher' : 'hitter';
      const needTxt = need == null ? null : (need < 0.05 ? (state.side === 'fld' ? 'that grazes the zone' : 'that slips off the edge') : (state.side === 'fld' ? `${need.toFixed(1)} in or more into the zone` : `${need.toFixed(1)} in or more off the zone`));
      const truth = wouldWin ? `ABS would overturn this (true ${ruling})` : `ABS would uphold the call (true ${ruling})`;
      const v = p.querySelector('#mVerd');
      if (conf >= pstar) { v.className = 'verdict go'; v.innerHTML = `<span class="word">Challenge</span><span class="why">${truth}, and it's identifiable: ${Math.round(conf * 100)}% clears the ${Math.round(pstar * 100)}% bar. Rule of thumb: challenge any pitch ${needTxt}.</span>`; }
      else if (need == null) { v.className = 'verdict hold'; v.innerHTML = `<span class="word">Hold</span><span class="why">${truth}, but no ${roleName} can reach ${Math.round(pstar * 100)}% certainty by eye here, so it isn't worth a challenge in the moment. Save it.</span>`; }
      else { v.className = 'verdict hold'; v.innerHTML = `<span class="word">Hold</span><span class="why">${truth}. A ${roleName} could only be ${Math.round(conf * 100)}% sure, under the ${Math.round(pstar * 100)}% bar. It becomes a good challenge for a pitch ${needTxt}.</span>`; }
    }
  }

  // ================= FILM ROOM =================
  async function renderFilm() {
    const p = el();
    p.innerHTML = viewTabs() + `<h2>Film room</h2><p class="abs-sub">Loading clips...</p>`;
    bindViewTabs();
    if (!events) { try { events = (await fetch('data/abs_challenge_events_2026.json').then(r => r.json())).events; } catch (e) { events = []; } }
    if (state.view !== 'film') return;
    const rows = events.map(e => ({
      date: e.date, player: e.player, team: e.team, type: e.type, result: e.result,
      count: e.count, inning: e.inning, half: (e.half || '').slice(0, 3),
      marginIn: e.marginIn, ev: +(+e.ev).toFixed(2), playId: e.playId
    }));
    p.innerHTML = viewTabs() +
      `<h2>Film room</h2>
       <p class="abs-sub">Every challenge and counted miss with its Savant clip. Margin = inches in the challenger's favor (negative = the call was right). Sorted by decision EV; search a player to pull their reel. Showing up to 500 rows.</p>
       <div class="abs-bar"><input type="search" id="fq" placeholder="Search player or team"><span class="abs-count" id="fcnt"></span></div>
       <div class="abs-tblwrap"><table id="ftbl"></table></div>`;
    bindViewTabs();
    const cols = [['date', 'Date', 'l'], ['player', 'Player', 'l'], ['team', 'Tm', 'l'], ['type', 'Type', 'l'], ['result', 'Result', 'l'], ['count', 'Cnt'], ['inning', 'Inn'], ['half', 'Half', 'l'], ['marginIn', 'Margin'], ['ev', 'EV'], ['playId', 'Video', 'l']];
    let fsort = 'ev', fdir = -1, fq = '';
    function draw() {
      let r = rows.slice();
      if (fq) { const q = fq.toLowerCase(); r = r.filter(x => (x.player || '').toLowerCase().includes(q) || String(x.team).toLowerCase().includes(q)); }
      r.sort((a, b) => { const x = a[fsort], y = b[fsort]; if (x == null) return 1; if (y == null) return -1; return (x < y ? -1 : x > y ? 1 : 0) * fdir * (typeof x === 'string' ? -1 : 1); });
      const tot = r.length; r = r.slice(0, 500);
      let h = '<thead><tr>' + cols.map(c => `<th class="${c[2] || ''}" data-k="${c[0]}">${c[1]}</th>`).join('') + '</tr></thead><tbody>';
      for (const x of r) h += '<tr>' + cols.map(c => {
        if (c[0] === 'playId') return `<td class="l"><a class="abs-vid" href="https://baseballsavant.mlb.com/sporty-videos?playId=${x.playId}" target="_blank" rel="noopener">&#9654; watch</a></td>`;
        const v = x[c[0]]; const cl = c[0] === 'ev' ? (v > 0.005 ? 'pos' : v < -0.005 ? 'neg' : '') : (['player', 'team', 'date', 'type', 'result', 'half'].includes(c[0]) ? 'l' : 'dim');
        return `<td class="${cl}">${c[0] === 'ev' || c[0] === 'marginIn' ? (v).toFixed(2) : v}</td>`;
      }).join('') + '</tr>';
      p.querySelector('#ftbl').innerHTML = h + '</tbody>';
      p.querySelector('#fcnt').textContent = tot > 500 ? `${tot} rows (showing 500)` : tot + ' rows';
      p.querySelectorAll('#ftbl th').forEach(th => th.addEventListener('click', () => { const k = th.dataset.k; if (fsort === k) fdir *= -1; else { fsort = k; fdir = -1; } draw(); }));
    }
    p.querySelector('#fq').addEventListener('input', e => { fq = e.target.value; draw(); });
    draw();
  }

  async function render() {
    injectStyles();
    const p = el(); if (!p) return;
    if (!core) { p.innerHTML = `<p class="abs-sub" style="padding:20px">Loading ABS data...</p>`; try { await ensureCore(); } catch (e) { p.innerHTML = `<p class="abs-sub" style="padding:20px">Could not load ABS data.</p>`; return; } }
    if (state.view === 'leaders') renderLeaders();
    else if (state.view === 'matrix') renderMatrix();
    else renderFilm();
  }

  return { render: render, setView: function (v) { state.view = v; } };
})();
