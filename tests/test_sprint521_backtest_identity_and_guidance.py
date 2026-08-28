"""Regression coverage for Sprint 5.2.1 result identity and portfolio guidance."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stock_tool.dashboard.backtest_ui import (
    BacktestCostPreset,
    BacktestFormValues,
    build_backtest_run_binding,
    resolve_backtest_result_display,
)
from stock_tool.dashboard.portfolio_guidance import portfolio_missing_data_guidance
from stock_tool.portfolio_health import PortfolioHealthService
from stock_tool.portfolio_valuation import PortfolioValuationService


def _values(**changes: object) -> BacktestFormValues:
    values: dict[str, object] = {
        "symbol": "2330",
        "market": "TWSE",
        "strategy_key": "ma_cross",
        "strategy_parameters": {"short_window": 20, "long_window": 60, "target_percent": 0.4},
        "data_rows": 80,
        "data_start": "2024-01-01",
        "data_end": "2024-04-19",
        "data_source": "yfinance",
        "initial_cash": 1_000_000.0,
        "allocation_rate": 0.40,
        "max_position_pct": 0.50,
        "commission_rate": 0.001425,
        "tax_rate": 0.003,
        "slippage_rate": 0.001,
        "cost_preset": BacktestCostPreset.TAIWAN_STOCK,
        "trailing_stop_pct": 0.10,
        "has_fundamentals": True,
        "market_costs_confirmed": True,
    }
    values.update(changes)
    return BacktestFormValues(**values)


def test_backtest_run_binding_uses_the_actual_executed_form_values() -> None:
    values = _values()
    binding = build_backtest_run_binding(values)

    assert binding.matches(values)
    assert binding.summary.symbol == "2330"
    assert binding.summary.market == "TWSE"
    assert binding.strategy_parameters == (
        ("long_window", 60),
        ("short_window", 20),
        ("target_percent", 0.4),
    )
    assert binding.initial_cash == 1_000_000.0
    assert binding.allocation_rate == 0.40
    assert binding.max_position_pct == 0.50
    assert binding.commission_rate == 0.001425
    assert binding.tax_rate == 0.003
    assert binding.slippage_rate == 0.001
    assert binding.trailing_stop_pct == 0.10
    assert binding.data_start == "2024-01-01"
    assert binding.data_end == "2024-04-19"
    assert binding.data_source == "yfinance"


def test_backtest_run_binding_rejects_changed_symbol_strategy_and_cost_settings() -> None:
    binding = build_backtest_run_binding(_values())

    assert not binding.matches(_values(symbol="AAPL", market="US"))
    assert not binding.matches(
        _values(
            strategy_key="breakout", strategy_parameters={"lookback": 20, "target_percent": 0.4}
        )
    )
    assert not binding.matches(_values(commission_rate=0.002))
    assert not binding.matches(_values(allocation_rate=0.30))
    assert not binding.matches(_values(max_position_pct=0.60))


def test_result_display_uses_saved_summary_after_form_changes_without_mutating_binding() -> None:
    binding = build_backtest_run_binding(_values())
    before = binding

    current = resolve_backtest_result_display(_values(), binding)
    changed = resolve_backtest_result_display(_values(symbol="6488", market="TPEX"), binding)
    legacy = resolve_backtest_result_display(_values(), None)

    assert current.is_current
    assert current.summary == binding.summary
    assert not changed.is_current
    assert changed.summary == binding.summary
    assert changed.message is not None
    assert "設定已變更" in changed.message
    assert legacy.summary is None
    assert legacy.message is not None
    assert binding == before


def test_portfolio_health_generated_missing_fields_have_actionable_chinese_guidance() -> None:
    positions = pd.read_csv(
        Path(__file__).parent / "fixtures" / "sprint32_positions.csv",
        dtype={"symbol": str, "market": str, "currency": str},
    ).head(1)
    prices = pd.DataFrame(
        {
            "date": ["2026-01-02"],
            "symbol": [positions.iloc[0]["symbol"]],
            "market": [positions.iloc[0]["market"]],
            "close": [120.0],
        }
    )
    valuation = PortfolioValuationService().value(positions=positions, prices=prices)
    health = PortfolioHealthService().assess(portfolio=positions, valuation=valuation)
    fields = {item.field for item in health.missing_data}
    guidance = {
        item.field: item.next_step for item in portfolio_missing_data_guidance(health.missing_data)
    }

    assert {
        "portfolio_fundamentals",
        "portfolio_indicators",
        "portfolio_composite_scores",
    } <= fields
    assert "各持股基本面資料" in guidance["portfolio_fundamentals"]
    assert "足夠歷史價格" in guidance["portfolio_indicators"]
    assert "研究快照與綜合評分" in guidance["portfolio_composite_scores"]
