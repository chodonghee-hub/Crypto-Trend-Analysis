/**
 * 앱 진입점 — 초기화 및 60s 갱신 루프
 */

import { loadAnalysisData }                from './data.js';
import { fetchTicker24h, fetchKlines,
         fetchCoinGeckoMarket, fetchCoinGeckoNews,
         fetchFearGreed }                   from './api.js';
import { initDualChart, updateDualChart }   from './charts.js';
import { initScatterChart, initLagChart,
         updateScatterLag }                 from './correlation.js';
import { updateGauge, renderNews }          from './sentiment.js';
import { initPoll }                         from './poll.js';

/* ── 캐시 ──────────────────────────────────────────────────────────── */
const cache = { ticker: null, klines: null, market: null };

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

/* ── 타임프레임 버튼 ────────────────────────────────────────────────── */
function initTimeframeButtons() {
  document.querySelectorAll('[data-tf]').forEach(btn => {
    btn.addEventListener('click', async () => {
      document.querySelectorAll('[data-tf]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const intervalMap = { '1H': '1h', '4H': '4h', '1D': '1d', '7D': '1d', '1M': '1d' };
      const limitMap    = { '1H': 100, '4H': 100, '1D': 90, '7D': 42, '1M': 30 };
      const tf = btn.dataset.tf;
      const klines = await fetchKlines(intervalMap[tf] || '1h', limitMap[tf] || 100);
      if (klines) { cache.klines = klines; updateDualChart(klines); }
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
  const [ticker, klines, market, fearGreed, news] = await Promise.all([
    fetchTicker24h(),
    fetchKlines('1h', 100),
    fetchCoinGeckoMarket(),
    fetchFearGreed(),
    fetchCoinGeckoNews(),
  ]);

  if (ticker) cache.ticker = ticker;
  if (klines) cache.klines = klines;
  if (market) cache.market = market;

  renderPrice(ticker, market);
  renderMarketStats(market, ticker, fearGreed, null);

  if (klines && cache.sentimentSeries) updateDualChart(klines);

  // 뉴스: 실시간 우선, 없으면 스냅샷 유지
  if (news?.length) renderNews(news);

  stampUpdated();
}

/* ── 초기화 ─────────────────────────────────────────────────────────── */
async function init() {
  startClock();
  initPoll();
  initTimeframeButtons();
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

    updateGauge(analysis.sentiment_gauge?.score, analysis.sentiment_gauge?.count);
    renderNews(analysis.news);
    renderMarketStats(null, null, null, analysis.market_stats);
  }

  // 실시간 데이터 초기 로드
  const [ticker, klines, fearGreed] = await Promise.all([
    fetchTicker24h(),
    fetchKlines('1h', 100),
    fetchFearGreed(),
  ]);

  if (ticker) cache.ticker = ticker;
  if (klines) cache.klines = klines;

  renderPrice(ticker, null);

  if (klines) {
    initDualChart('dual-chart', klines, analysis?.sentiment_series ?? []);
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
