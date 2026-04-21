"""
Data collection module:
- Binance REST API  : 1-min / 1-hour BTC/USDT candles, 24-hour ticker
- CoinGecko News API: BTC news headlines (free, no API key required)
- RSS feeds         : CoinDesk, CoinTelegraph
- CoinGecko API     : Market cap, ATH, circulating supply
"""

from __future__ import annotations

import os
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROC = BASE_DIR / "data" / "processed"
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROC.mkdir(parents=True, exist_ok=True)

BINANCE_BASE = "https://api.binance.com/api/v3"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

RSS_SOURCES = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
}


# ──────────────────────────────────────────────
# Binance
# ──────────────────────────────────────────────

def fetch_binance_ticker_24h(symbol: str = "BTCUSDT") -> dict:
    """24-hour rolling window price statistics."""
    resp = requests.get(f"{BINANCE_BASE}/ticker/24hr", params={"symbol": symbol}, timeout=10)
    resp.raise_for_status()
    raw = resp.json()
    return {
        "symbol": raw["symbol"],
        "price": float(raw["lastPrice"]),
        "change_pct_24h": float(raw["priceChangePercent"]),
        "high_24h": float(raw["highPrice"]),
        "low_24h": float(raw["lowPrice"]),
        "volume_24h": float(raw["volume"]),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_binance_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    """Fetch up to `limit` klines for a single request window."""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start:
        params["startTime"] = _epoch_ms(start)
    if end:
        params["endTime"] = _epoch_ms(end)

    resp = requests.get(f"{BINANCE_BASE}/klines", params=params, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]


def collect_binance_klines_range(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    start: datetime = datetime(2017, 1, 1, tzinfo=timezone.utc),
    end: datetime | None = None,
    sleep_sec: float = 0.05,
) -> None:
    """
    Download full historical klines for a date range in 1000-row chunks,
    save as monthly Parquet files under data/raw/.
    Supports resume: reads the last saved timestamp to set startTime.
    """
    if end is None:
        end = datetime.now(timezone.utc)

    suffix = interval  # e.g. "1m", "1h"
    log.info("Starting klines collection: %s %s  %s → %s", symbol, interval, start.date(), end.date())

    current = _resume_start(symbol, suffix, start)
    total_rows = 0

    while current < end:
        df = fetch_binance_klines(symbol, interval, start=current, end=end, limit=1000)
        if df.empty:
            break

        _save_klines_monthly(df, symbol, suffix)
        total_rows += len(df)
        last_time = df["open_time"].iloc[-1].to_pydatetime()

        if last_time <= current:
            break
        current = last_time
        time.sleep(sleep_sec)

        if total_rows % 100_000 == 0:
            log.info("  collected %d rows, current: %s", total_rows, current)

    log.info("Done. Total rows: %d", total_rows)


def _resume_start(symbol: str, suffix: str, default: datetime) -> datetime:
    pattern = f"btc_{suffix}_*.parquet"
    files = sorted(DATA_RAW.glob(pattern))
    if not files:
        return default
    last_file = files[-1]
    df = pd.read_parquet(last_file, columns=["open_time"])
    if df.empty:
        return default
    last_ts = pd.to_datetime(df["open_time"].max(), utc=True).to_pydatetime()
    log.info("Resuming from %s (file: %s)", last_ts, last_file.name)
    return last_ts


def _save_klines_monthly(df: pd.DataFrame, symbol: str, suffix: str) -> None:
    for (year, month), group in df.groupby([df["open_time"].dt.year, df["open_time"].dt.month]):
        fname = DATA_RAW / f"btc_{suffix}_{year:04d}{month:02d}.parquet"
        if fname.exists():
            existing = pd.read_parquet(fname)
            group = pd.concat([existing, group]).drop_duplicates("open_time").sort_values("open_time")
        group.to_parquet(fname, index=False)


# ──────────────────────────────────────────────
# CoinGecko News
# ──────────────────────────────────────────────

def fetch_coingecko_news(pages: int = 5) -> pd.DataFrame:
    """
    Fetch recent crypto news from CoinGecko News API.
    Free Demo tier: 30 req/min, 10,000 req/month. No API key required.
    """
    records = []
    url = f"{COINGECKO_BASE}/news"
    seen_urls: set[str] = set()

    for page in range(1, pages + 1):
        try:
            resp = requests.get(url, params={"page": page}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("CoinGecko News page %d failed: %s", page, exc)
            break

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            item_url = item.get("url", "")
            if item_url in seen_urls:
                continue
            seen_urls.add(item_url)
            ts = item.get("published_at")
            published = (
                pd.to_datetime(ts, unit="s", utc=True) if isinstance(ts, (int, float))
                else pd.to_datetime(ts, utc=True) if ts
                else pd.NaT
            )
            records.append({
                "title": item.get("title", ""),
                "url": item_url,
                "source": item.get("news_site", item.get("author", "")),
                "published_at": published,
            })

        time.sleep(2)

    df = pd.DataFrame(records)
    if not df.empty:
        _save_news_monthly(df)
    return df


def _save_news_monthly(df: pd.DataFrame) -> None:
    df = df.dropna(subset=["published_at"])
    for (year, month), group in df.groupby([df["published_at"].dt.year, df["published_at"].dt.month]):
        fname = DATA_RAW / f"news_{year:04d}{month:02d}.csv"
        if fname.exists():
            existing = pd.read_csv(fname, parse_dates=["published_at"])
            group = pd.concat([existing, group]).drop_duplicates("url").sort_values("published_at")
        group.to_csv(fname, index=False)
    log.info("Saved %d news records", len(df))


# ──────────────────────────────────────────────
# RSS Feeds
# ──────────────────────────────────────────────

def fetch_rss_news(source_name: str, url: str) -> pd.DataFrame:
    """Parse an RSS feed and return headlines with UTC timestamps."""
    feed = feedparser.parse(url)
    records = []
    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            dt = datetime(*published[:6], tzinfo=timezone.utc)
        else:
            dt = pd.NaT

        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        if not title:
            continue
        records.append({
            "title": title,
            "url": link,
            "source": source_name,
            "published_at": dt,
        })

    df = pd.DataFrame(records)
    if not df.empty:
        _save_news_monthly(df)
    log.info("RSS [%s] fetched %d items", source_name, len(df))
    return df


def fetch_all_rss() -> pd.DataFrame:
    frames = []
    for name, url in RSS_SOURCES.items():
        try:
            df = fetch_rss_news(name, url)
            frames.append(df)
        except Exception as exc:
            log.warning("RSS %s failed: %s", name, exc)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ──────────────────────────────────────────────
# CoinGecko Market Stats
# ──────────────────────────────────────────────

def fetch_coingecko_stats(coin_id: str = "bitcoin") -> dict:
    """Fetch market cap, ATH, circulating supply from CoinGecko."""
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false",
    }
    resp = requests.get(f"{COINGECKO_BASE}/coins/{coin_id}", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    md = data.get("market_data", {})

    stats = {
        "market_cap_usd": md.get("market_cap", {}).get("usd"),
        "ath_usd": md.get("ath", {}).get("usd"),
        "circulating_supply": md.get("circulating_supply"),
        "total_supply": md.get("total_supply"),
        "price_usd": md.get("current_price", {}).get("usd"),
        "price_change_24h_pct": md.get("price_change_percentage_24h"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = DATA_PROC / "market_stats.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    log.info("CoinGecko stats saved → %s", out_path)
    return stats


# ──────────────────────────────────────────────
# Utility: load saved news
# ──────────────────────────────────────────────

def load_all_news() -> pd.DataFrame:
    """Concatenate all monthly news CSVs into a single DataFrame."""
    files = sorted(DATA_RAW.glob("news_*.csv"))
    if not files:
        log.warning("No news CSV files found in %s", DATA_RAW)
        return pd.DataFrame()
    frames = [pd.read_csv(f, parse_dates=["published_at"]) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates("url").sort_values("published_at").reset_index(drop=True)
    log.info("Loaded %d news records from %d files", len(df), len(files))
    return df


def load_klines(interval: str = "1h") -> pd.DataFrame:
    """Concatenate all monthly kline Parquet files for the given interval."""
    files = sorted(DATA_RAW.glob(f"btc_{interval}_*.parquet"))
    if not files:
        log.warning("No kline parquet files for interval=%s", interval)
        return pd.DataFrame()
    frames = [pd.read_parquet(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    log.info("Loaded %d kline rows (%s) from %d files", len(df), interval, len(files))
    return df
