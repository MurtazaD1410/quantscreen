# run_pipeline.py — One-click data refresh script
# Run this once before using the app, then every morning to keep data fresh.
#
# Usage:
#   python run_pipeline.py                             ← NIFTY 50 (fast, ~5 min)
#   python run_pipeline.py --index "NIFTY 500"         ← 500 stocks (~30 min)
#   python run_pipeline.py --index "NIFTY Midcap 100"  ← 100 mid-cap stocks
#   python run_pipeline.py --index "NIFTY Smallcap 100"← 100 small-cap stocks
#   python run_pipeline.py --index "All Indices"       ← ~600 deduplicated stocks
#   python run_pipeline.py --index "NSE All"           ← all 2100+ NSE stocks (~3 hrs)
#   python run_pipeline.py --quick                     ← prices only, skip fundamentals

import sys
import time
import argparse

sys.stdout.reconfigure(encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description="QuantScreen India — Data Pipeline")
    parser.add_argument("--index",  default="NIFTY 50",
                        help="Index to download: 'NIFTY 50', 'NIFTY 100', 'NIFTY 500', "
                             "'NIFTY Midcap 100', 'NIFTY Smallcap 100', 'All Indices', 'NSE All'")
    parser.add_argument("--quick",  action="store_true",
                        help="Only refresh prices (skip fundamentals)")
    parser.add_argument("--force",  action="store_true",
                        help="Force re-download even if data is fresh")
    args = parser.parse_args()

    print("=" * 55)
    print("  QuantScreen India — Data Pipeline")
    print(f"  Index    : {args.index}")
    print(f"  Quick    : {args.quick}")
    print(f"  Force    : {args.force}")
    print("=" * 55)

    # ── Step 1: Universe ──────────────────────────────────────
    print("\n[1/5] Fetching stock universe from NSE…")
    from pipeline.universe import get_index_stocks
    stocks = get_index_stocks(args.index)
    symbols = stocks["yf_symbol"].dropna().tolist()
    print(f"      ✓ {len(symbols)} stocks in {args.index}")

    # ── Step 2: Price data ────────────────────────────────────
    from config import YEARS_OF_HISTORY
    from pipeline.price_data import download_price_history
    print(f"\n[2/5] Downloading price history ({YEARS_OF_HISTORY} years)…")
    print(      "      First run: ~15–20 min. Subsequent runs: ~2–3 min.")
    t0 = time.time()
    failed_prices = download_price_history(symbols, years=YEARS_OF_HISTORY, force=args.force)
    elapsed = time.time() - t0
    print(f"      ✓ Done in {elapsed/60:.1f} min. "
          f"Failed: {len(failed_prices)} stocks.")

    if args.quick:
        print("\n[--quick mode] Skipping fundamentals and holdings.")
        print("\n✅ Quick refresh complete. Run the app with:")
        print("   streamlit run app/main.py")
        return

    # ── Step 3: Fundamentals ──────────────────────────────────
    print(f"\n[3/5] Downloading fundamental data…")
    from pipeline.fundamentals import download_fundamentals

    failed_fund = []
    total_fund  = len(symbols)

    for i, sym in enumerate(symbols, 1):
        try:
            download_fundamentals(sym, force=args.force)
        except Exception:
            failed_fund.append(sym)
        if i % 25 == 0:
            print(f"      [{i}/{total_fund}] done…")

    print(f"      ✓ Done. Failed: {len(failed_fund)} stocks.")

    # ── Step 4: Shareholding ──────────────────────────────────
    print(f"\n[4/5] Extracting shareholding data…")
    from pipeline.shareholding import build_holdings_dataframe
    import os
    from config import DATA_DIR
    holdings = build_holdings_dataframe(symbols)
    out_path = os.path.join(DATA_DIR, "processed", "holdings.csv")
    holdings.to_csv(out_path)
    print(f"      ✓ Holdings saved → {out_path}")

    # ── Step 5: Pre-compute metrics dataframe ─────────────────
    print(f"\n[5/5] Pre-computing screener metrics…")
    from pipeline.fundamentals import build_metrics_dataframe
    metrics_df = build_metrics_dataframe(symbols)
    metrics_path = os.path.join(DATA_DIR, "processed", "metrics.parquet")
    metrics_df.to_parquet(metrics_path)
    print(f"      ✓ Metrics saved → {metrics_path} ({len(metrics_df)} stocks)")

    print("\n" + "=" * 55)
    print("  ✅ Data refresh complete!")
    print("  Run the app with:")
    print("     streamlit run app/main.py")
    print("=" * 55)


if __name__ == "__main__":
    main()
