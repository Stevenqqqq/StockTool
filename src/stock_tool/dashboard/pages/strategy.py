"""Research-only strategy health presentation built around the validation layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from stock_tool.backtest import BacktestEngine
from stock_tool.backtest.validation import (
    OutOfSampleConfig,
    ParameterSensitivityConfig,
    StrategyValidationService,
    ValidationPeriod,
    WalkForwardConfig,
)
from stock_tool.strategies.base import StrategyBase
from stock_tool.strategies.registry import StrategyDefinition


@dataclass(frozen=True, slots=True)
class StrategyHealthPreflight:
    """Bounded, transparent validation plan derived from loaded price data."""

    can_run: bool
    message: str
    train_period: ValidationPeriod | None
    test_period: ValidationPeriod | None
    walk_forward: WalkForwardConfig | None
    sensitivity: ParameterSensitivityConfig | None
    expected_sensitivity_combinations: int


def build_strategy_health_preflight(
    *, price_data: pd.DataFrame, definition: StrategyDefinition
) -> StrategyHealthPreflight:
    """Create a conservative deterministic plan without executing a backtest."""

    if "date" not in price_data.columns:
        return _unavailable_preflight("資料不足：缺少日期欄位。")
    dates = pd.to_datetime(price_data["date"], errors="coerce").dropna().drop_duplicates()
    dates = dates.sort_values().reset_index(drop=True)
    required_rows = max(definition.minimum_rows, 12)
    if len(dates) < required_rows:
        return _unavailable_preflight(
            f"資料不足：目前 {len(dates)} 個交易日；{definition.display_name_zh} 建議至少 {required_rows} 個交易日。"
        )
    train_end_index = max(int(len(dates) * 0.7) - 1, 0)
    if train_end_index >= len(dates) - 1:
        return _unavailable_preflight("資料不足：無法形成獨立的樣本外期間。")
    train_period = ValidationPeriod(dates.iloc[0], dates.iloc[train_end_index])
    test_period = ValidationPeriod(dates.iloc[train_end_index + 1], dates.iloc[-1])
    # Keep enough non-overlapping test bars for the minimum two-fold contract.
    # The page does not silently lower a strategy's own minimum warm-up need.
    train_bars = max(definition.minimum_rows, len(dates) // 2)
    remaining_bars = len(dates) - train_bars
    if remaining_bars < 10:
        return _unavailable_preflight("資料不足：無法形成至少兩個獨立樣本外 fold。")
    test_bars = min(20, remaining_bars // 2)
    walk = WalkForwardConfig(
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=test_bars,
        max_folds=10,
    )
    sensitivity = _default_sensitivity(definition)
    return StrategyHealthPreflight(
        can_run=True,
        message="資料與日期切分可用；結果僅供研究健檢，不構成買賣建議。",
        train_period=train_period,
        test_period=test_period,
        walk_forward=walk,
        sensitivity=sensitivity,
        expected_sensitivity_combinations=sensitivity.expected_combinations,
    )


def render_strategy_health(
    st: Any,
    *,
    strategy: StrategyBase,
    price_data: pd.DataFrame,
    fundamentals: pd.DataFrame | None,
    engine_factory: Callable[[], BacktestEngine],
) -> None:
    """Render optional strategy health without changing the retained single backtest."""

    from stock_tool.strategies.registry import get_strategy_definition

    definition = get_strategy_definition(strategy.name)
    preflight = build_strategy_health_preflight(price_data=price_data, definition=definition)
    st.divider()
    st.subheader("策略健檢")
    st.caption("以固定參數、相同成本與既有次一根 K 棒成交模型進行研究驗證，不推薦任何策略。")
    st.markdown(f"**{definition.display_name_zh}**：{definition.description}")
    with st.expander("策略限制與資料需求", expanded=False):
        st.write(f"需要欄位：{', '.join(definition.required_price_fields)}")
        st.write(f"最低建議資料：{definition.minimum_rows} 筆。")
        for risk_note in definition.risk_notes:
            st.write(f"限制：{risk_note}")
    if not preflight.can_run:
        st.warning(preflight.message)
        return
    assert preflight.train_period is not None
    assert preflight.test_period is not None
    assert preflight.walk_forward is not None
    assert preflight.sensitivity is not None
    st.info(
        "樣本內："
        f"{preflight.train_period.start} 至 {preflight.train_period.end}；樣本外："
        f"{preflight.test_period.start} 至 {preflight.test_period.end}。"
    )
    st.caption(
        f"前推驗證最多 {preflight.walk_forward.max_folds} 個 fold；"
        f"敏感度預計 {preflight.expected_sensitivity_combinations} 次回測（上限 25）。"
    )
    if not st.button("執行策略健檢", key="run_strategy_health"):
        return
    service = StrategyValidationService(engine_factory=engine_factory)
    try:
        with st.spinner("正在執行樣本外、前推與鄰近參數研究健檢…"):
            oos = service.run_out_of_sample(
                strategy=strategy,
                price_data=price_data,
                fundamentals=fundamentals,
                config=OutOfSampleConfig(preflight.train_period, preflight.test_period),
            )
            walk = service.run_walk_forward(
                strategy=strategy,
                price_data=price_data,
                fundamentals=fundamentals,
                config=preflight.walk_forward,
            )
            sensitivity = service.run_parameter_sensitivity(
                strategy=strategy,
                price_data=price_data,
                fundamentals=fundamentals,
                config=preflight.sensitivity,
            )
    except Exception as exc:  # The optional validation must not hide the retained backtest result.
        st.warning(f"策略健檢無法完成：{exc}")
        return
    st.session_state["strategy_validation_result"] = (oos, walk, sensitivity)
    _render_oos(st, oos)
    _render_walk_forward(st, walk)
    _render_sensitivity(st, sensitivity)


def _default_sensitivity(definition: StrategyDefinition) -> ParameterSensitivityConfig:
    parameter = definition.sensitivity_parameters[0]
    default = definition.default_parameters[parameter]
    if isinstance(default, int):
        values: tuple[object, ...] = (max(1, default - 1), default, default + 1)
    elif isinstance(default, float):
        values = (max(0.0, default - 0.02), default, default + 0.02)
    else:
        values = (default,)
    return ParameterSensitivityConfig({parameter: values}, max_combinations=25)


def _unavailable_preflight(message: str) -> StrategyHealthPreflight:
    return StrategyHealthPreflight(False, message, None, None, None, None, 0)


def _render_oos(st: Any, result: Any) -> None:
    st.markdown("#### 樣本內／樣本外比較")
    if result.status != "ready" or result.in_sample is None or result.out_of_sample is None:
        st.warning("資料不足：無法完成樣本內／樣本外比較。")
        _render_warnings(st, result.warnings)
        return
    comparison = pd.DataFrame(
        [
            {
                "期間": "樣本內",
                "總報酬": result.in_sample.metrics.total_return,
                "最大回撤": result.in_sample.metrics.max_drawdown,
                "交易次數": result.in_sample.metrics.number_of_trades,
            },
            {
                "期間": "樣本外",
                "總報酬": result.out_of_sample.metrics.total_return,
                "最大回撤": result.out_of_sample.metrics.max_drawdown,
                "交易次數": result.out_of_sample.metrics.number_of_trades,
            },
        ]
    )
    st.dataframe(comparison, use_container_width=True)
    _render_warnings(st, result.warnings)


def _render_walk_forward(st: Any, result: Any) -> None:
    st.markdown("#### Walk-forward 前推驗證")
    if result.status != "ready":
        st.warning("資料不足：無法形成至少兩個有效樣本外 fold。")
        _render_warnings(st, result.warnings)
        return
    rows = [
        {
            "Fold": fold.fold_number,
            "樣本內": f"{fold.train_period.start} 至 {fold.train_period.end}",
            "樣本外": f"{fold.test_period.start} 至 {fold.test_period.end}",
            "樣本外總報酬": fold.test_run.metrics.total_return,
            "交易次數": fold.test_run.metrics.number_of_trades,
        }
        for fold in result.folds
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    _render_warnings(st, result.warnings)


def _render_sensitivity(st: Any, result: Any) -> None:
    st.markdown("#### 參數敏感度")
    if result.status != "ready":
        st.warning("資料不足：參數敏感度無法驗證。")
        _render_warnings(st, result.warnings)
        return
    rows = [
        {
            "參數": ", ".join(f"{key}={value}" for key, value in run.parameters),
            "總報酬": run.total_return,
            "交易次數": run.run.metrics.number_of_trades,
        }
        for run in result.runs
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    _render_warnings(st, result.warnings)
    st.caption("所有組合使用相同資料期間、成本與執行模型；不以最高報酬視為推薦參數。")


def _render_warnings(st: Any, warnings: tuple[Any, ...]) -> None:
    for warning in warnings:
        st.caption(f"注意：{warning.message}")
