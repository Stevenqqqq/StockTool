"""Regression tests for explicit price and benchmark return-basis policies."""

from __future__ import annotations

import pandas as pd
import pytest

from stock_tool.backtest import BacktestEngine
from stock_tool.backtest.metrics import calculate_benchmark_comparison
from stock_tool.data.corporate_actions import (
    AdjustedSeriesContract,
    CorporateAction,
    CorporateActionType,
    PricePolicy,
    ReturnBasis,
)
from stock_tool.domain.models import Market, Symbol


def _equity_curve() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "cash": [100.0, 110.0],
            "market_value": [0.0, 0.0],
            "total_equity": [100.0, 110.0],
        }
    )


def _benchmark() -> pd.DataFrame:
    return pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "close": [100.0, 105.0]})


def _split() -> CorporateAction:
    return CorporateAction(
        symbol=Symbol("ABC", Market.US),
        action_type=CorporateActionType.SPLIT,
        effective_date="2024-01-02",
        available_date="2024-01-01",
        split_ratio=2.0,
        source="synthetic-fixture",
        provenance={"fixture": "policy"},
        confidence="complete",
    )


def test_adjusted_total_return_policy_rejects_explicit_actions_to_prevent_double_counting() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "symbol": ["ABC", "ABC"],
            "open": [100.0, 50.0],
            "high": [100.0, 50.0],
            "low": [100.0, 50.0],
            "close": [100.0, 50.0],
            "volume": [100, 100],
            "adjusted_close": [50.0, 50.0],
        }
    )

    with pytest.raises(ValueError, match="double-count"):
        BacktestEngine(
            corporate_actions=(_split(),),
            price_policy=PricePolicy.ADJUSTED_TOTAL_RETURN,
            return_basis=ReturnBasis.TOTAL_RETURN,
        ).run(prices)


def test_adjusted_total_return_requires_total_return_and_verified_contract() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "symbol": ["ABC"] * 3,
            "market": ["US"] * 3,
            "open": [100.0, 100.0, 50.0],
            "high": [100.0, 100.0, 50.0],
            "low": [100.0, 100.0, 50.0],
            "close": [100.0, 100.0, 50.0],
            "adjusted_close": [50.0, 50.0, 50.0],
            "volume": [100, 100, 100],
        }
    )
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "ABC", "action": "buy", "quantity": 10}]
    )

    with pytest.raises(ValueError, match="adjusted series contract"):
        BacktestEngine(
            initial_cash=1_000.0,
            price_policy=PricePolicy.ADJUSTED_TOTAL_RETURN,
            return_basis=ReturnBasis.TOTAL_RETURN,
        ).run(prices, signals)
    with pytest.raises(ValueError, match="total_return"):
        BacktestEngine(
            price_policy=PricePolicy.ADJUSTED_TOTAL_RETURN,
            return_basis=ReturnBasis.PRICE_RETURN,
        )

    result = BacktestEngine(
        initial_cash=1_000.0,
        price_policy=PricePolicy.ADJUSTED_TOTAL_RETURN,
        return_basis=ReturnBasis.TOTAL_RETURN,
        adjusted_series_contract=AdjustedSeriesContract(
            source="synthetic-fixture",
            verified=True,
        ),
    ).run(prices, signals)

    assert result.equity_curve.iloc[-1]["total_equity"] == pytest.approx(1_000.0)


def test_unknown_price_policy_fails_closed_when_actions_are_supplied() -> None:
    with pytest.raises(ValueError, match="price policy"):
        BacktestEngine(corporate_actions=(_split(),), price_policy=PricePolicy.UNKNOWN)


def test_benchmark_requires_same_explicit_return_basis() -> None:
    comparison = calculate_benchmark_comparison(
        _equity_curve(),
        _benchmark(),
        strategy_total_return=0.10,
        strategy_return_basis=ReturnBasis.PRICE_RETURN,
        benchmark_return_basis=ReturnBasis.TOTAL_RETURN,
    )

    assert comparison.available is False
    assert comparison.missing_reason == "benchmark_return_basis_mismatch"


def test_matching_return_basis_has_golden_expected_return_and_policy_metadata() -> None:
    comparison = calculate_benchmark_comparison(
        _equity_curve(),
        _benchmark(),
        strategy_total_return=0.10,
        strategy_return_basis=ReturnBasis.PRICE_RETURN,
        benchmark_return_basis=ReturnBasis.PRICE_RETURN,
        benchmark_price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        benchmark_source="synthetic-fixture",
    )

    assert comparison.available is True
    assert comparison.total_return == pytest.approx(0.05)
    assert comparison.excess_return == pytest.approx(0.05)
    assert comparison.return_basis == ReturnBasis.PRICE_RETURN.value
    assert comparison.price_policy == PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS.value
    assert comparison.source == "synthetic-fixture"
