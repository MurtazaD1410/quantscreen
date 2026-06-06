# engine/holdings_factor.py — Stakeholder Holdings factor scoring

import pandas as pd


def score_holdings(holdings: pd.DataFrame) -> pd.Series:
    """
    Scores stocks on Stakeholder Holdings quality (0–100).

    Signals:
      - Higher insider (promoter) holding → better (up to 75%)
      - Higher institutional holding → better

    holdings: DataFrame with columns insider_pct, institution_pct indexed by symbol
    """
    if holdings.empty:
        return pd.Series(dtype=float, name="holdings_score")

    s = pd.DataFrame(index=holdings.index)

    if "insider_pct" in holdings.columns:
        # Sweet spot: 40–75%. Cap at 75 to avoid very-low-float penalty
        insider = holdings["insider_pct"].clip(0, 75)
        s["insider"] = _norm(insider)

    if "institution_pct" in holdings.columns:
        inst = holdings["institution_pct"].clip(0, 80)
        s["institution"] = _norm(inst)

    if s.empty:
        return pd.Series(50.0, index=holdings.index, name="holdings_score")

    composite = s.mean(axis=1)
    return _scale(composite).rename("holdings_score")


def _norm(series):
    std = series.std()
    if std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _scale(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(50.0, index=series.index)
    return (series - mn) / (mx - mn) * 100
