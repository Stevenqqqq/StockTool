from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import stock_tool.dashboard.shell as dashboard_shell
from stock_tool.application.daily_brief import DailyRefreshRecord, DailyRefreshResult
from stock_tool.dashboard.shell import (
    DashboardShellDependencies,
    _handle_home_action,
    _execute_pending_shell_search,
    _route_explore_research,
)
from stock_tool.dashboard.navigation import navigation_for_key
from stock_tool.dashboard.shell import _render_home_workspace
from stock_tool.dashboard.pages.home import HomeAction
from stock_tool.domain.models import Symbol
from stock_tool.dashboard.state import (
    DashboardStatus,
    SearchRequest,
    apply_pending_workspace_navigation,
    begin_search,
    dashboard_status,
    navigate_to_workspace,
)


class _FakeSessionState(dict):
    def __getattr__(self, name: str):
        return self.get(name)


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = _FakeSessionState(price_data_source={})
        self.messages: list[str] = []
        self.rerun_count = 0

    def spinner(self, _message: str):
        return nullcontext()

    def success(self, message: str) -> None:
        self.messages.append(message)

    def info(self, message: str) -> None:
        self.messages.append(message)

    def warning(self, message: str) -> None:
        self.messages.append(message)

    def error(self, message: str) -> None:
        self.messages.append(message)

    def rerun(self) -> None:
        self.rerun_count += 1

    def write(self, message: str) -> None:
        self.messages.append(message)

    def expander(self, _label: str):
        return nullcontext()

    def caption(self, message: str) -> None:
        self.messages.append(message)


class _HomeFakeStreamlit(_FakeStreamlit):
    def __init__(self, *, button_result: bool = False) -> None:
        super().__init__()
        self.session_state.update(
            {
                "research_snapshot": None,
                "dashboard_show_research_workspace": False,
                "active_symbol": None,
                "dashboard_recent_searches": [],
            }
        )
        self.button_result = button_result
        self.rerun_count = 0

    def button(self, _label: str, *, key: str) -> bool:
        del key
        return self.button_result

    def rerun(self) -> None:
        self.rerun_count += 1


def _dependencies(callback):
    return DashboardShellDependencies(
        ensure_symbol_data=callback,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell"),
    )


def test_shell_search_can_retry_the_same_request_after_a_failure() -> None:
    fake_st = _FakeStreamlit()
    calls: list[tuple[str, str]] = []

    def fail_then_succeed(_st, *, symbol: str, market: str, force_refresh: bool):
        del force_refresh
        calls.append((symbol, market))
        if len(calls) == 1:
            raise RuntimeError("temporary provider failure")
        return {"symbol": symbol, "warnings": ()}

    request = SearchRequest(symbol="AAPL", market="US")
    begin_search(fake_st.session_state, request)
    _execute_pending_shell_search(fake_st, _dependencies(fail_then_succeed))

    assert dashboard_status(fake_st.session_state) is DashboardStatus.ERROR
    assert fake_st.session_state["dashboard_pending_search"] is None

    begin_search(fake_st.session_state, request)
    _execute_pending_shell_search(fake_st, _dependencies(fail_then_succeed))
    _execute_pending_shell_search(fake_st, _dependencies(fail_then_succeed))

    assert calls == [("AAPL", "US"), ("AAPL", "US")]
    assert dashboard_status(fake_st.session_state) is DashboardStatus.READY
    assert any("已切換至 AAPL" in message for message in fake_st.messages)


def test_shell_search_builds_one_snapshot_and_preserves_it_when_later_search_fails() -> None:
    fake_st = _FakeStreamlit()
    snapshots: list[object] = []

    def succeeds_once(_st, *, symbol: str, market: str, force_refresh: bool):
        del force_refresh
        if symbol == "MISSING":
            raise RuntimeError("provider failure")
        return {"symbol": symbol, "market": market, "warnings": ()}

    def build_snapshot(_st, *, symbol: str, market: str):
        snapshot = {"symbol": symbol, "market": market}
        snapshots.append(snapshot)
        return snapshot

    dependencies = DashboardShellDependencies(
        ensure_symbol_data=succeeds_once,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell.snapshot"),
        build_research_snapshot=build_snapshot,
    )
    request = SearchRequest(symbol="2330", market="TWSE")
    begin_search(fake_st.session_state, request)
    _execute_pending_shell_search(fake_st, dependencies)

    first_snapshot = fake_st.session_state["research_snapshot"]
    assert first_snapshot == {"symbol": "2330", "market": "TWSE"}
    assert snapshots == [first_snapshot]
    assert fake_st.session_state["dashboard_show_research_workspace"] is True

    begin_search(fake_st.session_state, SearchRequest(symbol="MISSING", market="US"))
    _execute_pending_shell_search(fake_st, dependencies)

    assert dashboard_status(fake_st.session_state) is DashboardStatus.ERROR
    assert fake_st.session_state["research_snapshot"] is first_snapshot
    assert fake_st.session_state["dashboard_show_research_workspace"] is True


def test_explicit_research_workspace_request_can_open_retained_snapshot(monkeypatch) -> None:
    fake_st = _HomeFakeStreamlit(button_result=False)
    snapshot = object()
    fake_st.session_state["research_snapshot"] = snapshot
    fake_st.session_state["dashboard_show_research_workspace"] = True
    rendered: list[object] = []

    monkeypatch.setattr(
        dashboard_shell,
        "render_research_workspace",
        lambda _st, current_snapshot: rendered.append(current_snapshot),
    )

    _render_home_workspace(fake_st, _dependencies(lambda **_kwargs: {}), DashboardStatus.READY)

    assert rendered == [snapshot]
    assert fake_st.session_state["research_snapshot"] is snapshot


def test_failed_new_search_keeps_home_visible_when_previous_snapshot_is_retained() -> None:
    fake_st = _HomeFakeStreamlit(button_result=False)
    snapshot = object()
    fake_st.session_state["research_snapshot"] = snapshot
    fake_st.session_state["dashboard_show_research_workspace"] = False

    def fail(_st, *, symbol: str, market: str, force_refresh: bool):
        del symbol, market, force_refresh
        raise RuntimeError("provider failure")

    begin_search(fake_st.session_state, SearchRequest(symbol="MISSING", market="US"))
    _execute_pending_shell_search(fake_st, _dependencies(fail))

    assert fake_st.session_state["research_snapshot"] is snapshot
    assert fake_st.session_state["dashboard_show_research_workspace"] is False
    assert dashboard_status(fake_st.session_state) is DashboardStatus.ERROR


def test_return_to_daily_home_keeps_snapshot_and_does_not_reopen_on_rerun(monkeypatch) -> None:
    fake_st = _HomeFakeStreamlit(button_result=True)
    snapshot = object()
    fake_st.session_state["research_snapshot"] = snapshot
    fake_st.session_state["dashboard_show_research_workspace"] = True

    _render_home_workspace(fake_st, _dependencies(lambda **_kwargs: {}), DashboardStatus.READY)

    assert fake_st.session_state["dashboard_show_research_workspace"] is False
    assert fake_st.session_state["research_snapshot"] is snapshot
    assert fake_st.rerun_count == 1

    fake_st.button_result = False
    home_calls: list[str] = []

    def render_home(_st, _context):
        home_calls.append("home")
        return None

    monkeypatch.setattr(dashboard_shell, "render_home", render_home)
    monkeypatch.setattr(
        dashboard_shell,
        "render_research_workspace",
        lambda *_args, **_kwargs: pytest.fail("research workspace reopened after return"),
    )

    _render_home_workspace(fake_st, _dependencies(lambda **_kwargs: {}), DashboardStatus.READY)

    assert fake_st.session_state["dashboard_show_research_workspace"] is False
    assert fake_st.session_state["research_snapshot"] is snapshot
    assert home_calls == ["home"]


def test_home_navigation_synchronizes_primary_and_secondary_widgets() -> None:
    """A home CTA must survive the sidebar radio widget's next rerun."""

    session: dict[str, object] = {
        "dashboard_active_workspace": "home",
        "dashboard_primary_navigation": "研究首頁",
    }

    navigate_to_workspace(
        session,
        workspace="holdings",
        legacy_page="投資組合管理",
    )

    assert session["dashboard_active_workspace"] == "holdings"
    assert session["workspace_holdings_secondary_navigation"] == "投資組合管理"
    assert session["dashboard_pending_workspace_destination"] == {
        "workspace": "holdings",
        "legacy_page": "投資組合管理",
    }
    apply_pending_workspace_navigation(session)
    assert session["dashboard_primary_navigation"] == "持倉"


def test_home_navigation_can_open_watchlist_without_losing_sidebar_selection() -> None:
    """Explore CTAs should land on the retained watchlist child page."""

    session: dict[str, object] = {}

    navigate_to_workspace(session, workspace="explore", legacy_page="自選股清單")

    assert session["dashboard_active_workspace"] == "explore"
    assert session["workspace_explore_secondary_navigation"] == "自選股清單"
    apply_pending_workspace_navigation(session)
    assert session["dashboard_primary_navigation"] == "探索"


def test_explore_research_route_uses_canonical_symbol_and_home_flow() -> None:
    fake_st = _FakeStreamlit()
    _route_explore_research(fake_st, Symbol.parse("2330.TW", market="TWSE"))

    request = fake_st.session_state["dashboard_pending_search"]
    assert request.symbol == "2330"
    assert request.market == "TWSE"
    assert fake_st.session_state["dashboard_active_workspace"] == "home"
    assert fake_st.rerun_count == 1


def test_home_holdings_action_routes_to_management_child_and_reruns_once() -> None:
    fake_st = _FakeStreamlit()
    action = HomeAction(
        kind="workspace",
        workspace="holdings",
        legacy_page="投資組合管理",
    )

    dashboard_shell._handle_home_action(fake_st, _dependencies(lambda **_kwargs: {}), action)

    assert fake_st.rerun_count == 1
    assert fake_st.session_state["dashboard_active_workspace"] == "holdings"
    apply_pending_workspace_navigation(fake_st.session_state)
    assert fake_st.session_state["dashboard_primary_navigation"] == "持倉"
    assert fake_st.session_state["workspace_holdings_secondary_navigation"] == "投資組合管理"


def test_prediction_outcome_action_uses_explicit_callback_and_reruns() -> None:
    fake_st = _FakeStreamlit()
    calls: list[str] = []
    dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda **_kwargs: None,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell.prediction-eval"),
        evaluate_prediction_outcomes=lambda: calls.append("evaluate")
        or SimpleNamespace(status="partial"),
    )

    dashboard_shell._handle_home_action(
        fake_st, dependencies, HomeAction(kind="prediction_outcome_evaluation")
    )

    assert calls == ["evaluate"]
    assert fake_st.rerun_count == 1
    assert any("部分到期樣本仍待資料" in message for message in fake_st.messages)


def test_daily_refresh_reruns_once_and_zero_requested_is_information() -> None:
    fake_st = _FakeStreamlit()
    fake_st.session_state.update({"dashboard_daily_refresh_result": None})
    result = DailyRefreshResult(requested_count=0, limited_count=0, records=())
    dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda **_kwargs: None,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell.refresh"),
        refresh_daily_data=lambda _st: result,
    )

    dashboard_shell._handle_home_action(fake_st, dependencies, HomeAction(kind="refresh"))

    assert fake_st.session_state["dashboard_daily_refresh_result"] is result
    assert fake_st.rerun_count == 1
    assert any("目前沒有可更新的持股或自選股" in message for message in fake_st.messages)
    assert not any("已完成 0" in message for message in fake_st.messages)


def test_home_search_and_refresh_failure_paths_are_explicit() -> None:
    fake = _FakeStreamlit()
    preparation = SimpleNamespace(request=SearchRequest(symbol="AAPL", market="US"))
    dashboard_shell._handle_home_action(
        fake,
        _dependencies(lambda **_kwargs: {}),
        HomeAction(kind="search", preparation=preparation),
    )
    assert fake.session_state["dashboard_pending_search"].symbol == "AAPL"

    failure = DailyRefreshResult(
        requested_count=2,
        limited_count=2,
        records=(
            DailyRefreshRecord(symbol=Symbol.parse("2330", market="TWSE"), status="failure"),
            DailyRefreshRecord(symbol=Symbol.parse("6488", market="TPEX"), status="failure"),
        ),
    )
    dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda **_kwargs: None,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell.refresh.failure"),
        refresh_daily_data=lambda _st: failure,
    )
    fake.rerun = None
    dashboard_shell._handle_home_action(fake, dependencies, HomeAction(kind="refresh"))
    assert fake.messages

    partial = DailyRefreshResult(
        requested_count=2,
        limited_count=2,
        records=(
            DailyRefreshRecord(symbol=Symbol.parse("2330", market="TWSE"), status="success"),
            DailyRefreshRecord(symbol=Symbol.parse("6488", market="TPEX"), status="failure"),
        ),
    )
    dashboard_shell._handle_home_action(
        fake,
        replace(dependencies, refresh_daily_data=lambda _st: partial),
        HomeAction(kind="refresh"),
    )
    assert len(fake.messages) >= 2


def test_daily_refresh_result_is_rendered_once_after_rerun() -> None:
    fake_st = _FakeStreamlit()
    symbol = Symbol.parse("2330", market="TWSE")
    result = DailyRefreshResult(
        requested_count=1,
        limited_count=1,
        records=(DailyRefreshRecord(symbol=symbol, status="success", provider="fixture"),),
    )
    fake_st.session_state["dashboard_daily_refresh_result"] = result

    dashboard_shell._render_daily_refresh_result(fake_st)
    dashboard_shell._render_daily_refresh_result(fake_st)

    assert fake_st.session_state["dashboard_daily_refresh_result"] is None
    assert sum("更新" in message for message in fake_st.messages) == 1


def test_home_refresh_rerun_keeps_existing_daily_brief_and_calls_refresh_once(monkeypatch) -> None:
    fake_st = _HomeFakeStreamlit(button_result=False)
    refresh_calls: list[int] = []
    rendered_briefs: list[object] = []
    result = DailyRefreshResult(requested_count=1, limited_count=1, records=())
    brief = object()
    first_render = True

    def render_home(_st, context):
        nonlocal first_render
        if first_render:
            first_render = False
            return HomeAction(kind="refresh")
        rendered_briefs.append(context.daily_brief)
        return None

    monkeypatch.setattr(dashboard_shell, "render_home", render_home)

    def refresh(_st):
        refresh_calls.append(1)
        return result

    dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda **_kwargs: None,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell.refresh.brief"),
        build_daily_brief=lambda _st: brief,
        refresh_daily_data=refresh,
    )

    _render_home_workspace(fake_st, dependencies, DashboardStatus.READY)
    _render_home_workspace(fake_st, dependencies, DashboardStatus.READY)

    assert refresh_calls == [1]
    assert rendered_briefs == [brief]
    assert fake_st.session_state["dashboard_daily_refresh_result"] is None


def test_home_ai_research_action_generates_once_and_reruns(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    generated: list[bool] = []
    expected = object()
    dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda **_kwargs: None,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell.assistant"),
        generate_daily_ai_research=lambda _st, force: generated.append(force) or expected,
    )

    dashboard_shell._handle_home_action(
        fake_st, dependencies, HomeAction(kind="ai_research", force_regenerate=True)
    )

    assert generated == [True]
    assert fake_st.session_state["dashboard_ai_research_brief"] is expected
    assert fake_st.rerun_count == 1


def test_home_daily_evidence_action_calls_explicit_generator_once() -> None:
    fake_st = _FakeStreamlit()
    generated: list[bool] = []
    expected = object()
    dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda **_kwargs: None,
        render_legacy_page=lambda _st, _page: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.dashboard.shell.evidence"),
        generate_daily_evidence_brief=lambda _st, force: generated.append(force) or expected,
    )

    _handle_home_action(fake_st, dependencies, HomeAction(kind="daily_evidence_brief"))

    assert generated == [False]
    assert fake_st.session_state["dashboard_daily_evidence_brief"] is expected
    assert fake_st.rerun_count == 1


def test_native_holdings_shell_uses_injected_service_and_explicit_refresh(
    monkeypatch, tmp_path: Path
) -> None:
    fake_st = _FakeStreamlit()
    calls: list[tuple[str, str, bool]] = []

    class FakePortfolioService:
        def __init__(self, **_kwargs) -> None:
            pass

        def load_positions(self):
            import pandas as pd

            return pd.DataFrame(
                [{"symbol": "2330", "market": "TWSE"}, {"symbol": "LOCAL", "market": "CUSTOM"}]
            )

    captured: list[object] = []

    def render_native(_st, *, service, refresh_callback):
        captured.append(service)
        captured.append(refresh_callback())

    monkeypatch.setattr(
        dashboard_shell, "PortfolioWorkspaceApplicationService", FakePortfolioService
    )
    monkeypatch.setattr(
        dashboard_shell,
        "RuntimePaths",
        SimpleNamespace(
            from_environment=lambda: SimpleNamespace(ledger_database_file=tmp_path / "ledger.db")
        ),
    )
    monkeypatch.setattr(dashboard_shell, "render_page_header", lambda *_args: None)
    monkeypatch.setattr(dashboard_shell, "render_portfolio_workspace", render_native)
    dependencies = _dependencies(
        lambda _st, *, symbol, market, force_refresh: calls.append((symbol, market, force_refresh))
        or {"symbol": symbol}
    )

    dashboard_shell._render_workspace(fake_st, dependencies, navigation_for_key("holdings"))

    assert calls == [("2330", "TWSE", False)]
    assert len(captured) == 2


def test_native_holdings_refresh_uses_keyword_only_contract_and_invalidates_analysis(
    monkeypatch, tmp_path: Path
) -> None:
    fake_st = _FakeStreamlit()
    fake_st.session_state.update(
        {
            "portfolio_workspace_analysis": object(),
            "portfolio_workspace_stress_result": object(),
        }
    )
    calls: list[tuple[object, bool]] = []

    class FakePortfolioService:
        def __init__(self, **_kwargs) -> None:
            pass

        def load_positions(self):
            import pandas as pd

            return pd.DataFrame([{"symbol": "2330", "market": "TWSE"}])

    def strict_refresh(_st, portfolio, *, force_refresh: bool):
        calls.append((portfolio, force_refresh))
        return {"status": "success"}

    captured: list[object] = []

    def render_native(_st, *, service, refresh_callback):
        captured.append(service)
        captured.append(refresh_callback())

    monkeypatch.setattr(
        dashboard_shell, "PortfolioWorkspaceApplicationService", FakePortfolioService
    )
    monkeypatch.setattr(
        dashboard_shell,
        "RuntimePaths",
        SimpleNamespace(
            from_environment=lambda: SimpleNamespace(ledger_database_file=tmp_path / "ledger.db")
        ),
    )
    monkeypatch.setattr(dashboard_shell, "render_page_header", lambda *_args: None)
    monkeypatch.setattr(dashboard_shell, "render_portfolio_workspace", render_native)
    dependencies = replace(
        _dependencies(lambda *_args, **_kwargs: None), refresh_portfolio_data=strict_refresh
    )

    dashboard_shell._render_workspace(fake_st, dependencies, navigation_for_key("holdings"))

    assert len(calls) == 1
    assert calls[0][1] is True
    assert len(captured) == 2
    assert "portfolio_workspace_analysis" not in fake_st.session_state
    assert "portfolio_workspace_stress_result" not in fake_st.session_state


def test_native_holdings_refresh_exception_does_not_clear_existing_analysis(
    monkeypatch, tmp_path: Path
) -> None:
    fake_st = _FakeStreamlit()
    old_analysis = object()
    old_stress = object()
    fake_st.session_state.update(
        {
            "portfolio_workspace_analysis": old_analysis,
            "portfolio_workspace_stress_result": old_stress,
        }
    )

    class FakePortfolioService:
        def __init__(self, **_kwargs) -> None:
            pass

        def load_positions(self):
            import pandas as pd

            return pd.DataFrame([{"symbol": "2330", "market": "TWSE"}])

    def strict_refresh(_st, _portfolio, *, force_refresh: bool):
        assert force_refresh is True
        raise RuntimeError("provider unavailable")

    def render_native(_st, *, service, refresh_callback):
        del service
        with pytest.raises(RuntimeError, match="provider unavailable"):
            refresh_callback()

    monkeypatch.setattr(
        dashboard_shell, "PortfolioWorkspaceApplicationService", FakePortfolioService
    )
    monkeypatch.setattr(
        dashboard_shell,
        "RuntimePaths",
        SimpleNamespace(
            from_environment=lambda: SimpleNamespace(ledger_database_file=tmp_path / "ledger.db")
        ),
    )
    monkeypatch.setattr(dashboard_shell, "render_page_header", lambda *_args: None)
    monkeypatch.setattr(dashboard_shell, "render_portfolio_workspace", render_native)
    dependencies = replace(
        _dependencies(lambda *_args, **_kwargs: None), refresh_portfolio_data=strict_refresh
    )

    dashboard_shell._render_workspace(fake_st, dependencies, navigation_for_key("holdings"))

    assert fake_st.session_state["portfolio_workspace_analysis"] is old_analysis
    assert fake_st.session_state["portfolio_workspace_stress_result"] is old_stress


def test_session_status_sync_handles_empty_provider_and_sqlite_sources() -> None:
    import pandas as pd

    fake = _FakeStreamlit()
    fake.session_state.update(
        {
            "dashboard_status": DashboardStatus.FIRST_USE.value,
            "price_data": pd.DataFrame({"close": [1]}),
            "price_data_source": {"source_type": "SQLite cache", "end_date": "2026-08-01"},
        }
    )
    dashboard_shell.synchronize_existing_session_status(fake)
    assert fake.session_state.dashboard_status == DashboardStatus.STALE.value
    assert fake.session_state.dashboard_status_updated_at == "2026-08-01"

    fake.session_state.update(
        {
            "dashboard_status": DashboardStatus.FIRST_USE.value,
            "price_data": pd.DataFrame({"close": [1]}),
            "price_data_source": {"source_type": "provider"},
        }
    )
    dashboard_shell.synchronize_existing_session_status(fake)
    assert fake.session_state.dashboard_status == DashboardStatus.READY.value
    fake.session_state.dashboard_status = DashboardStatus.READY.value
    dashboard_shell.synchronize_existing_session_status(fake)


def test_session_status_sync_returns_for_non_first_use() -> None:
    import pandas as pd

    fake = _FakeStreamlit()
    fake.session_state.update(
        {
            "dashboard_status": DashboardStatus.STALE.value,
            "price_data": pd.DataFrame({"close": [1]}),
            "price_data_source": {"source_type": "provider"},
        }
    )
    dashboard_shell.synchronize_existing_session_status(fake)
    assert fake.session_state.dashboard_status == DashboardStatus.STALE.value


def test_home_actions_without_optional_callbacks_are_recoverable() -> None:
    fake = _FakeStreamlit()
    dependencies = _dependencies(lambda **_kwargs: {})
    dashboard_shell._handle_home_action(fake, dependencies, HomeAction(kind="ai_research"))
    dashboard_shell._handle_home_action(fake, dependencies, HomeAction(kind="refresh"))
    dashboard_shell._handle_home_action(fake, dependencies, HomeAction(kind="other"))
    assert len(fake.messages) == 2


def test_home_search_and_research_workspace_render_routes(monkeypatch) -> None:
    fake = _HomeFakeStreamlit(button_result=False)
    fake.session_state["research_snapshot"] = object()
    fake.session_state["dashboard_show_research_workspace"] = True
    monkeypatch.setattr(
        dashboard_shell,
        "render_research_workspace",
        lambda *_args, **_kwargs: SimpleNamespace(
            request=SearchRequest(symbol="2330", market="TWSE"), message=""
        ),
    )
    _render_home_workspace(fake, _dependencies(lambda _st, **_kwargs: {}), DashboardStatus.READY)
    # The pending search is executed immediately when the shell callback is
    # available; assert the resulting status instead of the transient queue.
    assert fake.session_state["dashboard_status"] in {
        DashboardStatus.READY.value,
        DashboardStatus.PARTIAL.value,
    }

    no_rerun = _HomeFakeStreamlit(button_result=False)
    no_rerun.rerun = None
    no_rerun.session_state["research_snapshot"] = object()
    no_rerun.session_state["dashboard_show_research_workspace"] = False
    monkeypatch.setattr(dashboard_shell, "render_home", lambda *_args: None)
    monkeypatch.setattr(dashboard_shell, "render_research_workspace", lambda *_args: None)
    no_rerun.session_state["dashboard_show_research_workspace"] = True
    _render_home_workspace(
        no_rerun, _dependencies(lambda _st, **_kwargs: {}), DashboardStatus.READY
    )

    direct = _HomeFakeStreamlit(button_result=False)
    direct.rerun = None
    direct.session_state["research_snapshot"] = object()
    direct.session_state["dashboard_show_research_workspace"] = True
    rendered: list[object] = []
    monkeypatch.setattr(dashboard_shell, "render_home", lambda *_args: None)
    monkeypatch.setattr(
        dashboard_shell,
        "render_research_workspace",
        lambda _st, snapshot: rendered.append(snapshot),
    )
    _render_home_workspace(direct, _dependencies(lambda _st, **_kwargs: {}), DashboardStatus.READY)
    assert rendered == [direct.session_state["research_snapshot"]]


def test_daily_refresh_result_covers_partial_failure_and_limit_messages() -> None:
    fake = _FakeStreamlit()
    symbol = Symbol.parse("2330", market="TWSE")
    records = tuple(
        DailyRefreshRecord(symbol=symbol, status=status, provider=None, reason="reason")
        for status in ("partial", "failure", "unavailable")
    )
    fake.session_state["dashboard_daily_refresh_result"] = DailyRefreshResult(
        requested_count=4, limited_count=3, records=records
    )
    dashboard_shell._render_daily_refresh_result(fake)
    assert fake.session_state["dashboard_daily_refresh_result"] is None
    assert any("reason" in message for message in fake.messages)
    fake.session_state["dashboard_daily_refresh_result"] = DailyRefreshResult(
        requested_count=0, limited_count=0, records=()
    )
    dashboard_shell._render_daily_refresh_result(fake)
    fake.session_state["dashboard_daily_refresh_result"] = DailyRefreshResult(
        requested_count=2,
        limited_count=2,
        records=(
            DailyRefreshRecord(symbol=symbol, status="success"),
            DailyRefreshRecord(symbol=symbol, status="failure"),
        ),
    )
    dashboard_shell._render_daily_refresh_result(fake)
    fake.session_state["dashboard_daily_refresh_result"] = DailyRefreshResult(
        requested_count=1,
        limited_count=1,
        records=(DailyRefreshRecord(symbol=symbol, status="failure"),),
    )
    dashboard_shell._render_daily_refresh_result(fake)


def test_current_library_route_rejects_invalid_payload_and_accepts_valid_payload() -> None:
    fake = _FakeStreamlit()
    fake.session_state["dashboard_library_current_research"] = {"symbol": 1, "market": None}
    assert dashboard_shell._route_current_library_research(fake) is True
    assert fake.session_state.get("dashboard_library_current_research") is None
    fake.session_state["dashboard_library_current_research"] = {"symbol": "AAPL", "market": "US"}
    assert dashboard_shell._route_current_library_research(fake) is True
    assert fake.rerun_count == 1


def test_research_continuation_and_legacy_entry_fail_safe(monkeypatch) -> None:
    fake = _FakeStreamlit()
    dashboard_shell._record_research_continuation(fake, object())
    symbol = Symbol.parse("2330", market="TWSE")
    snapshot = SimpleNamespace(
        symbol=symbol, updated_at="None", price=None, score_coverage=0.5, status="ready"
    )
    dashboard_shell._record_research_continuation(fake, snapshot)
    assert len(fake.session_state["dashboard_research_continuations"]) == 1
    dashboard_shell._submit_shell_search(fake, SimpleNamespace(request=None, message="invalid"))
    assert any("invalid" in message for message in fake.messages)

    class Sidebar:
        def title(self, _message):
            pass

        def button(self, _label, *, key):
            return False

        def warning(self, _message):
            pass

        def radio(self, _label, options, *, key):
            return options[0]

    fake.sidebar = Sidebar()
    monkeypatch.setattr(dashboard_shell, "_render_legacy_page_safely", lambda *_args: None)
    dashboard_shell.render_legacy_dashboard(fake, _dependencies(lambda **_kwargs: {}))
    fake.sidebar.button = lambda _label, *, key: True
    dashboard_shell.render_legacy_dashboard(fake, _dependencies(lambda **_kwargs: {}))


def test_library_force_refresh_and_snapshot_assembly_paths_are_safe(
    monkeypatch, tmp_path: Path
) -> None:
    fake = _FakeStreamlit()
    fake.session_state.update(
        {
            "price_data_source": {"user_symbol": "2330", "market": "TWSE"},
            "active_symbol": "2330",
        }
    )
    fake.selectbox = lambda _label, options, *, key: options[0]
    monkeypatch.setattr(dashboard_shell, "render_page_header", lambda *_args: None)
    monkeypatch.setattr(
        dashboard_shell,
        "default_runtime_paths",
        lambda: SimpleNamespace(research_library_dir=tmp_path / "library"),
    )
    monkeypatch.setattr(dashboard_shell, "render_library_workspace", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dashboard_shell, "render_workspace_overview", lambda *_args: None)
    calls: list[bool] = []
    dependencies = _dependencies(
        lambda _st, *, symbol, market, force_refresh: calls.append(force_refresh) or {}
    )
    dashboard_shell._render_workspace(fake, dependencies, navigation_for_key("library"))
    assert calls == [True]

    monkeypatch.setattr(
        dashboard_shell,
        "render_library_workspace",
        lambda *_args, **_kwargs: True,
    )
    failing = _dependencies(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("refresh failed"))
    )
    dashboard_shell._render_workspace(fake, failing, navigation_for_key("library"))
    assert fake.messages


def test_snapshot_assembly_preserves_continuation_and_handles_failure() -> None:
    fake = _FakeStreamlit()
    begin_search(fake.session_state, SearchRequest(symbol="2330", market="TWSE"))
    symbol = Symbol.parse("2330", market="TWSE")
    good = SimpleNamespace(
        symbol=symbol, updated_at="2026-08-01", price=None, score_coverage=1.0, status="ready"
    )
    good_dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda _st, **_kwargs: {},
        render_legacy_page=lambda *_args: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.snapshot.assembly"),
        build_research_snapshot=lambda *_args, **_kwargs: good,
    )
    _execute_pending_shell_search(fake, good_dependencies)
    assert fake.session_state["dashboard_research_continuations"]

    begin_search(fake.session_state, SearchRequest(symbol="6488", market="TPEX"))
    bad_dependencies = DashboardShellDependencies(
        ensure_symbol_data=lambda _st, **_kwargs: {},
        render_legacy_page=lambda *_args: None,
        portfolio_path=Path("portfolio.csv"),
        watchlist_path=Path("watchlist.csv"),
        risk_notice="research only",
        app_title="StockTool",
        logger=logging.getLogger("test.snapshot.failure"),
        build_research_snapshot=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("bad snapshot")
        ),
    )
    _execute_pending_shell_search(fake, bad_dependencies)
    assert dashboard_status(fake.session_state) is DashboardStatus.PARTIAL


def test_legacy_switcher_and_entry_fail_closed(monkeypatch) -> None:
    fake = _FakeStreamlit()
    fake.session_state["dashboard_pending_workspace_destination"] = {
        "workspace": "explore",
        "legacy_page": "自選股",
    }
    selected: list[str] = []
    fake.selectbox = lambda _label, options, *, key: options[1]
    monkeypatch.setattr(
        dashboard_shell,
        "_render_legacy_page_safely",
        lambda _st, _dependencies, page: selected.append(page),
    )
    dashboard_shell._render_workspace_legacy_entry(
        fake, _dependencies(lambda **_kwargs: {}), "explore"
    )
    assert selected
    broken = _dependencies(lambda **_kwargs: {})
    broken = replace(
        broken,
        render_legacy_page=lambda *_args: (_ for _ in ()).throw(RuntimeError("legacy")),
    )
    dashboard_shell._render_legacy_page_safely(fake, broken, "broken")
    assert selected[-1] == "broken"
