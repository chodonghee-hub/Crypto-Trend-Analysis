"""
Correlation analysis module.

Steps:
  1. Aggregate news into 5-minute windows using confidence-weighted average
  2. Calculate BTC price returns at T+5m, T+15m, T+30m, T+60m
  3. Merge sentiment windows with price returns
  4. Compute Pearson correlation coefficients with p-value validation
  5. Save merged dataset to data/processed/merged_analysis.csv
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PROC = BASE_DIR / "data" / "processed"
DATA_PROC.mkdir(parents=True, exist_ok=True)

MERGED_FILE = DATA_PROC / "merged_analysis.csv"
LAGS = [5, 15, 30, 60]  # minutes


# ──────────────────────────────────────────────
# Step 1: Confidence-weighted window aggregation
# ──────────────────────────────────────────────

def aggregate_to_windows(sentiment_df: pd.DataFrame, window_minutes: int = 5) -> pd.DataFrame:
    """
    Aggregate sentiment scores into fixed-width time windows.

    Uses confidence-weighted average:
        confidence_i = max(positive_prob, negative_prob)
        window_score = Σ(score_i × confidence_i) / Σ(confidence_i)

    Only rows with is_valid=True are included.
    Returns a DataFrame indexed by window_start (UTC, floored to window_minutes).
    """
    df = sentiment_df[sentiment_df["is_valid"]].copy()
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
    df["confidence"] = df[["positive_prob", "negative_prob"]].max(axis=1)

    freq = f"{window_minutes}min"
    df["window_start"] = df["published_at"].dt.floor(freq)

    def weighted_avg(group: pd.DataFrame) -> pd.Series:
        w = group["confidence"]
        s = group["score"]
        total_w = w.sum()
        if total_w == 0:
            return pd.Series({"window_score": np.nan, "news_count": len(group), "confidence_sum": 0.0})
        return pd.Series({
            "window_score": (s * w).sum() / total_w,
            "news_count": len(group),
            "confidence_sum": total_w,
        })

    agg = df.groupby("window_start")[["confidence", "score"]].apply(weighted_avg).reset_index()
    agg["window_start"] = pd.to_datetime(agg["window_start"], utc=True)
    log.info("Aggregated %d valid news → %d windows (%d-min)", len(df), len(agg), window_minutes)
    return agg


# ──────────────────────────────────────────────
# Step 2: Price returns at T+N
# ──────────────────────────────────────────────

def compute_price_returns(klines_df: pd.DataFrame, lags: list[int] = LAGS) -> pd.DataFrame:
    """
    For each 1-minute candle, compute forward returns at T+5m, T+15m, T+30m, T+60m.
    Returns a DataFrame with open_time and return columns.
    """
    df = klines_df[["open_time", "close"]].copy()
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.sort_values("open_time").reset_index(drop=True)
    df = df.set_index("open_time")

    for lag in lags:
        shifted = df["close"].shift(-lag)
        df[f"return_{lag}m"] = (shifted - df["close"]) / df["close"] * 100

    df = df.reset_index()
    log.info("Computed price returns for lags: %s", lags)
    return df


# ──────────────────────────────────────────────
# Step 3: Merge sentiment windows with price returns
# ──────────────────────────────────────────────

def merge_sentiment_price(
    windows_df: pd.DataFrame,
    returns_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge aggregated sentiment windows with 1-min price return data.
    window_start is matched to the nearest open_time (floor to minute).
    """
    ret = returns_df.copy()
    ret["open_time"] = pd.to_datetime(ret["open_time"], utc=True)

    win = windows_df.copy()
    win["open_time"] = win["window_start"].dt.floor("1min")

    merged = pd.merge(win, ret, on="open_time", how="inner")
    merged = merged.dropna(subset=["window_score"])
    log.info("Merged dataset: %d rows", len(merged))
    return merged


# ──────────────────────────────────────────────
# Step 4: Pearson correlation
# ──────────────────────────────────────────────

def compute_correlations(merged_df: pd.DataFrame, lags: list[int] = LAGS) -> pd.DataFrame:
    """
    Compute Pearson correlation between window_score and each lag return.
    Returns a summary DataFrame with r, p-value, N, and significance flag.
    """
    records = []
    for lag in lags:
        col = f"return_{lag}m"
        subset = merged_df[["window_score", col]].dropna()
        n = len(subset)
        if n < 30:
            log.warning("Lag T+%dm: only %d rows — skipping", lag, n)
            records.append({"lag_min": lag, "r": np.nan, "p_value": np.nan, "n": n, "significant": False})
            continue

        r, p = stats.pearsonr(subset["window_score"], subset[col])
        significant = p < 0.05
        records.append({"lag_min": lag, "r": round(r, 4), "p_value": round(p, 6), "n": n, "significant": significant})
        log.info("T+%02dm: r=%.4f  p=%.4f  n=%d  sig=%s", lag, r, p, n, significant)

    return pd.DataFrame(records)


# ──────────────────────────────────────────────
# Step 5: Period performance table
# ──────────────────────────────────────────────

def compute_period_performance(
    klines_df: pd.DataFrame,
    sentiment_df: pd.DataFrame,
    periods: dict[str, int] | None = None,
) -> pd.DataFrame:
    """
    Build a period-performance table (today / 7d / 30d / 60d / 90d).

    Columns: period, price_change_pct, avg_sentiment_score, valid_news_count
    """
    if periods is None:
        periods = {"Today": 1, "7 Days": 7, "30 Days": 30, "60 Days": 60, "90 Days": 90}

    klines = klines_df[["open_time", "close"]].copy()
    klines["open_time"] = pd.to_datetime(klines["open_time"], utc=True)
    klines = klines.sort_values("open_time")

    sent = sentiment_df[sentiment_df["is_valid"]].copy()
    sent["published_at"] = pd.to_datetime(sent["published_at"], utc=True)

    now = klines["open_time"].max()
    records = []

    for label, days in periods.items():
        cutoff = now - pd.Timedelta(days=days)
        k_slice = klines[klines["open_time"] >= cutoff]
        s_slice = sent[sent["published_at"] >= cutoff]

        if k_slice.empty:
            records.append({"period": label, "price_change_pct": np.nan,
                            "avg_sentiment": np.nan, "valid_news_count": 0})
            continue

        price_start = k_slice["close"].iloc[0]
        price_end = k_slice["close"].iloc[-1]
        price_change = (price_end - price_start) / price_start * 100

        records.append({
            "period": label,
            "price_change_pct": round(price_change, 2),
            "avg_sentiment": round(s_slice["score"].mean(), 4) if not s_slice.empty else np.nan,
            "valid_news_count": len(s_slice),
        })

    return pd.DataFrame(records)


# ──────────────────────────────────────────────
# Full pipeline entry point
# ──────────────────────────────────────────────

def run_analysis_pipeline(
    sentiment_df: pd.DataFrame,
    klines_df: pd.DataFrame,
    window_minutes: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Full analysis pipeline.
    Returns (merged_df, correlations_df, period_df).
    Saves merged data to data/processed/merged_analysis.csv.
    """
    windows = aggregate_to_windows(sentiment_df, window_minutes)
    returns = compute_price_returns(klines_df)
    merged = merge_sentiment_price(windows, returns)

    merged.to_csv(MERGED_FILE, index=False)
    log.info("Merged analysis saved → %s", MERGED_FILE)

    correlations = compute_correlations(merged)
    period_perf = compute_period_performance(klines_df, sentiment_df)

    return merged, correlations, period_perf


def hypothesis_report(correlations_df: pd.DataFrame) -> str:
    """Generate a text summary for hypothesis validation."""
    lines = ["=" * 60, "HYPOTHESIS VALIDATION REPORT", "=" * 60]

    row_15 = correlations_df[correlations_df["lag_min"] == 15]
    if not row_15.empty:
        r15 = row_15.iloc[0]
        sig = "SIGNIFICANT ✓" if r15["significant"] else "NOT significant ✗"
        lines.append(
            f"\nHypothesis 1 (positive news → price rise within 15 min):"
            f"\n  T+15m: r={r15['r']:.4f}, p={r15['p_value']:.4f}  [{sig}]"
        )
        if r15["significant"]:
            direction = "positive correlation (supports H1)" if r15["r"] > 0 else "negative correlation (contradicts H1)"
            lines.append(f"  Direction: {direction}")

    lines.append("\nTime-lag Correlation Summary:")
    for _, row in correlations_df.iterrows():
        sig = "✓" if row["significant"] else "✗"
        lines.append(f"  T+{int(row['lag_min']):02d}m: r={row['r']:.4f}  p={row['p_value']:.4f}  n={int(row['n'])}  {sig}")

    best = correlations_df[correlations_df["significant"]].copy()
    if not best.empty:
        best_row = best.loc[best["r"].abs().idxmax()]
        lines.append(
            f"\nBest predictive lag: T+{int(best_row['lag_min'])}m  "
            f"(r={best_row['r']:.4f}, p={best_row['p_value']:.4f})"
        )
    else:
        lines.append("\nNo statistically significant lag found (p ≥ 0.05 for all).")

    lines.append("=" * 60)
    return "\n".join(lines)


def load_merged_analysis() -> pd.DataFrame:
    if not MERGED_FILE.exists():
        raise FileNotFoundError(f"Run run_analysis_pipeline() first. Expected: {MERGED_FILE}")
    df = pd.read_csv(MERGED_FILE, parse_dates=["window_start", "open_time"])
    df["window_start"] = pd.to_datetime(df["window_start"], utc=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df
