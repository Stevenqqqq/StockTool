"""Golden tests for benchmark alignment and comparison metrics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from stock_tool.backtest.metrics import PerformanceMetrics, calculate_benchmark_comparison


def _equity_curve() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "cash": [100.0, 105.0, 103.0, 112.0],
            "market_value": [0.0, 0.0, 0.0, 0.0],
            "total_equity": [100.0, 105.0, 103.0, 112.0],
        }
    )


def _benchmark() -> pd.DataFrame:
    return pd.read_csv(Path(__file__).parent / "fixtures" / "benchmark_golden.csv")


def test_golden_benchmark_metrics_are_exactly_date_aligned() -> None:
    comparison = calculate_benchmark_comparison(
        _equity_curve(),
        _benchmark(),
        strategy_total_return=0.12,
    )

    assert comparison.available is True
    assert comparison.total_return == pytest.approx(0.08)
    assert comparison.max_drawdown == pytest.approx(-0.10)
    assert comparison.excess_return == pytest.approx(0.04)
    assert comparison.aligned_start_date == "2024-01-01"
    assert comparison.aligned_end_date == "2024-01-04"
    assert comparison.observations == 4
    assert comparison.missing_reason is None


@pytest.mark.parametrize("removed_date", ["2024-01-01", "2024-01-04"])
def test_missing_benchmark_boundary_is_unavailable(removed_date: str) -> None:
    benchmark = _benchmark().loc[lambda frame: frame["date"] != removed_date]

    comparison = calculate_benchmark_comparison(
        _equity_curve(), benchmark, strategy_total_return=0.12
    )

    assert comparison.available is False
    assert comparison.total_return is None
    assert comparison.missing_reason == "benchmark_dates_do_not_match_equity_curve"


def test_duplicate_benchmark_date_is_unavailable_without_silent_deduplication() -> None:
    benchmark = pd.concat([_benchmark(), _benchmark().tail(1)], ignore_index=True)

    comparison = calculate_benchmark_comparison(
        _equity_curve(), benchmark, strategy_total_return=0.12
    )

    assert comparison.available is False
    assert comparison.missing_reason == "benchmark_contains_duplicate_dates"


@pytest.mark.parametrize(
    "benchmark",
    [pd.DataFrame({"date": ["2024-01-01"]}), pd.DataFrame(), pd.DataFrame({"close": [100]})],
)
def test_invalid_or_empty_benchmark_is_explicitly_unavailable(benchmark: pd.DataFrame) -> None:
    comparison = calculate_benchmark_comparison(
        _equity_curve(), benchmark, strategy_total_return=0.12
    )

    assert comparison.available is False
    assert comparison.total_return is None
    assert comparison.missing_reason is not None


def test_performance_metrics_exposes_benchmark_drawdown_alignment_and_excess_return() -> None:
    metrics = PerformanceMetrics.calculate(
        _equity_curve(), [], initial_cash=100.0, benchmark=_benchmark()
    )

    assert metrics.benchmark_total_return == pytest.approx(0.08)
    assert metrics.benchmark_max_drawdown == pytest.approx(-0.10)
    assert metrics.benchmark_excess_return == pytest.approx(0.04)
    assert metrics.benchmark_aligned_start_date == "2024-01-01"
    assert metrics.benchmark_aligned_end_date == "2024-01-04"
    assert metrics.benchmark_observations == 4


def test_different_strategy_trading_dates_are_not_forward_filled() -> None:
    equity = _equity_curve().loc[lambda frame: frame["date"] != "2024-01-03"]

    comparison = calculate_benchmark_comparison(equity, _benchmark(), strategy_total_return=0.12)

    assert comparison.available is False
    assert comparison.missing_reason == "benchmark_dates_do_not_match_equity_curve"


def test_timezone_aware_and_naive_dates_are_normalized_for_alignment() -> None:
    equity = _equity_curve()
    equity["date"] = pd.date_range("2024-01-01", periods=4)
    benchmark = _benchmark()
    benchmark["date"] = pd.date_range("2024-01-01", periods=4, tz="UTC")

    comparison = calculate_benchmark_comparison(equity, benchmark, strategy_total_return=0.12)

    assert comparison.available is True
    assert comparison.aligned_start_date == "2024-01-01"


def test_invalid_normalized_date_is_unavailable_with_explicit_reason() -> None:
    benchmark = _benchmark()
    benchmark.loc[1, "date"] = "not-a-date"

    comparison = calculate_benchmark_comparison(
        _equity_curve(), benchmark, strategy_total_return=0.12
    )

    assert comparison.available is False
    assert comparison.missing_reason == "benchmark_contains_invalid_dates"
