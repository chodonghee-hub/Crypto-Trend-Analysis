"""
CryptoSentinel FastAPI 서버
- /api/data/analysis : 처리된 CSV → JSON 반환 (로컬 개발용)
- /                  : web/ 정적 파일 서빙

실행: uvicorn server:app --reload --port 8080
문서: http://localhost:8080/docs
"""

import json
import math
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from scipy.stats import pearsonr

ROOT = Path(__file__).parent

app = FastAPI(
    title="CryptoSentinel API",
    description="BTC Sentiment Analysis Dashboard — Local Data API",
    version="1.0.0",
)


def safe_float(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return round(float(val), 6)


def compute_lags(df: pd.DataFrame) -> list[dict]:
    lags = [("5m", "return_5m"), ("15m", "return_15m"), ("30m", "return_30m"), ("60m", "return_60m")]
    results = []
    for label, col in lags:
        valid = df[["window_score", col]].dropna()
        if len(valid) < 3:
            results.append({"lag": label, "r": None, "p": None, "n": int(len(valid))})
            continue
        r, p = pearsonr(valid["window_score"], valid[col])
        results.append({"lag": label, "r": round(float(r), 4), "p": round(float(p), 4), "n": int(len(valid))})
    return results


@app.get("/api/data/analysis", summary="분석 데이터 반환")
def get_analysis():
    """
    merged_analysis.csv + news_sentiment.csv + market_stats.json 을 읽어
    웹 대시보드에 필요한 JSON을 반환한다.
    """
    merged_path  = ROOT / "data" / "processed" / "merged_analysis.csv"
    news_path    = ROOT / "data" / "processed" / "news_sentiment.csv"
    stats_path   = ROOT / "data" / "processed" / "market_stats.json"

    # ── merged_analysis ────────────────────────────────────────────
    if not merged_path.exists():
        merged_df = pd.DataFrame()
    else:
        merged_df = pd.read_csv(merged_path)
        merged_df["window_start"] = pd.to_datetime(merged_df["window_start"], utc=True)

    # ── news_sentiment ─────────────────────────────────────────────
    if not news_path.exists():
        news_df = pd.DataFrame()
    else:
        news_df = pd.read_csv(news_path)
        news_df["published_at"] = pd.to_datetime(news_df["published_at"], utc=True)

    # ── market_stats ───────────────────────────────────────────────
    market_stats = {}
    if stats_path.exists():
        with open(stats_path, encoding="utf-8") as f:
            market_stats = json.load(f)

    # ── Gauge ──────────────────────────────────────────────────────
    if not news_df.empty and "score" in news_df.columns:
        valid_news = news_df[news_df.get("is_valid", pd.Series([True] * len(news_df))) == True]
        gauge_score = safe_float(valid_news["score"].mean()) if not valid_news.empty else 0.0
        gauge_count = int(len(valid_news))
    else:
        gauge_score, gauge_count = 0.0, 0

    # ── Sentiment series ───────────────────────────────────────────
    sentiment_series = []
    if not merged_df.empty:
        for _, row in merged_df.iterrows():
            sentiment_series.append({
                "timestamp": row["window_start"].isoformat(),
                "score": safe_float(row["window_score"]),
            })

    # ── Scatter ────────────────────────────────────────────────────
    scatter = []
    if not merged_df.empty:
        for _, row in merged_df.iterrows():
            scatter.append({
                "date": row["window_start"].isoformat(),
                "sentiment": safe_float(row["window_score"]),
                "return_15m": safe_float(row.get("return_15m")),
                "return_60m": safe_float(row.get("return_60m")),
            })

    # ── Lag correlations ───────────────────────────────────────────
    lags = compute_lags(merged_df) if not merged_df.empty else []

    # ── News list ──────────────────────────────────────────────────
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

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sentiment_gauge": {"score": gauge_score, "count": gauge_count},
        "sentiment_series": sentiment_series,
        "correlation": {"scatter": scatter, "lags": lags},
        "news": news_items,
        "market_stats": market_stats,
    }


# 정적 파일은 API 라우트 등록 후 마운트 (순서 중요)
web_dir = ROOT / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
