from __future__ import annotations

from types import SimpleNamespace

import stock_tool.dashboard.app as dashboard_app
from stock_tool.dashboard.app import BACKTEST_STRATEGY_LABELS
from stock_tool.backtest import BrokerConfig
from stock_tool.dashboard.backtest_ui import (
    BACKTEST_RESEARCH_NOTICE,
    BacktestCostPreset,
    BacktestFormValues,
    build_backtest_broker_config,
    build_backtest_summary,
    no_trade_explanation,
    percent_to_rate,
    rate_to_percent,
    resolve_backtest_currency,
    resolve_cost_preset,
    strategy_guidance,
    validate_backtest_form,
)
from stock_tool.dashboard.portfolio_guidance import (
    PORTFOLIO_RISK_INDEPENDENCE_NOTICE,
    portfolio_missing_data_guidance,
)
from stock_tool.domain.models import MissingData, MissingDataState


def _values(**changes: object) -> BacktestFormValues:
    base: dict[str, object] = {
        "symbol": "2330",
        "market": "TWSE",
        "strategy_key": "ma_cross",
        "strategy_parameters": {"short_window": 20, "long_window": 60},
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
        "trailing_stop_pct": None,
        "has_fundamentals": True,
        "market_costs_confirmed": True,
    }
    base.update(changes)
    return BacktestFormValues(**base)


class _SessionState(dict):
    def __getattr__(self, name: str) -> object:
        return self[name]

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _WidgetSt:
    def __init__(self) -> None:
        self.session_state = _SessionState()
        self.events: list[tuple[str, str]] = []

    def __enter__(self) -> _WidgetSt:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def columns(self, count: int) -> list[_WidgetSt]:
        return [self] * count

    def metric(self, label: str, _value: object) -> None:
        self.events.append(("metric", label))

    def caption(self, message: str) -> None:
        self.events.append(("caption", message))

    def info(self, message: str) -> None:
        self.events.append(("info", message))

    def success(self, message: str) -> None:
        self.events.append(("success", message))

    def write(self, message: str) -> None:
        self.events.append(("write", message))

    def expander(self, _label: str) -> _WidgetSt:
        return self

    def selectbox(self, _label: str, options: list[str], **kwargs: object) -> str:
        key = str(kwargs.get("key"))
        self.session_state.setdefault(key, options[0])
        return str(self.session_state[key])

    def number_input(self, _label: str, *args: object, **kwargs: object) -> float:
        key = kwargs.get("key")
        value = float(kwargs.get("value", 0.0))
        if key is None:
            return value
        self.session_state.setdefault(str(key), value)
        return float(self.session_state[str(key)])

    def slider(self, _label: str, *args: object, **kwargs: object) -> float:
        if "value" in kwargs:
            return float(kwargs["value"])
        return float(args[2])


def test_percent_rate_conversions_are_precise_and_round_trip() -> None:
    assert percent_to_rate(40.0) == 0.40
    assert percent_to_rate(0.1425) == 0.001425
    assert rate_to_percent(0.001425) == 0.1425
    assert percent_to_rate(rate_to_percent(0.40)) == 0.40


def test_market_defaults_resolve_to_actual_broker_costs() -> None:
    assert resolve_cost_preset("US") is BacktestCostPreset.US_STOCK
    assert resolve_cost_preset("TWSE") is BacktestCostPreset.TAIWAN_STOCK
    assert resolve_backtest_currency("US") == "USD"
    assert resolve_backtest_currency("TPEX") == "TWD"

    us = _values(
        symbol="MU",
        market="US",
        cost_preset=BacktestCostPreset.US_STOCK,
        commission_rate=0.001,
        tax_rate=0.0,
        slippage_rate=0.001,
    )
    tw = _values()
    assert build_backtest_broker_config(us) == BrokerConfig(
        commission_rate=0.001, tax_rate=0.0, slippage_rate=0.001, execution_price_col="open"
    )
    assert build_backtest_broker_config(tw) == BrokerConfig(
        commission_rate=0.001425, tax_rate=0.003, slippage_rate=0.001, execution_price_col="open"
    )


def test_unknown_market_is_custom_and_does_not_guess_currency_or_costs() -> None:
    assert resolve_cost_preset("UNKNOWN") is BacktestCostPreset.CUSTOM
    assert resolve_backtest_currency("UNKNOWN") is None
    result = validate_backtest_form(
        _values(
            market="UNKNOWN", cost_preset=BacktestCostPreset.CUSTOM, market_costs_confirmed=False
        )
    )
    assert not result.can_execute
    assert any("確認" in item for item in result.errors)


def test_custom_cost_preset_is_retained_after_rerun() -> None:
    assert (
        resolve_cost_preset("US", current_preset=BacktestCostPreset.CUSTOM, is_user_edited=True)
        is BacktestCostPreset.CUSTOM
    )


def test_dashboard_cost_state_uses_market_default_then_preserves_explicit_custom_rates() -> None:
    fake_st = SimpleNamespace(session_state=_SessionState())
    dashboard_app._prepare_backtest_cost_state(fake_st, "US")
    assert fake_st.session_state.backtest_cost_preset == BacktestCostPreset.US_STOCK.value
    assert fake_st.session_state.backtest_tax_pct == 0.0

    fake_st.session_state.backtest_cost_preset = BacktestCostPreset.CUSTOM.value
    fake_st.session_state.backtest_costs_user_edited = True
    fake_st.session_state.backtest_commission_pct = 0.2222
    dashboard_app._prepare_backtest_cost_state(fake_st, "TWSE")

    assert fake_st.session_state.backtest_cost_preset == BacktestCostPreset.CUSTOM.value
    assert fake_st.session_state.backtest_commission_pct == 0.2222


def test_dashboard_cost_controls_keep_engine_rates_in_percent_ui() -> None:
    fake_st = _WidgetSt()
    preset, commission, tax, slippage = dashboard_app._render_backtest_cost_controls(
        fake_st, "TWSE"
    )

    assert preset is BacktestCostPreset.TAIWAN_STOCK
    assert (commission, tax, slippage) == (0.001425, 0.003, 0.001)

    fake_st.session_state.backtest_cost_preset = BacktestCostPreset.CUSTOM.value
    fake_st.session_state.backtest_costs_user_edited = True
    fake_st.session_state.backtest_commission_pct = 0.2222
    preset, commission, _tax, _slippage = dashboard_app._render_backtest_cost_controls(
        fake_st, "US"
    )
    assert preset is BacktestCostPreset.CUSTOM
    assert commission == 0.002222


def test_preflight_blocks_invalid_allocation_and_ma_windows_with_guidance() -> None:
    allocation = validate_backtest_form(_values(allocation_rate=0.60, max_position_pct=0.50))
    assert not allocation.can_execute
    assert any("投入比例" in item for item in allocation.errors)

    windows = validate_backtest_form(
        _values(strategy_parameters={"short_window": 60, "long_window": 20})
    )
    assert not windows.can_execute
    assert any("短均線" in item for item in windows.errors)


def test_preflight_blocks_insufficient_rows_and_missing_fundamentals() -> None:
    rows = validate_backtest_form(_values(data_rows=20))
    assert not rows.can_execute
    assert rows.next_steps

    fundamentals = validate_backtest_form(
        _values(strategy_key="fundamental_growth", has_fundamentals=False)
    )
    assert not fundamentals.can_execute
    assert any("基本面" in item for item in fundamentals.errors)


def test_summary_uses_actual_engine_values_and_strategy_guidance_is_research_only() -> None:
    values = _values(trailing_stop_pct=0.10)
    summary = build_backtest_summary(values)
    assert summary.broker_config == build_backtest_broker_config(values)
    assert summary.execution_model == "次一根 K 棒開盤價"
    assert summary.trailing_stop_status == "啟用（10.00%）"

    guidance = strategy_guidance("ma_cross")
    assert guidance.observe
    assert guidance.buy_signal
    assert guidance.sell_signal
    assert "推薦" not in " ".join(guidance.limitations)


def test_preflight_does_not_mutate_form_values() -> None:
    values = _values(strategy_parameters={"short_window": 20, "long_window": 60})
    before = dict(values.strategy_parameters)
    validate_backtest_form(values)
    assert values.strategy_parameters == before


def test_zero_trade_state_is_neutral_and_nonzero_results_have_no_empty_state() -> None:
    assert "不代表策略成功或失敗" in (no_trade_explanation(0) or "")
    assert no_trade_explanation(1) is None


def test_backtest_and_portfolio_notices_explain_their_independent_workflows() -> None:
    assert "不會自動下單" in BACKTEST_RESEARCH_NOTICE
    assert "使用投資組合風險不需要先執行回測" in BACKTEST_RESEARCH_NOTICE
    assert "不需要先執行策略回測" in PORTFOLIO_RISK_INDEPENDENCE_NOTICE


def test_dashboard_renders_preflight_and_zero_trade_interpretation() -> None:
    fake_st = _WidgetSt()
    values = _values()
    summary = build_backtest_summary(values)
    dashboard_app._display_backtest_preflight(fake_st, summary, validate_backtest_form(values))
    result = SimpleNamespace(
        trades=[],
        metrics=SimpleNamespace(
            total_return=0.0,
            cagr=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            number_of_trades=0,
        ),
    )
    dashboard_app._display_backtest_interpretation(fake_st, result, summary)

    messages = " ".join(message for _kind, message in fake_st.events)
    assert "設定可執行" in messages
    assert "不代表策略成功或失敗" in messages


def test_dashboard_strategy_controls_keep_existing_strategy_parameters() -> None:
    fake_st = _WidgetSt()
    strategies = {
        "ma_cross": dashboard_app._strategy_controls(
            fake_st, strategy_key="ma_cross", target_percent=0.40
        ),
        "breakout": dashboard_app._strategy_controls(
            fake_st, strategy_key="breakout", target_percent=0.40
        ),
        "rsi_reversal": dashboard_app._strategy_controls(
            fake_st, strategy_key="rsi_reversal", target_percent=0.40
        ),
        "macd_trend": dashboard_app._strategy_controls(
            fake_st, strategy_key="macd_trend", target_percent=0.40
        ),
        "volume_price_breakout": dashboard_app._strategy_controls(
            fake_st, strategy_key="volume_price_breakout", target_percent=0.40
        ),
        "fundamental_growth": dashboard_app._strategy_controls(
            fake_st, strategy_key="fundamental_growth", target_percent=0.40
        ),
    }
    assert set(strategies) == set(BACKTEST_STRATEGY_LABELS)
    assert all(strategy.parameters["target_percent"] == 0.40 for strategy in strategies.values())


def test_portfolio_missing_data_guidance_has_clear_chinese_next_steps() -> None:
    guidance = portfolio_missing_data_guidance(
        (
            MissingData("latest_price", MissingDataState.MISSING, "fixture"),
            MissingData("fx_rate_to_base", MissingDataState.MISSING, "fixture"),
            MissingData("technical_indicators", MissingDataState.MISSING, "fixture"),
            MissingData("fundamental_scores", MissingDataState.MISSING, "fixture"),
            MissingData("composite_score", MissingDataState.MISSING, "fixture"),
            MissingData("portfolio.identity", MissingDataState.UNKNOWN, "fixture"),
        )
    )
    actions = " ".join(item.next_step for item in guidance)
    assert "更新持股價格" in actions
    assert "更新匯率" in actions
    assert "歷史股價" in actions
    assert "基本面" in actions
    assert "Research Workspace" in actions
    assert "確認股票代號" in actions
