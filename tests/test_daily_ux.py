"""Presentation and navigation contracts for the bounded daily workflow change."""

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_tool.dashboard.components.research_header import render_research_header
from stock_tool.dashboard.pages import research
from stock_tool.dashboard.shell import _open_research_comparison
from stock_tool.research.library import ResearchLibrary
from test_breakout_observation import snapshot
from test_research_header_completeness import _FakeStreamlit as HeaderUI, _dossier, _profile
from test_research_workspace import _FakeStreamlit as WorkspaceUI


@pytest.mark.parametrize("code", ["3006", "6669", "6933"])
@pytest.mark.parametrize("missing", [False, True])
def test_compact_header_keeps_source_and_missing_state_before_details(code, missing):
    s = snapshot(code)
    dossier = replace(
        _dossier(gaps=("必要財報仍缺，不能當作完整研究。",)), symbol=code, market="TWSE"
    )
    s = replace(s, company_profile=replace(_profile(dossier=dossier), symbol=code))
    if missing:
        s = replace(s, price=None, price_history=None)
    before = s.price_history.copy(deep=True) if s.price_history is not None else None
    ui = HeaderUI()
    render_research_header(ui, s, compact=True)
    split = next(i for i, e in enumerate(ui.events) if e[0] == "expander")
    visible = str(ui.events[:split])
    assert "必要財報仍缺" in visible and "研究狀態" in visible
    assert "目前觀察" not in visible and "支持與反向證據" not in visible
    assert any(k == "write" and "行情來源" in str(v) for k, v in ui.events[:split])
    assert s.source_metadata.fetched_at in visible
    assert ("資料不足" in visible) if missing else ("106.00" in visible)
    if before is not None:
        pd.testing.assert_frame_equal(before, s.price_history)


@pytest.mark.parametrize("field", ["provider", "source_type", "row"])
def test_compact_header_does_not_fold_synthetic_warning(field):
    s = snapshot()
    source = replace(s.source_metadata, provider="yfinance", source_type="online")
    frame = s.price_history.copy(deep=True)
    if field == "row":
        frame["provider"] = "synthetic"
    else:
        source = replace(source, **{field: "synthetic"})
    ui = HeaderUI()
    render_research_header(
        ui, replace(s, source_metadata=source, price_history=frame), compact=True
    )
    visible = str(ui.events[: next(i for i, e in enumerate(ui.events) if e[0] == "expander")])
    assert "模擬資料／Synthetic" in visible and "模擬收盤價（測試資料）" in visible
    assert "最新可用收盤價" not in visible


def test_completion_exclusion_visible_and_full_notice_reachable():
    s = snapshot()
    notice = "收盤研究：已排除 1 筆未收盤日線；原始行情保留。當日行情須重新取得。"
    ui = HeaderUI()
    render_research_header(
        ui, replace(s, source_metadata=replace(s.source_metadata, warnings=(notice,))), compact=True
    )
    split = next(i for i, e in enumerate(ui.events) if e[0] == "expander")
    assert "已排除 1 筆未收盤日線；原始行情保留" in str(ui.events[:split])
    assert ("info", notice) in ui.events[split:]


def test_search_is_before_title_and_focus_is_inside_overview(monkeypatch, tmp_path):
    ui = WorkspaceUI()

    def search(st, **kwargs):
        st.events.append(("search", kwargs))

    monkeypatch.setattr(research, "render_global_search", search)
    research.render_research_workspace(
        ui, snapshot(), library=ResearchLibrary(tmp_path / "library")
    )
    search_i = next(i for i, e in enumerate(ui.events) if e[0] == "search")
    title_i = next(i for i, e in enumerate(ui.events) if e[0] == "title")
    tabs_i = next(i for i, e in enumerate(ui.events) if e[0] == "tabs")
    focus = [i for i, e in enumerate(ui.events) if e == ("markdown", "#### 目前觀察")]
    assert len(focus) == 1 and search_i < title_i < tabs_i < focus[0]


def test_comparison_navigation_preserves_snapshot_and_does_not_refresh():
    sentinel = snapshot()
    state = {"research_snapshot": sentinel, "price_data_source": {"provider": "cached"}}
    reruns = []
    _open_research_comparison(
        SimpleNamespace(session_state=state, rerun=lambda: reruns.append(True))
    )
    assert state["dashboard_pending_workspace_destination"] == {
        "workspace": "explore",
        "legacy_page": "自選股清單",
    }
    assert state["research_snapshot"] is sentinel
    assert state["price_data_source"] == {"provider": "cached"}
    assert len(reruns) == 1


def test_comparison_button_stops_render_after_callback(tmp_path):
    ui = WorkspaceUI()
    ui.button = lambda label, **kwargs: label == "自選股比較"
    called = []
    research.render_research_workspace(
        ui,
        snapshot(),
        library=ResearchLibrary(tmp_path / "library"),
        on_compare=lambda: called.append(True),
    )
    assert called == [True] and not ui.events


def test_only_wholly_stale_home_controls_are_hidden():
    from stock_tool.dashboard.styles import STATIC_STYLES

    assert (
        '.st-key-home_command_panel:has([data-stale="true"]):not(:has([data-stale="false"]))'
        in STATIC_STYLES
    )
    assert '[data-stale="true"] {\n  display: none' not in STATIC_STYLES


@pytest.mark.parametrize("back", [False, True])
def test_focused_watchlist_uses_existing_tool_and_can_return(monkeypatch, back):
    from stock_tool.dashboard import shell
    from stock_tool.dashboard.navigation import navigation_for_key

    calls = []
    state = {
        "workspace_explore_secondary_navigation": "自選股清單",
        "research_comparison_focus": True,
    }
    ui = SimpleNamespace(
        session_state=state,
        button=lambda *a, **k: back,
        rerun=lambda: calls.append("rerun"),
    )
    monkeypatch.setattr(shell, "render_page_header", lambda *a: None)
    monkeypatch.setattr(shell, "consume_research_handoff", lambda *a, **k: None)
    monkeypatch.setattr(
        shell, "_render_legacy_page_safely", lambda st, dep, page: calls.append(page)
    )
    monkeypatch.setattr(
        shell,
        "render_explore_workspace",
        lambda *a, **k: pytest.fail("Unrelated overview rendered"),
    )
    shell._render_workspace(ui, object(), navigation_for_key("explore"))
    assert calls == (["rerun"] if back else ["自選股清單"])
    assert state["workspace_explore_secondary_navigation"] == (
        "工作區總覽" if back else "自選股清單"
    )
