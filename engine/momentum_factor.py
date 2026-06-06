# engine/momentum_factor.py — Momentum factor scoring

import pandas as pd
import numpy as np


def score_momentum(close_matrix: pd.DataFrame) -> pd.Series:
    """
    Scores each stock on Momentum (0–100).
    Uses 12-1 momentum as primary signal (12-month return, skip last month).

    close_matrix: wide DataFrame — rows=dates, columns=symbols
    """
    if len(close_matrix) < 252:
        # Not enough history — return neutral
        return pd.Series(50.0, index=close_matrix.columns, name="momentum_score")

    latest        = close_matrix.iloc[-1]
    one_month_ago = close_matrix.iloc[-21]
    three_m_ago   = close_matrix.iloc[-63]
    six_m_ago     = close_matrix.iloc[-126]
    twelve_m_ago  = close_matrix.iloc[-252]

    # 12-1 momentum: avoids short-term reversal effect
    m12_1 = (one_month_ago / twelve_m_ago.replace(0, np.nan)) - 1
    m6    = (latest        / six_m_ago.replace(0, np.nan))    - 1
    m3    = (latest        / three_m_ago.replace(0, np.nan))  - 1

    # 52-week high proximity (breakout signal)
    high_52w      = close_matrix.tail(252).max()
    prox_52w      = latest / high_52w.replace(0, np.nan)

    def norm(s):
        s = s.replace([np.inf, -np.inf], np.nan)
        std = s.std()
        if std == 0 or pd.isna(std):
            return pd.Series(0.0, index=s.index)
        return (s - s.mean()) / std

    composite = (
        0.50 * norm(m12_1) +
        0.25 * norm(m6)    +
        0.15 * norm(m3)    +
        0.10 * norm(prox_52w)
    )

    return _scale(composite).rename("momentum_score")


def golden_cross_signal(close_matrix: pd.DataFrame) -> pd.Series:
    """
    Returns 1 for stocks where 50-day MA > 200-day MA (golden cross),
    -1 where 50-day MA < 200-day MA (death cross), 0 otherwise.
    """
    if len(close_matrix) < 200:
        return pd.Series(0, index=close_matrix.columns)

    ma50  = close_matrix.tail(250).rolling(50).mean().iloc[-1]
    ma200 = close_matrix.tail(250).rolling(200).mean().iloc[-1]

    signal = pd.Series(0, index=close_matrix.columns)
    signal[ma50 > ma200] = 1
    signal[ma50 < ma200] = -1
    return signal


def _scale(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(50.0, index=series.index)
    return (series - mn) / (mx - mn) * 100
