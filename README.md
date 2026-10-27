# QuantScreen India 📈

**NSE Quantitative Stock Screener — Local Streamlit App**

Quantitative stock screener for NSE-listed Indian equities. It ranks stocks with a multi-factor model (Value, Quality, Momentum, Low Volatility) and lets you test a screen with a historical backtest.

> **Disclaimer:** This app is for educational and research purposes only. It does not constitute SEBI-registered investment advice. Past backtest performance does not guarantee future returns.

---

## Features

- **4 Strategy Modules** — Value, Quality, Momentum, Low Volatility (all toggleable)
- **2 Overlay Modules** — Mean Reversion, Stakeholder Holdings
- **Custom Weights** — drag sliders to weight each strategy
- **Sector & Cap Filter** — filter universe by sector or market cap
- **Results Table** — ranked by composite score with per-factor breakdown
- **Heatmap View** — colour-coded factor grid for top 30 stocks
- **Stock Detail** — price chart with MA overlays + radar chart of factor scores
- **Backtesting** — historical simulation with equity curve, Sharpe, CAGR, drawdown
- **CSV Export** — download results for any screen

---

## How scoring works

Each module scores every stock from a few underlying metrics:

| Module | Metrics |
|--------|---------|
| Value | P/E, P/B, EV/EBITDA |
| Quality | ROCE, ROE, Piotroski F-Score |
| Momentum | 12M momentum, 52-week-high proximity |
| Low Volatility | Beta, annualised volatility, max drawdown |
| Mean Reversion (overlay) | RSI, Bollinger Band, Z-score signals |
| Holdings (overlay) | Promoter and institutional holding % |

Scores are normalised across the stock universe with cross-sectional z-scores and combined, using the weights set in the sidebar, into one composite score. Stocks are ranked by that composite score.

---

## How it fits together

```
pipeline/  →  data/  →  engine/  →  app/main.py
download      stored    factor        Streamlit UI
and parse     files     scores,       (results, heatmap,
data                    composite,    stock detail,
                        backtest      backtest)
```

**Tech stack:** Python, Streamlit, FastAPI, yfinance, Docker

---

## Quick Start (3 steps)

### Step 1 — Install dependencies
Open a terminal in this folder and run:
```bash
pip install -r requirements.txt
```

### Step 2 — Download data (one-time, ~15 min for NIFTY 50)
```bash
# Start with NIFTY 50 (50 stocks — fast, good for testing)
python run_pipeline.py --index "NIFTY 50"

# When ready, upgrade to NIFTY 500 (500 stocks — ~30–40 min first time)
python run_pipeline.py --index "NIFTY 500"
```

### Step 3 — Run the app
```bash
streamlit run app/main.py
```
Opens at **http://localhost:8501** in your browser.

---

## Daily Usage

Every morning, refresh data before opening the app:
```bash
python run_pipeline.py --index "NIFTY 50"   # ~2–3 min incremental
streamlit run app/main.py
```

---

## Docker and tests

A `Dockerfile` and `docker-compose.yml` are included for running the project in a container. Automated tests live in `tests/`:
```bash
pip install -r requirements-dev.txt
pytest
```

---

## Project Structure

```
quantscreen/
├── app/
│   └── main.py              ← Streamlit UI (run this)
├── engine/
│   ├── indicators.py        ← RSI, Bollinger, MA, ADX etc.
│   ├── value_factor.py      ← P/E, P/B, EV/EBITDA scoring
│   ├── quality_factor.py    ← ROCE, ROE, Piotroski F-Score
│   ├── momentum_factor.py   ← 12M momentum, 52W high proximity
│   ├── lowvol_factor.py     ← Beta, annualised vol, max drawdown
│   ├── meanrev_factor.py    ← RSI, Bollinger Band, Z-score signals
│   ├── holdings_factor.py   ← Promoter & institutional holding %
│   ├── composite.py         ← Weighted score combiner + ranker
│   └── backtester.py        ← Historical simulation engine
├── pipeline/
│   ├── universe.py          ← NSE index constituent lists
│   ├── price_data.py        ← yfinance OHLCV download + loader
│   ├── fundamentals.py      ← yfinance financials download + parser
│   ├── bhavcopy.py          ← NSE official Bhavcopy downloader
│   └── shareholding.py      ← Promoter / FII / DII holding data
├── tests/                   ← Automated tests
├── data/                    ← Auto-created, holds all downloaded data
├── api.py                   ← FastAPI service
├── config.py                ← All settings in one place
├── run_pipeline.py          ← One-click data refresh script
├── Dockerfile
├── docker-compose.yml
├── n8n_workflow.json        ← n8n workflow export
└── requirements.txt
```

---

## Data Sources

| Data | Source | Cost |
|------|--------|------|
| Stock universe | NSE official index CSVs | Free |
| Price history (OHLCV) | yfinance (Yahoo Finance / NSE) | Free |
| Fundamentals (P/E, ROCE…) | yfinance | Free |
| Shareholding | yfinance major_holders | Free |
| NSE Bhavcopy | NSE archives | Free |

Free data sources can have gaps or delays, especially for fundamentals and shareholding.
