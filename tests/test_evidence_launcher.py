from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

import scripts.browser_transport_harness as transport_harness
import scripts.evidence_launcher as launcher_module
from scripts.evidence_launcher import (
    IsolationGuardError,
    new_data_root,
    run_evidence,
    validate_data_root,
    validate_existing_data_root,
)


def _roots(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    local_appdata = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    return tmp_path / "workspace", local_appdata / "StockTool"


def test_blank_data_root_is_rejected(tmp_path: Path, monkeypatch) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    with pytest.raises(IsolationGuardError):
        validate_data_root(Path(" "), workspace_root=workspace, real_user_root=real_root)


@pytest.mark.parametrize("relative", ["localappdata/StockTool", "localappdata/StockTool/child"])
def test_real_user_root_and_child_are_rejected(tmp_path: Path, monkeypatch, relative: str) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    candidate = tmp_path / relative
    with pytest.raises(IsolationGuardError):
        validate_data_root(candidate, workspace_root=workspace, real_user_root=real_root)


@pytest.mark.parametrize("relative", ["workspace", "workspace/release", "workspace/artifacts"])
def test_workspace_release_and_artifacts_are_rejected(
    tmp_path: Path, monkeypatch, relative: str
) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    with pytest.raises(IsolationGuardError):
        validate_data_root(tmp_path / relative, workspace_root=workspace, real_user_root=real_root)


def test_existing_test_root_is_rejected(tmp_path: Path, monkeypatch) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    test_root = tmp_path / "existing-test"
    with pytest.raises(IsolationGuardError):
        validate_data_root(
            test_root / "child",
            workspace_root=workspace,
            real_user_root=real_root,
            existing_test_roots=(test_root,),
        )


def test_relative_data_root_is_rejected_even_when_cwd_is_temp(tmp_path: Path, monkeypatch) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IsolationGuardError, match="absolute"):
        validate_data_root(
            Path("relative-root"), workspace_root=workspace, real_user_root=real_root
        )


def test_real_user_root_must_match_canonical_localappdata(tmp_path: Path, monkeypatch) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    with pytest.raises(IsolationGuardError, match="canonical"):
        validate_data_root(
            tmp_path / "fresh", workspace_root=workspace, real_user_root=tmp_path / "other"
        )


def test_new_temp_root_is_absolute_and_not_created(tmp_path: Path, monkeypatch) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    monkeypatch.setattr("scripts.evidence_launcher.tempfile.gettempdir", lambda: str(tmp_path))
    root = new_data_root(workspace_root=workspace, real_user_root=real_root)
    assert root.is_absolute()
    assert not root.exists()


def test_existing_isolated_root_can_be_replayed_but_boundaries_are_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, real_root = _roots(tmp_path, monkeypatch)
    isolated = Path(tempfile.gettempdir()) / f"stocktool-test-replay-{uuid.uuid4().hex}"
    isolated.mkdir()
    try:
        assert (
            validate_existing_data_root(
                isolated, workspace_root=workspace, real_user_root=real_root
            )
            == isolated.resolve()
        )
        with pytest.raises(IsolationGuardError):
            validate_existing_data_root(
                workspace, workspace_root=workspace, real_user_root=real_root
            )
        with pytest.raises(IsolationGuardError):
            validate_existing_data_root(
                Path("replay-root"), workspace_root=workspace, real_user_root=real_root
            )
    finally:
        isolated.rmdir()


def test_guard_result_schema_is_machine_readable(tmp_path: Path) -> None:
    payload = {
        "status": "failed",
        "before_file_count": 188,
        "after_file_count": 189,
        "data_diff": {"added": ["new.log"], "removed": [], "changed": [], "zero_diff": False},
        "cleanup": {"verified": True},
    }
    path = tmp_path / "guard-result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["data_diff"]["zero_diff"] is False


def test_manifest_change_fails_closed(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "StockTool.exe"
    candidate.write_bytes(b"candidate")
    real_root = tmp_path / "real"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    evidence_root = tmp_path / "evidence"
    isolated = tmp_path / "isolated"
    monkeypatch.setattr("scripts.evidence_launcher.new_data_root", lambda **_: isolated)
    manifests = iter(
        (
            {"file_count": 1, "files": []},
            {"file_count": 2, "files": [{"path": "new.log", "size_bytes": 1, "sha256": "x"}]},
        )
    )
    monkeypatch.setattr("scripts.evidence_launcher.build_manifest", lambda _root: next(manifests))

    class _Process:
        pid = 101
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr("scripts.evidence_launcher.subprocess.Popen", lambda *a, **k: _Process())
    monkeypatch.setattr("scripts.evidence_launcher._candidate_processes", lambda _candidate: [])
    monkeypatch.setattr("scripts.evidence_launcher._listener_count", lambda: 0)
    result = run_evidence(
        candidate=candidate,
        evidence_root=evidence_root,
        real_user_root=real_root,
        workspace_root=tmp_path,
    )
    assert result.status == "failed"
    assert result.data_diff["zero_diff"] is False


def test_process_exception_still_records_cleanup(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "StockTool.exe"
    candidate.write_bytes(b"candidate")
    isolated = tmp_path / "isolated"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("scripts.evidence_launcher.new_data_root", lambda **_: isolated)
    monkeypatch.setattr(
        "scripts.evidence_launcher.build_manifest",
        lambda _root: {"file_count": 188, "files": []},
    )
    monkeypatch.setattr(
        "scripts.evidence_launcher.subprocess.Popen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("launch failed")),
    )
    monkeypatch.setattr("scripts.evidence_launcher._candidate_processes", lambda _candidate: [])
    monkeypatch.setattr("scripts.evidence_launcher._listener_count", lambda: 0)
    result = run_evidence(
        candidate=candidate,
        evidence_root=tmp_path / "evidence",
        real_user_root=tmp_path / "real",
        workspace_root=tmp_path,
    )
    assert result.status == "failed"
    assert result.cleanup["verified"] is True


def test_timeout_kills_harness_and_still_cleans_up(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "StockTool.exe"
    candidate.write_bytes(b"candidate")
    isolated = tmp_path / "isolated"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("scripts.evidence_launcher.new_data_root", lambda **_: isolated)
    monkeypatch.setattr(
        "scripts.evidence_launcher.build_manifest",
        lambda _root: {"file_count": 188, "files": []},
    )
    killed: list[int] = []

    class _TimeoutProcess:
        pid = 202
        returncode = None

        def poll(self):
            return 0 if killed else None

        def wait(self, timeout=None):
            if timeout == 0:
                return None
            if not killed:
                raise __import__("subprocess").TimeoutExpired("harness", 1)
            return 1

    monkeypatch.setattr(
        "scripts.evidence_launcher.subprocess.Popen", lambda *a, **k: _TimeoutProcess()
    )
    monkeypatch.setattr(
        "scripts.evidence_launcher._kill_process_tree", lambda pid: killed.append(pid)
    )
    monkeypatch.setattr("scripts.evidence_launcher._candidate_processes", lambda _candidate: [])
    monkeypatch.setattr("scripts.evidence_launcher._listener_count", lambda: 0)
    result = run_evidence(
        candidate=candidate,
        evidence_root=tmp_path / "evidence",
        real_user_root=tmp_path / "real",
        workspace_root=tmp_path,
        timeout_seconds=1,
    )
    assert result.status == "failed"
    assert result.error == "evidence harness timed out"
    assert killed == [202]


def test_cleanup_order_and_post_cleanup_manifest_change_fail_closed(
    tmp_path: Path, monkeypatch
) -> None:
    candidate = tmp_path / "StockTool.exe"
    candidate.write_bytes(b"candidate")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    isolated = tmp_path / "isolated"
    monkeypatch.setattr("scripts.evidence_launcher.new_data_root", lambda **_: isolated)
    events: list[str] = []
    manifests = iter(
        (
            {"file_count": 188, "files": []},
            {"file_count": 189, "files": [{"path": "new.log"}]},
        )
    )

    def _manifest(_root):
        events.append("manifest")
        return next(manifests)

    monkeypatch.setattr("scripts.evidence_launcher.build_manifest", _manifest)
    monkeypatch.setattr(
        "scripts.evidence_launcher.subprocess.Popen",
        lambda *a, **k: type(
            "Process",
            (),
            {"pid": 303, "poll": lambda self: 0, "wait": lambda self, timeout=None: 0},
        )(),
    )

    def _cleanup(_candidate: Path) -> dict[str, object]:
        events.append("cleanup")
        return {"verified": True}

    monkeypatch.setattr("scripts.evidence_launcher._cleanup_candidate", _cleanup)
    result = run_evidence(
        candidate=candidate,
        evidence_root=tmp_path / "evidence",
        real_user_root=tmp_path / "StockTool",
        workspace_root=tmp_path,
    )
    assert events == ["manifest", "cleanup", "manifest"]
    assert result.status == "failed"
    assert result.data_diff["zero_diff"] is False


def test_normal_guarded_run_is_zero_diff(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "StockTool.exe"
    candidate.write_bytes(b"candidate")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    isolated = tmp_path / "isolated"
    monkeypatch.setattr("scripts.evidence_launcher.new_data_root", lambda **_: isolated)
    monkeypatch.setattr(
        "scripts.evidence_launcher.build_manifest",
        lambda _root: {"file_count": 188, "files": []},
    )
    monkeypatch.setattr(
        "scripts.evidence_launcher.subprocess.Popen",
        lambda *a, **k: type(
            "Process",
            (),
            {"pid": 404, "poll": lambda self: 0, "wait": lambda self, timeout=None: 0},
        )(),
    )
    monkeypatch.setattr("scripts.evidence_launcher._candidate_processes", lambda _candidate: [])
    monkeypatch.setattr("scripts.evidence_launcher._listener_count", lambda: 0)
    result = run_evidence(
        candidate=candidate,
        evidence_root=tmp_path / "evidence",
        real_user_root=tmp_path / "StockTool",
        workspace_root=tmp_path,
    )
    assert result.status == "passed"
    assert result.before_file_count == 188
    assert result.after_file_count == 188
    assert result.data_diff["zero_diff"] is True


def test_performance_has_no_direct_candidate_popen_fallback() -> None:
    source = Path("scripts/measure_performance.py").read_text(encoding="utf-8")
    assert "subprocess.Popen" not in source
    assert "STOCK_TOOL_EVIDENCE_GUARD" not in source
    assert "run_evidence(" in source


def test_expected_exit_code_defaults_to_only_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evidence_launcher.py",
            "--candidate",
            "candidate.exe",
            "--evidence-root",
            "evidence",
            "--real-user-root",
            "real",
        ],
    )
    args = launcher_module._parse_args()
    assert args.expected_exit_code == (0,)
    assert transport_harness._exit_code_matches(0, args.expected_exit_code)
    assert not transport_harness._exit_code_matches(10, args.expected_exit_code)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "browser_transport_harness.py",
            "--candidate",
            "candidate.exe",
            "--data-root",
            "data",
            "--evidence-root",
            "evidence",
            "--mode",
            "offline",
        ],
    )
    transport_args = transport_harness._parse_args()
    assert transport_args.expected_exit_code == (0,)


@pytest.mark.parametrize("code", [10, 20, 30, 40])
def test_expected_exit_code_explicit_value_is_exclusive(monkeypatch, code: int) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evidence_launcher.py",
            "--candidate",
            "candidate.exe",
            "--evidence-root",
            "evidence",
            "--real-user-root",
            "real",
            "--expected-exit-code",
            str(code),
        ],
    )
    assert launcher_module._parse_args().expected_exit_code == (code,)
    assert transport_harness._exit_code_matches(code, (code,))
    assert not transport_harness._exit_code_matches(0, (code,))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "browser_transport_harness.py",
            "--candidate",
            "candidate.exe",
            "--data-root",
            "data",
            "--evidence-root",
            "evidence",
            "--mode",
            "offline",
            "--expected-exit-code",
            str(code),
        ],
    )
    assert transport_harness._parse_args().expected_exit_code == (code,)


def test_explicit_multiple_exit_codes_are_the_only_accepted_set(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evidence_launcher.py",
            "--candidate",
            "candidate.exe",
            "--evidence-root",
            "evidence",
            "--real-user-root",
            "real",
            "--expected-exit-code",
            "10",
            "--expected-exit-code",
            "30",
        ],
    )
    assert launcher_module._parse_args().expected_exit_code == (10, 30)


def test_evidence_launcher_forwards_exact_exit_code_set(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "StockTool.exe"
    candidate.write_bytes(b"candidate")
    isolated = tmp_path / "isolated"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("scripts.evidence_launcher.new_data_root", lambda **_: isolated)
    monkeypatch.setattr(
        "scripts.evidence_launcher.build_manifest",
        lambda _root: {"file_count": 188, "files": []},
    )
    captured: list[list[str]] = []

    class _Process:
        pid = 505
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def _popen(command, **_kwargs):
        captured.append(command)
        return _Process()

    monkeypatch.setattr("scripts.evidence_launcher.subprocess.Popen", _popen)
    monkeypatch.setattr("scripts.evidence_launcher._candidate_processes", lambda _candidate: [])
    monkeypatch.setattr("scripts.evidence_launcher._listener_count", lambda: 0)
    result = run_evidence(
        candidate=candidate,
        evidence_root=tmp_path / "evidence",
        real_user_root=tmp_path / "StockTool",
        workspace_root=tmp_path,
        expected_exit_codes=(10, 30),
    )
    assert result.status == "passed"
    assert captured
    forwarded = [
        int(captured[0][index + 1])
        for index, value in enumerate(captured[0])
        if value == "--expected-exit-code"
    ]
    assert forwarded == [10, 30]
    assert 0 not in forwarded
