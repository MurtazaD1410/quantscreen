# Cloud Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate QuantScreen India to Streamlit Community Cloud (free) with Supabase for portfolio persistence and live yfinance for price data.

**Architecture:** Replace SQLite with Supabase REST API (same function signatures), replace CSV-based price loading with live yfinance fetches wrapped in `@st.cache_data(ttl=86400)`. Local pipeline (`run_pipeline.py`) is untouched. Portfolio tab works fully on cloud; screener/backtest require fundamentals data that won't be available on cloud (known limitation, acceptable per user requirements).

**Tech Stack:** `supabase` Python client v2.x, Streamlit `@st.cache_data` / `@st.cache_resource`, yfinance (already installed), Supabase free tier (PostgreSQL), Streamlit Community Cloud (free tier).

---

## Known Limitation

The screener and backtest tabs require fundamentals CSVs (`data/processed/fundamentals/`, `data/processed/shareholding/`) that are produced by `run_pipeline.py`. These are not available on Streamlit Cloud's ephemeral filesystem. On cloud, clicking "Run Screen" will show the existing "Data not ready" error. **The Portfolio Tracker tab works fully and is the primary use case.**

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `requirements.txt` | Modify | Add `supabase` dependency |
| `.gitignore` | Create | Keep secrets and local data out of git |
| `.streamlit/secrets.toml` | Create (local, gitignored) | Local Supabase credentials |
| `app/supabase_client.py` | Create | Supabase singleton via `@st.cache_resource` |
| `app/portfolio_db.py` | Rewrite | Supabase internals, same public API |
| `pipeline/price_data.py` | Modify | Add `fetch_price()` and `fetch_close_matrix()` |
| `app/main.py` | Modify | Import new fetch functions, add `@st.cache_data` wrappers, update 3 call sites |
| `scripts/migrate_sqlite_to_supabase.py` | Create | One-time migration of existing portfolio data |

---

## Task 1: Add `supabase` to `requirements.txt`

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the dependency**

Open `requirements.txt` and append one line:

```
supabase>=2.0.0,<3.0.0
```

Full file after edit:

```
streamlit==1.35.0
yfinance==0.2.40
pandas==2.2.2
numpy==1.26.4
ta==0.11.0
scipy==1.13.1
requests==2.32.3
beautifulsoup4==4.12.3
plotly==5.22.0
openpyxl==3.1.3
lxml==5.2.2
supabase>=2.0.0,<3.0.0
```

- [ ] **Step 2: Install locally**

```
pip install "supabase>=2.0.0,<3.0.0"
```

Expected: installs `supabase` and its dependencies (`httpx`, `gotrue`, `postgrest-py`, etc.)

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat: add supabase dependency for cloud portfolio storage"
```

---

## Task 2: Create `.gitignore`

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Create the file**

Create `.gitignore` at the project root with this content:

```
# Streamlit secrets — NEVER commit
.streamlit/secrets.toml

# Local data directories — large, ephemeral, not for git
database/
data/

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/

# Virtual environments
.venv/
venv/
env/

# IDE
.idea/
.vscode/
*.swp
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore (secrets, data, python artifacts)"
```

---

## Task 3: Create `app/supabase_client.py`

**Files:**
- Create: `app/supabase_client.py`

- [ ] **Step 1: Write the file**

```python
import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def _get_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def get_supabase() -> Client:
    return _get_client()
```

`@st.cache_resource` creates the client once per Streamlit server process and reuses it across all sessions — correct for a connection-like object.

- [ ] **Step 2: Commit**

```bash
git add app/supabase_client.py
git commit -m "feat: add Supabase client singleton"
```

---

## Task 4: Rewrite `app/portfolio_db.py` with Supabase

**Files:**
- Modify: `app/portfolio_db.py`

All public function signatures are **identical** to the SQLite version — no changes needed in `main.py`'s import block.

- [ ] **Step 1: Replace the entire file**

```python
from datetime import datetime
from app.supabase_client import get_supabase


def init_db():
    """Verify Supabase connection. Tables are pre-created via Supabase SQL editor."""
    try:
        get_supabase().table("portfolios").select("id").limit(1).execute()
    except Exception as e:
        raise RuntimeError(f"Supabase connection failed: {e}")


def list_portfolios():
    res = get_supabase().table("portfolios").select("*").order("created_at").execute()
    return res.data


def create_portfolio(name):
    res = get_supabase().table("portfolios").insert({
        "name": name,
        "strategy_note": "",
        "created_at": datetime.now().isoformat(),
    }).execute()
    return res.data[0]["id"]


def rename_portfolio(portfolio_id, new_name):
    get_supabase().table("portfolios").update(
        {"name": new_name}
    ).eq("id", portfolio_id).execute()


def update_strategy_note(portfolio_id, note):
    get_supabase().table("portfolios").update(
        {"strategy_note": note}
    ).eq("id", portfolio_id).execute()


def delete_portfolio(portfolio_id):
    get_supabase().table("portfolios").delete().eq("id", portfolio_id).execute()


def list_holdings(portfolio_id):
    res = (
        get_supabase()
        .table("holdings")
        .select("*")
        .eq("portfolio_id", portfolio_id)
        .order("symbol")
        .execute()
    )
    return res.data


def add_holding(portfolio_id, symbol, quantity, purchase_price, purchase_date):
    get_supabase().table("holdings").insert({
        "portfolio_id": portfolio_id,
        "symbol": symbol.strip().upper(),
        "quantity": quantity,
        "purchase_price": purchase_price,
        "purchase_date": purchase_date,
    }).execute()


def delete_holding(holding_id):
    get_supabase().table("holdings").delete().eq("id", holding_id).execute()
```

- [ ] **Step 2: Commit**

```bash
git add app/portfolio_db.py
git commit -m "feat: rewrite portfolio_db.py with Supabase (same public API)"
```

---

## Task 5: Add `fetch_price` and `fetch_close_matrix` to `pipeline/price_data.py`

**Files:**
- Modify: `pipeline/price_data.py`

These are **new functions** appended after the existing ones. Existing functions (`load_price`, `load_close_matrix`, `download_price_history`) are unchanged.

- [ ] **Step 1: Append the two new functions to `pipeline/price_data.py`**

Add after line 165 (end of `load_benchmark`):

```python


def fetch_price(symbol: str) -> pd.DataFrame:
    """
    Fetches a single stock's OHLCV directly from yfinance (no local CSV).
    Returns a DataFrame with timezone stripped and DatetimeIndex.
    Raises FileNotFoundError if yfinance returns no data.
    """
    start = (datetime.now() - timedelta(days=YEARS_OF_HISTORY * 365)).strftime("%Y-%m-%d")
    df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
    if df.empty:
        raise FileNotFoundError(f"No price data returned for {symbol}")
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_convert(None) if idx.tz is not None else idx.tz_localize(None)
    return df


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
```

- [ ] **Step 2: Write a quick smoke test to verify the functions work**

Create `tests/test_fetch_price.py`:

```python
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest
from pipeline.price_data import fetch_price, fetch_close_matrix


def _make_df(tz="Asia/Kolkata"):
    idx = pd.date_range("2024-01-01", periods=5, tz=tz)
    return pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0, 104.0],
                         "Open":  [99.0,  100.0, 101.0, 102.0, 103.0]}, index=idx)


def test_fetch_price_returns_tz_naive_dataframe():
    with patch("pipeline.price_data.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = _make_df()
        df = fetch_price("RELIANCE.NS")
    assert isinstance(df, pd.DataFrame)
    assert "Close" in df.columns
    assert df.index.tz is None


def test_fetch_price_raises_on_empty():
    with patch("pipeline.price_data.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        with pytest.raises(FileNotFoundError):
            fetch_price("BOGUS.NS")


def test_fetch_close_matrix_returns_close_column_only():
    with patch("pipeline.price_data.yf.download") as mock_dl:
        mock_dl.return_value = _make_df()
        result = fetch_close_matrix(["RELIANCE.NS"])
    assert isinstance(result, pd.DataFrame)
    assert "RELIANCE.NS" in result.columns
    assert result.index.tz is None


def test_fetch_close_matrix_empty_on_failure():
    with patch("pipeline.price_data.yf.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame()
        result = fetch_close_matrix(["BOGUS.NS"])
    assert result.empty
```

- [ ] **Step 3: Run the tests**

```bash
python -m pytest tests/test_fetch_price.py -v
```

Expected output:
```
PASSED tests/test_fetch_price.py::test_fetch_price_returns_tz_naive_dataframe
PASSED tests/test_fetch_price.py::test_fetch_price_raises_on_empty
PASSED tests/test_fetch_price.py::test_fetch_close_matrix_returns_close_column_only
PASSED tests/test_fetch_price.py::test_fetch_close_matrix_empty_on_failure
```

- [ ] **Step 4: Commit**

```bash
git add pipeline/price_data.py tests/test_fetch_price.py
git commit -m "feat: add fetch_price and fetch_close_matrix for live yfinance fetching"
```

---

## Task 6: Update `app/main.py` — imports, wrappers, call sites

**Files:**
- Modify: `app/main.py`

Three independent edits. Apply them in order.

### 6a — Update the import line

- [ ] **Step 1: Update the price_data import (line 16)**

Old:
```python
from pipeline.price_data  import load_close_matrix, load_price, load_benchmark
```

New:
```python
from pipeline.price_data  import load_benchmark, fetch_price, fetch_close_matrix
```

(`load_price` and `load_close_matrix` are no longer called from main.py. `load_benchmark` is kept because `engine/backtester.py` uses it via this module's namespace. `fetch_price` and `fetch_close_matrix` are the new live-fetching equivalents.)

### 6b — Add cached wrapper functions

- [ ] **Step 2: Add two cached wrappers after line 33 (after the portfolio_db imports), before `def _fmt`**

Insert:

```python

@st.cache_data(ttl=86400)
def _cached_close_matrix(symbols):
    return fetch_close_matrix(list(symbols))


@st.cache_data(ttl=86400)
def _cached_price(symbol):
    return fetch_price(symbol)

```

`ttl=86400` = 24 hours. The cache is per-Streamlit-server-process, so a fresh deploy or idle restart starts with a cold cache.

### 6c — Update the three call sites

- [ ] **Step 3: Update `load_data()` (around line 512)**

Old:
```python
    closes     = load_close_matrix(symbols)
```

New:
```python
    closes     = _cached_close_matrix(tuple(symbols))
```

(`tuple()` makes the argument hashable, which is safer for Streamlit's cache key hashing with large symbol lists.)

- [ ] **Step 4: Update `_render_stock_detail()` (around line 261)**

Old:
```python
        price_df = load_price(selected)
```

New:
```python
        price_df = _cached_price(selected)
```

The surrounding `try/except` already handles missing data gracefully.

- [ ] **Step 5: Update `load_ohlcv_dict()` (around line 521)**

Old:
```python
            data[sym] = load_price(sym)
```

New:
```python
            data[sym] = _cached_price(sym)
```

- [ ] **Step 6: Commit**

```bash
git add app/main.py
git commit -m "feat: switch main.py to live yfinance fetch with st.cache_data wrappers"
```

---

## Task 7: Create `scripts/migrate_sqlite_to_supabase.py`

**Files:**
- Create: `scripts/migrate_sqlite_to_supabase.py`

This script runs standalone (no Streamlit) and accepts credentials interactively. Run it once before switching over to preserve existing portfolio data.

- [ ] **Step 1: Create the script**

```python
"""
One-time migration: SQLite portfolios.db → Supabase.
Run from the project root: python scripts/migrate_sqlite_to_supabase.py
"""
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database", "portfolios.db",
)


def main():
    if not os.path.exists(DB_PATH):
        print(f"No SQLite database found at {DB_PATH}. Nothing to migrate.")
        return

    supabase_url = input("SUPABASE_URL: ").strip()
    supabase_key = input("SUPABASE_KEY (anon key): ").strip()
    sb = create_client(supabase_url, supabase_key)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    portfolios = [dict(r) for r in conn.execute(
        "SELECT * FROM portfolios ORDER BY created_at"
    ).fetchall()]
    print(f"\nFound {len(portfolios)} portfolio(s) to migrate.")

    old_to_new = {}
    for p in portfolios:
        res = sb.table("portfolios").insert({
            "name": p["name"],
            "strategy_note": p["strategy_note"],
            "created_at": p["created_at"],
        }).execute()
        new_id = res.data[0]["id"]
        old_to_new[p["id"]] = new_id
        print(f"  Portfolio '{p['name']}': old id {p['id']} → new id {new_id}")

    holdings = [dict(r) for r in conn.execute("SELECT * FROM holdings").fetchall()]
    print(f"\nFound {len(holdings)} holding(s) to migrate.")

    for h in holdings:
        new_pid = old_to_new.get(h["portfolio_id"])
        if new_pid is None:
            print(f"  WARN: holding id {h['id']} references missing portfolio — skipped")
            continue
        sb.table("holdings").insert({
            "portfolio_id": new_pid,
            "symbol": h["symbol"],
            "quantity": h["quantity"],
            "purchase_price": h["purchase_price"],
            "purchase_date": h["purchase_date"],
        }).execute()
        print(f"  Holding {h['symbol']} x{h['quantity']} migrated.")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/migrate_sqlite_to_supabase.py
git commit -m "feat: add one-time SQLite→Supabase migration script"
```

---

## Task 8: Set up Supabase project and tables (manual)

No code changes — follow these steps in the browser.

- [ ] **Step 1: Create a free Supabase project**

  1. Go to [supabase.com](https://supabase.com) and sign in (free tier is sufficient)
  2. Click **New project**
  3. Name it `quantscreen` (or any name)
  4. Set a strong database password (save it — you won't use it directly but it's the DB password)
  5. Choose the region closest to India (e.g., **Singapore**)
  6. Click **Create new project** and wait ~1 min for provisioning

- [ ] **Step 2: Create the tables**

  In the Supabase dashboard → **SQL Editor** → **New query**, paste and run:

  ```sql
  create table portfolios (
    id            bigserial primary key,
    name          text not null,
    strategy_note text not null default '',
    created_at    text not null
  );

  create table holdings (
    id             bigserial primary key,
    portfolio_id   bigint not null references portfolios(id) on delete cascade,
    symbol         text not null,
    quantity       real not null,
    purchase_price real not null,
    purchase_date  text not null
  );

  -- Disable Row Level Security for this personal app
  -- (all requests use the anon key from the app server — no user auth needed)
  alter table portfolios disable row level security;
  alter table holdings   disable row level security;
  ```

  Click **Run**. Expected: "Success. No rows returned."

- [ ] **Step 3: Copy credentials**

  Dashboard → **Project Settings** → **API**:
  - Copy **Project URL** (e.g., `https://xyzxyz.supabase.co`) → this is `SUPABASE_URL`
  - Copy **anon public** key → this is `SUPABASE_KEY`

  Keep these open for the next two tasks.

---

## Task 9: Set up local secrets

**Files:**
- Create: `.streamlit/secrets.toml` (gitignored — do NOT commit)

- [ ] **Step 1: Create the `.streamlit/` directory if needed, then create `secrets.toml`**

  Create the file at `.streamlit/secrets.toml`:

  ```toml
  SUPABASE_URL = "https://your-project-id.supabase.co"
  SUPABASE_KEY = "your-anon-public-key-here"
  ```

  Replace the placeholder values with the credentials from Task 8 Step 3.

- [ ] **Step 2: Verify `.gitignore` protects it**

  ```bash
  git status
  ```

  Expected: `.streamlit/secrets.toml` should NOT appear in the output (it's gitignored). If it appears as untracked, your `.gitignore` is not matching — verify the path.

---

## Task 10: Run the data migration (if you have existing portfolio data)

Skip this task if your SQLite database is empty or you want to start fresh.

- [ ] **Step 1: Run the migration script**

  ```bash
  python scripts/migrate_sqlite_to_supabase.py
  ```

  When prompted, paste the `SUPABASE_URL` and `SUPABASE_KEY` from Task 8.

  Expected output:
  ```
  Found N portfolio(s) to migrate.
    Portfolio 'My Portfolio': old id 1 → new id 1
  Found M holding(s) to migrate.
    Holding RELIANCE.NS x10 migrated.
    ...
  Migration complete.
  ```

- [ ] **Step 2: Verify in Supabase dashboard**

  Dashboard → **Table Editor** → `portfolios` and `holdings`. Confirm your data appears.

---

## Task 11: Smoke test locally

- [ ] **Step 1: Run the app**

  ```bash
  streamlit run app/main.py
  ```

  Expected: app starts, no import errors in terminal.

- [ ] **Step 2: Verify Portfolio tab**

  - Open the **Portfolio** tab
  - Expected: existing portfolios and holdings appear (migrated from SQLite)
  - Create a new portfolio via the **＋ New Portfolio** button
  - Add a stock holding (e.g., RELIANCE.NS, qty 1, price 100)
  - Expected: holding appears in the table with live price fetched from yfinance

- [ ] **Step 3: Verify price chart in Stock Lookup tab**

  - Open **Stock Lookup** tab, search for any NSE stock (e.g., `RELIANCE.NS`)
  - Expected: price chart loads (fetched live from yfinance, ~2–3 seconds)
  - Second lookup of same stock should be instant (cached)

- [ ] **Step 4: Verify screener shows expected error**

  - Click **Run Screen** in the Screener tab
  - Expected: "Data not ready" error with message to run `run_pipeline.py`
  - This is correct — fundamentals CSVs are not available in cloud mode

---

## Task 12: Deploy to Streamlit Community Cloud

No code changes — follow these steps in the browser.

- [ ] **Step 1: Push the code to GitHub**

  ```bash
  git push origin main
  ```

  (Create a GitHub repo first if needed. The repo can be private — Streamlit Cloud supports private repos.)

- [ ] **Step 2: Connect to Streamlit Community Cloud**

  1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub
  2. Click **New app**
  3. Select your repository and branch (`main`)
  4. Set **Main file path** to `app/main.py`
  5. Click **Advanced settings** before deploying

- [ ] **Step 3: Add secrets in Streamlit Cloud dashboard**

  In **Advanced settings** → **Secrets**, paste:

  ```toml
  SUPABASE_URL = "https://your-project-id.supabase.co"
  SUPABASE_KEY = "your-anon-public-key-here"
  ```

  Use the same values as your local `secrets.toml`.

- [ ] **Step 4: Deploy**

  Click **Deploy!**. Wait 2–4 minutes for the build (pip install of all dependencies).

  Expected: app loads at `https://your-app-name.streamlit.app`

- [ ] **Step 5: Share the URL with your father**

  The URL format is `https://<your-app-name>.streamlit.app`. Send it — it works on any browser including tablet and mobile.

---

## Self-Review Checklist

- **Spec coverage:**
  - [x] Section 1 (Supabase portfolio): Tasks 3, 4, 8, 9, 10
  - [x] Section 2 (live price fetch + cache): Tasks 5, 6
  - [x] Section 3 (deployment): Tasks 12
  - [x] requirements.txt: Task 1
  - [x] .gitignore: Task 2
  - [x] Migration script: Task 7
  - [x] `init_db()` becomes connection check (not no-op): Task 4 Step 1 ✓

- **Type/name consistency:**
  - `fetch_price(symbol: str)` defined in Task 5, called as `_cached_price(symbol)` in Task 6 ✓
  - `fetch_close_matrix(symbols: list)` defined in Task 5, called as `_cached_close_matrix(tuple(symbols))` in Task 6 ✓
  - `get_supabase()` defined in Task 3, called in Task 4 ✓
  - All `portfolio_db` function names identical to original ✓

- **RLS note:** Task 8 SQL includes `alter table ... disable row level security` — without this, the anon key cannot read/write and the app silently returns empty data. Critical step. ✓
