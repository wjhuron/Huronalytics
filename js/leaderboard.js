const COLUMNS = {
  pitchMetrics: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: '_compare',    label: '',         format: function(){ return ''; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, isCompare: true, group: 'info', width: '32px' },
    { key: 'pitcher',     label: 'Pitcher',  format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'throws',      label: 'Throws',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isPitchType: true },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'usagePct',    label: 'Usage%',   format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Pct of pitcher\'s total pitches', group: 'info' },
    // Metrics (stuff first)
    { key: 'velocity',       label: 'Velo',     format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, desc: 'Average velocity (mph)', group: 'metrics' },
    { key: 'effectiveVelo', label: 'EffVelo',  format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Effective velocity (mph) — perceived speed accounting for extension', group: 'metrics' },
    { key: 'maxVelo',       label: 'Max Velo', format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Maximum velocity (mph)', group: 'metrics' },
    { key: 'spinRate',    label: 'Spin',     format: Utils.formatInt, sortType: 'numeric', desc: 'Average spin rate (rpm)', group: 'metrics' },
    { key: 'breakTilt',   label: 'OTilt',    format: Utils.formatTilt, sortType: 'numeric', sortKey: 'breakTiltMinutes', noPercentile: true, desc: 'Observed break tilt (clock notation) — direction of total break', group: 'metrics' },
    { key: 'indVertBrk',  label: 'IVB',      format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Induced vertical break (inches) — gravity-independent', group: 'metrics' },
    { key: 'xIVB',        label: 'xIVB',     format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Expected IVB from MVN model given velo, spin, arm slot', group: 'metrics' },
    { key: 'ivbOE',       label: 'IVBOE',    format: Utils.formatSignedDecimal(1), sortType: 'numeric', desc: 'IVB over expected (IVB − xIVB) — positive = more rise than expected', group: 'metrics' },
    { key: 'horzBrk',     label: 'HB',       format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Horizontal break (inches, pitcher POV)', group: 'metrics' },
    { key: 'xHB',         label: 'xHB',      format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Expected HB from MVN model given velo, spin, arm slot', group: 'metrics' },
    { key: 'hbOE',        label: 'HBOE',     format: Utils.formatSignedDecimal(1), sortType: 'numeric', desc: 'HB over expected (HB − xHB)', group: 'metrics' },
    { key: 'relPosZ',     label: 'RelZ',     format: Utils.formatFeetInches, sortType: 'numeric', noPercentile: true, desc: 'Vertical release point (feet)', group: 'metrics' },
    { key: 'relPosX',     label: 'RelX',     format: Utils.formatFeetInches, sortType: 'numeric', noPercentile: true, desc: 'Horizontal release point (feet, pitcher POV)', group: 'metrics' },
    { key: 'extension',   label: 'Ext',      format: Utils.formatFeetInches, sortType: 'numeric', noPercentile: true, desc: 'Extension toward home plate at release (feet)', group: 'metrics' },
    { key: 'armAngle',    label: 'Arm Angle', format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Arm angle at release (degrees)', group: 'metrics' },
    { key: 'nVAA',        label: 'nVAA',     format: Utils.formatDecimal(2), sortType: 'numeric', desc: 'Normalized VAA — location-independent (VAA minus expected VAA at that plate height)', group: 'metrics' },
    { key: 'nHAA',        label: 'nHAA',     format: Utils.formatDecimal(2), sortType: 'numeric', desc: 'Normalized HAA — location-independent (HAA minus expected HAA at that plate location)', group: 'metrics' },
    { key: 'vaa',         label: 'VAA',      format: Utils.formatDecimal(2), sortType: 'numeric', desc: 'Vertical approach angle at the plate (degrees)', group: 'metrics' },
    { key: 'haa',         label: 'HAA',      format: Utils.formatDecimal(2), sortType: 'numeric', desc: 'Horizontal approach angle at the plate (degrees)', group: 'metrics' },
    { key: 'stuffScore',  label: 'Stuff+',   format: Utils.formatInt, sortType: 'numeric', desc: 'Stuff+ quality score from physical characteristics only (100 = avg, higher = better for pitcher)', group: 'metrics' },
    // Outcomes
    { key: 'runValue',    label: 'PitchRV',  format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, desc: 'Pitch-level run value — runs saved vs league avg (negative = better for pitcher)', group: 'outcomes' },
    { key: 'rv100',       label: 'RV/100',   format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Run value per 100 pitches', group: 'outcomes' },
    { key: 'xBA',         label: 'xBA',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected batting average (Statcast model, based on EV + LA)', group: 'outcomes' },
    { key: 'xSLG',        label: 'xSLG',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected slugging (Statcast model, based on EV + LA)', group: 'outcomes' },
    { key: 'wOBA',         label: 'wOBA',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Weighted on-base average — all plate outcomes weighted by run value', group: 'outcomes' },
    { key: 'xwOBA',       label: 'xwOBA',    format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA (Statcast model, based on EV + LA)', group: 'outcomes' },
  ],
  pitcherStats: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: '_compare',    label: '',         format: function(){ return ''; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, isCompare: true, group: 'info', width: '32px' },
    { key: 'pitcher',     label: 'Pitcher',  format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'throws',      label: 'Throws',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'armAngle',   label: 'Arm\u00B0',  format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Arm angle at release (degrees)', group: 'info' },
    // Counting stats (from boxscore API)
    { key: 'g',           label: 'G',        format: Utils.formatInt, sortType: 'numeric', noPercentile: true, sectionStart: true, group: 'counting' },
    { key: 'gs',          label: 'GS',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'ip',          label: 'IP',       format: function(v){ return v != null ? v : '—'; }, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'w',           label: 'W',        format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'l',           label: 'L',        format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'sv',          label: 'SV',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'hld',         label: 'HLD',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'tbf',         label: 'TBF',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, desc: 'Total batters faced', group: 'counting' },
    // Traditional / Advanced
    { key: 'era',         label: 'ERA',      format: Utils.formatDecimal(2), sortType: 'numeric', sectionStart: true, desc: 'Earned run average', group: 'advanced' },
    { key: 'fip',         label: 'FIP',      format: Utils.formatDecimal(2), sortType: 'numeric', desc: 'Fielding Independent Pitching — ERA estimator using K, BB, HBP, HR', group: 'advanced' },
    { key: 'xFIP',        label: 'xFIP',     format: Utils.formatDecimal(2), sortType: 'numeric', desc: 'Expected FIP — FIP with league-avg HR/FB rate', group: 'advanced' },
    { key: 'siera',       label: 'SIERA',    format: Utils.formatDecimal(2), sortType: 'numeric', desc: 'Skill-Interactive ERA — uses K%, BB%, GB% with interaction terms', group: 'advanced' },
    // Rate stats
    { key: 'kPct',        label: 'K%',       format: Utils.formatPct, sortType: 'numeric', sectionStart: true, desc: 'Strikeout rate (K / TBF)', group: 'stats' },
    { key: 'bbPct',       label: 'BB%',      format: Utils.formatPct, sortType: 'numeric', desc: 'Walk rate (BB / TBF)', group: 'stats' },
    { key: 'kbbPct',      label: 'K-BB%',    format: Utils.formatPct, sortType: 'numeric', desc: 'K% minus BB%', group: 'stats' },
    // Run Value
    { key: 'runValue',    label: 'PitchRV',  format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, desc: 'Pitch-level run value — runs saved vs league avg (negative = better)', group: 'run_value' },
    { key: 'rv100',       label: 'RV/100',   format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Run value per 100 pitches', group: 'run_value' },
    // Expected
    { key: 'wOBA',         label: 'wOBA',     format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, desc: 'Weighted on-base average against', group: 'expected' },
    { key: 'xwOBA',       label: 'xwOBA',    format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA against (Statcast model)', group: 'expected' },
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
    { key: 'babip',       label: 'BABIP',    format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, desc: 'Batting avg on balls in play against', group: 'batted_ball' },
    { key: 'xBA',         label: 'xBA',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected BA against (Statcast, EV + LA)', group: 'batted_ball' },
    { key: 'xSLG',        label: 'xSLG',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected SLG against (Statcast, EV + LA)', group: 'batted_ball' },
    { key: 'xwOBA',       label: 'xwOBA',    format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA against (Statcast, EV + LA)', group: 'batted_ball' },
    { key: 'xwOBAcon',   label: 'xwOBAcon', format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA on contact — avg xwOBA on BIP only', group: 'batted_ball' },
    { key: 'xwOBAsp',    label: 'xwOBASp',  format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA spray-adjusted — avg zone wOBA based on LA × spray direction of BIP against', group: 'batted_ball' },
    { key: 'avgEVAgainst', label: 'Avg EV',  format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Average exit velocity against (mph)', group: 'batted_ball' },
    { key: 'maxEVAgainst', label: 'Max EV',  format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Max exit velocity against (mph)', group: 'batted_ball' },
    { key: 'hardHitPct',  label: 'Hard-Hit%', format: Utils.formatPct, sortType: 'numeric', desc: 'Pct of BIP with EV ≥ 95 mph', group: 'batted_ball' },
    { key: 'barrelPctAgainst', label: 'Barrel%', format: Utils.formatPct, sortType: 'numeric', desc: 'Barrel rate against (Statcast barrel definition)', group: 'batted_ball' },
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', desc: 'Ground ball rate', group: 'batted_ball' },
    { key: 'hrFbPct',     label: 'HR/FB',    format: Utils.formatPct, sortType: 'numeric', desc: 'Home runs per fly ball', group: 'batted_ball' },
  ],
  pitcherSwingDecisions: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: '_compare',    label: '',         format: function(){ return ''; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, isCompare: true, group: 'info', width: '32px' },
    { key: 'pitcher',     label: 'Pitcher',  format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'throws',      label: 'Throws',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nSwings',     label: 'Swings',   format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    // Plate Discipline Stats
    { key: 'strikePct',   label: 'Strike%',  format: Utils.formatPct, sortType: 'numeric', sectionStart: true, desc: 'Total strike rate (called + swinging + foul)', group: 'stats' },
    { key: 'izPct',       label: 'Zone%',    format: Utils.formatPct, sortType: 'numeric', desc: 'Pct of pitches in the strike zone', group: 'stats' },
    { key: 'cswPct',      label: 'CSW%',     format: Utils.formatPct, sortType: 'numeric', desc: 'Called strikes + whiffs / total pitches', group: 'stats' },
    { key: 'swStrPct',    label: 'Whiff%',   format: Utils.formatPct, sortType: 'numeric', desc: 'Swinging strikes / total swings', group: 'stats' },
    { key: 'izWhiffPct',  label: 'IZ Whiff%', format: Utils.formatPct, sortType: 'numeric', desc: 'Whiff rate on in-zone swings', group: 'stats' },
    { key: 'chasePct',    label: 'Chase%',   format: Utils.formatPct, sortType: 'numeric', desc: 'Out-of-zone swing rate', group: 'stats' },
    { key: 'fpsPct',      label: 'FPS%',     format: Utils.formatPct, sortType: 'numeric', desc: 'First-pitch strike rate', group: 'stats' },
    { key: 'twoStrikeWhiffPct', label: '2K Whiff%', format: Utils.formatPct, sortType: 'numeric', desc: 'Whiff rate on pitches with 2 strikes', group: 'stats' },
  ],
  hitterStats: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'g',           label: 'G',        format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'pa',          label: 'PA',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'ab',          label: 'AB',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    // Stats
    { key: 'avg',         label: 'AVG',      format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, desc: 'Batting average', group: 'stats' },
    { key: 'obp',         label: 'OBP',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'On-base percentage', group: 'stats' },
    { key: 'slg',         label: 'SLG',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Slugging percentage', group: 'stats' },
    { key: 'ops',         label: 'OPS',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'OBP + SLG', group: 'stats' },
    { key: 'iso',         label: 'ISO',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Isolated power (SLG − AVG)', group: 'stats' },
    { key: 'wOBA',         label: 'wOBA',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Weighted on-base average — plate outcomes weighted by run value', group: 'stats' },
    { key: 'wRCplus',     label: 'wRC+',     format: Utils.formatInt, sortType: 'numeric', desc: 'Weighted runs created+ (100 = league avg, park-adjusted)', group: 'stats' },
    { key: 'kPct',        label: 'K%',       format: Utils.formatPct, sortType: 'numeric', desc: 'Strikeout rate (K / PA)', group: 'stats' },
    { key: 'bbPct',       label: 'BB%',      format: Utils.formatPct, sortType: 'numeric', desc: 'Walk rate (BB / PA)', group: 'stats' },
    // Supplemental
    { key: 'babip',       label: 'BABIP',    format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, desc: 'Batting average on balls in play', group: 'supplemental' },
    { key: 'hrFbPct',     label: 'HR/FB',    format: Utils.formatPct, sortType: 'numeric', desc: 'Home runs per fly ball', group: 'supplemental' },
    // Expected Stats
    { key: 'xBA',         label: 'xBA',      format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, desc: 'Expected BA (Statcast, EV + LA)', group: 'expected' },
    { key: 'xSLG',        label: 'xSLG',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected SLG (Statcast, EV + LA)', group: 'expected' },
    { key: 'xwOBA',       label: 'xwOBA',    format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA (Statcast, EV + LA)', group: 'expected' },
    { key: 'xwOBAcon',   label: 'xwOBAcon', format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA on contact — avg xwOBA on BIP only', group: 'expected' },
    { key: 'xWRCplus',   label: 'xWRC+',    format: Utils.formatInt, sortType: 'numeric', desc: 'Expected wRC+ (derived from xwOBA, park-adjusted)', group: 'expected' },
    { key: 'runValue',    label: 'PitchRV',  format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Pitch-level run value (positive = better for hitter)', group: 'expected' },
    // Counting
    { key: 'doubles',     label: '2B',       format: Utils.formatInt, sortType: 'numeric', sectionStart: true, noPercentile: true, group: 'counting' },
    { key: 'triples',     label: '3B',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    { key: 'hr',          label: 'HR',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'counting' },
    // Baserunning
    { key: 'sb',          label: 'SB',       format: Utils.formatInt, sortType: 'numeric', sectionStart: true, noPercentile: true, group: 'baserunning' },
    { key: 'cs',          label: 'CS',       format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'baserunning' },
    { key: 'sbPct',       label: 'SB%',      format: function(v){ return v != null ? v.toFixed(1) + '%' : '—'; }, sortType: 'numeric', noPercentile: true, desc: 'Stolen base success rate', group: 'baserunning' },
    { key: 'sprintSpeed', label: 'Sprint',   format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Sprint speed (ft/s) — avg of top running efforts', group: 'baserunning' },
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
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || ''; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isPitchType: true },
    // Exit Velocity
    { key: 'avgEVAll',    label: 'Avg EV',       format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, desc: 'Average exit velocity on all BIP (mph)', group: 'ev' },
    { key: 'ev50',        label: 'EV50',     format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Avg EV of top 50% hardest-hit BIP (mph)', group: 'ev' },
    { key: 'maxEV',       label: 'Max EV',   format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Maximum exit velocity (mph)', group: 'ev' },
    // Quality
    { key: 'medLA',       label: 'Med LA',   format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, sectionStart: true, desc: 'Median launch angle (degrees)', group: 'quality' },
    { key: 'hardHitPct',  label: 'Hard-Hit%', format: Utils.formatPct, sortType: 'numeric', desc: 'Pct of BIP with EV ≥ 95 mph', group: 'quality' },
    { key: 'barrelPct',   label: 'Barrel%',  format: Utils.formatPct, sortType: 'numeric', desc: 'Barrel rate (Statcast barrel definition, EV + LA combo)', group: 'quality' },
    // Expected Stats
    { key: 'xBA',         label: 'xBA',      format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, desc: 'Expected BA (Statcast, EV + LA)', group: 'expected' },
    { key: 'xSLG',        label: 'xSLG',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected SLG (Statcast, EV + LA)', group: 'expected' },
    { key: 'xwOBA',       label: 'xwOBA',    format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA (Statcast, EV + LA)', group: 'expected' },
    { key: 'xwOBAcon',   label: 'xwOBAcon', format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA on contact — avg xwOBA on BIP only', group: 'expected' },
    { key: 'xwOBAsp',    label: 'xwOBAsp',  format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA spray-adjusted — avg zone wOBA by LA × spray direction', group: 'expected' },
    // Composition
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', sectionStart: true, desc: 'Ground ball rate', group: 'composition' },
    { key: 'ldPct',       label: 'LD%',      format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Line drive rate', group: 'composition' },
    { key: 'fbPct',       label: 'FB%',      format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Fly ball rate', group: 'composition' },
    // Spray
    { key: 'pullPct',     label: 'Pull%',    format: Utils.formatPct, sortType: 'numeric', noPercentile: true, sectionStart: true, desc: 'Pull rate (BIP to pull side)', group: 'spray' },
    { key: 'middlePct',   label: 'Middle%',  format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Center rate (BIP up the middle)', group: 'spray' },
    { key: 'oppoPct',     label: 'Oppo%',    format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Oppo rate (BIP to opposite field)', group: 'spray' },
    { key: 'airPullPct',  label: 'AirPull%', format: Utils.formatPct, sortType: 'numeric', desc: 'Air-pull rate (LD + FB + PU to pull side / total BIP)', group: 'spray' },
    // Distance
    { key: 'avgFbDist',   label: 'Avg FB Dist', format: Utils.formatInt, sortType: 'numeric', noPercentile: true, desc: 'Average fly ball distance (feet)', sectionStart: true, group: 'distance' },
    { key: 'avgHrDist',   label: 'Avg HR Dist', format: Utils.formatInt, sortType: 'numeric', noPercentile: true, desc: 'Average home run distance (feet)', group: 'distance' },
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
    { key: 'kPct',        label: 'K%',       format: Utils.formatPct, sortType: 'numeric', sectionStart: true, desc: 'Strikeout rate (K / PA)', group: 'rates' },
    { key: 'bbPct',       label: 'BB%',      format: Utils.formatPct, sortType: 'numeric', desc: 'Walk rate (BB / PA)', group: 'rates' },
    // Discipline
    { key: 'swingPct',    label: 'Swing%',   format: Utils.formatPct, sortType: 'numeric', sectionStart: true, desc: 'Overall swing rate (swings / pitches seen)', group: 'discipline' },
    { key: 'izSwingPct',  label: 'IZSw%',    format: Utils.formatPct, sortType: 'numeric', desc: 'In-zone swing rate', group: 'discipline' },
    { key: 'chasePct',    label: 'Chase%',   format: Utils.formatPct, sortType: 'numeric', desc: 'Out-of-zone swing rate', group: 'discipline' },
    { key: 'izSwChase',   label: 'IZSw-Ch%',  format: Utils.formatPct, sortType: 'numeric', desc: 'Discipline spread (IZ Swing% − Chase%)', group: 'discipline' },
    { key: 'firstPitchSwingPct', label: 'FPSw%',  format: Utils.formatPct, sortType: 'numeric', desc: 'First-pitch swing rate (% of PAs swinging on 0-0)', group: 'discipline' },
    { key: 'contactPct',  label: 'Contact%', format: Utils.formatPct, sortType: 'numeric', desc: 'Contact rate (contact / swings)', group: 'discipline' },
    { key: 'izContactPct', label: 'IZCT%',   format: Utils.formatPct, sortType: 'numeric', desc: 'In-zone contact rate', group: 'discipline' },
    { key: 'whiffPct',    label: 'Whiff%',   format: Utils.formatPct, sortType: 'numeric', desc: 'Whiff rate (misses / swings)', group: 'discipline' },
    { key: 'twoStrikeWhiffPct', label: '2K Whiff%', format: Utils.formatPct, sortType: 'numeric', desc: 'Whiff rate on pitches with 2 strikes', group: 'discipline' },
  ],
  hitterBatTracking: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'nCompSwings', label: 'Comp. Swings', format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    // Bat Tracking
    { key: 'batSpeed',    label: 'Bat Speed', format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, desc: 'Avg bat speed on competitive swings (mph)', group: 'bat_tracking' },
    { key: 'swingLength', label: 'Swing Length', format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Avg swing length — total bat-head distance from start to contact (feet)', group: 'bat_tracking' },
    { key: 'attackAngle', label: 'Attack Angle', format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Avg attack angle — bat direction at contact (degrees, positive = upward)', group: 'bat_tracking' },
    { key: 'attackDirection', label: 'Attack Dir', format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Avg attack direction at contact (degrees, positive = pull side)', group: 'bat_tracking' },
    { key: 'swingPathTilt', label: 'Path Tilt', format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Avg swing path tilt — bat path angle over 40ms before contact (degrees)', group: 'bat_tracking' },
    { key: 'blastPct', label: 'Blast%', format: Utils.formatPct, sortType: 'numeric', desc: 'Bat speed ≥75 mph AND exit velo ≥80% of theoretical max — fast swing + squared up', group: 'bat_tracking' },
    { key: 'idealAAPct', label: 'IdealAtkAngle%', format: Utils.formatPct, sortType: 'numeric', desc: 'Pct of competitive swings with attack angle in the 5–20° ideal range', group: 'bat_tracking' },
  ],
  hitterPitch: [
    { key: '_rank',       label: '#',        format: function(v){ return v; }, sortType: null, align: 'center', noPercentile: true, noToggle: true, group: 'info', width: '36px' },
    { key: 'hitter',      label: 'Hitter',   format: function(v){ return v || '--'; }, sortType: 'string', align: 'left', sticky: true, cls: 'col-pitcher', noPercentile: true, noToggle: true, group: 'info' },
    { key: 'team',        label: 'Team',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isTeam: true, sticky: true, stickyIdx: 1 },
    { key: 'stands',      label: 'Bats',     format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info' },
    { key: 'pitchType',   label: 'Pitch',    format: function(v){ return v || '--'; }, sortType: 'string', align: 'center', noPercentile: true, group: 'info', isPitchType: true },
    { key: 'seenPct',     label: '% Seen',   format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Pct of pitches seen of this type', group: 'info' },
    { key: 'count',       label: 'Pitches',  format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nSwings',     label: 'Swings',   format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'nBip',        label: 'BIP',      format: Utils.formatInt, sortType: 'numeric', noPercentile: true, group: 'info' },
    { key: 'runValue',    label: 'PitchRV',  format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Pitch-level run value vs this pitch type (positive = better for hitter)', group: 'info' },
    { key: 'rv100',       label: 'RV/100',   format: Utils.formatDecimal(1), sortType: 'numeric', noPercentile: true, desc: 'Run value per 100 pitches of this type', group: 'info' },
    { key: 'avg',         label: 'AVG',      format: Utils.formatDecimal(3), sortType: 'numeric', sectionStart: true, desc: 'Batting average vs this pitch type', group: 'stats' },
    { key: 'slg',         label: 'SLG',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Slugging vs this pitch type', group: 'stats' },
    { key: 'iso',         label: 'ISO',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Isolated power vs this pitch type (SLG − AVG)', group: 'stats' },
    { key: 'wOBA',         label: 'wOBA',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Weighted on-base average vs this pitch type', group: 'stats' },
    { key: 'xBA',         label: 'xBA',      format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected BA vs this pitch type (Statcast, EV + LA)', group: 'stats' },
    { key: 'xSLG',        label: 'xSLG',     format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected SLG vs this pitch type (Statcast, EV + LA)', group: 'stats' },
    { key: 'xwOBA',       label: 'xwOBA',    format: Utils.formatDecimal(3), sortType: 'numeric', desc: 'Expected wOBA vs this pitch type (Statcast, EV + LA)', group: 'stats' },
    { key: 'ev50',        label: 'EV50',     format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, desc: 'Avg EV of top 50% hardest-hit BIP (mph)', group: 'ev' },
    { key: 'maxEV',       label: 'Max EV',   format: Utils.formatDecimal(1), sortType: 'numeric', desc: 'Maximum exit velocity (mph)', group: 'ev' },
    { key: 'medLA',       label: 'Med LA',   format: Utils.formatDecimal(1), sortType: 'numeric', sectionStart: true, desc: 'Median launch angle (degrees)', group: 'batted_ball' },
    { key: 'barrelPct',   label: 'Barrel%',  format: Utils.formatPct, sortType: 'numeric', desc: 'Barrel rate (Statcast barrel definition)', group: 'batted_ball' },
    { key: 'gbPct',       label: 'GB%',      format: Utils.formatPct, sortType: 'numeric', sectionStart: true, desc: 'Ground ball rate', group: 'batted_ball' },
    { key: 'ldPct',       label: 'LD%',      format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Line drive rate', group: 'batted_ball' },
    { key: 'fbPct',       label: 'FB%',      format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Fly ball rate', group: 'batted_ball' },
    { key: 'pullPct',     label: 'Pull%',    format: Utils.formatPct, sortType: 'numeric', noPercentile: true, sectionStart: true, desc: 'Pull rate', group: 'spray' },
    { key: 'oppoPct',     label: 'Oppo%',    format: Utils.formatPct, sortType: 'numeric', noPercentile: true, desc: 'Opposite field rate', group: 'spray' },
    { key: 'swingPct',    label: 'Swing%',   format: Utils.formatPct, sortType: 'numeric', sectionStart: true, desc: 'Swing rate vs this pitch type', group: 'discipline' },
    { key: 'izSwingPct',  label: 'IZSw%',    format: Utils.formatPct, sortType: 'numeric', desc: 'In-zone swing rate', group: 'discipline' },
    { key: 'chasePct',    label: 'Chase%',   format: Utils.formatPct, sortType: 'numeric', desc: 'Out-of-zone swing rate', group: 'discipline' },
    { key: 'contactPct',  label: 'Contact%', format: Utils.formatPct, sortType: 'numeric', desc: 'Contact rate (contact / swings)', group: 'discipline' },
    { key: 'izContactPct', label: 'IZCT%',   format: Utils.formatPct, sortType: 'numeric', desc: 'In-zone contact rate', group: 'discipline' },
    { key: 'whiffPct',    label: 'Whiff%',   format: Utils.formatPct, sortType: 'numeric', desc: 'Whiff rate (misses / swings)', group: 'discipline' },
  ],
};

const Leaderboard = {
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
    this.hiddenColumns['vaa'] = true;
    this.hiddenColumns['haa'] = true;
  },

  getVisibleColumns: function (columns) {
    const self = this;
    return columns.filter(function (col) {
      return !self.hiddenColumns[col.key];
    });
  },

  sortData: function (data, columnKey, columns) {
    let col = null;
    for (let i = 0; i < columns.length; i++) {
      if (columns[i].key === columnKey) { col = columns[i]; break; }
    }
    if (!col || col.sortType === null) return data;

    const sortKey = col.sortKey || col.key;

    if (this.currentSort.key === columnKey) {
      this.currentSort.dir = this.currentSort.dir === 'desc' ? 'asc' : 'desc';
    } else {
      this.currentSort.key = columnKey;
      this.currentSort.dir = col.sortType === 'string' ? 'asc' : 'desc';
    }

    const dir = this.currentSort.dir === 'asc' ? 1 : -1;

    data.sort(function (a, b) {
      const va = a[sortKey];
      const vb = b[sortKey];
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

  computeLeagueAvgRow: function (data, columns, opts) {
    const avg = {};
    const meta = DataStore.metadata || {};

    // When contextual filters (hand, role) are active, skip precomputed static
    // averages and compute dynamically from the filtered league data
    const hasContextualFilter = (opts.vsHand && opts.vsHand !== 'all') ||
                                 (opts.throws && opts.throws !== 'all') ||
                                 (opts.role && opts.role !== 'all');

    // Always load precomputed averages
    const isPitcher = data.length > 0 && data[0].pitcher;
    const overallAvgs = isPitcher ? (meta.pitcherLeagueAverages || {}) : (meta.hitterLeagueAverages || {});
    const pitchTypeAvgs = meta.leagueAverages || {};
    const pitchTypes = (opts && opts.pitchTypes) || 'all';
    let precomputed;
    if (pitchTypes !== 'all' && Array.isArray(pitchTypes) && pitchTypes.length === 1 && pitchTypeAvgs[pitchTypes[0]]) {
      precomputed = pitchTypeAvgs[pitchTypes[0]];
    } else if (pitchTypes !== 'all' && Array.isArray(pitchTypes) && pitchTypes.length > 1) {
      precomputed = {};
    } else {
      precomputed = overallAvgs;
    }

    // Stats that should recalculate when contextual filters are active.
    // Everything else (pitch metrics, plate discipline) keeps precomputed values.
    var DYNAMIC_STATS = { runValue:1, rv100:1, xBA:1, xSLG:1, wOBA:1, xwOBA:1, xwOBAcon:1, xwOBAsp:1,
                          era:1, fip:1, xFIP:1, siera:1, hr9:1,
                          avg:1, obp:1, slg:1, ops:1, iso:1 };

    // Keys where average should use absolute values (RHP/LHP have opposite signs)
    const ABS_AVG_KEYS = { horzBrk: true, haa: true, relPosX: true };
    const numericKeys = [];
    for (let i = 0; i < columns.length; i++) {
      if (columns[i].sortType === 'numeric' && !columns[i].noPercentile && columns[i].key !== '_rank') {
        numericKeys.push(columns[i].key);
      }
    }

    // IP parser for ERA/FIP-style stats (ip stored as string like "6.1")
    function _parseIP(ipStr) {
      if (ipStr == null) return 0;
      var parts = String(ipStr).split('.');
      return parseInt(parts[0], 10) + (parts[1] ? parseInt(parts[1], 10) / 3 : 0);
    }

    // Weight mapping — matches process_data.py precomputed average methodology
    var IP_WEIGHTED = { era:1, fip:1, xFIP:1, siera:1, hr9:1 };
    var BIP_WEIGHTED = { avgEVAgainst:1, maxEVAgainst:1, hardHitPct:1, barrelPctAgainst:1,
                          gbPct:1, ldPct:1, fbPct:1, puPct:1, hrFbPct:1, xwOBAsp:1,
                          avgEV:1, maxEV:1, barrelPct:1, pullPct:1, airPullPct:1 };
    var PA_WEIGHTED = { wOBA:1, xBA:1, xSLG:1, xwOBA:1, xwOBAcon:1,
                         kPct:1, bbPct:1, kbbPct:1, babip:1,
                         avg:1, obp:1, slg:1, ops:1, iso:1 };

    numericKeys.forEach(function (key) {
      if (DYNAMIC_STATS[key]) {
        // Dynamic stats: use precomputed when no contextual filter, else compute from filtered data
        if (!hasContextualFilter && precomputed[key] !== undefined && precomputed[key] !== null) {
          avg[key] = precomputed[key];
          return;
        }
        var useAbs = ABS_AVG_KEYS[key] || false;
        var sumW = 0, totalW = 0;
        for (var j = 0; j < data.length; j++) {
          var v = data[j][key];
          if (v === null || v === undefined) continue;
          var w;
          if (IP_WEIGHTED[key]) {
            w = _parseIP(data[j].ip);
          } else if (BIP_WEIGHTED[key]) {
            w = data[j].nBip || 0;
          } else if (PA_WEIGHTED[key]) {
            w = data[j].pa || 0;
          } else {
            w = data[j].count || 0;
          }
          if (w > 0) {
            sumW += (useAbs ? Math.abs(v) : v) * w;
            totalW += w;
          }
        }
        avg[key] = totalW > 0 ? sumW / totalW : null;
      } else {
        // Non-dynamic stats (velo, spin, IVB, etc.): only use precomputed values.
        // Shows "--" when no precomputed value exists (e.g. all pitch types view).
        if (precomputed[key] !== undefined && precomputed[key] !== null) {
          avg[key] = precomputed[key];
        }
      }
    });
    avg.pitcher = 'League Avg';
    avg.hitter = 'League Avg';
    avg._isLeagueAvg = true;
    avg._rank = '';
    // wRC+, xWRC+, and Stuff+ are by definition 100 for league average
    avg.wRCplus = 100;
    avg.xWRCplus = 100;
    avg.stuffScore = 100;
    return avg;
  },

  render: function (data, columns, opts) {
    opts = opts || {};
    const self = this;
    const visCols = this.getVisibleColumns(columns);
    let headerRow = document.getElementById('table-header');
    const tbody = document.getElementById('table-body');
    const pinnedBody = document.getElementById('table-pinned-body');
    const noResults = document.getElementById('no-results');
    const isDark = document.body.classList.contains('dark');

    this.lastRenderedData = data;
    this.lastRenderedColumns = columns;
    this._lastRenderOpts = opts;

    // Pagination
    const totalRows = data.length;
    const pageSize = this.pageSize;
    const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(totalRows / pageSize)) : 1;
    if (this.currentPage > totalPages) this.currentPage = totalPages;
    const startIdx = pageSize > 0 ? (this.currentPage - 1) * pageSize : 0;
    const endIdx = pageSize > 0 ? Math.min(startIdx + pageSize, totalRows) : totalRows;
    const pageData = data.slice(startIdx, endIdx);

    // Update pagination UI
    const pageInfo = document.getElementById('page-info');
    const pagePrev = document.getElementById('page-prev');
    const pageNext = document.getElementById('page-next');
    if (pageInfo) pageInfo.textContent = 'Page ' + this.currentPage + ' of ' + totalPages;
    if (pagePrev) pagePrev.disabled = this.currentPage <= 1;
    if (pageNext) pageNext.disabled = this.currentPage >= totalPages;

    // Build header - group row + column row
    let thead = document.querySelector('#leaderboard-table thead');
    thead.innerHTML = '';

    // Group header row
    const groupRow = document.createElement('tr');
    groupRow.id = 'table-group-header';
    const groupLabels = { info: '', rates: 'Rates', stats: 'Stats', metrics: 'Metrics', counting: 'Counting', advanced: 'Advanced', ev: 'Exit Velo', batted_ball: 'Batted Ball', spray: 'Spray', discipline: 'Discipline', bat_tracking: 'Bat Tracking' };
    let prevGroup = null;
    const groupSpans = [];
    visCols.forEach(function (col) {
      const g = col.group || 'info';
      if (g === prevGroup) {
        groupSpans[groupSpans.length - 1].span++;
      } else {
        groupSpans.push({ group: g, span: 1, sticky: col.sticky });
        prevGroup = g;
      }
    });
    const hasGroups = groupSpans.some(function (gs) { return groupLabels[gs.group]; });
    if (hasGroups) {
      let colIdx = 0;
      groupSpans.forEach(function (gs) {
        const th = document.createElement('th');
        th.setAttribute('colspan', gs.span);
        th.textContent = groupLabels[gs.group] || '';
        th.classList.add('group-header-cell');
        if (gs.sticky) { th.classList.add('sticky-col'); th.classList.add('sticky-col-last'); }
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
      const th = document.createElement('th');
      if (col.isCompare) {
        th.classList.add('col-compare');
        th.style.width = col.width || 'auto';
      } else {
        const labelSpan = document.createElement('span');
        labelSpan.textContent = col.label;
        th.appendChild(labelSpan);
        // Fixed-width sort indicator to prevent layout shift
        if (col.sortType !== null) {
          const sortSpan = document.createElement('span');
          sortSpan.className = 'sort-indicator';
          sortSpan.style.display = 'inline-block';
          sortSpan.style.width = '12px';
          sortSpan.style.textAlign = 'center';
          sortSpan.style.fontSize = '9px';
          sortSpan.style.marginLeft = '2px';
          sortSpan.style.color = 'var(--accent)';
          if (self.currentSort.key === col.key) {
            sortSpan.textContent = self.currentSort.dir === 'asc' ? '\u25B2' : '\u25BC';
          }
          th.appendChild(sortSpan);
        }
      }
      th.setAttribute('data-key', col.key);
      if (col.align) th.classList.add('align-' + col.align);
      if (col.sticky) th.classList.add('sticky-col');
      if (col.stickyIdx === 1) th.classList.add('sticky-col-last');
      if (col.sectionStart) th.classList.add('section-start');
      if (col.width) th.style.width = col.width;
      if (col.desc) th.title = col.desc;
      else if (Utils.TOOLTIPS[col.label]) th.title = Utils.TOOLTIPS[col.label];

      if (self.currentSort.key === col.key) {
        th.classList.add('sorted', self.currentSort.dir);
        th.setAttribute('aria-sort', self.currentSort.dir === 'asc' ? 'ascending' : 'descending');
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
      const groupRowHeight = groupRow.offsetHeight || 25;
      for (let hi = 0; hi < headerRow.cells.length; hi++) {
        headerRow.cells[hi].style.top = groupRowHeight + 'px';
      }
    }

    // Calculate sticky column offsets (for frozen Team column)
    this._stickyLeftOffsets = {};
    let firstStickyTh = null;
    for (let si = 0; si < visCols.length; si++) {
      if (visCols[si].sticky && !visCols[si].stickyIdx) {
        firstStickyTh = headerRow.cells[si];
        break;
      }
    }
    if (firstStickyTh) {
      const firstStickyWidth = firstStickyTh.offsetWidth;
      for (let si2 = 0; si2 < visCols.length; si2++) {
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
      const thead2 = document.querySelector('#leaderboard-table thead');
      const thHeight = thead2 ? thead2.offsetHeight : 36;

      // League Average: computed from all-teams data (ignores team filter)
      const leagueAvgData = opts.leagueData || data;
      const leagueAvgRow = this.computeLeagueAvgRow(leagueAvgData, visCols, opts);
      leagueAvgRow.pitcher = 'League Avg';
      leagueAvgRow.hitter = 'League Avg';
      const leagueTr = this._createRow(leagueAvgRow, visCols, -1, isDark, true);
      leagueTr.classList.add('league-avg-row');
      pinnedBody.appendChild(leagueTr);

      // Make league avg row cells sticky
      for (let ci = 0; ci < leagueTr.cells.length; ci++) {
        leagueTr.cells[ci].style.position = 'sticky';
        leagueTr.cells[ci].style.top = thHeight + 'px';
        leagueTr.cells[ci].style.zIndex = leagueTr.cells[ci].classList.contains('sticky-col') ? '5' : '3';
      }

    }

    const fragment = document.createDocumentFragment();

    // Data rows
    for (let ri = 0; ri < pageData.length; ri++) {
      const row = pageData[ri];
      const globalRank = startIdx + ri + 1;
      const tr = this._createRow(row, visCols, globalRank, isDark, false);
      tr.classList.add('clickable-row');
      tr._playerName = row.pitcher || row.hitter;
      tr._rowData = row;
      tr._rowIndex = ri;

      if (this.keyboardFocusIndex === ri) {
        tr.classList.add('keyboard-focus');
      }

      fragment.appendChild(tr);
    }

    tbody.appendChild(fragment);

    // Event delegation: single click handler on tbody instead of per-row listeners
    if (!tbody._delegatedClick) {
      tbody.addEventListener('click', function (e) {
        if (e.target.type === 'checkbox') return;
        const tr = e.target.closest('tr.clickable-row');
        if (!tr || !tr._rowData) return;
        // Remove active from all rows
        const prev = tbody.querySelectorAll('.active-row');
        for (let k = 0; k < prev.length; k++) prev[k].classList.remove('active-row');
        // Highlight all rows for this person
        const personName = tr._playerName;
        const allRows = tbody.querySelectorAll('tr');
        allRows.forEach(function (row) {
          if (row._playerName === personName) row.classList.add('active-row');
        });
        self.keyboardFocusIndex = tr._rowIndex;
        const r = tr._rowData;
        if (typeof App !== 'undefined' && App.openSidePanel) {
          App.openSidePanel(personName, r.team, r.throws || r.stands, r);
        }
      });
      tbody._delegatedClick = true;
    }
    document.getElementById('row-count').textContent = totalRows;
  },

  _createRow: function (row, visCols, rank, isDark, isAvgRow) {
    const self = this;
    const tr = document.createElement('tr');

    visCols.forEach(function (col) {
      const td = document.createElement('td');

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
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          const compareKey = (row.pitcher || '') + '|' + (row.team || '');
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
        const badge = document.createElement('span');
        badge.className = 'pitch-badge';
        badge.textContent = row[col.key];
        const pitchColor = Utils.getPitchColor(row[col.key]);
        badge.style.backgroundColor = pitchColor;
        badge.style.color = Utils.badgeTextColor(pitchColor);
        td.appendChild(badge);
        if (col.align) td.classList.add('align-' + col.align);
        tr.appendChild(td);
        return;
      }

      // Player name as clickable link to player page (pitcher or hitter)
      if ((col.key === 'pitcher' || col.key === 'hitter') && !isAvgRow && row.mlbId) {
        const nameLink = document.createElement('a');
        nameLink.href = '#player=' + row.mlbId;
        nameLink.className = 'pitcher-name-link';
        nameLink.textContent = col.format(row[col.key]);
        nameLink.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          PlayerPage.open(row.mlbId);
        });
        td.appendChild(nameLink);
        if (col.align) td.classList.add('align-' + col.align);
        if (col.sticky) {
          td.classList.add('sticky-col');
          if (col.stickyIdx === 1) { td.classList.add('sticky-col-last'); }
          if (col.stickyIdx === 1 && self._stickyLeftOffsets[col.key]) {
            td.style.left = self._stickyLeftOffsets[col.key] + 'px';
          }
        }
        if (col.cls) td.classList.add(col.cls);
        tr.appendChild(td);
        return;
      }

      // Regular cell
      const val = row[col.key];
      td.textContent = col.format(val);
      if (col.align) td.classList.add('align-' + col.align);
      if (col.sticky) {
        td.classList.add('sticky-col');
        if (col.stickyIdx === 1) { td.classList.add('sticky-col-last'); }
        if (col.stickyIdx === 1 && self._stickyLeftOffsets[col.key]) {
          td.style.left = self._stickyLeftOffsets[col.key] + 'px';
        }
      }
      if (col.cls) td.classList.add(col.cls);
      if (col.sectionStart) td.classList.add('section-start');
      if (val === null || val === undefined) td.classList.add('col-null');

      // Percentile coloring (only for qualified players, with exceptions)
      if (!col.noPercentile && !isAvgRow) {
        const pctlKey = col.key + '_pctl';
        const pctl = row[pctlKey];
        if (pctl !== null && pctl !== undefined) {
          // Determine qualifying status
          const isPitcherRow = !!row.pitcher;
          const isHitterRow = !!row.hitter;
          const isSinglePitchType = self._lastRenderOpts &&
              Array.isArray(self._lastRenderOpts.pitchTypes) &&
              self._lastRenderOpts.pitchTypes.length === 1;
          const isHitterPitchType = isHitterRow && row.pitchType != null;
          const teamGames = Aggregator.loaded ? Aggregator.getTeamGamesPlayed() : {};
          const tg = teamGames[row.team] || 0;
          let showColor;
          // Pitch shape metrics always show color on single-pitch-type views (no min count)
          const PITCH_SHAPE_ALWAYS_COLOR = {
            velocity: true, spinRate: true, indVertBrk: true, horzBrk: true,
            vaa: true, haa: true, nVAA: true, nHAA: true
          };
          // Hitter stats that require ≥20 BIP
          const HITTER_BIP_STATS = {
            avgEVAll: true, ev50: true, maxEV: true, medLA: true,
            hardHitPct: true, barrelPct: true,
            xBA: true, xSLG: true, xwOBA: true, xwOBAcon: true, xwOBAsp: true,
            babip: true, hrFbPct: true, airPullPct: true,
            gbPct: true, ldPct: true, fbPct: true, puPct: true,
            pullPct: true, middlePct: true, oppoPct: true
          };
          // Hitter stats that require ≥10 competitive swings
          const HITTER_BAT_TRACKING = { batSpeed: true, swingLength: true, blastPct: true, idealAAPct: true };

          if (isPitcherRow && isSinglePitchType) {
            // Pitcher pitch-type: shape metrics always qualify; outcome metrics need ≥50 pitches
            showColor = PITCH_SHAPE_ALWAYS_COLOR[col.key] || (row.count || 0) >= 50;
          } else if (isPitcherRow) {
            // Pitcher overall: IP-based qualification
            const ipStr = row.ip;
            let ipFloat = 0;
            if (ipStr != null) {
              const ipParts = String(ipStr).split('.');
              ipFloat = parseInt(ipParts[0], 10) + (ipParts[1] ? parseInt(ipParts[1], 10) / 3 : 0);
            }
            const rg = row.g || 0;
            const rgs = row.gs || 0;
            const isStarter = rg > 0 && (rgs / rg) > 0.5;
            const ipThresh = isStarter ? tg * 1.0 : tg * 0.1;
            showColor = ipFloat >= ipThresh;
            // Pitcher always-color: FB velo, extension
            if (!showColor) showColor = col.key === 'fbVelo' || col.key === 'extension';
          } else if (isHitterPitchType) {
            // Hitter pitch-type: ≥25 pitches of that type seen
            showColor = (row.count || 0) >= 25;
          } else {
            // Hitter overall: per-stat qualification gates
            const paQual = (row.pa || 0) >= tg * 3.1;
            if (HITTER_BIP_STATS[col.key]) {
              showColor = (row.nBip || 0) >= 20;
            } else if (HITTER_BAT_TRACKING[col.key]) {
              showColor = (row.nCompSwings || 0) >= 10;
            } else if (col.key === 'sprintSpeed') {
              showColor = (row.nCompRuns || 0) >= 10;
            } else {
              showColor = paQual;
            }
            // Hitter always-color: maxEV
            if (!showColor && col.key === 'maxEV') showColor = true;
          }

          if (showColor) {
            if (isDark) {
              td.style.backgroundColor = Utils.percentileColorDark(pctl);
              td.style.color = Utils.percentileTextColorDark(pctl);
            } else {
              td.style.backgroundColor = Utils.percentileColor(pctl);
              td.style.color = Utils.percentileTextColor(pctl);
            }
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
