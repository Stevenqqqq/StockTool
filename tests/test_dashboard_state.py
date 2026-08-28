from __future__ import annotations

from stock_tool.dashboard.state import (
    DashboardStatus,
    SearchRequest,
    begin_search,
    dashboard_status,
    finish_search,
    initialize_dashboard_state,
    prepare_search_request,
    should_execute_pending_search,
)


def test_dashboard_status_covers_first_use_loading_partial_ready_stale_and_error() -> None:
    session: dict[str, object] = {}
    initialize_dashboard_state(session)

    assert dashboard_status(session) is DashboardStatus.FIRST_USE

    request = SearchRequest(symbol="2330", market="TWSE")
    begin_search(session, request)
    assert dashboard_status(session) is DashboardStatus.LOADING

    finish_search(session, request, status=DashboardStatus.PARTIAL)
    assert dashboard_status(session) is DashboardStatus.PARTIAL

    finish_search(session, request, status=DashboardStatus.READY)
    assert dashboard_status(session) is DashboardStatus.READY

    finish_search(session, request, status=DashboardStatus.STALE)
    assert dashboard_status(session) is DashboardStatus.STALE

    finish_search(session, request, status=DashboardStatus.ERROR, message="查詢暫時失敗")
    assert dashboard_status(session) is DashboardStatus.ERROR


def test_search_state_survives_page_switch_and_same_rerun_is_not_reexecuted() -> None:
    session: dict[str, object] = {}
    initialize_dashboard_state(session)
    request = SearchRequest(symbol="AAPL", market="US")

    begin_search(session, request)
    assert should_execute_pending_search(session) is request
    assert should_execute_pending_search(session) is None

    session["dashboard_active_workspace"] = "strategy"
    assert session["dashboard_search_request"] == request


def test_same_request_can_be_retried_after_an_error_without_duplicate_reruns() -> None:
    session: dict[str, object] = {}
    initialize_dashboard_state(session)
    request = SearchRequest(symbol="AAPL", market="US")

    begin_search(session, request)
    assert should_execute_pending_search(session) is request
    assert should_execute_pending_search(session) is None
    finish_search(session, request, status=DashboardStatus.ERROR, message="暫時失敗")
    assert dashboard_status(session) is DashboardStatus.ERROR
    assert session["dashboard_pending_search"] is None

    begin_search(session, request)
    assert dashboard_status(session) is DashboardStatus.LOADING
    assert should_execute_pending_search(session) is request
    assert should_execute_pending_search(session) is None
    finish_search(session, request, status=DashboardStatus.READY)

    assert dashboard_status(session) is DashboardStatus.READY
    assert session["dashboard_submission_sequence"] == 2


def test_successful_same_request_can_be_submitted_again_by_the_user() -> None:
    session: dict[str, object] = {}
    initialize_dashboard_state(session)
    request = SearchRequest(symbol="AAPL", market="US")

    begin_search(session, request)
    assert should_execute_pending_search(session) is request
    finish_search(session, request, status=DashboardStatus.READY)

    begin_search(session, request)
    assert should_execute_pending_search(session) is request
    assert session["dashboard_submission_sequence"] == 2


def test_search_request_requires_nonempty_symbol_and_explicit_market() -> None:
    empty = prepare_search_request("   ", "TWSE")
    ambiguous = prepare_search_request("2330", None)
    valid = prepare_search_request(" aapl ", "US")

    assert empty.request is None
    assert empty.message == "請先輸入股票代號。"
    assert ambiguous.request is None
    assert "選擇市場" in ambiguous.message
    assert valid.request == SearchRequest(symbol="AAPL", market="US")


def test_legacy_dashboard_is_off_by_default_and_can_be_explicitly_enabled() -> None:
    session: dict[str, object] = {}
    initialize_dashboard_state(session)

    assert session["legacy_dashboard"] is False
    session["legacy_dashboard"] = True
    assert session["legacy_dashboard"] is True


def test_research_snapshot_state_survives_workspace_switches() -> None:
    session: dict[str, object] = {}
    initialize_dashboard_state(session)
    snapshot = object()
    session["research_snapshot"] = snapshot
    session["dashboard_active_workspace"] = "strategy"
    session["dashboard_active_workspace"] = "home"

    assert session["research_snapshot"] is snapshot
