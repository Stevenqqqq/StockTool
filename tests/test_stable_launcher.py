"""Executable stable-entry dispatch tests independent of Inno script text."""

from __future__ import annotations

from pathlib import Path

import stable_launcher
from stock_tool.stable_entry import CurrentPayload


def test_stable_launcher_reports_the_verified_authority_version(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    monkeypatch.setattr(stable_launcher, "_program_root", lambda: tmp_path)
    monkeypatch.setattr(
        stable_launcher,
        "resolve_current_payload",
        lambda _root: CurrentPayload("1.2.1", tmp_path / "versions/1.2.1/StockToolPayload.exe"),
    )

    assert stable_launcher.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "1.2.1"


def test_stable_launcher_dispatches_only_the_resolved_payload(monkeypatch, tmp_path: Path) -> None:
    payload = CurrentPayload("1.2.2", tmp_path / "versions/1.2.2/StockToolPayload.exe")
    observed: dict[str, object] = {}

    class Process:
        def wait(self) -> int:
            return 0

    monkeypatch.setattr(stable_launcher, "_program_root", lambda: tmp_path)
    monkeypatch.setattr(stable_launcher, "resolve_current_payload", lambda _root: payload)
    monkeypatch.setattr(
        stable_launcher.subprocess,
        "Popen",
        lambda command: observed.setdefault("command", command) and Process(),
    )

    assert stable_launcher.main(["--example"]) == 0
    assert observed["command"] == [str(payload.executable), "--example"]
