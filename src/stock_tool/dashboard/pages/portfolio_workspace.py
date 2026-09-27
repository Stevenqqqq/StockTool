"""Native Streamlit Holdings and Risk workspace renderer."""

from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import replace
from typing import Any, Callable

import pandas as pd

from stock_tool.application.portfolio_workspace import (
    PortfolioWorkspaceAnalysis,
    PortfolioWorkspaceApplicationService,
    PortfolioWorkspaceStressResult,
)
from stock_tool.portfolio_stress import StressScenario, StressScenarioType
from stock_tool.portfolio_valuation import Currency, FxQuote
from stock_tool.application.holding_analysis import holding_fx_is_usable, validated_holding_prices


from stock_tool.dashboard.presentation_mapper import (
    format_iso_datetime,
    format_source_state_label,
    format_status_label,
)


def _safe_expander(st: Any, label: str, expanded: bool = False) -> Any:
    expander = getattr(st, "expander", None)
    if callable(expander):
        try:
            return expander(label, expanded=expanded)
        except TypeError:
            return expander(label)
    return _null_context()


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def render_portfolio_workspace(
    st: Any,
    *,
    service: PortfolioWorkspaceApplicationService,
    refresh_callback: Callable[[], object] | None = None,
    classification_callback: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    on_research: Callable[[str, str], None] | None = None,
) -> None:
    """Refresh once per holding set/day, then project the same analysis to UI and AI."""

    from stock_tool.application.holding_identity import load_identity_state
    from stock_tool.runtime_paths import RuntimePaths

    if not st.session_state.get("holding_identity_loaded"):
        metadata = load_identity_state(
            RuntimePaths.from_environment().data_dir / "holding_identity.json"
        )
        st.session_state.setdefault("holding_profiles", metadata.get("profiles", {}))
        st.session_state.setdefault("holding_type_overrides", metadata.get("overrides", {}))
        st.session_state["holding_identity_loaded"] = True

    st.caption("管理市場限定的持股、估值與風險證據。這不是交易建議，不會自動下單。")
    snapshot = st.session_state.get("portfolio_workspace_snapshot")
    if snapshot is None:
        snapshot = service.load_snapshot()
        st.session_state.portfolio_workspace_snapshot = snapshot
    st.session_state.setdefault(
        "portfolio_workspace_stress_type", StressScenarioType.ALL_HOLDINGS_DECLINE.value
    )
    st.session_state.setdefault("portfolio_workspace_stress_shock", 0.1)
    st.session_state.setdefault("portfolio_workspace_stress_market", "TWSE")

    positions = st.session_state.get("portfolio_workspace_positions")
    if not isinstance(positions, pd.DataFrame):
        positions = snapshot.positions.copy(deep=True)

    # Consume navigation before the single selection widget is constructed.
    focus_identity = _consume_portfolio_focus(st, positions)

    refresh_key = (
        positions[["symbol", "market"]].to_json() if not positions.empty else "empty",
        datetime.now(UTC).date().isoformat(),
    )
    if (
        refresh_callback is not None
        and not positions.empty
        and st.session_state.get("holding_refresh_key") != refresh_key
    ):
        # Record the attempt before I/O so failed sources cannot create a rerun loop.
        st.session_state["holding_refresh_key"] = refresh_key
        st.session_state["holding_force_refresh"] = False
        _refresh_and_analyze(st, service, positions, refresh_callback, classification_callback)
    elif (
        refresh_callback is not None
        and not positions.empty
        and st.session_state.get("portfolio_workspace_analysis") is None
    ):
        # Editing quantity/cost needs recalculation, not another market-data request.
        _refresh_and_analyze(st, service, positions, None, classification_callback)

    # 1. 持倉概況
    _render_first_screen(st, snapshot, st.session_state.get("portfolio_workspace_analysis"))
    if st.session_state.get("holding_refresh_failed"):
        st.error("資料更新失敗；保留前次可用資料，請查看每筆資料日期。")

    # 2. 分析持倉
    if refresh_callback is not None and st.button(
        "更新並分析持股", key="portfolio_workspace_refresh"
    ):
        st.session_state["holding_force_refresh"] = True
        _refresh_and_analyze(st, service, positions, refresh_callback, classification_callback)
        _rerun(st)
    with _safe_expander(st, "進階設定與手動資料備援", expanded=False):
        _render_analysis_controls(st, service, positions, classification_callback)
    analysis = st.session_state.get("portfolio_workspace_analysis")
    if isinstance(analysis, PortfolioWorkspaceAnalysis):
        _render_analysis(st, service, analysis, positions)
    if not positions.empty:
        from stock_tool.dashboard.components.holding_analysis import render_holding_analysis

        render_holding_analysis(st, positions, analysis)

    # 3. 持股管理
    _render_position_editor(st, service, positions)
    positions = st.session_state.get("portfolio_workspace_positions", positions)
    if not isinstance(positions, pd.DataFrame):
        positions = service.load_positions()
    _render_position_table(st, positions, on_research=on_research, focus_identity=focus_identity)


def _refresh_and_analyze(
    st: Any,
    service: PortfolioWorkspaceApplicationService,
    positions: pd.DataFrame,
    refresh_callback: Callable[[], object] | None,
    classification_callback: Callable[[pd.DataFrame], pd.DataFrame] | None,
) -> None:
    try:
        if refresh_callback is not None:
            st.session_state.portfolio_workspace_refresh_result = refresh_callback()
            st.session_state["holding_refresh_failed"] = False
    except Exception:
        st.session_state["holding_refresh_failed"] = True
        st.error("資料更新失敗；保留前次可用資料，請查看每筆資料日期。")
    if positions.empty:
        return
    try:
        classifications = classification_callback(positions) if classification_callback else None
    except Exception:
        classifications = None
    if classifications is not None:
        st.session_state["portfolio_classifications"] = classifications
    profile_rows = []
    profiles = st.session_state.get("holding_profiles", {})
    overrides = st.session_state.get("holding_type_overrides", {})
    for row in positions.itertuples(index=False):
        identity = f"{row.symbol}|{row.market}"
        profile = profiles.get(identity, {})
        kind = overrides.get(identity, profile.get("instrument_type"))
        if kind == "股票" and profile.get("source"):
            profile_rows.append(
                {
                    "symbol": row.symbol,
                    "market": row.market,
                    "sector": profile.get("sector", ""),
                    "industry": profile.get("industry", ""),
                    "source": profile["source"],
                }
            )
    if profiles:
        classifications = pd.DataFrame(
            profile_rows, columns=["symbol", "market", "sector", "industry", "source"]
        )
        st.session_state["portfolio_classifications"] = classifications
    st.session_state.portfolio_workspace_analysis = service.analyze(
        positions=positions,
        prices=validated_holding_prices(
            positions,
            st.session_state.get("price_data"),
            st.session_state.get("holding_profiles", {}),
        ),
        base_currency=st.session_state.get("portfolio_workspace_base_currency", "TWD"),
        fx_quote=_resolved_fx_quote(st),
        classifications=classifications,
        fx_applied_at=st.session_state.get("portfolio_workspace_manual_fx_applied_at"),
    )


def _render_first_screen(st: Any, snapshot: Any, analysis: object) -> None:
    if snapshot.positions.empty:
        st.info("先加入一筆持股；股價與必要匯率會自動更新，股數以「股」為單位。")
        return
    result = analysis if isinstance(analysis, PortfolioWorkspaceAnalysis) else None
    valuation = result.valuation if result is not None else None
    risk = result.risk if result is not None else None
    market_value = valuation.base_market_value if valuation is not None else None
    pnl = valuation.base_unrealized_pnl if valuation is not None else None
    largest = risk.position_concentration if risk is not None else None
    st.subheader("持倉概況")
    columns = st.columns(2) + st.columns(2)
    columns[0].metric("持股筆數", str(len(snapshot.positions)))
    columns[1].metric("基準幣別總市值", _money(market_value, result))
    columns[2].metric("原幣損益換算", _money(pnl, result))
    largest_label = "最大單一持股"
    if valuation is not None and not valuation.positions.empty:
        ranked = valuation.positions.dropna(subset=["weight"]).sort_values(
            "weight", ascending=False
        )
        if not ranked.empty:
            largest_label = f"最大持股：{ranked.iloc[0]['symbol']}"
    columns[3].metric(largest_label, _percent(largest))
    if result is None:
        st.info("尚未分析持股；請點擊下方「分析持倉」以計算最新估值與風險。")
        return
    st.caption("此處呈現持股估值；財報、事件與基金成分的完整程度請看單筆分析。")
    with _safe_expander(st, "詳細技術診斷與可重現資料", expanded=False):
        st.caption(f"診斷 manifest digest：{result.manifest.digest}")
    if market_value is None:
        st.warning("部分價格或換算匯率尚不可用，因此不顯示完整組合總額；可用的原幣估值仍保留。")


def _render_position_editor(
    st: Any, service: PortfolioWorkspaceApplicationService, positions: pd.DataFrame
) -> None:
    st.subheader("持股管理")
    with st.expander("新增／更新持股", expanded=positions.empty):
        if not positions.empty:
            editing = st.selectbox(
                "載入既有持股",
                [f"{row.symbol} / {row.market}" for row in positions.itertuples(index=False)],
                key="holding_edit_identity",
            )
            if st.button("填入既有股數、成本與備註", key="holding_load_editor"):
                edit_symbol, edit_market = editing.split(" / ", 1)
                row = positions.loc[
                    (positions.symbol == edit_symbol) & (positions.market == edit_market)
                ].iloc[0]
                for key, value in (
                    ("symbol", edit_symbol),
                    ("market", edit_market),
                    ("currency", row.currency),
                    ("quantity", float(row.quantity)),
                    ("average_cost", float(row.average_cost)),
                    ("note", str(row.note)),
                ):
                    st.session_state[f"portfolio_workspace_{key}"] = value
        with st.form("holding_position_form"):
            columns = st.columns(3) + st.columns(3)
            symbol = columns[0].text_input("股票代號", value="", key="portfolio_workspace_symbol")
            market = columns[1].selectbox(
                "市場",
                ["自動辨識", "TWSE", "TPEX", "US", "CUSTOM"],
                key="portfolio_workspace_market",
            )
            currency = columns[2].selectbox(
                "幣別", ["自動", "TWD", "USD"], key="portfolio_workspace_currency"
            )
            quantity = columns[3].number_input(
                "數量（股，可輸入零股）",
                min_value=0.0001,
                value=1.0,
                step=0.0001,
                key="portfolio_workspace_quantity",
            )
            average_cost = columns[4].number_input(
                "平均成本（原幣／股）",
                min_value=0.0,
                value=100.0,
                step=0.01,
                key="portfolio_workspace_average_cost",
            )
            note = columns[5].text_input("備註", value="", key="portfolio_workspace_note")
            raw_symbol = (
                str(symbol).strip()
                or str(st.session_state.get("portfolio_workspace_symbol") or "").strip()
            )
            if st.form_submit_button(
                "加入／更新持股", type="primary", key="portfolio_workspace_upsert"
            ):
                if not raw_symbol:
                    st.warning("請輸入股票代號。")
                else:
                    try:
                        if market == "自動辨識":
                            from stock_tool.application.holding_identity import (
                                resolve_holding_identity,
                            )

                            identity = resolve_holding_identity(raw_symbol)
                            raw_symbol = str(identity["symbol"])
                            market = str(identity["market"])
                            st.session_state.setdefault("holding_profiles", {})[
                                f"{raw_symbol}|{market}"
                            ] = identity
                            if currency == "自動":
                                currency = str(identity["currency"])
                        updated = service.add_or_update_position(
                            positions,
                            symbol=raw_symbol,
                            market=market,
                            currency=None if currency == "自動" else currency,
                            quantity=float(quantity),
                            average_cost=float(average_cost),
                            note=note,
                        )
                    except (OSError, ValueError) as exc:
                        st.error(f"持股儲存失敗：{exc}")
                    else:
                        st.session_state.portfolio_workspace_positions = updated
                        st.session_state.portfolio_workspace_snapshot = service.load_snapshot()
                        _invalidate_analysis(st)
                        st.success(f"已儲存 {raw_symbol.upper()} / {market}。")
                        _rerun(st)

    if not positions.empty:
        st.markdown("#### 移除指定持股")
        identities = [
            f"{row.symbol} / {row.market}"
            for row in positions[["symbol", "market"]].itertuples(index=False)
        ]
        selected = st.selectbox(
            "移除指定市場持股",
            identities,
            key="portfolio_workspace_remove_identity",
        )
        confirmed = st.checkbox(
            f"我確認要從持倉中移除 {selected}（此操作無法復原）",
            value=False,
            key="portfolio_workspace_remove_confirmed",
        )
        if st.button("移除持股", key="portfolio_workspace_remove"):
            if not confirmed:
                st.warning("請先勾選確認方塊，以確認移除此持股。")
            else:
                symbol_value, market_value = selected.split(" / ", maxsplit=1)
                try:
                    updated = service.remove_position(
                        positions, symbol=symbol_value, market=market_value
                    )
                except (OSError, ValueError) as exc:
                    st.error(f"持股移除失敗：{exc}")
                else:
                    st.session_state.portfolio_workspace_positions = updated
                    st.session_state.portfolio_workspace_snapshot = service.load_snapshot()
                    _invalidate_analysis(st)
                    st.success(f"已移除 {symbol_value} / {market_value}。")
                    _rerun(st)

    if st.button("重新載入持股", key="portfolio_workspace_reload"):
        st.session_state.portfolio_workspace_positions = service.load_positions()
        st.session_state.portfolio_workspace_snapshot = service.load_snapshot()
        _invalidate_analysis(st)
        st.success("已重新載入持股。")
        _rerun(st)


def _render_position_table(
    st: Any,
    positions: pd.DataFrame,
    *,
    on_research: Callable[[str, str], None] | None = None,
    focus_identity: str | None = None,
) -> None:
    if positions.empty:
        st.info("目前沒有持股。請使用上方表格新增持股。")
        return
    st.subheader("現有持股清單")
    display_df = positions[["symbol", "market", "currency", "quantity", "average_cost"]].copy()
    display_df.columns = ["股票代號", "市場", "幣別", "持股數量", "平均成本"]
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
    )
    if on_research is not None:
        identities = [
            f"{row.symbol} / {row.market}"
            for row in positions[["symbol", "market"]].itertuples(index=False)
        ]
        selected = st.session_state.get("portfolio_workspace_research_identity", identities[0])
        if selected not in identities:
            selected = identities[0]
        st.caption(f"目前研究持股：{selected}（與上方分析共用選擇）")
        if st.button("深入研究這筆持股", key="portfolio_workspace_return_research"):
            symbol, market = selected.split(" / ", maxsplit=1)
            on_research(symbol, market)


def _consume_portfolio_focus(st: Any, positions: pd.DataFrame) -> str | None:
    """Consume one Research-to-Holdings focus and make its effect visible."""
    raw = st.session_state.pop("portfolio_workspace_focus", None)
    if not isinstance(raw, dict):
        return None
    symbol = str(raw.get("symbol") or "").strip().upper()
    market = str(raw.get("market") or "").strip().upper()
    if not symbol or market not in {"TWSE", "TPEX", "US", "CUSTOM"}:
        st.info("持倉聚焦內容無效；未修改持股。請重新從研究頁選擇標的。")
        return None
    if not {"symbol", "market"}.issubset(positions.columns):
        st.info(f"目前不在持倉：{symbol} / {market}。請在持股管理區明確新增。")
        return None
    match = positions[
        positions["symbol"].astype(str).str.strip().str.upper().eq(symbol)
        & positions["market"].astype(str).str.strip().str.upper().eq(market)
    ]
    identity = f"{symbol} / {market}"
    if match.empty:
        st.info(f"目前不在持倉：{identity}。請在持股管理區明確新增；系統未自動新增。")
        return None
    st.session_state["portfolio_workspace_research_identity"] = identity
    st.success(f"已聚焦持股：{identity}。未新增或修改持股。")
    return identity


def _render_analysis_controls(
    st: Any,
    service: PortfolioWorkspaceApplicationService,
    positions: pd.DataFrame,
    classification_callback: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> None:
    st.subheader("分析設定")
    st.selectbox("基準幣別", ["TWD", "USD"], key="portfolio_workspace_base_currency")
    manual_rate = st.number_input(
        "手動 USD/TWD 匯率（可選）",
        min_value=0.0,
        value=float(st.session_state.get("portfolio_workspace_manual_fx") or 0.0),
        step=0.01,
        key="portfolio_workspace_manual_fx_input",
    )
    if st.button("套用手動匯率", key="portfolio_workspace_apply_fx"):
        if manual_rate <= 0:
            st.error("匯率必須是大於零的數字。")
        else:
            st.session_state.portfolio_workspace_manual_fx = float(manual_rate)
            st.session_state.portfolio_workspace_manual_fx_applied_at = datetime.now(
                UTC
            ).isoformat()
            st.session_state.pop("portfolio_fx_resolution", None)
            _invalidate_analysis(st)
            st.caption("手動匯率已套用；分析時會記錄實際 UTC applied_at。")
            st.success("已套用手動 USD/TWD 匯率；請重新分析。")
    st.caption("持股首次開啟與新增標的會自動更新；手動匯率僅作資料來源失敗時的備援。")
    if st.button("分析持倉", type="primary", key="portfolio_workspace_analyze"):
        quote = _resolved_fx_quote(st)
        manual_value = st.session_state.get("portfolio_workspace_manual_fx")
        if manual_value and quote is None:
            st.error("匯率無效或已過期，無法執行跨幣別分析。")
            return
        _refresh_and_analyze(st, service, positions, None, classification_callback)
        _rerun(st)


def _render_analysis(
    st: Any,
    service: PortfolioWorkspaceApplicationService,
    analysis: PortfolioWorkspaceAnalysis,
    positions: pd.DataFrame,
) -> None:
    prices = validated_holding_prices(
        positions, st.session_state.get("price_data"), st.session_state.get("holding_profiles", {})
    )
    quote = _resolved_fx_quote(st)
    if quote is not None:
        st.caption(
            f"匯率來源：{format_source_state_label(quote.source)}｜"
            f"生效時間：{format_iso_datetime(quote.effective_at)}｜"
            f"狀態：{'過期' if quote.stale else '正常'}"
        )
    base_currency = st.session_state.get(
        "portfolio_workspace_base_currency",
        analysis.manifest.core["base_currency"],
    )
    if not service.result_is_current(
        analysis,
        positions=positions,
        prices=prices,
        base_currency=str(base_currency),
        fx_quote=quote,
        fx_applied_at=st.session_state.get("portfolio_workspace_manual_fx_applied_at"),
    ):
        st.session_state.pop("portfolio_workspace_stress_result", None)
        st.warning("設定或資料已變更，保存的分析結果可能過期；請重新分析。")
    st.subheader("持股市值與集中度")
    if not analysis.valuation.positions.empty:
        val_df = analysis.valuation.positions.copy(deep=True)
        rename_map = {
            "symbol": "股票代號",
            "market": "市場",
            "currency": "幣別",
            "quantity": "持股數量",
            "average_cost": "平均成本",
            "close": "最新收盤",
            "market_value": "目前市值",
            "unrealized_pnl": "未實現損益",
            "unrealized_pnl_pct": "未實現報酬率",
            "weight": "持股權重",
            "status": "資料狀態",
            "native_currency": "報價幣別",
            "latest_price": "收盤價",
            "native_market_value": "原幣市值",
            "native_unrealized_pnl": "原幣未實現損益",
            "base_market_value": "換算參考市值",
        }
        visible = [
            "symbol",
            "market",
            "quantity",
            "native_currency",
            "latest_price",
            "native_market_value",
            "native_unrealized_pnl",
            "base_market_value",
            "weight",
        ]
        val_df = val_df[[column for column in visible if column in val_df.columns]]
        val_df = val_df.rename(columns={k: v for k, v in rename_map.items() if k in val_df.columns})
        if "資料狀態" in val_df.columns:
            val_df["資料狀態"] = val_df["資料狀態"].map(lambda s: format_status_label(s))
        st.dataframe(val_df, width="stretch", hide_index=True)
    st.caption(
        "換算市值採用目前匯率；原幣損益未計入歷史換匯損益。各筆資料可能來自不同交易日期，詳見單筆分析。"
    )
    with _safe_expander(st, "進階曝險、假設情境與診斷", expanded=False):
        _render_risk_details(st, service, analysis)


def _render_risk_details(
    st: Any,
    service: PortfolioWorkspaceApplicationService,
    analysis: PortfolioWorkspaceAnalysis,
) -> None:
    exp_labels = {
        "market": "市場曝險",
        "currency": "幣別曝險",
        "sector": "板塊曝險",
        "industry": "產業曝險",
    }
    for exposure in (
        analysis.risk.market_exposure,
        analysis.risk.currency_exposure,
        analysis.risk.sector_exposure,
        analysis.risk.industry_exposure,
    ):
        dim_label = exp_labels.get(str(exposure.dimension).lower(), str(exposure.dimension))
        values = ", ".join(f"{item.identity} {_percent(item.weight)}" for item in exposure.items)
        st.write(f"{dim_label}：{values or '資料不足'}")
    if analysis.ledger_snapshot is None:
        st.info("帳本（Ledger）尚未建立；已實現損益需等交易紀錄建立後計算。")
    else:
        st.write(f"帳本已實現損益：{_money(analysis.risk.realized_pnl, analysis)}")
    gaps = [item.to_dict() for item in analysis.risk.missing_data]
    if gaps:
        st.subheader("資料缺口與修復方式")
        gap_df = pd.DataFrame(gaps)
        gap_rename = {
            "field": "缺少欄位",
            "state": "狀態",
            "reason": "原因與修復建議",
        }
        gap_df = gap_df.rename(columns={k: v for k, v in gap_rename.items() if k in gap_df.columns})
        if "狀態" in gap_df.columns:
            gap_df["狀態"] = gap_df["狀態"].map(lambda s: format_status_label(s))
        st.dataframe(gap_df, width="stretch", hide_index=True)
    _render_stress(st, service, analysis)
    with _safe_expander(st, "詳細資料與可重現 Manifest", expanded=False):
        st.download_button(
            "下載分析 manifest",
            data=analysis.manifest.to_json(),
            file_name="portfolio-workspace-manifest.json",
            mime="application/json",
            key="portfolio_workspace_manifest_download",
        )


def _render_stress(
    st: Any, service: PortfolioWorkspaceApplicationService, analysis: PortfolioWorkspaceAnalysis
) -> None:
    st.subheader("壓力測試（假設情境）")
    scenario_type = st.selectbox(
        "壓力測試情境",
        [item.value for item in StressScenarioType],
        key="portfolio_workspace_stress_type",
    )
    shock = st.slider(
        "衝擊幅度",
        -0.8 if scenario_type == StressScenarioType.USD_TWD_MOVE.value else 0.0,
        0.8,
        0.1,
        0.01,
        key="portfolio_workspace_stress_shock",
    )
    market = None
    if scenario_type == StressScenarioType.MARKET_DECLINE.value:
        market = st.selectbox(
            "壓力測試市場", ["TWSE", "TPEX", "US"], key="portfolio_workspace_stress_market"
        )
    if st.button("執行壓力測試", key="portfolio_workspace_run_stress"):
        scenario = StressScenario(
            name="native-workspace-scenario",
            scenario_type=StressScenarioType(scenario_type),
            shock_pct=float(shock),
            market=market,
        )
        st.session_state.pop("portfolio_workspace_stress_result", None)
        result = service.run_stress(analysis, scenario)
        st.session_state.portfolio_workspace_stress_result = result
    result = st.session_state.get("portfolio_workspace_stress_result")
    if isinstance(result, PortfolioWorkspaceStressResult) and service.stress_result_is_current(
        result,
        analysis,
        StressScenario(
            name="native-workspace-scenario",
            scenario_type=StressScenarioType(scenario_type),
            shock_pct=float(shock),
            market=market,
        ),
    ):
        st.write(f"假設後基準幣別總額：{_money(result.base_value_after, analysis)}")
        st.write(f"假設影響：{_money(result.base_impact, analysis)}")
        st.caption("這是明確的假設情境，不是預測、VaR 或買賣建議。")
        for assumption in result.assumptions:
            st.write(assumption)
    elif result is not None:
        st.warning("壓力測試結果已過期，請重新執行。")
        st.session_state.pop("portfolio_workspace_stress_result", None)


def _manual_quote(value: object, applied_at: str | None = None) -> FxQuote | None:
    try:
        if value is None:
            rate = 0.0
        elif isinstance(value, (int, float)):
            rate = float(value)
        else:
            rate = float(str(value))
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    timestamp = applied_at or datetime.now(UTC).isoformat()
    quote = FxQuote.manual(Currency.USD, Currency.TWD, rate, timestamp)
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds()
    except ValueError:
        return replace(quote, stale=True)
    return replace(quote, stale=age > 86_400)


def _resolved_fx_quote(st: Any) -> FxQuote | None:
    resolution = st.session_state.get("portfolio_fx_resolution")
    quote = getattr(resolution, "quote", None)
    if isinstance(quote, FxQuote):
        return quote if holding_fx_is_usable(quote) else None
    manual = _manual_quote(
        st.session_state.get("portfolio_workspace_manual_fx"),
        st.session_state.get("portfolio_workspace_manual_fx_applied_at"),
    )
    return manual if holding_fx_is_usable(manual) else None


def _invalidate_analysis(st: Any) -> None:
    st.session_state.pop("portfolio_workspace_analysis", None)
    st.session_state.pop("portfolio_workspace_stress_result", None)


def _frame_or_none(value: object) -> pd.DataFrame | None:
    return value.copy(deep=True) if isinstance(value, pd.DataFrame) else None


def _money(value: float | None, analysis: PortfolioWorkspaceAnalysis | None) -> str:
    if value is None:
        return "資料不足"
    currency = "TWD"
    if analysis is not None:
        currency = str(analysis.manifest.core.get("base_currency") or currency)
    return f"{currency} {float(value):,.2f}"


def _health_percent(value: float | None) -> str:
    """Format health scores whose domain is 0–100, not a 0–1 ratio."""

    return "無資料" if value is None else f"{float(value):.2f}%"


def _percent(value: float | None) -> str:
    return "資料不足" if value is None else f"{float(value):.2%}"


def _rerun(st: Any) -> None:
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()
