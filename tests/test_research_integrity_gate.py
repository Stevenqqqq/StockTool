"""Synthetic stock-distribution scenario; NOT actual 6669 event terms/dates."""

from pathlib import Path
from dataclasses import replace

import pandas as pd
import pytest

from stock_tool.data.corporate_actions import CorporateAction, raw_research_safety_errors
from stock_tool.domain.models import Market, Symbol
from stock_tool.fundamentals.models import visible_fundamentals_as_of
from stock_tool.strategies import FundamentalGrowthStrategy
from stock_tool.application.strategy_workspace import StrategyWorkspaceApplicationService
from test_strategy_workspace import _prices, _values
from stock_tool.strategies.registry import create_strategy, get_strategy_definition


def test_6669_distribution_is_blocked_without_guessing_or_mutation():
    prices = pd.read_csv(
        Path(__file__).parent / "fixtures/integrity_6669_stock_distribution.csv",
        dtype={"symbol": str},
    )
    original = prices.copy(deep=True)
    assert "重大不連續" in raw_research_safety_errors(prices)[0]
    for symbol in ("6669", "OTHER"):
        prices["symbol"] = symbol
        assert raw_research_safety_errors(prices)
    prices["symbol"] = "6669"
    pd.testing.assert_frame_equal(prices, original)


def test_existing_event_contract_does_not_make_raw_indicators_safe():
    prices = _prices()
    event = CorporateAction(
        symbol=Symbol("2330", Market.TWSE),
        action_type="split",
        effective_date="2024-02-01",
        available_date="2024-01-20",
        split_ratio=3,
        source="synthetic",
        confidence="complete",
        completeness="complete",
    )
    assert "原始訊號序列" in raw_research_safety_errors(prices, (event,))[0]
    assert (
        "可得日期不足"
        in raw_research_safety_errors(prices, (replace(event, available_date=None),))[0]
    )
    assert not raw_research_safety_errors(
        prices, (replace(event, symbol=Symbol("2330", Market.TPEX)),)
    )


def test_standard_and_health_gate_cannot_be_bypassed(tmp_path):
    prices = _prices()
    prices.loc[40:, ["open", "high", "low", "close"]] /= 3
    service = StrategyWorkspaceApplicationService(
        engine_factory=lambda **kw: pytest.fail("engine must not run")
    )
    definition = get_strategy_definition("breakout")
    values = _values()
    validation, plan = service.preflight(values=values, price_data=prices, definition=definition)
    assert not validation.can_execute
    data = service.inspect_data(
        price_data=prices, symbol="2330", market="TWSE", source=None, definition=definition
    )
    strategy = create_strategy("breakout", {"lookback": 5, "target_percent": 0.4})
    assert (
        service.run_standard(
            values=values, strategy=strategy, price_data=prices, fundamentals=None, data=data
        ).status
        == "blocked"
    )
    assert (
        service.run_health(
            strategy=strategy, price_data=prices, fundamentals=None, health_plan=plan, values=values
        ).status
        == "blocked"
    )
    corrupt = tmp_path / "actions.csv"
    corrupt.write_text("broken", encoding="utf-8")
    service.corporate_actions_path = corrupt
    assert "契約無效" in service.integrity_errors(_prices())[0]


def test_strict_default_never_substitutes_report_date():
    fund = pd.DataFrame(
        [
            dict(
                symbol="2330",
                date="2024-01-01",
                fiscal_period="2023Q4",
                eps_growth=0.3,
                revenue_growth=0.3,
                roe=0.3,
                debt_ratio=0.2,
            )
        ]
    )
    assert visible_fundamentals_as_of(fund, "2024-04-01").data.empty
    strategy = FundamentalGrowthStrategy(quantity=1)
    signals = strategy.generate_signals(_prices(), fund)
    assert signals.signal.eq(0).all()
    legacy = FundamentalGrowthStrategy(quantity=1, point_in_time_mode="legacy").generate_signals(
        _prices(), fund
    )
    assert legacy.signal.eq(1).any()
    assert legacy.attrs["fundamental_warnings"]
    fund["available_date"] = "2024-02-01"
    signals = strategy.generate_signals(_prices(), fund)
    assert signals.loc[signals.date < "2024-02-01", "signal"].eq(0).all()
    assert signals.loc[signals.signal.eq(1), "date"].iloc[0] == "2024-02-01"


@pytest.mark.parametrize("bad", [None, 0, float("inf"), -1])
def test_invalid_raw_prices_fail_closed(bad):
    prices = _prices()
    prices.loc[5, "open"] = bad
    assert raw_research_safety_errors(prices)


def test_fundamental_missing_availability_blocks_workspace_not_zero_performance():
    service = StrategyWorkspaceApplicationService()
    prices = _prices()
    definition = get_strategy_definition("fundamental_growth")
    data = service.inspect_data(
        price_data=prices, symbol="2330", market="TWSE", source=None, definition=definition
    )
    values = _values(strategy_key="fundamental_growth", has_fundamentals=True)
    strategy = FundamentalGrowthStrategy(target_percent=0.4)
    fund = pd.DataFrame(
        [
            dict(
                symbol="2330",
                date="2024-01-01",
                eps_growth=0.2,
                revenue_growth=0.2,
                roe=0.2,
                debt_ratio=0.2,
            )
        ]
    )
    result = service.run_standard(
        values=values, strategy=strategy, price_data=prices, fundamentals=fund, data=data
    )
    assert result.status == "blocked" and result.result is None
    assert any("available_date" in message for message in result.validation.errors)


def test_workspace_ui_disables_both_runs_for_distribution(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path))
    script = """
import pandas as pd
import streamlit as st
from stock_tool.application.strategy_workspace import StrategyWorkspaceApplicationService
from stock_tool.dashboard.pages.strategy_workspace import render_strategy_workspace
close = [3000.0] * 45 + [1000.0] * 45
st.session_state.price_data = pd.DataFrame(dict(date=pd.date_range('2025-01-01', periods=90), symbol='6669', market='TWSE', open=close, high=close, low=close, close=close, volume=1000))
st.session_state.price_data_source = {'source_type':'synthetic'}
st.session_state.fundamentals = None
render_strategy_workspace(st, service=StrategyWorkspaceApplicationService())
"""
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    assert any("重大不連續" in item.value for item in app.error)
    for label in ("執行標準回測", "執行完整策略健檢"):
        assert next(item for item in app.button if item.label == label).disabled
    assert not any(item.value == "標準回測結果" for item in app.subheader)
