# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from stock_tool.application.settings_workspace import SettingsWorkspaceApplicationService
from stock_tool.runtime_paths import RuntimePaths


def _service(
    root: Path,
    *,
    environment: dict[str, str] | None = None,
) -> SettingsWorkspaceApplicationService:
    paths = RuntimePaths(root)
    return SettingsWorkspaceApplicationService(
        paths,
        database_path=paths.processed_dir / "stock_data.sqlite",
        environment=environment or {},
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_empty_isolated_root_is_missing_without_creating_storage(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    snapshot = _service(root).inspect()

    assert snapshot.status == "missing"
    assert all(
        component.status == "missing"
        for component in snapshot.components
        if component.key != "provider_settings"
    )
    assert snapshot.digest
    assert not root.exists()


def test_healthy_snapshot_counts_components_and_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    paths = RuntimePaths(root)
    paths.data_dir.mkdir(parents=True)
    paths.settings_file.write_text(json.dumps({"theme": "system"}), encoding="utf-8")
    paths.portfolio_file.write_text(
        "symbol,market,quantity,average_cost\n2330,TWSE,1,600\n", encoding="utf-8"
    )
    paths.watchlist_file.write_text("symbol,market\n2330,TWSE\n", encoding="utf-8")
    (paths.research_library_dir / "entries").mkdir(parents=True)
    (paths.research_library_dir / "entries" / "entry.json").write_text("{}", encoding="utf-8")
    paths.ledger_database_file.parent.mkdir(parents=True)
    connection = sqlite3.connect(paths.ledger_database_file)
    connection.execute("CREATE TABLE portfolio_ledger_entries (id TEXT)")
    connection.execute("INSERT INTO portfolio_ledger_entries VALUES ('one')")
    connection.commit()
    connection.close()
    paths.processed_dir.mkdir(parents=True)
    connection = sqlite3.connect(paths.processed_dir / "stock_data.sqlite")
    connection.execute("CREATE TABLE prices (id TEXT)")
    connection.execute("INSERT INTO prices VALUES ('one')")
    connection.commit()
    connection.close()
    paths.cache_dir.mkdir(parents=True)
    (paths.cache_dir / "prices.csv").write_text("date,close\n2026-01-01,1\n", encoding="utf-8")

    service = _service(root, environment={"OPENAI_API_KEY": "SECRET", "FINMIND_TOKEN": "TOKEN"})
    first = service.inspect()
    second = service.inspect()
    statuses = {component.key: component for component in first.components}

    assert first.status == "healthy"
    assert statuses["portfolio"].count == 1
    assert statuses["watchlist"].count == 1
    assert statuses["research_library"].count == 1
    assert dict(statuses["ledger"].details)["row_count"] == "1"
    assert dict(statuses["provider_settings"].details)["presence"] == "configured"
    assert first.digest == second.digest
    manifest_text = json.dumps(first.to_manifest_dict(), ensure_ascii=False)
    assert str(root) not in manifest_text
    assert "SECRET" not in manifest_text
    assert "TOKEN" not in manifest_text


def test_corrupt_and_stale_components_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    paths = RuntimePaths(root)
    paths.data_dir.mkdir(parents=True)
    paths.settings_file.write_text("not-json", encoding="utf-8")
    paths.portfolio_file.write_text("symbol\n2330\n", encoding="utf-8")
    paths.cache_dir.mkdir(parents=True)
    stale = paths.cache_dir / "old.csv"
    stale.write_text("close\n1\n", encoding="utf-8")
    old_timestamp = datetime(2025, 12, 1, tzinfo=UTC).timestamp()
    os.utime(stale, (old_timestamp, old_timestamp))

    snapshot = _service(root).inspect()
    statuses = {component.key: component for component in snapshot.components}

    assert snapshot.status == "error"
    assert statuses["settings"].status == "error"
    assert statuses["portfolio"].status == "error"
    assert statuses["market_cache"].status == "stale"
    assert statuses["ledger"].status == "missing"
    assert statuses["sqlite"].status == "missing"
    assert not paths.ledger_database_file.exists()
    assert not (paths.processed_dir / "stock_data.sqlite").exists()


def test_provider_presence_is_boolean_only(tmp_path: Path) -> None:
    snapshot = _service(
        tmp_path / "runtime",
        environment={"OPENAI_API_KEY": "secret-value"},
    ).inspect()
    component = next(item for item in snapshot.components if item.key == "provider_settings")

    assert dict(component.details) == {"presence": "configured"}
    payload = json.dumps(snapshot.to_manifest_dict(), ensure_ascii=False)
    assert "secret-value" not in payload


def test_optional_provider_absence_does_not_lower_healthy_local_data(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    paths = RuntimePaths(root)
    paths.data_dir.mkdir(parents=True)
    paths.settings_file.write_text(json.dumps({"theme": "system"}), encoding="utf-8")
    paths.portfolio_file.write_text(
        "symbol,market,quantity,average_cost\n2330,TWSE,1,600\n", encoding="utf-8"
    )
    paths.watchlist_file.write_text("symbol,market\n2330,TWSE\n", encoding="utf-8")
    (paths.research_library_dir / "entries").mkdir(parents=True)
    (paths.research_library_dir / "entries" / "entry.json").write_text("{}", encoding="utf-8")
    paths.ledger_database_file.parent.mkdir(parents=True)
    with sqlite3.connect(paths.ledger_database_file) as connection:
        connection.execute("CREATE TABLE portfolio_ledger_entries (id TEXT)")
        connection.execute("INSERT INTO portfolio_ledger_entries VALUES ('one')")
    paths.processed_dir.mkdir(parents=True)
    with sqlite3.connect(paths.processed_dir / "stock_data.sqlite") as connection:
        connection.execute("CREATE TABLE prices (id TEXT)")
        connection.execute("INSERT INTO prices VALUES ('one')")
    paths.cache_dir.mkdir(parents=True)
    (paths.cache_dir / "prices.csv").write_text("date,close\n2026-01-01,1\n", encoding="utf-8")

    snapshot = _service(root, environment={}).inspect()
    provider = next(item for item in snapshot.components if item.key == "provider_settings")

    assert snapshot.status == "healthy"
    assert provider.status == "healthy"
    assert dict(provider.details) == {"presence": "not_configured"}
    assert provider.warnings == ()
    assert all("Provider" not in gap for gap in snapshot.gaps)
    assert all("Provider" not in warning for warning in snapshot.warnings)


def test_read_only_sqlite_connections_close_after_inspection_and_refresh(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    paths = RuntimePaths(root)
    paths.ledger_database_file.parent.mkdir(parents=True)
    paths.processed_dir.mkdir(parents=True)
    connection = sqlite3.connect(paths.ledger_database_file)
    connection.execute("CREATE TABLE portfolio_ledger_entries (id TEXT)")
    connection.commit()
    connection.close()
    connection = sqlite3.connect(paths.processed_dir / "stock_data.sqlite")
    connection.execute("CREATE TABLE prices (id TEXT)")
    connection.commit()
    connection.close()
    service = _service(root)

    service.inspect()
    service.refresh()
    ledger_moved = paths.ledger_database_file.with_suffix(".moved.sqlite")
    sqlite_moved = (paths.processed_dir / "stock_data.sqlite").with_suffix(".moved.sqlite")
    paths.ledger_database_file.replace(ledger_moved)
    (paths.processed_dir / "stock_data.sqlite").replace(sqlite_moved)
    assert ledger_moved.exists()
    assert sqlite_moved.exists()


def test_read_only_sqlite_query_error_still_closes_connection(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    paths = RuntimePaths(root)
    paths.ledger_database_file.parent.mkdir(parents=True)
    connection = sqlite3.connect(paths.ledger_database_file)
    connection.execute("CREATE TABLE portfolio_ledger_entries (id TEXT)")
    connection.commit()
    connection.close()
    service = _service(root)

    monkeypatch.setattr(
        "stock_tool.application.settings_workspace._sqlite_row_count",
        lambda *_args: (_ for _ in ()).throw(sqlite3.Error("query failed")),
    )
    snapshot = service.inspect()
    moved = paths.ledger_database_file.with_suffix(".after-error.sqlite")
    paths.ledger_database_file.replace(moved)

    assert next(item for item in snapshot.components if item.key == "ledger").status == "error"
    assert moved.exists()


def test_settings_apptest_refreshes_once_and_keeps_session_state_isolated(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app = AppTest.from_string("""
import os
import streamlit as st
from pathlib import Path
from stock_tool.application.settings_workspace import SettingsWorkspaceApplicationService
from stock_tool.dashboard.pages.settings_workspace import render_settings_workspace
from stock_tool.runtime_paths import RuntimePaths

paths = RuntimePaths(Path(os.environ["STOCK_TOOL_USER_DATA_DIR"]))
service = SettingsWorkspaceApplicationService(paths, database_path=paths.processed_dir / "stock_data.sqlite", environment={})
if "refresh_calls" not in st.session_state:
    st.session_state.refresh_calls = 0

def refresh():
    st.session_state.refresh_calls += 1
    return service.refresh()

render_settings_workspace(st, service=service, refresh_callback=refresh)
""").run(timeout=20)

    assert not app.exception
    assert any("查看本機設定與資料狀態" in str(item.value) for item in app.caption)
    assert any("缺少" in str(item.value) for item in app.markdown)
    assert app.session_state["refresh_calls"] == 0

    app.button(key="settings_workspace_refresh").click().run(timeout=20)
    assert not app.exception
    assert app.session_state["refresh_calls"] == 1
    assert not (runtime / "data" / "portfolio.csv").exists()
    assert not (runtime / "data" / "ledger" / "portfolio_ledger.sqlite").exists()


def test_settings_refresh_exception_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app = AppTest.from_string("""
import os
import streamlit as st
from pathlib import Path
from stock_tool.application.settings_workspace import SettingsWorkspaceApplicationService
from stock_tool.dashboard.pages.settings_workspace import render_settings_workspace
from stock_tool.runtime_paths import RuntimePaths

paths = RuntimePaths(Path(os.environ["STOCK_TOOL_USER_DATA_DIR"]))
service = SettingsWorkspaceApplicationService(paths, database_path=paths.processed_dir / "stock_data.sqlite", environment={})
render_settings_workspace(st, service=service, refresh_callback=lambda: (_ for _ in ()).throw(RuntimeError("offline")))
""").run(timeout=20)
    before = app.session_state["settings_workspace_snapshot"].digest

    app.button(key="settings_workspace_refresh").click().run(timeout=20)
    assert not app.exception
    assert app.session_state["settings_workspace_snapshot"].digest == before
    assert any("檢查失敗" in str(item.value) for item in app.error)


def test_settings_workspace_render_deduplication_exact_counts(tmp_path: Path, monkeypatch) -> None:
    """Verify that each missing component gap appears exactly once across the rendered page."""
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app = AppTest.from_string("""
import os
import streamlit as st
from pathlib import Path
from stock_tool.application.settings_workspace import SettingsWorkspaceApplicationService
from stock_tool.dashboard.pages.settings_workspace import render_settings_workspace
from stock_tool.runtime_paths import RuntimePaths

paths = RuntimePaths(Path(os.environ["STOCK_TOOL_USER_DATA_DIR"]))
service = SettingsWorkspaceApplicationService(paths, database_path=paths.processed_dir / "stock_data.sqlite", environment={})
render_settings_workspace(st, service=service, refresh_callback=lambda: service.refresh())
""").run(timeout=20)

    assert not app.exception
    all_texts = [str(item.value) for item in app.markdown]

    # Check that each standard component status line appears exactly once in rendered markdown
    components = [
        "本機設定",
        "持股清單",
        "自選股清單",
        "研究庫",
        "持倉帳本",
        "本機行情資料庫",
        "本機行情快取",
    ]
    for comp in components:
        matching_lines = [
            text
            for text in all_texts
            if comp in text and ("缺少資料" in text or "資料不足" in text or "新鮮度" in text)
        ]
        assert (
            len(matching_lines) == 1
        ), f"Expected component '{comp}' gap to appear exactly once, but found {len(matching_lines)}: {matching_lines}"

    # Verify no redundant duplicate warning alert blocks were rendered for component missing gaps
    warning_texts = [str(item.value) for item in app.warning]
    for comp in components:
        assert not any(
            f"{comp}：缺少" in w for w in warning_texts
        ), f"Component '{comp}' unexpectedly repeated in warning alerts: {warning_texts}"


def test_settings_workspace_notification_and_schedule_buttons(tmp_path: Path, monkeypatch) -> None:
    """Verify schedule action buttons and notification controls render and interact cleanly."""
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app = AppTest.from_string("""
import os
from datetime import datetime, timezone
import streamlit as st
from pathlib import Path
from types import SimpleNamespace
from stock_tool.application.daily_research_scheduler import DailyScheduleSettings
from stock_tool.application.settings_workspace import SettingsWorkspaceApplicationService
from stock_tool.dashboard.pages.settings_workspace import render_settings_workspace
from stock_tool.runtime_paths import RuntimePaths

paths = RuntimePaths(Path(os.environ["STOCK_TOOL_USER_DATA_DIR"]))
service = SettingsWorkspaceApplicationService(paths, database_path=paths.processed_dir / "stock_data.sqlite", environment={})

# Mock notification service
notif_service = SimpleNamespace(
    settings=lambda: SimpleNamespace(enabled=True),
    status=lambda: SimpleNamespace(capability_available=True, settings_warning=None, last_status="sent", last_reason=None),
    set_enabled=lambda val: None,
    send_test_notification=lambda: SimpleNamespace(status="sent"),
)

# Mock schedule service
schedule_service = SimpleNamespace(
    settings=lambda: DailyScheduleSettings.default(),
    state=lambda: SimpleNamespace(status="enabled"),
    latest_run=lambda: SimpleNamespace(status="completed", data_as_of="2026-08-29", output_brief_fingerprint="abc"),
    plan=lambda: SimpleNamespace(command=["python.exe", "daily_research.py"]),
    adapter=SimpleNamespace(task_name="StockToolDailyResearch"),
    now_fn=lambda: datetime(2026, 8, 29, 10, 0, 0, tzinfo=timezone.utc),
    enable=lambda: None,
    disable=lambda: None,
    run_now=lambda: SimpleNamespace(status="success"),
    uninstall=lambda: None,
)

render_settings_workspace(
    st,
    service=service,
    daily_schedule_service=schedule_service,
    daily_notification_service=notif_service,
    refresh_callback=lambda: service.refresh(),
)
""").run(timeout=20)

    assert not app.exception

    # Test daily schedule run now
    if app.button(key="daily_schedule_run_now"):
        app.button(key="daily_schedule_run_now").click().run(timeout=20)
        assert not app.exception

    # Test daily schedule uninstall warning when checkbox not checked
    if app.button(key="daily_schedule_uninstall"):
        app.button(key="daily_schedule_uninstall").click().run(timeout=20)
        assert not app.exception
        assert any("請先勾選確認方塊" in str(w.value) for w in app.warning)

    # Test daily schedule uninstall when confirmed
    if app.checkbox(key="daily_schedule_uninstall_confirm"):
        app.checkbox(key="daily_schedule_uninstall_confirm").check().run(timeout=20)
        app.button(key="daily_schedule_uninstall").click().run(timeout=20)
        assert not app.exception

    # Test notifications buttons
    if app.button(key="daily_notifications_test"):
        app.button(key="daily_notifications_test").click().run(timeout=20)
        assert not app.exception
