import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database", "portfolios.db"
)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                strategy_note TEXT    NOT NULL DEFAULT '',
                created_at    TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id   INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                symbol         TEXT    NOT NULL,
                quantity       REAL    NOT NULL,
                purchase_price REAL    NOT NULL,
                purchase_date  TEXT    NOT NULL
            )
        """)


def list_portfolios():
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM portfolios ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]


def create_portfolio(name):
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO portfolios (name, strategy_note, created_at) VALUES (?, '', ?)",
            (name, datetime.now().isoformat())
        )
        return cur.lastrowid


def rename_portfolio(portfolio_id, new_name):
    with _conn() as conn:
        conn.execute("UPDATE portfolios SET name = ? WHERE id = ?", (new_name, portfolio_id))


def update_strategy_note(portfolio_id, note):
    with _conn() as conn:
        conn.execute("UPDATE portfolios SET strategy_note = ? WHERE id = ?", (note, portfolio_id))


def delete_portfolio(portfolio_id):
    with _conn() as conn:
        conn.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))


def list_holdings(portfolio_id):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holdings WHERE portfolio_id = ? ORDER BY symbol",
            (portfolio_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_holding(portfolio_id, symbol, quantity, purchase_price, purchase_date):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO holdings (portfolio_id, symbol, quantity, purchase_price, purchase_date)"
            " VALUES (?, ?, ?, ?, ?)",
            (portfolio_id, symbol.strip().upper(), quantity, purchase_price, purchase_date)
        )


def delete_holding(holding_id):
    with _conn() as conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
