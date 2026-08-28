from __future__ import annotations

from stock_tool.dashboard.workspace_overview import workspace_actions


def test_workspace_overviews_expose_all_required_legacy_actions() -> None:
    assert [action.legacy_page for action in workspace_actions("explore")] == [
        "產業 / 概念股查詢",
        "股票篩選器",
        "自選股清單",
    ]
    assert [action.legacy_page for action in workspace_actions("strategy")] == ["策略回測"]
    assert [action.legacy_page for action in workspace_actions("holdings")] == [
        "投資組合管理",
        "投資組合風險",
    ]
    assert [action.legacy_page for action in workspace_actions("library")] == [
        "研究報告摘要",
        "報表下載",
    ]
    assert [action.legacy_page for action in workspace_actions("settings")] == [
        "資料匯入",
        "自動抓資料",
        None,
    ]


def test_workspace_actions_have_actionable_copy_and_no_fake_data() -> None:
    for workspace_key in ("explore", "strategy", "holdings", "library", "settings"):
        for action in workspace_actions(workspace_key):
            assert action.title
            assert action.purpose
            assert action.data_requirement
            assert action.button_label
            assert "保證" not in action.purpose
