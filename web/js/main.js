import '../css/design-tokens.css';
import '../css/layout.css';
import '../css/components.css';
import '../css/charts.css';

/**
 * 앱 진입점 — 초기화 및 60s 갱신 루프
 */

import { loadAnalysisData }                from './data.js';
import { fetchTicker24h, fetchKlines,
         fetchCoinGeckoMarket,
         fetchFearGreed,
         fetchKlinesFromBackend }           from './api.js';
import { initDualChart, updateDualChart,
         resetZoom, zoomIn, zoomOut,
         updateChartPins }                  from './charts.js';
import { initScatterChart, initLagChart,
         updateScatterLag }                 from './correlation.js';
import { updateGauge, renderNews }          from './sentiment.js';
import { initPoll }                         from './poll.js';

/* ── 캐시 ──────────────────────────────────────────────────────────── */
const cache = { ticker: null, klines: null, market: null, news: null };

/* ── 유틸 ──────────────────────────────────────────────────────────── */
function fmt(n, decimals = 2) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: decimals });
}
function fmtPct(n) {
  if (n == null) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${Number(n).toFixed(2)}%`;
}
function fmtUsd(n) {
  if (n == null) return '—';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(2)}M`;
  return `$${fmt(n, 0)}`;
}
function setText(id, val)  { const el = document.getElementById(id); if (el) el.textContent = val; }
function setClass(id, cls) { const el = document.getElementById(id); if (el) el.className = cls; }

/* ── UTC 시계 ───────────────────────────────────────────────────────── */
function startClock() {
  const tick = () => {
    const now = new Date();
    const utc = now.toUTCString().split(' ').slice(4, 5)[0];
    setText('utc-clock', `${utc} UTC`);
  };
  tick();
  setInterval(tick, 1000);
}

/* ── 마지막 업데이트 표시 ──────────────────────────────────────────── */
function stampUpdated() {
  const now = new Date();
  setText('last-updated', now.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
}

/* ── Zone A + C: 가격·퍼포먼스 업데이트 ─────────────────────────── */
function renderPrice(ticker, market) {
  if (!ticker && !cache.ticker) return;
  const t = ticker || cache.ticker;

  setText('price-value', `$${fmt(t.price, 0)}`);
  const pctEl = document.getElementById('price-change24h');
  if (pctEl) {
    pctEl.textContent = fmtPct(t.change24h);
    pctEl.className = `price-change ${t.change24h >= 0 ? 'up' : 'down'}`;
  }

  // Zone C
  const m  = market || {};
  const c1 = m.change1h   ?? t.change1h;
  const c7 = m.change7d   ?? null;
  const ath = m.ath        ?? null;

  setText('perf-1h',  fmtPct(c1));
  setText('perf-24h', fmtPct(t.change24h));
  setText('perf-7d',  fmtPct(c7));
  setText('perf-ath', ath ? `$${fmt(ath, 0)}` : '—');

  setClass('perf-1h',  `perf-item__value ${c1 != null && c1 >= 0 ? 'up' : 'down'}`);
  setClass('perf-24h', `perf-item__value ${t.change24h >= 0 ? 'up' : 'down'}`);
  setClass('perf-7d',  `perf-item__value ${c7 != null && c7 >= 0 ? 'up' : 'down'}`);

  // 24h range bar
  const lo = t.low24h, hi = t.high24h, cur = t.price;
  if (lo && hi && hi > lo) {
    const pct = ((cur - lo) / (hi - lo)) * 100;
    const needle = document.getElementById('range-needle');
    if (needle) needle.style.left = `${Math.max(2, Math.min(98, pct))}%`;
    setText('range-low',  `$${fmt(lo, 0)}`);
    setText('range-high', `$${fmt(hi, 0)}`);
  }
}

/* ── Zone D: 마켓 통계 ──────────────────────────────────────────────── */
function renderMarketStats(market, ticker, fearGreed, snapshotStats) {
  const s = snapshotStats || {};
  const m = market || {};
  const t = ticker  || {};

  setText('stat-mcap',   fmtUsd(m.marketCap   || s.market_cap_usd));
  setText('stat-volume', fmtUsd(t.volume24h));
  setText('stat-supply', m.circulatingSupply
    ? `${fmt(m.circulatingSupply / 1e6, 2)}M BTC`
    : s.circulating_supply ? `${fmt(s.circulating_supply / 1e6, 2)}M BTC` : '—');
  setText('stat-ath',    m.ath ? `$${fmt(m.ath, 0)}` : s.ath_usd ? `$${fmt(s.ath_usd, 0)}` : '—');
  setText('stat-fg',     fearGreed ? `${fearGreed.value} ${fearGreed.label}` : '—');
  setText('stat-dom',    m.dominance ? `${m.dominance.toFixed(1)}%` : '—');
}

/* ── 상태 배너 ──────────────────────────────────────────────────────── */
function showBanner(msg, isError = false) {
  const el = document.getElementById('status-banner');
  if (!el) return;
  el.textContent = msg;
  el.className = `status-banner${isError ? ' error' : ''}`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add('hidden'), 4000);
}

/* ── 범위 버튼 & 줌 제어 ────────────────────────────────────────────── */
const RANGE_CONFIG = {
  '1D':  { interval: '1h', days: 1   },
  '7D':  { interval: '1h', days: 7   },
  '1M':  { interval: '1h', days: 30  },
  '3M':  { interval: '1h', days: 90  },
  '6M':  { interval: '1d', days: 180 },
  '1Y':  { interval: '1d', days: 365 },
  'ALL': { interval: '1d', days: null },
};
let activeRange = '7D';
let chartOpts   = { priceMode: 'series', sentimentMode: 'scatter' };

async function loadRange(rangeKey) {
  const { interval, days } = RANGE_CONFIG[rangeKey];
  const toTs   = Date.now();
  const fromTs = days ? toTs - days * 24 * 60 * 60 * 1000 : null;
  const limit  = interval === '1h' ? 2200 : 2500;
  let klines = await fetchKlinesFromBackend(interval, fromTs, toTs, limit);

  if (!klines || klines.length === 0) {
    const fallbackLimit = interval === '1h'
      ? Math.min(days ? days * 24 : 500, 1000)
      : Math.min(days ?? 500, 500);
    klines = await fetchKlines(interval, fallbackLimit);
  }

  if (!klines || klines.length === 0) { showBanner('히스토리 데이터 로드 실패', true); return; }
  cache.klines = klines;
  const showDate = days === null || days > 1;
  updateDualChart(klines, showDate, cache.sentimentSeries ?? null);
  if (cache.news) updateChartPins(klines, cache.news);
  resetZoom();
}

function initRangeButtons() {
  document.querySelectorAll('[data-range]').forEach(btn => {
    btn.addEventListener('click', async () => {
      document.querySelectorAll('[data-range]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeRange = btn.dataset.range;
      await loadRange(activeRange);
    });
  });
}

function initZoomControls() {
  document.getElementById('btn-zoom-in')?.addEventListener('click', zoomIn);
  document.getElementById('btn-zoom-out')?.addEventListener('click', zoomOut);
  document.getElementById('btn-zoom-reset')?.addEventListener('click', resetZoom);
}

function initChartModeToggles() {
  document.querySelectorAll('[data-price-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-price-mode]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      chartOpts.priceMode = btn.dataset.priceMode;
      if (cache.klines) {
        initDualChart('dual-chart', cache.klines, cache.sentimentSeries ?? [], cache.news ?? [], chartOpts);
      }
    });
  });

  document.querySelectorAll('[data-sentiment-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-sentiment-mode]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      chartOpts.sentimentMode = btn.dataset.sentimentMode;
      if (cache.klines) {
        initDualChart('dual-chart', cache.klines, cache.sentimentSeries ?? [], cache.news ?? [], chartOpts);
      }
    });
  });
}

/* ── Zone E 탭 ──────────────────────────────────────────────────────── */
function initScatterTabs() {
  document.querySelectorAll('[data-lag]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-lag]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      updateScatterLag('scatter-canvas', btn.dataset.lag);
    });
  });
}

/* ── 주 갱신 루프 ────────────────────────────────────────────────────── */
async function refresh() {
  const [ticker, klines, market, fearGreed] = await Promise.all([
    fetchTicker24h(),
    fetchKlines('1h', 100),
    fetchCoinGeckoMarket(),
    fetchFearGreed(),
  ]);

  if (ticker) cache.ticker = ticker;
  if (klines) cache.klines = klines;
  if (market) cache.market = market;

  renderPrice(ticker, market);
  renderMarketStats(market, ticker, fearGreed, null);

  if (klines && cache.sentimentSeries && activeRange === '7D') updateDualChart(klines, false, cache.sentimentSeries);

  stampUpdated();
}

/* ── 초기화 ─────────────────────────────────────────────────────────── */
async function init() {
  startClock();
  initPoll();
  initRangeButtons();
  initZoomControls();
  initChartModeToggles();
  initScatterTabs();

  // 분석 데이터 (정적 스냅샷 or FastAPI)
  let analysis = null;
  try {
    analysis = await loadAnalysisData();
  } catch (e) {
    showBanner('분석 데이터 로드 실패', true);
  }

  if (analysis) {
    cache.sentimentSeries = analysis.sentiment_series;
    cache.news = analysis.news ?? [];

    updateGauge(analysis.sentiment_gauge?.score, analysis.sentiment_gauge?.count);
    renderNews(analysis.news);
    renderMarketStats(null, null, null, analysis.market_stats);

    if (analysis.generated_at) {
      const genEl = document.getElementById('data-generated-at');
      if (genEl) {
        const genTime = new Date(analysis.generated_at).toLocaleString('ko-KR', {
          year: 'numeric', month: '2-digit', day: '2-digit',
          hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Seoul',
        });
        genEl.textContent = `데이터 기준: ${genTime} (KST)`;
      }
    }
  }

  // 실시간 데이터 초기 로드
  const [ticker, rawKlines, fearGreed] = await Promise.all([
    fetchTicker24h(),
    fetchKlinesFromBackend('1h', Date.now() - 7 * 24 * 3600 * 1000, Date.now(), 2000),
    fetchFearGreed(),
  ]);
  const klines = (rawKlines && rawKlines.length > 0) ? rawKlines : await fetchKlines('1h', 168);

  if (ticker) cache.ticker = ticker;
  if (klines) cache.klines = klines;

  renderPrice(ticker, null);

  if (klines) {
    initDualChart('dual-chart', klines, analysis?.sentiment_series ?? [], analysis?.news ?? [], chartOpts);
  }

  if (fearGreed) renderMarketStats(null, ticker, fearGreed, analysis?.market_stats);

  if (analysis?.correlation) {
    initScatterChart('scatter-canvas', analysis.correlation.scatter);
    initLagChart('lag-canvas', analysis.correlation.lags);
  }

  stampUpdated();

  // 60s 인터벌 갱신
  setInterval(refresh, 60_000);
}

document.addEventListener('DOMContentLoaded', init);
