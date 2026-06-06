# engine/lowvol_factor.py — Low Volatility factor scoring

import pandas as pd
import numpy as np
from engine.indicators import rolling_volatility, max_drawdown, beta_vs_market
from pipeline.price_data import load_benchmark
from config import NIFTY50_TICKER


def score_lowvol(close_matrix: pd.DataFrame) -> pd.Series:
    """
    Scores each stock on Low Volatility (0–100).
    Lower annualised vol, lower beta, smaller max drawdown = higher score.

    close_matrix: wide DataFrame — rows=dates, columns=symbols
    """
    # Load benchmark returns once
    benchmark = load_benchmark(NIFTY50_TICKER)
    bm_returns = benchmark.pct_change().dropna() if not benchmark.empty else None

    rows = []
    for sym in close_matrix.columns:
        close = close_matrix[sym].dropna()
        if len(close) < 100:
            continue

        ann_vol  = rolling_volatility(close, window=252)
        max_dd   = max_drawdown(close, window=252)

        # Beta
        if bm_returns is not None:
            stock_ret = close.pct_change().dropna()
            aligned_bm = bm_returns.reindex(stock_ret.index).dropna()
            aligned_st = stock_ret.reindex(aligned_bm.index)
            beta = beta_vs_market(aligned_st, aligned_bm)
        else:
            beta = 1.0

        rows.append({"symbol": sym, "ann_vol": ann_vol, "max_dd": max_dd, "beta": beta})

    if not rows:
        return pd.Series(50.0, index=close_matrix.columns, name="lowvol_score")

    df = pd.DataFrame(rows).set_index("symbol")

    def norm_invert(series):
        """Lower raw value → higher score."""
        clipped = series.clip(series.quantile(0.05), series.quantile(0.95))
        std = clipped.std()
        if std == 0:
            return pd.Series(0.0, index=series.index)
        z = (clipped - clipped.mean()) / std
        return -z

    composite = (
        0.40 * norm_invert(df["ann_vol"]) +
        0.40 * norm_invert(df["beta"]) +
        0.20 * norm_invert(df["max_dd"])
    )

    # Reindex to full symbol list, fill gaps with neutral 50
    result = _scale(composite).rename("lowvol_score")
    return result.reindex(close_matrix.columns).fillna(50)


def _scale(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(50.0, index=series.index)
    return (series - mn) / (mx - mn) * 100
