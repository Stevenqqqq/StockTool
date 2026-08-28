from __future__ import annotations

import pandas as pd
import pytest

from stock_tool.backtest import BacktestEngine
from stock_tool.data.universe import HistoricalUniverse, UniverseMembership
from stock_tool.domain.models import Market, Symbol


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "symbol": ["2330", "2330", "2330"],
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.5, 10.5, 11.5],
            "close": [10.0, 11.0, 12.0],
            "volume": [100, 100, 100],
        }
    )


def test_backtest_legacy_mode_preserves_behavior_but_warns_about_survivorship() -> None:
    signals = pd.DataFrame([{"date": "2024-01-01", "symbol": "2330", "signal": 1, "quantity": 1}])
    engine = BacktestEngine(point_in_time_mode="legacy", initial_cash=1000)

    result = engine.run(_prices(), signals)

    assert result.trades
    assert any("存活者偏誤" in warning for warning in result.warnings)


def test_backtest_strict_mode_requires_historical_universe_without_fallback() -> None:
    engine = BacktestEngine(point_in_time_mode="strict", initial_cash=1000)

    with pytest.raises(ValueError, match="historical universe"):
        engine.run(_prices(), None)


def test_backtest_strict_mode_accepts_explicit_universe_and_preserves_t_plus_one() -> None:
    universe = HistoricalUniverse(
        memberships=(
            UniverseMembership(
                symbol=Symbol("2330", Market.TWSE),
                effective_from="2024-01-01",
                effective_to=None,
                status="listed",
                source="synthetic-fixture",
                dataset_completeness="complete",
            ),
        ),
        dataset_completeness="complete",
        source="synthetic-fixture",
    )
    signals = pd.DataFrame([{"date": "2024-01-01", "symbol": "2330", "signal": 1, "quantity": 1}])
    engine = BacktestEngine(
        point_in_time_mode="strict",
        historical_universe=universe,
        initial_cash=1000,
    )

    result = engine.run(_prices(), signals)

    assert result.trades[0].signal_date == "2024-01-01"
    assert result.trades[0].execution_date == "2024-01-02"
    assert not any("存活者偏誤" in warning for warning in result.warnings)


def test_backtest_strict_mode_skips_signals_without_historical_membership() -> None:
    universe = HistoricalUniverse(
        memberships=(
            UniverseMembership(
                symbol=Symbol("2330", Market.TWSE),
                effective_from="2024-01-02",
                effective_to=None,
                status="listed",
                source="synthetic-fixture",
                dataset_completeness="partial",
            ),
        ),
        dataset_completeness="partial",
        source="synthetic-fixture",
    )
    signals = pd.DataFrame([{"date": "2024-01-01", "symbol": "2330", "signal": 1, "quantity": 1}])

    result = BacktestEngine(
        point_in_time_mode="strict",
        historical_universe=universe,
        initial_cash=1000,
    ).run(_prices(), signals)

    assert result.trades == []
    assert any("no historical-universe membership" in warning for warning in result.warnings)


def test_legacy_mode_warns_even_when_complete_universe_is_provided() -> None:
    universe = HistoricalUniverse(
        memberships=(
            UniverseMembership(
                Symbol("2330", Market.TWSE), "2024-01-01", None, "listed", "fixture", "complete"
            ),
            UniverseMembership(
                Symbol("OLD", Market.TWSE),
                "2020-01-01",
                "2023-12-31",
                "delisted",
                "fixture",
                "complete",
            ),
        ),
        dataset_completeness="complete",
        source="fixture",
    )
    signals = pd.DataFrame([{"date": "2024-01-01", "symbol": "2330", "signal": 1, "quantity": 1}])

    legacy = BacktestEngine(
        initial_cash=1000, point_in_time_mode="legacy", historical_universe=universe
    ).run(_prices(), signals)
    strict = BacktestEngine(
        initial_cash=1000, point_in_time_mode="strict", historical_universe=universe
    ).run(_prices(), signals)

    assert any("legacy mode does not filter" in warning.lower() for warning in legacy.warnings)
    assert not any("legacy mode does not filter" in warning.lower() for warning in strict.warnings)
