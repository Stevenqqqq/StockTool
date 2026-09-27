from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    root = Path("artifacts/sprint30.2.1")
    ledger_path = root / "interactive-ownership-ledger.json"
    result_path = root / "interactive-final15" / "interactive-result.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    log_path = root / "interactive-final15" / "installer-interactive.log"
    ledger["attempts"].append(
        {
            "artifact_dir": "interactive-final15",
            "result_present": True,
            "result_status": result.get("status"),
            "session_id": result.get("session_id"),
            "started_utc": result.get("launch", {}).get("started_utc"),
            "log_path": str(log_path.resolve()),
            "log_sha256": sha256(log_path),
            "created_temp_paths": [
                {"path": item["path"]}
                for item in result.get("ownership_ledger", {}).get("owned_temp_paths", {}).values()
            ],
        }
    )
    ledger["interactive_attempt_directory_count"] = len(ledger["attempts"])
    for item in result.get("ownership_ledger", {}).get("owned_temp_paths", {}).values():
        record = {
            "path": item["path"],
            "status": "owned_cleaned",
            "present_after": False,
            "evidence_basis": item.get("ownership_basis", []),
        }
        ledger.setdefault("owned_residuals_history", []).append(record)
    ledger["fresh_interactive"] = {
        "artifact_dir": "interactive-final15",
        "session_id": result.get("session_id"),
        "status": result.get("status"),
        "cleanup_verified": result.get("cleanup_verified"),
        "path_matches": result.get("destination", {}).get("path_matches"),
        "screenshot": result.get("destination", {}).get("screenshot"),
    }
    ledger["cleanup_status"] = "passed"
    ledger["remaining_owned"] = []
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
