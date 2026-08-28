from __future__ import annotations

import socket
from types import SimpleNamespace
from pathlib import Path

import pytest

import launcher
from launcher import (
    _available_port,
    _is_port_available,
    _log_paths,
    _open_browser,
    _streamlit_command,
)


def test_streamlit_command_uses_python_module_invocation_in_source_mode() -> None:
    command = _streamlit_command(app_path=Path("src/stock_tool/dashboard/app.py"), port=8501)

    assert "-m" in command
    assert "streamlit" in command
    assert "run" in command
    assert "8501" in command


def test_available_port_returns_none_when_candidate_is_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
        sock.listen(1)
        busy_port = int(sock.getsockname()[1])

        assert not _is_port_available(busy_port)
        assert _available_port((busy_port,)) is None


def test_launcher_uses_one_explicit_ipv4_address_strategy() -> None:
    assert launcher.SERVER_HOST == "127.0.0.1"
    assert launcher._health_url(8501) == "http://127.0.0.1:8501/_stcore/health"
    assert "127.0.0.1" in _streamlit_command(app_path=Path("app.py"), port=8501)


def test_ipv4_busy_port_falls_back_without_treating_ipv6_as_the_server() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy_port = int(sock.getsockname()[1])
        assert _available_port((busy_port, busy_port + 1)) == busy_port + 1


def test_ipv6_only_listener_does_not_block_ipv4_launcher_binding() -> None:
    if not socket.has_ipv6:
        pytest.skip("IPv6 is unavailable on this host")
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind(("::1", 0))
        sock.listen(1)
        port = int(sock.getsockname()[1])
        assert _available_port((port,)) == port


def test_log_paths_are_created_under_logs_directory(tmp_path) -> None:
    stdout_log, stderr_log = _log_paths(tmp_path)

    assert stdout_log.parent == tmp_path
    assert stderr_log.parent == tmp_path
    assert stdout_log.name.startswith("streamlit_")
    assert stderr_log.name.endswith("_error.log")


def test_open_browser_prefers_windows_startfile(monkeypatch) -> None:
    if launcher.os.name != "nt":
        pytest.skip("Windows-specific browser fallback")

    opened: list[str] = []

    def fake_startfile(url: str) -> None:
        opened.append(url)

    def fail_webbrowser(*args, **kwargs) -> bool:
        raise AssertionError("webbrowser.open should not run when os.startfile works")

    monkeypatch.setattr(launcher.os, "startfile", fake_startfile)
    monkeypatch.setattr(launcher.webbrowser, "open", fail_webbrowser)

    assert _open_browser("http://localhost:8501")
    assert opened == ["http://localhost:8501"]


def test_browser_launch_is_disabled_only_by_explicit_test_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("STOCK_TOOL_NO_BROWSER", raising=False)
    assert not launcher._browser_launch_disabled()

    monkeypatch.setenv("STOCK_TOOL_NO_BROWSER", "1")
    assert launcher._browser_launch_disabled()


def test_daily_research_cli_forwards_trigger_without_streamlit(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, bool]] = []

    class FakeRunner:
        def __init__(self, paths):
            assert paths.root == tmp_path.resolve()

        def run(self, *, trigger, dry_run):
            calls.append((trigger, dry_run))
            return SimpleNamespace(
                status="skipped_dry_run",
                exit_code=20,
                record=SimpleNamespace(run_id="fixture-run"),
            )

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "HeadlessDailyResearchRunner", FakeRunner)
    assert launcher._run_daily_research_cli(["--trigger", "scheduled", "--dry-run"]) == 20
    assert calls == [("scheduled", True)]


def test_daily_research_cli_rejects_unknown_trigger() -> None:
    assert launcher._run_daily_research_cli(["--trigger", "other"]) == 40
