var COLUMNS = {
  pitchMetrics: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: '_compare',    label: '',         format: function(){ return ''; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, isCompare: true, group: 'info', width: '32px' },
    { key: 'pitcher',     label: 'Pitcher',  format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'throws',      label: 'Throws',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isPitchType: true },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nBip',        label: 'BIP',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'usagePct',    label: 'Usage%',   format: Utils.formatPct, sortType: 'numeric', noPercentile: true, group: 'info' },
    // Metrics
    { key: 'velocity',    label: 'Velo',     format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, group: 'metrics' },
    { key: 'spinRate',    label: 'Spin',     format: Utils.formatInt, sortType: 'numeric', group: 'metrics' },
    { key: 'breakTilt',   label: 'Tilt',     format: Utils.formatTilt, sortType: 'numeric', sortKey: 'breakTiltMinutes', noPercentile: true, group: 'metrics' },
    { key: 'indVertBrk',  label: 'IVB',      format: Utils.formatDecimal(1), sortType: 'numeric', group: 'metrics' },
    { key: 'horzBrk',     label: 'HB',       format: Utils.formatDecimal(1), sortType: 'numeric', group: 'metrics' },
    { key: 'relPosZ',     label: 'RelZ',     format: Utils.formatFeetInches, sortType: 'numeric', group: 'metrics' },
    { key: 'relPosX',     label: 'RelX',     format: Utils.formatFeetInches, sortType: 'numeric', group: 'metrics' },
    { key: 'extension',   label: 'Ext',      format: Utils.formatFeetInches, sortType: 'numeric', group: 'metrics' },
    { key: 'armAngle',    label: 'Arm Angle', format: Utils.formatDecimal(1), sortType: 'numeric', group: 'metrics' },
    { key: 'vaa',         label: 'VAA',      format: Utils.formatDecimal(2), sortType: 'numeric', group: 'metrics' },
    { key: 'nVAA',        label: 'nVAA',     format: Utils.formatDecimal(2), sortType: 'numeric', group: 'metrics' },
    { key: 'haa',         label: 'HAA',      format: Utils.formatDecimal(2), sortType: 'numeric', group: 'metrics' },
    { key: 'vra',         label: 'VRA',      format: Utils.formatDecimal(2), sortType: 'numeric', group: 'metrics' },
    { key: 'hra',         label: 'HRA',      format: Utils.formatDecimal(2), sortType: 'numeric', group: 'metrics' },
    // Stats
    { key: 'izPct',       label: 'Zone%',    format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'stats' },
    { key: 'cswPct',      label: 'CSW%',     format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'swStrPct',    label: 'Whiff%',   format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'izWhiffPct',  label: 'IZWhiff%', format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'chasePct',    label: 'Chase%',   format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'fpsPct',      label: 'FPS%',     format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
  ],
  pitcherStats: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: '_compare',    label: '',         format: function(){ return ''; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, isCompare: true, group: 'info', width: '32px' },
    { key: 'pitcher',     label: 'Pitcher',  format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'throws',      label: 'Throws',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    // Counting stats (FanGraphs — not yet populated)
    { key: 'g',           label: 'G',        format: Utils.formatInt, sortType: 'numeric', noPercentile: true, sectionStart: true, group: 'counting' },
    { key: 'gs',          label: 'GS',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'ip',          label: 'IP',       format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'pa',          label: 'TBF',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    // Rate stats
    { key: 'kPct',        label: 'K%',       format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'stats' },
    { key: 'bbPct',       label: 'BB%',      format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'kbbPct',      label: 'K-BB%',    format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'babip',       label: 'BABIP',    format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'hrFbPct',     label: 'HR/FB',    format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    // Advanced pitching (FanGraphs — not yet populated)
    { key: 'era',         label: 'ERA',      format: Utils.formatDecimal(2), sortType: 'numeric', sectionStart: true, group: 'advanced' },
    { key: 'xERA',        label: 'xERA',     format: Utils.formatDecimal(2), sortType: 'numeric', group: 'advanced' },
    { key: 'eraMinusXera', label: 'ERA-xERA', format: Utils.formatDecimal(2), sortType: 'numeric', group: 'advanced' },
    { key: 'fip',         label: 'FIP',      format: Utils.formatDecimal(2), sortType: 'numeric', group: 'advanced' },
    { key: 'xFIP',        label: 'xFIP',     format: Utils.formatDecimal(2), sortType: 'numeric', group: 'advanced' },
    { key: 'siera',       label: 'SIERA',    format: Utils.formatDecimal(2), sortType: 'numeric', group: 'advanced' },
  ],
  pitcherBattedBall: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: '_compare',    label: '',         format: function(){ return ''; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, isCompare: true, group: 'info', width: '32px' },
    { key: 'pitcher',     label: 'Pitcher',  format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'throws',      label: 'Throws',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nBip',        label: 'BIP',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    // Batted Ball Stats
    { key: 'babip',       label: 'BABIP',    format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, group: 'batted_ball' },
    { key: 'avgEVAgainst', label: 'Avg EV',  format: Utils.formatDecimal(1), sortType: 'numeric', group: 'batted_ball' },
    { key: 'maxEVAgainst', label: 'Max EV',  format: Utils.formatDecimal(1), sortType: 'numeric', group: 'batted_ball' },
    { key: 'hardHitPct',  label: 'HardHit%', format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'barrelPctAgainst', label: 'Barrel%', format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'ldPct',       label: 'LD%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'fbPct',       label: 'FB%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'puPct',       label: 'PU%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'hrFbPct',     label: 'HR/FB',    format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
  ],
  pitcherSwingDecisions: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: '_compare',    label: '',         format: function(){ return ''; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, isCompare: true, group: 'info', width: '32px' },
    { key: 'pitcher',     label: 'Pitcher',  format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'throws',      label: 'Throws',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || ''; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isPitchBadge: true },
    // Swing Decision Stats
    { key: 'izPct',       label: 'Zone%',    format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'stats' },
    { key: 'cswPct',      label: 'CSW%',     format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'swStrPct',    label: 'Whiff%',   format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'izWhiffPct',  label: 'IZ Whiff%', format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'chasePct',    label: 'Chase%',   format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    { key: 'fpsPct',      label: 'FPS%',     format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
  ],
  hitterStats: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'pa',          label: 'PA',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'ab',          label: 'AB',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'stats' },
    // Stats
    { key: 'avg',         label: 'AVG',      format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, group: 'stats' },
    { key: 'obp',         label: 'OBP',      format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'slg',         label: 'SLG',      format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'ops',         label: 'OPS',      format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'iso',         label: 'ISO',      format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'babip',       label: 'BABIP',    format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'hrFbPct',     label: 'HR/FB',    format: Utils.formatPct, sortType: 'numeric', group: 'stats' },
    // Counting
    { key: 'doubles',     label: '2B',       format: Utils.formatInt, sortType: 'numeric', sectionStart: true, noPercentile: true, group: 'counting' },
    { key: 'triples',     label: '3B',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'hr',          label: 'HR',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'xbh',         label: 'XBH',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
  ],
  hitterBattedBall: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'pa',          label: 'PA',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nSwings',     label: 'Swings',   format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nBip',        label: 'BIP',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || ''; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isPitchBadge: true },
    // Exit Velocity
    { key: 'medEV',       label: 'Med EV',   format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, group: 'ev' },
    { key: 'ev75',        label: 'EV75',     format: Utils.formatDecimal(1), sortType: 'numeric', group: 'ev' },
    { key: 'maxEV',       label: 'Max EV',   format: Utils.formatDecimal(1), sortType: 'numeric', group: 'ev' },
    // Batted Ball
    { key: 'medLA',       label: 'Med LA',   format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, group: 'batted_ball' },
    { key: 'hardHitPct',  label: 'Hard-Hit%', format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'barrelPct',   label: 'Barrel%',  format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'laSweetSpotPct', label: 'Sweet-Spot%', format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'ldPct',       label: 'LD%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'fbPct',       label: 'FB%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'puPct',       label: 'PU%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'hrFbPct',     label: 'HR/FB',    format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    // Spray
    { key: 'pullPct',     label: 'Pull%',    format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'spray' },
    { key: 'middlePct',   label: 'Middle%',  format: Utils.formatPct, sortType: 'numeric', group: 'spray' },
    { key: 'oppoPct',     label: 'Oppo%',    format: Utils.formatPct, sortType: 'numeric', group: 'spray' },
    { key: 'airPullPct',  label: 'AirPull%', format: Utils.formatPct, sortType: 'numeric', group: 'spray' },
  ],
  hitterSwingDecisions: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'pa',          label: 'PA',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nSwings',     label: 'Swings',   format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || ''; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isPitchBadge: true },
    // Rates
    { key: 'kPct',        label: 'K%',       format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'rates' },
    { key: 'bbPct',       label: 'BB%',      format: Utils.formatPct, sortType: 'numeric', group: 'rates' },
    // Discipline
    { key: 'swingPct',    label: 'Swing%',   format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'discipline' },
    { key: 'izSwingPct',  label: 'IZSw%',    format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'chasePct',    label: 'Chase%',   format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'izSwChase',   label: 'IZSw-Ch',  format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'contactPct',  label: 'Contact%', format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'izContactPct', label: 'IZCT%',   format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'whiffPct',    label: 'Whiff%',   format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
  ],
  hitterBatTracking: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    // Bat Tracking
    { key: 'batSpeed',    label: 'Bat Speed', format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, group: 'bat_tracking' },
    { key: 'swingLength', label: 'Swing Length', format: Utils.formatDecimal(1), sortType: 'numeric', group: 'bat_tracking' },
    { key: 'attackAngle', label: 'Attack Angle', format: Utils.formatDecimal(1), sortType: 'numeric', group: 'bat_tracking' },
    { key: 'attackDirection', label: 'Attack Dir', format: Utils.formatDecimal(1), sortType: 'numeric', group: 'bat_tracking' },
    { key: 'swingPathTilt', label: 'Path Tilt', format: Utils.formatDecimal(1), sortType: 'numeric', group: 'bat_tracking' },
  ],
  hitterPitch: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'seenPct',     label: '% Seen',   format: Utils.formatPct, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nSwings',     label: 'Swings',   format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nBip',        label: 'BIP',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'avg',         label: 'AVG',      format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, group: 'stats' },
    { key: 'slg',         label: 'SLG',      format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'iso',         label: 'ISO',      format: Utils.formatDecimal(3), sortType: 'numeric', group: 'stats' },
    { key: 'medEV',       label: 'Med EV',   format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, group: 'ev' },
    { key: 'ev75',        label: 'EV75',     format: Utils.formatDecimal(1), sortType: 'numeric', group: 'ev' },
    { key: 'maxEV',       label: 'Max EV',   format: Utils.formatDecimal(1), sortType: 'numeric', group: 'ev' },
    { key: 'medLA',       label: 'Med LA',   format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, group: 'batted_ball' },
    { key: 'barrelPct',   label: 'Barrel%',  format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'batted_ball' },
    { key: 'ldPct',       label: 'LD%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'fbPct',       label: 'FB%',      format: Utils.formatPct, sortType: 'numeric', group: 'batted_ball' },
    { key: 'pullPct',     label: 'Pull%',    format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'spray' },
    { key: 'oppoPct',     label: 'Oppo%',    format: Utils.formatPct, sortType: 'numeric', group: 'spray' },
    { key: 'swingPct',    label: 'Swing%',   format: Utils.formatPct, sortType: 'numeric', sectionStart: true, group: 'discipline' },
    { key: 'izSwingPct',  label: 'IZSw%',    format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'chasePct',    label: 'Chase%',   format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'contactPct',  label: 'Contact%', format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'izContactPct', label: 'IZCT%',   format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
    { key: 'whiffPct',    label: 'Whiff%',   format: Utils.formatPct, sortType: 'numeric', group: 'discipline' },
  ],
};

var Leaderboard = {
  currentSort: { key: null, dir: 'desc' },
  hiddenColumns: {},  // key -> true if hidden
  showLeagueAvg: true,
  currentPage: 1,
  pageSize: 50,
  lastRenderedData: null,
  lastRenderedColumns: null,
  selectedForCompare: {},  // pitcher name -> true
  keyboardFocusIndex: -1,

  initHiddenColumns: function () {
    // No columns are hidden by default
  },

  getVisibleColumns: function (columns) {
    var self = this;
    return columns.filter(function (col) {
      return !self.hiddenColumns[col.key];
    });
  },

  sortData: function (data, columnKey, columns) {
    var col = null;
    for (var i = 0; i < columns.length; i++) {
      if (columns[i].key === columnKey) { col = columns[i]; break; }
    }
    if (!col || col.sortType === null) return data;

    var sortKey = col.sortKey || col.key;

    if (this.currentSort.key === columnKey) {
      this.currentSort.dir = this.currentSort.dir === 'desc' ? 'asc' : 'desc';
    } else {
      this.currentSort.key = columnKey;
      this.currentSort.dir = col.sortType === 'string' ? 'asc' : 'desc';
    }

    var dir = this.currentSort.dir === 'asc' ? 1 : -1;

    data.sort(function (a, b) {
      var va = a[sortKey];
      var vb = b[sortKey];
      if (va === null || va === undefined) {
        if (vb === null || vb === undefined) return 0;
        return 1;
      }
      if (vb === null || vb === undefined) return -1;
      if (col.sortType === 'string') return dir * String(va).localeCompare(String(vb));
      return dir * (va - vb);
    });

    return data;
  },

  computeLeagueAvgRow: function (data, columns) {
    var avg = {};
    // Keys where average should use absolute values (RHP/LHP have opposite signs)
    var ABS_AVG_KEYS = { horzBrk: true, haa: true, hra: true, relPosX: true };
    var numericKeys = [];
    for (var i = 0; i < columns.length; i++) {
      if (columns[i].sortType === 'numeric' && !columns[i].noPercentile && columns[i].key !== '_rank') {
        numericKeys.push(columns[i].key);
      }
    }
    numericKeys.forEach(function (key) {
      var sum = 0, count = 0;
      var useAbs = ABS_AVG_KEYS[key] || false;
      for (var j = 0; j < data.length; j++) {
        var v = data[j][key];
        if (v !== null && v !== undefined) {
          sum += useAbs ? Math.abs(v) : v;
          count++;
        }
      }
      avg[key] = count > 0 ? sum / count : null;
    });
    avg.pitcher = 'League Avg';
    avg.hitter = 'League Avg';
    avg._isLeagueAvg = true;
    avg._rank = '';
    return avg;
  },

  render: function (data, columns, opts) {
    opts = opts || {};
    var self = this;
    var visCols = this.getVisibleColumns(columns);
    var headerRow = document.getElementById('table-header');
    var tbody = document.getElementById('table-body');
    var pinnedBody = document.getElementById('table-pinned-body');
    var noResults = document.getElementById('no-results');
    var isDark = document.body.classList.contains('dark');

    this.lastRenderedData = data;
    this.lastRenderedColumns = columns;
    this._lastRenderOpts = opts;

    // Pagination
    var totalRows = data.length;
    var pageSize = this.pageSize;
    var totalPages = pageSize > 0 ? Math.max(1, Math.ceil(totalRows / pageSize)) : 1;
    if (this.currentPage > totalPages) this.currentPage = totalPages;
    var startIdx = pageSize > 0 ? (this.currentPage - 1) * pageSize : 0;
    var endIdx = pageSize > 0 ? Math.min(startIdx + pageSize, totalRows) : totalRows;
    var pageData = data.slice(startIdx, endIdx);

    // Update pagination UI
    var pageInfo = document.getElementById('page-info');
    var pagePrev = document.getElementById('page-prev');
    var pageNext = document.getElementById('page-next');
    if (pageInfo) pageInfo.textContent = 'Page ' + this.currentPage + ' of ' + totalPages;
    if (pagePrev) pagePrev.disabled = this.currentPage <= 1;
    if (pageNext) pageNext.disabled = this.currentPage >= totalPages;

    // Build header - group row + column row
    var thead = document.querySelector('#leaderboard-table thead');
    thead.innerHTML = '';

    // Group header row
    var groupRow = document.createElement('tr');
    groupRow.id = 'table-group-header';
    var groupLabels = { info: '', rates: 'Rates', stats: 'Stats', metrics: 'Metrics', counting: 'Counting', ev: 'Exit Velo', batted_ball: 'Batted Ball', spray: 'Spray', discipline: 'Discipline', bat_tracking: 'Bat Tracking' };
    var prevGroup = null;
    var groupSpans = [];
    visCols.forEach(function (col) {
      var g = col.group || 'info';
      if (g === prevGroup) {
        groupSpans[groupSpans.length - 1].span++;
      } else {
        groupSpans.push({ group: g, span: 1, sticky: col.sticky });
        prevGroup = g;
      }
    });
    var hasGroups = groupSpans.some(function (gs) { return groupLabels[gs.group]; });
    if (hasGroups) {
      var colIdx = 0;
      groupSpans.forEach(function (gs) {
        var th = document.createElement('th');
        th.setAttribute('colspan', gs.span);
        th.textContent = groupLabels[gs.group] || '';
        th.classList.add('group-header-cell');
        if (gs.sticky) { th.classList.add('sticky-col'); }
        if (gs.group !== 'info' && groupLabels[gs.group]) th.classList.add('group-header-labeled');
        // Check if first col in this span is sectionStart
        if (visCols[colIdx] && visCols[colIdx].sectionStart) th.classList.add('section-start');
        colIdx += gs.span;
        groupRow.appendChild(th);
      });
      thead.appendChild(groupRow);
    }

    // Column header row
    headerRow = document.createElement('tr');
    headerRow.id = 'table-header';
    visCols.forEach(function (col) {
      var th = document.createElement('th');
      if (col.isCompare) {
        th.classList.add('col-compare');
        th.style.width = col.width || 'auto';
      } else {
        th.textContent = col.label;
      }
      th.setAttribute('data-key', col.key);
      if (col.align) th.classList.add('align-' + col.align);
      if (col.sticky) th.classList.add('sticky-col');
      if (col.sectionStart) th.classList.add('section-start');
      if (col.width) th.style.width = col.width;
      if (Utils.TOOLTIPS[col.label]) th.title = Utils.TOOLTIPS[col.label];

      if (self.currentSort.key === col.key) {
        th.classList.add('sorted', self.currentSort.dir);
      }

      if (col.sortType !== null) {
        th.addEventListener('click', function () {
          self.sortData(data, col.key, columns);
          self.currentPage = 1;
          self.render(data, columns, self._lastRenderOpts);
        });
      }

      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);

    // Set column header sticky top below group header
    if (hasGroups) {
      var groupRowHeight = groupRow.offsetHeight || 25;
      for (var hi = 0; hi < headerRow.cells.length; hi++) {
        headerRow.cells[hi].style.top = groupRowHeight + 'px';
      }
    }

    // Calculate sticky column offsets (for frozen Team column)
    this._stickyLeftOffsets = {};
    var firstStickyTh = null;
    for (var si = 0; si < visCols.length; si++) {
      if (visCols[si].sticky && !visCols[si].stickyIdx) {
        firstStickyTh = headerRow.cells[si];
        break;
      }
    }
    if (firstStickyTh) {
      var firstStickyWidth = firstStickyTh.offsetWidth;
      for (var si2 = 0; si2 < visCols.length; si2++) {
        if (visCols[si2].stickyIdx === 1) {
          headerRow.cells[si2].style.left = firstStickyWidth + 'px';
          this._stickyLeftOffsets[visCols[si2].key] = firstStickyWidth;
          // Also set on group header if present
          if (hasGroups) {
            // Find which group cell contains this column
          }
        }
      }
    }

    // Build body
    tbody.innerHTML = '';
    if (pinnedBody) pinnedBody.innerHTML = '';

    if (data.length === 0) {
      noResults.style.display = '';
      document.getElementById('row-count').textContent = '0';
      document.getElementById('pagination').style.display = 'none';
      return;
    }
    noResults.style.display = 'none';
    document.getElementById('pagination').style.display = '';

    // Pinned average rows
    if (pinnedBody && this.showLeagueAvg && data.length > 0) {
      var thead = document.querySelector('#leaderboard-table thead');
      var thHeight = thead ? thead.offsetHeight : 36;

      // League Average: computed from all-teams data (ignores team filter)
      var leagueAvgData = opts.leagueData || data;
      var leagueAvgRow = this.computeLeagueAvgRow(leagueAvgData, visCols);
      leagueAvgRow.pitcher = 'League Avg';
      leagueAvgRow.hitter = 'League Avg';
      var leagueTr = this._createRow(leagueAvgRow, visCols, -1, isDark, true);
      leagueTr.classList.add('league-avg-row');
      pinnedBody.appendChild(leagueTr);

      // Make league avg row cells sticky
      for (var ci = 0; ci < leagueTr.cells.length; ci++) {
        leagueTr.cells[ci].style.position = 'sticky';
        leagueTr.cells[ci].style.top = thHeight + 'px';
        leagueTr.cells[ci].style.zIndex = leagueTr.cells[ci].classList.contains('sticky-col') ? '5' : '3';
      }

      // Team Average: only when a single team is selected
      if (opts.teamFilter && opts.teamFilter !== 'all' && data.length > 0) {
        var teamAvgRow = this.computeLeagueAvgRow(data, visCols);
        teamAvgRow.pitcher = opts.teamFilter + ' Avg';
        teamAvgRow.hitter = opts.teamFilter + ' Avg';
        teamAvgRow._isTeamAvg = true;
        var teamTr = this._createRow(teamAvgRow, visCols, -1, isDark, true);
        teamTr.classList.add('league-avg-row', 'team-avg-row');
        pinnedBody.appendChild(teamTr);

        var leagueRowHeight = leagueTr.offsetHeight || 30;
        for (var ti = 0; ti < teamTr.cells.length; ti++) {
          teamTr.cells[ti].style.position = 'sticky';
          teamTr.cells[ti].style.top = (thHeight + leagueRowHeight) + 'px';
          teamTr.cells[ti].style.zIndex = teamTr.cells[ti].classList.contains('sticky-col') ? '5' : '3';
        }
      }
    }

    var fragment = document.createDocumentFragment();

    // Data rows
    for (var ri = 0; ri < pageData.length; ri++) {
      var row = pageData[ri];
      var globalRank = startIdx + ri + 1;
      var tr = this._createRow(row, visCols, globalRank, isDark, false);
      tr.classList.add('clickable-row');
      tr._pitcherName = row.pitcher || row.hitter;
      tr._rowIndex = ri;

      // Click handler
      (function (r, idx) {
        tr.addEventListener('click', function (e) {
          // Don't trigger on compare checkbox clicks
          if (e.target.type === 'checkbox') return;
          // Remove active from all rows
          var prev = tbody.querySelectorAll('.active-row');
          for (var k = 0; k < prev.length; k++) prev[k].classList.remove('active-row');
          // Highlight all rows for this person
          var personName = r.pitcher || r.hitter;
          var allRows = tbody.querySelectorAll('tr');
          allRows.forEach(function (row) {
            if (row._pitcherName === personName) row.classList.add('active-row');
          });
          self.keyboardFocusIndex = idx;
          if (typeof App !== 'undefined' && App.openSidePanel) {
            App.openSidePanel(personName, r.team, r.throws || r.stands, r);
          }
        });
      })(row, ri);

      if (this.keyboardFocusIndex === ri) {
        tr.classList.add('keyboard-focus');
      }

      fragment.appendChild(tr);
    }

    tbody.appendChild(fragment);
    document.getElementById('row-count').textContent = totalRows;
  },

  _createRow: function (row, visCols, rank, isDark, isAvgRow) {
    var self = this;
    var tr = document.createElement('tr');

    visCols.forEach(function (col) {
      var td = document.createElement('td');

      // Special: rank column
      if (col.key === '_rank') {
        td.textContent = isAvgRow ? '' : rank;
        td.classList.add('col-rank');
        if (col.align) td.classList.add('align-' + col.align);
        tr.appendChild(td);
        return;
      }

      // Special: compare checkbox column
      if (col.isCompare) {
        td.classList.add('col-compare');
        if (!isAvgRow) {
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          var compareKey = (row.pitcher || '') + '|' + (row.team || '');
          cb.checked = !!self.selectedForCompare[compareKey];
          cb.addEventListener('change', function () {
            if (cb.checked) {
              self.selectedForCompare[compareKey] = true;
            } else {
              delete self.selectedForCompare[compareKey];
            }
            if (typeof App !== 'undefined' && App.updateCompareButton) {
              App.updateCompareButton();
            }
          });
          td.appendChild(cb);
        }
        tr.appendChild(td);
        return;
      }

      // Special: pitch type badge
      if (col.isPitchType && row[col.key] && !isAvgRow) {
        var badge = document.createElement('span');
        badge.className = 'pitch-badge';
        badge.textContent = row[col.key];
        var pitchColor = Utils.getPitchColor(row[col.key]);
        badge.style.backgroundColor = pitchColor;
        // Ensure readability for light colors
        if (row[col.key] === 'SI' || row[col.key] === 'SV') {
          badge.style.color = '#1a1a2e';
        }
        td.appendChild(badge);
        if (col.align) td.classList.add('align-' + col.align);
        tr.appendChild(td);
        return;
      }

      // Pitcher name as clickable link to player page
      if (col.key === 'pitcher' && !isAvgRow && row.mlbId) {
        var link = document.createElement('a');
        link.href = '#player=' + row.mlbId;
        link.className = 'pitcher-name-link';
        link.textContent = col.format(row[col.key]);
        link.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          PlayerPage.open(row.mlbId);
        });
        td.appendChild(link);
        if (col.align) td.classList.add('align-' + col.align);
        if (col.sticky) {
          td.classList.add('sticky-col');
          if (col.stickyIdx === 1 && self._stickyLeftOffsets[col.key]) {
            td.style.left = self._stickyLeftOffsets[col.key] + 'px';
          }
        }
        if (col.cls) td.classList.add(col.cls);
        tr.appendChild(td);
        return;
      }

      // Hitter name as clickable link to player page
      if (col.key === 'hitter' && !isAvgRow && row.mlbId) {
        var hLink = document.createElement('a');
        hLink.href = '#player=' + row.mlbId;
        hLink.className = 'pitcher-name-link';
        hLink.textContent = col.format(row[col.key]);
        hLink.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          PlayerPage.open(row.mlbId);
        });
        td.appendChild(hLink);
        if (col.align) td.classList.add('align-' + col.align);
        if (col.sticky) {
          td.classList.add('sticky-col');
          if (col.stickyIdx === 1 && self._stickyLeftOffsets[col.key]) {
            td.style.left = self._stickyLeftOffsets[col.key] + 'px';
          }
        }
        if (col.cls) td.classList.add(col.cls);
        tr.appendChild(td);
        return;
      }

      // Regular cell
      var val = row[col.key];
      td.textContent = col.format(val);
      if (col.align) td.classList.add('align-' + col.align);
      if (col.sticky) {
        td.classList.add('sticky-col');
        if (col.stickyIdx === 1 && self._stickyLeftOffsets[col.key]) {
          td.style.left = self._stickyLeftOffsets[col.key] + 'px';
        }
      }
      if (col.cls) td.classList.add(col.cls);
      if (col.sectionStart) td.classList.add('section-start');
      if (val === null || val === undefined) td.classList.add('col-null');

      // Percentile coloring
      if (!col.noPercentile && !isAvgRow) {
        var pctlKey = col.key + '_pctl';
        var pctl = row[pctlKey];
        if (pctl !== null && pctl !== undefined) {
          if (isDark) {
            td.style.backgroundColor = Utils.percentileColorDark(pctl);
            td.style.color = Utils.percentileTextColorDark(pctl);
          } else {
            td.style.backgroundColor = Utils.percentileColor(pctl);
            td.style.color = Utils.percentileTextColor(pctl);
          }
          // Store percentile for tooltip
          td.setAttribute('data-pctl', pctl);
          td.setAttribute('data-col-key', col.key);
          td.setAttribute('data-col-label', col.label);
        }
      }

      tr.appendChild(td);
    });

    return tr;
  },

  getCompareList: function () {
    return Object.keys(this.selectedForCompare);
  },

  clearCompare: function () {
    this.selectedForCompare = {};
  },
};

// Initialize hidden columns on load
Leaderboard.initHiddenColumns();
