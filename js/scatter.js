const ScatterChart = {
  chart: null,
  compareChart: null,

  MARKER_STYLES: ['circle', 'triangle', 'rect', 'rectRot'],

  getColor: function (pt) {
    return { bg: Utils.getPitchColor(pt), border: Utils.getPitchBorderColor(pt) };
  },

  computeEllipse: function (points) {
    if (points.length < QUAL.MIN_ELLIPSE_PTS) return null;
    const n = points.length;
    let mx = 0, my = 0;
    for (let i = 0; i < n; i++) { mx += points[i].x; my += points[i].y; }
    mx /= n; my /= n;
    let cxx = 0, cxy = 0, cyy = 0;
    for (let i = 0; i < n; i++) {
      const dx = points[i].x - mx, dy = points[i].y - my;
      cxx += dx * dx; cxy += dx * dy; cyy += dy * dy;
    }
    cxx /= n; cxy /= n; cyy /= n;
    const trace = cxx + cyy;
    const det = cxx * cyy - cxy * cxy;
    const disc = Math.sqrt(Math.max(0, trace * trace / 4 - det));
    const l1 = trace / 2 + disc;
    const l2 = trace / 2 - disc;
    let angle = 0;
    if (cxy !== 0) angle = Math.atan2(l1 - cxx, cxy);
    else if (cxx < cyy) angle = Math.PI / 2;
    const rx = 1.5 * Math.sqrt(Math.max(0, l1));
    const ry = 1.5 * Math.sqrt(Math.max(0, l2));
    return { cx: mx, cy: my, rx: rx, ry: ry, angle: angle };
  },

  ellipsePlugin: {
    id: 'ellipsePlugin',
    afterDatasetsDraw: function (chart) {
      const ctx = chart.ctx;
      const xScale = chart.scales.x;
      const yScale = chart.scales.y;

      ctx.save();

      const zeroX = xScale.getPixelForValue(0);
      const zeroY = yScale.getPixelForValue(0);
      ctx.strokeStyle = '#999';
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(zeroX, yScale.top);
      ctx.lineTo(zeroX, yScale.bottom);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(xScale.left, zeroY);
      ctx.lineTo(xScale.right, zeroY);
      ctx.stroke();

      const meta = chart._ellipseMeta;
      if (meta) {
        for (let i = 0; i < meta.length; i++) {
          const e = meta[i];
          if (!e.ellipse) continue;
          const cpx = xScale.getPixelForValue(e.ellipse.cx);
          const cpy = yScale.getPixelForValue(e.ellipse.cy);
          const rpxX = Math.abs(xScale.getPixelForValue(e.ellipse.rx) - xScale.getPixelForValue(0));
          const rpxY = Math.abs(yScale.getPixelForValue(e.ellipse.ry) - yScale.getPixelForValue(0));
          ctx.strokeStyle = e.color;
          ctx.lineWidth = 1.5;
          // Vary dash pattern by pitch category
          const fastballs = { FF: 1, SI: 1 };
          const breaking = { FC: 1, SL: 1, ST: 1, CU: 1, SV: 1 };
          // offspeed: CH, FS, KN (default)
          if (e.pitchType && fastballs[e.pitchType]) {
            ctx.setLineDash([]);         // solid
          } else if (e.pitchType && breaking[e.pitchType]) {
            ctx.setLineDash([6, 4]);     // dashed
          } else {
            ctx.setLineDash([2, 4]);     // dotted (offspeed / unknown)
          }
          ctx.beginPath();
          ctx.save();
          ctx.translate(cpx, cpy);
          ctx.rotate(-e.ellipse.angle);
          ctx.ellipse(0, 0, rpxX, rpxY, 0, 0, 2 * Math.PI);
          ctx.restore();
          ctx.stroke();
        }
      }

      ctx.restore();
    }
  },

  _buildMovementData: function (pitcherName, team) {
    const details = window.PITCH_DETAILS;
    if (!details) return null;
    const key = pitcherName + '|' + (team || '');
    const pitches = details[key];
    if (!pitches || pitches.length === 0) return null;

    const groups = {};
    for (let i = 0; i < pitches.length; i++) {
      const p = pitches[i];
      if (!groups[p.pt]) groups[p.pt] = [];
      groups[p.pt].push({ x: p.hb, y: p.ivb });
    }
    return groups;
  },

  render: function (pitcherName, team) {
    const groups = this._buildMovementData(pitcherName, team);
    if (!groups) return;

    const datasets = [];
    const ellipseMeta = [];
    const pitchTypes = Utils.sortPitchTypes(Object.keys(groups));

    for (let j = 0; j < pitchTypes.length; j++) {
      const pt = pitchTypes[j];
      const pts = groups[pt];
      const color = this.getColor(pt);
      const label = pt + ' - ' + Utils.pitchTypeLabel(pt);

      datasets.push({
        label: label,
        data: pts,
        backgroundColor: color.bg,
        borderColor: color.border,
        borderWidth: 1.5,
        pointRadius: 6,
        pointHoverRadius: 8,
      });

      const ellipse = this.computeEllipse(pts);
      ellipseMeta.push({ color: color.border, ellipse: ellipse, pitchType: pt });
    }

    this.destroyMain();

    const canvas = document.getElementById('pitch-chart');
    const ctx = canvas.getContext('2d');

    this.chart = new Chart(ctx, {
      type: 'scatter',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 1,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, pointStyle: 'circle', padding: 14, font: { size: 11 } },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ': IVB ' + ctx.parsed.y.toFixed(1) + ', HB ' + ctx.parsed.x.toFixed(1);
              }
            }
          }
        },
        scales: {
          x: {
            title: { display: true, text: 'Horizontal Break (in.)', font: { size: 12, weight: 'bold' } },
            min: -25, max: 25,
            grid: { display: true, color: 'rgba(0,0,0,0.06)' },
            ticks: { stepSize: 5 },
          },
          y: {
            title: { display: true, text: 'Induced Vertical Break (in.)', font: { size: 12, weight: 'bold' } },
            min: -25, max: 25,
            grid: { display: true, color: 'rgba(0,0,0,0.06)' },
            ticks: { stepSize: 5 },
          },
        },
        animation: { duration: 300 },
      },
      plugins: [this.ellipsePlugin],
    });

    this.chart._ellipseMeta = ellipseMeta;
  },

  renderCompare: function (pitcherNames) {
    if (!pitcherNames || pitcherNames.length === 0) return;

    const datasets = [];
    const details = window.PITCH_DETAILS;
    if (!details) return;

    for (let pi = 0; pi < pitcherNames.length; pi++) {
      const key = pitcherNames[pi]; // format: "name|team"
      const pitches = details[key];
      if (!pitches) continue;
      const name = key.split('|')[0];

      const groups = {};
      for (let i = 0; i < pitches.length; i++) {
        const p = pitches[i];
        if (!groups[p.pt]) groups[p.pt] = [];
        groups[p.pt].push({ x: p.hb, y: p.ivb });
      }

      const pitchTypes = Utils.sortPitchTypes(Object.keys(groups));
      const markerStyle = this.MARKER_STYLES[pi % this.MARKER_STYLES.length];

      for (let j = 0; j < pitchTypes.length; j++) {
        const pt = pitchTypes[j];
        const color = this.getColor(pt);
        datasets.push({
          label: name + ' - ' + pt,
          data: groups[pt],
          backgroundColor: color.bg,
          borderColor: color.border,
          borderWidth: 1.5,
          pointRadius: 6,
          pointHoverRadius: 8,
          pointStyle: markerStyle,
        });
      }
    }

    this.destroyCompare();

    const canvas = document.getElementById('compare-chart');
    const ctx = canvas.getContext('2d');

    this.compareChart = new Chart(ctx, {
      type: 'scatter',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 1,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, padding: 12, font: { size: 11 } },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ': IVB ' + ctx.parsed.y.toFixed(1) + ', HB ' + ctx.parsed.x.toFixed(1);
              }
            }
          }
        },
        scales: {
          x: {
            title: { display: true, text: 'Horizontal Break (in.)', font: { size: 12, weight: 'bold' } },
            min: -25, max: 25,
            grid: { display: true, color: 'rgba(0,0,0,0.06)' },
            ticks: { stepSize: 5 },
          },
          y: {
            title: { display: true, text: 'Induced Vertical Break (in.)', font: { size: 12, weight: 'bold' } },
            min: -25, max: 25,
            grid: { display: true, color: 'rgba(0,0,0,0.06)' },
            ticks: { stepSize: 5 },
          },
        },
        animation: { duration: 300 },
      },
      plugins: [this.ellipsePlugin],
    });

    this.compareChart._ellipseMeta = [];
  },

  destroyMain: function () {
    if (this.chart) { this.chart.destroy(); this.chart = null; }
  },

  destroyCompare: function () {
    if (this.compareChart) { this.compareChart.destroy(); this.compareChart = null; }
  },

  destroy: function () {
    this.destroyMain();
  },
};
