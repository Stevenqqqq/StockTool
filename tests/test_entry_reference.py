from __future__ import annotations

import pandas as pd

from stock_tool.entry_reference import estimate_entry_reference


def _prices(rows: int = 80) -> pd.DataFrame:
    data = []
    for index in range(rows):
        close = 100.0 + index
        data.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
                "symbol": "2330",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + index,
                "adjusted_close": close,
            }
        )
    return pd.DataFrame(data)


def test_entry_reference_returns_trend_pullback_zone_without_mutating_input() -> None:
    prices = _prices()
    original = prices.copy(deep=True)

    result = estimate_entry_reference(prices, symbol="2330")

    assert result.is_available
    assert result.method == "趨勢回檔觀察"
    assert result.reference_price is not None
    assert result.zone_low is not None
    assert result.zone_high is not None
    assert result.zone_low <= result.reference_price <= result.zone_high
    assert result.stop_loss_reference is not None
    assert result.stop_loss_reference < result.zone_low
    pd.testing.assert_frame_equal(prices, original)


def test_entry_reference_marks_insufficient_data_unknown() -> None:
    result = estimate_entry_reference(_prices(rows=5), symbol="2330")

    assert not result.is_available
    assert result.reference_price is None
    assert "at_least_20_price_rows" in result.missing_data


def test_entry_reference_respects_as_of_date_and_ignores_future_rows() -> None:
    prices = _prices(rows=40)
    cutoff = "2024-01-25"

    base = estimate_entry_reference(prices, symbol="2330", as_of_date=cutoff)

    future_spike = prices.copy(deep=True)
    future_spike.loc[future_spike.index[-1], ["high", "close"]] = [999.0, 999.0]
    with_spike = estimate_entry_reference(future_spike, symbol="2330", as_of_date=cutoff)

    assert base.as_of_date == cutoff
    assert with_spike.reference_price == base.reference_price
    assert with_spike.breakout_trigger == base.breakout_trigger


def test_entry_reference_does_not_use_far_breakout_as_main_reference() -> None:
    prices = _prices(rows=80)
    prices.loc[:, "close"] = [200.0 - index for index in range(80)]
    prices.loc[:, "open"] = prices["close"] + 0.5
    prices.loc[:, "high"] = prices["close"] + 3.0
    prices.loc[:, "low"] = prices["close"] - 3.0

    result = estimate_entry_reference(prices, symbol="2330")

    latest_close = float(prices["close"].iloc[-1])
    assert result.method == "保守觀察"
    assert result.reference_price is not None
    assert result.breakout_trigger is not None
    assert result.reference_price <= latest_close * 1.05
    assert result.breakout_trigger > result.reference_price
    assert any("不代表目前應以該價位進場" in note for note in result.notes)
