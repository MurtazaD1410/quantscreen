# pipeline/fundamentals.py — Download and extract fundamental data via yfinance

import os
import json
import warnings
import pandas as pd
import yfinance as yf
from config import FUND_DIR

warnings.filterwarnings("ignore", message="invalid value encountered in cast", category=RuntimeWarning)


def _cache_path(symbol: str) -> str:
    return os.path.join(FUND_DIR, f"{symbol}.json")


def download_fundamentals(symbol: str, force: bool = False) -> dict:
    """
    Downloads income statement, balance sheet, cash flow and key info
    for one symbol from yfinance. Saves to JSON cache.
    Returns the raw data dict.
    """
    os.makedirs(FUND_DIR, exist_ok=True)
    path = _cache_path(symbol)

    if not force and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            os.remove(path)  # corrupt cache — delete and re-download

    try:
        t = yf.Ticker(symbol)
        data = {
            "info":           t.info or {},
            "income_stmt":    _df_to_dict(t.quarterly_income_stmt),
            "balance_sheet":  _df_to_dict(t.quarterly_balance_sheet),
            "cashflow":       _df_to_dict(t.quarterly_cashflow),
            "major_holders":  _df_to_dict(t.major_holders),
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str)
        os.replace(tmp, path)  # atomic: no partial file left on crash
        return data
    except Exception as e:
        print(f"  WARN: fundamentals failed for {symbol} — {e}")
        return {}


def _df_to_dict(df) -> dict:
    if df is None or (hasattr(df, "empty") and df.empty):
        return {}
    # Timestamp column/index labels are not valid JSON keys — stringify both axes
    return df.rename(columns=str, index=str).to_dict()


def extract_metrics(symbol: str) -> dict:
    """
    Returns a flat dict of the key metrics we use for factor scoring.
    Downloads from yfinance if local cache is missing.
    """
    path = _cache_path(symbol)
    if not os.path.exists(path):
        download_fundamentals(symbol)
    if not os.path.exists(path):
        return {"symbol": symbol}

    with open(path) as f:
        data = json.load(f)

    info = data.get("info", {})

    # ── Income-statement derived metrics ──────────────────────────
    # Attempt to compute ROCE from raw statements if not in info
    roce = _compute_roce(data)

    return {
        "symbol":            symbol,
        "name":              info.get("longName", symbol),
        "sector":            info.get("sector", ""),
        "industry":          info.get("industry", ""),
        "market_cap":        info.get("marketCap"),          # in absolute currency
        "pe_ratio":          info.get("trailingPE"),
        "forward_pe":        info.get("forwardPE"),
        "pb_ratio":          info.get("priceToBook"),
        "ev_ebitda":         info.get("enterpriseToEbitda"),
        "ev_revenue":        info.get("enterpriseToRevenue"),
        "roe":               info.get("returnOnEquity"),      # decimal, e.g. 0.18
        "roa":               info.get("returnOnAssets"),
        "roce":              roce,
        "debt_to_equity":    info.get("debtToEquity"),
        "current_ratio":     info.get("currentRatio"),
        "quick_ratio":       info.get("quickRatio"),
        "gross_margins":     info.get("grossMargins"),
        "operating_margins": info.get("operatingMargins"),
        "profit_margins":    info.get("profitMargins"),
        "revenue_growth":    info.get("revenueGrowth"),
        "earnings_growth":   info.get("earningsGrowth"),
        "beta":              info.get("beta"),
        "dividend_yield":    info.get("dividendYield"),
        "payout_ratio":      info.get("payoutRatio"),
        "52w_high":          info.get("fiftyTwoWeekHigh"),
        "52w_low":           info.get("fiftyTwoWeekLow"),
        "employees":         info.get("fullTimeEmployees"),
        "shares_outstanding":info.get("sharesOutstanding"),
        "float_shares":      info.get("floatShares"),
        "insider_pct":       _parse_holders(data, 0),        # % held by insiders
        "institution_pct":   _parse_holders(data, 1),        # % held by institutions
    }


def _parse_holders(data: dict, row_idx: int):
    try:
        holders = data.get("major_holders", {})
        # major_holders is stored as {col: {row_str: value}}
        values = list(list(holders.values())[0].values())
        raw = str(values[row_idx]).replace("%", "").strip()
        return float(raw)
    except Exception:
        return None


def _compute_roce(data: dict):
    """
    ROCE = EBIT / Capital Employed
    Capital Employed = Total Assets - Current Liabilities
    """
    try:
        bs = data.get("balance_sheet", {})
        inc = data.get("income_stmt", {})

        # Get the most recent period (first column key)
        def latest(d):
            if not d:
                return {}
            return d[list(d.keys())[0]]

        bs_latest  = latest(bs)
        inc_latest = latest(inc)

        ebit = inc_latest.get("EBIT") or inc_latest.get("Operating Income")
        total_assets      = bs_latest.get("Total Assets")
        current_liab      = bs_latest.get("Current Liabilities") or bs_latest.get("Total Current Liabilities")

        if ebit and total_assets and current_liab:
            capital_employed = total_assets - current_liab
            if capital_employed > 0:
                return ebit / capital_employed
    except Exception:
        pass
    return None


def build_metrics_dataframe(symbols: list) -> pd.DataFrame:
    """
    Builds a DataFrame of fundamental metrics for all symbols.
    Rows = symbols, Columns = metrics.
    """
    records = [extract_metrics(s) for s in symbols]
    df = pd.DataFrame(records)
    if "symbol" in df.columns:
        df = df.set_index("symbol")
    # Coerce every column to numeric — yfinance occasionally returns strings
    # (e.g. "N/A", "Infinity") which cause object-dtype columns and break scoring.
    str_cols = {"name", "sector", "industry"}
    for col in df.columns:
        if col not in str_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace([float("inf"), float("-inf")], pd.NA, inplace=True)
    return df
