/**
 * Zone E — 감성 vs 수익률 산점도
 * Zone F — 시간 지연별 상관계수 바 차트
 */

const GRID_COLOR = 'rgba(61, 58, 57, 0.5)';

let scatterChart = null;
let lagChart = null;
let _scatterData = null;

/* ── 선형 회귀 ─────────────────────────────────────────────────────── */
function linearRegression(points) {
  const n = points.length;
  if (n < 2) return null;
  const sumX  = points.reduce((s, p) => s + p.x, 0);
  const sumY  = points.reduce((s, p) => s + p.y, 0);
  const sumXY = points.reduce((s, p) => s + p.x * p.y, 0);
  const sumX2 = points.reduce((s, p) => s + p.x * p.x, 0);
  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;
  const xMin = Math.min(...points.map(p => p.x));
  const xMax = Math.max(...points.map(p => p.x));
  return [
    { x: xMin, y: slope * xMin + intercept },
    { x: xMax, y: slope * xMax + intercept },
  ];
}

/* ── Zone E: Scatter ─────────────────────────────────────────────────── */
export function initScatterChart(canvasId, scatterData) {
  _scatterData = scatterData;
  renderScatter(canvasId, 'return_15m');
}

export function updateScatterLag(canvasId, lag) {
  if (!_scatterData) return;
  renderScatter(canvasId, lag);
}

function renderScatter(canvasId, lagKey) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !_scatterData?.length) return;

  const points = _scatterData
    .filter(d => d.sentiment != null && d[lagKey] != null)
    .map(d => ({ x: d.sentiment, y: d[lagKey], date: d.date }));

  const posPoints = points.filter(p => p.y >= 0);
  const negPoints = points.filter(p => p.y < 0);
  const trendLine = linearRegression(points);

  const cfg = {
    type: 'scatter',
    data: {
      datasets: [
        {
          label: 'Positive return',
          data: posPoints,
          backgroundColor: 'rgba(47, 214, 161, 0.55)',
          pointRadius: 5,
          pointHoverRadius: 7,
        },
        {
          label: 'Negative return',
          data: negPoints,
          backgroundColor: 'rgba(251, 86, 91, 0.55)',
          pointRadius: 5,
          pointHoverRadius: 7,
        },
        ...(trendLine
          ? [{
              label: 'Trend',
              type: 'line',
              data: trendLine,
              borderColor: 'rgba(242, 242, 242, 0.25)',
              borderWidth: 1.5,
              borderDash: [4, 4],
              pointRadius: 0,
              fill: false,
            }]
          : []),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#101010',
          borderColor: '#3d3a39',
          borderWidth: 1,
          titleColor: '#8b949e',
          bodyColor: '#f2f2f2',
          padding: 10,
          filter: item => item.datasetIndex < 2,
          callbacks: {
            title(items) {
              const raw = items[0]?.raw;
              return raw?.date ? new Date(raw.date).toLocaleDateString('ko-KR') : '';
            },
            label(ctx) {
              return [
                `  Sentiment: ${ctx.parsed.x.toFixed(3)}`,
                `  Return:    ${ctx.parsed.y.toFixed(4)}%`,
              ];
            },
          },
        },
      },
      scales: {
        x: {
          title: {
            display: true,
            text: 'Sentiment Score',
            color: '#8b949e',
            font: { family: "'SFMono-Regular', monospace", size: 10 },
          },
          ticks: { color: '#8b949e', font: { family: "'SFMono-Regular', monospace", size: 10 } },
          grid: { color: GRID_COLOR },
          border: { color: GRID_COLOR },
        },
        y: {
          title: {
            display: true,
            text: `Return (${lagKey.replace('return_', 'T+')})  %`,
            color: '#8b949e',
            font: { family: "'SFMono-Regular', monospace", size: 10 },
          },
          ticks: {
            color: '#8b949e',
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            callback: v => `${v.toFixed(2)}%`,
          },
          grid: { color: GRID_COLOR },
          border: { color: GRID_COLOR },
        },
      },
    },
  };

  if (scatterChart) scatterChart.destroy();
  scatterChart = new Chart(canvas, cfg);
}

/* ── Zone F: Lag bar chart ───────────────────────────────────────────── */
export function initLagChart(canvasId, lagData) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !lagData?.length) return;

  const labels = lagData.map(d => `T+${d.lag}`);
  const rValues = lagData.map(d => d.r ?? 0);
  const pValues = lagData.map(d => d.p);

  const barColors = rValues.map((r, i) => {
    if (pValues[i] > 0.05) return '#8b949e';
    return r >= 0 ? '#0ea5e9' : '#fb565b';
  });

  const cfg = {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Pearson r',
        data: rValues,
        backgroundColor: barColors,
        borderRadius: 3,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#101010',
          borderColor: '#3d3a39',
          borderWidth: 1,
          titleColor: '#8b949e',
          bodyColor: '#f2f2f2',
          padding: 10,
          callbacks: {
            label(ctx) {
              const i = ctx.dataIndex;
              const p = pValues[i];
              const sig = p == null ? '' : p <= 0.01 ? ' **' : p <= 0.05 ? ' *' : ' (n.s.)';
              return [
                `  r = ${ctx.parsed.y.toFixed(4)}${sig}`,
                `  p = ${p?.toFixed(4) ?? 'N/A'}`,
                `  n = ${lagData[i].n ?? '?'}`,
              ];
            },
          },
        },
        /* p-value 라벨을 각 바 위에 표시 */
        afterDraw: null,
      },
      scales: {
        x: {
          ticks: { color: '#8b949e', font: { family: "'SFMono-Regular', monospace", size: 11 } },
          grid: { display: false },
          border: { color: GRID_COLOR },
        },
        y: {
          min: -1, max: 1,
          ticks: {
            color: '#8b949e',
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            callback: v => v.toFixed(1),
            maxTicksLimit: 7,
          },
          grid: { color: GRID_COLOR },
          border: { color: GRID_COLOR },
        },
      },
    },
    plugins: [{
      id: 'pValueLabels',
      afterDatasetsDraw(chart) {
        const { ctx } = chart;
        chart.data.datasets[0].data.forEach((r, i) => {
          const p = pValues[i];
          if (p == null) return;
          const sig = p <= 0.01 ? '**' : p <= 0.05 ? '*' : '';
          const label = `p=${p.toFixed(3)}${sig ? ' ' + sig : ''}`;
          const meta = chart.getDatasetMeta(0);
          const bar  = meta.data[i];
          ctx.save();
          ctx.fillStyle = '#8b949e';
          ctx.font = `10px 'SFMono-Regular', monospace`;
          ctx.textAlign = 'center';
          const yPos = r >= 0 ? bar.y - 6 : bar.y + 14;
          ctx.fillText(label, bar.x, yPos);
          ctx.restore();
        });
        /* r=0 기준선 */
        const yScale = chart.scales.y;
        const y0 = yScale.getPixelForValue(0);
        ctx.save();
        ctx.strokeStyle = 'rgba(61,58,57,0.9)';
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(chart.chartArea.left, y0);
        ctx.lineTo(chart.chartArea.right, y0);
        ctx.stroke();
        ctx.restore();
      },
    }],
  };

  if (lagChart) lagChart.destroy();
  lagChart = new Chart(canvas, cfg);
}
