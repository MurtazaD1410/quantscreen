# engine/quality_factor.py — Quality factor scoring including Piotroski F-Score

import pandas as pd
import numpy as np
from config import SCORING


# ── Piotroski F-Score ─────────────────────────────────────────────

def piotroski_score(metrics_row: pd.Series) -> int:
    """
    9-point financial health checklist (Piotroski, 2000).
    We compute the subset of signals available from yfinance data.
    Score 7–9 = strong quality, 0–2 = weak / distressed.
    """
    score = 0

    # Profitability
    roa = metrics_row.get("roa")
    if roa and roa > 0:
        score += 1                  # ROA positive

    op_margin = metrics_row.get("operating_margins")
    if op_margin and op_margin > 0:
        score += 1                  # Operating margin positive

    profit_margin = metrics_row.get("profit_margins")
    op_cf_proxy = metrics_row.get("roa")  # best we have without raw CF data
    if profit_margin and op_cf_proxy and op_cf_proxy > profit_margin:
        score += 1                  # Cash flow > net income (quality of earnings)

    rev_growth = metrics_row.get("revenue_growth")
    if rev_growth and rev_growth > 0:
        score += 1                  # Revenue growing

    # Leverage
    de = metrics_row.get("debt_to_equity")
    if de is not None and de < 1.0:
        score += 1                  # Debt/Equity below 1

    cr = metrics_row.get("current_ratio")
    if cr and cr > 1.0:
        score += 1                  # Current ratio > 1 (solvent short-term)

    # Efficiency
    gross_m = metrics_row.get("gross_margins")
    if gross_m and gross_m > 0.2:
        score += 1                  # Gross margin > 20%

    roe = metrics_row.get("roe")
    if roe and roe > 0.10:
        score += 1                  # ROE > 10%

    roce = metrics_row.get("roce")
    if roce and roce > 0.10:
        score += 1                  # ROCE > 10%

    return score


# ── Quality factor score ──────────────────────────────────────────

def score_quality(metrics: pd.DataFrame) -> pd.Series:
    """
    Scores each stock on Quality (0–100).
    Combines ROCE, ROE, debt, margins and Piotroski F-Score.
    """
    lo, hi = SCORING["winsorize_lower"], SCORING["winsorize_upper"]
    s = pd.DataFrame(index=metrics.index)

    # ROCE — higher is better
    roce_col = "roce" if "roce" in metrics.columns else None
    if roce_col:
        roce = metrics[roce_col].where(metrics[roce_col] > 0).clip(upper=0.5)
        s["roce"] = _norm(roce, lo, hi)

    # ROE — higher is better, cap at 50%
    if "roe" in metrics.columns:
        roe = metrics["roe"].clip(0, 0.5)
        s["roe"] = _norm(roe, lo, hi)

    # Debt/Equity — lower is better
    if "debt_to_equity" in metrics.columns:
        de = metrics["debt_to_equity"].clip(0, 5)
        s["de"] = -_norm(de, lo, hi)

    # Operating margin — higher is better
    if "operating_margins" in metrics.columns:
        om = metrics["operating_margins"].clip(0, 0.5)
        s["om"] = _norm(om, lo, hi)

    # Revenue growth — higher is better
    if "revenue_growth" in metrics.columns:
        rg = metrics["revenue_growth"].clip(-0.3, 0.5)
        s["rg"] = _norm(rg, lo, hi)

    # Piotroski F-Score (0–9 scaled to 0–1)
    piotro = metrics.apply(piotroski_score, axis=1) / 9.0
    s["piotro"] = _norm(piotro, 0, 1)

    if s.empty:
        return pd.Series(50.0, index=metrics.index, name="quality_score")

    composite = s.mean(axis=1)
    return _scale(composite).rename("quality_score")


# ── helpers ──────────────────────────────────────────────────────

def _norm(series, lo, hi):
    clipped = series.clip(series.quantile(lo) if lo > 0 else series.min(),
                          series.quantile(hi) if hi < 1 else series.max())
    std = clipped.std()
    if std == 0:
        return pd.Series(0.0, index=series.index)
    return (clipped - clipped.mean()) / std


def _scale(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(50.0, index=series.index)
    return (series - mn) / (mx - mn) * 100
