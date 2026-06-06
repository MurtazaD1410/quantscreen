# engine/composite.py — Combine all factor scores into a single ranked output

import pandas as pd


FACTOR_COLUMNS = [
    "value_score",
    "quality_score",
    "momentum_score",
    "lowvol_score",
    "meanrev_score",
    "holdings_score",
]


def compute_composite(
    symbols: list,
    weights: dict,
    value_scores:    pd.Series = None,
    quality_scores:  pd.Series = None,
    momentum_scores: pd.Series = None,
    lowvol_scores:   pd.Series = None,
    meanrev_scores:  pd.Series = None,
    holdings_scores: pd.Series = None,
) -> pd.DataFrame:
    """
    Combines individual factor scores into a composite score.

    weights example:
        {"value": 0.30, "quality": 0.30, "momentum": 0.25, "low_volatility": 0.15}

    Returns a DataFrame sorted descending by composite_score with a Rank column.
    """
    score_map = {
        "value":          value_scores,
        "quality":        quality_scores,
        "momentum":       momentum_scores,
        "low_volatility": lowvol_scores,
        "mean_reversion": meanrev_scores,
        "holdings":       holdings_scores,
    }

    col_map = {
        "value":          "value_score",
        "quality":        "quality_score",
        "momentum":       "momentum_score",
        "low_volatility": "lowvol_score",
        "mean_reversion": "meanrev_score",
        "holdings":       "holdings_score",
    }

    df = pd.DataFrame(index=symbols)
    composite = pd.Series(0.0, index=symbols)
    total_w   = 0.0

    for factor, scores in score_map.items():
        w = weights.get(factor, 0)
        if scores is not None and w > 0:
            aligned = scores.reindex(symbols).fillna(50)
            df[col_map[factor]] = aligned
            composite += aligned * w
            total_w   += w

    if total_w > 0:
        composite /= total_w

    df["composite_score"] = composite.round(1)
    df = df.sort_values("composite_score", ascending=False)
    df.insert(0, "rank", range(1, len(df) + 1))

    return df
