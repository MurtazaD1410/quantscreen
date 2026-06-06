# pipeline/universe.py — Fetch NIFTY index constituent lists from NSE

import os
import pandas as pd
import requests
from config import NSE_INDEX_URLS, NSE_ALL_EQUITY_URL, RAW_DIR, REQUEST_HEADERS


def get_index_stocks(index_name: str = "NIFTY 500") -> pd.DataFrame:
    """
    Downloads the official NSE index constituent list.
    Returns a DataFrame with columns:
        Symbol, Company Name, Industry, Series, ISIN Code, yf_symbol
    Falls back to a cached local copy if NSE is unreachable.
    Pass "All Indices" to get the deduplicated union of all known indices.
    """
    index_name_normal = index_name.strip().lower()

    if index_name_normal == "all indices":
        frames = [get_index_stocks(idx) for idx in NSE_INDEX_URLS]
        combined = pd.concat(frames, ignore_index=True)
        return combined.drop_duplicates(subset=["yf_symbol"]).reset_index(drop=True)

    if index_name_normal == "nse all":
        return _get_all_nse_stocks()

    os.makedirs(RAW_DIR, exist_ok=True)

    url       = NSE_INDEX_URLS.get(index_name, NSE_INDEX_URLS["NIFTY 500"])
    cache_path = os.path.join(RAW_DIR, f"{index_name.replace(' ', '_').lower()}.csv")

    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        df.columns = df.columns.str.strip()

        # Normalise the symbol column name across index files
        if "Symbol" not in df.columns and "symbol" in df.columns:
            df.rename(columns={"symbol": "Symbol"}, inplace=True)

        df["yf_symbol"] = df["Symbol"].str.strip() + ".NS"
        df.to_csv(cache_path, index=False)
        print(f"[Universe] Downloaded {len(df)} stocks for {index_name}")
        return df

    except Exception as e:
        print(f"[Universe] Live download failed ({e}). Trying cache…")
        if os.path.exists(cache_path):
            df = pd.read_csv(cache_path)
            print(f"[Universe] Loaded {len(df)} stocks from cache.")
            return df
        raise RuntimeError(f"Cannot load {index_name} — no cache and no network.")


def get_symbols(index_name: str = "NIFTY 500") -> list:
    """Returns a plain list of yfinance-compatible symbols, e.g. ['RELIANCE.NS', …]"""
    df = get_index_stocks(index_name)
    return df["yf_symbol"].dropna().unique().tolist()


def _get_all_nse_stocks() -> pd.DataFrame:
    """Fetches every EQ-series stock listed on NSE (~2000 stocks)."""
    cache_path = os.path.join(RAW_DIR, "nse_all_equity.csv")
    os.makedirs(RAW_DIR, exist_ok=True)

    try:
        resp = requests.get(NSE_ALL_EQUITY_URL, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        df.columns = df.columns.str.strip()
        # Keep only normal equity series to exclude ETFs, preference shares, etc.
        if "SERIES" in df.columns:
            df = df[df["SERIES"].str.strip() == "EQ"]
        # Normalise to the same shape as index CSVs
        df = df.rename(columns={
            "SYMBOL":          "Symbol",
            "NAME OF COMPANY": "Company Name",
            "SERIES":          "Series",
            "ISIN NUMBER":     "ISIN Code",
        })
        df["Industry"]   = ""
        df["yf_symbol"]  = df["Symbol"].str.strip() + ".NS"
        df.to_csv(cache_path, index=False)
        print(f"[Universe] Downloaded {len(df)} NSE equity stocks")
        return df
    except Exception as e:
        print(f"[Universe] NSE All download failed ({e}). Trying cache…")
        if os.path.exists(cache_path):
            df = pd.read_csv(cache_path)
            print(f"[Universe] Loaded {len(df)} stocks from cache.")
            return df
        raise RuntimeError("Cannot load NSE All — no cache and no network.")


def get_symbol_metadata(index_name: str = "NIFTY 500") -> dict:
    """Returns {yf_symbol: {name, sector, industry}} for display in the UI."""
    df = get_index_stocks(index_name)
    meta = {}
    for _, row in df.iterrows():
        sym = str(row.get("yf_symbol", "")).strip()
        meta[sym] = {
            "name":     str(row.get("Company Name", row.get("company name", sym))).strip(),
            "industry": str(row.get("Industry",     row.get("industry", ""))).strip(),
        }
    return meta
