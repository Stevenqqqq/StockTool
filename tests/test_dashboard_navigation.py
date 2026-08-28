from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tomllib

import pandas as pd
from streamlit.testing.v1 import AppTest

from stock_tool.dashboard.navigation import (
    PRIMARY_NAVIGATION,
    LEGACY_PAGE_OPTIONS,
    all_legacy_pages,
    navigation_for_key,
    workspace_for_legacy_page,
)
from stock_tool.dashboard.pages.home import _display_optional_text as home_display_optional_text
from stock_tool.dashboard.pages.library import (
    _display_optional_text as library_display_optional_text,
)
from stock_tool.dashboard.shell import _optional_display_text
from stock_tool.dashboard.styles import DESIGN_TOKENS, STREAMLIT_THEME_CONTRACT


def test_optional_display_values_never_render_python_none_sentinel() -> None:
    for value in (None, "", "   ", "None", "none"):
        assert home_display_optional_text(value) == "無資料"
        assert library_display_optional_text(value) == "無資料"
        assert _optional_display_text(value) is None


def test_primary_navigation_has_exactly_six_fixed_workspaces() -> None:
    assert [item.key for item in PRIMARY_NAVIGATION] == [
        "home",
        "explore",
        "strategy",
        "holdings",
        "library",
        "settings",
    ]
    assert [item.label for item in PRIMARY_NAVIGATION] == [
        "研究首頁",
        "探索",
        "策略",
        "持倉",
        "研究庫",
        "設定",
    ]


def test_every_legacy_page_is_reachable_from_exactly_one_workspace() -> None:
    assert set(all_legacy_pages()) == set(LEGACY_PAGE_OPTIONS)
    assert len(all_legacy_pages()) == len(set(all_legacy_pages()))
    for page in LEGACY_PAGE_OPTIONS:
        workspace = workspace_for_legacy_page(page)
        assert workspace is not None
        assert page in navigation_for_key(workspace).legacy_pages


def test_primary_navigation_does_not_expose_legacy_pages_as_top_level_items() -> None:
    primary_labels = {item.label for item in PRIMARY_NAVIGATION}

    assert primary_labels.isdisjoint(set(LEGACY_PAGE_OPTIONS))
    assert len(PRIMARY_NAVIGATION) == 6


def test_streamlit_config_disables_implicit_multipage_sidebar_navigation() -> None:
    config = (Path(__file__).parents[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert "showSidebarNavigation = false" in config
    assert 'toolbarMode = "auto"' in config
    spec = (Path(__file__).parents[1] / "StockTool.spec").read_text(encoding="utf-8")
    assert "('.streamlit\\\\config.toml', '.streamlit')" in spec
    assert "('.streamlit\\\\', '.streamlit')" not in spec


def test_streamlit_theme_is_one_valid_dark_contract() -> None:
    config_path = Path(__file__).parents[1] / ".streamlit" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert config["theme"] == STREAMLIT_THEME_CONTRACT
    assert "light" not in config["theme"]
    assert "dark" not in config["theme"]
    assert config["theme"]["base"] == "dark"
    assert DESIGN_TOKENS["app_background"] == config["theme"]["backgroundColor"].lower()
    assert DESIGN_TOKENS["surface"] == config["theme"]["secondaryBackgroundColor"].lower()
    assert DESIGN_TOKENS["text"] == config["theme"]["textColor"].lower()


def test_streamlit_config_command_has_no_invalid_nested_theme_warning() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "streamlit", "config", "show"],
        cwd=root,
        capture_output=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + b"\n" + result.stderr

    assert result.returncode == 0
    assert b'"theme.light.base" is not a valid config option' not in output
    assert b'"theme.dark.base" is not a valid config option' not in output


def test_static_dashboard_styles_define_stable_layout_and_component_selectors() -> None:
    styles = (
        Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "styles.py"
    ).read_text(encoding="utf-8")

    assert "max-width: 1440px" in styles
    assert 'section[data-testid="stSidebar"]' in styles
    assert ".st-ui-workspace-header" in styles
    assert ".st-ui-command-panel" in styles
    assert ".st-ui-stat-grid" in styles
    assert ".st-ui-prediction-buckets" in styles
    assert 'div[data-testid="stButton"] > button' in styles
    assert 'button[data-testid="stBaseButton-primaryFormSubmit"]' in styles
    assert 'div[data-testid="stAlert"] > div' in styles
    assert "@media (max-width: 900px)" in styles
    assert "@media (max-width: 600px)" in styles
    assert "flex-wrap: wrap" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "white-space: nowrap" in styles


def test_dashboard_styles_bind_to_the_single_dark_product_theme() -> None:
    styles = (
        Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "styles.py"
    ).read_text(encoding="utf-8")

    assert "color-scheme: dark" in styles
    assert "var(--background-color)" not in styles
    assert "var(--text-color)" not in styles
    assert "var(--secondary-background-color)" not in styles
    assert DESIGN_TOKENS["app_background"] in styles
    assert DESIGN_TOKENS["surface"] in styles
    assert DESIGN_TOKENS["text"] in styles


def test_dashboard_style_tokens_have_semantic_states_and_focus_contract() -> None:
    styles = (
        Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "styles.py"
    ).read_text(encoding="utf-8")

    for token in (
        '"surface"',
        '"surface_alt"',
        '"primary"',
        '"accent"',
        '"success"',
        '"warning"',
        '"error"',
        '"radius_md"',
        '"shadow_surface"',
        '"focus_ring"',
    ):
        assert token in styles
    assert ":focus-visible" in styles
    assert "unsafe_allow_html" in styles  # static stylesheet injection only


def test_shell_opens_all_six_workspaces_and_legacy_is_an_explicit_rollback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=20)

    assert not app.exception
    assert app.radio[0].label == "主導航"
    assert app.radio[0].options == [item.label for item in PRIMARY_NAVIGATION]

    for index in range(1, 6):
        app.radio[0].set_value(app.radio[0].options[index]).run(timeout=20)
        assert not app.exception

    legacy_button = next(button for button in app.button if button.label == "開啟診斷模式")
    legacy_button.click().run(timeout=20)
    assert not app.exception
    assert app.radio[0].label == "診斷頁面"
    assert app.radio[0].options == list(LEGACY_PAGE_OPTIONS)


def test_workspace_overviews_show_action_cards_and_open_existing_entrypoints(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=20)
    expected_actions = {
        "探索": ("開始查詢", "產業 / 概念股查詢"),
        "研究庫": ("查看研究報告", "研究報告摘要"),
        "設定": ("匯入資料", "資料匯入"),
    }
    expected_actions.pop(PRIMARY_NAVIGATION[-1].label, None)

    for workspace, (action_label, legacy_page) in expected_actions.items():
        app.radio[0].set_value(workspace).run(timeout=20)
        assert not app.exception
        action = next(button for button in app.button if button.label == action_label)
        action.click().run(timeout=20)
        assert not app.exception
        switcher = next(
            selectbox for selectbox in app.selectbox if selectbox.label == "此工作區功能"
        )
        assert switcher.value == legacy_page

    app.radio[0].set_value("持倉").run(timeout=20)
    assert not app.exception
    assert any(item.value == "持倉工作區" for item in app.title)
    assert any(item.label == "加入／更新持股" for item in app.button)

    app.radio[0].set_value(PRIMARY_NAVIGATION[-1].label).run(timeout=20)
    assert not app.exception
    assert any(item.value == "設定與資料健康" for item in app.title)
    assert any(item.label == "重新檢查本機狀態" for item in app.button)


def test_explore_workspace_search_shows_explainable_result_and_current_research_action(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=20)
    app.radio[0].set_value("探索").run(timeout=20)

    query = next(item for item in app.text_input if item.label == "股票代號、公司名稱或題材")
    query.set_value("2330")
    next(item for item in app.button if item.label == "搜尋探索").click().run(timeout=20)

    assert not app.exception
    assert any("台積電" in str(item.value) for item in app.markdown)
    assert any("本機探索索引" in str(item.value) for item in app.caption)
    assert any(item.label == "以此代號研究目前資料" for item in app.button)


def test_home_reads_runtime_portfolio_and_watchlist_counts_on_first_open(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    data_dir = runtime / "data"
    data_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "MU", "00935"],
            "quantity": [1, 1, 1, 1],
            "average_cost": [1, 1, 1, 1],
            "market": ["TWSE", "US", "US", "TWSE"],
            "currency": ["TWD", "USD", "USD", "TWD"],
            "note": ["", "", "", ""],
        }
    ).to_csv(data_dir / "portfolio.csv", index=False, encoding="utf-8")
    pd.DataFrame({"symbol": ["2330", "AAPL"], "market": ["TWSE", "US"], "note": ["", ""]}).to_csv(
        data_dir / "watchlist.csv", index=False, encoding="utf-8"
    )
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"

    app = AppTest.from_file(str(app_path)).run(timeout=20)
    metrics = {metric.label: metric.value for metric in app.metric}

    assert metrics["自選股"] == "4"
    assert metrics["持股筆數"] == "4"


def test_home_primary_actions_select_the_retained_child_pages(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    data_dir = runtime / "data"
    data_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "symbol": ["2330"],
            "quantity": [1],
            "average_cost": [100],
            "market": ["TWSE"],
            "currency": ["TWD"],
            "note": [""],
        }
    ).to_csv(data_dir / "portfolio.csv", index=False, encoding="utf-8")
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=20)

    next(button for button in app.button if button.label == "查看持倉").click().run(timeout=20)

    assert app.radio[0].value == "持倉"
    assert any(item.value == "持倉工作區" for item in app.title)
    assert any(item.label == "加入／更新持股" for item in app.button)

    app.radio[0].set_value("研究首頁").run(timeout=20)
    next(button for button in app.button if button.label == "查看自選股").click().run(timeout=20)

    assert app.radio[0].value == "探索"
    switcher = next(item for item in app.selectbox if item.label == "此工作區功能")
    assert switcher.value == "自選股清單"


def test_explore_watchlist_toggle_updates_persisted_state_and_session(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=20)
    app.radio[0].set_value("探索").run(timeout=20)
    query = next(item for item in app.text_input if item.label == "股票代號、公司名稱或題材")
    query.set_value("2330")
    next(item for item in app.button if item.label == "搜尋探索").click().run(timeout=20)

    assert any(item.label == "加入自選股" for item in app.button)
    next(item for item in app.button if item.label == "加入自選股").click().run(timeout=20)
    assert any(item.label == "移除自選股" for item in app.button)

    watchlist_path = runtime / "data" / "watchlist.csv"
    saved = pd.read_csv(watchlist_path, dtype=str)
    assert ((saved["symbol"] == "2330") & (saved["market"] == "TWSE")).any()
    next(item for item in app.button if item.label == "移除自選股").click().run(timeout=20)
    assert not any(item.label == "移除自選股" for item in app.button)
    saved = pd.read_csv(watchlist_path, dtype=str)
    assert not ((saved["symbol"] == "2330") & (saved["market"] == "TWSE")).any()


def test_explore_watchlist_preloaded_identity_starts_as_remove(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    data_dir = runtime / "data"
    data_dir.mkdir(parents=True)
    pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"], "note": [""]}).to_csv(
        data_dir / "watchlist.csv", index=False, encoding="utf-8"
    )
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=20)
    app.radio[0].set_value("探索").run(timeout=20)
    query = next(item for item in app.text_input if item.label == "股票代號、公司名稱或題材")
    query.set_value("2330")
    next(item for item in app.button if item.label == "搜尋探索").click().run(timeout=20)
    assert any(item.label == "移除自選股" for item in app.button)


def test_strategy_primary_workspace_is_native_and_handles_missing_data(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=20)
    app.radio[0].set_value("策略").run(timeout=20)

    assert not app.exception
    assert any(item.value == "策略研究工作區" for item in app.subheader)
    assert any("尚未載入可用價格資料" in item.value for item in app.info)
