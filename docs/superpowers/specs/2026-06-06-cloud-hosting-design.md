# QuantScreen Cloud Hosting Design
**Date:** 2026-06-06  
**Goal:** Host the app on Streamlit Community Cloud (free) so a non-technical user can access it from a tablet/mobile browser.

---

## Problem

The app currently relies on:
- Local CSV files for price/fundamentals data
- SQLite (`database/portfolios.db`) for portfolio persistence

Neither survives on Streamlit Cloud: the filesystem is ephemeral (wiped on idle restart after ~30 min), so portfolio data would be lost and CSVs would be unavailable.

---

## Approach: Supabase portfolio + Streamlit cache for prices

**Out of scope:** migrating fundamentals scraping, changing `run_pipeline.py`, or any screener/backtest logic.

---

## Section 1: Supabase Portfolio Migration

### New files
- `app/supabase_client.py` — initialises the Supabase Python client using `st.secrets["SUPABASE_URL"]` and `st.secrets["SUPABASE_KEY"]`. Returns a singleton client.

### Changed files
- `app/portfolio_db.py` — rewritten internals; all function signatures unchanged:
  - `init_db()`, `list_portfolios()`, `create_portfolio()`, `rename_portfolio()`, `delete_portfolio()`, `update_strategy_note()`, `list_holdings()`, `add_holding()`, `delete_holding()`
  - SQLite calls replaced with Supabase REST calls (`supabase.table().select/insert/update/delete`)
- `requirements.txt` — add `supabase`

### Database schema (Supabase SQL editor)
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
```

### Secrets
| Key | Where |
|-----|-------|
| `SUPABASE_URL` | `.streamlit/secrets.toml` (local, gitignored) + Streamlit Cloud dashboard |
| `SUPABASE_KEY` | same |

### One-time migration
- Small standalone script (`scripts/migrate_sqlite_to_supabase.py`) reads the existing `database/portfolios.db` and inserts all rows into Supabase. Run once before switching over.

---

## Section 2: Live Price Fetching with Streamlit Cache

### New functions in `pipeline/price_data.py`
- `fetch_price(symbol: str) -> pd.DataFrame` — fetches a single stock's OHLCV from yfinance directly (no CSV).
- `fetch_close_matrix(symbols: list) -> pd.DataFrame` — fetches all symbols in batches, returns wide close-price DataFrame.

Existing `load_price()`, `load_close_matrix()`, `download_price_history()` are **unchanged** — local pipeline (`run_pipeline.py`) continues to work.

### Changes in `app/main.py`
- Two `@st.cache_data(ttl=86400)` wrapper functions replace the CSV-reading calls:
  ```python
  @st.cache_data(ttl=86400)
  def _cached_close_matrix(symbols):
      return fetch_close_matrix(symbols)

  @st.cache_data(ttl=86400)  
  def _cached_price(symbol):
      return fetch_price(symbol)
  ```
- All existing call sites updated to use the cached wrappers.
- `load_benchmark()` already fetches live — no change.
- Screener/backtest first run shows `st.spinner("Fetching price data… this takes a few minutes on first load")`.

### Performance expectation
| Universe | First load | Subsequent (same session) |
|----------|-----------|--------------------------|
| NIFTY 50 | ~15 sec | instant |
| NIFTY 500 | ~1–2 min | instant |
| All NSE (2000+) | ~5–10 min | instant |

---

## Section 3: Deployment

### Steps
1. **Supabase** — Create free project at supabase.com. Run schema SQL above. Copy URL + anon key.
2. **Data migration** — Run `scripts/migrate_sqlite_to_supabase.py` once to preserve existing portfolio data.
3. **GitHub** — Push repo (public or private).
4. **Streamlit Cloud** — Connect repo at share.streamlit.io. Set entry point to `app/main.py`. Add `SUPABASE_URL` and `SUPABASE_KEY` as secrets.
5. **Local dev** — Add `.streamlit/secrets.toml` (gitignored) with same two keys.

### Files to add to `.gitignore`
```
.streamlit/secrets.toml
database/
data/
```

---

## What is NOT changing
- `run_pipeline.py` and all pipeline CSV logic — local development workflow unchanged
- Screener, backtest, fundamentals, and factor engine logic — zero changes
- `app/main.py` tab structure — only the data-fetching call sites change
