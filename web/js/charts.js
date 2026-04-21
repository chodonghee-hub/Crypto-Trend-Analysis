/**
 * Zone B — BTC 가격 + 감성 점수 듀얼 축 라인 차트 (Chart.js)
 */

const PRICE_COLOR     = '#0ea5e9';
const SENTIMENT_COLOR = '#818cf8';
const GRID_COLOR      = 'rgba(61, 58, 57, 0.5)';

let dualChart = null;

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

function formatDate(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:00`;
}

/** 감성 시리즈를 가격 klines의 timestamps에 맞게 보간 */
function alignSentiment(klines, sentimentSeries) {
  if (!sentimentSeries?.length) return klines.map(() => null);

  const sorted = [...sentimentSeries].sort(
    (a, b) => new Date(a.timestamp) - new Date(b.timestamp),
  );

  return klines.map(k => {
    const kTime = k.time;
    let closest = sorted[0];
    for (const s of sorted) {
      const diff = Math.abs(new Date(s.timestamp) - kTime);
      const closestDiff = Math.abs(new Date(closest.timestamp) - kTime);
      if (diff < closestDiff) closest = s;
    }
    // 2시간 이상 떨어진 경우 null 처리
    return Math.abs(new Date(closest.timestamp) - kTime) > 2 * 3600 * 1000
      ? null
      : closest.score;
  });
}

export function initDualChart(canvasId, klines, sentimentSeries) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const labels = klines.map(k => formatTime(k.time));
  const prices = klines.map(k => k.close);
  const sentiments = alignSentiment(klines, sentimentSeries);

  const cfg = {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'BTC Price (USD)',
          data: prices,
          yAxisID: 'yPrice',
          borderColor: PRICE_COLOR,
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
        },
        {
          label: 'Sentiment Score',
          data: sentiments,
          yAxisID: 'ySentiment',
          borderColor: SENTIMENT_COLOR,
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.3,
          spanGaps: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
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
              if (ctx.datasetIndex === 0)
                return `  Price: $${ctx.parsed.y.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
              if (ctx.parsed.y == null) return null;
              return `  Sentiment: ${ctx.parsed.y.toFixed(3)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#8b949e', font: { family: "'SFMono-Regular', monospace", size: 10 }, maxTicksLimit: 8 },
          grid: { color: GRID_COLOR },
          border: { color: GRID_COLOR },
        },
        yPrice: {
          type: 'linear',
          position: 'left',
          ticks: {
            color: PRICE_COLOR,
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            callback: v => `$${(v / 1000).toFixed(0)}k`,
          },
          grid: { color: GRID_COLOR },
          border: { color: GRID_COLOR },
        },
        ySentiment: {
          type: 'linear',
          position: 'right',
          min: -1, max: 1,
          ticks: {
            color: SENTIMENT_COLOR,
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            callback: v => v.toFixed(1),
            maxTicksLimit: 5,
          },
          grid: { drawOnChartArea: false },
          border: { color: GRID_COLOR },
        },
      },
    },
  };

  if (dualChart) dualChart.destroy();
  dualChart = new Chart(canvas, cfg);
}

export function updateDualChart(klines) {
  if (!dualChart) return;
  dualChart.data.labels = klines.map(k => formatTime(k.time));
  dualChart.data.datasets[0].data = klines.map(k => k.close);
  dualChart.update('none');
}
