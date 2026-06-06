# app/main.py — QuantScreen India — Streamlit App

import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from pipeline.universe    import get_index_stocks, get_symbol_metadata
from pipeline.price_data  import load_benchmark, fetch_price, fetch_close_matrix
from pipeline.fundamentals import build_metrics_dataframe
from pipeline.shareholding import build_holdings_dataframe

from engine.value_factor    import score_value
from engine.quality_factor  import score_quality, piotroski_score
from engine.momentum_factor import score_momentum, golden_cross_signal
from engine.lowvol_factor   import score_lowvol
from engine.meanrev_factor  import score_meanrev
from engine.holdings_factor import score_holdings
from engine.composite       import compute_composite
from engine.backtester      import run_backtest

from config import DEFAULT_WEIGHTS, BACKTEST, NIFTY50_TICKER
from app.portfolio_db import (
    init_db, list_portfolios, create_portfolio, rename_portfolio,
    delete_portfolio, update_strategy_note, list_holdings, add_holding, delete_holding,
)


@st.cache_data(ttl=86400)
def _cached_close_matrix(symbols):
    return fetch_close_matrix(list(symbols))


@st.cache_data(ttl=86400)
def _cached_price(symbol):
    return fetch_price(symbol)


def _fmt(val, decimals=1):
    try:    return f"{float(val):.{decimals}f}"
    except: return "—"

def _pct(val):
    try:    return f"{float(val)*100:.1f}%"
    except: return "—"


_WEIGHT_LABELS = {
    "value": "Value Factor", "quality": "Quality Factor",
    "momentum": "Momentum", "low_volatility": "Low Volatility",
    "mean_reversion": "Mean Reversion", "holdings": "Stakeholder Holdings",
}


def _config_rows(weights, extra_rows):
    rows = list(extra_rows)
    rows += [(_WEIGHT_LABELS.get(k, k), f"{v * 100:.1f}%") for k, v in weights.items()]
    return pd.DataFrame(rows, columns=["", ""])


def _build_screener_excel(top_results, weights, universe, sector_filter, cap_filter):
    buf = io.BytesIO()

    cfg = _config_rows(weights, [
        ("Run Date",          datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Universe",          universe),
        ("Sector Filter",     ", ".join(sector_filter) if sector_filter else "All"),
        ("Market Cap Filter", cap_filter),
        ("Stocks in Output",  len(top_results)),
    ])

    score_cols = [c for c in top_results.columns if c.endswith("_score")]
    export_df = top_results[["rank", "name"] + score_cols].copy()
    export_df = export_df.reset_index().rename(columns={"index": "Ticker"})
    for col in score_cols:
        export_df[col] = export_df[col].round(1)
    export_df.rename(columns={
        "rank": "Rank", "name": "Company",
        **{c: c.replace("_score", "").replace("_", " ").title() + " Score" for c in score_cols},
    }, inplace=True)

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        cfg.to_excel(writer, sheet_name="Results", index=False, header=False)
        export_df.to_excel(writer, sheet_name="Results", index=False, startrow=len(cfg) + 1)

    buf.seek(0)
    return buf.getvalue()


def _build_alloc_excel(alloc_df, weights, capital, weighting, universe):
    buf = io.BytesIO()

    cfg = _config_rows(weights, [
        ("Run Date",         datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Universe",         universe),
        ("Capital (₹)",      capital),
        ("Weighting Method", weighting),
        ("Number of Stocks", len(alloc_df)),
    ])

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        cfg.to_excel(writer, sheet_name="Results", index=False, header=False)
        alloc_df.reset_index().to_excel(writer, sheet_name="Results", index=False, startrow=len(cfg) + 1)

    buf.seek(0)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def _load_lookup_meta():
    return get_symbol_metadata("NSE All")


PRESETS = {
    "qmv": {
        "label": "QMV · The Quant Core",
        "tag": "Balanced",
        "formula": "Quality 35% · Momentum 40% · Value 25%",
        "summary": (
            "The institutional standard. Buy great businesses (Quality), at the right time "
            "(Momentum), without overpaying (Value). Each factor is ranked across all stocks "
            "so scores are comparable. Best all-weather starting point for any universe."
        ),
        "tog_value": True,  "tog_quality": True,  "tog_momentum": True,
        "tog_lowvol": False, "tog_meanrev": False, "tog_holdings": False,
        "slid_value": 25, "slid_quality": 35, "slid_momentum": 40,
        "slid_lowvol": 15, "slid_meanrev": 10, "slid_holdings": 10,
    },
    "qm": {
        "label": "QM · Growth Momentum",
        "tag": "High Growth",
        "formula": "Quality 50% · Momentum 50%",
        "summary": (
            "Built for bull markets. Deliberately drops Value — in growth-driven markets, "
            "cheap stocks are often cheap for a reason. Quality filters weak businesses; "
            "Momentum confirms the market agrees. Simple, robust, low signal-cancellation."
        ),
        "tog_value": False, "tog_quality": True,  "tog_momentum": True,
        "tog_lowvol": False, "tog_meanrev": False, "tog_holdings": False,
        "slid_value": 30, "slid_quality": 50, "slid_momentum": 50,
        "slid_lowvol": 15, "slid_meanrev": 10, "slid_holdings": 10,
    },
    "qvl": {
        "label": "QVL · The Defensive Compounder",
        "tag": "Conservative",
        "formula": "Quality 40% · Value 30% · Low Vol 30%",
        "summary": (
            "Steady compounding over flashy returns. Strong businesses (Quality) trading "
            "at fair prices (Value) that don't swing wildly (Low Vol). Lower turnover, "
            "smaller drawdowns, and better sleep. Suits conservative or retirement mandates."
        ),
        "tog_value": True,  "tog_quality": True,  "tog_momentum": False,
        "tog_lowvol": True,  "tog_meanrev": False, "tog_holdings": False,
        "slid_value": 30, "slid_quality": 40, "slid_momentum": 25,
        "slid_lowvol": 30, "slid_meanrev": 10, "slid_holdings": 10,
    },
    "wealth_builder": {
        "label": "The All-Rounder",
        "tag": "All-Weather",
        "formula": "Value 35% · Quality 40% · Momentum 25%",
        "summary": (
            "The most-used combination for long-term investors. Quality keeps you out of "
            "bad businesses, Value stops you overpaying, Momentum avoids value traps that "
            "just keep falling. Balanced, battle-tested, and hard to go badly wrong with."
        ),
        "tog_value": True,  "tog_quality": True,  "tog_momentum": True,
        "tog_lowvol": False, "tog_meanrev": False, "tog_holdings": False,
        "slid_value": 35, "slid_quality": 40, "slid_momentum": 25,
        "slid_lowvol": 15, "slid_meanrev": 10, "slid_holdings": 10,
    },
    "conservative": {
        "label": "Capital Preservation",
        "tag": "Low Risk",
        "formula": "Quality 40% · Low Vol 35% · Holdings 25%",
        "summary": (
            "Designed to survive bad years. Prioritises financially strong, low-volatility "
            "stocks where promoters and institutions hold conviction. Expect fewer 10-baggers "
            "— but also far fewer 70% drawdowns. Ideal for capital you can't afford to lose."
        ),
        "tog_value": False, "tog_quality": True,  "tog_momentum": False,
        "tog_lowvol": True,  "tog_meanrev": False, "tog_holdings": True,
        "slid_value": 30, "slid_quality": 40, "slid_momentum": 25,
        "slid_lowvol": 35, "slid_meanrev": 10, "slid_holdings": 25,
    },
    "contrarian": {
        "label": "Contrarian Bounce",
        "tag": "Tactical",
        "formula": "Mean Reversion 50% · Value 30% · Quality 20%",
        "summary": (
            "Buys what everyone is selling. Targets oversold, beaten-down stocks that are "
            "statistically due for a reversal. Works best after market corrections. High "
            "risk — requires conviction to hold through continued selling pressure."
        ),
        "tog_value": True,  "tog_quality": True,  "tog_momentum": False,
        "tog_lowvol": False, "tog_meanrev": True,  "tog_holdings": False,
        "slid_value": 30, "slid_quality": 20, "slid_momentum": 25,
        "slid_lowvol": 15, "slid_meanrev": 50, "slid_holdings": 10,
    },
}

_TOG_KEYS  = ["tog_value", "tog_quality", "tog_momentum", "tog_lowvol", "tog_meanrev", "tog_holdings"]
_SLID_KEYS = ["slid_value", "slid_quality", "slid_momentum", "slid_lowvol", "slid_meanrev", "slid_holdings"]

def _apply_preset(key: str):
    p = PRESETS[key]
    for k in _TOG_KEYS + _SLID_KEYS:
        st.session_state[k] = p[k]


@st.cache_data(ttl=300, show_spinner=False)
def _get_live_price(symbol: str):
    try:
        import yfinance as yf
        fi    = yf.Ticker(symbol).fast_info
        price = getattr(fi, "last_price",      None)
        prev  = getattr(fi, "previous_close",  None)
        return (float(price) if price else None,
                float(prev)  if prev  else None)
    except Exception:
        return None, None


def _render_stock_detail(selected: str, row: pd.Series, meta: dict, factor_row=None):
    name = meta.get(selected, {}).get("name", selected)
    st.subheader(f"{name}  `{selected}`")

    # Live price (cached 5 min)
    live_price, prev_close = _get_live_price(selected)
    if live_price:
        lp1, _ = st.columns([1, 5])
        with lp1:
            delta_str = None
            if prev_close and prev_close > 0:
                chg     = live_price - prev_close
                chg_pct = chg / prev_close * 100
                delta_str = f"{chg:+.2f} ({chg_pct:+.2f}%)"
            st.metric("Current Price", f"₹{live_price:,.2f}", delta=delta_str)
    else:
        st.caption("Live price unavailable — check network or run pipeline.")

    st.divider()

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("P/E",        _fmt(row.get("pe_ratio")))
    m2.metric("P/B",        _fmt(row.get("pb_ratio"), 2))
    m3.metric("ROE",        _pct(row.get("roe")))
    m4.metric("ROCE",       _pct(row.get("roce")))
    m5.metric("Debt/Eq",    _fmt(row.get("debt_to_equity"), 2))
    m6.metric("Rev Growth", _pct(row.get("revenue_growth")))

    m7, m8, m9, m10, m11, m12 = st.columns(6)
    m7.metric("Beta",       _fmt(row.get("beta"), 2))
    m8.metric("EV/EBITDA",  _fmt(row.get("ev_ebitda")))
    m9.metric("Op Margin",  _pct(row.get("operating_margins")))
    m10.metric("Sector",    str(row.get("sector", "—")))
    mcap = row.get("market_cap")
    m11.metric("Mkt Cap",   f"₹{int(mcap/1e7):,} Cr" if mcap and not pd.isna(mcap) else "—")
    m12.metric("Piotroski", piotroski_score(row))

    st.divider()

    st.markdown("**Price Chart**")
    try:
        price_df = _cached_price(selected)
        ma50  = price_df["Close"].rolling(50).mean()
        ma200 = price_df["Close"].rolling(200).mean()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=price_df.index, y=price_df["Close"],
            mode="lines", name="Price",
            line=dict(color="#2563eb", width=2)
        ))
        fig.add_trace(go.Scatter(x=price_df.index, y=ma50,
            mode="lines", name="MA 50",
            line=dict(color="#f59e0b", dash="dash", width=1.2)))
        fig.add_trace(go.Scatter(x=price_df.index, y=ma200,
            mode="lines", name="MA 200",
            line=dict(color="#ef4444", dash="dash", width=1.2)))
        default_start = price_df.index[-1] - pd.DateOffset(years=1)
        fig.update_layout(
            height=380,
            margin=dict(l=0, r=0, t=40, b=50),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="left", x=0),
            xaxis=dict(
                range=[default_start, price_df.index[-1]],
                rangeselector=dict(
                    buttons=[
                        dict(count=1,  label="1M", step="month", stepmode="backward"),
                        dict(count=3,  label="3M", step="month", stepmode="backward"),
                        dict(count=6,  label="6M", step="month", stepmode="backward"),
                        dict(count=1,  label="1Y", step="year",  stepmode="backward"),
                        dict(count=3,  label="3Y", step="year",  stepmode="backward"),
                        dict(count=5,  label="5Y", step="year",  stepmode="backward"),
                        dict(step="all", label="All"),
                    ],
                    activecolor="#2563eb",
                    bgcolor="#1e293b",
                    font=dict(color="#94a3b8", size=12),
                ),
                rangeslider=dict(visible=False),
                type="date",
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception:
        st.warning("Price chart unavailable — run data pipeline first.")

    if factor_row is not None:
        radar_col, _ = st.columns([1, 1])
        with radar_col:
            st.markdown("**Factor Scores**")
            factor_cols = [c for c in factor_row.index
                           if c.endswith("_score") and c != "composite_score"]
            if factor_cols:
                vals   = [factor_row.get(c, 0) for c in factor_cols]
                labels = [c.replace("_score","").replace("_"," ").title()
                          for c in factor_cols]
                fig2 = go.Figure(go.Scatterpolar(
                    r=vals + [vals[0]],
                    theta=labels + [labels[0]],
                    fill="toself",
                    fillcolor="rgba(59,130,246,0.2)",
                    line=dict(color="#2563eb"),
                ))
                fig2.update_layout(
                    polar=dict(radialaxis=dict(range=[0, 100], visible=True)),
                    height=320, margin=dict(l=20,r=20,t=20,b=20),
                    showlegend=False,
                )
                st.plotly_chart(fig2, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="QuantScreen India",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .metric-card { background:#f8fafc; border-radius:10px; padding:12px 16px; border:1px solid #e2e8f0; }
    .stProgress > div > div { background: linear-gradient(90deg,#3b82f6,#06b6d4); }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# SIDEBAR — CONTROLS
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    components.html("""
    <style>
      * { margin:0; padding:0; }
      body { background:transparent; font-family:"Source Sans Pro","Segoe UI",sans-serif; }
      .brand {
        font-size:1.6rem; font-weight:700; cursor:pointer;
        padding:4px 2px; display:block; color:#31333f;
      }
      @media (prefers-color-scheme:dark) { .brand { color:#fafafa; } }
      .brand:hover { opacity:.75; }
    </style>
    <div class="brand" title="Go to Screener"
      onclick="window.parent.document.querySelectorAll('[data-testid=stTab]')[0]?.click()">
      📈 QuantScreen India
    </div>
    """, height=48)
    st.caption("NSE Quantitative Stock Screener")
    st.divider()

    # ── Universe ──────────────────────────────────────────────
    st.subheader("1 · Universe")
    universe = st.selectbox(
        "Index",
        ["NIFTY 50", "NIFTY 100", "NIFTY 500", "NIFTY Midcap 100", "NIFTY Smallcap 100",
         "All Indices", "NSE All"],
        index=0,
        help="Start with NIFTY 50 for faster loading during first run",
    )

    sector_options = ["Technology", "Financial Services", "Healthcare",
                      "Consumer Staples", "Automobile", "Energy",
                      "Industrials", "Materials", "Real Estate"]
    sector_filter = st.multiselect(
        "Sectors",
        options=sector_options,
        placeholder="All sectors (none selected = all)",
    )

    cap_filter = st.selectbox("Market Cap", ["All", "Large Cap (>₹20,000 Cr)",
                                              "Mid Cap (₹5,000–20,000 Cr)",
                                              "Small Cap (<₹5,000 Cr)"])
    st.divider()

    # ── Strategies ────────────────────────────────────────────
    st.subheader("2 · Strategies")

    STRATEGY_HELP = {
        "value":    "Finds stocks that are cheap relative to their earnings and assets. "
                    "Looks at P/E ratio, P/B ratio, and EV/EBITDA. "
                    "A low P/E means you're paying less per rupee of profit — like buying on sale.",
        "quality":  "Finds well-run, financially healthy businesses. "
                    "Looks at ROCE, ROE, low debt, and profit margins. "
                    "High quality companies tend to compound wealth over the long term.",
        "momentum": "Finds stocks that have been rising strongly in recent months. "
                    "Based on 12-month and 6-month price returns. "
                    "The idea: winners tend to keep winning (for a while).",
        "lowvol":   "Finds stocks that move less than the broader market. "
                    "Looks at Beta, standard deviation, and max drawdown. "
                    "Lower risk, steadier returns — good for conservative investors.",
        "meanrev":  "Finds stocks that have fallen sharply and may bounce back. "
                    "Uses RSI (below 35 = oversold), Bollinger Bands, and Z-score. "
                    "Contrarian strategy — buys when others are selling.",
        "holdings": "Checks who owns the stock. High promoter holding means founders "
                    "have skin in the game. Rising institutional holding signals "
                    "confidence from mutual funds and FIIs.",
    }

    use_value    = st.toggle("📉 Value Factor",         value=True,  key="tog_value",
                             help=STRATEGY_HELP["value"])
    use_quality  = st.toggle("🏆 Quality Factor",       value=True,  key="tog_quality",
                             help=STRATEGY_HELP["quality"])
    use_momentum = st.toggle("🚀 Momentum",             value=True,  key="tog_momentum",
                             help=STRATEGY_HELP["momentum"])
    use_lowvol   = st.toggle("🛡️ Low Volatility",       value=False, key="tog_lowvol",
                             help=STRATEGY_HELP["lowvol"])
    use_meanrev  = st.toggle("↩️ Mean Reversion",       value=False, key="tog_meanrev",
                             help=STRATEGY_HELP["meanrev"])
    use_holdings = st.toggle("👥 Stakeholder Holdings", value=False, key="tog_holdings",
                             help=STRATEGY_HELP["holdings"])

    with st.expander("📖 What do these mean?"):
        st.markdown("""
**📉 Value** — *Buy cheap stocks*
Screens for stocks trading below their intrinsic worth.
Key metrics: P/E ratio, P/B ratio, EV/EBITDA.
Best for: patient, long-term investors.

---
**🏆 Quality** — *Buy great businesses*
Screens for financially strong, well-managed companies.
Key metrics: ROCE, ROE, Debt/Equity, Piotroski Score.
Best for: long-term compounding.

---
**🚀 Momentum** — *Buy recent winners*
Screens for stocks with strong recent price performance.
Key metrics: 12-month return, 6-month return, 52W high proximity.
Best for: trend followers, medium-term holds.

---
**🛡️ Low Volatility** — *Buy stable stocks*
Screens for stocks that move less than the market.
Key metrics: Beta, annualised volatility, max drawdown.
Best for: conservative investors, lower drawdowns.

---
**↩️ Mean Reversion** — *Buy beaten-down stocks*
Screens for oversold stocks likely to bounce back.
Key metrics: RSI < 35, Bollinger Band position, Z-score vs 200-day MA.
Best for: short-to-medium term contrarian trades.

---
**👥 Stakeholder Holdings** — *Buy where insiders believe*
Screens for stocks with high and rising promoter / institutional ownership.
Key metrics: Promoter %, FII + DII holding %.
Best for: governance filter and conviction signal.
        """)

    st.divider()

    # ── Weights ───────────────────────────────────────────────
    st.subheader("3 · Weights")
    raw_w = {}
    if use_value:    raw_w["value"]          = st.slider("Value",          0, 100, 30, key="slid_value")
    if use_quality:  raw_w["quality"]        = st.slider("Quality",        0, 100, 30, key="slid_quality")
    if use_momentum: raw_w["momentum"]       = st.slider("Momentum",       0, 100, 25, key="slid_momentum")
    if use_lowvol:   raw_w["low_volatility"] = st.slider("Low Volatility", 0, 100, 15, key="slid_lowvol")
    if use_meanrev:  raw_w["mean_reversion"] = st.slider("Mean Reversion", 0, 100, 10, key="slid_meanrev")
    if use_holdings: raw_w["holdings"]       = st.slider("Holdings",       0, 100, 10, key="slid_holdings")

    total_raw = sum(raw_w.values())
    weights   = {k: v / total_raw for k, v in raw_w.items()} if total_raw > 0 else DEFAULT_WEIGHTS

    if raw_w:
        st.caption(f"✓ Weights normalised to 100%")
    st.divider()

    top_n      = st.slider("Show top N stocks", 10, 100, 25)
    if universe == "All Indices":
        st.warning("All Indices loads 600+ stocks — expect 3–5 minutes.", icon="⏳")
    elif universe == "NSE All":
        st.warning("NSE All loads 2000+ stocks — expect 15–30 minutes on first run.", icon="⏳")
    run_screen = st.button("🔍 Run Screen", type="primary", use_container_width=True)


# ═══════════════════════════════════════════════════════════════
# MAIN TABS
# ═══════════════════════════════════════════════════════════════
tab_screen, tab_stock, tab_lookup, tab_backtest, tab_portfolio = st.tabs(
    ["📊 Screener", "🔎 Stock Detail", "🔍 Stock Lookup", "📉 Backtest", "💼 Portfolio"]
)


# ── Helper: load all data (no cache — called only on Run Screen click) ───────
def load_data(index_name: str):
    stocks_df  = get_index_stocks(index_name)
    symbols    = stocks_df["yf_symbol"].dropna().tolist()
    meta       = get_symbol_metadata(index_name)
    closes     = _cached_close_matrix(tuple(symbols))
    metrics    = build_metrics_dataframe(symbols)
    holdings   = build_holdings_dataframe(symbols)
    return symbols, meta, closes, metrics, holdings


@st.cache_data(ttl=3600, show_spinner=False)
def load_ohlcv_dict(symbols):
    data = {}
    for sym in symbols:
        try:
            data[sym] = _cached_price(sym)
        except Exception:
            pass
    return data


def apply_filters(symbols, metrics, meta, sector_filter, cap_filter):
    filtered = []
    for sym in symbols:
        row = metrics.loc[sym] if sym in metrics.index else pd.Series()

        # Sector filter — empty list means all sectors
        if sector_filter:
            sector = str(row.get("sector", "")).strip().lower()
            if not any(s.lower() in sector for s in sector_filter):
                continue

        # Market cap filter
        mcap = row.get("market_cap")
        if mcap and cap_filter != "All":
            mcap_cr = mcap / 1e7  # convert to crores
            if "Large" in cap_filter   and mcap_cr < 20_000: continue
            if "Mid"   in cap_filter   and not (5_000 <= mcap_cr < 20_000): continue
            if "Small" in cap_filter   and mcap_cr >= 5_000: continue

        filtered.append(sym)
    return filtered


# ═══════════════════════════════════════════════════════════════
#  TAB 1 — SCREENER
# ═══════════════════════════════════════════════════════════════
with tab_screen:
    # ── Run computation only when the button is clicked ──────
    if run_screen:
        with st.spinner(f"Loading {universe} data…"):
            try:
                symbols, meta, closes, metrics, holdings = load_data(universe)
            except Exception as e:
                st.error(f"Data not ready: {e}\n\nRun `python run_pipeline.py` first.")
                st.stop()

        # Warn when the universe has more symbols than we have cached data for
        cached_count = sum(1 for s in symbols if s in closes.columns)
        if cached_count < len(symbols):
            missing = len(symbols) - cached_count
            st.info(
                f"**Data gap:** {cached_count} of {len(symbols)} stocks have downloaded data "
                f"({missing} missing). Only scored stocks will appear in results.  \n"
                f"Run `python run_pipeline.py --index \"{universe}\"` to download the rest.",
                icon="ℹ️",
            )

        # Apply filters
        filtered_syms = apply_filters(symbols, metrics, meta, sector_filter, cap_filter)
        if not filtered_syms:
            st.warning("No stocks match the selected filters.")
            st.stop()

        filtered_closes  = closes[
            [s for s in filtered_syms if s in closes.columns]
        ].dropna(how="all", axis=1) if not closes.empty else pd.DataFrame()

        filtered_metrics  = metrics.reindex(filtered_syms)
        filtered_holdings = holdings.reindex(filtered_syms)

        with st.spinner("Computing factor scores…"):
            val_s    = score_value(filtered_metrics)    if use_value    else None
            qual_s   = score_quality(filtered_metrics)  if use_quality  else None
            mom_s    = score_momentum(filtered_closes)  if use_momentum and not filtered_closes.empty else None
            lv_s     = score_lowvol(filtered_closes)    if use_lowvol   and not filtered_closes.empty else None
            hold_s   = score_holdings(filtered_holdings) if use_holdings else None

            mr_s = None
            if use_meanrev and not filtered_closes.empty:
                ohlcv_dict = load_ohlcv_dict(filtered_syms)
                mr_s = score_meanrev(filtered_closes, ohlcv_dict)

            results = compute_composite(
                symbols=filtered_syms,
                weights=weights,
                value_scores=val_s,
                quality_scores=qual_s,
                momentum_scores=mom_s,
                lowvol_scores=lv_s,
                meanrev_scores=mr_s,
                holdings_scores=hold_s,
            )

        top_results = results.head(top_n).copy()
        top_results.insert(0, "name",
            top_results.index.map(lambda s: meta.get(s, {}).get("name", s)))

        # Persist to session state so the table survives tab switches
        st.session_state["results"]           = results
        st.session_state["top_results"]       = top_results
        st.session_state["metrics"]           = metrics
        st.session_state["closes"]            = closes
        st.session_state["meta"]              = meta
        st.session_state["symbols"]           = symbols
        st.session_state["screened_universe"] = universe
        st.session_state["screened_count"]    = len(filtered_syms)
        st.session_state["strategies_active"] = sum([use_value, use_quality, use_momentum,
                                                      use_lowvol, use_meanrev, use_holdings])

    # ── Display results whenever they exist in session state ──
    if "top_results" in st.session_state:
        results     = st.session_state["results"]
        top_results = st.session_state["top_results"]
        metrics     = st.session_state["metrics"]
        meta        = st.session_state["meta"]

        # ── Summary metrics ──────────────────────────────────────
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Universe",          st.session_state.get("screened_universe", universe))
        col2.metric("Stocks Screened",   st.session_state.get("screened_count", "—"))
        col3.metric("Strategies Active", st.session_state.get("strategies_active", "—"))
        col4.metric("Showing",           f"Top {len(top_results)}")

        st.divider()

        # ── Results tabs ─────────────────────────────────────────
        r_tab1, r_tab2, r_tab3, r_tab4 = st.tabs(["📋 Ranked Table", "🌡️ Heatmap", "📈 Score Distribution", "💰 Portfolio Builder"])

        with r_tab1:
            score_cols = [c for c in top_results.columns if c.endswith("_score")]
            display_df = top_results[["rank", "name"] + score_cols].copy()
            display_df.columns = [c.replace("_score", "").replace("_", " ").title()
                                   for c in display_df.columns]
            for c in display_df.columns:
                if c not in ["Rank", "Name"] and pd.api.types.is_numeric_dtype(display_df[c]):
                    display_df[c] = display_df[c].round(1)

            st.dataframe(
                display_df,
                use_container_width=True,
                height=600,
                column_config={
                    "Composite": st.column_config.ProgressColumn(
                        "Overall Score", min_value=0, max_value=100,
                        help="Weighted combination of all active strategies. Higher = better overall rank."
                    ),
                    "Value": st.column_config.NumberColumn(
                        "Value 📉", format="%.1f",
                        help="Score based on P/E, P/B, EV/EBITDA. High score = cheap stock."
                    ),
                    "Quality": st.column_config.NumberColumn(
                        "Quality 🏆", format="%.1f",
                        help="Score based on ROCE, ROE, debt, margins, Piotroski. High = strong business."
                    ),
                    "Momentum": st.column_config.NumberColumn(
                        "Momentum 🚀", format="%.1f",
                        help="Score based on 12M, 6M price return. High = recent strong performer."
                    ),
                    "Lowvol": st.column_config.NumberColumn(
                        "Low Vol 🛡️", format="%.1f",
                        help="Score based on Beta and volatility. High = stable, low-risk stock."
                    ),
                    "Meanrev": st.column_config.NumberColumn(
                        "Mean Rev ↩️", format="%.1f",
                        help="Score based on RSI, Bollinger Bands. High = oversold, potential bounce."
                    ),
                    "Holdings": st.column_config.NumberColumn(
                        "Holdings 👥", format="%.1f",
                        help="Score based on promoter and institutional holding %. High = insiders confident."
                    ),
                }
            )

            screened_universe = st.session_state.get("screened_universe", universe)
            xlsx_bytes = _build_screener_excel(
                top_results, weights, screened_universe, sector_filter, cap_filter,
            )
            st.download_button(
                "⬇ Download Excel",
                xlsx_bytes,
                f"quantscreen_{screened_universe.replace(' ','_').lower()}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with r_tab2:
            factor_cols = [c for c in results.columns
                           if c.endswith("_score") and c != "composite_score"]
            if factor_cols:
                hmap = top_results[factor_cols].head(30).copy()
                hmap.columns = [c.replace("_score", "").replace("_", " ").title()
                                 for c in hmap.columns]
                fig = px.imshow(
                    hmap.T,
                    color_continuous_scale="RdYlGn",
                    zmin=0, zmax=100,
                    aspect="auto",
                    title=f"Factor Score Heatmap — Top {min(30, len(top_results))} Stocks",
                )
                fig.update_layout(height=420, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig, use_container_width=True)

        with r_tab3:
            fig = go.Figure()
            fig.add_trace(go.Histogram(
                x=results["composite_score"],
                nbinsx=30,
                marker_color="#3b82f6",
                name="All stocks"
            ))
            fig.add_vline(
                x=top_results["composite_score"].min(),
                line_dash="dash", line_color="red",
                annotation_text=f"Top {len(top_results)} cutoff"
            )
            fig.update_layout(
                title="Composite Score Distribution",
                xaxis_title="Score", yaxis_title="# Stocks",
                height=360, margin=dict(l=0,r=0,t=40,b=0)
            )
            st.plotly_chart(fig, use_container_width=True)

        with r_tab4:
            closes_df  = st.session_state.get("closes", pd.DataFrame())
            last_prices = closes_df.iloc[-1].to_dict() if not closes_df.empty else {}

            pb_col1, pb_col2, pb_col3 = st.columns(3)
            with pb_col1:
                capital = st.number_input(
                    "Capital (₹)", min_value=1_000, max_value=100_000_000,
                    value=100_000, step=1_000, format="%d",
                )
            with pb_col2:
                max_stocks = len(top_results)
                alloc_n = st.slider("Number of stocks", 1, max_stocks, min(10, max_stocks),
                                    key="alloc_n")
            with pb_col3:
                weighting = st.radio("Weighting", ["Equal", "Score weighted"], horizontal=True)

            alloc_syms = top_results.index[:alloc_n].tolist()

            # Build target weights
            if weighting == "Score weighted":
                scores     = top_results.loc[alloc_syms, "composite_score"]
                total_sc   = scores.sum()
                alloc_w    = (scores / total_sc).to_dict() if total_sc > 0 else {s: 1/alloc_n for s in alloc_syms}
            else:
                alloc_w = {s: 1 / alloc_n for s in alloc_syms}

            prices      = {s: last_prices.get(s, 0) for s in alloc_syms}
            no_price    = [s for s in alloc_syms if prices[s] <= 0]
            if no_price:
                st.warning(f"No price data for: {', '.join(no_price)} — skipped.")
                alloc_syms = [s for s in alloc_syms if prices[s] > 0]
                tw = sum(alloc_w[s] for s in alloc_syms)
                alloc_w = {s: alloc_w[s] / tw for s in alloc_syms} if tw > 0 else {}

            if not alloc_syms:
                st.error("No price data available for any selected stock.")
            else:
                # Floor allocation
                targets    = {s: capital * alloc_w[s] for s in alloc_syms}
                shares     = {}
                remainders = {}
                for s in alloc_syms:
                    p          = prices[s]
                    q          = targets[s] / p
                    shares[s]  = int(q)
                    remainders[s] = q - int(q)

                spent    = sum(shares[s] * prices[s] for s in alloc_syms)
                leftover = capital - spent

                # Largest-remainder top-up: buy one extra share where fractional
                # remainder is highest, until cash runs out
                for s in sorted(alloc_syms, key=lambda s: remainders[s], reverse=True):
                    if leftover >= prices[s]:
                        shares[s] += 1
                        leftover  -= prices[s]

                # Build display table
                rows = []
                for s in alloc_syms:
                    p     = prices[s]
                    n     = shares[s]
                    value = n * p
                    rows.append({
                        "Ticker":    s,
                        "Company":   meta.get(s, {}).get("name", s),
                        "Price (₹)": round(p, 2),
                        "Shares":    n,
                        "Value (₹)": round(value, 2),
                        "Weight %":  round(value / capital * 100, 1),
                    })

                alloc_df      = pd.DataFrame(rows).set_index("Ticker")
                total_invested = alloc_df["Value (₹)"].sum()

                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Capital",     f"₹{capital:,.0f}")
                s2.metric("Invested",    f"₹{total_invested:,.0f}")
                s3.metric("Leftover",    f"₹{leftover:,.2f}")
                s4.metric("Utilisation", f"{total_invested / capital * 100:.1f}%")

                st.divider()
                st.dataframe(
                    alloc_df,
                    use_container_width=True,
                    column_config={
                        "Price (₹)": st.column_config.NumberColumn(format="₹%.2f"),
                        "Shares":    st.column_config.NumberColumn(format="%d"),
                        "Value (₹)": st.column_config.NumberColumn(format="₹%.2f"),
                        "Weight %":  st.column_config.ProgressColumn(
                            "Weight %", min_value=0, max_value=100, format="%.1f%%"
                        ),
                    }
                )

                alloc_xlsx = _build_alloc_excel(
                    alloc_df, weights, capital, weighting,
                    st.session_state.get("screened_universe", universe),
                )
                st.download_button(
                    "⬇ Download Allocation Excel",
                    alloc_xlsx,
                    "portfolio_allocation.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    else:
        # ── No results yet — show getting started guide ───────
        st.info("👈 Configure your strategy in the sidebar, then click **Run Screen**.")
        st.markdown("""
        **Getting started:**
        1. Run `python run_pipeline.py` in your terminal first to download data (one-time, ~20 min)
        2. Choose your index universe and sector
        3. Toggle strategies on/off and set weights
        4. Click Run Screen
        """)

        st.divider()
        st.subheader("📚 Strategy Guide")
        st.caption("Understanding what each strategy does and how it scores stocks.")

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("""
#### 📉 Value Factor
**What it does:** Finds stocks that are *cheap* relative to their earnings, book value, and cash flows.

**Think of it as:** Hunting for a ₹100 note selling for ₹70.

**Metrics used:**
- **P/E Ratio** — Price ÷ Earnings per share. Lower = cheaper.
- **P/B Ratio** — Price ÷ Book value. Below 1 = trading below asset value.
- **EV/EBITDA** — Enterprise value ÷ Operating profit. Lower = better deal.
- **ROE** — Return on equity. Higher = more efficient use of capital.

**Best for:** Long-term, patient investors willing to wait for the market to recognise value.

---
#### 🛡️ Low Volatility
**What it does:** Finds stocks that don't swing wildly — they rise and fall less than the market.

**Think of it as:** Choosing the calm lane on the highway.

**Metrics used:**
- **Beta** — How much the stock moves vs NIFTY. Beta < 1 = less volatile.
- **Annualised Volatility** — Standard deviation of daily returns over 1 year.
- **Max Drawdown** — Worst peak-to-trough loss in the past year.

**Best for:** Conservative investors, capital preservation, sleeping well at night.
""")

        with c2:
            st.markdown("""
#### 🏆 Quality Factor
**What it does:** Finds financially strong, well-run businesses that are likely to keep growing profitably.

**Think of it as:** Finding companies that run like a well-oiled machine.

**Metrics used:**
- **ROCE** — Return on Capital Employed. How efficiently does the company use its money?
- **ROE** — Return on Equity. How much profit per rupee of shareholder money?
- **Debt/Equity** — Lower = less financial risk.
- **Operating Margin** — What % of revenue becomes operating profit?
- **Piotroski F-Score** — A 9-point checklist: profitability, leverage, efficiency. Score 7–9 = strong.

**Best for:** Long-term wealth compounding. Quality companies rarely go bankrupt.

---
#### ↩️ Mean Reversion
**What it does:** Finds stocks that have fallen sharply and are statistically due for a bounce.

**Think of it as:** A rubber band — the more you stretch it, the harder it snaps back.

**Metrics used:**
- **RSI (Relative Strength Index)** — Below 30–35 = oversold. The stock has been sold too aggressively.
- **Bollinger Bands** — Price near or below the lower band = statistically cheap.
- **Z-score vs 200-day MA** — How far below the long-term average is the stock?

**Best for:** Short-to-medium term contrarian trades. Higher risk, higher reward.
""")

        with c3:
            st.markdown("""
#### 🚀 Momentum
**What it does:** Finds stocks that have been rising strongly — and bets they'll keep going.

**Think of it as:** Catching a wave while it's still building.

**Metrics used:**
- **12-1 Month Return** — Return over last 12 months, skipping last month (avoids short-term reversal).
- **6-Month Return** — Medium-term strength.
- **52-Week High Proximity** — How close is the stock to its all-time high this year? Near the top = strong.

**Best for:** Trend followers. Works best in bull markets, loses badly in sharp reversals.

---
#### 👥 Stakeholder Holdings
**What it does:** Checks whether the people who know the company best — promoters and institutions — are holding or increasing their stake.

**Think of it as:** If the chef eats their own food, it's probably good.

**Metrics used:**
- **Promoter Holding %** — Founders and management holding their own shares. High = confidence.
- **Institutional Holding %** — Mutual funds, insurance, FIIs. Rising = professional conviction.

**Best for:** Governance filter. Use alongside other factors to avoid companies where insiders are quietly selling.
""")

        st.divider()
        st.subheader("🎯 Suggested Combinations")
        st.caption("Click **Apply** to load a preset into the sidebar, then hit **Run Screen**.")

        preset_order = ["qmv", "qm", "qvl", "wealth_builder", "conservative", "contrarian"]
        row1, row2 = preset_order[:3], preset_order[3:]

        cols1 = st.columns(3)
        for col, key in zip(cols1, row1):
            p = PRESETS[key]
            with col:
                with st.container(border=True):
                    st.markdown(f"**{p['label']}** `{p['tag']}`")
                    st.caption(p["formula"])
                    st.write(p["summary"])
                    st.button("Apply", key=f"preset_{key}",
                              on_click=_apply_preset, args=(key,),
                              use_container_width=True)

        cols2 = st.columns(3)
        for col, key in zip(cols2, row2):
            p = PRESETS[key]
            with col:
                with st.container(border=True):
                    st.markdown(f"**{p['label']}** `{p['tag']}`")
                    st.caption(p["formula"])
                    st.write(p["summary"])
                    st.button("Apply", key=f"preset_{key}",
                              on_click=_apply_preset, args=(key,),
                              use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  TAB 2 — STOCK DETAIL  (requires screener run)
# ═══════════════════════════════════════════════════════════════
with tab_stock:
    if "results" not in st.session_state:
        st.info("Run a screen first (Tab 1) to populate stock data.")
    else:
        results = st.session_state["results"]
        metrics = st.session_state["metrics"]
        meta    = st.session_state["meta"]

        selected = st.selectbox(
            "Select stock",
            options=results.index.tolist(),
            format_func=lambda s: f"{s}  —  {meta.get(s, {}).get('name', '')}",
        )

        if selected and selected in metrics.index:
            factor_row = results.loc[selected] if selected in results.index else None
            _render_stock_detail(selected, metrics.loc[selected], meta, factor_row=factor_row)


# ═══════════════════════════════════════════════════════════════
#  TAB 3 — STOCK LOOKUP  (no screener required)
# ═══════════════════════════════════════════════════════════════
with tab_lookup:
    lookup_meta    = _load_lookup_meta()
    lookup_symbols = sorted(lookup_meta.keys())

    lookup_sel = st.selectbox(
        "Search by ticker or company name",
        options=[""] + lookup_symbols,
        format_func=lambda s: (
            f"{s}  —  {lookup_meta.get(s, {}).get('name', '')}" if s else "— select a stock —"
        ),
    )

    if lookup_sel:
        with st.spinner(f"Loading {lookup_sel}…"):
            try:
                mdf = build_metrics_dataframe([lookup_sel])
                lookup_row = mdf.loc[lookup_sel] if lookup_sel in mdf.index else pd.Series()
            except Exception:
                lookup_row = pd.Series()
        _render_stock_detail(lookup_sel, lookup_row, lookup_meta)


# ═══════════════════════════════════════════════════════════════
#  TAB 4 — BACKTESTING
# ═══════════════════════════════════════════════════════════════
with tab_backtest:
    st.subheader("Strategy Backtester")
    st.caption("Simulates your current strategy configuration on historical NSE data.")

    if "symbols" not in st.session_state:
        st.info("Run a screen first (Tab 1) to load data, then come back here to backtest.")
    else:
        bt_col1, bt_col2, bt_col3 = st.columns(3)
        with bt_col1:
            bt_years = st.selectbox("Backtest Period", [1, 2, 3, 5, 7, 10], index=2,
                                    format_func=lambda y: f"{y} Year{'s' if y>1 else ''}")
        with bt_col2:
            bt_freq  = st.selectbox("Rebalancing", ["Q — Quarterly", "M — Monthly", "A — Annual"],
                                    index=0)
            freq_map = {"Q": "Q", "M": "M", "A": "A"}
            rebal_freq = freq_map[bt_freq[0]]
        with bt_col3:
            bt_size  = st.slider("Portfolio Size (Top N)", 5, 50, 20)

        run_bt = st.button("▶ Run Backtest", type="primary")

        if run_bt:
            with st.spinner("Running backtest… this may take 30–60 seconds."):
                try:
                    bt_result = run_backtest(
                        symbols        = st.session_state["symbols"],
                        metrics        = st.session_state["metrics"],
                        weights        = weights,
                        years          = bt_years,
                        rebalance_freq = rebal_freq,
                        portfolio_size = bt_size,
                    )

                    # ── Metrics row ──────────────────────────────
                    st.divider()
                    bm1, bm2, bm3, bm4, bm5, bm6 = st.columns(6)
                    bm1.metric("Strategy CAGR",
                               f"{bt_result['cagr']}%",
                               delta=f"{bt_result['alpha']:+.1f}% vs benchmark")
                    bm2.metric("Benchmark CAGR",  f"{bt_result['benchmark_cagr']}%")
                    bm3.metric("Total Return",     f"{bt_result['total_return']}%")
                    bm4.metric("Sharpe Ratio",     bt_result["sharpe"])
                    bm5.metric("Sortino Ratio",    bt_result["sortino"])
                    bm6.metric("Max Drawdown",     f"{bt_result['max_drawdown']}%")

                    st.divider()

                    # ── Equity curve ─────────────────────────────
                    eq   = bt_result["equity_curve"]
                    bm   = bt_result["benchmark_curve"]

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=eq.index, y=eq.values,
                        name="Strategy", mode="lines",
                        line=dict(color="#2563eb", width=2.5)
                    ))
                    if not bm.empty:
                        bm_aligned = bm.reindex(
                            bm.index[bm.index >= eq.index[0]]
                        )
                        fig.add_trace(go.Scatter(
                            x=bm_aligned.index, y=bm_aligned.values,
                            name="NIFTY 500", mode="lines",
                            line=dict(color="#94a3b8", width=1.5, dash="dot")
                        ))

                    fig.update_layout(
                        title=f"Equity Curve — {bt_years}Y Backtest  (Base = ₹100)",
                        xaxis_title="Date",
                        yaxis_title="Portfolio Value (₹)",
                        height=420,
                        hovermode="x unified",
                        legend=dict(orientation="h", y=1.05),
                        margin=dict(l=0,r=0,t=50,b=0),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # ── Drawdown chart ────────────────────────────
                    peak    = eq.cummax()
                    drawdown = ((eq - peak) / peak) * 100
                    fig_dd = go.Figure()
                    fig_dd.add_trace(go.Scatter(
                        x=drawdown.index, y=drawdown.values,
                        fill="tozeroy", name="Drawdown",
                        line=dict(color="#ef4444"), fillcolor="rgba(239,68,68,0.15)"
                    ))
                    fig_dd.update_layout(
                        title="Drawdown Chart (%)",
                        height=240,
                        margin=dict(l=0,r=0,t=40,b=0),
                        yaxis_title="Drawdown %",
                    )
                    st.plotly_chart(fig_dd, use_container_width=True)

                    # ── Rebalance log ─────────────────────────────
                    with st.expander("📋 Rebalancing History"):
                        log_df = pd.DataFrame(bt_result["rebalance_log"])
                        if not log_df.empty:
                            log_df["stocks"] = log_df["stocks"].apply(
                                lambda x: ", ".join(x)
                            )
                            st.dataframe(log_df, use_container_width=True)

                    # ── Disclaimer ────────────────────────────────
                    st.caption(
                        "⚠️ Disclaimer: Backtest results are hypothetical and do not guarantee future returns. "
                        "Fundamental data is not fully point-in-time — results may overstate actual performance. "
                        "This is not SEBI-registered investment advice."
                    )

                except Exception as e:
                    st.error(f"Backtest failed: {e}")
                    st.info("Make sure you have downloaded price data via `python run_pipeline.py`.")

# ═══════════════════════════════════════════════════════════════
# PORTFOLIO TRACKER TAB
# ═══════════════════════════════════════════════════════════════
init_db()

with tab_portfolio:
    st.subheader("💼 Portfolio Tracker")

    # ── helpers ─────────────────────────────────────────────────

    def _fetch_prices(symbols):
        import yfinance as yf
        tickers = [s if s.endswith(".NS") or s.endswith(".BO") else s + ".NS" for s in symbols]
        prices = {}
        for sym, ticker in zip(symbols, tickers):
            try:
                info = yf.Ticker(ticker).fast_info
                prices[sym] = float(info.last_price)
            except Exception:
                prices[sym] = None
        return prices

    def _pnl_color(val):
        if val is None:
            return "color: gray"
        return "color: #16a34a; font-weight:600" if val >= 0 else "color: #dc2626; font-weight:600"

    # ── Load all portfolios ──────────────────────────────────────
    portfolios = list_portfolios()
    port_ids   = [p["id"] for p in portfolios]

    # ── New portfolio button (top-right) ─────────────────────────
    _, new_col = st.columns([5, 1])
    with new_col:
        with st.popover("＋ New", use_container_width=True):
            new_name = st.text_input("Portfolio name", key="pf_new_name")
            if st.button("Create", key="pf_create_btn") and new_name.strip():
                create_portfolio(new_name.strip())
                st.rerun()

    if not portfolios:
        st.info("No portfolios yet. Create one using the **＋ New** button above.")
        st.stop()

    # Ensure a valid selection exists
    if "pf_selected_id" not in st.session_state or st.session_state["pf_selected_id"] not in port_ids:
        st.session_state["pf_selected_id"] = port_ids[0]

    # ── Portfolio cards ──────────────────────────────────────────
    n_cols = min(3, len(portfolios))
    card_cols = st.columns(n_cols)
    for i, p in enumerate(portfolios):
        is_sel = st.session_state["pf_selected_id"] == p["id"]
        with card_cols[i % n_cols]:
            with st.container(border=True):
                st.markdown(f"**{p['name']}**" + (" ✓" if is_sel else ""))
                st.caption(f"Since {p['created_at'][:10]}")
                if st.button(
                    "Viewing" if is_sel else "Open →",
                    key=f"pf_card_{p['id']}",
                    use_container_width=True,
                    type="primary" if is_sel else "secondary",
                ):
                    st.session_state["pf_selected_id"] = p["id"]
                    st.rerun()

    st.divider()

    # ── Selected portfolio header (name + rename/delete) ─────────
    chosen_id   = st.session_state["pf_selected_id"]
    chosen_port = next(p for p in portfolios if p["id"] == chosen_id)
    chosen_name = chosen_port["name"]

    name_col, act_col1, act_col2 = st.columns([6, 1, 1])
    with name_col:
        st.markdown(f"### {chosen_name}")
    with act_col1:
        with st.popover("✏️ Rename", use_container_width=True):
            rn_val = st.text_input("New name", value=chosen_name, key="pf_rename_val")
            if st.button("Save", key="pf_rename_btn") and rn_val.strip() and rn_val.strip() != chosen_name:
                rename_portfolio(chosen_id, rn_val.strip())
                st.rerun()
    with act_col2:
        with st.popover("🗑️ Delete", use_container_width=True):
            st.warning(f"Delete **{chosen_name}** and all its holdings?")
            if st.button("Yes, delete", key="pf_delete_btn"):
                delete_portfolio(chosen_id)
                st.session_state.pop("pf_selected_id", None)
                st.session_state.pop(f"pf_prices_{chosen_id}", None)
                st.rerun()

    st.divider()

    # ── strategy note ────────────────────────────────────────────
    with st.expander("📋 Strategy / Factor Notes", expanded=bool(chosen_port["strategy_note"])):
        note_val = st.text_area(
            "Describe the strategy, factors, and weights used for this portfolio",
            value=chosen_port["strategy_note"],
            height=100,
            key=f"pf_note_{chosen_id}",
            placeholder="e.g. QMV preset — Quality 35%, Momentum 40%, Value 25%. Screened NIFTY 500, top 15 stocks, Jan 2026.",
        )
        if st.button("Save note", key="pf_note_save"):
            update_strategy_note(chosen_id, note_val)
            st.success("Saved.")

    # ── load holdings ────────────────────────────────────────────
    holdings = list_holdings(chosen_id)

    # ── fetch / refresh prices ───────────────────────────────────
    pf_prices_key = f"pf_prices_{chosen_id}"
    refresh_col, _ = st.columns([1, 6])
    with refresh_col:
        if st.button("🔄 Refresh Prices", key="pf_refresh"):
            st.session_state.pop(pf_prices_key, None)

    if holdings and pf_prices_key not in st.session_state:
        with st.spinner("Fetching current prices…"):
            syms = list({h["symbol"] for h in holdings})
            st.session_state[pf_prices_key] = _fetch_prices(syms)

    prices = st.session_state.get(pf_prices_key, {})

    # ── summary metrics ──────────────────────────────────────────
    if holdings:
        total_invested = sum(h["quantity"] * h["purchase_price"] for h in holdings)
        total_current  = sum(
            h["quantity"] * (prices.get(h["symbol"]) or h["purchase_price"])
            for h in holdings
        )
        total_pnl_rs  = total_current - total_invested
        total_pnl_pct = (total_pnl_rs / total_invested * 100) if total_invested else 0
        pnl_color = "#16a34a" if total_pnl_rs >= 0 else "#dc2626"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Invested", f"₹{total_invested:,.0f}")
        m2.metric("Current Value",  f"₹{total_current:,.0f}")
        m3.metric("P&L (₹)", f"₹{total_pnl_rs:+,.0f}")
        m4.metric("P&L (%)", f"{total_pnl_pct:+.2f}%")

        st.divider()

    # ── holdings table ───────────────────────────────────────────
    if holdings:
        rows = []
        for h in holdings:
            cur = prices.get(h["symbol"])
            invested = h["quantity"] * h["purchase_price"]
            cur_val  = h["quantity"] * cur if cur is not None else None
            pnl_rs   = (cur_val - invested) if cur_val is not None else None
            pnl_pct  = (pnl_rs / invested * 100) if (pnl_rs is not None and invested) else None
            rows.append({
                "_id":              h["id"],
                "Symbol":           h["symbol"],
                "Qty":              h["quantity"],
                "Buy Price (₹)":    h["purchase_price"],
                "Total Buy (₹)":    invested,
                "Buy Date":         h["purchase_date"],
                "Current (₹)":      cur,
                "Total Current (₹)": cur_val,
                "Total P&L (₹)":    pnl_rs,
                "P&L (%)":          pnl_pct,
            })

        df = pd.DataFrame(rows)

        # render with HTML for color
        def _render_cur(val):
            if val is None:
                return '<span style="color:gray">—</span>'
            return f'<span style="color:#6b7280">₹{val:,.2f}</span>'

        def _render_total_buy(val):
            return f"₹{val:,.0f}"

        def _render_pnl_rs(row):
            v = row["Total P&L (₹)"]
            if v is None:
                return '<span style="color:gray">—</span>'
            sign = "+" if v >= 0 else ""
            return f'<span style="{_pnl_color(v)}">₹{sign}{v:,.0f}</span>'

        def _render_pnl_pct(row):
            v = row["P&L (%)"]
            if v is None:
                return '<span style="color:gray">—</span>'
            sign = "+" if v >= 0 else ""
            return f'<span style="{_pnl_color(v)}">{sign}{v:.2f}%</span>'

        def _render_total_cur(val):
            if val is None:
                return '<span style="color:gray">—</span>'
            return f"₹{val:,.0f}"

        display_df = df.drop(columns=["_id"]).copy()
        display_df["Total Buy (₹)"]      = display_df["Total Buy (₹)"].apply(_render_total_buy)
        display_df["Current (₹)"]        = display_df["Current (₹)"].apply(_render_cur)
        display_df["Total Current (₹)"]  = display_df["Total Current (₹)"].apply(_render_total_cur)
        display_df["Total P&L (₹)"]      = df.apply(_render_pnl_rs,  axis=1)
        display_df["P&L (%)"]            = df.apply(_render_pnl_pct, axis=1)

        st.write(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)

        # per-row delete
        st.markdown("**Remove a holding:**")
        del_labels = [f"{h['symbol']} — {h['quantity']} @ ₹{h['purchase_price']}" for h in holdings]
        del_sel = st.selectbox("Select holding to remove", ["— select —"] + del_labels, key="pf_del_sel")
        if del_sel != "— select —" and st.button("Remove", key="pf_del_btn"):
            idx = del_labels.index(del_sel)
            delete_holding(holdings[idx]["id"])
            st.session_state.pop(pf_prices_key, None)
            st.rerun()

    else:
        st.info("No holdings yet. Add your first stock below.")

    st.divider()

    # ── add holding form ─────────────────────────────────────────
    _pf_meta = _load_lookup_meta()
    _pf_syms = sorted(_pf_meta.keys())

    with st.expander("➕ Add Stock", expanded=not holdings):
        with st.form("pf_add_form", clear_on_submit=True):
            add_sym = st.selectbox(
                "NSE Symbol",
                options=[""] + _pf_syms,
                format_func=lambda s: (
                    f"{s}  —  {_pf_meta.get(s, {}).get('name', '')}" if s else "— type to search —"
                ),
                key="pf_add_sym",
            )
            fc2, fc3, fc4 = st.columns(3)
            add_qty   = fc2.number_input("Quantity", min_value=0.0, step=1.0, format="%.2f")
            add_price = fc3.number_input("Buy Price (₹)", min_value=0.0, step=0.01, format="%.2f")
            add_date  = fc4.date_input("Buy Date", value=datetime.today())
            submitted = st.form_submit_button("Add to Portfolio")
            if submitted:
                if not add_sym:
                    st.error("Please select a stock.")
                elif add_qty <= 0:
                    st.error("Quantity must be greater than zero.")
                elif add_price <= 0:
                    st.error("Buy price must be greater than zero.")
                else:
                    add_holding(chosen_id, add_sym, add_qty, add_price, str(add_date))
                    st.session_state.pop(pf_prices_key, None)
                    st.rerun()
