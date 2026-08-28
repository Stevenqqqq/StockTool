from __future__ import annotations

import pandas as pd
import pytest

from stock_tool.backtest import BacktestEngine
from stock_tool.backtest.validation import (
    ParameterSensitivityConfig,
    ParameterSensitivityError,
    StrategyValidationService,
    detect_isolated_parameter_peak,
)
from stock_tool.strategies.registry import create_strategy


def _prices(rows: int = 72) -> pd.DataFrame:
    closes = [100.0 + ((index % 7) - 3) * 3.0 + index * 0.1 for index in range(rows)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "symbol": "2330",
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1000.0] * rows,
        }
    )


def test_parameter_sensitivity_is_deterministic_and_does_not_mutate_inputs() -> None:
    strategy = create_strategy("breakout", {"lookback": 3, "quantity": 1})
    prices = _prices()
    original_prices = prices.copy(deep=True)
    original_parameters = dict(strategy.parameters)
    config = ParameterSensitivityConfig({"lookback": (2, 3, 4)}, max_combinations=25)
    service = StrategyValidationService(engine_factory=lambda: BacktestEngine(initial_cash=10_000))

    first = service.run_parameter_sensitivity(strategy=strategy, price_data=prices, config=config)
    second = service.run_parameter_sensitivity(strategy=strategy, price_data=prices, config=config)

    assert first.status in {"ready", "unavailable"}
    assert first.parameter_sets == second.parameter_sets
    pd.testing.assert_frame_equal(prices, original_prices)
    assert strategy.parameters == original_parameters


def test_parameter_sensitivity_rejects_forbidden_and_excessive_combinations() -> None:
    strategy = create_strategy("breakout", {"lookback": 3, "quantity": 1})
    service = StrategyValidationService(engine_factory=lambda: BacktestEngine(initial_cash=10_000))

    with pytest.raises(ParameterSensitivityError, match="not allowed"):
        service.run_parameter_sensitivity(
            strategy=strategy,
            price_data=_prices(),
            config=ParameterSensitivityConfig({"target_percent": (0.1, 0.2)}),
        )
    with pytest.raises(ParameterSensitivityError, match="maximum"):
        service.run_parameter_sensitivity(
            strategy=strategy,
            price_data=_prices(),
            config=ParameterSensitivityConfig(
                {"lookback": tuple(range(1, 27))}, max_combinations=25
            ),
        )


def test_single_peak_warns_but_stable_neighbours_do_not() -> None:
    spiky = (
        (("lookback", 2), 0.01),
        (("lookback", 3), 0.30),
        (("lookback", 4), 0.02),
    )
    stable = (
        (("lookback", 2), 0.14),
        (("lookback", 3), 0.15),
        (("lookback", 4), 0.13),
    )

    assert detect_isolated_parameter_peak(spiky)
    assert not detect_isolated_parameter_peak(stable)
