(function () {
  // ---- State ----
  var currentTab = 'pitcherStats';
  var currentSection = 'pitchers';  // 'home', 'pitchers', 'hitters'
  var selectedPitchTypes = []; // empty = all; or array of selected types
  var allData = []; // current filtered + sorted data (full, before pagination)
  var columnRangeFilters = {}; // { colKey: { min: number|null, max: number|null } }

  // Tab → section mapping
  var TAB_SECTION = {
    pitcherStats: 'pitchers', pitchMetrics: 'pitchers',
    pitcherBattedBall: 'pitchers', pitcherSwingDecisions: 'pitchers',
    hitterStats: 'hitters', hitterBattedBall: 'hitters',
    hitterSwingDecisions: 'hitters', hitterBatTracking: 'hitters',
    hitterPitch: 'hitters'
  };

  // Tab → data source mapping
  var TAB_DATA = {
    pitcherStats: 'pitcher', pitchMetrics: 'pitch',
    pitcherBattedBall: 'pitcher', pitcherSwingDecisions: 'pitcher',
    hitterStats: 'hitter', hitterBattedBall: 'hitter',
    hitterSwingDecisions: 'hitter', hitterBatTracking: 'hitter',
    hitterPitch: 'hitterPitch'
  };

  // Tab → hash route mapping
  var TAB_ROUTE = {
    pitcherStats: 'pitchers/stats', pitchMetrics: 'pitchers/pitch-metrics',
    pitcherBattedBall: 'pitchers/batted-ball', pitcherSwingDecisions: 'pitchers/plate-discipline',
    hitterStats: 'hitters/stats', hitterBattedBall: 'hitters/batted-ball',
    hitterSwingDecisions: 'hitters/plate-discipline', hitterBatTracking: 'hitters/bat-tracking',
    hitterPitch: 'hitters/pitch-type'
  };

  // Hash route → tab mapping (reverse of TAB_ROUTE)
  var ROUTE_TAB = {};
  Object.keys(TAB_ROUTE).forEach(function (t) { ROUTE_TAB[TAB_ROUTE[t]] = t; });

  // Old tab names → new tab names (backward compat)
  var OLD_TAB_MAP = {
    pitcher: 'pitcherStats', pitch: 'pitchMetrics',
    hitterStats: 'hitterStats', hitterBattedBall: 'hitterBattedBall',
    hitterSwingDecisions: 'hitterSwingDecisions', hitterPitch: 'hitterPitch'
  };

  // Tabs that show pitch type filter
  var PITCH_TYPE_TABS = {
    pitchMetrics: true, hitterPitch: true,
    pitcherBattedBall: true, pitcherSwingDecisions: true,
    hitterBattedBall: true, hitterSwingDecisions: true,
    hitterBatTracking: true
  };

  function isHitterTab(tab) {
    return TAB_SECTION[tab] === 'hitters';
  }

  function isPitcherTab(tab) {
    return TAB_SECTION[tab] === 'pitchers';
  }

  // ---- DOM refs ----
  var teamSelect, throwsSelect, vsHandSelect, minCountInput, minSwingsInput, searchInput;
  var minIpInput, minTbfInput, minBipInput, minPitcherSwingsInput;
  var dateStartInput, dateEndInput;
  var currentGameType = null; // 'ST' or 'RS'
  var sidePanel, panelOverlay, panelClose;

  // ---- Init ----
  // Detect ?roc=1 URL parameter for hidden ROC team filter
  var rocMode = (new URLSearchParams(window.location.search)).get('roc') === '1';
  window._rocMode = rocMode;

  function init() {
    DataStore.load().then(function () {
      return Aggregator.load(DataStore.active().microData);
    }).then(function () {
      if (!DataStore.metadata) {
        document.getElementById('no-results').textContent = 'Failed to load data.';
        document.getElementById('no-results').style.display = '';
        return;
      }
      setupDOM();
      setupFilters();
      setupTabs();
      setupToolbar();
      setupPagination();
      setupSidePanel();
      setupCompareModal();
      setupPercentileTooltips();
      setupKeyboardNav();
      setupColumnSettings();
      setupRangeFilters();
      setupDarkMode();

      // Populate home page counts
      var pitcherCount = document.getElementById('home-pitcher-count');
      var hitterCount = document.getElementById('home-hitter-count');
      var rocTeamsInit = (DataStore.metadata.rocTeams || []);
      if (pitcherCount && DataStore.pitcherData) {
        var mlbPitchers = DataStore.pitcherData.filter(function(r) { return rocTeamsInit.indexOf(r.team) === -1; });
        pitcherCount.textContent = mlbPitchers.length + ' pitchers';
      }
      if (hitterCount && DataStore.hitterData) {
        var mlbHitters = DataStore.hitterData.filter(function(r) { return rocTeamsInit.indexOf(r.team) === -1; });
        hitterCount.textContent = mlbHitters.length + ' hitters';
      }

      // Player page back button
      document.getElementById('player-back').addEventListener('click', function () {
        PlayerPage.close();
      });

      // Handle browser navigation (back/forward, hash changes)
      window.addEventListener('hashchange', function () {
        handleRoute();
      });

      // Initial routing
      handleRoute();
    });
  }

  function handleRoute() {
    var hash = window.location.hash.replace(/^#/, '');

    // Player page route
    if (hash.indexOf('player=') === 0) {
      var mlbId = hash.split('=')[1];
      if (mlbId && !PlayerPage.isOpen) {
        PlayerPage.open(mlbId);
      }
      return;
    }

    // Close player page if open
    if (PlayerPage.isOpen) {
      PlayerPage.close();
    }

    // Home page
    if (!hash || hash === 'home') {
      showHome();
      return;
    }

    // Backward compat: old format like "tab=pitcher&team=NYY"
    if (hash.indexOf('tab=') !== -1) {
      var oldParams = Utils.readHash();
      var newTab = OLD_TAB_MAP[oldParams.tab] || oldParams.tab || 'pitcherStats';
      // Restore filter state from old params
      if (oldParams.team) teamSelect.value = oldParams.team;
      if (oldParams.throws) throwsSelect.value = oldParams.throws;
      if (oldParams.vsHand) vsHandSelect.value = oldParams.vsHand;
      if (oldParams.min) minCountInput.value = oldParams.min;
      if (oldParams.search) searchInput.value = oldParams.search;
      if (oldParams.sort) Leaderboard.currentSort.key = oldParams.sort;
      if (oldParams.dir) Leaderboard.currentSort.dir = oldParams.dir;
      if (oldParams.page) Leaderboard.currentPage = parseInt(oldParams.page, 10) || 1;
      navigateToTab(newTab);
      return;
    }

    // New route format: "pitchers/stats?team=NYY&throws=R"
    var parts = hash.split('?');
    var routePart = parts[0];
    // Backward compat: old swing-decisions → plate-discipline
    if (routePart === 'pitchers/swing-decisions') routePart = 'pitchers/plate-discipline';
    if (routePart === 'hitters/swing-decisions') routePart = 'hitters/plate-discipline';
    var tab = ROUTE_TAB[routePart];
    if (tab) {
      // Parse query params and apply filters before navigating
      if (parts[1]) {
        var qp = {};
        parts[1].split('&').forEach(function (p) {
          var kv = p.split('=');
          qp[kv[0]] = decodeURIComponent(kv[1] || '');
        });
        if (qp.team) teamSelect.value = qp.team;
        if (qp.throws) throwsSelect.value = qp.throws;
        if (qp.vsHand) vsHandSelect.value = qp.vsHand;
        if (qp.min) minCountInput.value = qp.min;
        if (qp.search) searchInput.value = qp.search;
        if (qp.sort) Leaderboard.currentSort.key = qp.sort;
        if (qp.dir) Leaderboard.currentSort.dir = qp.dir;
        if (qp.page) Leaderboard.currentPage = parseInt(qp.page, 10) || 1;
        if (qp.dateStart) dateStartInput.value = qp.dateStart;
        if (qp.dateEnd) dateEndInput.value = qp.dateEnd;
        if (qp.pitch) {
          selectedPitchTypes = qp.pitch.split(',');
        }
      }
      navigateToTab(tab, true);  // true = don't push hash (already there)
    } else {
      // Unknown route — go home
      showHome();
    }
  }

  function showHome() {
    currentSection = 'home';
    document.getElementById('home-page').style.display = '';
    document.querySelector('.controls').style.display = 'none';
    document.querySelector('.toolbar').style.display = 'none';
    document.querySelector('.table-wrapper').style.display = 'none';
    document.getElementById('pagination').style.display = 'none';
    var banner = document.getElementById('tab-banner');
    if (banner) banner.style.display = 'none';

    // Update section tabs
    document.querySelectorAll('.section-tab').forEach(function (t) { t.classList.remove('active'); });
    var homeBtn = document.querySelector('.section-tab[data-section="home"]');
    if (homeBtn) homeBtn.classList.add('active');

    // Hide subtabs
    document.getElementById('pitcher-subtabs').style.display = 'none';
    document.getElementById('hitter-subtabs').style.display = 'none';
  }

  function showLeaderboard() {
    document.getElementById('home-page').style.display = 'none';
    document.querySelector('.controls').style.display = '';
    document.querySelector('.toolbar').style.display = '';
    document.querySelector('.table-wrapper').style.display = '';
    document.getElementById('pagination').style.display = '';
  }

  function navigateToTab(tab, skipHash) {
    currentTab = tab;
    currentSection = TAB_SECTION[tab];

    // Update URL hash
    if (!skipHash) {
      window.location.hash = TAB_ROUTE[tab];
    }

    showLeaderboard();

    // Update section tabs
    document.querySelectorAll('.section-tab').forEach(function (t) { t.classList.remove('active'); });
    var sectionBtn = document.querySelector('.section-tab[data-section="' + currentSection + '"]');
    if (sectionBtn) sectionBtn.classList.add('active');

    // Show/hide subtab bars
    document.getElementById('pitcher-subtabs').style.display = currentSection === 'pitchers' ? '' : 'none';
    document.getElementById('hitter-subtabs').style.display = currentSection === 'hitters' ? '' : 'none';

    // Update active subtab
    document.querySelectorAll('.nav-subtabs .tab').forEach(function (t) { t.classList.remove('active'); });
    var activeTab = document.querySelector('.tab[data-tab="' + tab + '"]');
    if (activeTab) activeTab.classList.add('active');

    // Reset state for new tab
    Leaderboard.currentSort = { key: isHitterTab(currentTab) ? 'hitter' : 'pitcher', dir: 'asc' };
    Leaderboard.currentPage = 1;
    Leaderboard.keyboardFocusIndex = -1;

    // Show/hide pitch type filter
    document.getElementById('pitch-type-filter-group').style.display =
      PITCH_TYPE_TABS[currentTab] ? '' : 'none';

    // Show/hide min swings filter (hitter tabs except hitterPitch and hitterBattedBall)
    document.getElementById('min-swings-filter-group').style.display =
      (isHitterTab(currentTab) && currentTab !== 'hitterPitch' && currentTab !== 'hitterBattedBall') ? '' : 'none';

    // Show/hide pitcher-specific filters
    document.getElementById('min-ip-filter-group').style.display =
      currentTab === 'pitcherStats' ? '' : 'none';
    document.getElementById('min-tbf-filter-group').style.display =
      currentTab === 'pitcherStats' ? '' : 'none';
    document.getElementById('min-bip-filter-group').style.display =
      (currentTab === 'pitcherBattedBall' || currentTab === 'hitterBattedBall') ? '' : 'none';
    document.getElementById('min-pitcher-swings-filter-group').style.display =
      currentTab === 'pitcherSwingDecisions' ? '' : 'none';

    // Show SP/RP role filter on all pitcher tabs
    var isPitcherTab = currentTab === 'pitcherStats' || currentTab === 'pitchMetrics' ||
                       currentTab === 'pitcherBattedBall' || currentTab === 'pitcherSwingDecisions';
    document.getElementById('role-filter-group').style.display = isPitcherTab ? '' : 'none';

    // Hide Min Pitches on pitcherStats (uses Min IP / Min TBF instead)
    document.getElementById('min-count').parentElement.style.display =
      currentTab === 'pitcherStats' ? 'none' : '';

    // Rebuild pitch chips
    selectedPitchTypes = [];
    if (currentTab === 'hitterPitch') {
      buildHitterPitchChips(false);
    } else if (PITCH_TYPE_TABS[currentTab]) {
      buildPitchChipsWithAll();
    } else {
      buildPitchChips();
    }

    // Update labels
    var throwsLabel = document.querySelector('#throws-filter-group label');
    if (throwsLabel) {
      throwsLabel.textContent = isHitterTab(currentTab) ? 'Bats' : 'Throws';
    }
    var minCountLabel = document.querySelector('[for="min-count"]');
    var isMinPA = isHitterTab(currentTab) && currentTab !== 'hitterPitch';
    if (minCountLabel) {
      minCountLabel.textContent = isMinPA ? 'Min PA' : 'Min Pitches';
    }
    // Update dropdown options based on whether this is PA or pitch count
    var savedVal = minCountInput.value;
    var paOpts = [['Q','Qualified'],['1','1'],['10','10'],['25','25'],['50','50'],['75','75'],['100','100'],['150','150']];
    var pitchOpts = [['Q','Qualified'],['1','1'],['10','10'],['25','25'],['50','50'],['100','100'],['150','150'],['200','200']];
    var opts = isMinPA ? paOpts : pitchOpts;
    minCountInput.innerHTML = '';
    for (var oi = 0; oi < opts.length; oi++) {
      var o = document.createElement('option');
      o.value = opts[oi][0]; o.textContent = opts[oi][1];
      minCountInput.appendChild(o);
    }
    // Restore previous value if it exists in new options, otherwise default to Q
    var found = false;
    for (var oi2 = 0; oi2 < minCountInput.options.length; oi2++) {
      if (minCountInput.options[oi2].value === savedVal) { found = true; break; }
    }
    minCountInput.value = found ? savedVal : 'Q';
    updateVsHandLabels();
    searchInput.placeholder = isHitterTab(currentTab) ? 'Hitter name...' : 'Pitcher name...';

    // Hide compare button on hitter tabs
    document.getElementById('compare-btn').style.display = isHitterTab(currentTab) ? 'none' : '';

    // Tab banner
    var banner = document.getElementById('tab-banner');
    if (banner) {
      banner.style.display = 'none';
    }

    // Reset range filters
    columnRangeFilters = {};
    updateRangeFilterBadge();

    refresh();
  }

  function setupDOM() {
    teamSelect = document.getElementById('team-filter');
    throwsSelect = document.getElementById('throws-filter');
    vsHandSelect = document.getElementById('vs-hand-filter');
    minCountInput = document.getElementById('min-count');
    minSwingsInput = document.getElementById('min-swings');
    minIpInput = document.getElementById('min-ip');
    minTbfInput = document.getElementById('min-tbf');
    minBipInput = document.getElementById('min-bip');
    minPitcherSwingsInput = document.getElementById('min-pitcher-swings');
    searchInput = document.getElementById('search-input');
    dateStartInput = document.getElementById('date-start');
    dateEndInput = document.getElementById('date-end');
    sidePanel = document.getElementById('side-panel');
    panelOverlay = document.getElementById('panel-overlay');
    panelClose = document.getElementById('panel-close');
  }

  // ---- Rebuild team dropdown based on current game type ----
  function rebuildTeamDropdown() {
    teamSelect.innerHTML = '<option value="all">All Teams</option>';
    var rocTeams = (DataStore.metadata.rocTeams || []);
    DataStore.metadata.teams.forEach(function(team) {
      if (currentGameType === 'RS' && team === 'WBC') return;
      // Hide ROC/AAA teams unless ?roc=1 URL parameter is present
      if (rocTeams.indexOf(team) !== -1 && !window._rocMode) return;
      var opt = document.createElement('option');
      opt.value = team;
      opt.textContent = team;
      teamSelect.appendChild(opt);
    });
  }

  // Expose current game type for player pages
  window.getCurrentGameType = function() { return currentGameType; };

  // ---- Filters ----
  function setupFilters() {
    // Populate team dropdown (will be rebuilt when game type changes)
    rebuildTeamDropdown();

    // Populate pitch type chips (will be rebuilt on tab switch if needed)
    buildPitchChips();

    // Set generated date
    var genDate = document.getElementById('generated-date');
    if (genDate) genDate.textContent = DataStore.metadata.generatedAt;
    var freshness = document.getElementById('data-freshness');
    if (freshness && DataStore.metadata.generatedAt) {
      freshness.textContent = '| Updated ' + DataStore.metadata.generatedAt;
    }

    // Set date range min/max from micro data dates
    if (Aggregator.loaded && Aggregator.data && Aggregator.data.lookups.dates.length > 0) {
      var dates = Aggregator.data.lookups.dates;
      dateStartInput.min = dates[0];
      dateStartInput.max = dates[dates.length - 1];
      dateEndInput.min = dates[0];
      dateEndInput.max = dates[dates.length - 1];
    }

    // Disable vs-hand and date filters if micro data not available
    if (!Aggregator.loaded) {
      vsHandSelect.disabled = true;
      vsHandSelect.title = 'Requires micro data (run process_data.py)';
      dateStartInput.disabled = true;
      dateEndInput.disabled = true;
      dateStartInput.title = 'Requires micro data';
      dateEndInput.title = 'Requires micro data';
    }

    // Filter listeners
    teamSelect.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    throwsSelect.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    vsHandSelect.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    minCountInput.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    minSwingsInput.addEventListener('input', function () { Leaderboard.currentPage = 1; refresh(); });
    minIpInput.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    minTbfInput.addEventListener('input', function () { Leaderboard.currentPage = 1; refresh(); });
    minBipInput.addEventListener('input', function () { Leaderboard.currentPage = 1; refresh(); });
    minPitcherSwingsInput.addEventListener('input', function () { Leaderboard.currentPage = 1; refresh(); });
    document.getElementById('role-filter').addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    dateStartInput.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    dateEndInput.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });

    // Game Type toggle (ST / Regular Season)
    function setGameType(type) {
      currentGameType = type;
      DataStore.gameType = type;
      DataStore.updateGlobals();

      // Reload aggregator with new micro data
      var microData = DataStore.active().microData;
      if (microData) {
        Aggregator.load(microData);
      } else {
        Aggregator.loaded = false;
      }

      // Clear date inputs (user can set them manually within this game type)
      dateStartInput.value = '';
      dateEndInput.value = '';

      // Update date range min/max from new micro data dates
      if (Aggregator.loaded && Aggregator.data && Aggregator.data.lookups.dates.length > 0) {
        var dates = Aggregator.data.lookups.dates;
        dateStartInput.min = dates[0];
        dateStartInput.max = dates[dates.length - 1];
        dateEndInput.min = dates[0];
        dateEndInput.max = dates[dates.length - 1];
      }

      // Rebuild team dropdown (WBC only in ST)
      rebuildTeamDropdown();

      // Update active button styling
      var btns = document.querySelectorAll('#game-type-toggle .game-type-btn');
      for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('active', btns[i].getAttribute('data-type') === type);
      }

      Leaderboard.currentPage = 1;
      refresh();
    }
    var gameTypeToggle = document.getElementById('game-type-toggle');
    if (gameTypeToggle) {
      gameTypeToggle.addEventListener('click', function (e) {
        var btn = e.target.closest('.game-type-btn');
        if (!btn) return;
        var type = btn.getAttribute('data-type');
        if (type === currentGameType) return;
        setGameType(type);
      });
      // Auto-default based on current date
      var today = new Date().toISOString().slice(0, 10);
      var defaultType = today >= '2026-03-25' ? 'RS' : 'ST';
      currentGameType = defaultType;
      DataStore.gameType = defaultType;
      DataStore.updateGlobals();

      // Reload aggregator with the correct micro data for default game type
      var defaultMicroData = DataStore.active().microData;
      if (defaultMicroData) {
        Aggregator.load(defaultMicroData);
      }

      var btns = document.querySelectorAll('#game-type-toggle .game-type-btn');
      for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('active', btns[i].getAttribute('data-type') === defaultType);
      }
    }

    var searchTimer = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { Leaderboard.currentPage = 1; refresh(); }, 200);
    });
  }

  // Standard pitch type ordering used across all tabs
  var PITCH_TYPE_ORDER = [
    'FF', 'SI', 'CF', '|',
    'FC', 'SL', 'ST', 'CU', 'SV', '|',
    'CH', 'FS', 'KN'
  ];

  // Ordered chip list for hitterPitch tab (adds All + categories before the standard order)
  var HITTER_PITCH_CHIP_ORDER = [
    'All', '|',
    'Hard', 'Breaking', 'Offspeed', '|'
  ].concat(PITCH_TYPE_ORDER);

  // Category chip colors
  var CATEGORY_CHIP_COLORS = {
    'All': '#888',
    'Hard': '#d62728',
    'Breaking': '#2ca02c',
    'Offspeed': '#ff7f0e'
  };

  function buildPitchChips() {
    var container = document.getElementById('pitch-type-chips');
    container.innerHTML = '';
    var available = DataStore.metadata.pitchTypes;

    PITCH_TYPE_ORDER.forEach(function (item) {
      if (item === '|') {
        var divider = document.createElement('span');
        divider.className = 'chip-divider';
        container.appendChild(divider);
        return;
      }
      // Only show chip if this pitch type exists in the data
      if (available.indexOf(item) === -1) return;

      var btn = document.createElement('button');
      btn.className = 'pitch-chip';
      btn.textContent = item;
      btn.setAttribute('data-pitch', item);
      var color = Utils.getPitchColor(item);
      btn.style.setProperty('--chip-bg', color);
      btn.style.borderColor = color;
      // For light-colored pitches, adjust text
      if (item === 'SI' || item === 'SV') btn.style.color = '';
      btn.title = Utils.pitchTypeLabel(item);

      btn.addEventListener('click', function () {
        togglePitchChip(item, btn);
        Leaderboard.currentPage = 1;
        refresh();
      });

      container.appendChild(btn);
    });
  }

  function buildPitchChipsWithAll() {
    var container = document.getElementById('pitch-type-chips');
    container.innerHTML = '';
    var available = DataStore.metadata.pitchTypes;

    selectedPitchTypes = ['All'];

    // Add "All" chip first
    var allBtn = document.createElement('button');
    allBtn.className = 'pitch-chip selected';
    allBtn.textContent = 'All';
    allBtn.setAttribute('data-pitch', 'All');
    allBtn.style.setProperty('--chip-bg', '#888');
    allBtn.style.borderColor = 'transparent';
    allBtn.style.backgroundColor = '#888';
    allBtn.addEventListener('click', function () {
      toggleHitterPitchChip('All');
      Leaderboard.currentPage = 1;
      refresh();
    });
    container.appendChild(allBtn);

    // Add divider
    var divider = document.createElement('span');
    divider.className = 'chip-divider';
    container.appendChild(divider);

    // Add individual pitch type chips
    PITCH_TYPE_ORDER.forEach(function (item) {
      if (item === '|') {
        var div = document.createElement('span');
        div.className = 'chip-divider';
        container.appendChild(div);
        return;
      }
      if (available.indexOf(item) === -1) return;

      var btn = document.createElement('button');
      btn.className = 'pitch-chip';
      btn.textContent = item;
      btn.setAttribute('data-pitch', item);
      var color = Utils.getPitchColor(item);
      btn.style.setProperty('--chip-bg', color);
      btn.style.borderColor = color;
      if (item === 'SI' || item === 'SV') btn.style.color = '';
      btn.title = Utils.pitchTypeLabel(item);

      btn.addEventListener('click', function () {
        toggleHitterPitchChip(item);
        Leaderboard.currentPage = 1;
        refresh();
      });

      container.appendChild(btn);
    });
  }

  function buildHitterPitchChips(preserveSelection) {
    var container = document.getElementById('pitch-type-chips');
    container.innerHTML = '';

    // Default to "All" selected if no preserved selection
    if (!preserveSelection) {
      selectedPitchTypes = ['All'];
    }

    HITTER_PITCH_CHIP_ORDER.forEach(function (item) {
      if (item === '|') {
        var divider = document.createElement('span');
        divider.className = 'chip-divider';
        container.appendChild(divider);
        return;
      }

      var btn = document.createElement('button');
      btn.className = 'pitch-chip';
      btn.textContent = item;
      btn.setAttribute('data-pitch', item);

      var color;
      if (CATEGORY_CHIP_COLORS[item]) {
        color = CATEGORY_CHIP_COLORS[item];
      } else {
        color = Utils.getPitchColor(item);
      }
      btn.style.setProperty('--chip-bg', color);
      btn.style.borderColor = color;
      if (item === 'SI' || item === 'SV') btn.style.color = '';

      // Set initial selected state
      if (selectedPitchTypes.indexOf(item) !== -1) {
        btn.classList.add('selected');
        btn.style.backgroundColor = color;
        btn.style.borderColor = 'transparent';
      }

      btn.addEventListener('click', function () {
        toggleHitterPitchChip(item);
        Leaderboard.currentPage = 1;
        refresh();
      });

      container.appendChild(btn);
    });
  }

  function toggleHitterPitchChip(pt) {
    var isAll = (pt === 'All');
    var idx = selectedPitchTypes.indexOf(pt);

    if (isAll) {
      // Clicking "All": if not selected, select it and deselect everything else
      if (idx === -1) {
        selectedPitchTypes = ['All'];
      }
      // If already selected, do nothing (can't deselect All by clicking it again — always need something)
    } else {
      // Clicking a non-All chip
      // First remove "All" if it's selected
      var allIdx = selectedPitchTypes.indexOf('All');
      if (allIdx !== -1) {
        selectedPitchTypes.splice(allIdx, 1);
      }

      if (idx === -1) {
        // Not accounting for possible shift from removing All
        selectedPitchTypes.push(pt);
      } else {
        // Recalculate idx since All removal may have shifted it
        var newIdx = selectedPitchTypes.indexOf(pt);
        if (newIdx !== -1) {
          selectedPitchTypes.splice(newIdx, 1);
        }
      }

      // If nothing selected after toggle, revert to "All"
      if (selectedPitchTypes.length === 0) {
        selectedPitchTypes = ['All'];
      }
    }

    // Re-render chips to update visual state
    updateHitterPitchChipVisuals();
  }

  function updateHitterPitchChipVisuals() {
    var container = document.getElementById('pitch-type-chips');
    var chips = container.querySelectorAll('.pitch-chip');
    chips.forEach(function (btn) {
      var pt = btn.getAttribute('data-pitch');
      var color = btn.style.getPropertyValue('--chip-bg');
      if (selectedPitchTypes.indexOf(pt) !== -1) {
        btn.classList.add('selected');
        btn.style.backgroundColor = color;
        btn.style.borderColor = 'transparent';
      } else {
        btn.classList.remove('selected');
        btn.style.backgroundColor = '';
        btn.style.borderColor = '';
      }
    });
  }

  function togglePitchChip(pt, btn) {
    var idx = selectedPitchTypes.indexOf(pt);
    if (idx === -1) {
      selectedPitchTypes.push(pt);
      btn.classList.add('selected');
      btn.style.backgroundColor = btn.style.getPropertyValue('--chip-bg');
      btn.style.borderColor = 'transparent';
    } else {
      selectedPitchTypes.splice(idx, 1);
      btn.classList.remove('selected');
      btn.style.backgroundColor = '';
      btn.style.borderColor = '';
    }
  }

  // ---- Tabs ----
  function setupTabs() {
    // Section tab clicks (Home / Pitchers / Hitters)
    document.querySelectorAll('.section-tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var section = btn.getAttribute('data-section');
        if (section === 'home') {
          window.location.hash = 'home';
        } else if (section === 'pitchers') {
          navigateToTab('pitcherStats');
        } else if (section === 'hitters') {
          navigateToTab('hitterStats');
        }
      });
    });

    // Subtab clicks
    document.querySelectorAll('.nav-subtabs .tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        var tabKey = tab.getAttribute('data-tab');
        navigateToTab(tabKey);
      });
    });
  }

  // ---- vs-Hand label helper ----
  function updateVsHandLabels() {
    if (!vsHandSelect) return;
    var opts = vsHandSelect.options;
    var isHitter = isHitterTab(currentTab);
    for (var i = 0; i < opts.length; i++) {
      if (opts[i].value === 'R') opts[i].textContent = isHitter ? 'RHP' : 'RHH';
      if (opts[i].value === 'L') opts[i].textContent = isHitter ? 'LHP' : 'LHH';
    }
  }

  // ---- Core refresh ----
  function _getMaxTeamGames() {
    var tg = Aggregator.loaded ? Aggregator.getTeamGamesPlayed() : {};
    var max = 0;
    for (var t in tg) { if (tg[t] > max) max = tg[t]; }
    return max;
  }

  function _resolveMinCount() {
    var val = minCountInput.value;
    if (val === 'Q') {
      // Qualified: hitters = 3.1 PA/team game, pitchers = 10 pitches (fallback)
      if (isHitterTab(currentTab) && currentTab !== 'hitterPitch') {
        return Math.round(_getMaxTeamGames() * 3.1) || 1;
      }
      return 10; // pitch tabs: just use 10 as reasonable default
    }
    return parseInt(val) || 1;
  }

  function _resolveMinIp() {
    var val = minIpInput.value;
    if (val === 'Q') {
      // Qualified: SP = 1.0 IP/game, RP = 0.1 IP/game
      var maxTg = _getMaxTeamGames();
      var role = document.getElementById('role-filter').value;
      if (role === 'RP') return Math.round(maxTg * 0.1 * 10) / 10 || 0;
      return Math.round(maxTg * 1.0 * 10) / 10 || 0; // default to SP threshold
    }
    return parseFloat(val) || 0;
  }

  function getFilters() {
    return {
      team: teamSelect.value,
      pitchTypes: (selectedPitchTypes.length === 0 || (selectedPitchTypes.length === 1 && selectedPitchTypes[0] === 'All')) ? 'all' : selectedPitchTypes,
      throws: throwsSelect.value,
      vsHand: vsHandSelect.value,
      minCount: currentTab === 'pitcherStats' ? 0 : _resolveMinCount(),
      minSwings: parseInt(minSwingsInput.value) || 1,
      minIp: currentTab === 'pitcherStats' ? _resolveMinIp() : 0,
      minTbf: currentTab === 'pitcherStats' ? (parseInt(minTbfInput.value) || 1) : 0,
      minBip: (currentTab === 'pitcherBattedBall' || currentTab === 'hitterBattedBall') ? (parseInt(minBipInput.value) || 1) : 0,
      minPitcherSwings: currentTab === 'pitcherSwingDecisions' ? (parseInt(minPitcherSwingsInput.value) || 1) : 0,
      search: searchInput.value.trim(),
      dateStart: dateStartInput.value || '',
      dateEnd: dateEndInput.value || '',
      role: document.getElementById('role-filter').value,
    };
  }

  // Columns hidden when viewing ROC (AAA) team data
  var ROC_HIDDEN_PITCHER = ['armAngle', 'runValue', 'rv100', 'xwOBA'];
  var ROC_HIDDEN_HITTER = ['xwOBA', 'xwOBAcon', 'batSpeed', 'swingLength', 'attackAngle', 'attackDirection', 'swingPathTilt', 'nCompSwings'];
  var ALL_ROC_HIDDEN = ROC_HIDDEN_PITCHER.concat(ROC_HIDDEN_HITTER);

  function refresh() {
    var filters = getFilters();
    var dataTab = TAB_DATA[currentTab] || 'pitcher';

    // When pitch types are selected, switch to pitch-level data sources
    var hasPitchTypeFilter = selectedPitchTypes.length > 0 && !(selectedPitchTypes.length === 1 && selectedPitchTypes[0] === 'All');

    if ((currentTab === 'pitcherSwingDecisions' || currentTab === 'pitcherBattedBall') && hasPitchTypeFilter) {
      dataTab = 'pitch';
    }
    if ((currentTab === 'hitterBattedBall' || currentTab === 'hitterSwingDecisions') && hasPitchTypeFilter) {
      dataTab = 'hitterPitch';
    }

    // ROC column visibility: hide columns that have no data for AAA teams
    var rocTeamsRefresh = (DataStore.metadata && DataStore.metadata.rocTeams) || [];
    var isROCTeam = rocTeamsRefresh.indexOf(filters.team) !== -1;

    // Clear previous ROC-specific hiding
    ALL_ROC_HIDDEN.forEach(function (k) {
      if (Leaderboard._rocHidden && Leaderboard._rocHidden[k]) {
        delete Leaderboard.hiddenColumns[k];
      }
    });
    Leaderboard._rocHidden = {};

    if (isROCTeam) {
      var toHide = isPitcherTab(currentTab) ? ROC_HIDDEN_PITCHER : ROC_HIDDEN_HITTER;
      toHide.forEach(function (k) {
        Leaderboard.hiddenColumns[k] = true;
        Leaderboard._rocHidden[k] = true;
      });
    }

    // Hide bat tracking tab for ROC (no bat tracking data for AAA)
    var batTrackingTab = document.querySelector('.tab[data-tab="hitterBatTracking"]');
    if (batTrackingTab) {
      batTrackingTab.style.display = isROCTeam ? 'none' : '';
    }
    // If on bat tracking tab and ROC selected, switch to hitterStats
    if (isROCTeam && currentTab === 'hitterBatTracking') {
      navigateToTab('hitterStats');
      return;
    }

    var data = DataStore.getFilteredDataV2(dataTab, filters);
    var columns = COLUMNS[currentTab];

    // Apply column range filters
    data = applyRangeFilters(data, columns);

    // Apply sort
    if (!Leaderboard.currentSort.key) {
      Leaderboard.currentSort = { key: isHitterTab(currentTab) ? 'hitter' : 'pitcher', dir: 'asc' };
    }

    var sortKey = Leaderboard.currentSort.key;
    var col = null;
    for (var i = 0; i < columns.length; i++) {
      if (columns[i].key === sortKey) { col = columns[i]; break; }
    }

    if (col && col.sortType) {
      var sk = col.sortKey || col.key;
      var dir = Leaderboard.currentSort.dir === 'asc' ? 1 : -1;
      data.sort(function (a, b) {
        var va = a[sk], vb = b[sk];
        if (va === null || va === undefined) { return vb === null || vb === undefined ? 0 : 1; }
        if (vb === null || vb === undefined) return -1;
        if (col.sortType === 'string') return dir * String(va).localeCompare(String(vb));
        return dir * (va - vb);
      });
    }

    allData = data;

    // Compute league-wide data (all teams) for league avg row
    var leagueFilters = {};
    for (var fk in filters) leagueFilters[fk] = filters[fk];
    leagueFilters.team = 'all';
    var leagueData = DataStore.getFilteredDataV2(dataTab, leagueFilters);
    leagueData = applyRangeFilters(leagueData, columns);

    Leaderboard.render(data, columns, {
      teamFilter: filters.team,
      leagueData: leagueData,
      pitchTypes: filters.pitchTypes
    });
    saveURLState();
  }

  // ---- Toolbar ----
  function setupToolbar() {
    // League average toggle (button removed — always on)
    var avgBtn = document.getElementById('league-avg-toggle');
    if (avgBtn) {
      avgBtn.addEventListener('click', function () {
        Leaderboard.showLeagueAvg = !Leaderboard.showLeagueAvg;
        avgBtn.classList.toggle('active', Leaderboard.showLeagueAvg);
        refresh();
      });
    }

    // Compact mode toggle
    (function () {
      var compactBtn = document.getElementById('compact-toggle');
      if (!compactBtn) return;
      if (localStorage.getItem('compactMode') === '1') {
        document.body.classList.add('compact');
        compactBtn.classList.add('active');
      }
      compactBtn.addEventListener('click', function () {
        document.body.classList.toggle('compact');
        var on = document.body.classList.contains('compact');
        compactBtn.classList.toggle('active', on);
        localStorage.setItem('compactMode', on ? '1' : '0');
      });
    })();

    // Export CSV
    document.getElementById('export-csv-btn').addEventListener('click', function () {
      var visCols = Leaderboard.getVisibleColumns(COLUMNS[currentTab]).filter(function (c) {
        return c.key !== '_rank' && !c.isCompare;
      });
      var csv = Utils.toCSV(allData, visCols);
      Utils.downloadFile(csv, 'leaderboard_' + currentTab + '.csv');
    });

    // Copy to clipboard
    document.getElementById('copy-clipboard-btn').addEventListener('click', function () {
      var visCols = Leaderboard.getVisibleColumns(COLUMNS[currentTab]).filter(function (c) {
        return c.key !== '_rank' && !c.isCompare;
      });
      var tsv = Utils.toTSV(allData, visCols);
      Utils.copyToClipboard(tsv);
      // Visual feedback
      var btn = document.getElementById('copy-clipboard-btn');
      var orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(function () { btn.textContent = orig; }, 1500);
    });
  }

  // ---- Pagination ----
  function setupPagination() {
    document.getElementById('page-prev').addEventListener('click', function () {
      if (Leaderboard.currentPage > 1) {
        Leaderboard.currentPage--;
        Leaderboard.keyboardFocusIndex = -1;
        refresh();
        scrollTableToTop();
      }
    });

    document.getElementById('page-next').addEventListener('click', function () {
      Leaderboard.currentPage++;
      Leaderboard.keyboardFocusIndex = -1;
      refresh();
      scrollTableToTop();
    });

    document.getElementById('page-size').addEventListener('change', function () {
      Leaderboard.pageSize = parseInt(this.value) || 0;
      Leaderboard.currentPage = 1;
      Leaderboard.keyboardFocusIndex = -1;
      refresh();
    });
  }

  function scrollTableToTop() {
    var container = document.getElementById('table-container');
    if (container) container.scrollTop = 0;
  }

  // ---- Side Panel ----
  function setupSidePanel() {
    window.App = window.App || {};

    App.openSidePanel = function (name, team, hand, rowData) {
      document.getElementById('panel-pitcher-name').textContent = name;
      var info = [];
      if (team) info.push(team);
      if (isHitterTab(currentTab)) {
        if (hand) info.push(hand === 'R' ? 'RHH' : hand === 'L' ? 'LHH' : hand === 'S' ? 'Switch' : hand);
      } else {
        if (hand) info.push(hand === 'R' ? 'RHP' : 'LHP');
      }
      document.getElementById('panel-pitcher-info').textContent = info.join(' | ');

      sidePanel.classList.add('open');
      panelOverlay.classList.add('visible');

      // Chart container and metrics table
      var chartContainer = sidePanel.querySelector('.chart-container');

      if (isHitterTab(currentTab)) {
        // Hide scatter chart for hitters
        if (chartContainer) chartContainer.style.display = 'none';
        ScatterChart.destroy();
        buildHitterPanelTable(name, team);
      } else {
        // Show scatter chart for pitchers
        if (chartContainer) chartContainer.style.display = '';
        ScatterChart.render(name, team);
        buildPanelMetricsTable(name, team);
      }
    };

    App.closeSidePanel = function () {
      sidePanel.classList.remove('open');
      panelOverlay.classList.remove('visible');
      ScatterChart.destroy();
      // Restore chart container visibility
      var chartContainer = sidePanel.querySelector('.chart-container');
      if (chartContainer) chartContainer.style.display = '';
      var active = document.querySelectorAll('.active-row');
      for (var i = 0; i < active.length; i++) active[i].classList.remove('active-row');
    };

    panelClose.addEventListener('click', App.closeSidePanel);
    panelOverlay.addEventListener('click', App.closeSidePanel);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        // Close compare modal if open
        var cm = document.getElementById('compare-modal');
        if (cm && cm.style.display !== 'none') {
          cm.style.display = 'none';
          return;
        }
        App.closeSidePanel();
      }
    });

  }

  function buildPanelMetricsTable(pitcherName, team) {
    var container = document.getElementById('panel-metrics-table');
    container.innerHTML = '';

    // Get pitch data for this pitcher
    var pitchData = DataStore.pitchData;
    if (!pitchData) return;

    var pitcherRows = pitchData.filter(function (r) { return r.pitcher === pitcherName && r.team === team; });
    if (pitcherRows.length === 0) return;

    // Sort by usage descending
    pitcherRows.sort(function (a, b) { return (b.usagePct || 0) - (a.usagePct || 0); });

    var metricCols = [
      { key: 'pitchType', label: 'Pitch', format: function (v) { return v; } },
      { key: 'usagePct', label: 'Usage', format: Utils.formatPct },
      { key: 'velocity', label: 'Velo', format: Utils.formatDecimal(1) },
      { key: 'maxVelo', label: 'Max Velo', format: Utils.formatDecimal(1) },
      { key: 'spinRate', label: 'Spin', format: Utils.formatInt },
      { key: 'breakTilt', label: 'Tilt', format: function (v) { return v || '--'; } },
      { key: 'indVertBrk', label: 'IVB', format: Utils.formatDecimal(1) },
      { key: 'horzBrk', label: 'HB', format: Utils.formatDecimal(1) },
      { key: 'swStrPct', label: 'Whiff%', format: Utils.formatPct },
    ];

    var table = document.createElement('table');
    var thead = document.createElement('thead');
    var headerTr = document.createElement('tr');
    metricCols.forEach(function (mc) {
      var th = document.createElement('th');
      th.textContent = mc.label;
      if (mc.key === 'pitchType') th.style.textAlign = 'left';
      headerTr.appendChild(th);
    });
    thead.appendChild(headerTr);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    pitcherRows.forEach(function (row) {
      var tr = document.createElement('tr');
      metricCols.forEach(function (mc) {
        var td = document.createElement('td');
        if (mc.key === 'pitchType') {
          var badge = document.createElement('span');
          badge.className = 'pitch-badge';
          badge.textContent = row[mc.key];
          var _bc = Utils.getPitchColor(row[mc.key]);
          badge.style.backgroundColor = _bc;
          badge.style.color = Utils.badgeTextColor(_bc);
          td.appendChild(badge);
          td.style.textAlign = 'left';
        } else {
          td.textContent = mc.format(row[mc.key]);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  function buildHitterPanelTable(hitterName, team) {
    var container = document.getElementById('panel-metrics-table');
    container.innerHTML = '';

    var details = window.HITTER_PITCH_DETAILS;
    var key = hitterName + '|' + (team || '');
    if (!details || !details[key]) return;

    var ptData = details[key];
    if (ptData.length === 0) return;

    var statCols = [
      { key: 'pitchType', label: 'Pitch', format: function (v) { return v; } },
      { key: 'count', label: '#', format: Utils.formatInt },
      { key: 'swingPct', label: 'Swing%', format: Utils.formatPct },
      { key: 'whiffPct', label: 'Whiff%', format: Utils.formatPct },
      { key: 'medEV', label: 'Avg EV', format: Utils.formatDecimal(1) },
    ];

    var table = document.createElement('table');
    var thead = document.createElement('thead');
    var headerTr = document.createElement('tr');
    statCols.forEach(function (mc) {
      var th = document.createElement('th');
      th.textContent = mc.label;
      if (mc.key === 'pitchType') th.style.textAlign = 'left';
      headerTr.appendChild(th);
    });
    thead.appendChild(headerTr);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    ptData.forEach(function (row) {
      var tr = document.createElement('tr');
      statCols.forEach(function (mc) {
        var td = document.createElement('td');
        if (mc.key === 'pitchType') {
          var badge = document.createElement('span');
          badge.className = 'pitch-badge';
          badge.textContent = row[mc.key];
          var _bc = Utils.getPitchColor(row[mc.key]);
          badge.style.backgroundColor = _bc;
          badge.style.color = Utils.badgeTextColor(_bc);
          td.appendChild(badge);
          td.style.textAlign = 'left';
        } else {
          td.textContent = mc.format(row[mc.key]);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  // ---- Compare Modal ----
  function setupCompareModal() {
    window.App = window.App || {};

    App.updateCompareButton = function () {
      var list = Leaderboard.getCompareList();
      var btn = document.getElementById('compare-btn');
      btn.textContent = 'Compare (' + list.length + ')';
      btn.disabled = list.length < 2;
    };

    document.getElementById('compare-btn').addEventListener('click', function () {
      var list = Leaderboard.getCompareList();
      if (list.length < 2) return;
      var modal = document.getElementById('compare-modal');
      modal.style.display = '';
      ScatterChart.renderCompare(list);
    });

    document.getElementById('compare-close').addEventListener('click', function () {
      document.getElementById('compare-modal').style.display = 'none';
      ScatterChart.destroyCompare();
    });
  }

  // ---- Percentile Tooltips ----
  function setupPercentileTooltips() {
    var tooltip = document.getElementById('pctl-tooltip');
    var tbody = document.getElementById('table-body');

    tbody.addEventListener('mouseover', function (e) {
      var td = e.target.closest('td[data-pctl]');
      if (!td) { tooltip.classList.remove('visible'); return; }
      var pctl = td.getAttribute('data-pctl');
      var label = td.getAttribute('data-col-label');
      var colKey = td.getAttribute('data-col-key');

      // Build tooltip text
      var text = pctl + 'th percentile';

      // Add league average if available
      var meta = DataStore.metadata;
      if (meta && meta.leagueAverages) {
        // Try to find which pitch type this row belongs to
        var tr = td.closest('tr');
        if (tr && tr._pitcherName) {
          // For simplicity, just show the percentile
        }
      }

      tooltip.textContent = text;
      tooltip.classList.add('visible');
    });

    tbody.addEventListener('mousemove', function (e) {
      if (tooltip.classList.contains('visible')) {
        tooltip.style.left = (e.clientX + 12) + 'px';
        tooltip.style.top = (e.clientY - 30) + 'px';
      }
    });

    tbody.addEventListener('mouseout', function (e) {
      if (!e.target.closest('td[data-pctl]')) {
        tooltip.classList.remove('visible');
      }
    });
  }

  // ---- Keyboard Navigation ----
  function setupKeyboardNav() {
    document.addEventListener('keydown', function (e) {
      // Only handle when not focused on an input
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;

      var tbody = document.getElementById('table-body');
      var rows = tbody.querySelectorAll('tr.clickable-row');
      if (rows.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        Leaderboard.keyboardFocusIndex = Math.min(Leaderboard.keyboardFocusIndex + 1, rows.length - 1);
        updateKeyboardFocus(rows);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        Leaderboard.keyboardFocusIndex = Math.max(Leaderboard.keyboardFocusIndex - 1, 0);
        updateKeyboardFocus(rows);
      } else if (e.key === 'Enter' && Leaderboard.keyboardFocusIndex >= 0) {
        e.preventDefault();
        rows[Leaderboard.keyboardFocusIndex].click();
      }
    });
  }

  function updateKeyboardFocus(rows) {
    for (var i = 0; i < rows.length; i++) {
      rows[i].classList.toggle('keyboard-focus', i === Leaderboard.keyboardFocusIndex);
    }
    if (Leaderboard.keyboardFocusIndex >= 0 && rows[Leaderboard.keyboardFocusIndex]) {
      rows[Leaderboard.keyboardFocusIndex].scrollIntoView({ block: 'nearest' });
    }
  }

  // ---- Range Filters ----
  function setupRangeFilters() {
    var btn = document.getElementById('range-filter-btn');
    var panel = document.getElementById('range-filter-panel');

    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      panel.classList.toggle('open');
      if (panel.classList.contains('open')) {
        buildRangeFilterPanel();
      }
    });

    // Close on outside click
    document.addEventListener('click', function (e) {
      if (!panel.contains(e.target) && e.target !== btn) {
        panel.classList.remove('open');
      }
    });
  }

  function isPercentageColumn(col) {
    return col.format === Utils.formatPct;
  }

  function buildRangeFilterPanel() {
    var panel = document.getElementById('range-filter-panel');
    panel.innerHTML = '';

    var columns = COLUMNS[currentTab];
    var currentGroup = '';

    columns.forEach(function (col) {
      if (col.sortType !== 'numeric') return;
      if (col.key === '_rank' || col.isCompare) return;

      // Group header
      if (col.group && col.group !== currentGroup) {
        currentGroup = col.group;
        var groupLabel = document.createElement('div');
        groupLabel.className = 'range-filter-group-label';
        groupLabel.textContent = currentGroup.charAt(0).toUpperCase() + currentGroup.slice(1);
        panel.appendChild(groupLabel);
      }

      var row = document.createElement('div');
      row.className = 'range-filter-row';

      var label = document.createElement('span');
      label.className = 'rf-label';
      label.textContent = col.label;
      row.appendChild(label);

      var existing = columnRangeFilters[col.key] || {};
      var isPct = isPercentageColumn(col);

      var minInput = document.createElement('input');
      minInput.type = 'number';
      minInput.placeholder = 'Min';
      minInput.step = 'any';
      if (existing.min !== null && existing.min !== undefined) {
        minInput.value = isPct ? (existing.min * 100) : existing.min;
      }

      var sep = document.createElement('span');
      sep.className = 'rf-sep';
      sep.textContent = '–';

      var maxInput = document.createElement('input');
      maxInput.type = 'number';
      maxInput.placeholder = 'Max';
      maxInput.step = 'any';
      if (existing.max !== null && existing.max !== undefined) {
        maxInput.value = isPct ? (existing.max * 100) : existing.max;
      }

      row.appendChild(minInput);
      row.appendChild(sep);
      row.appendChild(maxInput);
      panel.appendChild(row);

      // Debounced input handlers
      var debounceTimer = null;
      function onInput() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          var minVal = minInput.value !== '' ? parseFloat(minInput.value) : null;
          var maxVal = maxInput.value !== '' ? parseFloat(maxInput.value) : null;

          // Scale percentage inputs
          if (isPct) {
            if (minVal !== null) minVal = minVal / 100;
            if (maxVal !== null) maxVal = maxVal / 100;
          }

          if (minVal === null && maxVal === null) {
            delete columnRangeFilters[col.key];
          } else {
            columnRangeFilters[col.key] = { min: minVal, max: maxVal };
          }

          updateRangeFilterBadge();
          Leaderboard.currentPage = 1;
          refresh();
        }, 200);
      }

      minInput.addEventListener('input', onInput);
      maxInput.addEventListener('input', onInput);
    });

    // Clear All button
    var actions = document.createElement('div');
    actions.className = 'range-filter-actions';
    var clearBtn = document.createElement('button');
    clearBtn.className = 'rf-clear-btn';
    clearBtn.textContent = 'Clear All';
    clearBtn.addEventListener('click', function () {
      columnRangeFilters = {};
      updateRangeFilterBadge();
      buildRangeFilterPanel(); // rebuild to clear inputs
      Leaderboard.currentPage = 1;
      refresh();
    });
    actions.appendChild(clearBtn);
    panel.appendChild(actions);
  }

  function applyRangeFilters(data, columns) {
    var keys = Object.keys(columnRangeFilters);
    if (keys.length === 0) return data;

    return data.filter(function (row) {
      for (var i = 0; i < keys.length; i++) {
        var key = keys[i];
        var filter = columnRangeFilters[key];
        var val = row[key];

        // Exclude rows with null values for filtered columns
        if (val === null || val === undefined) return false;

        if (filter.min !== null && val < filter.min) return false;
        if (filter.max !== null && val > filter.max) return false;
      }
      return true;
    });
  }

  function updateRangeFilterBadge() {
    var badge = document.getElementById('range-filter-badge');
    var count = Object.keys(columnRangeFilters).length;
    if (count > 0) {
      badge.textContent = count;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  }

  // ---- Column Settings ----
  function setupColumnSettings() {
    var btn = document.getElementById('col-settings-btn');
    var panel = document.getElementById('col-settings-panel');

    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      panel.classList.toggle('open');
      if (panel.classList.contains('open')) {
        buildColumnSettingsPanel();
      }
    });

    // Close on outside click
    document.addEventListener('click', function (e) {
      if (!panel.contains(e.target) && e.target !== btn) {
        panel.classList.remove('open');
      }
    });
  }

  function buildColumnSettingsPanel() {
    var panel = document.getElementById('col-settings-panel');
    panel.innerHTML = '';

    var columns = COLUMNS[currentTab];
    var currentGroup = '';

    columns.forEach(function (col) {
      if (col.noToggle) return;

      // Group header
      if (col.group && col.group !== currentGroup) {
        currentGroup = col.group;
        var groupLabel = document.createElement('div');
        groupLabel.className = 'col-settings-group-label';
        groupLabel.textContent = currentGroup.charAt(0).toUpperCase() + currentGroup.slice(1);
        panel.appendChild(groupLabel);
      }

      var label = document.createElement('label');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !Leaderboard.hiddenColumns[col.key];
      cb.addEventListener('change', function () {
        if (cb.checked) {
          delete Leaderboard.hiddenColumns[col.key];
        } else {
          Leaderboard.hiddenColumns[col.key] = true;
        }
        refresh();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + col.label));
      panel.appendChild(label);
    });
  }

  // ---- Dark Mode ----
  function setupDarkMode() {
    var toggle = document.getElementById('dark-mode-toggle');
    var sunIcon = toggle.querySelector('.icon-sun');
    var moonIcon = toggle.querySelector('.icon-moon');

    // Check saved preference or system preference
    var saved = localStorage.getItem('darkMode');
    if (saved === 'true' || (saved === null && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      enableDark();
    }

    toggle.addEventListener('click', function () {
      if (document.body.classList.contains('dark')) {
        disableDark();
      } else {
        enableDark();
      }
      // Re-render to update percentile colors
      refresh();
    });

    function enableDark() {
      document.body.classList.add('dark');
      sunIcon.style.display = 'none';
      moonIcon.style.display = '';
      localStorage.setItem('darkMode', 'true');
    }

    function disableDark() {
      document.body.classList.remove('dark');
      sunIcon.style.display = '';
      moonIcon.style.display = 'none';
      localStorage.setItem('darkMode', 'false');
    }
  }

  // ---- URL State ----
  function saveURLState() {
    // Don't overwrite player page URL
    if (PlayerPage.isOpen) return;
    // Use new route format: #pitchers/stats?team=NYY&throws=R
    var route = TAB_ROUTE[currentTab] || 'pitchers/stats';
    var parts = [];
    if (teamSelect.value !== 'all') parts.push('team=' + teamSelect.value);
    if (throwsSelect.value !== 'all') parts.push('throws=' + throwsSelect.value);
    if (vsHandSelect.value !== 'all') parts.push('vsHand=' + vsHandSelect.value);
    if (minCountInput.value !== 'Q') parts.push('min=' + minCountInput.value);
    if (searchInput.value) parts.push('search=' + encodeURIComponent(searchInput.value));
    if (Leaderboard.currentSort.key) parts.push('sort=' + Leaderboard.currentSort.key);
    if (Leaderboard.currentSort.dir) parts.push('dir=' + Leaderboard.currentSort.dir);
    if (Leaderboard.currentPage > 1) parts.push('page=' + Leaderboard.currentPage);
    if (dateStartInput.value) parts.push('dateStart=' + dateStartInput.value);
    if (dateEndInput.value) parts.push('dateEnd=' + dateEndInput.value);
    if (selectedPitchTypes.length > 0) parts.push('pitch=' + selectedPitchTypes.join(','));
    var hash = route + (parts.length > 0 ? '?' + parts.join('&') : '');
    if (window.location.hash !== '#' + hash) {
      history.replaceState(null, '', '#' + hash);
    }
  }

  // applyURLState is now handled by handleRoute()

  // Start the app
  init();
})();
