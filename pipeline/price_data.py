# pipeline/price_data.py — Download and load daily OHLCV price data via yfinance

import os
import time
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from config import PRICE_DIR, YEARS_OF_HISTORY

_BATCH_SIZE = 25   # tickers per yf.download() call


def _cache_path(symbol: str) -> str:
    return os.path.join(PRICE_DIR, f"{symbol}.csv")


def _is_stale(filepath: str, start: str = None) -> bool:
    """Returns True if file doesn't exist, wasn't updated today, or doesn't cover start date."""
    if not os.path.exists(filepath):
        return True
    modified = datetime.fromtimestamp(os.path.getmtime(filepath)).date()
    if modified < datetime.now().date():
        return True
    if start:
        try:
            first_row = pd.read_csv(filepath, index_col=0, nrows=1, parse_dates=True)
            earliest = pd.to_datetime(first_row.index[0]).date()
            required = datetime.strptime(start, "%Y-%m-%d").date()
            if earliest > required + timedelta(days=30):
                return True
        except Exception:
            pass
    return False


def _save_ticker(symbol: str, df: pd.DataFrame, path: str) -> bool:
    df = df.dropna(how="all")
    if df.empty:
        return False
    # yfinance returns tz-aware index (e.g. +05:30) — strip timezone, normalize to YYYY-MM-DD
    idx = pd.to_datetime(df.index)
    idx = idx.tz_convert(None) if idx.tz is not None else idx.tz_localize(None)
    df.index = idx.strftime("%Y-%m-%d")
    df.to_csv(path)
    return True


def _download_batch(batch: list, start: str) -> dict[str, pd.DataFrame]:
    """Batch-download via yf.download(); returns {symbol: DataFrame}."""
    raw = yf.download(
        tickers=batch,
        start=start,
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=False,  # single-threaded — prevents SSL storms under rate-limiting
    )
    if raw.empty:
        return {}

    results = {}
    if len(batch) == 1:
        # Single ticker: flatten (Price, Ticker) MultiIndex to flat columns
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        results[batch[0]] = raw
    else:
        for sym in batch:
            try:
                # yf.download with group_by="ticker" → MultiIndex (Ticker, Price) — level 0
                df = raw.xs(sym, axis=1, level=0)
                if not df.empty:
                    results[sym] = df
            except Exception:
                pass
    return results


def _process_batch(batch: list, start: str) -> list[str]:
    """Download one batch and save each ticker to CSV. Returns failed symbols."""
    failed = []
    try:
        frames = _download_batch(batch, start)
    except Exception as e:
        print(f"  WARN: batch download failed ({e}), retrying individually…")
        frames = {}

    for symbol in batch:
        path = _cache_path(symbol)
        if symbol in frames:
            if not _save_ticker(symbol, frames[symbol], path):
                failed.append(symbol)
        else:
            try:
                time.sleep(0.5)
                df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
                if not _save_ticker(symbol, df, path):
                    failed.append(symbol)
            except Exception as e2:
                failed.append(symbol)
                print(f"  WARN: {symbol} failed — {e2}")
    return failed


def download_price_history(symbols: list, years: int = YEARS_OF_HISTORY, force: bool = False):
    """
    Downloads daily OHLCV for each symbol and saves as individual CSVs.
    Skips symbols already downloaded today with sufficient history (unless force=True).
    Returns list of symbols that failed.
    """
    os.makedirs(PRICE_DIR, exist_ok=True)
    start = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")

    to_download = [s for s in symbols if force or _is_stale(_cache_path(s), start)]
    if not to_download:
        return []

    total   = len(to_download)
    batches = [to_download[i : i + _BATCH_SIZE] for i in range(0, total, _BATCH_SIZE)]
    failed  = []
    done    = 0

    for batch in batches:
        batch_failed = _process_batch(batch, start)
        failed.extend(batch_failed)
        done += len(batch)
        print(f"  [{min(done, total)}/{total}] price data downloaded…")

    return failed


def load_price(symbol: str) -> pd.DataFrame:
    """Loads a single stock's OHLCV DataFrame from local CSV."""
    path = _cache_path(symbol)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No price data for {symbol}. Run download_price_history() first.")
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, format="mixed")
    return df


def load_close_matrix(symbols: list) -> pd.DataFrame:
    """
    Returns a wide DataFrame of adjusted closing prices.
    Rows = trading dates, Columns = symbols.
    Missing symbols are silently skipped.
    """
    closes = {}
    for sym in symbols:
        try:
            closes[sym] = load_price(sym)["Close"]
        except Exception:
            pass
    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes).sort_index()


def load_benchmark(ticker: str = "^NSEI", years: int = YEARS_OF_HISTORY) -> pd.Series:
    """Downloads and returns the NIFTY 50 (or any benchmark) closing prices."""
    start = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    try:
        df = yf.Ticker(ticker).history(start=start, auto_adjust=True)
        idx = pd.to_datetime(df.index)
        df.index = idx.tz_convert(None) if idx.tz is not None else idx.tz_localize(None)
        return df["Close"].rename(ticker)
    except Exception as e:
        print(f"WARN: Could not load benchmark {ticker}: {e}")
        return pd.Series(dtype=float)


def fetch_price(symbol: str) -> pd.DataFrame:
    """
    Fetches a single stock's OHLCV directly from yfinance (no local CSV).
    Uses yf.download() which is more reliable on cloud IPs than Ticker.history().
    Raises FileNotFoundError if yfinance returns no data.
    """
    start = (datetime.now() - timedelta(days=YEARS_OF_HISTORY * 365)).strftime("%Y-%m-%d")
    raw = yf.download(symbol, start=start, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise FileNotFoundError(f"No price data returned for {symbol}")
    idx = pd.to_datetime(raw.index)
    raw.index = idx.tz_convert(None) if idx.tz is not None else idx.tz_localize(None)
    # yf.download for a single ticker returns flat columns (Open, High, Low, Close, Volume)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def fetch_close_matrix(symbols: list) -> pd.DataFrame:
    """
    Fetches adjusted close prices for all symbols directly from yfinance (no CSVs).
    Downloads in batches of _BATCH_SIZE to avoid rate-limiting.
    Returns a wide DataFrame: rows = dates, columns = symbols.
    Symbols that fail are silently skipped.
    """
    start = (datetime.now() - timedelta(days=YEARS_OF_HISTORY * 365)).strftime("%Y-%m-%d")
    closes = {}
    batches = [symbols[i: i + _BATCH_SIZE] for i in range(0, len(symbols), _BATCH_SIZE)]

    for batch in batches:
        frames = _download_batch(batch, start)
        for sym, df in frames.items():
            if df.empty:
                continue
            idx = pd.to_datetime(df.index)
            df.index = idx.tz_convert(None) if idx.tz is not None else idx.tz_localize(None)
            closes[sym] = df["Close"]

    return pd.DataFrame(closes).sort_index() if closes else pd.DataFrame()
