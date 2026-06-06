import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch
import pandas as pd
import pytest
from pipeline.price_data import fetch_price, fetch_close_matrix


def _make_df(tz="Asia/Kolkata"):
    idx = pd.date_range("2024-01-01", periods=5, tz=tz)
    return pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0, 103.0, 104.0],
         "Open":  [99.0,  100.0, 101.0, 102.0, 103.0]},
        index=idx,
    )


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
