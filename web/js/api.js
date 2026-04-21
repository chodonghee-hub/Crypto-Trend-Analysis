/**
 * 외부 API 래퍼 — Binance, CoinGecko, Alternative.me
 * 각 함수는 { data, error } 형태로 반환 (throw 없음)
 */

const BINANCE = 'https://api.binance.com/api/v3';
const COINGECKO = 'https://api.coingecko.com/api/v3';
const FEARGREED = 'https://api.alternative.me/fng/?limit=1';

async function safeFetch(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) return { data: null, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { data, error: null };
  } catch (e) {
    return { data: null, error: e.message };
  }
}

/** BTC 24hr 티커 */
export async function fetchTicker24h() {
  const { data, error } = await safeFetch(`${BINANCE}/ticker/24hr?symbol=BTCUSDT`);
  if (error || !data) return null;
  return {
    price:       parseFloat(data.lastPrice),
    change24h:   parseFloat(data.priceChangePercent),
    change1h:    null,           // klines에서 별도 계산
    high24h:     parseFloat(data.highPrice),
    low24h:      parseFloat(data.lowPrice),
    volume24h:   parseFloat(data.quoteVolume),
  };
}

/** BTC klines (캔들 데이터) */
export async function fetchKlines(interval = '1h', limit = 100) {
  const url = `${BINANCE}/klines?symbol=BTCUSDT&interval=${interval}&limit=${limit}`;
  const { data, error } = await safeFetch(url);
  if (error || !data) return null;
  return data.map(k => ({
    time:  k[0],
    open:  parseFloat(k[1]),
    high:  parseFloat(k[2]),
    low:   parseFloat(k[3]),
    close: parseFloat(k[4]),
  }));
}

/** CoinGecko 마켓 데이터 */
export async function fetchCoinGeckoMarket() {
  const url = `${COINGECKO}/coins/bitcoin?localization=false&tickers=false&community_data=false&developer_data=false`;
  const { data, error } = await safeFetch(url);
  if (error || !data) return null;
  const m = data.market_data;
  return {
    marketCap:         m.market_cap?.usd,
    ath:               m.ath?.usd,
    athDate:           m.ath_date?.usd,
    circulatingSupply: m.circulating_supply,
    dominance:         null,   // 별도 endpoint 필요
    change1h:          m.price_change_percentage_1h_in_currency?.usd,
    change7d:          m.price_change_percentage_7d,
  };
}

/** CoinGecko 뉴스 */
export async function fetchCoinGeckoNews() {
  const url = `${COINGECKO}/news`;
  const { data, error } = await safeFetch(url);
  if (error || !data?.data) return null;
  return data.data.slice(0, 10).map(n => ({
    title:       n.title,
    url:         n.url,
    source:      n.news_site,
    published_at: n.updated_at
      ? new Date(n.updated_at * 1000).toISOString()
      : null,
    sentiment_label: 'neutral',
    score: 0,
  }));
}

/** Fear & Greed Index */
export async function fetchFearGreed() {
  const { data, error } = await safeFetch(FEARGREED);
  if (error || !data?.data?.[0]) return null;
  return {
    value:       parseInt(data.data[0].value),
    label:       data.data[0].value_classification,
  };
}
