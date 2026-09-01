from __future__ import annotations

import json
from typing import Any

import pandas as pd
from streamlit.testing.v1 import AppTest

from stock_tool.application.strategy_workspace import StrategyWorkspaceApplicationService
from stock_tool.backtest import BacktestEngine
from stock_tool.dashboard.backtest_ui import (
    BacktestCostPreset,
    BacktestFormValues,
)
from stock_tool.strategies.registry import create_strategy, get_strategy_definition


def _prices(rows: int = 100) -> pd.DataFrame:
    close = [100.0 + index * 0.5 + (index % 5) for index in range(rows)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "symbol": "2330",
            "market": "TWSE",
            "open": close,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": 1000,
        }
    )


def _values(**overrides: object) -> BacktestFormValues:
    defaults = {
        "symbol": "2330",
        "market": "TWSE",
        "strategy_key": "breakout",
        "strategy_parameters": {"lookback": 5, "target_percent": 0.4},
        "data_rows": 100,
        "data_start": "2024-01-01",
        "data_end": "2024-04-09",
        "data_source": "fixture",
        "initial_cash": 100_000.0,
        "allocation_rate": 0.4,
        "max_position_pct": 0.5,
        "commission_rate": 0.001425,
        "tax_rate": 0.003,
        "slippage_rate": 0.001,
        "cost_preset": BacktestCostPreset.TAIWAN_STOCK,
        "trailing_stop_pct": None,
        "has_fundamentals": False,
        "market_costs_confirmed": True,
    }
    values = {**defaults, **overrides}
    return BacktestFormValues(
        symbol=str(values["symbol"]),
        market=str(values["market"]),
        strategy_key=str(values["strategy_key"]),
        strategy_parameters=values["strategy_parameters"],
        data_rows=int(values["data_rows"]),
        data_start=values["data_start"],
        data_end=values["data_end"],
        data_source=values["data_source"],
        initial_cash=float(values["initial_cash"]),
        allocation_rate=float(values["allocation_rate"]),
        max_position_pct=float(values["max_position_pct"]),
        commission_rate=float(values["commission_rate"]),
        tax_rate=float(values["tax_rate"]),
        slippage_rate=float(values["slippage_rate"]),
        cost_preset=values["cost_preset"],
        trailing_stop_pct=values["trailing_stop_pct"],
        has_fundamentals=bool(values["has_fundamentals"]),
        market_costs_confirmed=bool(values["market_costs_confirmed"]),
    )


def test_strategy_workspace_classifies_missing_partial_and_stale_data() -> None:
    service = StrategyWorkspaceApplicationService()
    definition = get_strategy_definition("breakout")

    missing = service.inspect_data(
        price_data=None,
        symbol="2330",
        market="TWSE",
        source=None,
        definition=definition,
    )
    assert missing.status == "missing"

    partial = service.inspect_data(
        price_data=_prices().drop(columns=["high"]),
        symbol="2330",
        market="TWSE",
        source={"source_type": "fixture"},
        definition=definition,
    )
    assert partial.status == "partial"
    assert "high" in partial.missing_fields

    stale = service.inspect_data(
        price_data=_prices(),
        symbol="2330",
        market="TWSE",
        source={"source_type": "cache", "end_date": "2024-04-09"},
        definition=definition,
    )
    assert stale.status == "stale"


def test_strategy_workspace_manifest_is_deterministic_and_private_path_free() -> None:
    service = StrategyWorkspaceApplicationService()
    prices = _prices()
    definition = get_strategy_definition("breakout")
    data = service.inspect_data(
        price_data=prices,
        symbol="2330",
        market="TWSE",
        source={"source_type": "fixture", "end_date": "2024-04-09"},
        definition=definition,
    )
    strategy = create_strategy("breakout", {"lookback": 5, "target_percent": 0.4})
    first = service.build_manifest(values=_values(), data=data, strategy=strategy, status="planned")
    second = service.build_manifest(
        values=_values(), data=data, strategy=strategy, status="planned"
    )

    assert first.digest == second.digest
    payload = json.loads(first.to_json())
    assert payload["core"] == json.loads(second.to_json())["core"]
    assert "C:\\Users" not in first.to_json()
    assert service.result_is_current(first, second)
    changed = service.build_manifest(
        values=_values(initial_cash=200_000.0),
        data=data,
        strategy=strategy,
        status="planned",
    )
    assert not service.result_is_current(changed, first)


def test_strategy_workspace_standard_run_uses_existing_engine_and_manifest() -> None:
    service = StrategyWorkspaceApplicationService()
    prices = _prices()
    definition = get_strategy_definition("breakout")
    data = service.inspect_data(
        price_data=prices,
        symbol="2330",
        market="TWSE",
        source={"source_type": "fixture", "end_date": "2024-04-09"},
        definition=definition,
    )
    strategy = create_strategy("breakout", {"lookback": 5, "target_percent": 0.4})
    run = service.run_standard(
        values=_values(), strategy=strategy, price_data=prices, fundamentals=None, data=data
    )
    assert run.status == "standard_complete"
    assert run.result is not None
    assert run.manifest.core["execution"]["model"] == "T+1"
    assert run.manifest.core["costs"]["commission"] == 0.001425


def test_strategy_workspace_rejects_unknown_market_without_confirmation() -> None:
    service = StrategyWorkspaceApplicationService()
    values = _values(market="UNKNOWN", market_costs_confirmed=False)
    validation = service.preflight(
        values=values,
        price_data=_prices(),
        definition=get_strategy_definition("breakout"),
    )[0]
    assert not validation.can_execute


def test_strategy_workspace_rejects_allocation_above_position_limit() -> None:
    service = StrategyWorkspaceApplicationService()
    validation = service.preflight(
        values=_values(allocation_rate=0.8, max_position_pct=0.5),
        price_data=_prices(),
        definition=get_strategy_definition("breakout"),
    )[0]
    assert not validation.can_execute


def test_strategy_workspace_binds_all_costs_and_allocation_to_engine_and_manifest() -> None:
    captured: dict[str, object] = {}

    class CaptureEngine(BacktestEngine):
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            super().__init__(**kwargs)

    service = StrategyWorkspaceApplicationService(engine_factory=CaptureEngine)
    prices = _prices()
    definition = get_strategy_definition("breakout")
    data = service.inspect_data(
        price_data=prices,
        symbol="2330",
        market="TWSE",
        source={"source_type": "fixture", "end_date": "2024-04-09"},
        definition=definition,
    )
    values = _values(
        allocation_rate=0.4,
        max_position_pct=0.5,
        initial_cash=250_000.0,
        commission_rate=0.002,
        tax_rate=0.001,
        slippage_rate=0.003,
        trailing_stop_pct=0.1,
    )
    strategy = create_strategy(
        "breakout", {"lookback": 5, "target_percent": values.allocation_rate}
    )
    run = service.run_standard(
        values=values, strategy=strategy, price_data=prices, fundamentals=None, data=data
    )
    assert run.result is not None
    assert strategy.parameters["target_percent"] == values.allocation_rate
    assert captured["initial_cash"] == values.initial_cash
    assert captured["max_position_pct"] == values.max_position_pct
    assert captured["trailing_stop_pct"] == values.trailing_stop_pct
    broker: Any = captured["broker_config"]
    assert broker.commission_rate == values.commission_rate
    assert broker.tax_rate == values.tax_rate
    assert broker.slippage_rate == values.slippage_rate
    costs = run.manifest.core["costs"]
    assert costs["allocation"] == values.allocation_rate
    assert costs["initial_cash"] == values.initial_cash
    assert costs["commission"] == values.commission_rate
    assert costs["tax"] == values.tax_rate
    assert costs["slippage"] == values.slippage_rate
    assert costs["trailing_stop"] == values.trailing_stop_pct


def test_strategy_workspace_rejects_strategy_allocation_mismatch() -> None:
    service = StrategyWorkspaceApplicationService()
    prices = _prices()
    definition = get_strategy_definition("breakout")
    data = service.inspect_data(
        price_data=prices,
        symbol="2330",
        market="TWSE",
        source={"source_type": "fixture", "end_date": "2024-04-09"},
        definition=definition,
    )
    values = _values(allocation_rate=0.4, max_position_pct=0.5)
    mismatched = create_strategy("breakout", {"lookback": 5, "target_percent": 0.2})
    run = service.run_standard(
        values=values,
        strategy=mismatched,
        price_data=prices,
        fundamentals=None,
        data=data,
    )
    assert run.status == "blocked"
    assert any("投入比例" in error for error in run.validation.errors)
    assert run.result is None


def test_strategy_workspace_market_binding_is_per_symbol_and_conflicts_fail_closed() -> None:
    service = StrategyWorkspaceApplicationService()
    definition = get_strategy_definition("breakout")
    mixed = pd.concat(
        [
            _prices(30).assign(symbol="2330", market="TWSE"),
            _prices(30).assign(symbol="6488", market="TPEX"),
            _prices(30).assign(symbol="AAPL", market="US"),
        ],
        ignore_index=True,
    )
    for symbol, market in (("2330", "TWSE"), ("6488", "TPEX"), ("AAPL", "US")):
        snapshot = service.inspect_data(
            price_data=mixed.loc[mixed["symbol"] == symbol],
            symbol=symbol,
            market=market,
            source={"source_type": "fixture", "end_date": "2024-01-30"},
            definition=definition,
        )
        assert snapshot.market == market
        assert snapshot.status == "stale"
    conflict = service.inspect_data(
        price_data=mixed.loc[mixed["symbol"].isin(["2330", "6488"])],
        symbol="mixed",
        market="CONFLICT",
        source={"source_type": "fixture", "end_date": "2024-01-30"},
        definition=definition,
    )
    assert conflict.status == "partial"
    assert "market" in conflict.missing_fields


def test_native_strategy_workspace_apptest_runs_health_and_expires_after_setting_change(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    script = """
import streamlit as st
import pandas as pd
from stock_tool.application.strategy_workspace import StrategyWorkspaceApplicationService
from stock_tool.dashboard.pages.strategy_workspace import render_strategy_workspace

if "price_data" not in st.session_state:
    close = [100.0 + index * 0.5 + (index % 5) for index in range(90)]
    st.session_state.price_data = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=90, freq="D"),
        "symbol": "2330", "market": "TWSE", "open": close,
        "high": [value + 1 for value in close], "low": [value - 1 for value in close],
        "close": close, "volume": 1000,
    })
    st.session_state.price_data_source = {"source_type": "fixture", "end_date": "2099-01-01"}
    st.session_state.fundamentals = None

render_strategy_workspace(st, service=StrategyWorkspaceApplicationService())
"""
    app = AppTest.from_string(script).run(timeout=60)
    assert not app.exception
    assert any(item.label == "執行標準回測" and not item.disabled for item in app.button)
    next(item for item in app.button if item.label == "執行標準回測").click().run(timeout=60)
    assert any(item.value == "標準回測結果" for item in app.subheader)
    allocation = next(item for item in app.slider if "投入比例" in item.label)
    allocation.set_value(80.0).run(timeout=20)
    assert any("設定已變更" in item.value for item in app.warning)
    assert next(item for item in app.button if item.label == "執行標準回測").disabled
    allocation.set_value(40.0).run(timeout=20)
    next(item for item in app.button if item.label == "執行標準回測").click().run(timeout=60)
    assert any(item.value == "標準回測結果" for item in app.subheader)
    next(item for item in app.button if item.label == "執行完整策略健檢").click().run(timeout=120)
    assert any("Walk-forward" in item.value for item in app.markdown)
    assert any("參數" in item.value for item in app.markdown)


def test_strategy_workspace_health_is_bounded_and_preserves_standard_result() -> None:
    service = StrategyWorkspaceApplicationService()
    prices = _prices(120)
    definition = get_strategy_definition("breakout")
    strategy = create_strategy("breakout", {"lookback": 5, "target_percent": 0.4})
    values = _values(data_rows=len(prices), data_end="2024-04-29")
    validation, plan = service.preflight(values=values, price_data=prices, definition=definition)
    assert validation.can_execute
    assert plan.walk_forward.max_folds <= 10
    assert plan.expected_sensitivity_combinations <= 25
    run = service.run_health(
        strategy=strategy,
        price_data=prices,
        fundamentals=None,
        health_plan=plan,
        values=values,
    )
    assert run.status in {"complete", "partial", "blocked"}


def test_strategy_workspace_metrics_formatting_is_ratio_based() -> None:
    from stock_tool.dashboard.presentation_mapper import format_percentage

    # Total return ratio of 0.5667 must format as +56.67%, not +0.57%
    formatted_return = format_percentage(0.5667, with_sign=True, is_ratio=True)
    assert formatted_return == "+56.67%"
    assert formatted_return != "+0.57%"

    # Max drawdown ratio of 0.1234 must format as 12.34%, not 0.12%
    formatted_drawdown = format_percentage(0.1234, is_ratio=True)
    assert formatted_drawdown == "12.34%"
    assert formatted_drawdown != "0.12%"


def test_strategy_workspace_render_run_branches() -> None:
    from types import SimpleNamespace
    from stock_tool.dashboard.pages.strategy_workspace import _render_run

    service = StrategyWorkspaceApplicationService()

    class FakeSt:
        def __init__(self):
            self.warnings = []
            self.errors = []
            self.subheaders = []
            self.infos = []

        def warning(self, msg):
            self.warnings.append(msg)

        def error(self, msg):
            self.errors.append(msg)

        def subheader(self, msg):
            self.subheaders.append(msg)

        def info(self, msg):
            self.infos.append(msg)

        def columns(self, n):
            return [SimpleNamespace(metric=lambda *a, **k: None) for _ in range(n)]

    # Test blocked run
    st = FakeSt()
    blocked_run = SimpleNamespace(status="blocked")
    _render_run(st, blocked_run, None, service)
    assert any("標準回測未執行" in w for w in st.warnings)

    # Test error run
    st = FakeSt()
    error_run = SimpleNamespace(status="error", health_message="計算錯誤")
    _render_run(st, error_run, None, service)
    assert any("計算錯誤" in e for e in st.errors)
