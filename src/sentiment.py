"""
Sentiment analysis module — FinBERT + Gemma 3 (Ollama) ensemble.

Pipeline:
  1. FinBERT: in-process text-classification (HuggingFace transformers)
  2. Gemma 3: prompt-based classification via Ollama HTTP API (localhost:11434)
  3. Ensemble: weighted average → ensemble_score
  4. agreement_score = 1 - |finbert_score - gemma_score| / 2
  5. Apply neutral filter on ensemble_score
  6. Save to data/processed/news_sentiment.csv
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    pipeline,
)

log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent
DATA_PROC = BASE_DIR / "data" / "processed"
DATA_PROC.mkdir(parents=True, exist_ok=True)

# ── 모델 설정 ──────────────────────────────────────────────────────────────
MODEL_NAME     = "ProsusAI/finbert"
GEMMA_MODEL_ID = os.getenv("GEMMA_MODEL_ID", "gemma3:1b")
OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://localhost:11434")
FINBERT_WEIGHT = float(os.getenv("FINBERT_WEIGHT", "0.5"))
GEMMA_WEIGHT   = float(os.getenv("GEMMA_WEIGHT", "0.5"))

OUTPUT_FILE = DATA_PROC / "news_sentiment.csv"

NEUTRAL_PROB_THRESHOLD = 0.5
DIFF_THRESHOLD         = 0.10

# Gemma 레이블 → 확률 근사 매핑
_GEMMA_PROB_MAP: dict[str, tuple[float, float, float]] = {
    "positive": (0.9, 0.05, 0.05),
    "neutral":  (0.05, 0.9, 0.05),
    "negative": (0.05, 0.05, 0.9),
}

# 구 CSV 컬럼 → 신규 컬럼 이름 (하위 호환 마이그레이션)
_LEGACY_COL_MAP = {
    "positive_prob": "finbert_positive_prob",
    "neutral_prob":  "finbert_neutral_prob",
    "negative_prob": "finbert_negative_prob",
}


# ── 디바이스 감지 ──────────────────────────────────────────────────────────
def _get_device() -> str:
    if torch.cuda.is_available():
        log.info("Using CUDA")
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        log.info("Using MPS (Apple Silicon)")
        return "mps"
    log.info("Using CPU")
    return "cpu"


# ── FinBERT ────────────────────────────────────────────────────────────────
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


def _parse_finbert_scores(raw_output: list[list[dict]]) -> list[dict]:
    """Convert FinBERT pipeline output to finbert_* probability dicts."""
    label_map = {
        "positive": "finbert_positive_prob",
        "neutral":  "finbert_neutral_prob",
        "negative": "finbert_negative_prob",
    }
    results = []
    for item in raw_output:
        row = {"finbert_positive_prob": 0.0, "finbert_neutral_prob": 0.0, "finbert_negative_prob": 0.0}
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
    Score headlines with FinBERT.

    Returns DataFrame with columns:
        title, finbert_positive_prob, finbert_neutral_prob, finbert_negative_prob, finbert_score
    """
    if nlp is None:
        nlp = load_finbert_pipeline()

    all_scores: list[dict] = []
    total = len(titles)
    for i in range(0, total, batch_size):
        batch = titles[i : i + batch_size]
        raw = nlp(batch, batch_size=batch_size)
        all_scores.extend(_parse_finbert_scores(raw))
        if (i + batch_size) % 1000 == 0 or i + batch_size >= total:
            log.info("  FinBERT scored %d / %d", min(i + batch_size, total), total)

    df = pd.DataFrame(all_scores)
    df["title"] = titles
    df["finbert_score"] = df["finbert_positive_prob"] - df["finbert_negative_prob"]
    return df[["title", "finbert_positive_prob", "finbert_neutral_prob", "finbert_negative_prob", "finbert_score"]]


# ── Gemma 3 via Ollama ─────────────────────────────────────────────────────
def check_ollama_available() -> bool:
    """Ollama 서버가 실행 중인지 확인한다."""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        if resp.status_code == 200:
            # 요청한 모델이 pull 되어 있는지 확인
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            if not any(GEMMA_MODEL_ID in m for m in models):
                log.warning(
                    "Ollama 실행 중이나 '%s' 모델 없음. `ollama pull %s` 실행 필요.",
                    GEMMA_MODEL_ID, GEMMA_MODEL_ID,
                )
                return False
            return True
    except Exception as exc:
        log.warning("Ollama 연결 실패 (%s): %s", OLLAMA_HOST, exc)
    return False


def _build_gemma_prompt(title: str) -> str:
    return (
        "Classify the sentiment of the following cryptocurrency news headline.\n"
        "Respond with ONLY one word: positive, neutral, or negative.\n\n"
        f'Headline: "{title}"\n'
        "Sentiment:"
    )


def _call_ollama_single(title: str, max_retries: int = 3) -> tuple[str, str]:
    """Ollama API 단건 호출. (title, label) 반환. 실패 시 지수 백오프로 재시도."""
    prompt = _build_gemma_prompt(title)
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{OLLAMA_HOST}/api/generate",
                json={
                    "model": GEMMA_MODEL_ID,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 5},
                },
                timeout=30,
            )
            resp.raise_for_status()
            generated = resp.json().get("response", "").strip()
            first_word = re.split(r"\W+", generated.lower())[0] if generated else ""
            label = first_word if first_word in _GEMMA_PROB_MAP else "neutral"
            return title, label
        except requests.exceptions.RequestException as exc:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def score_headlines_gemma(
    titles: list[str],
    max_workers: int = 1,
) -> pd.DataFrame:
    """
    Score headlines with Gemma 3 via Ollama HTTP API.
    Ollama는 순차 처리이므로 max_workers=1이 기본값이다.

    Returns DataFrame with columns:
        title, gemma_positive_prob, gemma_neutral_prob, gemma_negative_prob, gemma_score
    """
    results: dict[str, str] = {}
    total = len(titles)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {ex.submit(_call_ollama_single, t): t for t in titles}
        done = 0
        for future in as_completed(future_map):
            try:
                title, label = future.result()
                results[title] = label
            except Exception as exc:
                title = future_map[future]
                log.warning("Gemma 추론 실패 ('%s'): %s → neutral fallback", title[:40], exc)
                results[title] = "neutral"
            done += 1
            if done % 20 == 0 or done == total:
                log.info("  Gemma scored %d / %d", done, total)

    rows = []
    for t in titles:  # 원래 순서 유지
        label = results.get(t, "neutral")
        pos, neu, neg = _GEMMA_PROB_MAP[label]
        rows.append({
            "title": t,
            "gemma_positive_prob": pos,
            "gemma_neutral_prob":  neu,
            "gemma_negative_prob": neg,
            "gemma_score": pos - neg,
        })
    return pd.DataFrame(rows)


# ── 앙상블 결합 ────────────────────────────────────────────────────────────
def _label_ensemble(row: pd.Series) -> str:
    if not row["is_valid"]:
        return "neutral"
    return "positive" if row["ensemble_score"] > 0 else "negative"


def combine_ensemble(
    finbert_df: pd.DataFrame,
    gemma_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """
    Combine FinBERT and Gemma scores.

    - gemma_df=None → fallback: ensemble_score = finbert_score
    - 중립 필터는 FinBERT 확률 기준 적용
    - score = ensemble_score (backward-compat alias)
    """
    df = finbert_df.copy()

    if gemma_df is not None:
        gemma_cols = gemma_df.drop(columns=["title"], errors="ignore").reset_index(drop=True)
        df = pd.concat([df.reset_index(drop=True), gemma_cols], axis=1)
        df["ensemble_score"]  = df["finbert_score"] * FINBERT_WEIGHT + df["gemma_score"] * GEMMA_WEIGHT
        df["agreement_score"] = 1.0 - (df["finbert_score"] - df["gemma_score"]).abs() / 2.0
    else:
        df["gemma_positive_prob"] = None
        df["gemma_neutral_prob"]  = None
        df["gemma_negative_prob"] = None
        df["gemma_score"]         = None
        df["ensemble_score"]      = df["finbert_score"]
        df["agreement_score"]     = None

    df["is_valid"] = ~(
        (df["finbert_neutral_prob"] >= NEUTRAL_PROB_THRESHOLD)
        | (np.abs(df["finbert_positive_prob"] - df["finbert_negative_prob"]) < DIFF_THRESHOLD)
    )
    df["sentiment_label"] = df.apply(_label_ensemble, axis=1)
    df["score"] = df["ensemble_score"]
    return df


# ── 레거시 CSV 마이그레이션 ────────────────────────────────────────────────
def _migrate_legacy_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename old-style columns (positive_prob etc.) to finbert_* in existing CSVs."""
    rename = {
        old: new
        for old, new in _LEGACY_COL_MAP.items()
        if old in df.columns and new not in df.columns
    }
    if rename:
        df = df.rename(columns=rename)
        if "score" in df.columns and "finbert_score" not in df.columns:
            df["finbert_score"] = df["score"]
        log.info("Migrated legacy CSV columns: %s", list(rename.keys()))
    return df


# ── 파이프라인 ────────────────────────────────────────────────────────────
def run_sentiment_pipeline(
    news_df: pd.DataFrame,
    batch_size: int = 64,
    use_gemma: bool = True,
) -> pd.DataFrame:
    """
    Incremental pipeline: skip already-scored articles.

    - use_gemma=True  : FinBERT(in-process) + Gemma(Ollama) 병렬 실행
    - use_gemma=False : FinBERT 단독 실행 (Ollama 미실행 환경 fallback)
    """
    # ── 기존 결과 로드 ────────────────────────────────────────────
    if OUTPUT_FILE.exists() and "url" in news_df.columns:
        existing_df = pd.read_csv(OUTPUT_FILE, parse_dates=["published_at"])
        existing_df = _migrate_legacy_columns(existing_df)
        scored_urls = set(existing_df["url"].dropna())
        new_df = news_df[~news_df["url"].isin(scored_urls)].reset_index(drop=True)
        log.info("증분 처리: %d건 신규 / %d건 기존 캐시 재사용", len(new_df), len(news_df) - len(new_df))
    else:
        existing_df = pd.DataFrame()
        new_df = news_df.reset_index(drop=True)
        log.info("전체 처리: %d건", len(new_df))

    if new_df.empty:
        log.info("신규 기사 없음 — 기존 캐시 반환")
        return existing_df

    titles = new_df.apply(
        lambda r: f"{r['title']}. {str(r['body']).strip()[:512]}"
        if pd.notna(r.get("body")) and str(r.get("body", "")).strip()
        else r["title"],
        axis=1,
    ).fillna("").tolist()
    finbert_nlp = load_finbert_pipeline()

    # ── FinBERT + Gemma 병렬 추론 ─────────────────────────────────
    gemma_scores_df = None
    if use_gemma:
        with ThreadPoolExecutor(max_workers=2) as ex:
            fb_future = ex.submit(score_headlines, titles, finbert_nlp, batch_size)
            gm_future = ex.submit(score_headlines_gemma, titles)
            finbert_scores_df = fb_future.result()
            try:
                gemma_scores_df = gm_future.result()
            except Exception as exc:
                log.warning("Gemma 추론 실패 — FinBERT 단독으로 fallback: %s", exc)
                gemma_scores_df = None
    else:
        log.info("Gemma 비활성화 — FinBERT 단독 실행")
        finbert_scores_df = score_headlines(titles, nlp=finbert_nlp, batch_size=batch_size)

    # ── 앙상블 결합 ───────────────────────────────────────────────
    ensemble_df = combine_ensemble(finbert_scores_df, gemma_scores_df)
    new_result  = new_df.reset_index(drop=True).join(ensemble_df.drop(columns=["title"]))

    # ── 기존 + 신규 병합 후 저장 ──────────────────────────────────
    if not existing_df.empty:
        result = pd.concat([existing_df, new_result], ignore_index=True)
        if "url" in result.columns:
            result = result.drop_duplicates("url", keep="last")
    else:
        result = new_result

    result = result.sort_values("published_at").reset_index(drop=True)
    result.to_csv(OUTPUT_FILE, index=False)
    log.info(
        "Sentiment results saved → %s  (valid: %d / %d)",
        OUTPUT_FILE,
        result["is_valid"].sum() if "is_valid" in result.columns else "?",
        len(result),
    )
    return result


def load_sentiment_results() -> pd.DataFrame:
    """Load previously computed sentiment results."""
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(f"Run run_sentiment_pipeline() first. Expected: {OUTPUT_FILE}")
    df = pd.read_csv(OUTPUT_FILE, parse_dates=["published_at"])
    df = _migrate_legacy_columns(df)
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
    return df


def sentiment_summary(df: pd.DataFrame) -> dict:
    """Return a summary of sentiment distribution."""
    total = len(df)
    valid = df["is_valid"].sum()
    pos   = (df["sentiment_label"] == "positive").sum()
    neg   = (df["sentiment_label"] == "negative").sum()
    neu   = total - valid

    score_col = "ensemble_score" if "ensemble_score" in df.columns else "score"
    summary = {
        "total": total,
        "valid_non_neutral": int(valid),
        "positive": int(pos),
        "negative": int(neg),
        "neutral_filtered": int(neu),
        "neutral_pct": round(neu / total * 100, 1) if total else 0,
        "mean_score_valid": round(df.loc[df["is_valid"], score_col].mean(), 4) if valid else None,
    }
    log.info(
        "Sentiment summary — total: %d | valid: %d | pos: %d | neg: %d | neutral: %d (%.1f%%)",
        total, valid, pos, neg, neu, summary["neutral_pct"],
    )
    return summary
