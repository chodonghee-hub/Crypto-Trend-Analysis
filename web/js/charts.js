import Chart from 'chart.js/auto';
import zoomPlugin from 'chartjs-plugin-zoom';
Chart.register(zoomPlugin);

/**
 * Zone B — BTC 가격 + 감성 점수 듀얼 축 차트
 * - priceMode:     'series' (라인) | 'candle' (캔들스틱)
 * - sentimentMode: 'scatter' (뉴스 개별 점) | 'series' (평균 라인)
 */

const PRICE_COLOR    = '#0ea5e9';
const POSITIVE_COLOR = '#4ade80';
const NEUTRAL_COLOR  = '#94a3b8';
const NEGATIVE_COLOR = '#f87171';
const CANDLE_UP      = '#26a69a';
const CANDLE_DOWN    = '#ef5350';
const GRID_COLOR     = 'rgba(61, 58, 57, 0.5)';

const SCATTER_BASE = {
  borderColor: 'transparent',
  borderWidth: 0,
  showLine: false,
  pointRadius: 5,
  pointHoverRadius: 8,
  pointStyle: 'circle',
  spanGaps: false,
  yAxisID: 'ySentiment',
};

let dualChart = null;

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}
function formatDate(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:00`;
}

/** 뉴스 → kline 인덱스 매핑. positive/neutral/negative 3쌍 반환 */
function buildNewsScatter(klines, news) {
  const n = klines.length;
  const scatterPos = new Array(n).fill(null);
  const scatterNeu = new Array(n).fill(null);
  const scatterNeg = new Array(n).fill(null);
  const lookupPos = {}, lookupNeu = {}, lookupNeg = {};

  if (!news?.length || !klines?.length)
    return { scatterPos, scatterNeu, scatterNeg, lookupPos, lookupNeu, lookupNeg };

  const avgInterval = klines.length > 1
    ? (klines[klines.length - 1].time - klines[0].time) / (klines.length - 1)
    : Infinity;
  const maxDiff = avgInterval * 2;

  news.forEach(article => {
    const nTime = new Date(article.published_at).getTime();
    let bestIdx = 0, bestDiff = Infinity;
    klines.forEach((k, i) => {
      const diff = Math.abs(k.time - nTime);
      if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
    });
    if (bestDiff > maxDiff) return;

    const score = article.score ?? 0;
    const label = article.sentiment_label ??
      (score > 0.05 ? 'positive' : score < -0.05 ? 'negative' : 'neutral');
    const entry = { title: article.title, url: article.url, score };

    const [scatter, lookup] =
      label === 'positive' ? [scatterPos, lookupPos] :
      label === 'negative' ? [scatterNeg, lookupNeg] :
                             [scatterNeu, lookupNeu];

    const existing = lookup[bestIdx];
    if (!existing || Math.abs(score) > Math.abs(existing.score ?? 0)) {
      scatter[bestIdx] = score;
      lookup[bestIdx] = entry;
    }
  });

  return { scatterPos, scatterNeu, scatterNeg, lookupPos, lookupNeu, lookupNeg };
}

/** sentimentSeries → kline 인덱스 매핑. 단일 라인 데이터 반환 */
function buildSentimentLine(klines, sentimentSeries) {
  const data = new Array(klines.length).fill(null);
  if (!sentimentSeries?.length || !klines?.length) return data;

  const avgInterval = klines.length > 1
    ? (klines[klines.length - 1].time - klines[0].time) / (klines.length - 1)
    : Infinity;
  const maxDiff = avgInterval * 3;

  sentimentSeries.forEach(entry => {
    const ts = new Date(entry.timestamp).getTime();
    let bestIdx = 0, bestDiff = Infinity;
    klines.forEach((k, i) => {
      const diff = Math.abs(k.time - ts);
      if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
    });
    if (bestDiff <= maxDiff && data[bestIdx] === null) {
      data[bestIdx] = entry.score ?? 0;
    }
  });

  return data;
}

function getLookupByDatasetIndex(chart, datasetIndex) {
  const l = chart._lookup;
  if (!l) return null;
  return [null, l.pos, l.neu, l.neg][datasetIndex] ?? null;
}

/* ── 캔들스틱 렌더링 플러그인 ──────────────────────────────────────── */
const candlestickPlugin = {
  id: 'candlestick',
  afterDatasetsDraw(chart) {
    if (chart._priceMode !== 'candle' || !chart._ohlcData?.length) return;

    const ctx    = chart.ctx;
    const meta   = chart.getDatasetMeta(0);
    const yScale = chart.scales.yPrice;
    const n      = chart._ohlcData.length;
    const stepW  = chart.chartArea.width / n;
    const candleW = Math.max(2, Math.min(stepW * 0.65, 14));

    chart._ohlcData.forEach((candle, i) => {
      const point = meta.data[i];
      if (!point || !candle) return;

      const xPixel = point.x;
      const { o, h, l, c } = candle;
      const yO = yScale.getPixelForValue(o);
      const yH = yScale.getPixelForValue(h);
      const yL = yScale.getPixelForValue(l);
      const yC = yScale.getPixelForValue(c);

      const isUp       = c >= o;
      const color      = isUp ? CANDLE_UP : CANDLE_DOWN;
      const bodyTop    = Math.min(yO, yC);
      const bodyHeight = Math.max(1, Math.abs(yC - yO));

      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth   = 1;

      // 위 wick
      ctx.beginPath();
      ctx.moveTo(xPixel, yH);
      ctx.lineTo(xPixel, bodyTop);
      ctx.stroke();

      // 아래 wick
      ctx.beginPath();
      ctx.moveTo(xPixel, bodyTop + bodyHeight);
      ctx.lineTo(xPixel, yL);
      ctx.stroke();

      // 캔들 몸통 (상승/하락 모두 filled)
      ctx.fillStyle = color;
      ctx.fillRect(xPixel - candleW / 2, bodyTop, candleW, bodyHeight);

      ctx.restore();
    });
  },
};

/* ── 마그네틱 크로스헤어 플러그인 ──────────────────────────────────── */
const magneticCrosshairPlugin = {
  id: 'magneticCrosshair',
  afterDraw(chart) {
    const activeElements = chart.tooltip?._active;
    if (!activeElements?.length) return;

    const ctx       = chart.ctx;
    const chartArea = chart.chartArea;
    const dataIndex = activeElements[0].index;
    const xPixel    = chart.getDatasetMeta(0).data[dataIndex]?.x;
    if (xPixel == null) return;

    // 수직 점선
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(xPixel, chartArea.top);
    ctx.lineTo(xPixel, chartArea.bottom);
    ctx.lineWidth   = 1;
    ctx.strokeStyle = 'rgba(242, 242, 242, 0.4)';
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.restore();

    // 시리즈 모드에서만 원형 마커
    if (chart._priceMode !== 'candle') {
      chart.data.datasets.forEach((dataset, di) => {
        const value = dataset.data[dataIndex];
        if (value == null) return;
        const point = chart.getDatasetMeta(di).data[dataIndex];
        if (!point) return;

        const fillColor =
          dataset.borderColor && dataset.borderColor !== 'transparent'
            ? dataset.borderColor
            : (dataset.backgroundColor || 'rgba(255,255,255,0.8)');

        ctx.save();
        ctx.beginPath();
        ctx.arc(xPixel, point.y, 5, 0, Math.PI * 2);
        ctx.fillStyle   = fillColor;
        ctx.strokeStyle = '#101010';
        ctx.lineWidth   = 1.5;
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      });
    }
  },
};

/* ── 메인 차트 초기화 ───────────────────────────────────────────────── */
export function initDualChart(canvasId, klines, sentimentSeries, news = [], opts = {}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const {
    priceMode     = 'series',
    sentimentMode = 'scatter',
    showDate      = false,
  } = opts;

  const labelFn  = showDate ? k => formatDate(k.time) : k => formatTime(k.time);
  const labels   = klines.map(labelFn);
  const prices   = klines.map(k => k.close);
  const ohlcData = klines.map(k => ({ o: k.open, h: k.high, l: k.low, c: k.close }));

  // 가격 데이터셋: candle 모드일 때 라인을 투명하게 (x축 기준점 역할만)
  const priceDataset = {
    label: 'BTC 가격 (USD)',
    data: prices,
    yAxisID: 'yPrice',
    borderColor:      priceMode === 'candle' ? 'transparent' : PRICE_COLOR,
    backgroundColor:  'transparent',
    borderWidth:      priceMode === 'candle' ? 0 : 1.5,
    pointRadius:      0,
    pointHoverRadius: priceMode === 'candle' ? 0 : 5,
    tension: 0.3,
  };

  // 감성 데이터셋 구성
  let sentimentDatasets = [];
  let lookup = null;

  if (sentimentMode === 'scatter') {
    const { scatterPos, scatterNeu, scatterNeg, lookupPos, lookupNeu, lookupNeg } =
      buildNewsScatter(klines, news);
    lookup = { pos: lookupPos, neu: lookupNeu, neg: lookupNeg };
    sentimentDatasets = [
      { label: 'Positive', data: scatterPos, backgroundColor: POSITIVE_COLOR, ...SCATTER_BASE },
      { label: 'Neutral',  data: scatterNeu, backgroundColor: NEUTRAL_COLOR,  ...SCATTER_BASE },
      { label: 'Negative', data: scatterNeg, backgroundColor: NEGATIVE_COLOR, ...SCATTER_BASE },
    ];
  } else {
    // series 모드: 시간 윈도우 평균을 연결 라인으로 표시
    const lineData    = buildSentimentLine(klines, sentimentSeries);
    const pointColors = lineData.map(v =>
      v === null ? 'transparent' :
      v > 0.05   ? POSITIVE_COLOR :
      v < -0.05  ? NEGATIVE_COLOR :
                   NEUTRAL_COLOR
    );
    sentimentDatasets = [{
      label: '감성 (평균)',
      data: lineData,
      yAxisID: 'ySentiment',
      borderColor: '#818cf8',
      backgroundColor: 'transparent',
      borderWidth: 1.5,
      showLine: true,
      spanGaps: true,
      pointRadius: 4,
      pointHoverRadius: 7,
      pointBackgroundColor: pointColors,
      pointBorderColor: 'transparent',
      tension: 0.3,
    }];
  }

  const cfg = {
    type: 'line',
    data: {
      labels,
      datasets: [priceDataset, ...sentimentDatasets],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      onHover(e, elements) {
        const isOnScatter = elements.some(el => el.datasetIndex >= 1);
        e.native.target.style.cursor =
          isOnScatter && sentimentMode === 'scatter' ? 'pointer' : 'default';
      },
      plugins: {
        legend: {
          display: true,
          labels: {
            color: '#8b949e',
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            boxWidth: 10,
            padding: 12,
          },
          filter: item => item.datasetIndex !== 0,
        },
        tooltip: {
          backgroundColor: '#101010',
          borderColor: '#3d3a39',
          borderWidth: 1,
          titleColor: '#8b949e',
          bodyColor: '#f2f2f2',
          padding: 10,
          callbacks: {
            label(ctx) {
              if (ctx.datasetIndex === 0) {
                if (dualChart?._priceMode === 'candle') {
                  const c = dualChart._ohlcData?.[ctx.dataIndex];
                  if (c) {
                    const f = v => `$${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
                    return [`  O: ${f(c.o)}  H: ${f(c.h)}`, `  L: ${f(c.l)}  C: ${f(c.c)}`];
                  }
                }
                return `  가격: $${ctx.parsed.y.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
              }
              if (ctx.parsed.y == null) return null;
              if (dualChart?._sentimentMode === 'scatter') {
                const lk = getLookupByDatasetIndex(dualChart, ctx.datasetIndex);
                const entry = lk?.[ctx.dataIndex];
                if (entry?.title) return `  뉴스: ${entry.title}`;
              }
              return `  감성: ${ctx.parsed.y.toFixed(3)}`;
            },
          },
        },
        zoom: {
          pan:  { enabled: true, mode: 'x' },
          zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' },
          limits: { x: { minRange: 12 } },
        },
      },
      scales: {
        x: {
          ticks: {
            color: '#8b949e',
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            maxTicksLimit: 8,
          },
          grid:   { color: GRID_COLOR },
          border: { color: GRID_COLOR },
        },
        yPrice: {
          type: 'linear',
          position: 'left',
          ticks: {
            color: priceMode === 'candle' ? '#6b9ab8' : PRICE_COLOR,
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            callback: v => `$${(v / 1000).toFixed(0)}k`,
          },
          grid:   { color: GRID_COLOR },
          border: { color: GRID_COLOR },
        },
        ySentiment: {
          type: 'linear',
          position: 'right',
          min: -1, max: 1,
          ticks: {
            color: NEUTRAL_COLOR,
            font: { family: "'SFMono-Regular', monospace", size: 10 },
            callback: v => v.toFixed(1),
            maxTicksLimit: 5,
          },
          grid:   { drawOnChartArea: false },
          border: { color: GRID_COLOR },
        },
      },
    },
    plugins: [candlestickPlugin, magneticCrosshairPlugin],
  };

  if (dualChart) dualChart.destroy();
  dualChart = new Chart(canvas, cfg);

  dualChart._ohlcData        = ohlcData;
  dualChart._sentimentSeries = sentimentSeries;
  dualChart._cachedNews      = news;
  dualChart._priceMode       = priceMode;
  dualChart._sentimentMode   = sentimentMode;
  dualChart._lookup          = lookup;

  if (!canvas._newsClickListenerAdded) {
    canvas.addEventListener('click', e => {
      if (!dualChart || dualChart._sentimentMode !== 'scatter') return;
      const points = dualChart.getElementsAtEventForMode(
        e, 'nearest', { intersect: true }, false
      );
      if (!points.length) return;
      const { datasetIndex, index } = points[0];
      if (datasetIndex === 0) return;
      const lk    = getLookupByDatasetIndex(dualChart, datasetIndex);
      const entry = lk?.[index];
      if (entry?.url) window.open(entry.url, '_blank');
    });
    canvas._newsClickListenerAdded = true;
  }
}

/* ── 데이터 업데이트 (모드 유지) ────────────────────────────────────── */
export function updateDualChart(klines, showDate = false, sentimentSeries = null) {
  if (!dualChart) return;
  initDualChart(
    dualChart.canvas.id,
    klines,
    sentimentSeries ?? dualChart._sentimentSeries ?? [],
    dualChart._cachedNews ?? [],
    {
      priceMode:     dualChart._priceMode     ?? 'series',
      sentimentMode: dualChart._sentimentMode ?? 'scatter',
      showDate,
    }
  );
}

export function resetZoom() { if (dualChart) dualChart.resetZoom(); }
export function zoomIn()    { if (dualChart) dualChart.zoom(1.5); }
export function zoomOut()   { if (dualChart) dualChart.zoom(1 / 1.5); }

export function updateChartPins(klines, news) {
  if (!dualChart) return;
  initDualChart(
    dualChart.canvas.id,
    klines,
    dualChart._sentimentSeries ?? [],
    news,
    {
      priceMode:     dualChart._priceMode     ?? 'series',
      sentimentMode: dualChart._sentimentMode ?? 'scatter',
    }
  );
}
