from __future__ import annotations

import pandas as pd

from stock_tool.backtest import BacktestEngine
from stock_tool.backtest.validation import (
    OutOfSampleConfig,
    StrategyValidationService,
    ValidationPeriod,
    WalkForwardConfig,
)
from stock_tool.strategies.registry import create_strategy


def _prices(rows: int = 90) -> pd.DataFrame:
    closes = [100.0 + ((index % 9) - 4) * 2.0 + index * 0.15 for index in range(rows)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "symbol": "2330",
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000.0 + (index % 4) * 250 for index in range(rows)],
        }
    )


def _service() -> StrategyValidationService:
    return StrategyValidationService(
        engine_factory=lambda: BacktestEngine(initial_cash=10_000.0),
    )


def test_oos_keeps_train_and_test_strictly_separate_and_t_plus_one() -> None:
    prices = _prices()
    service = _service()
    result = service.run_out_of_sample(
        strategy=create_strategy("breakout", {"lookback": 3, "quantity": 1}),
        price_data=prices,
        config=OutOfSampleConfig(
            train_period=ValidationPeriod("2024-01-01", "2024-02-14"),
            test_period=ValidationPeriod("2024-02-15", "2024-03-30"),
        ),
    )

    assert result.status == "ready"
    assert result.in_sample is not None
    assert result.out_of_sample is not None
    assert result.in_sample.period.end < result.out_of_sample.period.start
    for trade in result.out_of_sample.trades:
        assert trade.signal_date >= "2024-02-15"
        assert trade.execution_date > trade.signal_date
        assert trade.execution_date >= "2024-02-15"
    assert result.out_of_sample.equity_curve["date"].min() >= "2024-02-15"


def test_oos_rejects_overlapping_or_too_short_periods_with_structured_warning() -> None:
    result = _service().run_out_of_sample(
        strategy=create_strategy("breakout", {"lookback": 3, "quantity": 1}),
        price_data=_prices(12),
        config=OutOfSampleConfig(
            train_period=ValidationPeriod("2024-01-01", "2024-01-08"),
            test_period=ValidationPeriod("2024-01-08", "2024-01-12"),
        ),
    )

    assert result.status == "unavailable"
    assert any(warning.code == "invalid_time_split" for warning in result.warnings)


def test_walk_forward_has_deterministic_non_overlapping_test_folds() -> None:
    result = _service().run_walk_forward(
        strategy=create_strategy("breakout", {"lookback": 3, "quantity": 1}),
        price_data=_prices(),
        config=WalkForwardConfig(train_bars=30, test_bars=12, step_bars=12, max_folds=4),
    )

    assert result.status == "ready"
    assert len(result.folds) >= 2
    assert [fold.fold_number for fold in result.folds] == list(range(1, len(result.folds) + 1))
    for previous, current in zip(result.folds, result.folds[1:]):
        assert previous.test_period.end < current.test_period.start
    for fold in result.folds:
        assert fold.train_period.end < fold.test_period.start
        for trade in fold.test_run.trades:
            assert trade.execution_date > trade.signal_date
            assert trade.signal_date >= fold.test_period.start


def test_walk_forward_returns_unavailable_when_two_test_folds_cannot_be_formed() -> None:
    result = _service().run_walk_forward(
        strategy=create_strategy("breakout", {"lookback": 3, "quantity": 1}),
        price_data=_prices(42),
        config=WalkForwardConfig(train_bars=30, test_bars=10, step_bars=10, max_folds=10),
    )

    assert result.status == "unavailable"
    assert any(warning.code == "insufficient_walk_forward_folds" for warning in result.warnings)


def test_validation_does_not_mutate_prices_or_strategy_parameters() -> None:
    prices = _prices()
    original = prices.copy(deep=True)
    strategy = create_strategy("breakout", {"lookback": 3, "quantity": 1})
    original_parameters = dict(strategy.parameters)

    _service().run_walk_forward(
        strategy=strategy,
        price_data=prices,
        config=WalkForwardConfig(train_bars=30, test_bars=12, step_bars=12, max_folds=2),
    )

    pd.testing.assert_frame_equal(prices, original)
    assert strategy.parameters == original_parameters


def test_fundamental_validation_uses_available_date_and_fails_closed_when_missing() -> None:
    prices = _prices(40)
    fundamentals = pd.DataFrame(
        {
            "symbol": ["2330"],
            "available_date": ["2024-01-25"],
            "filing_date": ["2024-01-10"],
            "eps_growth": [0.2],
            "revenue_growth": [0.2],
            "roe": [0.2],
            "debt_ratio": [0.2],
        }
    )
    config = OutOfSampleConfig(
        train_period=ValidationPeriod("2024-01-01", "2024-01-20"),
        test_period=ValidationPeriod("2024-01-21", "2024-02-09"),
    )
    strategy = create_strategy("fundamental_growth", {"quantity": 1})

    visible = _service().run_out_of_sample(
        strategy=strategy,
        price_data=prices,
        fundamentals=fundamentals,
        config=config,
    )
    missing = _service().run_out_of_sample(
        strategy=strategy,
        price_data=prices,
        fundamentals=fundamentals.drop(columns=["available_date"]),
        config=config,
    )

    assert visible.status == "ready"
    assert visible.out_of_sample is not None
    assert visible.out_of_sample.signal_count > 0
    assert missing.status == "unavailable"
    assert missing.out_of_sample is None
    assert any(warning.code == "fundamental_available_date_missing" for warning in missing.warnings)
