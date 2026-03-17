(function () {
  // ---- State ----
  var currentTab = 'pitcher';
  var selectedPitchTypes = []; // empty = all; or array of selected types
  var allData = []; // current filtered + sorted data (full, before pagination)
  var columnRangeFilters = {}; // { colKey: { min: number|null, max: number|null } }

  function isHitterTab(tab) {
    return tab === 'hitterStats' || tab === 'hitterBattedBall' || tab === 'hitterSwingDecisions' || tab === 'hitterPitch';
  }

  // ---- DOM refs ----
  var teamSelect, throwsSelect, vsHandSelect, minCountInput, minSwingsInput, searchInput;
  var dateStartInput, dateEndInput;
  var sidePanel, panelOverlay, panelClose;

  // ---- Init ----
  function init() {
    Promise.all([DataStore.load(), Aggregator.load()]).then(function () {
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
      applyURLState();
      // Set initial filter visibility based on default tab
      document.getElementById('pitch-type-filter-group').style.display =
        (currentTab === 'pitch' || currentTab === 'hitterPitch') ? '' : 'none';
      document.getElementById('min-swings-filter-group').style.display =
        (isHitterTab(currentTab) && currentTab !== 'hitterPitch') ? '' : 'none';
      // Set initial vs-hand labels
      updateVsHandLabels();
      refresh();
    });
  }

  function setupDOM() {
    teamSelect = document.getElementById('team-filter');
    throwsSelect = document.getElementById('throws-filter');
    vsHandSelect = document.getElementById('vs-hand-filter');
    minCountInput = document.getElementById('min-count');
    minSwingsInput = document.getElementById('min-swings');
    searchInput = document.getElementById('search-input');
    dateStartInput = document.getElementById('date-start');
    dateEndInput = document.getElementById('date-end');
    sidePanel = document.getElementById('side-panel');
    panelOverlay = document.getElementById('panel-overlay');
    panelClose = document.getElementById('panel-close');
  }

  // ---- Filters ----
  function setupFilters() {
    // Populate team dropdown
    DataStore.metadata.teams.forEach(function (team) {
      var opt = document.createElement('option');
      opt.value = team;
      opt.textContent = team;
      teamSelect.appendChild(opt);
    });

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
    minCountInput.addEventListener('input', function () { Leaderboard.currentPage = 1; refresh(); });
    minSwingsInput.addEventListener('input', function () { Leaderboard.currentPage = 1; refresh(); });
    dateStartInput.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });
    dateEndInput.addEventListener('change', function () { Leaderboard.currentPage = 1; refresh(); });

    var searchTimer = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { Leaderboard.currentPage = 1; refresh(); }, 200);
    });
  }

  // Ordered chip list for hitterPitch tab
  var HITTER_PITCH_CHIP_ORDER = [
    'All', '|',
    'Hard', 'Breaking', 'Offspeed', '|',
    'FF', 'SI', 'CF', '|',
    'FC', 'SL', 'ST', 'CU', 'SV', '|',
    'CH', 'FS', 'KN'
  ];

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

    DataStore.metadata.pitchTypes.forEach(function (pt) {
      var btn = document.createElement('button');
      btn.className = 'pitch-chip';
      btn.textContent = pt;
      btn.setAttribute('data-pitch', pt);
      var color = Utils.getPitchColor(pt);
      btn.style.setProperty('--chip-bg', color);
      btn.style.borderColor = color;
      // For light-colored pitches, adjust text
      if (pt === 'SI' || pt === 'SV') btn.style.color = '';
      btn.title = Utils.pitchTypeLabel(pt);

      btn.addEventListener('click', function () {
        togglePitchChip(pt, btn);
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
    document.querySelectorAll('.tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
        tab.classList.add('active');
        currentTab = tab.getAttribute('data-tab');
        Leaderboard.currentSort = { key: isHitterTab(currentTab) ? 'hitter' : 'pitcher', dir: 'asc' };
        Leaderboard.currentPage = 1;
        Leaderboard.keyboardFocusIndex = -1;

        // Show/hide pitch type filter (pitch tab and hitter pitch type tab)
        document.getElementById('pitch-type-filter-group').style.display =
          (currentTab === 'pitch' || currentTab === 'hitterPitch') ? '' : 'none';

        // Show/hide min swings filter (hitter tabs except hitterPitch)
        document.getElementById('min-swings-filter-group').style.display =
          (isHitterTab(currentTab) && currentTab !== 'hitterPitch') ? '' : 'none';

        // Rebuild pitch chips for hitterPitch tab (custom) vs standard
        selectedPitchTypes = [];
        if (currentTab === 'hitterPitch') {
          buildHitterPitchChips(false);
        } else {
          buildPitchChips();
        }

        // Update throws/stands label and min count label
        var throwsLabel = document.querySelector('#throws-filter-group label');
        if (throwsLabel) {
          throwsLabel.textContent = isHitterTab(currentTab) ? 'Bats' : 'Throws';
        }
        var minCountLabel = document.querySelector('[for="min-count"]');
        if (minCountLabel) {
          minCountLabel.textContent = (isHitterTab(currentTab) && currentTab !== 'hitterPitch') ? 'Min PA' : 'Min Pitches';
        }

        // Update vs-hand option labels (RHH/LHH for pitcher tabs, RHP/LHP for hitter tabs)
        updateVsHandLabels();

        // Update search placeholder
        searchInput.placeholder = isHitterTab(currentTab) ? 'Hitter name...' : 'Pitcher name...';

        // Hide compare button on hitter tabs (no scatter compare for hitters)
        document.getElementById('compare-btn').style.display =
          isHitterTab(currentTab) ? 'none' : '';

        // Reset range filters on tab switch
        columnRangeFilters = {};
        updateRangeFilterBadge();

        refresh();
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
  function getFilters() {
    return {
      team: teamSelect.value,
      pitchTypes: selectedPitchTypes.length > 0 ? selectedPitchTypes : 'all',
      throws: throwsSelect.value,
      vsHand: vsHandSelect.value,
      minCount: parseInt(minCountInput.value) || 1,
      minSwings: parseInt(minSwingsInput.value) || 1,
      search: searchInput.value.trim(),
      dateStart: dateStartInput.value || '',
      dateEnd: dateEndInput.value || '',
    };
  }

  function refresh() {
    var filters = getFilters();
    var dataTab = currentTab === 'hitterPitch' ? 'hitterPitch' : (isHitterTab(currentTab) ? 'hitter' : currentTab);
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
      leagueData: leagueData
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
          badge.style.backgroundColor = Utils.getPitchColor(row[mc.key]);
          if (row[mc.key] === 'SI' || row[mc.key] === 'SV') badge.style.color = '#1a1a2e';
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
      { key: 'medEV', label: 'Med EV', format: Utils.formatDecimal(1) },
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
          badge.style.backgroundColor = Utils.getPitchColor(row[mc.key]);
          if (row[mc.key] === 'SI' || row[mc.key] === 'SV') badge.style.color = '#1a1a2e';
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
    var params = {
      tab: currentTab,
      team: teamSelect.value,
      throws: throwsSelect.value,
      vsHand: vsHandSelect.value,
      min: minCountInput.value,
      search: searchInput.value,
      sort: Leaderboard.currentSort.key || '',
      dir: Leaderboard.currentSort.dir || '',
      page: Leaderboard.currentPage.toString(),
      dateStart: dateStartInput.value || '',
      dateEnd: dateEndInput.value || '',
    };
    if (selectedPitchTypes.length > 0) {
      params.pitch = selectedPitchTypes.join(',');
    }
    Utils.writeHash(params);
  }

  function applyURLState() {
    var params = Utils.readHash();
    if (!params || Object.keys(params).length === 0) return;

    if (params.tab) {
      currentTab = params.tab;
      document.querySelectorAll('.tab').forEach(function (t) {
        t.classList.toggle('active', t.getAttribute('data-tab') === currentTab);
      });
      document.getElementById('pitch-type-filter-group').style.display =
        (currentTab === 'pitch' || currentTab === 'hitterPitch') ? '' : 'none';
      document.getElementById('min-swings-filter-group').style.display =
        (isHitterTab(currentTab) && currentTab !== 'hitterPitch') ? '' : 'none';
      // Update throws/stands label and min count label
      var throwsLabel = document.querySelector('#throws-filter-group label');
      if (throwsLabel) {
        throwsLabel.textContent = isHitterTab(currentTab) ? 'Bats' : 'Throws';
      }
      var minCountLabel = document.querySelector('[for="min-count"]');
      if (minCountLabel) {
        minCountLabel.textContent = (isHitterTab(currentTab) && currentTab !== 'hitterPitch') ? 'Min PA' : 'Min Pitches';
      }
      // Update search placeholder
      if (searchInput) {
        searchInput.placeholder = isHitterTab(currentTab) ? 'Hitter name...' : 'Pitcher name...';
      }
      // Hide compare on hitter tabs
      document.getElementById('compare-btn').style.display =
        isHitterTab(currentTab) ? 'none' : '';
    }
    if (params.team) teamSelect.value = params.team;
    if (params.throws) throwsSelect.value = params.throws;
    if (params.vsHand) vsHandSelect.value = params.vsHand;
    if (params.min) minCountInput.value = params.min;
    if (params.search) searchInput.value = params.search;
    if (params.dateStart) dateStartInput.value = params.dateStart;
    if (params.dateEnd) dateEndInput.value = params.dateEnd;
    if (params.sort) Leaderboard.currentSort.key = params.sort;
    if (params.dir) Leaderboard.currentSort.dir = params.dir;
    if (params.page) Leaderboard.currentPage = parseInt(params.page) || 1;

    // Rebuild chips if hitterPitch tab and restore selection
    if (currentTab === 'hitterPitch') {
      if (params.pitch) {
        selectedPitchTypes = params.pitch.split(',');
      } else {
        selectedPitchTypes = ['All'];
      }
      buildHitterPitchChips(true);
    } else if (params.pitch) {
      var types = params.pitch.split(',');
      var chips = document.querySelectorAll('.pitch-chip');
      types.forEach(function (pt) {
        chips.forEach(function (chip) {
          if (chip.getAttribute('data-pitch') === pt) {
            togglePitchChip(pt, chip);
          }
        });
      });
    }
  }

  // Start the app
  init();
})();
