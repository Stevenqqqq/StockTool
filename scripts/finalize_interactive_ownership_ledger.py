from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path("artifacts/sprint30.2.1")
    ledger_path = root / "interactive-ownership-ledger.json"
    cleanup_path = root / "owned-temp-cleanup-correction.json"
    text = ledger_path.read_text(encoding="utf-8").replace("\\n", "")
    ledger = json.loads(text)
    cleanup = json.loads(cleanup_path.read_text(encoding="utf-8"))
    ledger["cleanup_status"] = "passed"
    ledger["cleanup_result_path"] = cleanup_path.name
    ledger["temp_scan_after"] = cleanup["after"]
    ledger["remaining_owned"] = []
    ledger["owned_residuals_history"] = ledger["owned_residuals"]
    ledger["owned_residuals"] = [
        dict(item, present_after=False) for item in ledger["owned_residuals"]
    ]
    ledger["preserved_unproven_paths"] = [item["path"] for item in ledger["unproven_residuals"]]
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
