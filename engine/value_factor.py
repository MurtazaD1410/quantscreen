# engine/value_factor.py — Value factor scoring

import pandas as pd
import numpy as np
from config import SCORING


def score_value(metrics: pd.DataFrame) -> pd.Series:
    """
    Scores each stock on the Value factor (0–100).
    Lower P/E, P/B, EV/EBITDA = higher score.
    Higher ROE (earnings yield proxy) = higher score.
    """
    lo, hi = SCORING["winsorize_lower"], SCORING["winsorize_upper"]
    scores  = pd.DataFrame(index=metrics.index)
    metrics = metrics.apply(lambda c: pd.to_numeric(c, errors="coerce").replace([np.inf, -np.inf], np.nan))

    # ── P/E ratio (lower = better → invert) ──────────────────────
    if "pe_ratio" in metrics.columns:
        pe = metrics["pe_ratio"]
        pe = pe.where((pe > 0) & (pe < 100))        # filter losses + extremes
        scores["pe"] = _norm_invert(pe, lo, hi)

    # ── P/B ratio (lower = better → invert) ──────────────────────
    if "pb_ratio" in metrics.columns:
        pb = metrics["pb_ratio"].where(metrics["pb_ratio"] > 0)
        scores["pb"] = _norm_invert(pb, lo, hi)

    # ── EV/EBITDA (lower = better → invert) ──────────────────────
    if "ev_ebitda" in metrics.columns:
        ev = metrics["ev_ebitda"].where(
            (metrics["ev_ebitda"] > 0) & (metrics["ev_ebitda"] < 50)
        )
        scores["ev"] = _norm_invert(ev, lo, hi)

    # ── ROE (higher = better) ─────────────────────────────────────
    if "roe" in metrics.columns:
        roe = metrics["roe"].where(metrics["roe"] > 0).clip(upper=0.5)
        scores["roe"] = _norm(roe, lo, hi)

    if scores.empty:
        return pd.Series(50.0, index=metrics.index, name="value_score")

    composite = scores.mean(axis=1)
    return _scale(composite).rename("value_score")


# ── helpers ──────────────────────────────────────────────────────

def _norm(series: pd.Series, lo: float, hi: float) -> pd.Series:
    """Winsorise then z-score normalise. Higher raw value → higher score."""
    clipped = series.clip(series.quantile(lo), series.quantile(hi))
    std = clipped.std()
    if std == 0:
        return pd.Series(0.0, index=series.index)
    return (clipped - clipped.mean()) / std


def _norm_invert(series: pd.Series, lo: float, hi: float) -> pd.Series:
    """Winsorise, z-score, then invert. Lower raw value → higher score."""
    return -_norm(series, lo, hi)


def _scale(series: pd.Series) -> pd.Series:
    """Scales a series to 0–100."""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(50.0, index=series.index)
    return (series - mn) / (mx - mn) * 100
