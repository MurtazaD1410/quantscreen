# config.py — Central settings for QuantScreen India

import os

# ── Paths ────────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
DATA_DIR        = os.path.join(BASE_DIR, "data")
RAW_DIR         = os.path.join(DATA_DIR, "raw")
PRICE_DIR       = os.path.join(DATA_DIR, "processed", "prices")
FUND_DIR        = os.path.join(DATA_DIR, "processed", "fundamentals")
CACHE_DIR       = os.path.join(DATA_DIR, "cache")

# ── NSE Index URLs ───────────────────────────────────────────────
NSE_INDEX_URLS = {
    "NIFTY 50":          "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTY 100":         "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTY 500":         "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "NIFTY Midcap 100":  "https://archives.nseindia.com/content/indices/ind_niftymidcap100list.csv",
    "NIFTY Smallcap 100":"https://archives.nseindia.com/content/indices/ind_niftysmallcap100list.csv",
}

# Full NSE equity list (all ~2000 listed EQ-series stocks)
NSE_ALL_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

# NSE benchmark ticker (used in backtesting)
NIFTY500_TICKER  = "^CRSLDX"   # NIFTY 500 on Yahoo Finance
NIFTY50_TICKER   = "^NSEI"

# ── Data settings ────────────────────────────────────────────────
YEARS_OF_HISTORY = 10           # How many years of price history to download
REQUEST_HEADERS  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ── Default strategy weights ─────────────────────────────────────
DEFAULT_WEIGHTS = {
    "value":          0.30,
    "quality":        0.30,
    "momentum":       0.25,
    "low_volatility": 0.15,
}

# ── Scoring parameters ───────────────────────────────────────────
SCORING = {
    "winsorize_lower": 0.05,    # Clip bottom 5% outliers
    "winsorize_upper": 0.95,    # Clip top 5% outliers
}

# ── Technical indicator defaults ─────────────────────────────────
TA = {
    "rsi_period":     14,
    "bb_period":      20,
    "bb_std":          2,
    "ma_short":       50,
    "ma_long":       200,
    "ema_period":     20,
    "adx_period":     14,
    "atr_period":     14,
    "roc_3m":         63,   # ~3 months in trading days
    "roc_6m":        126,
    "roc_12m":       252,
    "vol_window":    252,   # 1 year for volatility calc
    "zscore_window": 200,
}

# ── Backtest defaults ────────────────────────────────────────────
BACKTEST = {
    "default_years":        3,
    "rebalance_freq":       "Q",    # Q=Quarterly, M=Monthly, A=Annual
    "portfolio_size":       20,     # Top N stocks per period
    "transaction_cost_pct": 0.002,  # 0.2% round-trip (brokerage + impact)
    "initial_capital":      100,    # Index value starting at 100
}

# ── Filter defaults ──────────────────────────────────────────────
FILTERS = {
    "min_market_cap_cr": 500,   # Minimum ₹500 crore market cap
    "min_pe":            0,
    "max_pe":            100,
}
