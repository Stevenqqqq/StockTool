from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

PAYLOAD_SHA = "487FE8666B93A7C2A4E39AE99460590AEB997E42595263999CE5D6E1D4E48403"
SETUP_SHA = "388A796580234EFC95F3B1C70AD4CB44BFDDC7BA0F9203BF4902B9929B136F95"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def file_records(directory: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        records.append(
            {
                "relative": str(path.relative_to(directory)).replace("/", "\\"),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return records


def main() -> int:
    root = Path("artifacts/sprint30.2.1").resolve()
    installer = Path(
        "artifacts/sprint30.2/installer/StockTool-Setup-1.3.0-internal-test.exe"
    ).resolve()
    temp_root = Path(os.environ["TEMP"]).resolve()
    attempt_dirs = sorted(
        (path for path in root.iterdir() if path.is_dir() and path.name.startswith("interactive-")),
        key=lambda path: path.name,
    )
    attempts: list[dict[str, object]] = []
    for directory in attempt_dirs:
        result_path = directory / "interactive-result.json"
        result: dict[str, object] | None = None
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                result = None
        log_path = directory / "installer-interactive.log"
        lines: list[str] = []
        if log_path.exists():
            lines = [
                line.strip()
                for line in log_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                if "Created temporary directory:" in line
            ]
        attempts.append(
            {
                "artifact_dir": directory.name,
                "result_present": result_path.exists(),
                "result_status": result.get("status") if result else "no-result",
                "session_id": result.get("session_id") if result else None,
                "started_utc": result.get("started_utc") if result else None,
                "log_path": str(log_path.resolve()),
                "log_sha256": sha256(log_path) if log_path.exists() else None,
                "created_temp_paths": [
                    {"path": line.split("Created temporary directory:", 1)[1].strip()}
                    for line in lines
                ],
            }
        )

    snapshots: list[dict[str, object]] = []
    for path in sorted(temp_root.glob("is-*.tmp")):
        snapshots.append(
            {
                "path": str(path),
                "name": path.name,
                "created_utc": dt.datetime.fromtimestamp(
                    path.stat().st_ctime, dt.timezone.utc
                ).isoformat(),
                "modified_utc": dt.datetime.fromtimestamp(
                    path.stat().st_mtime, dt.timezone.utc
                ).isoformat(),
                "files": file_records(path) if path.is_dir() else [],
            }
        )

    owned: list[dict[str, object]] = []
    unproven: list[dict[str, object]] = []
    for snapshot in snapshots:
        files = snapshot["files"]
        assert isinstance(files, list)
        hashes = {record["sha256"] for record in files if isinstance(record, dict)}
        name = snapshot["name"]
        if name in {"is-SGMRNQ52YQ.tmp", "is-S0ICLBN9E4.tmp"} and PAYLOAD_SHA in hashes:
            basis = [
                "user-confirmed current installer payload extraction",
                "exact payload size/hash match",
            ]
        elif name in {"is-MKF612Z8M4.tmp", "is-K7NYEHSC0T.tmp"} and SETUP_SHA in hashes:
            basis = [
                "user-confirmed current installer setup64 extraction",
                "exact setup64 size/hash match",
            ]
        else:
            basis = ["no surviving session-specific proof sufficient for deletion; preserve"]
        entry = {
            "path": snapshot["path"],
            "files": files,
            "status": "owned" if len(basis) > 1 else "unproven_preexisting",
            "evidence_basis": basis,
        }
        (owned if entry["status"] == "owned" else unproven).append(entry)

    output = {
        "schema_version": 2,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "artifact_root": str(root),
        "interactive_attempt_directory_count": len(attempt_dirs),
        "attempts": attempts,
        "installer": {
            "path": str(installer),
            "size_bytes": installer.stat().st_size,
            "sha256": sha256(installer),
            "payload_expected": {"size_bytes": 4427264, "sha256": PAYLOAD_SHA},
            "setup64_expected": {"size_bytes": 6144, "sha256": SETUP_SHA},
        },
        "temp_root": str(temp_root),
        "temp_scan_before": snapshots,
        "owned_residuals": owned,
        "unproven_residuals": unproven,
        "cleanup_status": "pending",
        "remaining_owned": [entry["path"] for entry in owned],
        "preserved_unproven_paths": [entry["path"] for entry in unproven],
    }
    (root / "interactive-ownership-ledger.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "attempts": len(attempt_dirs),
                "temp": len(snapshots),
                "owned": len(owned),
                "unproven": len(unproven),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
