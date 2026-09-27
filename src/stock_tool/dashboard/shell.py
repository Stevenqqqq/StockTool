"""Dashboard Shell orchestration separated from legacy Dashboard page implementations."""

from __future__ import annotations

import logging
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from stock_tool import __version__
from stock_tool.dashboard.components.layout import (
    render_dashboard_shell as render_primary_navigation,
)
from stock_tool.dashboard.components.layout import render_page_header
from stock_tool.dashboard.components.status import render_dashboard_status
from stock_tool.dashboard.home_data import load_home_summary
from stock_tool.dashboard.navigation import LEGACY_PAGE_OPTIONS, NavigationItem, navigation_for_key
from stock_tool.application.daily_brief import DailyBrief, DailyRefreshResult, ResearchContinuation
from stock_tool.application.daily_research_loop import DailyResearchLoopResult
from stock_tool.application.daily_research_brief import DailyResearchBrief
from stock_tool.research.assistant import DailyResearchAssistantBrief
from stock_tool.research.library import ResearchLibrary
from stock_tool.runtime_paths import RuntimePaths, default_runtime_paths
from stock_tool.dashboard.pages.home import HomeAction, HomeContext, render_home
from stock_tool.dashboard.pages.library import render_library_workspace
from stock_tool.dashboard.pages.research import render_research_workspace
from stock_tool.dashboard.pages.discovery import render_explore_workspace
from stock_tool.dashboard.pages.strategy_workspace import render_strategy_workspace
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
from stock_tool.dashboard.pages.settings_workspace import render_settings_workspace
from stock_tool.application.strategy_workspace import StrategyWorkspaceApplicationService
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.application.settings_workspace import (
    SettingsWorkspaceApplicationService,
    SettingsWorkspaceSnapshot,
)
from stock_tool.application.daily_research_scheduler import DailyScheduleApplicationService
from stock_tool.application.daily_research_runner import (
    DailyResearchRunManifest,
    DailyResearchRunOutcome,
)
from stock_tool.application.daily_research_inbox import (
    DailyResearchInboxService,
    DailyResearchNotificationService,
    ResearchInboxEntry,
)
from stock_tool.application.daily_research_changes import (
    DailyResearchChangeSet,
    DailyResearchChangeStore,
)
from stock_tool.application.macro_snapshot import MacroSignal, MacroSnapshot
from stock_tool.application.prediction_lab import PredictionLabSummary
from stock_tool.application.explore import ExploreApplicationService
from stock_tool.application.market_monitor import (
    MarketMonitorApplicationService,
    load_local_classifications,
)
from stock_tool.application.research_context import (
    ResearchContext,
    ResearchHandoffAction,
    ResearchWorkspace,
)
from stock_tool.dashboard.state import (
    DashboardStatus,
    SearchRequest,
    SearchPreparation,
    apply_pending_workspace_navigation,
    begin_search,
    dashboard_status,
    consume_research_handoff,
    enqueue_research_handoff,
    finish_search,
    navigate_to_workspace,
    should_execute_pending_search,
)
from stock_tool.dashboard.workspace_overview import render_workspace_overview
from stock_tool.domain.models import Market, Symbol


class PortfolioRefreshCallback(Protocol):
    """Keyword-only contract for the explicit native portfolio refresh action."""

    def __call__(self, st: Any, portfolio: Any, *, force_refresh: bool) -> object: ...


@dataclass(frozen=True, slots=True)
class DashboardShellDependencies:
    """Callbacks and paths supplied by the legacy Dashboard bootstrap."""

    ensure_symbol_data: Callable[..., Mapping[str, Any]]
    render_legacy_page: Callable[[Any, str], None]
    portfolio_path: Path
    watchlist_path: Path
    risk_notice: str
    app_title: str
    logger: logging.Logger
    build_research_snapshot: Callable[..., Any] | None = None
    build_daily_brief: Callable[[Any], DailyBrief] | None = None
    build_daily_research_loop: Callable[[Any], DailyResearchLoopResult] | None = None
    refresh_daily_data: Callable[[Any], DailyRefreshResult] | None = None
    run_daily_research: Callable[[], DailyResearchRunOutcome] | None = None
    build_daily_research_run: Callable[[], DailyResearchRunManifest | None] | None = None
    generate_daily_ai_research: Callable[[Any, bool], DailyResearchAssistantBrief] | None = None
    build_daily_evidence_brief: Callable[[Any], DailyResearchBrief | None] | None = None
    generate_daily_evidence_brief: Callable[[Any, bool], DailyResearchBrief] | None = None
    concept_path: Path | None = None
    refresh_portfolio_data: PortfolioRefreshCallback | None = None
    build_portfolio_classifications: Callable[[Any, Any], Any] | None = None
    refresh_settings_workspace: Callable[[], SettingsWorkspaceSnapshot] | None = None
    daily_schedule_service: DailyScheduleApplicationService | None = None
    daily_research_inbox_service: DailyResearchInboxService | None = None
    daily_notification_service: DailyResearchNotificationService | None = None
    build_macro_snapshot: (
        Callable[[Any], tuple[MacroSnapshot | None, tuple[MacroSignal, ...]]] | None
    ) = None
    build_macro_links: Callable[[Any, MacroSnapshot], tuple[dict[str, object], ...]] | None = None
    build_macro_revisions: Callable[[Any], tuple[dict[str, object], ...]] | None = None
    refresh_macro_snapshot: Callable[[Any], MacroSnapshot] | None = None
    build_prediction_lab_summary: Callable[[Any], PredictionLabSummary] | None = None
    evaluate_prediction_outcomes: Callable[[], object] | None = None


def synchronize_existing_session_status(st: Any) -> None:
    """Reflect existing session prices without relabeling failed research as current."""

    if dashboard_status(st.session_state) is not DashboardStatus.FIRST_USE:
        return
    prices = st.session_state.price_data
    if prices is None or prices.empty:
        return
    source = st.session_state.price_data_source or {}
    source_type = str(source.get("source_type") or "")
    st.session_state.dashboard_status = (
        DashboardStatus.STALE.value
        if "快取" in source_type or "SQLite" in source_type
        else DashboardStatus.READY.value
    )
    st.session_state.dashboard_status_source = source_type or None
    st.session_state.dashboard_status_updated_at = source.get("end_date")


_scroll_reset_component: Any = None
try:
    import streamlit.components.v2 as _components

    _scroll_reset_component = _components.component(
        "scroll_reset",
        isolate_styles=False,
        js="""
        export default function scrollReset() {
          const reset = () => {
            const targets = document.querySelectorAll(
              '[data-testid="stMain"], [data-testid="stAppViewContainer"], .main'
            );
            for (const target of targets) {
              target.scrollTop = 0;
              if (typeof target.scrollTo === 'function') target.scrollTo(0, 0);
            }
            document.documentElement.scrollTop = 0;
            if (document.body) document.body.scrollTop = 0;
            window.scrollTo(0, 0);
          };
          reset();
          window.requestAnimationFrame(reset);
          window.setTimeout(reset, 80);
        }
        """,
    )
except Exception:
    _scroll_reset_component = None


def _render_scroll_reset(st: Any, token: str) -> None:
    """Safely reset page scroll to top on workspace transition."""
    if _scroll_reset_component is not None:
        try:
            _scroll_reset_component(key=f"nav_scroll_reset_{token}")
        except Exception:
            pass


def render_dashboard_shell(st: Any, dependencies: DashboardShellDependencies) -> None:
    """Render the six-workspace shell using existing legacy callbacks only."""

    apply_pending_workspace_navigation(st.session_state)
    active_key = str(st.session_state.dashboard_active_workspace)
    item = render_primary_navigation(st, active_key=active_key)
    st.session_state.dashboard_active_workspace = item.key
    previous_workspace = st.session_state.get("_last_rendered_workspace")
    if previous_workspace != item.key:
        import time as _time

        st.session_state["_last_rendered_workspace"] = item.key
        token = f"{item.key}_{int(_time.time() * 1000)}"
        _render_scroll_reset(st, token)
    current_status = dashboard_status(st.session_state)
    if item.key != "home":
        render_dashboard_status(
            st,
            status=current_status,
            message=st.session_state.dashboard_status_message,
        )

    if item.key == "home":
        _render_home_workspace(st, dependencies, current_status)
    else:
        _render_workspace(st, dependencies, item)
    st.sidebar.warning(dependencies.risk_notice)
    caption = getattr(st.sidebar, "caption", None)
    if callable(caption):
        caption(f"StockTool v{__version__}")


def render_legacy_dashboard(st: Any, dependencies: DashboardShellDependencies) -> None:
    """Render the old dashboard only after an explicit diagnostic opt-in."""

    st.sidebar.title(f"{dependencies.app_title} · Legacy")
    if st.sidebar.button("返回新版工作區", key="legacy_return_to_shell"):
        st.session_state.legacy_dashboard = False
        st.rerun()
    st.sidebar.warning("診斷模式：此介面保留至 Sprint 5 Research Workspace 驗收完成。")
    page = st.sidebar.radio(
        "診斷頁面", list(LEGACY_PAGE_OPTIONS), key="legacy_dashboard_navigation"
    )
    st.sidebar.warning(dependencies.risk_notice)
    _render_legacy_page_safely(st, dependencies, page)


def _render_home_workspace(
    st: Any,
    dependencies: DashboardShellDependencies,
    current_status: DashboardStatus,
) -> None:
    """Render the start screen and adapt one approved hydration request."""

    snapshot = st.session_state.research_snapshot
    if (
        snapshot is not None
        and st.session_state.get("company_details_force", False)
        and dependencies.build_research_snapshot is not None
    ):
        # Rebuild from the already loaded price/score inputs; only company
        # documents are refreshed. The new snapshot is also the AI input.
        try:
            refreshed = dependencies.build_research_snapshot(
                st, symbol=snapshot.symbol.code, market=snapshot.symbol.market.value
            )
            if refreshed is None or refreshed.symbol != snapshot.symbol:
                raise ValueError("Company refresh changed research identity")
            snapshot = refreshed
            st.session_state["research_snapshot"] = snapshot
            snapshots = dict(st.session_state.get("dashboard_research_snapshots") or {})
            snapshots[snapshot.symbol.canonical] = snapshot
            st.session_state["dashboard_research_snapshots"] = snapshots
        except Exception:
            warning = "公司資料更新未完成，仍顯示前次研究快照；請核對原文取得日期。"
            profile = getattr(snapshot, "company_profile", None)
            if profile is not None and profile.dossier is not None:
                snapshot = replace(
                    snapshot,
                    company_profile=replace(
                        profile, dossier=replace(profile.dossier, state="stale")
                    ),
                    warnings=(*snapshot.warnings, warning),
                )
                st.session_state["research_snapshot"] = snapshot
                snapshots = dict(st.session_state.get("dashboard_research_snapshots") or {})
                snapshots[snapshot.symbol.canonical] = snapshot
                st.session_state["dashboard_research_snapshots"] = snapshots
            st.warning(warning)
        finally:
            st.session_state.pop("company_details_force", None)
    if snapshot is not None and st.session_state.get("dashboard_show_research_workspace", False):
        if st.button("返回今天先看這些", key="return_to_daily_home"):
            st.session_state["dashboard_show_research_workspace"] = False
            st.rerun()
            return
        preparation = _render_research_with_handoff(st, snapshot)
        if preparation is not None:
            _submit_shell_search(st, preparation)
        _execute_pending_shell_search(st, dependencies)
        return

    source = st.session_state.price_data_source or {}
    summary = load_home_summary(
        st.session_state,
        portfolio_path=dependencies.portfolio_path,
        watchlist_path=dependencies.watchlist_path,
    )
    daily_brief = dependencies.build_daily_brief(st) if dependencies.build_daily_brief else None
    inbox_entries: tuple[ResearchInboxEntry, ...] = ()
    inbox_brief: DailyResearchBrief | None = None
    change_summary: DailyResearchChangeSet | None = None
    macro_snapshot: MacroSnapshot | None = None
    macro_signals: tuple[MacroSignal, ...] = ()
    macro_links: tuple[dict[str, object], ...] = ()
    macro_revisions: tuple[dict[str, object], ...] = ()
    prediction_lab_summary: PredictionLabSummary | None = None
    daily_research_run: DailyResearchRunManifest | None = None
    inbox_warning: str | None = None
    if dependencies.daily_research_inbox_service is not None:
        try:
            inbox_entries = dependencies.daily_research_inbox_service.entries()
            inbox_brief = dependencies.daily_research_inbox_service.latest_validated_brief()
        except Exception:
            inbox_warning = "每日研究收件匣資料無法驗證，已安全隱藏損壞內容。"
    try:
        paths = default_runtime_paths()
        change_summary = DailyResearchChangeStore(
            paths.daily_research_change_file,
            paths.daily_research_change_history_dir,
        ).load()
    except Exception:
        inbox_warning = inbox_warning or "今天的變化摘要無法驗證，已安全隱藏。"
    session_change_warning = st.session_state.pop("dashboard_daily_change_warning", None)
    if isinstance(session_change_warning, str) and session_change_warning.strip():
        inbox_warning = inbox_warning or session_change_warning.strip()
    if dependencies.build_macro_snapshot is not None:
        try:
            macro_snapshot, macro_signals = dependencies.build_macro_snapshot(st)
        except Exception:
            dependencies.logger.exception("Macro snapshot load failed")
            inbox_warning = inbox_warning or "總經背景無法驗證；目前不顯示未驗證內容。"
    if macro_snapshot is not None and dependencies.build_macro_links is not None:
        try:
            macro_links = dependencies.build_macro_links(st, macro_snapshot)
        except Exception:
            dependencies.logger.exception("Macro links load failed")
            inbox_warning = inbox_warning or "持股／自選股總經關聯無法驗證，已安全略過。"
    if dependencies.build_macro_revisions is not None:
        try:
            macro_revisions = dependencies.build_macro_revisions(st)
        except Exception:
            dependencies.logger.exception("Macro revision history load failed")
    if dependencies.build_prediction_lab_summary is not None:
        try:
            prediction_lab_summary = dependencies.build_prediction_lab_summary(st)
        except Exception:
            dependencies.logger.exception("Prediction Lab summary load failed")
            inbox_warning = inbox_warning or "預測評估實驗室資料目前無法驗證"
    if dependencies.build_daily_research_run is not None:
        try:
            daily_research_run = dependencies.build_daily_research_run()
        except Exception:
            dependencies.logger.exception("Daily research run manifest load failed")
    context = HomeContext(
        status=current_status,
        active_symbol=st.session_state.active_symbol,
        recent_searches=tuple(st.session_state.dashboard_recent_searches),
        watchlist_count=summary.watchlist_count,
        portfolio_count=summary.portfolio_count,
        source_label=source.get("source_type") or source.get("provider"),
        updated_at=source.get("end_date"),
        summary_warnings=summary.warnings + ((inbox_warning,) if inbox_warning else ()),
        daily_brief=daily_brief,
        daily_research_loop=(
            dependencies.build_daily_research_loop(st)
            if dependencies.build_daily_research_loop
            else None
        ),
        research_assistant_brief=st.session_state.get("dashboard_ai_research_brief"),
        research_assistant_available=(
            bool(st.session_state.get("dashboard_research_snapshots"))
            or bool(getattr(daily_brief, "attention_items", ()))
            or bool(getattr(daily_brief, "continuations", ()))
        ),
        daily_evidence_brief=(
            dependencies.build_daily_evidence_brief(st)
            if dependencies.build_daily_evidence_brief
            else None
        ),
        daily_evidence_available=True,
        daily_research_inbox=inbox_entries,
        daily_research_inbox_brief=inbox_brief,
        daily_research_changes=change_summary,
        macro_snapshot=macro_snapshot,
        macro_signals=macro_signals,
        macro_links=macro_links,
        macro_revisions=macro_revisions,
        prediction_lab=prediction_lab_summary,
        prediction_lab_evaluation_available=(dependencies.evaluate_prediction_outcomes is not None),
        daily_research_run=daily_research_run,
    )
    action = render_home(st, context)
    if action is not None:
        _handle_home_action(st, dependencies, action)
        if action.kind == "refresh":
            return
    _render_daily_refresh_result(st)
    _execute_pending_shell_search(st, dependencies)

    snapshot = st.session_state.research_snapshot
    if snapshot is not None and st.session_state.get("dashboard_show_research_workspace", False):
        rerun = getattr(st, "rerun", None)
        if callable(rerun):
            rerun()
        else:
            _render_research_with_handoff(st, snapshot)
        return

    st.caption("完成搜尋後會進入 Research Workspace；完整舊版介面僅保留於「設定」的診斷模式。")


def _handle_home_action(
    st: Any,
    dependencies: DashboardShellDependencies,
    action: HomeAction,
) -> None:
    """Route a Daily Research Home action without embedding business logic in UI cards."""

    if action.kind == "search" and action.preparation is not None:
        _submit_shell_search(st, action.preparation)
        return
    if action.kind == "workspace" and action.workspace:
        navigate_to_workspace(
            st.session_state,
            workspace=action.workspace,
            legacy_page=action.legacy_page,
        )
        st.rerun()
        return
    if action.kind == "ai_research":
        if dependencies.generate_daily_ai_research is None:
            st.info("目前沒有可用的研究簡報服務。")
            return
        with st.spinner("正在建立有引用的今日研究簡報…"):
            st.session_state["dashboard_ai_research_brief"] = (
                dependencies.generate_daily_ai_research(st, action.force_regenerate)
            )
        st.rerun()
        return
    if action.kind == "daily_evidence_brief":
        if dependencies.generate_daily_evidence_brief is None:
            st.info("目前無法產生研究簡報；既有研究內容仍可使用。")
            return
        try:
            with st.spinner("正在整理今日證據鏈研究簡報…"):
                brief_result = dependencies.generate_daily_evidence_brief(
                    st, action.force_regenerate
                )
            st.session_state["dashboard_daily_evidence_brief"] = brief_result
            st.success("今日研究簡報已產生；內容僅供研究驗證，不是投資建議。")
        except Exception:
            dependencies.logger.exception("Daily evidence brief generation failed")
            st.error("研究簡報產生失敗；最近一次成功版本仍保留。")
        rerun = getattr(st, "rerun", None)
        if callable(rerun):
            rerun()
        return
    if action.kind == "daily_research_run":
        if dependencies.run_daily_research is None:
            st.info("目前沒有可用的今日研究流程。")
            return
        try:
            with st.spinner("正在執行今日研究…"):
                outcome = dependencies.run_daily_research()
            st.session_state["dashboard_daily_run_outcome"] = outcome
            if outcome.status == "success":
                st.success("今日研究已完成；內容僅供研究驗證，不是投資建議。")
            elif outcome.status in {"partial", "failed"}:
                st.warning("今日研究部分完成；未驗證階段不會建立新樣本。")
            else:
                st.info("今日研究本次略過；既有成果仍可使用。")
        except Exception:
            dependencies.logger.exception("Daily research run failed")
            st.error("今日研究未完成；最近一次成功成果仍保留。")
        rerun = getattr(st, "rerun", None)
        if callable(rerun):
            rerun()
        return
    if action.kind == "prediction_outcome_evaluation":
        if dependencies.evaluate_prediction_outcomes is None:
            st.info("目前沒有可驗證的到期資料；既有樣本仍可查看。")
            return
        try:
            with st.spinner("正在更新到期結果…"):
                result = dependencies.evaluate_prediction_outcomes()
            status = str(getattr(result, "status", "unavailable"))
            if status == "success":
                st.success("到期結果已更新；內容僅供研究驗證。")
            elif status == "partial":
                st.warning("部分到期樣本仍待資料；未驗證內容不會顯示為績效。")
            else:
                st.info("目前沒有足夠的到期證據；既有結果仍保留。")
        except Exception:
            dependencies.logger.exception("Prediction outcome evaluation failed")
            st.error("到期結果更新未完成；既有結果仍保留。")
        rerun = getattr(st, "rerun", None)
        if callable(rerun):
            rerun()
        return
    if action.kind == "macro_refresh":
        if dependencies.refresh_macro_snapshot is None:
            st.info("目前無法更新總經資料；可繼續使用既有研究內容。")
            return
        try:
            with st.spinner("正在更新官方總經資料…"):
                snapshot = dependencies.refresh_macro_snapshot(st)
            st.session_state["dashboard_macro_snapshot"] = snapshot
            if snapshot.status == "ready":
                st.success("總經資料已更新並通過驗證。")
            elif snapshot.status == "stale":
                st.warning("官方更新失敗，已安全沿用最後一份已驗證快照。")
            else:
                st.warning("總經資料目前不完整，未產生未驗證數值。")
        except Exception:
            dependencies.logger.exception("Macro snapshot refresh failed")
            st.error("總經資料更新失敗；既有資料未被改寫。")
        rerun = getattr(st, "rerun", None)
        if callable(rerun):
            rerun()
        return
    if action.kind != "refresh":
        return
    if dependencies.refresh_daily_data is None:
        st.info("目前沒有可用的今日資料更新服務。")
        return
    with st.spinner("正在更新今日資料…"):
        result = dependencies.refresh_daily_data(st)
    st.session_state["dashboard_daily_refresh_result"] = result
    if result.requested_count == 0:
        st.info("目前沒有可更新的持股或自選股。")
    elif result.failure_count == 0:
        st.success(f"今日資料更新完成：{result.success_count} 檔。")
    elif result.success_count:
        st.warning(
            f"今日資料部分更新：成功 {result.success_count} 檔，"
            f"失敗 {result.failure_count} 檔。"
        )
    else:
        st.error("今日資料更新失敗，已保留上一次成功的研究內容。")
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()
    return


def _render_research_with_handoff(st: Any, snapshot: Any) -> Any:
    """Render Research with the typed callback while preserving test seams."""

    parameters = inspect.signature(render_research_workspace).parameters
    if "on_handoff" not in parameters:
        return render_research_workspace(st, snapshot)
    return render_research_workspace(
        st,
        snapshot,
        on_handoff=lambda destination, current: _route_research_workspace_handoff(
            st, destination, current
        ),
    )


def _render_daily_refresh_result(st: Any) -> None:
    """Render and consume one user-triggered refresh result after rerun."""

    result = st.session_state.get("dashboard_daily_refresh_result")
    if result is None:
        return
    try:
        if result.requested_count == 0:
            st.info("目前沒有可更新的持股或自選股。")
        elif result.failure_count == 0:
            st.success(f"今日資料更新完成：{result.success_count} 檔。")
        elif result.success_count:
            st.warning(
                f"今日資料部分更新：成功 {result.success_count} 檔，"
                f"失敗 {result.failure_count} 檔。"
            )
        else:
            st.error("今日資料更新失敗，已保留上一次成功的研究內容。")
        if result.requested_count > result.limited_count:
            st.info(
                f"本次更新 {result.limited_count} 檔，另有 "
                f"{result.requested_count - result.limited_count} 檔未納入。"
            )
        if result.records:
            with st.expander("今日更新明細"):
                for record in result.records:
                    status = {
                        "success": "成功",
                        "partial": "部分成功",
                        "failure": "失敗",
                        "unavailable": "資料不足",
                    }[record.status]
                    detail = (
                        f"{record.symbol.code} ({record.symbol.market.value})：{status}；"
                        f"來源：{record.provider or '資料不足'}；"
                        f"查詢代號：{record.query_symbol or '資料不足'}；"
                        f"最後資料日：{record.last_data_date or '資料不足'}"
                    )
                    st.write(detail)
                    if record.reason:
                        st.caption(record.reason)
    finally:
        st.session_state["dashboard_daily_refresh_result"] = None


def _render_workspace(
    st: Any,
    dependencies: DashboardShellDependencies,
    item: NavigationItem,
) -> None:
    """Render an action-oriented overview before the secondary legacy switcher."""

    render_page_header(st, item)
    handoff = consume_research_handoff(st.session_state, destination=item.key)
    if handoff is not None:
        _apply_workspace_handoff(st, handoff)
    notice = st.session_state.pop("dashboard_handoff_notice", None)
    if isinstance(notice, str) and notice:
        st.info(notice)
    if item.key == "strategy":
        handoff_error = st.session_state.pop("strategy_workspace_handoff_error", None)
        if isinstance(handoff_error, str) and handoff_error:
            st.warning(handoff_error)
            return
    if item.key == "explore":
        concept_path = dependencies.concept_path or (Path("data") / "sample" / "concept_stocks.csv")
        service = ExploreApplicationService(
            concept_path=concept_path,
            watchlist_path=dependencies.watchlist_path,
        )
        runtime = RuntimePaths.from_environment()
        market_service = MarketMonitorApplicationService(
            runtime.market_snapshot_file,
            classifications=load_local_classifications(concept_path),
        )
        render_explore_workspace(
            st,
            service,
            on_research=lambda symbol: _route_explore_research(st, symbol),
            market_service=market_service,
        )
    if item.key == "library":
        tracker = st.session_state.get("provider_health_tracker")
        snapshots = (
            tracker.snapshots() if tracker is not None and hasattr(tracker, "snapshots") else ()
        )
        paths = default_runtime_paths()
        force_refresh = render_library_workspace(
            st,
            source=st.session_state.price_data_source,
            provider_health=tuple(snapshot.to_dict() for snapshot in snapshots),
            library=ResearchLibrary(paths.research_library_dir),
            on_current_research=lambda symbol, market: _route_library_current_research(
                st, symbol, market
            ),
        )
        if force_refresh:
            source = st.session_state.price_data_source or {}
            symbol = source.get("user_symbol") or st.session_state.active_symbol
            market = source.get("market")
            if symbol and market:
                try:
                    dependencies.ensure_symbol_data(
                        st, symbol=str(symbol), market=str(market), force_refresh=True
                    )
                    st.success("已完成強制重新整理。")
                except Exception:
                    dependencies.logger.exception("Library force refresh failed")
                    st.error("無法完成強制重新整理；既有資料未被修改。")
    if item.key == "library" and _route_current_library_research(st):
        return
    if item.key == "strategy":
        strategy_kwargs: dict[str, Any] = {
            "service": StrategyWorkspaceApplicationService(),
        }
        if "on_research" in inspect.signature(render_strategy_workspace).parameters:
            strategy_kwargs["on_research"] = lambda symbol, market: _route_workspace_to_research(
                st, "strategy", symbol, market
            )
        render_strategy_workspace(st, **strategy_kwargs)
        return
    if item.key == "holdings":
        runtime = RuntimePaths.from_environment()
        portfolio_service = PortfolioWorkspaceApplicationService(
            portfolio_path=dependencies.portfolio_path,
            ledger_path=runtime.ledger_database_file,
        )

        def refresh_holdings() -> tuple[object, ...]:
            positions = portfolio_service.load_positions()
            from stock_tool.application.holding_identity import (
                fetch_holding_identity,
                save_identity_state,
            )

            profiles = st.session_state.setdefault("holding_profiles", {})
            errors = st.session_state.setdefault("holding_profile_errors", {})
            for row in positions.itertuples(index=False):
                identity = f"{row.symbol}|{row.market}"
                try:
                    profiles[identity] = fetch_holding_identity(str(row.symbol), str(row.market))
                    errors.pop(identity, None)
                except Exception:
                    errors[identity] = "標的名稱、類型或分類未能更新；請確認市場與代號。"
            try:
                save_identity_state(
                    runtime.data_dir / "holding_identity.json",
                    {
                        "profiles": profiles,
                        "overrides": st.session_state.get("holding_type_overrides", {}),
                    },
                )
            except OSError:
                st.warning("標的分類本次可用，但尚未保存；下次開啟將重新確認。")
            if dependencies.refresh_portfolio_data is not None:
                outcome = dependencies.refresh_portfolio_data(
                    st,
                    positions,
                    force_refresh=bool(st.session_state.get("holding_force_refresh", False)),
                )
                resolution = st.session_state.get("portfolio_fx_resolution")
                if getattr(resolution, "status", None) == "manual":
                    quote = getattr(resolution, "quote", None)
                    applied_at = getattr(quote, "effective_at", None)
                    if applied_at:
                        st.session_state["portfolio_workspace_manual_fx_applied_at"] = str(
                            applied_at
                        )
                st.session_state.pop("portfolio_workspace_stress_result", None)
                return (outcome,)
            outcomes: list[object] = []
            for row in positions.itertuples(index=False):
                market = str(row.market).strip().upper()
                if market in {"TWSE", "TPEX", "US"}:
                    outcomes.append(
                        dependencies.ensure_symbol_data(
                            st,
                            symbol=str(row.symbol),
                            market=market,
                            force_refresh=False,
                        )
                    )
            return tuple(outcomes)

        if dependencies.build_portfolio_classifications is not None:
            classification_builder = dependencies.build_portfolio_classifications
            portfolio_kwargs: dict[str, Any] = {
                "service": portfolio_service,
                "refresh_callback": refresh_holdings,
                "classification_callback": lambda positions: classification_builder(st, positions),
            }
            if "on_research" in inspect.signature(render_portfolio_workspace).parameters:
                portfolio_kwargs["on_research"] = (
                    lambda symbol, market: _route_workspace_to_research(
                        st, "holdings", symbol, market
                    )
                )
            render_portfolio_workspace(st, **portfolio_kwargs)
        else:
            portfolio_kwargs = {
                "service": portfolio_service,
                "refresh_callback": refresh_holdings,
            }
            if "on_research" in inspect.signature(render_portfolio_workspace).parameters:
                portfolio_kwargs["on_research"] = (
                    lambda symbol, market: _route_workspace_to_research(
                        st, "holdings", symbol, market
                    )
                )
            render_portfolio_workspace(st, **portfolio_kwargs)
        return
    if item.key == "settings":
        runtime = RuntimePaths.from_environment()
        settings_service = SettingsWorkspaceApplicationService(
            runtime,
            database_path=runtime.processed_dir / "stock_data.sqlite",
        )

        def refresh_settings() -> SettingsWorkspaceSnapshot:
            if dependencies.refresh_settings_workspace is not None:
                return dependencies.refresh_settings_workspace()
            return settings_service.refresh()

        render_settings_workspace(
            st,
            service=settings_service,
            refresh_callback=refresh_settings,
            daily_schedule_service=dependencies.daily_schedule_service,
            daily_notification_service=dependencies.daily_notification_service,
        )
        _render_workspace_legacy_entry(st, dependencies, "settings")
        return
    action = render_workspace_overview(st, item.key)
    if action is not None and action.diagnostic_mode:
        st.session_state.legacy_dashboard = True
        st.rerun()
        return
    _render_workspace_legacy_entry(
        st,
        dependencies,
        item.key,
        preferred_page=action.legacy_page if action is not None else None,
    )


def _route_library_current_research(st: Any, symbol: str, market: str) -> None:
    """Queue and consume one explicit Library→Research current-data handoff."""

    try:
        context = ResearchContext(
            symbol=Symbol.parse(symbol, market=Market.parse(market)),
            market=Market.parse(market),
            origin_workspace=ResearchWorkspace.LIBRARY,
            destination_workspace=ResearchWorkspace.RESEARCH,
            action=ResearchHandoffAction.RESEARCH_CURRENT_DATA,
        )
    except ValueError:
        st.warning("研究庫接力無效：市場與代號無法核對。請重新選擇保存版本。")
        return
    enqueue_research_handoff(st.session_state, context)
    consumed = consume_research_handoff(st.session_state, destination="research")
    if consumed is None:
        st.warning("研究庫接力尚未準備完成；既有保存版本未被修改。")
        return
    begin_search(
        st.session_state,
        SearchRequest(symbol=consumed.symbol_code, market=consumed.market.value),
    )
    navigate_to_workspace(st.session_state, workspace="home")
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def _route_workspace_to_research(st: Any, origin: str, symbol: str, market: str) -> None:
    """Return from Strategy/Holdings to Research through the same contract."""

    try:
        context = ResearchContext(
            symbol=Symbol.parse(symbol, market=Market.parse(market)),
            market=Market.parse(market),
            origin_workspace=ResearchWorkspace(origin),
            destination_workspace=ResearchWorkspace.RESEARCH,
            action=ResearchHandoffAction.RETURN_TO_RESEARCH,
        )
    except ValueError:
        st.warning("研究接力被拒絕：目前選取的市場或代號不明確。")
        return
    enqueue_research_handoff(st.session_state, context)
    consumed = consume_research_handoff(st.session_state, destination="research")
    if consumed is None:
        st.warning("研究接力尚未準備完成；既有資料未被修改。")
        return
    begin_search(
        st.session_state,
        SearchRequest(symbol=consumed.symbol_code, market=consumed.market.value),
    )
    navigate_to_workspace(st.session_state, workspace="home")
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def _route_current_library_research(st: Any) -> bool:
    """Route legacy Library payloads through the typed handoff boundary."""

    payload = st.session_state.pop("dashboard_library_current_research", None)
    if not isinstance(payload, dict):
        return False
    symbol = payload.get("symbol")
    market = payload.get("market")
    if not isinstance(symbol, str) or not isinstance(market, str):
        st.warning("目前資料研究請求無效。")
        return True
    _route_library_current_research(st, symbol, market)
    return True


def _route_research_workspace_handoff(
    st: Any,
    destination: str,
    snapshot: Any,
) -> None:
    """Queue an explicit Research→workspace handoff without mutating data."""

    symbol = getattr(snapshot, "symbol", None)
    market = getattr(symbol, "market", None)
    code = getattr(symbol, "code", None)
    market_value = getattr(market, "value", market)
    action_by_destination = {
        "strategy": ResearchHandoffAction.OPEN_STRATEGY,
        "holdings": ResearchHandoffAction.OPEN_HOLDINGS,
        "library": ResearchHandoffAction.OPEN_LIBRARY,
    }
    action = action_by_destination.get(destination)
    if not isinstance(code, str) or not isinstance(market_value, str) or action is None:
        st.warning("研究接力無效：目前研究的市場或代號無法核對。")
        return
    data_as_of = getattr(getattr(snapshot, "price", None), "last_data_date", None)
    try:
        context = ResearchContext(
            symbol=Symbol.parse(code, market=Market.parse(market_value)),
            market=Market.parse(market_value),
            origin_workspace=ResearchWorkspace.RESEARCH,
            destination_workspace=ResearchWorkspace(destination),
            action=action,
            data_as_of=data_as_of,
        )
    except ValueError:
        st.warning("研究接力被拒絕：市場限定身分無法驗證。")
        return
    enqueue_research_handoff(st.session_state, context)
    navigate_to_workspace(st.session_state, workspace=destination)
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def _apply_workspace_handoff(st: Any, context: ResearchContext) -> None:
    """Apply a consumed context as a non-mutating workspace focus."""

    if context.destination_workspace.value == "library":
        st.session_state["library_symbol_filter"] = context.symbol_code
        st.session_state["library_market_filter"] = context.market.value
        st.session_state["dashboard_handoff_notice"] = "已套用研究市場與代號篩選；未自動保存研究。"
        return
    if context.destination_workspace.value == "holdings":
        st.session_state["portfolio_workspace_focus"] = context.to_dict()
        st.session_state["dashboard_handoff_notice"] = "已預填持倉研究焦點；未新增或修改持股。"
        return
    if context.destination_workspace.value == "strategy":
        if not _loaded_identity_matches(st, context):
            _reject_stale_strategy_handoff(st)
            return
        if not _loaded_snapshot_matches(st, context):
            _reject_stale_strategy_handoff(st)
            return
        st.session_state["active_symbol"] = context.symbol_code
        st.session_state["strategy_workspace_identity"] = (
            f"{context.market.value} / {context.symbol_code}"
        )
        st.session_state["strategy_workspace_handoff_context"] = context.to_dict()
        st.session_state["dashboard_handoff_notice"] = "已帶入相同市場與代號；未自動抓取資料。"


def _loaded_identity_matches(st: Any, context: ResearchContext) -> bool:
    """Require an exact row-level market-qualified identity before Strategy handoff."""

    prices = st.session_state.get("price_data")
    if prices is None or not hasattr(prices, "columns"):
        return False
    if "symbol" not in prices.columns or "market" not in prices.columns:
        return False
    rows = prices.loc[
        prices["symbol"].astype(str).str.strip().str.upper().eq(context.symbol_code)
        & prices["market"].astype(str).str.strip().str.upper().eq(context.market.value)
    ]
    return not rows.empty


def _loaded_snapshot_matches(st: Any, context: ResearchContext) -> bool:
    """Require optional as-of/fingerprint claims to match known current state."""

    if context.snapshot_fingerprint is not None:
        current = st.session_state.get("research_snapshot_fingerprint")
        if current is None:
            snapshot = st.session_state.get("research_snapshot")
            current = getattr(snapshot, "snapshot_fingerprint", None)
            if current is None:
                current = getattr(snapshot, "fingerprint", None)
        if not isinstance(current, str) or current != context.snapshot_fingerprint:
            return False
    if context.data_as_of is None:
        return True
    prices = st.session_state.get("price_data")
    if prices is None or not hasattr(prices, "columns") or "date" not in prices.columns:
        return False
    dates = prices["date"].dropna()
    if dates.empty:
        return False
    latest = dates.max()
    if hasattr(latest, "date") and callable(latest.date):
        latest = latest.date()
    latest_text = latest.isoformat() if hasattr(latest, "isoformat") else str(latest)
    return latest_text == context.data_as_of


def _reject_stale_strategy_handoff(st: Any) -> None:
    st.session_state.pop("strategy_workspace_run", None)
    st.session_state["strategy_workspace_handoff_error"] = (
        "目前載入資料與接力的市場／代號或資料版本不一致。"
        "既有研究資料仍可查看，但未套用舊策略結果。"
        "系統已拒絕不相符的身分或 snapshot。"
        "請先載入相同市場與代號的目前資料，再重新執行策略。"
    )


def _route_explore_research(st: Any, symbol: Symbol) -> None:
    """Carry one canonical Explore identity into the existing current-data flow."""

    context = ResearchContext(
        symbol=symbol,
        market=symbol.market,
        origin_workspace=ResearchWorkspace.EXPLORE,
        destination_workspace=ResearchWorkspace.RESEARCH,
        action=ResearchHandoffAction.EXPLORE_TO_RESEARCH,
    )
    enqueue_research_handoff(st.session_state, context)
    consumed = consume_research_handoff(st.session_state, destination="research")
    if consumed is None:
        st.warning("探索接力尚未準備完成；請重新按一次研究按鈕。")
        return
    begin_search(
        st.session_state,
        SearchRequest(symbol=consumed.symbol_code, market=consumed.market.value),
    )
    navigate_to_workspace(st.session_state, workspace="home")
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def _submit_shell_search(st: Any, preparation: SearchPreparation) -> None:
    """Start a validated search while keeping raw input out of rendered HTML."""

    if preparation.request is None:
        st.warning(preparation.message or "請確認查詢條件後再試。")
        return
    begin_search(st.session_state, preparation.request)


def _execute_pending_shell_search(st: Any, dependencies: DashboardShellDependencies) -> None:
    """Execute one pending submission, isolating legacy exceptions from the UI."""

    request = should_execute_pending_search(st.session_state)
    if request is None:
        return
    try:
        with st.spinner("正在更新研究資料…"):
            result = dependencies.ensure_symbol_data(
                st,
                symbol=request.symbol,
                market=request.market,
                force_refresh=request.force_refresh,
            )
    except Exception:
        dependencies.logger.exception(
            "Dashboard global search failed for %s/%s", request.symbol, request.market
        )
        finish_search(
            st.session_state,
            request,
            status=DashboardStatus.ERROR,
            message="無法完成資料更新。請確認代號、市場或網路連線後再試。",
        )
        return

    warnings = tuple(result.get("warnings") or ())
    if dependencies.build_research_snapshot is not None:
        try:
            snapshot = dependencies.build_research_snapshot(
                st,
                symbol=request.symbol,
                market=request.market,
            )
            if snapshot is None or getattr(snapshot, "symbol", None) != Symbol(
                request.symbol, Market(request.market)
            ):
                raise ValueError("Research snapshot identity does not match search")
            if snapshot is not None:
                st.session_state["research_snapshot"] = snapshot
                st.session_state["dashboard_show_research_workspace"] = True
                snapshot_symbol = getattr(snapshot, "symbol", None)
                if isinstance(snapshot_symbol, Symbol):
                    snapshots = dict(st.session_state.get("dashboard_research_snapshots") or {})
                    snapshots[snapshot_symbol.canonical] = snapshot
                    st.session_state["dashboard_research_snapshots"] = snapshots
                _record_research_continuation(st, snapshot)
        except Exception:
            dependencies.logger.exception(
                "Research snapshot assembly failed for %s/%s", request.symbol, request.market
            )
            warnings = (*warnings, "研究快照尚未建立；已保留既有資料，不會顯示假結果。")
            st.session_state["dashboard_show_research_workspace"] = False
            finish_search(
                st.session_state,
                request,
                status=DashboardStatus.ERROR,
                message="新公司的研究未能確認，請重新查詢；尚未切換成功。",
            )
            st.rerun()
            return
    status = DashboardStatus.PARTIAL if warnings else DashboardStatus.READY
    finish_search(
        st.session_state,
        request,
        status=status,
        message=("已載入可用資料；部分內容仍待補齊。" if warnings else "已更新可用研究資料。"),
        source=str((st.session_state.price_data_source or {}).get("source_type") or ""),
        updated_at=str((st.session_state.price_data_source or {}).get("end_date") or "") or None,
    )
    if dependencies.build_research_snapshot is not None:
        st.rerun()
        return
    st.success(f"已載入 {request.symbol}（{request.market}）資料。")
    source = st.session_state.price_data_source or {}
    _render_daily_refresh_result(st)
    st.caption(
        "查詢輸入："
        f"{request.symbol}；辨識市場：{request.market}；實際查詢代號："
        f"{source.get('query_symbol') or result.get('symbol') or '資料不足'}。"
    )


def _record_research_continuation(st: Any, snapshot: Any) -> None:
    """Keep a compact, market-qualified continuation record for the daily home."""

    symbol = getattr(snapshot, "symbol", None)
    if not isinstance(symbol, Symbol):
        return
    try:
        continuation = ResearchContinuation(
            symbol=symbol,
            researched_at=_optional_display_text(getattr(snapshot, "updated_at", None)),
            data_as_of_date=getattr(getattr(snapshot, "price", None), "last_data_date", None),
            coverage=getattr(snapshot, "score_coverage", None),
            status=str(getattr(snapshot, "status", "")) or "available",
        )
    except (TypeError, ValueError):
        return
    existing = [
        item
        for item in st.session_state.get("dashboard_research_continuations", [])
        if not isinstance(item, ResearchContinuation) or item.symbol != continuation.symbol
    ]
    st.session_state["dashboard_research_continuations"] = [continuation, *existing][:8]


def _optional_display_text(value: object) -> str | None:
    """Normalize absent values before they can become a visible Python sentinel."""

    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.casefold() != "none" else None


def _render_workspace_legacy_entry(
    st: Any,
    dependencies: DashboardShellDependencies,
    workspace_key: str,
    *,
    summary_label: str = "工作區總覽",
    preferred_page: str | None = None,
) -> None:
    """Keep a compact secondary switcher for all retained legacy functionality."""

    item = navigation_for_key(workspace_key)
    options = (summary_label, *item.legacy_pages)
    widget_key = f"workspace_{workspace_key}_secondary_navigation"
    pending = st.session_state.get("dashboard_pending_workspace_destination")
    if (
        isinstance(pending, dict)
        and pending.get("workspace") == workspace_key
        and pending.get("legacy_page") in item.legacy_pages
    ):
        preferred_page = str(pending["legacy_page"])
        st.session_state["dashboard_pending_workspace_destination"] = None
    if preferred_page in item.legacy_pages:
        st.session_state[widget_key] = preferred_page
    selected = st.selectbox("此工作區功能", options, key=widget_key)
    if selected != summary_label:
        _render_legacy_page_safely(st, dependencies, selected)


def _render_legacy_page_safely(
    st: Any,
    dependencies: DashboardShellDependencies,
    page: str,
) -> None:
    """Prevent a retained page exception from breaking the new Dashboard shell."""

    try:
        dependencies.render_legacy_page(st, page)
    except Exception:
        dependencies.logger.exception("Legacy dashboard page failed: %s", page)
        st.error("此功能目前無法完成。既有資料未被修改，請確認資料狀態後再試。")
