# engine/meanrev_factor.py — Mean Reversion signal scoring

import pandas as pd
import numpy as np
from engine.indicators import add_indicators, zscore_from_ma


def score_meanrev(
    close_matrix: pd.DataFrame,
    price_data: dict,
    rsi_threshold: float = 35.0,
    zscore_threshold: float = -1.5,
) -> pd.Series:
    """
    Scores stocks on Mean Reversion opportunity (0–100).
    Higher score = more oversold = stronger mean-reversion candidate.

    close_matrix : wide DataFrame of closing prices
    price_data   : dict {symbol: OHLCV DataFrame} (for indicator calc)
    """
    scores = {}

    for sym in close_matrix.columns:
        close = close_matrix[sym].dropna()
        if len(close) < 50:
            continue

        ohlcv = price_data.get(sym)
        if ohlcv is None or ohlcv.empty:
            continue

        try:
            df_ind = add_indicators(ohlcv.tail(300).copy())
            latest = df_ind.iloc[-1]

            # ── RSI signal ───────────────────────────────────────
            rsi = latest.get("RSI_14", 50)
            rsi_signal = max(0.0, rsi_threshold - rsi) / rsi_threshold

            # ── Bollinger Band signal ────────────────────────────
            bb_pct = latest.get("BBP_20_2.0")   # 0 = at lower band
            if bb_pct is not None and not np.isnan(bb_pct):
                bb_signal = max(0.0, 0.25 - float(bb_pct)) / 0.25
            else:
                bb_signal = 0.0

            # ── Z-score signal ───────────────────────────────────
            z = zscore_from_ma(close, window=200)
            zscore_signal = max(0.0, (-z - 1.0)) / 3.0   # z=-4 → 1.0, z=0 → 0

            scores[sym] = (
                0.40 * rsi_signal +
                0.30 * bb_signal  +
                0.30 * zscore_signal
            )
        except Exception:
            continue

    if not scores:
        return pd.Series(50.0, index=close_matrix.columns, name="meanrev_score")

    s = pd.Series(scores).rename("meanrev_score")
    mx = s.max()
    if mx > 0:
        s = (s / mx) * 100

    return s.reindex(close_matrix.columns).fillna(0)
