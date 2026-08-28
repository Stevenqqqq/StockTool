"""Small deterministic checks for launcher behavior before packaged smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

import launcher
from stock_tool.runtime_paths import RuntimePaths


def test_launcher_version_flag_uses_the_package_canonical_version(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["StockTool.exe", "--version"])

    assert launcher.main() == 0
    assert capsys.readouterr().out.strip() == "1.4.0"


def test_launcher_uses_8502_when_8501_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "_is_port_available", lambda port: port == 8502)

    assert launcher._available_port((8501, 8502)) == 8502


def test_launcher_reports_no_fallback_when_both_supported_ports_are_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(launcher, "_is_port_available", lambda _port: False)

    assert launcher._available_port((8501, 8502)) is None


def test_launcher_writes_a_readable_error_log_when_both_ports_are_busy(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    monkeypatch.setattr(sys, "argv", ["StockTool.exe"])
    monkeypatch.setattr(launcher, "default_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(launcher, "migrate_legacy_user_data", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(launcher, "_is_port_available", lambda _port: False)

    assert launcher.main() == 1

    message = capsys.readouterr().err
    assert "8501, 8502" in message
    error_logs = tuple(runtime_paths.logs_dir.glob("launcher_*_error.log"))
    assert len(error_logs) == 1
    assert "請關閉占用中的服務" in error_logs[0].read_text(encoding="utf-8")
