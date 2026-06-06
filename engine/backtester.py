# engine/backtester.py — Historical strategy backtesting engine

import numpy as np
import pandas as pd
from datetime import datetime
from pipeline.price_data import load_close_matrix, load_benchmark
from engine.value_factor    import score_value
from engine.quality_factor  import score_quality
from engine.momentum_factor import score_momentum
from engine.lowvol_factor   import score_lowvol
from engine.composite       import compute_composite
from config import BACKTEST, NIFTY500_TICKER


def run_backtest(
    symbols:          list,
    metrics:          pd.DataFrame,
    weights:          dict,
    years:            int   = BACKTEST["default_years"],
    rebalance_freq:   str   = BACKTEST["rebalance_freq"],
    portfolio_size:   int   = BACKTEST["portfolio_size"],
    transaction_cost: float = BACKTEST["transaction_cost_pct"],
) -> dict:
    """
    Simulates the strategy on historical data and returns performance metrics.

    Parameters
    ----------
    symbols         : list of yf symbols to screen from
    metrics         : fundamentals DataFrame (used for value + quality)
    weights         : factor weights dict e.g. {"value": 0.3, "momentum": 0.7}
    years           : how many years of history to test
    rebalance_freq  : 'M' monthly, 'Q' quarterly, 'A' annual
    portfolio_size  : how many stocks to hold per period
    transaction_cost: round-trip cost as a fraction (e.g. 0.002 = 0.2%)

    Returns
    -------
    dict with keys:
        equity_curve   : pd.Series  (indexed by date, portfolio value starting at 100)
        benchmark_curve: pd.Series  (NIFTY 500 starting at 100)
        cagr           : float
        benchmark_cagr : float
        sharpe         : float
        sortino        : float
        max_drawdown   : float
        alpha          : float
        total_return   : float
        rebalance_log  : list of dicts (date, selected stocks, scores)
    """

    # ── 1. Load price data ────────────────────────────────────────
    close_matrix = load_close_matrix(symbols)
    if close_matrix.empty:
        raise ValueError("No price data available. Run the data pipeline first.")

    close_matrix = close_matrix.dropna(how="all", axis=1)
    close_matrix = close_matrix.sort_index()

    # Trim to desired years
    cutoff = close_matrix.index[-1] - pd.DateOffset(years=years)
    close_matrix = close_matrix[close_matrix.index >= cutoff]

    # ── 2. Build rebalancing dates ────────────────────────────────
    rebal_dates = pd.date_range(
        start=close_matrix.index[min(252, len(close_matrix) - 1)],
        end=close_matrix.index[-1],
        freq=rebalance_freq,
    )
    # Snap each date to the nearest actual trading day in our data
    rebal_dates = [_nearest_date(close_matrix.index, d) for d in rebal_dates]
    rebal_dates = sorted(set(rebal_dates))

    if len(rebal_dates) < 2:
        raise ValueError("Not enough history for the chosen backtest period and frequency.")

    # ── 3. Simulate portfolio ─────────────────────────────────────
    portfolio_value = 100.0
    equity_curve    = {}
    prev_holdings   = []
    rebalance_log   = []

    for i, rebal_date in enumerate(rebal_dates[:-1]):
        next_date = rebal_dates[i + 1]

        # Data available UP TO this rebalancing date (point-in-time)
        hist = close_matrix.loc[:rebal_date]

        if len(hist) < 63:
            continue

        # ── Score stocks using historical window ─────────────────
        available_syms = [s for s in symbols if s in hist.columns
                          and hist[s].dropna().shape[0] > 63]

        if len(available_syms) < portfolio_size:
            continue

        selected = _select_stocks(
            hist[available_syms], metrics, weights, portfolio_size
        )

        if not selected:
            continue

        # ── Compute period return ────────────────────────────────
        period_data   = close_matrix.loc[rebal_date:next_date, selected]
        period_return = _equal_weight_return(period_data)

        # Apply transaction cost for stocks that changed
        turnover = len(set(selected) - set(prev_holdings)) / max(len(selected), 1)
        cost     = turnover * transaction_cost
        period_return -= cost

        # Update portfolio value
        portfolio_value *= (1 + period_return)
        equity_curve[next_date] = round(portfolio_value, 4)

        rebalance_log.append({
            "date":    rebal_date.strftime("%Y-%m-%d"),
            "stocks":  selected,
            "return":  round(period_return * 100, 2),
        })
        prev_holdings = selected

    if not equity_curve:
        raise ValueError("Backtest produced no results. Try a longer date range.")

    # Extend equity curve from last rebalance date to latest price date
    # so the strategy line runs to the same endpoint as the benchmark.
    if prev_holdings:
        last_rebal  = max(equity_curve.keys())
        latest_date = close_matrix.index[-1]
        if latest_date > last_rebal:
            tail_data   = close_matrix.loc[last_rebal:latest_date, prev_holdings]
            tail_ret    = _equal_weight_return(tail_data)
            equity_curve[latest_date] = round(portfolio_value * (1 + tail_ret), 4)

    equity_series = pd.Series(equity_curve)
    equity_series = pd.concat([pd.Series({close_matrix.index[252]: 100.0}), equity_series])

    # ── 4. Benchmark curve ────────────────────────────────────────
    bm_raw   = load_benchmark(NIFTY500_TICKER, years=years + 1)
    bm_curve = _normalise_to_100(bm_raw, equity_series.index[0])

    # ── 5. Performance metrics ────────────────────────────────────
    metrics_out = _compute_metrics(equity_series, bm_curve)
    metrics_out.update({
        "equity_curve":    equity_series,
        "benchmark_curve": bm_curve,
        "rebalance_log":   rebalance_log,
    })
    return metrics_out


# ── helpers ──────────────────────────────────────────────────────

def _select_stocks(
    hist: pd.DataFrame,
    metrics: pd.DataFrame,
    weights: dict,
    n: int,
) -> list:
    """Scores and selects top-N stocks using historical price data."""
    syms = hist.columns.tolist()

    val_s  = score_value(metrics.reindex(syms))    if weights.get("value", 0)          > 0 else None
    qual_s = score_quality(metrics.reindex(syms))  if weights.get("quality", 0)        > 0 else None
    mom_s  = score_momentum(hist)                  if weights.get("momentum", 0)       > 0 else None
    lv_s   = score_lowvol(hist)                    if weights.get("low_volatility", 0) > 0 else None

    result = compute_composite(
        symbols=syms,
        weights=weights,
        value_scores=val_s,
        quality_scores=qual_s,
        momentum_scores=mom_s,
        lowvol_scores=lv_s,
    )

    return result.head(n).index.tolist()


def _equal_weight_return(period_data: pd.DataFrame) -> float:
    """Equal-weight buy-and-hold return for a set of stocks over a period."""
    if period_data.empty:
        return 0.0
    returns = []
    for col in period_data.columns:
        s = period_data[col].dropna()
        if len(s) < 2:
            continue
        ret = (s.iloc[-1] / s.iloc[0]) - 1
        if not np.isnan(ret) and not np.isinf(ret):
            returns.append(ret)
    return float(np.mean(returns)) if returns else 0.0


def _normalise_to_100(series: pd.Series, start_date) -> pd.Series:
    """Rebases a price series to 100 at start_date."""
    if series.empty:
        return pd.Series(dtype=float)
    aligned = series[series.index >= start_date]
    if aligned.empty:
        return pd.Series(dtype=float)
    return (aligned / aligned.iloc[0]) * 100


def _nearest_date(index: pd.DatetimeIndex, target) -> pd.Timestamp:
    """Finds the closest date in `index` to `target`."""
    target = pd.Timestamp(target)
    diffs  = abs(index - target)
    return index[diffs.argmin()]


def _compute_metrics(equity: pd.Series, benchmark: pd.Series) -> dict:
    """Computes CAGR, Sharpe, Sortino, Max Drawdown and Alpha."""

    def cagr(series):
        if len(series) < 2 or series.iloc[0] == 0:
            return 0.0
        years = (series.index[-1] - series.index[0]).days / 365.25
        return float((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1) if years > 0 else 0.0

    def sharpe(series, rf=0.065):   # 6.5% risk-free (Indian T-bill)
        rets = series.pct_change().dropna()
        if rets.std() == 0:
            return 0.0
        ann_ret = rets.mean() * 252
        ann_std = rets.std()  * np.sqrt(252)
        return float((ann_ret - rf) / ann_std)

    def sortino(series, rf=0.065):
        rets = series.pct_change().dropna()
        neg  = rets[rets < 0]
        if neg.std() == 0:
            return 0.0
        ann_ret      = rets.mean() * 252
        downside_std = neg.std() * np.sqrt(252)
        return float((ann_ret - rf) / downside_std)

    def max_dd(series):
        peak = series.cummax()
        dd   = (series - peak) / peak
        return float(dd.min())

    port_cagr = cagr(equity)
    bm_cagr   = cagr(benchmark) if not benchmark.empty else 0.0

    return {
        "cagr":            round(port_cagr * 100, 2),
        "benchmark_cagr":  round(bm_cagr   * 100, 2),
        "total_return":    round((equity.iloc[-1] / equity.iloc[0] - 1) * 100, 2) if len(equity) > 1 else 0,
        "sharpe":          round(sharpe(equity),  2),
        "sortino":         round(sortino(equity), 2),
        "max_drawdown":    round(max_dd(equity)   * 100, 2),
        "alpha":           round((port_cagr - bm_cagr) * 100, 2),
    }
