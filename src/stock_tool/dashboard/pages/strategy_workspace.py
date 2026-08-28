"""Native Streamlit Strategy workspace using the existing research contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from stock_tool.application.strategy_workspace import (
    StrategyDataSnapshot,
    StrategyHealthRun,
    StrategyRunManifest,
    StrategyWorkspaceApplicationService,
)
from stock_tool.dashboard.backtest_ui import (
    BacktestFormValues,
    cost_assumptions,
    resolve_cost_preset,
)
from stock_tool.dashboard.state import navigate_to_workspace
from stock_tool.domain.models import Market, Symbol
from stock_tool.strategies.registry import (
    StrategyDefinition,
    create_strategy,
    strategy_display_labels,
)


def render_strategy_workspace(
    st: Any,
    *,
    service: StrategyWorkspaceApplicationService,
    on_research: Callable[[str, str], None] | None = None,
) -> None:
    """Render a complete native strategy workflow without fetching new data."""

    st.subheader("策略研究工作區")
    st.caption("僅供研究驗證；不提供策略推薦、買賣建議或未來報酬預測。")
    prices = st.session_state.get("price_data")
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        st.info("尚未載入可用價格資料。請先到研究首頁載入標的，再回到策略工作區。")
        if st.button("回到研究首頁", key="strategy_workspace_home"):
            navigate_to_workspace(st.session_state, workspace="home")
            rerun = getattr(st, "rerun", None)
            if callable(rerun):
                rerun()
        return

    symbol, stock_data, market = _select_loaded_symbol(st, prices)
    if on_research is not None and st.button(
        "返回研究目前資料", key="strategy_workspace_return_research"
    ):
        on_research(symbol, market)
        return
    source = st.session_state.get("price_data_source")
    definition = _select_strategy(st, service)
    data = service.inspect_data(
        price_data=stock_data,
        symbol=symbol,
        market=market,
        source=source if isinstance(source, dict) else None,
        definition=definition,
    )
    _render_data_state(st, data)

    strategy, parameters, allocation_rate = _render_strategy_parameters(st, definition)
    costs = _render_cost_controls(st, market)
    values = BacktestFormValues(
        symbol=symbol,
        market=market,
        strategy_key=definition.key,
        strategy_parameters=parameters,
        data_rows=data.rows,
        data_start=data.start,
        data_end=data.end,
        data_source=data.source,
        initial_cash=costs["initial_cash"],
        allocation_rate=allocation_rate,
        max_position_pct=costs["max_position_pct"],
        commission_rate=costs["commission_rate"],
        tax_rate=costs["tax_rate"],
        slippage_rate=costs["slippage_rate"],
        cost_preset=costs["cost_preset"],
        trailing_stop_pct=costs["trailing_stop_pct"],
        has_fundamentals=isinstance(st.session_state.get("fundamentals"), pd.DataFrame),
        market_costs_confirmed=costs["market_costs_confirmed"],
    )
    validation, health_plan = service.preflight(
        values=values, price_data=stock_data, definition=definition
    )
    _render_preflight(st, validation, health_plan, data)

    current_manifest = (
        service.build_manifest(values=values, data=data, strategy=strategy, status="planned")
        if strategy is not None
        else None
    )
    previous_run = st.session_state.get("strategy_workspace_run")
    if previous_run is not None and hasattr(previous_run, "manifest"):
        if current_manifest is not None and not service.result_is_current(
            current_manifest, previous_run.manifest
        ):
            st.warning("設定已變更，先前結果可能過期；請重新執行策略。")

    action_columns = st.columns(2)
    with action_columns[0]:
        if st.button(
            "執行標準回測",
            key="strategy_workspace_run_standard",
            type="primary",
            disabled=not validation.can_execute or strategy is None,
        ):
            assert strategy is not None
            run = service.run_standard(
                values=values,
                strategy=strategy,
                price_data=stock_data,
                fundamentals=_optional_frame(st.session_state.get("fundamentals")),
                data=data,
            )
            st.session_state.strategy_workspace_run = run
            st.session_state.strategy_workspace_manifest = run.manifest
            st.rerun()
    with action_columns[1]:
        if st.button(
            "執行完整策略健檢",
            key="strategy_workspace_run_health",
            disabled=not validation.can_execute
            or strategy is None
            or not getattr(health_plan, "can_run", False),
        ):
            assert strategy is not None
            standard = service.run_standard(
                values=values,
                strategy=strategy,
                price_data=stock_data,
                fundamentals=_optional_frame(st.session_state.get("fundamentals")),
                data=data,
            )
            if standard.result is None:
                st.session_state.strategy_workspace_run = standard
            else:
                health = service.run_health(
                    strategy=strategy,
                    price_data=stock_data,
                    fundamentals=_optional_frame(st.session_state.get("fundamentals")),
                    health_plan=health_plan,
                    values=values,
                )
                st.session_state.strategy_workspace_run = _with_health(
                    standard, health, service, values, data, strategy
                )
            st.rerun()

    run = st.session_state.get("strategy_workspace_run")
    if run is not None and hasattr(run, "manifest"):
        _render_run(st, run, current_manifest, service)


def _loaded_identities(prices: pd.DataFrame) -> list[str]:
    """Return deterministic market-qualified identities from loaded rows."""
    if not {"symbol", "market"}.issubset(prices.columns):
        return []
    identities = set()
    for symbol, market in zip(prices["symbol"], prices["market"]):
        canonical = _canonical_identity(symbol, market)
        if canonical is not None:
            identities.add(canonical)
    return sorted(identities)


def _canonical_identity(symbol: object, market: object) -> str | None:
    try:
        parsed_market = Market.parse(str(market).strip().upper())
        parsed_symbol = Symbol.parse(str(symbol), market=parsed_market)
    except ValueError:
        return None
    return f"{parsed_market.value} / {parsed_symbol.code}"


def _preferred_identity(st: Any) -> str:
    context = st.session_state.get("strategy_workspace_handoff_context")
    if isinstance(context, dict):
        symbol = str(context.get("symbol") or "").strip()
        market = str(context.get("market") or "").strip().upper()
        if symbol and market:
            return f"{market} / {symbol}"
    return ""


def _select_loaded_symbol(st: Any, prices: pd.DataFrame) -> tuple[str, pd.DataFrame, str]:
    identities = _loaded_identities(prices)
    if not identities:
        return "", prices.iloc[0:0].copy(), "UNKNOWN"
    preferred = _preferred_identity(st)
    active = str(st.session_state.get("strategy_workspace_identity") or "")
    default = (
        preferred if preferred in identities else active if active in identities else identities[0]
    )
    identity = st.selectbox(
        "已載入標的（市場 / 代號）",
        identities,
        index=identities.index(default),
        key="strategy_workspace_identity",
    )
    market, symbol = (part.strip() for part in str(identity).split("/", 1))
    identities_for_rows = [
        _canonical_identity(row_symbol, row_market)
        for row_symbol, row_market in zip(prices["symbol"], prices["market"])
    ]
    selected = prices.loc[
        pd.Series(identities_for_rows, index=prices.index).eq(f"{market} / {symbol}")
    ].copy()
    st.session_state["active_symbol"] = symbol
    return symbol, selected, market


def _select_strategy(st: Any, service: StrategyWorkspaceApplicationService) -> StrategyDefinition:
    labels = strategy_display_labels()
    key = st.selectbox(
        "策略",
        list(labels),
        format_func=lambda value: labels[value],
        key="strategy_workspace_strategy",
    )
    return service.definition(key)


def _render_strategy_parameters(
    st: Any, definition: StrategyDefinition
) -> tuple[Any | None, dict[str, object], float]:
    parameters: dict[str, object] = {}
    for spec in definition.parameter_schema:
        default = definition.default_parameters.get(spec.key, 0)
        if spec.value_type == "integer":
            parameters[spec.key] = int(
                st.number_input(
                    spec.label_zh,
                    min_value=int(spec.minimum or 1),
                    value=int(default),
                    step=1,
                    key=f"strategy_workspace_parameter_{spec.key}",
                )
            )
        else:
            parameters[spec.key] = float(
                st.number_input(
                    spec.label_zh,
                    min_value=float(spec.minimum) if spec.minimum is not None else None,
                    max_value=float(spec.maximum) if spec.maximum is not None else None,
                    value=float(default),
                    step=0.1,
                    key=f"strategy_workspace_parameter_{spec.key}",
                )
            )
    allocation = float(
        st.slider(
            "策略投入比例 (%)",
            min_value=5.0,
            max_value=95.0,
            value=40.0,
            step=5.0,
            key="strategy_workspace_allocation",
        )
    )
    parameters["target_percent"] = allocation / 100.0
    try:
        strategy = create_strategy(definition.key, parameters)
    except ValueError:
        st.error("策略參數無效，請依欄位範圍修正後再執行。")
        return None, parameters, allocation / 100.0
    return strategy, parameters, allocation / 100.0


def _render_cost_controls(st: Any, market: str) -> dict[str, Any]:
    preset = resolve_cost_preset(market)
    assumptions = cost_assumptions(preset)
    st.caption(f"成本設定：{assumptions.label}；{assumptions.limitation}")
    initial_cash = float(
        st.number_input(
            "初始資金",
            min_value=1000.0,
            value=1_000_000.0,
            step=10_000.0,
            key="strategy_workspace_initial_cash",
        )
    )
    max_position = (
        float(
            st.slider(
                "單一持股上限 (%)", 5.0, 95.0, 50.0, 5.0, key="strategy_workspace_position_limit"
            )
        )
        / 100.0
    )
    confirmed = True
    if market not in {"TWSE", "TPEX", "US"}:
        confirmed = bool(
            st.checkbox("我確認要使用自訂市場成本", key="strategy_workspace_market_confirmed")
        )
    return {
        "initial_cash": initial_cash,
        "max_position_pct": max_position,
        "commission_rate": float(
            st.number_input(
                "手續費率 (%)",
                min_value=0.0,
                value=assumptions.commission_rate * 100,
                step=0.01,
                key="strategy_workspace_commission",
            )
        )
        / 100.0,
        "tax_rate": float(
            st.number_input(
                "交易稅率 (%)",
                min_value=0.0,
                value=assumptions.tax_rate * 100,
                step=0.01,
                key="strategy_workspace_tax",
            )
        )
        / 100.0,
        "slippage_rate": float(
            st.number_input(
                "滑價率 (%)",
                min_value=0.0,
                value=assumptions.slippage_rate * 100,
                step=0.01,
                key="strategy_workspace_slippage",
            )
        )
        / 100.0,
        "cost_preset": preset,
        "trailing_stop_pct": (
            float(
                st.slider(
                    "移動停利 (%)",
                    min_value=1.0,
                    max_value=50.0,
                    value=10.0,
                    step=1.0,
                    key="strategy_workspace_trailing_stop",
                )
            )
            / 100.0
            if st.checkbox("啟用移動停利", key="strategy_workspace_enable_trailing")
            else None
        ),
        "market_costs_confirmed": confirmed,
    }


def _render_data_state(st: Any, data: StrategyDataSnapshot) -> None:
    st.caption(
        f"標的：{data.symbol or '資料不足'}；市場：{data.market}；來源：{data.source or '資料不足'}；"
        f"期間：{data.start or '資料不足'} 至 {data.end or '資料不足'}；資料筆數：{data.rows}；狀態：{data.status}"
    )
    if data.missing_fields:
        st.warning("資料不足：缺少 " + ", ".join(data.missing_fields))


def _render_preflight(
    st: Any, validation: Any, health_plan: Any, data: StrategyDataSnapshot
) -> None:
    st.subheader("執行前檢查")
    if data.status in {"missing", "partial"}:
        st.error("目前資料不足，不能執行策略。請回研究首頁補齊資料。")
    elif validation.can_execute:
        st.success("目前設定可執行標準回測。")
    else:
        st.error("目前設定不可執行，請依下列阻擋原因修正。")
    for item in validation.errors:
        st.error(item)
    for item in validation.warnings:
        st.warning(item)
    if getattr(health_plan, "can_run", False):
        st.info(
            f"樣本內：{health_plan.train_period.start} 至 {health_plan.train_period.end}；"
            f"樣本外：{health_plan.test_period.start} 至 {health_plan.test_period.end}；"
            f"Walk-forward 最多 {health_plan.walk_forward.max_folds} folds；"
            f"敏感度最多 {health_plan.expected_sensitivity_combinations} 組。"
        )
    else:
        st.warning("資料不足，無法形成獨立樣本外期間；健檢會被阻擋。")


def _render_run(
    st: Any,
    run: Any,
    current: StrategyRunManifest | None,
    service: StrategyWorkspaceApplicationService,
) -> None:
    if run.status == "blocked":
        st.warning("標準回測未執行；請先修正資料或設定。")
        return
    if run.status == "error":
        st.error(run.health_message or "策略執行失敗。")
        return
    is_current = current is not None and service.result_is_current(current, run.manifest)
    if not is_current:
        st.warning("設定已變更，結果可能過期；請重新執行。")
    st.subheader("標準回測結果")
    if run.result is not None:
        metrics = run.result.metrics
        st.write(
            f"總報酬：{metrics.total_return:.2%}；最大回撤：{metrics.max_drawdown:.2%}；"
            f"交易次數：{metrics.number_of_trades}；資料期間：{run.manifest.core['data']['start']} 至 {run.manifest.core['data']['end']}"
        )
    st.caption(f"健檢狀態：{run.health_status}；manifest digest：{run.manifest.digest}")
    health = getattr(run, "health", None)
    if health is not None:
        oos_status = health.out_of_sample.status if health.out_of_sample is not None else "blocked"
        fold_count = len(health.walk_forward.folds) if health.walk_forward is not None else 0
        sensitivity_count = len(health.sensitivity.runs) if health.sensitivity is not None else 0
        st.info(
            f"樣本外：{oos_status}；Walk-forward folds：{fold_count}；"
            f"敏感度組合：{sensitivity_count}；完整健檢狀態：{health.status}。"
        )
        for warning in (
            *getattr(health.out_of_sample, "warnings", ()),
            *getattr(health.walk_forward, "warnings", ()),
            *getattr(health.sensitivity, "warnings", ()),
        ):
            st.warning(getattr(warning, "message", str(warning)))
        _render_health_details(st, health)
    st.download_button(
        "下載可重現 manifest",
        data=run.manifest.to_json(),
        file_name="strategy-run-manifest.json",
        mime="application/json",
        key="strategy_workspace_manifest_download",
    )


def _render_health_details(st: Any, health: StrategyHealthRun) -> None:
    """Render every validation result, never only aggregate counts."""

    if health.out_of_sample is not None and health.out_of_sample.in_sample is not None:
        train = health.out_of_sample.in_sample.metrics
        test = (
            health.out_of_sample.out_of_sample.metrics
            if health.out_of_sample.out_of_sample
            else None
        )
        st.write(
            "樣本內／樣本外："
            f"樣本內報酬 {train.total_return:.2%}、回撤 {train.max_drawdown:.2%}、交易 {train.number_of_trades}；"
            f"樣本外報酬 {test.total_return:.2%}、回撤 {test.max_drawdown:.2%}、交易 {test.number_of_trades}。"
            if test is not None
            else "樣本外結果不可用。"
        )
    if health.walk_forward is not None:
        st.markdown("**Walk-forward 各 fold**")
        for fold in health.walk_forward.folds:
            metrics = fold.test_run.metrics
            st.write(
                f"Fold {fold.fold_number}：{fold.test_period.start} 至 {fold.test_period.end}；"
                f"狀態 ready；報酬 {metrics.total_return:.2%}；回撤 {metrics.max_drawdown:.2%}；"
                f"交易 {metrics.number_of_trades}。"
            )
    if health.sensitivity is not None:
        st.markdown("**參數敏感度各組合**")
        for item in health.sensitivity.runs:
            metrics = item.run.metrics
            st.write(
                f"參數 {dict(item.parameters)}；報酬 {metrics.total_return:.2%}；"
                f"回撤 {metrics.max_drawdown:.2%}；交易 {metrics.number_of_trades}。"
            )


def _with_health(
    standard: Any, health: StrategyHealthRun, service: Any, values: Any, data: Any, strategy: Any
) -> Any:
    manifest = service.build_manifest(
        values=values,
        data=data,
        strategy=strategy,
        status="complete" if health.status == "complete" else "partial",
        health_status=health.status,
    )
    return type(standard)(
        status=standard.status,
        result=standard.result,
        manifest=manifest,
        validation=standard.validation,
        health_status=health.status,
        health_message=health.message,
        health=health,
    )


def _optional_frame(value: object) -> pd.DataFrame | None:
    return value.copy(deep=True) if isinstance(value, pd.DataFrame) else None
