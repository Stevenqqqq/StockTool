"""Centralized, UI-only Dashboard state with explicit research status semantics."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stock_tool.application.research_context import (
    ResearchContext,
    ResearchContextQueue,
    ResearchContextValidationError,
)
from stock_tool.dashboard.navigation import navigation_for_key


class DashboardStatus(StrEnum):
    """User-visible state of the current research workflow."""

    FIRST_USE = "first_use"
    LOADING = "loading"
    PARTIAL = "partial"
    READY = "ready"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """A market-qualified request accepted by the Dashboard search UI."""

    symbol: str
    market: str
    force_refresh: bool = False

    @property
    def signature(self) -> str:
        """Return a stable request identifier used to prevent rerun duplication."""

        return f"{self.symbol}:{self.market}:{self.force_refresh}"


@dataclass(frozen=True, slots=True)
class SearchPreparation:
    """Validated search intent or a user-facing validation message."""

    request: SearchRequest | None
    message: str | None = None


def initialize_dashboard_state(session: MutableMapping[str, Any]) -> None:
    """Initialize UI state without overwriting existing research or user data."""

    defaults: dict[str, Any] = {
        "dashboard_active_workspace": "home",
        "dashboard_status": DashboardStatus.FIRST_USE.value,
        "dashboard_status_message": None,
        "dashboard_status_source": None,
        "dashboard_status_updated_at": None,
        "dashboard_search_request": None,
        "dashboard_pending_search": None,
        "dashboard_pending_submission_id": None,
        "dashboard_consumed_submission_id": None,
        "dashboard_submission_sequence": 0,
        "dashboard_recent_searches": [],
        "dashboard_research_continuations": [],
        "dashboard_show_research_workspace": False,
        "dashboard_daily_refresh_result": None,
        "dashboard_ai_research_brief": None,
        "dashboard_research_snapshots": {},
        "dashboard_pending_workspace_destination": None,
        "legacy_dashboard": False,
        "research_snapshot": None,
        "dashboard_research_handoff_queue": ResearchContextQueue(),
    }
    for key, value in defaults.items():
        session.setdefault(key, value)
    if not isinstance(session.get("dashboard_research_handoff_queue"), ResearchContextQueue):
        # A malformed rerun payload is discarded rather than interpreted as a
        # different workspace or security identity.
        session["dashboard_research_handoff_queue"] = ResearchContextQueue()


def enqueue_research_handoff(
    session: MutableMapping[str, Any], context: ResearchContext
) -> ResearchContext:
    """Queue one validated, one-shot cross-workspace research handoff."""

    initialize_dashboard_state(session)
    queue = session["dashboard_research_handoff_queue"]
    if not isinstance(queue, ResearchContextQueue):
        raise ResearchContextValidationError("研究接力佇列狀態無效。")
    return queue.enqueue(context)


def peek_research_handoff(session: MutableMapping[str, Any]) -> ResearchContext | None:
    """Inspect the next handoff without consuming it."""

    initialize_dashboard_state(session)
    queue = session["dashboard_research_handoff_queue"]
    return queue.peek() if isinstance(queue, ResearchContextQueue) else None


def consume_research_handoff(
    session: MutableMapping[str, Any], *, destination: str | None = None
) -> ResearchContext | None:
    """Consume one handoff only when its destination matches the current page."""

    initialize_dashboard_state(session)
    queue = session["dashboard_research_handoff_queue"]
    if not isinstance(queue, ResearchContextQueue):
        return None
    if destination is not None:
        return queue.consume_for_destination(destination)
    pending = queue.peek()
    return queue.consume_once(expected=pending) if pending is not None else None


def navigate_to_workspace(
    session: MutableMapping[str, Any],
    *,
    workspace: str,
    legacy_page: str | None = None,
) -> None:
    """Synchronize one explicit home action with all Dashboard navigation widgets.

    The primary radio owns its visible selection during the current Streamlit
    run.  A home card therefore records an explicit pending destination; the
    pending selection is applied before that radio is recreated on the next
    rerun.  A retained child page is likewise preselected through its own
    workspace-local widget state.
    """

    item = navigation_for_key(workspace)
    if legacy_page is not None and legacy_page not in item.legacy_pages:
        raise ValueError(f"{legacy_page!r} is not reachable from workspace {workspace!r}.")
    initialize_dashboard_state(session)
    session["dashboard_active_workspace"] = item.key
    if legacy_page is not None:
        session[f"workspace_{item.key}_secondary_navigation"] = legacy_page
    session["dashboard_pending_workspace_destination"] = {
        "workspace": item.key,
        "legacy_page": legacy_page,
    }


def apply_pending_workspace_navigation(session: MutableMapping[str, Any]) -> None:
    """Apply a requested workspace before Streamlit creates the primary radio."""

    pending = session.get("dashboard_pending_workspace_destination")
    if not isinstance(pending, dict):
        return
    workspace = pending.get("workspace")
    if not isinstance(workspace, str):
        session["dashboard_pending_workspace_destination"] = None
        return
    try:
        item = navigation_for_key(workspace)
    except StopIteration:
        session["dashboard_pending_workspace_destination"] = None
        return
    legacy_page = pending.get("legacy_page")
    if legacy_page is not None and legacy_page not in item.legacy_pages:
        session["dashboard_pending_workspace_destination"] = None
        return
    session["dashboard_active_workspace"] = item.key
    session["dashboard_primary_navigation"] = item.label
    if isinstance(legacy_page, str):
        session[f"workspace_{item.key}_secondary_navigation"] = legacy_page
    session["dashboard_pending_workspace_destination"] = None


def prepare_search_request(
    symbol: str, market: str | None, *, force_refresh: bool = False
) -> SearchPreparation:
    """Validate explicit UI input without inferring an ambiguous market."""

    normalized_symbol = symbol.strip().upper()
    normalized_market = (market or "").strip().upper()
    if not normalized_symbol:
        return SearchPreparation(None, "請先輸入股票代號。")
    if normalized_market not in {"TWSE", "TPEX", "US"}:
        return SearchPreparation(None, "請選擇市場後再開始研究。")
    return SearchPreparation(
        SearchRequest(
            symbol=normalized_symbol,
            market=normalized_market,
            force_refresh=force_refresh,
        )
    )


def begin_search(session: MutableMapping[str, Any], request: SearchRequest) -> None:
    """Record a new user submission and move the UI into loading state."""

    initialize_dashboard_state(session)
    submission_id = int(session["dashboard_submission_sequence"]) + 1
    session["dashboard_submission_sequence"] = submission_id
    session["dashboard_search_request"] = request
    session["dashboard_pending_search"] = request
    session["dashboard_pending_submission_id"] = submission_id
    session["dashboard_status"] = DashboardStatus.LOADING.value
    session["dashboard_status_message"] = "正在整理可用資料…"
    session["dashboard_status_source"] = None


def should_execute_pending_search(session: MutableMapping[str, Any]) -> SearchRequest | None:
    """Consume one submitted request exactly once across Streamlit reruns."""

    pending = session.get("dashboard_pending_search")
    if not isinstance(pending, SearchRequest):
        return None
    submission_id = session.get("dashboard_pending_submission_id")
    if not isinstance(submission_id, int):
        return None
    if session.get("dashboard_consumed_submission_id") == submission_id:
        return None
    session["dashboard_consumed_submission_id"] = submission_id
    session["dashboard_pending_search"] = None
    session["dashboard_pending_submission_id"] = None
    return pending


def finish_search(
    session: MutableMapping[str, Any],
    request: SearchRequest,
    *,
    status: DashboardStatus,
    message: str | None = None,
    source: str | None = None,
    updated_at: str | None = None,
) -> None:
    """Persist the safe user-visible result of one completed search."""

    if status in {DashboardStatus.FIRST_USE, DashboardStatus.LOADING}:
        raise ValueError("A completed search must use partial, ready, stale, or error status.")
    initialize_dashboard_state(session)
    session["dashboard_search_request"] = request
    session["dashboard_status"] = status.value
    session["dashboard_status_message"] = message
    session["dashboard_status_source"] = source
    session["dashboard_status_updated_at"] = updated_at
    if status is not DashboardStatus.ERROR:
        recent = [item for item in session["dashboard_recent_searches"] if item != request]
        session["dashboard_recent_searches"] = [request, *recent][:8]


def dashboard_status(session: MutableMapping[str, Any]) -> DashboardStatus:
    """Return the current status, safely falling back to first-use state."""

    initialize_dashboard_state(session)
    try:
        return DashboardStatus(str(session["dashboard_status"]))
    except ValueError:
        return DashboardStatus.FIRST_USE
