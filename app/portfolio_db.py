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
