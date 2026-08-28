from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stock_tool.backtest import BacktestEngine
from stock_tool.strategies import (
    BreakoutStrategy,
    FundamentalGrowthStrategy,
    MACDTrendStrategy,
    MACrossStrategy,
    RSIReversalStrategy,
    StrategyBase,
    StrategyParameterError,
    VolumePriceBreakoutStrategy,
)


def _price_frame(closes: list[float], *, volumes: list[float] | None = None) -> pd.DataFrame:
    close = pd.Series(closes, dtype=float)
    volume = volumes if volumes is not None else [1000.0] * len(closes)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="D").strftime(
                "%Y-%m-%d"
            ),
            "symbol": "2330",
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volume,
        }
    )


def _assert_signal_contract(signals: pd.DataFrame) -> None:
    assert {"date", "symbol", "signal", "reason"}.issubset(signals.columns)
    assert set(signals["signal"]).issubset({-1, 0, 1})


def test_all_strategies_inherit_strategy_base() -> None:
    strategies = [
        MACrossStrategy(short_window=2, long_window=3, quantity=10),
        BreakoutStrategy(lookback=3, quantity=10),
        RSIReversalStrategy(period=2, quantity=10),
        MACDTrendStrategy(fast_period=2, slow_period=4, signal_period=2, quantity=10),
        VolumePriceBreakoutStrategy(
            lookback=3,
            volume_window=3,
            volume_multiplier=2,
            quantity=10,
        ),
        FundamentalGrowthStrategy(quantity=10),
    ]

    for strategy in strategies:
        assert isinstance(strategy, StrategyBase)
        assert strategy.name
        assert strategy.description
        assert strategy.risk_notes
        assert isinstance(strategy.parameters, dict)


def test_invalid_strategy_parameters_raise() -> None:
    with pytest.raises(StrategyParameterError):
        MACrossStrategy(short_window=20, long_window=20)
    with pytest.raises(StrategyParameterError):
        BreakoutStrategy(lookback=0)
    with pytest.raises(StrategyParameterError):
        RSIReversalStrategy(oversold=80, overbought=70)
    with pytest.raises(StrategyParameterError):
        MACDTrendStrategy(fast_period=26, slow_period=12)
    with pytest.raises(StrategyParameterError):
        VolumePriceBreakoutStrategy(volume_multiplier=0)


def test_ma_cross_strategy_generates_buy_and_sell_signals() -> None:
    prices = _price_frame([10, 10, 10, 10, 10, 12, 14, 16, 14, 12, 10, 8])
    strategy = MACrossStrategy(short_window=2, long_window=3, quantity=10)

    signals = strategy.generate_signals(prices)

    _assert_signal_contract(signals)
    assert 1 in set(signals["signal"])
    assert -1 in set(signals["signal"])


def test_breakout_strategy_uses_prior_range() -> None:
    prices = _price_frame([10, 11, 12, 13, 15, 9])
    strategy = BreakoutStrategy(lookback=3, quantity=10)

    signals = strategy.generate_signals(prices)

    _assert_signal_contract(signals)
    assert signals.loc[signals["date"] == "2024-01-04", "signal"].iloc[0] == 1
    assert signals.loc[signals["date"] == "2024-01-06", "signal"].iloc[0] == -1


def test_rsi_reversal_strategy_generates_numeric_signals() -> None:
    prices = _price_frame([10, 9, 8, 9, 10, 11, 12])
    strategy = RSIReversalStrategy(period=2, quantity=10)

    signals = strategy.generate_signals(prices)

    _assert_signal_contract(signals)
    assert 1 in set(signals["signal"])
    assert -1 in set(signals["signal"])


def test_macd_trend_strategy_generates_numeric_signals() -> None:
    prices = _price_frame([10, 9, 8, 9, 10, 11, 10, 9, 8, 7, 8, 9, 10, 11])
    strategy = MACDTrendStrategy(fast_period=2, slow_period=4, signal_period=2, quantity=10)

    signals = strategy.generate_signals(prices)

    _assert_signal_contract(signals)
    assert set(signals["signal"]).intersection({-1, 1})


def test_volume_price_breakout_strategy_requires_volume_confirmation() -> None:
    prices = _price_frame([10, 11, 12, 15, 9], volumes=[100, 100, 100, 300, 100])
    strategy = VolumePriceBreakoutStrategy(
        lookback=3,
        volume_window=3,
        volume_multiplier=2,
        quantity=10,
    )

    signals = strategy.generate_signals(prices)

    _assert_signal_contract(signals)
    assert signals.loc[signals["date"] == "2024-01-04", "signal"].iloc[0] == 1
    assert signals.loc[signals["date"] == "2024-01-05", "signal"].iloc[0] == -1


def test_fundamental_growth_strategy_uses_backward_available_data() -> None:
    prices = _price_frame([10, 11, 12, 13])
    fundamentals = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-03"],
            "symbol": ["2330", "2330"],
            "eps_growth": [0.2, 0.01],
            "revenue_growth": [0.2, 0.01],
            "roe": [0.2, 0.05],
            "debt_ratio": [0.3, 0.8],
        }
    )
    strategy = FundamentalGrowthStrategy(quantity=10)

    signals = strategy.generate_signals(prices, fundamentals=fundamentals)

    _assert_signal_contract(signals)
    assert signals.loc[signals["date"] == "2024-01-01", "signal"].iloc[0] == 1
    assert signals.loc[signals["date"] == "2024-01-02", "signal"].iloc[0] == 0
    assert signals.loc[signals["date"] == "2024-01-03", "signal"].iloc[0] == -1


def test_strategy_signals_can_be_used_by_backtest_engine() -> None:
    prices = _price_frame([10, 11, 12, 15, 16, 9])
    strategy = BreakoutStrategy(lookback=3, quantity=10)
    signals = strategy.generate_signals(prices)
    engine = BacktestEngine(initial_cash=10_000)

    result = engine.run(prices, signals)

    assert result.trades
    assert result.trades[0].signal_date == "2024-01-04"
    assert result.trades[0].execution_date == "2024-01-05"


def test_strategies_do_not_mutate_input_data() -> None:
    prices = _price_frame(list(np.linspace(10, 20, 80)))
    original = prices.copy(deep=True)
    strategy = BreakoutStrategy(lookback=5, quantity=10)

    strategy.generate_signals(prices)

    pd.testing.assert_frame_equal(prices, original)

