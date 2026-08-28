"""Replay the v1.3.0 installer in a disposable, hash-bound environment.

Every installer invocation is prepared with the complete silent command line
before process creation.  The harness never targets the formal installation or
the real StockTool user-data root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_ID = "{7ABF2B4C-4D79-4E74-B66C-9AF7E9E06568}"
DEFAULT_INSTALL_RELATIVE = Path("Programs") / "StockTool"
SILENT_SWITCHES = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-")
TMP_PATTERNS = ("is-*.tmp", "_setup64.tmp", "_unins.tmp")
SHA256_RE = re.compile(r"^[0-9A-F]{64}$")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _write_json(path: Path, payload: object) -> None:
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _real_root() -> Path:
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata or not localappdata.strip():
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return (Path(localappdata) / "StockTool").resolve()


def _default_install_root() -> Path:
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata or not localappdata.strip():
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return (Path(localappdata) / DEFAULT_INSTALL_RELATIVE).resolve()


def _uninstall_present() -> bool:
    try:
        import winreg

        key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path):
            return True
    except (FileNotFoundError, OSError):
        return False


def _processes() -> list[str]:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq StockTool.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    payload = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq StockToolPayload.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    names: list[str] = []
    for name, output in (
        ("StockTool.exe", result.stdout),
        ("StockToolPayload.exe", payload.stdout),
    ):
        if output.strip() and "INFO:" not in output:
            names.append(name)
    return names


def _listeners() -> list[int]:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    ports: list[int] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0].upper() == "TCP" and fields[3].upper() == "LISTENING":
            local = fields[1].rsplit(":", 1)[-1]
            if local.isdigit() and int(local) in {8501, 8502}:
                ports.append(int(local))
    return sorted(set(ports))


def _snapshot() -> dict[str, Any]:
    return {
        "captured_utc": _utc(),
        "uninstall_entry_present": _uninstall_present(),
        "default_install_exists": _default_install_root().exists(),
        "stocktool_processes": _processes(),
        "listeners": _listeners(),
    }


def _temp_candidates() -> dict[str, dict[str, Any]]:
    temp = Path(tempfile.gettempdir()).resolve()
    values: dict[str, dict[str, Any]] = {}
    for pattern in TMP_PATTERNS:
        for path in temp.glob(pattern):
            try:
                values[str(path.resolve())] = {
                    "path": str(path.resolve()),
                    "size_bytes": path.stat().st_size if path.is_file() else None,
                    "is_dir": path.is_dir(),
                }
            except OSError:
                continue
    return values


def _assert_safe_artifact(installer: Path, expected_size: int, expected_hash: str) -> None:
    if not installer.is_file() or installer.is_symlink():
        raise RuntimeError("installer is not a regular file")
    if isinstance(expected_size, bool) or installer.stat().st_size != expected_size:
        raise RuntimeError("installer size does not match the bound artifact")
    if (
        SHA256_RE.fullmatch(expected_hash.upper()) is None
        or _sha256(installer) != expected_hash.upper()
    ):
        raise RuntimeError("installer SHA-256 does not match the bound artifact")


def _prepared_command(
    executable: Path, args: list[str], log_path: Path, source_hash: str
) -> dict[str, Any]:
    full_args = [*args, f"/LOG={log_path}"]
    return {
        "prepared_utc": _utc(),
        "executable": str(executable.resolve()),
        "argv": full_args,
        "source_installer_sha256": source_hash,
        "log_path": str(log_path),
    }


def _run_command(command: dict[str, Any], *, cwd: Path, name: str) -> dict[str, Any]:
    started = _utc()
    process = subprocess.Popen(
        [command["executable"], *command["argv"]],
        cwd=str(cwd),
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    result = dict(command)
    result.update({"name": name, "started_utc": started, "pid": process.pid})
    exit_code = process.wait()
    result.update({"completed_utc": _utc(), "exit_code": exit_code})
    if exit_code != 0:
        raise RuntimeError(f"{name} failed with exit code {exit_code}")
    return result


def _kill_owned(process_ids: list[int]) -> None:
    for pid in process_ids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


def run_lifecycle(
    *,
    installer: Path,
    artifact_root: Path,
    expected_size: int,
    expected_hash: str,
    allow_host_lifecycle_test: bool,
) -> dict[str, Any]:
    if not allow_host_lifecycle_test:
        raise RuntimeError("refusing lifecycle without --allow-host-lifecycle-test")
    installer = installer.resolve()
    artifact_root = artifact_root.resolve()
    if not artifact_root.name.startswith("sprint30.2.1"):
        raise RuntimeError("artifact root must be a Sprint 30.2.1 directory")
    _assert_safe_artifact(installer, expected_size, expected_hash)
    before = _snapshot()
    if before["uninstall_entry_present"] or before["default_install_exists"]:
        raise RuntimeError("existing StockTool installation detected")
    if before["stocktool_processes"] or before["listeners"]:
        raise RuntimeError("StockTool process/listener preflight is not clean")

    artifact_root.mkdir(parents=True, exist_ok=True)
    run_id = f"lifecycle-{uuid.uuid4().hex[:16]}"
    evidence_root = artifact_root / "lifecycle" / run_id
    logs = evidence_root / "logs"
    logs.mkdir(parents=True, exist_ok=False)
    temp_root = Path(tempfile.mkdtemp(prefix="stocktool-s30.2.1-lifecycle-"))
    program = (temp_root / "Programs" / "StockTool").resolve()
    user_data = (temp_root / "UserData").resolve()
    user_data.mkdir(parents=True)
    sentinel = user_data / "sentinel.txt"
    sentinel.write_bytes(b"Sprint 30.2.1 isolated user-data sentinel\n")
    sentinel_hash = _sha256(sentinel)
    temp_before = _temp_candidates()
    result: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "failed",
        "installer": {
            "path": str(installer),
            "size_bytes": expected_size,
            "sha256": expected_hash.upper(),
        },
        "program_root_label": "<isolated-temp-program-root>",
        "user_data_label": "isolated-user-data",
        "commands": [],
        "snapshots": [{"name": "before", **before}],
        "temp_manifest_before": temp_before,
    }
    owned_pids: list[int] = []
    try:
        install_args = [*SILENT_SWITCHES, f"/DIR={program}"]
        for name, args, log_name in (
            ("install", install_args, "install.log"),
            ("repair", install_args, "repair.log"),
            ("upgrade_rehearsal", install_args, "upgrade-rehearsal.log"),
        ):
            log_path = logs / log_name
            command = _prepared_command(installer, args, log_path, expected_hash.upper())
            result["commands"].append({"name": name, "prepared": command})
            event = _run_command(command, cwd=artifact_root, name=name)
            result["commands"][-1]["execution"] = event
            owned_pids.append(event["pid"])
            if not program.is_dir() or not (program / "StockTool.exe").is_file():
                raise RuntimeError(f"{name} did not deploy the isolated program")
            result["snapshots"].append({"name": name, **_snapshot()})
        uninstaller = program / "unins000.exe"
        if not uninstaller.is_file():
            raise RuntimeError("installer did not produce an uninstaller")
        uninstall_log = logs / "uninstall.log"
        uninstall_command = _prepared_command(
            uninstaller,
            [*SILENT_SWITCHES],
            uninstall_log,
            expected_hash.upper(),
        )
        uninstall_command["origin_installer_sha256"] = expected_hash.upper()
        result["commands"].append({"name": "uninstall", "prepared": uninstall_command})
        event = _run_command(uninstall_command, cwd=artifact_root, name="uninstall")
        result["commands"][-1]["execution"] = event
        result["snapshots"].append({"name": "after_uninstall", **_snapshot()})
        if _sha256(sentinel) != sentinel_hash:
            raise RuntimeError("isolated user-data sentinel changed")
        result["status"] = "passed"
    finally:
        _kill_owned(owned_pids)
        if program.exists():
            shutil.rmtree(program, ignore_errors=True)
        temp_after = _temp_candidates()
        new_temp = sorted(set(temp_after) - set(temp_before))
        removed_temp: list[str] = []
        for raw_path in new_temp:
            path = Path(raw_path)
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            removed_temp.append(raw_path)
        result["temp_manifest_after"] = _temp_candidates()
        result["temp_cleanup"] = {"new_candidates": new_temp, "removed_candidates": removed_temp}
        result["cleanup"] = _snapshot()
        result["cleanup"].update(
            {
                "program_directory_absent": not program.exists(),
                "isolated_temp_root_absent": not temp_root.exists(),
                "sentinel_sha256": sentinel_hash,
            }
        )
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        result["cleanup"]["isolated_temp_root_absent"] = not temp_root.exists()
        _write_json(evidence_root / "lifecycle-result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--expected-size", type=int, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--allow-host-lifecycle-test", action="store_true")
    args = parser.parse_args()
    try:
        result = run_lifecycle(
            installer=args.installer,
            artifact_root=args.artifact_root,
            expected_size=args.expected_size,
            expected_hash=args.expected_sha256,
            allow_host_lifecycle_test=args.allow_host_lifecycle_test,
        )
    except Exception as exc:
        result = {"schema_version": 1, "status": "failed", "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
