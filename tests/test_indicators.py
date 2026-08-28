from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from stock_tool.indicators import (
    add_atr,
    add_bias,
    add_bollinger_bands,
    add_ema,
    add_macd,
    add_rolling_return,
    add_rolling_volatility,
    add_rsi,
    add_sma,
    add_stochastic_oscillator,
    add_volume_moving_average,
)


def _price_frame(rows: int = 40, symbol: str = "2330") -> pd.DataFrame:
    close = pd.Series(np.arange(1, rows + 1, dtype=float) + 100.0)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
            "symbol": symbol,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.arange(1_000, 1_000 + rows, dtype=float),
            "adjusted_close": close,
        }
    )


def test_sma_ema_and_bias_do_not_mutate_input() -> None:
    prices = _price_frame(rows=6)
    original = prices.copy(deep=True)

    with_sma = add_sma(prices, periods=(3,))
    with_ema = add_ema(prices, periods=(3,))
    with_bias = add_bias(prices, periods=(3,))

    pdt.assert_frame_equal(prices, original)
    assert with_sma["sma_3"].iloc[:2].isna().all()
    assert with_sma["sma_3"].iloc[2] == pytest.approx(102.0)
    assert with_ema["ema_3"].iloc[2] == pytest.approx(
        prices["close"].ewm(span=3, adjust=False, min_periods=3).mean().iloc[2]
    )
    assert with_bias["bias_3"].iloc[2] == pytest.approx(((103.0 / 102.0) - 1.0) * 100.0)


def test_indicators_are_grouped_by_symbol_and_restore_input_order() -> None:
    prices = pd.DataFrame(
        {
            "date": [
                "2024-01-03",
                "2024-01-01",
                "2024-01-01",
                "2024-01-02",
                "2024-01-02",
                "2024-01-03",
            ],
            "symbol": ["2330", "2330", "0050", "2330", "0050", "0050"],
            "open": [3.0, 1.0, 100.0, 2.0, 200.0, 300.0],
            "high": [4.0, 2.0, 101.0, 3.0, 201.0, 301.0],
            "low": [2.0, 0.5, 99.0, 1.0, 199.0, 299.0],
            "close": [3.0, 1.0, 100.0, 2.0, 200.0, 300.0],
            "volume": [30.0, 10.0, 1000.0, 20.0, 2000.0, 3000.0],
        }
    )

    result = add_sma(prices, periods=(2,))

    assert result.index.tolist() == prices.index.tolist()
    assert result["sma_2"].iloc[0] == pytest.approx(2.5)
    assert pd.isna(result["sma_2"].iloc[1])
    assert pd.isna(result["sma_2"].iloc[2])
    assert result["sma_2"].iloc[5] == pytest.approx(250.0)


def test_indicators_sort_dates_chronologically_before_calculation() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024/1/10", "2024/1/2", "2024/1/3"],
            "symbol": ["2330", "2330", "2330"],
            "open": [10.0, 2.0, 3.0],
            "high": [11.0, 3.0, 4.0],
            "low": [9.0, 1.0, 2.0],
            "close": [10.0, 2.0, 3.0],
            "volume": [1000.0, 1000.0, 1000.0],
        }
    )

    result = add_sma(prices, periods=(2,))

    assert result.index.tolist() == prices.index.tolist()
    assert result["sma_2"].iloc[0] == pytest.approx(6.5)
    assert pd.isna(result["sma_2"].iloc[1])


def test_indicators_reject_invalid_dates_when_date_column_is_present() -> None:
    prices = _price_frame(rows=3)
    prices.loc[1, "date"] = "not-a-date"

    with pytest.raises(ValueError, match="invalid dates"):
        add_sma(prices, periods=(2,))


def test_rsi_macd_and_stochastic_oscillator() -> None:
    prices = _price_frame(rows=45)

    with_rsi = add_rsi(prices, period=14)
    with_macd = add_macd(prices, fast_period=12, slow_period=26, signal_period=9)
    with_stochastic = add_stochastic_oscillator(
        prices,
        k_period=9,
        k_smoothing=3,
        d_period=3,
    )

    assert pd.isna(with_rsi["rsi_14"].iloc[13])
    assert with_rsi["rsi_14"].iloc[-1] == pytest.approx(100.0)
    assert pd.isna(with_macd["macd_dea"].iloc[32])
    assert pd.notna(with_macd["macd_dea"].iloc[-1])
    assert 0.0 <= with_stochastic["stoch_k"].iloc[-1] <= 100.0
    assert 0.0 <= with_stochastic["stoch_d"].iloc[-1] <= 100.0


def test_bollinger_bands_atr_and_rolling_volatility() -> None:
    prices = _price_frame(rows=8)

    with_bands = add_bollinger_bands(prices, period=3, num_std=2)
    with_atr = add_atr(prices, period=3)
    with_volatility = add_rolling_volatility(prices, periods=(3,), annualize=False)

    expected_middle = prices["close"].iloc[0:3].mean()
    expected_std = prices["close"].iloc[0:3].std(ddof=0)
    assert with_bands["bb_middle_3"].iloc[2] == pytest.approx(expected_middle)
    assert with_bands["bb_upper_3"].iloc[2] == pytest.approx(expected_middle + 2 * expected_std)
    assert with_bands["bb_lower_3"].iloc[2] == pytest.approx(expected_middle - 2 * expected_std)
    assert with_atr["atr_3"].iloc[2] == pytest.approx(2.0)

    one_period_return = (prices["close"] / prices["close"].shift(1)) - 1.0
    expected_volatility = one_period_return.rolling(window=3, min_periods=3).std(ddof=0).iloc[3]
    assert with_volatility["volatility_3"].iloc[3] == pytest.approx(expected_volatility)


def test_volume_average_and_rolling_return() -> None:
    prices = _price_frame(rows=6)

    with_volume = add_volume_moving_average(prices, periods=(3,))
    with_return = add_rolling_return(prices, periods=(2,))

    assert with_volume["volume_ma_3"].iloc[2] == pytest.approx(
        prices["volume"].iloc[0:3].mean()
    )
    assert with_return["return_2"].iloc[2] == pytest.approx((103.0 / 101.0) - 1.0)
    assert pd.isna(with_return["return_2"].iloc[1])


def test_public_indicator_functions_have_docstrings_and_type_hints() -> None:
    functions = [
        add_atr,
        add_bias,
        add_bollinger_bands,
        add_ema,
        add_macd,
        add_rolling_return,
        add_rolling_volatility,
        add_rsi,
        add_sma,
        add_stochastic_oscillator,
        add_volume_moving_average,
    ]

    for function in functions:
        assert inspect.getdoc(function)
        signature = inspect.signature(function)
        assert signature.return_annotation is not inspect.Signature.empty
        assert all(
            parameter.annotation is not inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )
