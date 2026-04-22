"""
CryptoSentinel FastAPI 서버
- /api/data/analysis  : 처리된 CSV → JSON 반환 (로컬 개발용)
- /api/pipeline/run   : 파이프라인 즉시 실행 (수동 트리거)
- /api/pipeline/status: 마지막 실행 결과 확인
- /                   : web/ 정적 파일 서빙

실행: uvicorn server:app --reload --port 8080
문서: http://localhost:8080/docs
"""

import asyncio
import functools
import json
import logging
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from scipy.stats import pearsonr

from src.collector import (
    fetch_coingecko_news,
    fetch_all_rss,
    fetch_coingecko_stats,
    load_all_news,
    load_klines,
)
from src.sentiment import run_sentiment_pipeline
from src.analyzer import run_analysis_pipeline

log = logging.getLogger("cryptosentinel")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ROOT = Path(__file__).parent

PIPELINE_INTERVAL_HOURS = 1

_pipeline_status: dict = {"last_run": None, "status": "not_started", "message": ""}


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


def _get_file_mtimes() -> tuple[float, float, float]:
    """각 데이터 파일의 수정 시각을 반환 (캐시 키로 사용)."""
    merged_path = ROOT / "data" / "processed" / "merged_analysis.csv"
    news_path   = ROOT / "data" / "processed" / "news_sentiment.csv"
    stats_path  = ROOT / "data" / "processed" / "market_stats.json"
    return (
        os.path.getmtime(merged_path) if merged_path.exists() else 0.0,
        os.path.getmtime(news_path)   if news_path.exists()   else 0.0,
        os.path.getmtime(stats_path)  if stats_path.exists()  else 0.0,
    )


@functools.lru_cache(maxsize=1)
def _build_analysis_payload(merged_mtime: float, news_mtime: float, stats_mtime: float) -> dict:
    """
    CSV 파일이 변경될 때만 재계산한다.
    mtime 인수가 바뀌면 lru_cache가 자동으로 무효화된다.
    """
    merged_path = ROOT / "data" / "processed" / "merged_analysis.csv"
    news_path   = ROOT / "data" / "processed" / "news_sentiment.csv"
    stats_path  = ROOT / "data" / "processed" / "market_stats.json"

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

    # ── Sentiment series (벡터화 — iterrows 제거) ─────────────────
    sentiment_series = []
    if not merged_df.empty:
        sentiment_series = [
            {"timestamp": ts.isoformat(), "score": safe_float(sc)}
            for ts, sc in zip(merged_df["window_start"], merged_df["window_score"])
        ]

    # ── Scatter (벡터화) ──────────────────────────────────────────
    scatter = []
    if not merged_df.empty:
        r15_col = merged_df["return_15m"] if "return_15m" in merged_df.columns else [None] * len(merged_df)
        r60_col = merged_df["return_60m"] if "return_60m" in merged_df.columns else [None] * len(merged_df)
        scatter = [
            {
                "date": ts.isoformat(),
                "sentiment": safe_float(sc),
                "return_15m": safe_float(r15),
                "return_60m": safe_float(r60),
            }
            for ts, sc, r15, r60 in zip(merged_df["window_start"], merged_df["window_score"], r15_col, r60_col)
        ]

    # ── Lag correlations ───────────────────────────────────────────
    lags = compute_lags(merged_df) if not merged_df.empty else []

    # ── News list (최신 20건) ──────────────────────────────────────
    news_items = []
    if not news_df.empty:
        cols = ["title", "url", "source", "published_at", "score", "sentiment_label"]
        available = [c for c in cols if c in news_df.columns]
        top_news = news_df[available].sort_values("published_at", ascending=False)
        for record in top_news.to_dict("records"):
            item = {}
            for c in available:
                val = record.get(c)
                if hasattr(val, "isoformat"):
                    item[c] = val.isoformat()
                elif isinstance(val, float):
                    item[c] = safe_float(val)
                else:
                    item[c] = val
            news_items.append(item)

    log.info("Analysis payload 빌드 완료 (merged=%d rows, news=%d rows)", len(merged_df), len(news_df))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sentiment_gauge": {"score": gauge_score, "count": gauge_count},
        "sentiment_series": sentiment_series,
        "correlation": {"scatter": scatter, "lags": lags},
        "news": news_items,
        "market_stats": market_stats,
    }


def _export_snapshot() -> None:
    """파이프라인 완료 후 snapshot.json 자동 갱신."""
    payload = _build_analysis_payload(*_get_file_mtimes())
    out_path = ROOT / "web" / "data" / "snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("Snapshot 자동 갱신 완료 → %s", out_path)


def run_pipeline() -> None:
    """전체 파이프라인: 수집 → 감성분석 → 상관분석"""
    global _pipeline_status
    _pipeline_status = {"last_run": datetime.now(timezone.utc).isoformat(), "status": "running", "message": ""}
    try:
        log.info("=== 파이프라인 시작 ===")

        log.info("[1/4] 뉴스 수집 (CoinGecko 2페이지 + RSS)")
        fetch_coingecko_news(pages=2)
        fetch_all_rss()
        fetch_coingecko_stats()

        log.info("[2/4] 뉴스 로드")
        news_df = load_all_news()
        if news_df.empty:
            raise RuntimeError("수집된 뉴스 없음")

        log.info("[3/4] FinBERT 감성분석 (%d건)", len(news_df))
        sentiment_df = run_sentiment_pipeline(news_df)

        log.info("[4/4] 상관분석")
        klines_df = load_klines("1m")
        if klines_df.empty:
            raise RuntimeError("klines 데이터 없음 — 01_data_collection.ipynb 먼저 실행 필요")
        run_analysis_pipeline(sentiment_df, klines_df)

        _pipeline_status["status"] = "success"
        _pipeline_status["message"] = f"완료 ({len(news_df)}건 처리)"
        log.info("=== 파이프라인 완료 ===")

        # 캐시 무효화 후 snapshot 자동 갱신
        _build_analysis_payload.cache_clear()
        try:
            _export_snapshot()
        except Exception as exc:
            log.warning("Snapshot 갱신 실패 (무시): %s", exc)

    except Exception as exc:
        _pipeline_status["status"] = "error"
        _pipeline_status["message"] = str(exc)
        log.error("파이프라인 오류: %s", exc)


async def _pipeline_loop() -> None:
    """서버 시작 시 즉시 1회 실행, 이후 1시간마다 반복"""
    loop = asyncio.get_event_loop()
    while True:
        await loop.run_in_executor(None, run_pipeline)
        await asyncio.sleep(PIPELINE_INTERVAL_HOURS * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_pipeline_loop())
    yield
    task.cancel()


app = FastAPI(
    title="CryptoSentinel API",
    description="BTC Sentiment Analysis Dashboard — Local Data API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/api/pipeline/run", summary="파이프라인 즉시 실행")
async def trigger_pipeline():
    """백그라운드에서 파이프라인을 즉시 실행한다."""
    if _pipeline_status.get("status") == "running":
        return {"message": "이미 실행 중입니다.", "status": _pipeline_status}
    loop = asyncio.get_event_loop()
    asyncio.create_task(loop.run_in_executor(None, run_pipeline))
    return {"message": "파이프라인 실행 시작됨"}


@app.get("/api/pipeline/status", summary="파이프라인 마지막 실행 결과")
def pipeline_status():
    return _pipeline_status


@app.get("/api/data/analysis", summary="분석 데이터 반환")
def get_analysis():
    """
    파일 mtime 기반 캐싱: CSV가 변경될 때만 재계산한다.
    파이프라인 실행 간격(1h) 동안 동일 요청은 메모리에서 즉시 반환.
    """
    return _build_analysis_payload(*_get_file_mtimes())


@app.get("/api/data/klines", summary="Historical BTC klines from parquet")
def get_klines(
    interval: str = "1h",
    from_ts: Optional[int] = None,
    to_ts: Optional[int] = None,
    limit: int = 2000,
):
    df = load_klines(interval if interval != "1d" else "1h")
    if df.empty:
        return []

    if interval == "1d":
        df = (
            df.set_index("open_time")
            .resample("1D")
            .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
            .dropna()
            .reset_index()
        )

    if from_ts is not None:
        df = df[df["open_time"] >= pd.Timestamp(from_ts, unit="ms", tz="UTC")]
    if to_ts is not None:
        df = df[df["open_time"] <= pd.Timestamp(to_ts, unit="ms", tz="UTC")]

    if len(df) > limit:
        step = max(1, len(df) // limit)
        df = df.iloc[::step]

    return [
        {
            "time": int(row.open_time.timestamp() * 1000),
            "open": round(float(row.open), 2),
            "high": round(float(row.high), 2),
            "low": round(float(row.low), 2),
            "close": round(float(row.close), 2),
        }
        for row in df.itertuples()
    ]


# 정적 파일은 API 라우트 등록 후 마운트 (순서 중요)
# npm run build 후에는 dist/, 그 외에는 web/ 폴백
dist_dir = ROOT / "dist"
web_dir  = ROOT / "web"
serve_dir = dist_dir if dist_dir.exists() else web_dir
if serve_dir.exists():
    app.mount("/", StaticFiles(directory=str(serve_dir), html=True), name="static")
