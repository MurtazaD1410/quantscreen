# engine/indicators.py — Technical indicator calculations using the `ta` library

import numpy as np
import pandas as pd
import ta


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds all technical indicators to an OHLCV DataFrame.
    Expected columns: Open, High, Low, Close, Volume
    """
    df = df.copy()
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df.get("Volume", pd.Series(0, index=df.index))

    # ── Momentum ──────────────────────────────────────────────
    df["RSI_14"]     = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["ROC_63"]     = close.pct_change(63)  * 100   # 3-month
    df["ROC_126"]    = close.pct_change(126) * 100   # 6-month
    df["ROC_252"]    = close.pct_change(252) * 100   # 12-month

    # ── Trend ─────────────────────────────────────────────────
    df["SMA_50"]     = ta.trend.SMAIndicator(close, window=50).sma_indicator()
    df["SMA_200"]    = ta.trend.SMAIndicator(close, window=200).sma_indicator()
    df["EMA_20"]     = ta.trend.EMAIndicator(close, window=20).ema_indicator()

    macd_obj         = ta.trend.MACD(close)
    df["MACD"]       = macd_obj.macd()
    df["MACD_signal"]= macd_obj.macd_signal()

    adx_obj          = ta.trend.ADXIndicator(high, low, close, window=14)
    df["ADX_14"]     = adx_obj.adx()

    # ── Volatility ────────────────────────────────────────────
    bb               = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df["BB_upper"]   = bb.bollinger_hband()
    df["BB_lower"]   = bb.bollinger_lband()
    df["BB_mid"]     = bb.bollinger_mavg()
    df["BBP_20_2.0"] = bb.bollinger_pband()   # 0 = at lower band, 1 = upper band

    df["ATR_14"]     = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()

    return df


def rolling_volatility(close: pd.Series, window: int = 252) -> float:
    """Annualised volatility = std of daily log-returns × √252."""
    returns = close.pct_change().dropna()
    return float(returns.tail(window).std() * np.sqrt(252))


def zscore_from_ma(close: pd.Series, window: int = 200) -> float:
    """
    Z-score of latest price relative to its rolling mean.
    < -2 → significantly below MA → potential mean-reversion candidate.
    """
    ma  = close.rolling(window).mean()
    std = close.rolling(window).std()
    z   = (close - ma) / std
    val = z.iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def max_drawdown(close: pd.Series, window: int = 252) -> float:
    """
    Maximum peak-to-trough drawdown over the last `window` trading days.
    Returns a negative number, e.g. -0.30 = worst drawdown was 30%.
    """
    tail = close.tail(window)
    peak = tail.cummax()
    dd   = (tail - peak) / peak
    return float(dd.min())


def beta_vs_market(stock_returns: pd.Series, market_returns: pd.Series) -> float:
    """Computes Beta of a stock vs a market index."""
    aligned = pd.DataFrame({"s": stock_returns, "m": market_returns}).dropna()
    if len(aligned) < 30:
        return 1.0
    cov = aligned.cov().iloc[0, 1]
    var = aligned["m"].var()
    return float(cov / var) if var != 0 else 1.0
