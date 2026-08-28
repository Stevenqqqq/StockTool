"""Fail-closed isolation guard for candidate evidence runs.

The guard is deliberately small: it validates a newly-created temporary data
root, snapshots the real user-data root read-only, and delegates all candidate
startup to :mod:`browser_transport_harness`.  It never writes beneath the real
user-data root and never changes proxy, firewall, registry, or installation
state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ``python scripts/evidence_launcher.py`` puts only ``scripts`` on
# ``sys.path``; make the repository root explicit for the existing helper.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sprint20_evidence import build_manifest, compare_manifests


class IsolationGuardError(RuntimeError):
    """Raised when an evidence run would cross a data boundary."""


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


def _redact_manifest_root(manifest: dict[str, object]) -> dict[str, object]:
    """Keep file hashes while excluding the private absolute root from evidence."""

    result = dict(manifest)
    result["root"] = "canonical_localappdata_stocktool"
    return result


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _canonical_real_user_root() -> Path:
    """Return the only real-data root permitted for evidence comparisons."""

    raw_local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if not raw_local_appdata:
        raise IsolationGuardError("LOCALAPPDATA is missing or blank")
    local_appdata = Path(raw_local_appdata)
    if not local_appdata.is_absolute():
        raise IsolationGuardError("LOCALAPPDATA must be an absolute path")
    return _resolved(local_appdata / "StockTool")


def validate_data_root(
    data_root: Path,
    *,
    workspace_root: Path,
    real_user_root: Path,
    existing_test_roots: tuple[Path, ...] = (),
) -> Path:
    """Validate an absolute, non-existing, temporary evidence data root."""

    raw = str(data_root).strip()
    if not raw:
        raise IsolationGuardError("isolated data root must not be blank")
    raw_path = Path(raw)
    if not raw_path.is_absolute():
        raise IsolationGuardError("isolated data root must be absolute")
    resolved = _resolved(raw_path)
    supplied_real_root = str(real_user_root).strip()
    if not supplied_real_root:
        raise IsolationGuardError("real user-data root must not be blank")
    supplied_real_path = Path(supplied_real_root)
    if not supplied_real_path.is_absolute():
        raise IsolationGuardError("real user-data root must be absolute")
    canonical_real_root = _canonical_real_user_root()
    if _resolved(supplied_real_path) != canonical_real_root:
        raise IsolationGuardError(
            f"real user-data root must be canonical LOCALAPPDATA/StockTool: {canonical_real_root}"
        )
    forbidden = (
        _resolved(workspace_root),
        _resolved(workspace_root) / "release",
        _resolved(workspace_root) / "artifacts",
        canonical_real_root,
        *(_resolved(item) for item in existing_test_roots),
    )
    for root in forbidden:
        if resolved == root or root in resolved.parents:
            raise IsolationGuardError(f"isolated data root is forbidden: {resolved}")
    temp_root = _resolved(Path(tempfile.gettempdir()))
    if temp_root not in resolved.parents:
        raise IsolationGuardError("isolated data root must be beneath the system temp directory")
    if resolved.exists():
        raise IsolationGuardError(f"isolated data root already exists: {resolved}")
    return resolved


def validate_existing_data_root(
    data_root: Path,
    *,
    workspace_root: Path,
    real_user_root: Path,
    existing_test_roots: tuple[Path, ...] = (),
) -> Path:
    """Validate a previously-created isolated temp root for replay only."""

    raw = str(data_root).strip()
    if not raw:
        raise IsolationGuardError("isolated data root must not be blank")
    raw_path = Path(raw)
    if not raw_path.is_absolute():
        raise IsolationGuardError("isolated data root must be absolute")
    candidate = _resolved(raw_path)
    supplied_real_root = str(real_user_root).strip()
    if not supplied_real_root:
        raise IsolationGuardError("real user-data root must not be blank")
    supplied_real_path = Path(supplied_real_root)
    if not supplied_real_path.is_absolute():
        raise IsolationGuardError("real user-data root must be absolute")
    canonical_real_root = _canonical_real_user_root()
    if _resolved(supplied_real_path) != canonical_real_root:
        raise IsolationGuardError(
            f"real user-data root must be canonical LOCALAPPDATA/StockTool: {canonical_real_root}"
        )
    forbidden = (
        _resolved(workspace_root),
        _resolved(workspace_root) / "release",
        _resolved(workspace_root) / "artifacts",
        canonical_real_root,
        *(_resolved(item) for item in existing_test_roots),
    )
    for root in forbidden:
        if candidate == root or root in candidate.parents:
            raise IsolationGuardError(f"isolated data root is forbidden: {candidate}")
    temp_root = _resolved(Path(tempfile.gettempdir()))
    if temp_root not in candidate.parents:
        raise IsolationGuardError("isolated data root must be beneath the system temp directory")
    if not candidate.is_dir() or candidate.is_symlink():
        raise IsolationGuardError("replay data root must be an existing regular directory")
    return candidate


def new_data_root(
    *,
    workspace_root: Path,
    real_user_root: Path,
    existing_test_roots: tuple[Path, ...] = (),
) -> Path:
    """Generate and validate a fresh temp root without creating it."""

    parent = _resolved(Path(tempfile.gettempdir()))
    return validate_data_root(
        parent / f"stocktool-evidence-{uuid.uuid4().hex}",
        workspace_root=workspace_root,
        real_user_root=real_user_root,
        existing_test_roots=existing_test_roots,
    )


def _kill_process_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        check=False,
        capture_output=True,
    )


def _candidate_processes(candidate: Path) -> list[dict[str, object]]:
    """Return candidate-owned processes only, for cleanup evidence."""

    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -notin @('powershell.exe','pwsh.exe','python.exe','pythonw.exe') -and $_.CommandLine -like '*"
        + str(candidate).replace("'", "''")
        + "*' } | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 3"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return [{"snapshot_error": "candidate process query returned invalid JSON"}]
    return parsed if isinstance(parsed, list) else [parsed]


def _listener_count() -> int:
    script = (
        "@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalPort -in 8501,8502 }).Count"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        return int(completed.stdout.strip() or "0")
    except ValueError:
        return -1


def _cleanup_candidate(candidate: Path, *, timeout_seconds: float = 15.0) -> dict[str, object]:
    """Terminate candidate-owned processes and wait for its listeners to close."""

    deadline = time.monotonic() + timeout_seconds
    while True:
        owned = _candidate_processes(candidate)
        for item in owned:
            pid = item.get("ProcessId")
            if isinstance(pid, int):
                _kill_process_tree(pid)
        listeners = _listener_count()
        if not owned and listeners == 0:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    remaining = _candidate_processes(candidate)
    listeners_remaining = _listener_count()
    return {
        "candidate_processes_remaining": remaining,
        "listeners_remaining": listeners_remaining,
        "verified": not remaining and listeners_remaining == 0,
    }


@dataclass(frozen=True, slots=True)
class EvidenceRunResult:
    session_id: str
    status: str
    data_root: str
    before_file_count: int
    after_file_count: int
    data_diff: dict[str, object]
    cleanup: dict[str, object]
    harness_exit_code: int | None
    health_ready_seconds: float | None
    error: str | None = None


def run_evidence(
    *,
    candidate: Path,
    evidence_root: Path,
    real_user_root: Path,
    workspace_root: Path,
    mode: str = "online",
    duration_seconds: int = 2,
    timeout_seconds: int = 60,
    existing_test_roots: tuple[Path, ...] = (),
    data_root: Path | None = None,
    reuse_data_root: bool = False,
    block_hosts: tuple[str, ...] = (),
    candidate_args: tuple[str, ...] = (),
    expected_exit_codes: tuple[int, ...] = (0,),
    capture_startup_timing: bool = False,
    session_id: str | None = None,
) -> EvidenceRunResult:
    """Run the existing transport harness under an isolation guard."""

    candidate = _resolved(candidate)
    session_id = session_id or f"evidence-{uuid.uuid4().hex}"
    if not candidate.is_file() or candidate.is_symlink():
        raise IsolationGuardError("candidate must be a regular file")
    if reuse_data_root:
        if data_root is None:
            raise IsolationGuardError("--reuse-data-root requires --data-root")
        data_root = validate_existing_data_root(
            data_root,
            workspace_root=workspace_root,
            real_user_root=real_user_root,
            existing_test_roots=existing_test_roots,
        )
    else:
        data_root = new_data_root(
            workspace_root=workspace_root,
            real_user_root=real_user_root,
            existing_test_roots=existing_test_roots,
        )
    evidence_root = _resolved(evidence_root)
    if evidence_root.exists():
        raise IsolationGuardError(f"evidence root already exists: {evidence_root}")
    real_user_root = _resolved(real_user_root)
    before = build_manifest(real_user_root)
    command = [
        sys.executable,
        str(_resolved(Path(__file__).with_name("browser_transport_harness.py"))),
        "--candidate",
        str(candidate),
        "--data-root",
        str(data_root),
        "--evidence-root",
        str(evidence_root),
        "--mode",
        mode,
        "--duration-seconds",
        str(duration_seconds),
        "--session-id",
        session_id,
    ]
    if reuse_data_root:
        command.append("--reuse-data-root")
    for host in block_hosts:
        command.extend(("--block-host", host))
    for candidate_arg in candidate_args:
        command.append(f"--candidate-arg={candidate_arg}")
    for expected_exit_code in expected_exit_codes:
        command.extend(("--expected-exit-code", str(expected_exit_code)))
    process: subprocess.Popen[str] | None = None
    exit_code: int | None = None
    error: str | None = None
    environment = os.environ.copy()
    if capture_startup_timing:
        environment["STOCK_TOOL_STARTUP_TIMING_FILE"] = str(evidence_root / "startup-timing.jsonl")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(workspace_root),
            text=True,
            env=environment,
        )
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            error = "evidence harness timed out"
            _kill_process_tree(process.pid)
            process.wait(timeout=15)
    except OSError as exc:
        error = str(exc)
    finally:
        if process is not None and process.poll() is None:
            _kill_process_tree(process.pid)
            process.wait(timeout=15)
        cleanup = _cleanup_candidate(candidate)
        after = build_manifest(real_user_root)
        diff = compare_manifests(before, after)
        status = (
            "passed"
            if (exit_code == 0 and error is None and diff["zero_diff"] and cleanup["verified"])
            else "failed"
        )
        before_count = before.get("file_count")
        after_count = after.get("file_count")
        if not isinstance(before_count, int) or not isinstance(after_count, int):
            raise IsolationGuardError("real-data manifest file_count must be an integer")
        health_ready_seconds: float | None = None
        launch_metadata = evidence_root / "launch.json"
        if launch_metadata.is_file():
            try:
                raw_health_seconds = json.loads(launch_metadata.read_text(encoding="utf-8")).get(
                    "health_ready_seconds"
                )
                if isinstance(raw_health_seconds, (int, float)):
                    health_ready_seconds = float(raw_health_seconds)
            except (OSError, json.JSONDecodeError):
                health_ready_seconds = None
        result = EvidenceRunResult(
            session_id=session_id,
            status=status,
            data_root=str(data_root),
            before_file_count=before_count,
            after_file_count=after_count,
            data_diff=diff,
            cleanup=cleanup,
            harness_exit_code=exit_code,
            health_ready_seconds=health_ready_seconds,
            error=error,
        )
        evidence_root.mkdir(parents=True, exist_ok=True)
        cleanup_completed_utc = datetime.now(timezone.utc).isoformat()
        _write_json(evidence_root / "real-data-before.json", _redact_manifest_root(before))
        _write_json(evidence_root / "real-data-after.json", _redact_manifest_root(after))
        _write_json(evidence_root / "real-data-current.json", _redact_manifest_root(after))
        _write_json(evidence_root / "real-data-diff.json", diff)
        _write_json(
            evidence_root / "guard-result.json",
            {
                "session_id": result.session_id,
                "status": result.status,
                "isolated_data_root_id": data_root.name,
                "before_file_count": result.before_file_count,
                "after_file_count": result.after_file_count,
                "data_diff": result.data_diff,
                "harness_exit_code": result.harness_exit_code,
                "health_ready_seconds": result.health_ready_seconds,
                "error": result.error,
                "cleanup_verified": result.cleanup.get("verified") is True,
                "candidate_processes_remaining": result.cleanup.get(
                    "candidate_processes_remaining", []
                ),
                "listeners_remaining": result.cleanup.get("listeners_remaining", 0),
                "cleanup_completed_utc": cleanup_completed_utc,
            },
        )
        return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--real-user-root", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("online", "offline", "partial"), default="online")
    parser.add_argument("--duration-seconds", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--reuse-data-root", action="store_true")
    parser.add_argument("--block-host", action="append", default=[])
    parser.add_argument("--candidate-arg", action="append", default=[])
    parser.add_argument("--expected-exit-code", action="append", type=int, default=None)
    parser.add_argument("--session-id")
    args = parser.parse_args()
    # ``append`` must not combine an implicit 0 with an explicitly requested
    # non-zero outcome.  The default is exactly the singleton set {0}; an
    # explicit flag owns the complete accepted set.
    args.expected_exit_code = tuple(args.expected_exit_code or (0,))
    return args


def main() -> int:
    args = _parse_args()
    try:
        result = run_evidence(
            candidate=args.candidate,
            evidence_root=args.evidence_root,
            real_user_root=args.real_user_root,
            workspace_root=args.workspace_root,
            mode=args.mode,
            duration_seconds=args.duration_seconds,
            timeout_seconds=args.timeout_seconds,
            data_root=args.data_root,
            reuse_data_root=args.reuse_data_root,
            block_hosts=tuple(args.block_host),
            candidate_args=tuple(args.candidate_arg),
            expected_exit_codes=tuple(args.expected_exit_code),
            session_id=args.session_id,
        )
    except IsolationGuardError as exc:
        print(f"isolation guard rejected run: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"status": result.status, "data_diff": result.data_diff, "cleanup": result.cleanup}
        )
    )
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
