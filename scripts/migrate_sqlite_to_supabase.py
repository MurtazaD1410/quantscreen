"""
One-time migration: SQLite portfolios.db -> Supabase.
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
        print(f"  Portfolio '{p['name']}': old id {p['id']} -> new id {new_id}")

    holdings = [dict(r) for r in conn.execute("SELECT * FROM holdings").fetchall()]
    print(f"\nFound {len(holdings)} holding(s) to migrate.")

    for h in holdings:
        new_pid = old_to_new.get(h["portfolio_id"])
        if new_pid is None:
            print(f"  WARN: holding id {h['id']} references missing portfolio -- skipped")
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
