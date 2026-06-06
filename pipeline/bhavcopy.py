# pipeline/bhavcopy.py — Download NSE Bhavcopy (official EOD data from NSE archives)

import os
import io
import zipfile
import requests
import pandas as pd
from datetime import datetime, timedelta
from config import RAW_DIR, REQUEST_HEADERS


BHAVCOPY_DIR = os.path.join(RAW_DIR, "bhavcopy")


def _bhavcopy_url(date: datetime) -> str:
    """
    Constructs the NSE Bhavcopy download URL for a given date.
    Example: https://archives.nseindia.com/content/historical/EQUITIES/2024/JAN/cm01JAN2024bhav.csv.zip
    """
    year     = date.strftime("%Y")
    month    = date.strftime("%b").upper()
    day_str  = date.strftime("%d%b%Y").upper()
    return (
        f"https://archives.nseindia.com/content/historical/EQUITIES"
        f"/{year}/{month}/cm{day_str}bhav.csv.zip"
    )


def download_bhavcopy(date: datetime) -> pd.DataFrame | None:
    """
    Downloads and parses NSE Bhavcopy for a single date.
    Returns None for weekends / market holidays (file won't exist).
    """
    os.makedirs(BHAVCOPY_DIR, exist_ok=True)

    # Skip weekends
    if date.weekday() >= 5:
        return None

    url = _bhavcopy_url(date)
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        if resp.status_code != 200:
            return None   # Holiday — file doesn't exist

        z   = zipfile.ZipFile(io.BytesIO(resp.content))
        df  = pd.read_csv(z.open(z.namelist()[0]))
        df.columns = df.columns.str.strip()
        df["DATE"]  = date.strftime("%Y-%m-%d")
        return df

    except Exception as e:
        print(f"  WARN: Bhavcopy {date.strftime('%Y-%m-%d')} — {e}")
        return None


def download_bhavcopy_range(start: datetime, end: datetime) -> pd.DataFrame:
    """
    Downloads Bhavcopy for every trading day in [start, end].
    Saves a combined CSV to data/raw/bhavcopy/bhavcopy_combined.csv.
    Returns the combined DataFrame.
    """
    frames   = []
    current  = start

    while current <= end:
        df = download_bhavcopy(current)
        if df is not None:
            frames.append(df)
            print(f"  Downloaded Bhavcopy: {current.strftime('%Y-%m-%d')}")
        current += timedelta(days=1)

    if not frames:
        print("No Bhavcopy data downloaded.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    out_path  = os.path.join(BHAVCOPY_DIR, "bhavcopy_combined.csv")
    combined.to_csv(out_path, index=False)
    print(f"Saved {len(combined):,} rows → {out_path}")
    return combined


def get_latest_bhavcopy() -> pd.DataFrame | None:
    """Downloads yesterday's (or most recent trading day's) Bhavcopy."""
    date = datetime.now() - timedelta(days=1)
    # Walk back to last weekday
    while date.weekday() >= 5:
        date -= timedelta(days=1)
    return download_bhavcopy(date)
