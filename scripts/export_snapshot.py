"""
CSV/JSON 분석 데이터를 web/data/snapshot.json으로 변환.
파이프라인 실행 후 이 스크립트를 실행하여 정적 배포용 스냅샷을 생성한다.

Usage: python scripts/export_snapshot.py
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from scipy.stats import pearsonr

ROOT = Path(__file__).parent.parent
OUT_PATH = ROOT / "web" / "data" / "snapshot.json"


def safe_float(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return round(float(val), 6)


def compute_lags(df: pd.DataFrame) -> list[dict]:
    lags = [
        ("5m",  "return_5m"),
        ("15m", "return_15m"),
        ("30m", "return_30m"),
        ("60m", "return_60m"),
    ]
    results = []
    for label, col in lags:
        valid = df[["window_score", col]].dropna()
        if len(valid) < 3:
            results.append({"lag": label, "r": None, "p": None, "n": len(valid)})
            continue
        r, p = pearsonr(valid["window_score"], valid[col])
        results.append({
            "lag": label,
            "r": round(float(r), 4),
            "p": round(float(p), 4),
            "n": int(len(valid)),
        })
    return results


def build_snapshot() -> dict:
    # ── merged_analysis.csv ──────────────────────────────────────────────────
    merged_path = ROOT / "data" / "processed" / "merged_analysis.csv"
    if not merged_path.exists():
        print(f"[WARN] {merged_path} not found — correlation data will be empty", file=sys.stderr)
        merged_df = pd.DataFrame()
    else:
        merged_df = pd.read_csv(merged_path)
        merged_df["window_start"] = pd.to_datetime(merged_df["window_start"], utc=True)

    # ── news_sentiment.csv ───────────────────────────────────────────────────
    news_path = ROOT / "data" / "processed" / "news_sentiment.csv"
    if not news_path.exists():
        print(f"[WARN] {news_path} not found — sentiment/news will be empty", file=sys.stderr)
        news_df = pd.DataFrame()
    else:
        news_df = pd.read_csv(news_path)
        news_df["published_at"] = pd.to_datetime(news_df["published_at"], utc=True)

    # ── market_stats.json ────────────────────────────────────────────────────
    stats_path = ROOT / "data" / "processed" / "market_stats.json"
    market_stats = {}
    if stats_path.exists():
        with open(stats_path, encoding="utf-8") as f:
            market_stats = json.load(f)

    # ── Sentiment gauge ──────────────────────────────────────────────────────
    if not news_df.empty and "score" in news_df.columns:
        valid_news = news_df[news_df.get("is_valid", pd.Series([True] * len(news_df))) == True]
        gauge_score = safe_float(valid_news["score"].mean()) if not valid_news.empty else 0.0
        gauge_count = int(len(valid_news))
    else:
        gauge_score, gauge_count = 0.0, 0

    # ── Sentiment time series (for Zone B overlay) ───────────────────────────
    sentiment_series = []
    if not merged_df.empty:
        for _, row in merged_df.iterrows():
            sentiment_series.append({
                "timestamp": row["window_start"].isoformat(),
                "score": safe_float(row["window_score"]),
            })

    # ── Scatter data (Zone E) ─────────────────────────────────────────────────
    scatter = []
    if not merged_df.empty:
        for _, row in merged_df.iterrows():
            scatter.append({
                "date": row["window_start"].isoformat(),
                "sentiment": safe_float(row["window_score"]),
                "return_15m": safe_float(row.get("return_15m")),
                "return_60m": safe_float(row.get("return_60m")),
            })

    # ── Lag correlations (Zone F) ─────────────────────────────────────────────
    lags = compute_lags(merged_df) if not merged_df.empty else []

    # ── News list (sidebar) ───────────────────────────────────────────────────
    news_items = []
    if not news_df.empty:
        cols = ["title", "url", "source", "published_at", "score", "sentiment_label"]
        available = [c for c in cols if c in news_df.columns]
        for _, row in news_df[available].sort_values("published_at", ascending=False).head(20).iterrows():
            item = {}
            for c in available:
                val = row[c]
                if hasattr(val, "isoformat"):
                    item[c] = val.isoformat()
                elif isinstance(val, float):
                    item[c] = safe_float(val)
                else:
                    item[c] = val
            news_items.append(item)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sentiment_gauge": {"score": gauge_score, "count": gauge_count},
        "sentiment_series": sentiment_series,
        "correlation": {"scatter": scatter, "lags": lags},
        "news": news_items,
        "market_stats": market_stats,
    }
    return snapshot


if __name__ == "__main__":
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"[OK] Snapshot written → {OUT_PATH}")
    print(f"     sentiment_series : {len(snapshot['sentiment_series'])} points")
    print(f"     scatter          : {len(snapshot['correlation']['scatter'])} points")
    print(f"     lags             : {snapshot['correlation']['lags']}")
    print(f"     news             : {len(snapshot['news'])} items")
