"""
Visualization module — PRD §4.5 dashboard layout.

Produces output/dashboard.png (1920×1080) and per-timeframe PNGs.
Color palette matches the Crypto Sentiment Dashboard HTML mockup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Color palette (matches HTML --css variables) ──────────────
P = {
    "bg":       "#0b0e11",
    "panel":    "#1e2026",
    "panel2":   "#2b2f36",
    "border":   "#373d47",
    "accent":   "#f0b90b",
    "up":       "#0ecb81",
    "down":     "#f6465d",
    "neutral":  "#848e9c",
    "text":     "#eaecef",
    "text2":    "#848e9c",
    "text3":    "#5e6673",
    "purple":   "#a78bfa",
    "purple_t": "#a78bfa44",
}

plt.rcParams.update({
    "figure.facecolor":  P["bg"],
    "axes.facecolor":    P["panel"],
    "axes.edgecolor":    P["border"],
    "axes.labelcolor":   P["text2"],
    "xtick.color":       P["text3"],
    "ytick.color":       P["text3"],
    "text.color":        P["text"],
    "grid.color":        P["border"],
    "grid.alpha":        0.5,
    "font.family":       "monospace",
    "font.size":         10,
})


# ──────────────────────────────────────────────
# Zone A — Price Header
# ──────────────────────────────────────────────

def draw_zone_a(ax: plt.Axes, ticker: dict, market: dict) -> None:
    ax.axis("off")
    price = ticker.get("price", 0)
    chg = ticker.get("change_pct_24h", 0)
    high = ticker.get("high_24h", 0)
    low = ticker.get("low_24h", 0)
    mcap = market.get("market_cap_usd", 0) or 0
    ath = market.get("ath_usd", 0) or 0

    chg_color = P["up"] if chg >= 0 else P["down"]
    chg_arrow = "▲" if chg >= 0 else "▼"

    ax.text(0.0, 0.85, "₿  Bitcoin   BTC", fontsize=14, color=P["text"], va="top", transform=ax.transAxes)
    ax.text(0.0, 0.45, f"${price:,.2f}", fontsize=32, color=P["text"], va="top",
            fontweight="bold", transform=ax.transAxes)
    ax.text(0.38, 0.55, f"{chg_arrow} {abs(chg):.2f}%  24h",
            fontsize=13, color=chg_color, va="top", transform=ax.transAxes)

    col2_x = 0.60
    items = [
        ("24h High",      f"${high:,.2f}",                P["up"]),
        ("24h Low",       f"${low:,.2f}",                 P["down"]),
        ("Market Cap",    f"${mcap/1e12:.2f}T" if mcap else "—", P["text"]),
        ("ATH",           f"${ath:,.0f}" if ath else "—", P["accent"]),
    ]
    for i, (label, val, color) in enumerate(items):
        x = col2_x + (i % 2) * 0.20
        y = 0.85 - (i // 2) * 0.42
        ax.text(x, y, label, fontsize=8, color=P["text2"], va="top", transform=ax.transAxes)
        ax.text(x, y - 0.28, val, fontsize=12, color=color, va="top",
                fontweight="bold", transform=ax.transAxes)

    ax.set_facecolor(P["panel"])


# ──────────────────────────────────────────────
# Zone B — Dual-axis timeseries chart
# ──────────────────────────────────────────────

TIMEFRAMES = {
    "1D":  pd.Timedelta(days=1),
    "7D":  pd.Timedelta(days=7),
    "1M":  pd.Timedelta(days=30),
    "3M":  pd.Timedelta(days=90),
}


def draw_zone_b(
    ax: plt.Axes,
    klines_df: pd.DataFrame,
    windows_df: pd.DataFrame,
    tf_label: str = "7D",
) -> None:
    delta = TIMEFRAMES.get(tf_label, pd.Timedelta(days=7))
    cutoff = pd.Timestamp.now(tz="UTC") - delta

    price_data = klines_df[klines_df["open_time"] >= cutoff].copy()
    sent_data  = windows_df[windows_df["window_start"] >= cutoff].copy() if not windows_df.empty else pd.DataFrame()

    ax.set_facecolor(P["panel"])
    ax.grid(True, axis="y", linewidth=0.4)

    if price_data.empty:
        ax.text(0.5, 0.5, "No price data", ha="center", va="center",
                color=P["text2"], transform=ax.transAxes)
        return

    ax.plot(price_data["open_time"], price_data["close"],
            color=P["accent"], linewidth=1.2, label="BTC/USDT")
    ax.set_ylabel("BTC/USDT", color=P["accent"], fontsize=9)
    ax.tick_params(axis="y", labelcolor=P["accent"])

    if not sent_data.empty:
        ax2 = ax.twinx()
        ax2.set_facecolor("none")
        ax2.plot(sent_data["window_start"], sent_data["window_score"],
                 color=P["purple"], linewidth=0.9, alpha=0.8, label="Sentiment")
        ax2.fill_between(sent_data["window_start"], sent_data["window_score"],
                         0, color=P["purple"], alpha=0.15)
        ax2.set_ylim(-1.1, 1.1)
        ax2.set_ylabel("Sentiment [-1,+1]", color=P["purple"], fontsize=9)
        ax2.tick_params(axis="y", labelcolor=P["purple"])
        ax2.axhline(0, color=P["neutral"], linewidth=0.5, linestyle="--")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M"))
    ax.tick_params(axis="x", labelsize=8)
    ax.set_title(f"BTC Price & Sentiment  [{tf_label}]", color=P["text2"], fontsize=10, pad=6)


def save_timeframe_charts(
    klines_df: pd.DataFrame,
    windows_df: pd.DataFrame,
) -> None:
    """Save 1D/7D/1M/3M individual chart PNGs to output/."""
    for tf in TIMEFRAMES:
        fig, ax = plt.subplots(figsize=(14, 4), facecolor=P["bg"])
        draw_zone_b(ax, klines_df, windows_df, tf_label=tf)
        out = OUTPUT_DIR / f"chart_{tf}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=150, facecolor=P["bg"])
        plt.close(fig)
        log.info("Saved %s", out)


# ──────────────────────────────────────────────
# Zone C — Semicircle Sentiment Gauge
# ──────────────────────────────────────────────

def draw_zone_c(
    ax: plt.Axes,
    current_score: float,
    recent_headlines: list[dict] | None = None,
) -> None:
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-0.4, 1.3)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor(P["panel"])

    # Gradient arc segments
    n_segs = 180
    for i in range(n_segs):
        theta = np.pi * (1 - i / n_segs)
        theta_next = np.pi * (1 - (i + 1) / n_segs)
        t = i / (n_segs - 1)
        if t < 0.5:
            r, g, b = 0.965, 0.275, 0.365  # down red
            r2, g2, b2 = 0.514, 0.557, 0.612  # neutral gray
            tf = t * 2
        else:
            r, g, b = 0.514, 0.557, 0.612
            r2, g2, b2 = 0.055, 0.796, 0.506  # up green
            tf = (t - 0.5) * 2
        color = (r + (r2 - r)*tf, g + (g2 - g)*tf, b + (b2 - b)*tf)
        wedge = mpatches.Wedge(
            (0, 0), 1.0, np.degrees(theta_next), np.degrees(theta),
            width=0.25, color=color,
        )
        ax.add_patch(wedge)

    # Needle
    needle_angle = np.pi * (1 - (current_score + 1) / 2)
    nx = 0.75 * np.cos(needle_angle)
    ny = 0.75 * np.sin(needle_angle)
    ax.annotate("", xy=(nx, ny), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=P["text"], lw=2))
    ax.plot(0, 0, "o", color=P["text"], markersize=6)

    score_color = P["up"] if current_score > 0.05 else (P["down"] if current_score < -0.05 else P["neutral"])
    ax.text(0, -0.15, f"{current_score:+.2f}", ha="center", fontsize=18,
            color=score_color, fontweight="bold")
    ax.text(0, -0.32, "Avg Sentiment Score", ha="center", fontsize=8, color=P["text2"])

    ax.text(-1.05, 0.05, "BEARISH", fontsize=7, color=P["down"])
    ax.text(0.75, 0.05, "BULLISH", fontsize=7, color=P["up"])

    ax.set_title("SENTIMENT GAUGE", color=P["text2"], fontsize=9, pad=4)

    # Recent headlines
    if recent_headlines:
        y_pos = -0.38
        for item in recent_headlines[:5]:
            score = item.get("score", 0)
            title = item.get("title", "")[:52]
            color = P["up"] if score > 0 else (P["down"] if score < 0 else P["neutral"])
            ax.text(-1.25, y_pos, f"{score:+.2f}  {title}", fontsize=6.5,
                    color=color, va="top", clip_on=True)
            y_pos -= 0.18


# ──────────────────────────────────────────────
# Zone D — Period Performance Table
# ──────────────────────────────────────────────

def draw_zone_d(ax: plt.Axes, period_df: pd.DataFrame) -> None:
    ax.axis("off")
    ax.set_facecolor(P["panel"])
    ax.set_title("PERIOD PERFORMANCE", color=P["text2"], fontsize=9, pad=4)

    if period_df.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", color=P["text2"])
        return

    col_labels = ["Period", "Price Δ%", "Avg Sentiment", "Valid News"]
    rows = []
    cell_colors = []

    for _, row in period_df.iterrows():
        chg = row["price_change_pct"]
        sent = row["avg_sentiment"]
        rows.append([
            row["period"],
            f"{chg:+.2f}%" if not np.isnan(chg) else "—",
            f"{sent:+.4f}" if not np.isnan(sent) else "—",
            str(int(row["valid_news_count"])),
        ])
        chg_bg = "#1a3d2b" if (not np.isnan(chg) and chg >= 0) else "#3d1a1d"
        cell_colors.append([P["panel2"], chg_bg, P["panel2"], P["panel2"]])

    table = ax.table(
        cellText=rows,
        colLabels=col_labels,
        cellLoc="center",
        loc="center",
        bbox=[0, 0, 1, 1],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)

    for (r, c), cell in table.get_celld().items():
        cell.set_facecolor(P["panel2"] if r == 0 else cell_colors[r-1][c] if r <= len(cell_colors) else P["panel2"])
        cell.set_edgecolor(P["border"])
        cell.set_text_props(color=P["text"])


# ──────────────────────────────────────────────
# Zone E — Scatter plots
# ──────────────────────────────────────────────

def draw_zone_e(ax: plt.Axes, merged_df: pd.DataFrame, lag_min: int = 15) -> None:
    col = f"return_{lag_min}m"
    ax.set_facecolor(P["panel"])
    ax.grid(True, linewidth=0.4)

    subset = merged_df[["window_score", col]].dropna() if col in merged_df.columns else pd.DataFrame()
    if subset.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center",
                color=P["text2"], transform=ax.transAxes)
        ax.set_title(f"Sentiment vs Return T+{lag_min}m", color=P["text2"], fontsize=9)
        return

    x = subset["window_score"].values
    y = subset[col].values

    colors = [P["up"] if yi >= 0 else P["down"] for yi in y]
    ax.scatter(x, y, c=colors, alpha=0.4, s=8, linewidths=0)

    slope, intercept, r, p, _ = stats.linregress(x, y)
    x_line = np.linspace(x.min(), x.max(), 100)
    y_line = slope * x_line + intercept
    ax.plot(x_line, y_line, color=P["accent"], linewidth=1.5)

    n = len(x)
    se = np.std(y - (slope * x + intercept))
    ci = 1.96 * se * np.sqrt(1/n + (x_line - x.mean())**2 / np.sum((x - x.mean())**2))
    ax.fill_between(x_line, y_line - ci, y_line + ci, color=P["accent"], alpha=0.12)

    sig_label = f"r={r:.3f}, p={p:.4f}"
    ax.set_title(f"Sentiment vs T+{lag_min}m Return  [{sig_label}]", color=P["text2"], fontsize=9)
    ax.set_xlabel("Sentiment Score", fontsize=8)
    ax.set_ylabel("Return (%)", fontsize=8)
    ax.axhline(0, color=P["neutral"], linewidth=0.5, linestyle="--")
    ax.axvline(0, color=P["neutral"], linewidth=0.5, linestyle="--")


# ──────────────────────────────────────────────
# Zone F — Correlation Bar Chart
# ──────────────────────────────────────────────

def draw_zone_f(ax: plt.Axes, corr_df: pd.DataFrame) -> None:
    ax.set_facecolor(P["panel"])
    ax.grid(True, axis="y", linewidth=0.4)
    ax.set_title("TIME-LAG CORRELATION (Pearson r)", color=P["text2"], fontsize=9)

    if corr_df.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center",
                color=P["text2"], transform=ax.transAxes)
        return

    labels = [f"T+{int(row['lag_min'])}m" for _, row in corr_df.iterrows()]
    r_vals = corr_df["r"].fillna(0).tolist()
    sigs = corr_df["significant"].tolist()

    x = np.arange(len(labels))
    for i, (r, sig) in enumerate(zip(r_vals, sigs)):
        color = P["up"] if r >= 0 else P["down"]
        alpha = 1.0 if sig else 0.4
        ax.bar(x[i], r, color=color, alpha=alpha, width=0.5, edgecolor=P["border"], linewidth=0.5)
        ax.text(x[i], r + (0.005 if r >= 0 else -0.012), f"{r:.3f}",
                ha="center", va="bottom" if r >= 0 else "top",
                fontsize=9, color=P["text"])
        if sig:
            ax.text(x[i], r + (0.018 if r >= 0 else -0.025), "✓",
                    ha="center", fontsize=8, color=P["accent"])

    ax.axhline(0, color=P["neutral"], linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Pearson r", fontsize=8)
    ax.set_ylim(
        min(-0.1, (corr_df["r"].min() or 0) - 0.05),
        max(0.1, (corr_df["r"].max() or 0) + 0.05),
    )

    sig_patch = mpatches.Patch(color=P["accent"], alpha=0.8, label="p < 0.05 ✓")
    ns_patch  = mpatches.Patch(color=P["neutral"], alpha=0.4, label="p ≥ 0.05")
    ax.legend(handles=[sig_patch, ns_patch], fontsize=8, facecolor=P["panel2"],
              edgecolor=P["border"], labelcolor=P["text"])


# ──────────────────────────────────────────────
# Full Dashboard
# ──────────────────────────────────────────────

def build_dashboard(
    klines_df: pd.DataFrame,
    windows_df: pd.DataFrame,
    merged_df: pd.DataFrame,
    corr_df: pd.DataFrame,
    period_df: pd.DataFrame,
    ticker: dict | None = None,
    market: dict | None = None,
    recent_headlines: list[dict] | None = None,
    tf_label: str = "7D",
    out_path: Optional[Path] = None,
) -> Path:
    """Render the full 6-zone dashboard and save to output/dashboard.png."""
    if ticker is None:
        ticker = {}
    if market is None:
        market = {}

    fig = plt.figure(figsize=(19.2, 10.8), facecolor=P["bg"])
    gs = gridspec.GridSpec(
        4, 3,
        figure=fig,
        hspace=0.38, wspace=0.28,
        left=0.05, right=0.97,
        top=0.94, bottom=0.05,
        height_ratios=[1, 3, 2, 2],
    )

    # Zone A — price header (top row, full width)
    ax_a = fig.add_subplot(gs[0, :])
    draw_zone_a(ax_a, ticker, market)

    # Zone B — timeseries chart (rows 1-2, left 2/3)
    ax_b = fig.add_subplot(gs[1, :2])
    draw_zone_b(ax_b, klines_df, windows_df, tf_label=tf_label)

    # Zone C — sentiment gauge (rows 1-2, right 1/3)
    current_score = 0.0
    if not windows_df.empty:
        recent_1h = windows_df[
            windows_df["window_start"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=1)
        ]
        if not recent_1h.empty:
            current_score = recent_1h["window_score"].mean()

    ax_c = fig.add_subplot(gs[1, 2])
    draw_zone_c(ax_c, current_score, recent_headlines)

    # Zone D — period table (row 2, left col)
    ax_d = fig.add_subplot(gs[2, 0])
    draw_zone_d(ax_d, period_df)

    # Zone E — scatter T+15m (row 2, mid col)
    ax_e1 = fig.add_subplot(gs[2, 1])
    draw_zone_e(ax_e1, merged_df, lag_min=15)

    # Zone E — scatter T+60m (row 2, right col)
    ax_e2 = fig.add_subplot(gs[2, 2])
    draw_zone_e(ax_e2, merged_df, lag_min=60)

    # Zone F — correlation bar (row 3, full width)
    ax_f = fig.add_subplot(gs[3, :])
    draw_zone_f(ax_f, corr_df)

    fig.suptitle("CryptoSentiment — Bitcoin Sentiment Analysis Dashboard",
                 fontsize=14, color=P["accent"], y=0.98)

    if out_path is None:
        out_path = OUTPUT_DIR / "dashboard.png"

    fig.savefig(out_path, dpi=100, facecolor=P["bg"], bbox_inches="tight")
    plt.close(fig)
    log.info("Dashboard saved → %s", out_path)
    return out_path


def run_full_visualization(
    klines_df: pd.DataFrame,
    windows_df: pd.DataFrame,
    merged_df: pd.DataFrame,
    corr_df: pd.DataFrame,
    period_df: pd.DataFrame,
    ticker: dict | None = None,
    market: dict | None = None,
    recent_headlines: list[dict] | None = None,
) -> None:
    """Save dashboard.png + per-timeframe chart PNGs."""
    for tf in TIMEFRAMES:
        build_dashboard(
            klines_df, windows_df, merged_df, corr_df, period_df,
            ticker=ticker, market=market, recent_headlines=recent_headlines,
            tf_label=tf, out_path=OUTPUT_DIR / f"dashboard_{tf}.png",
        )
    save_timeframe_charts(klines_df, windows_df)
    log.info("All visualizations complete.")
