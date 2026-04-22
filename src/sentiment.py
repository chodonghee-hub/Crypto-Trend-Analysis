"""
Sentiment analysis module using ProsusAI/finbert.

Pipeline:
  1. Load FinBERT model (auto-cached by Hugging Face)
  2. Batch-score headlines → positive / neutral / negative probabilities
  3. Compute score = positive_prob - negative_prob  ∈ [-1, +1]
  4. Apply neutral filter (PRD §4.3.1)
  5. Save results to data/processed/news_sentiment.csv
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PROC = BASE_DIR / "data" / "processed"
DATA_PROC.mkdir(parents=True, exist_ok=True)

MODEL_NAME = "ProsusAI/finbert"
OUTPUT_FILE = DATA_PROC / "news_sentiment.csv"

NEUTRAL_PROB_THRESHOLD = 0.5
DIFF_THRESHOLD = 0.10


def _get_device() -> str:
    if torch.cuda.is_available():
        log.info("Using CUDA")
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        log.info("Using MPS (Apple Silicon)")
        return "mps"
    log.info("Using CPU")
    return "cpu"


def load_finbert_pipeline(device: str | None = None):
    """Load FinBERT as a HuggingFace text-classification pipeline."""
    if device is None:
        device = _get_device()

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)

    device_id = 0 if device == "cuda" else (-1 if device == "cpu" else device)
    nlp = pipeline(
        "text-classification",
        model=model,
        tokenizer=tokenizer,
        device=device_id,
        top_k=None,
        truncation=True,
        max_length=512,
    )
    log.info("FinBERT pipeline loaded on %s", device)
    return nlp


def _parse_scores(raw_output: list[list[dict]]) -> list[dict]:
    """Convert pipeline output to {positive_prob, neutral_prob, negative_prob}."""
    results = []
    label_map = {"positive": "positive_prob", "neutral": "neutral_prob", "negative": "negative_prob"}
    for item in raw_output:
        row = {"positive_prob": 0.0, "neutral_prob": 0.0, "negative_prob": 0.0}
        for entry in item:
            key = label_map.get(entry["label"].lower())
            if key:
                row[key] = entry["score"]
        results.append(row)
    return results


def score_headlines(
    titles: list[str],
    nlp=None,
    batch_size: int = 64,
) -> pd.DataFrame:
    """
    Score a list of English news headlines with FinBERT.

    Returns a DataFrame with columns:
        title, positive_prob, neutral_prob, negative_prob, score, is_valid
    """
    if nlp is None:
        nlp = load_finbert_pipeline()

    all_scores: list[dict] = []
    total = len(titles)
    for i in range(0, total, batch_size):
        batch = titles[i : i + batch_size]
        raw = nlp(batch, batch_size=batch_size)
        all_scores.extend(_parse_scores(raw))
        if (i + batch_size) % 1000 == 0 or i + batch_size >= total:
            log.info("  scored %d / %d", min(i + batch_size, total), total)

    df = pd.DataFrame(all_scores)
    df["title"] = titles
    df["score"] = df["positive_prob"] - df["negative_prob"]

    df["is_valid"] = ~(
        (df["neutral_prob"] >= NEUTRAL_PROB_THRESHOLD)
        | (np.abs(df["positive_prob"] - df["negative_prob"]) < DIFF_THRESHOLD)
    )

    df["sentiment_label"] = df.apply(_label, axis=1)
    return df[["title", "positive_prob", "neutral_prob", "negative_prob", "score", "is_valid", "sentiment_label"]]


def _label(row: pd.Series) -> str:
    if not row["is_valid"]:
        return "neutral"
    return "positive" if row["score"] > 0 else "negative"


def run_sentiment_pipeline(news_df: pd.DataFrame, batch_size: int = 64) -> pd.DataFrame:
    """
    증분 처리 파이프라인: 이미 score가 있는 기사는 FinBERT를 재실행하지 않는다.
    신규 기사만 추론 후 기존 결과와 합쳐 저장한다.
    """
    SCORE_COLS = ["positive_prob", "neutral_prob", "negative_prob", "score", "is_valid", "sentiment_label"]

    # ── 기존 결과 로드 ─────────────────────────────────────────────
    if OUTPUT_FILE.exists() and "url" in news_df.columns:
        existing_df = pd.read_csv(OUTPUT_FILE, parse_dates=["published_at"])
        scored_urls = set(existing_df["url"].dropna())
        new_df = news_df[~news_df["url"].isin(scored_urls)].reset_index(drop=True)
        log.info("증분 처리: %d건 신규 / %d건 기존 캐시 재사용", len(new_df), len(news_df) - len(new_df))
    else:
        existing_df = pd.DataFrame()
        new_df = news_df.reset_index(drop=True)
        log.info("전체 처리: %d건", len(new_df))

    # ── 신규 기사만 FinBERT 추론 ───────────────────────────────────
    if new_df.empty:
        log.info("신규 기사 없음 — 기존 캐시 반환")
        return existing_df

    titles = new_df["title"].fillna("").tolist()
    nlp = load_finbert_pipeline()
    scores_df = score_headlines(titles, nlp=nlp, batch_size=batch_size)
    new_result = new_df.reset_index(drop=True).join(scores_df.drop(columns=["title"]))

    # ── 기존 + 신규 병합 후 저장 ──────────────────────────────────
    if not existing_df.empty:
        result = pd.concat([existing_df, new_result], ignore_index=True)
        if "url" in result.columns:
            result = result.drop_duplicates("url", keep="last")
    else:
        result = new_result

    result = result.sort_values("published_at").reset_index(drop=True)
    result.to_csv(OUTPUT_FILE, index=False)
    log.info("Sentiment results saved → %s  (valid: %d / %d)",
             OUTPUT_FILE,
             result["is_valid"].sum() if "is_valid" in result.columns else "?",
             len(result))
    return result


def load_sentiment_results() -> pd.DataFrame:
    """Load previously computed sentiment results."""
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(f"Run run_sentiment_pipeline() first. Expected: {OUTPUT_FILE}")
    df = pd.read_csv(OUTPUT_FILE, parse_dates=["published_at"])
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
    return df


def sentiment_summary(df: pd.DataFrame) -> dict:
    """Print and return a summary of sentiment distribution."""
    total = len(df)
    valid = df["is_valid"].sum()
    pos = (df["sentiment_label"] == "positive").sum()
    neg = (df["sentiment_label"] == "negative").sum()
    neu = total - valid

    summary = {
        "total": total,
        "valid_non_neutral": int(valid),
        "positive": int(pos),
        "negative": int(neg),
        "neutral_filtered": int(neu),
        "neutral_pct": round(neu / total * 100, 1) if total else 0,
        "mean_score_valid": round(df.loc[df["is_valid"], "score"].mean(), 4) if valid else None,
    }
    log.info(
        "Sentiment summary — total: %d | valid: %d | pos: %d | neg: %d | neutral: %d (%.1f%%)",
        total, valid, pos, neg, neu, summary["neutral_pct"],
    )
    return summary
