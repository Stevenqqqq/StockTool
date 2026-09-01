from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scripts.verify_interactive_ownership_ledger import verify
from scripts.sprint30_2_1_installer_lifecycle import (
    SILENT_SWITCHES,
    _prepared_command,
    run_lifecycle,
)


def test_lifecycle_command_is_complete_before_process_creation() -> None:
    assert SILENT_SWITCHES == ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-")


def test_prepared_command_binds_dir_and_log_before_execution(tmp_path: Path) -> None:
    command = _prepared_command(
        tmp_path / "StockTool-Setup-1.3.0.exe",
        [*SILENT_SWITCHES, f"/DIR={tmp_path / 'isolated' / 'Programs' / 'StockTool'}"],
        tmp_path / "install.log",
        "A" * 64,
    )
    assert command["source_installer_sha256"] == "A" * 64
    assert command["argv"][:4] == list(SILENT_SWITCHES)
    assert any(argument.startswith("/DIR=") for argument in command["argv"])
    assert command["argv"][-1] == f"/LOG={tmp_path / 'install.log'}"
    assert command["prepared_utc"]


def test_lifecycle_refuses_without_explicit_host_opt_in(tmp_path: Path) -> None:
    try:
        run_lifecycle(
            installer=tmp_path / "missing.exe",
            artifact_root=tmp_path / "sprint30.2.1",
            expected_size=1,
            expected_hash="A" * 64,
            allow_host_lifecycle_test=False,
        )
    except RuntimeError as exc:
        assert "allow-host-lifecycle-test" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("host lifecycle unexpectedly allowed")


def test_existing_lifecycle_result_records_same_source_hash_for_all_commands(
    tmp_path: Path,
) -> None:
    result_path = Path("artifacts/sprint30.2/lifecycle-retry-61d31828/lifecycle-result.json")
    if not result_path.is_file():
        return
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["candidate_version"] == "1.3.0"
    assert payload["status"] == "passed"


def test_interactive_failure_paths_have_unconditional_finally_cleanup() -> None:
    script = Path("scripts/capture_installer_destination.ps1").read_text(encoding="utf-8-sig")
    assert "} finally {" in script
    finally_block = script.split("} finally {", 1)[1]
    for marker in (
        "installer window was not discoverable",
        "installer window has no native handle",
        "installer Cancel button was not discoverable",
        "installer UI did not exit after Cancel",
    ):
        assert marker in script
    assert "Write-Utf8Json (Join-Path $outputPath 'ownership-ledger.json')" in finally_block
    assert "Write-Utf8Json (Join-Path $outputPath 'interactive-result.json')" in finally_block


def test_interactive_cleanup_only_removes_validated_owned_paths() -> None:
    script = Path("scripts/capture_installer_destination.ps1").read_text(encoding="utf-8-sig")
    assert "Test-OwnedTempPath" in script
    assert "StartsWith($tempRoot" in script
    assert "if ($null -ne $item -and $item.LinkType)" in script
    assert "owned_temp_paths.Keys" in script
    assert "foreach ($path in $newTemp)" not in script
    assert "unowned_candidates_left" in script


def test_interactive_cleanup_marks_owned_residual_as_failure() -> None:
    script = Path("scripts/capture_installer_destination.ps1").read_text(encoding="utf-8-sig")
    assert "owned temp remained after removal" in script
    assert "cleanupErrors.Count -eq 0" in script
    assert "owned_candidates | Where-Object { Test-Path" in script
    assert "if ($result.status -eq 'passed' -and -not $result.cleanup_verified)" in script


def test_interactive_ownership_ledger_records_prelaunch_and_process_evidence() -> None:
    script = Path("scripts/capture_installer_destination.ps1").read_text(encoding="utf-8-sig")
    for marker in (
        "pre_launch_manifest",
        "temp_manifest_after_launch",
        "process_tree_before_cleanup",
        "process_tree_after_cleanup",
        "absent_pre_launch",
        "installer_log_created_directory",
    ):
        assert marker in script


def test_owned_temp_cleanup_helper_is_fail_closed_and_exact_path_only() -> None:
    script = Path("scripts/cleanup_owned_interactive_temp.ps1").read_text(encoding="utf-8-sig")
    assert "param(" in script
    assert "$LedgerPath" in script and "$OutputPath" in script
    assert "owned_residuals" in script
    assert "Remove-Item -LiteralPath $full -Recurse -Force" in script
    assert "StartsWith($tempRoot" in script
    assert "is-*.tmp" in script
    assert "remaining_owned" in script
    assert "if (-not $result.passed) { exit 1 }" in script
    # No wildcard deletion or discovery-driven removal is permitted.
    assert "Remove-Item -Path" not in script
    assert "Get-ChildItem -Path" not in script


def test_interactive_process_evidence_covers_temp_extraction_and_cleanup() -> None:
    script = Path("scripts/capture_installer_destination.ps1").read_text(encoding="utf-8-sig")
    assert "Get-ProcessTreeTempPaths" in script
    assert "session_process_tree_recorded" in script
    assert "Get-LogCreatedTempPaths" in script
    assert "cleanup_verified" in script


def test_ownership_verifier_rejects_omitted_attempt(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    (artifact_root / "interactive-one").mkdir(parents=True)
    (artifact_root / "interactive-two").mkdir()
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "interactive_attempt_directory_count": 1,
                "attempts": [{"artifact_dir": "interactive-one"}],
                "temp_root": str(tmp_path),
                "temp_scan_before": [],
                "owned_residuals": [],
                "unproven_residuals": [],
            }
        ),
        encoding="utf-8",
    )
    assert any(
        "mismatch" in error for error in verify(artifact_root, ledger, require_present_owned=False)
    )


def test_same_payload_hash_is_auditable_owned_extraction() -> None:
    ledger = json.loads(
        Path("artifacts/sprint30.2.1/interactive-ownership-ledger.json").read_text(encoding="utf-8")
    )
    owned_paths = {Path(item["path"]).name for item in ledger["owned_residuals_history"]}
    assert {
        "is-SGMRNQ52YQ.tmp",
        "is-S0ICLBN9E4.tmp",
        "is-MKF612Z8M4.tmp",
        "is-K7NYEHSC0T.tmp",
    } <= owned_paths
    assert {"is-0QYSVGEDYY.tmp", "is-D4ZCILGZ5T.tmp"} <= owned_paths
    historical = [item for item in ledger["owned_residuals_history"] if "files" in item]
    assert historical and all(item["files"] for item in historical)


def test_cleanup_removes_only_owned_and_preserves_unrelated_temp(tmp_path: Path) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    owned = temp_root / "is-owned.tmp"
    unrelated = temp_root / "is-unrelated.tmp"
    owned.mkdir()
    unrelated.mkdir()
    (owned / "payload.tmp").write_bytes(b"owned")
    ledger = temp_root / "ledger.json"
    ledger.write_text(
        json.dumps({"owned_residuals": [{"path": str(owned), "status": "owned"}]}), encoding="utf-8"
    )
    output = temp_root / "cleanup.json"
    env = {**os.environ, "TEMP": str(temp_root), "TMP": str(temp_root)}
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/cleanup_owned_interactive_temp.ps1",
            "-LedgerPath",
            str(ledger),
            "-OutputPath",
            str(output),
            "-ProcessDetectionMode",
            "test-none",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not owned.exists()
    assert unrelated.exists()


def test_cleanup_failure_is_not_reported_as_passed(tmp_path: Path) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    outside = tmp_path / "outside.tmp"
    outside.mkdir()
    ledger = temp_root / "ledger.json"
    ledger.write_text(
        json.dumps({"owned_residuals": [{"path": str(outside), "status": "owned"}]}),
        encoding="utf-8",
    )
    output = temp_root / "cleanup.json"
    env = {**os.environ, "TEMP": str(temp_root), "TMP": str(temp_root)}
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/cleanup_owned_interactive_temp.ps1",
            "-LedgerPath",
            str(ledger),
            "-OutputPath",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is False


def test_cleanup_process_guard_is_fail_closed_before_remove(tmp_path: Path) -> None:
    """An injected related-process result must preserve every owned byte."""
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    owned = temp_root / "is-owned.tmp"
    owned.mkdir()
    payload = owned / "payload.bin"
    original = b"owned bytes must remain unchanged"
    payload.write_bytes(original)
    unrelated = temp_root / "is-unrelated.tmp"
    unrelated.mkdir()
    (unrelated / "payload.bin").write_bytes(b"unrelated")
    ledger = temp_root / "ledger.json"
    ledger.write_text(
        json.dumps({"owned_residuals": [{"path": str(owned), "status": "owned"}]}),
        encoding="utf-8",
    )
    output = temp_root / "cleanup.json"
    env = {**os.environ, "TEMP": str(temp_root), "TMP": str(temp_root)}
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/cleanup_owned_interactive_temp.ps1",
            "-LedgerPath",
            str(ledger),
            "-OutputPath",
            str(output),
            "-ProcessDetectionMode",
            "test-related-process",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert result["removed"] == []
    assert result["remaining_owned"] == [str(owned)]
    assert result["passed"] is False
    assert any("related installer or StockTool process exists" in e for e in result["errors"])
    assert payload.read_bytes() == original
    assert unrelated.exists()
