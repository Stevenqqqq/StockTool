from __future__ import annotations

import pandas as pd
import pandas.testing as pdt

from stock_tool.screener import ScreenerCriteria, screen_stocks


def test_screen_stocks_filters_latest_indicator_rows_without_mutating_input() -> None:
    indicators = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
            "symbol": ["2330", "2330", "0050", "0050"],
            "close": [100.0, 110.0, 80.0, 82.0],
            "volume": [100, 2000, 100, 500],
            "return_20": [0.01, 0.08, 0.02, 0.03],
            "volatility_20": [0.2, 0.15, 0.1, 0.25],
            "rsi_14": [55.0, 62.0, 50.0, 58.0],
        }
    )
    original = indicators.copy(deep=True)

    result = screen_stocks(
        indicators,
        ScreenerCriteria(min_volume=1000, min_return_20d=0.05, max_volatility_20d=0.2),
    )

    pdt.assert_frame_equal(indicators, original)
    assert result.warnings == ()
    assert result.matches["symbol"].tolist() == ["2330"]


def test_screen_stocks_warns_when_filter_column_is_missing() -> None:
    indicators = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "symbol": ["2330"],
            "close": [110.0],
        }
    )

    result = screen_stocks(indicators, ScreenerCriteria(min_rsi=50.0))

    assert "rsi_14" in result.warnings[0]
    assert result.matches["symbol"].tolist() == ["2330"]


def test_screen_stocks_empty_input_returns_warning() -> None:
    result = screen_stocks(pd.DataFrame(), ScreenerCriteria())

    assert result.matches.empty
    assert result.warnings
