from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_settings_schedule_controls_are_explicit_and_rerun_safe(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
from pathlib import Path
from stock_tool.application.settings_workspace import SettingsWorkspaceApplicationService
from stock_tool.application.daily_research_scheduler import (
    DailyScheduleSettings, TaskSchedulerPlan, TaskSchedulerState,
)
from stock_tool.dashboard.pages.settings_workspace import render_settings_workspace
from stock_tool.runtime_paths import RuntimePaths

paths = RuntimePaths(Path(__import__('os').environ['STOCK_TOOL_USER_DATA_DIR']))
settings_service = SettingsWorkspaceApplicationService(
    paths, database_path=paths.processed_dir / 'stock_data.sqlite', environment={}
)

class FakeSchedule:
    def __init__(self):
        self.calls = []
        from datetime import datetime, timezone
        self.now_fn = lambda: datetime.now(timezone.utc)
        self.adapter = type('Adapter', (), {'task_name': r'\\StockTool\\DailyResearchBrief'})()
    def settings(self):
        return DailyScheduleSettings()
    def state(self):
        return TaskSchedulerState('not_installed')
    def latest_run(self):
        return None
    def plan(self):
        return TaskSchedulerPlan(r'\\StockTool\\DailyResearchBrief', ('schtasks.exe', '/Create'), '<Task/>', r'C:\\StockTool.exe')
    def enable(self):
        self.calls.append('enable')
        return TaskSchedulerState('enabled')
    def disable(self):
        self.calls.append('disable')
        return TaskSchedulerState('disabled')
    def run_now(self):
        self.calls.append('run')
        return TaskSchedulerState('not_installed', 'task not installed')
    def uninstall(self):
        self.calls.append('uninstall')
        return TaskSchedulerState('not_installed')

if 'fake_schedule' not in st.session_state:
    st.session_state.fake_schedule = FakeSchedule()
render_settings_workspace(st, service=settings_service, daily_schedule_service=st.session_state.fake_schedule)
    """).run(timeout=30)
    assert not app.exception
    assert any("目前狀態：未安裝" in str(item.value) for item in app.markdown)
    assert any(item.value == "每日研究排程" for item in app.subheader)
    app.button(key="daily_schedule_run_now").click().run(timeout=30)
    assert any("尚未安裝" in item.value for item in app.warning)
    app.button(key="daily_schedule_enable").click().run(timeout=30)
    assert not app.exception
    assert app.session_state.fake_schedule.calls == ["run", "enable"]


def test_settings_notification_controls_are_opt_in_and_explicit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
from pathlib import Path
from stock_tool.application.settings_workspace import SettingsWorkspaceApplicationService
from stock_tool.application.daily_research_inbox import NotificationSettings, NotificationServiceStatus, NotificationResult
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.dashboard.pages.settings_workspace import render_settings_workspace

paths = RuntimePaths(Path(__import__('os').environ['STOCK_TOOL_USER_DATA_DIR']))
settings_service = SettingsWorkspaceApplicationService(
    paths, database_path=paths.processed_dir / 'stock_data.sqlite', environment={}
)

class FakeNotifications:
    def __init__(self):
        self.enabled = False
        self.calls = []
    def settings(self):
        return NotificationSettings(enabled=self.enabled)
    def status(self):
        return NotificationServiceStatus(self.enabled, None, None, None)
    def set_enabled(self, value):
        self.calls.append(('enabled', value))
        self.enabled = value
    def send_test_notification(self):
        self.calls.append(('test',))
        return NotificationResult('unavailable', 'Windows 通知目前不可用')

if 'fake_notifications' not in st.session_state:
    st.session_state.fake_notifications = FakeNotifications()
render_settings_workspace(
    st, service=settings_service,
    daily_notification_service=st.session_state.fake_notifications,
)
        """).run(timeout=30)
    assert not app.exception
    assert any(item.value == "每日研究通知" for item in app.subheader)
    app.button(key="daily_notifications_enable").click().run(timeout=30)
    assert app.session_state.fake_notifications.calls == [("enabled", True)]
    app.button(key="daily_notifications_test").click().run(timeout=30)
    assert app.session_state.fake_notifications.calls[-1] == ("test",)
