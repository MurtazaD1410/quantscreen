# pipeline/shareholding.py — Fetch stakeholder / shareholding data

import os
import json
import pandas as pd
import yfinance as yf
from config import FUND_DIR


def get_shareholding(symbol: str) -> dict:
    """
    Returns a dict with insider_pct and institution_pct for a symbol.
    Tries the local fundamentals JSON cache first; falls back to live fetch.
    """
    cache_path = os.path.join(FUND_DIR, f"{symbol}.json")

    # Try reading from already-downloaded fundamentals cache
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return _parse_holders(data)
        except (json.JSONDecodeError, ValueError):
            pass  # corrupt cache — fall through to live fetch

    # Live fetch (slower path)
    try:
        t = yf.Ticker(symbol)
        mh = t.major_holders
        if mh is None or mh.empty:
            return {}
        return {
            "insider_pct":     _to_float(mh.iloc[0, 0]),
            "institution_pct": _to_float(mh.iloc[1, 0]),
        }
    except Exception as e:
        print(f"  WARN: shareholding failed for {symbol} — {e}")
        return {}


def build_holdings_dataframe(symbols: list) -> pd.DataFrame:
    """
    Returns a DataFrame with insider_pct and institution_pct for all symbols.
    """
    records = []
    for sym in symbols:
        row = get_shareholding(sym)
        row["symbol"] = sym
        records.append(row)
    df = pd.DataFrame(records).set_index("symbol")
    return df


# ── helpers ──────────────────────────────────────────────────────

def _parse_holders(data: dict) -> dict:
    try:
        holders = data.get("major_holders", {})
        vals = list(list(holders.values())[0].values())
        return {
            "insider_pct":     _to_float(vals[0]),
            "institution_pct": _to_float(vals[1]) if len(vals) > 1 else None,
        }
    except Exception:
        return {}


def _to_float(val) -> float | None:
    try:
        return float(str(val).replace("%", "").strip())
    except Exception:
        return None
