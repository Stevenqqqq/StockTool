from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify(artifact_root: Path, ledger_path: Path, *, require_present_owned: bool) -> list[str]:
    errors: list[str] = []
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"ledger unreadable: {exc}"]
    directories = sorted(
        path.name
        for path in artifact_root.iterdir()
        if path.is_dir() and path.name.startswith("interactive-")
    )
    attempts = ledger.get("attempts")
    declared = ledger.get("interactive_attempt_directory_count")
    listed = sorted(
        str(item["artifact_dir"])
        for item in attempts or []
        if isinstance(item, dict) and isinstance(item.get("artifact_dir"), str)
    )
    if not isinstance(declared, int) or declared != len(directories):
        errors.append(f"attempt count mismatch declared={declared} actual={len(directories)}")
    if listed != directories:
        errors.append("attempt directory set mismatch")
    temp_root = Path(str(ledger.get("temp_root", ""))).resolve()
    entries = ledger.get("temp_scan_before")
    current = {str(item.get("path")) for item in entries or [] if isinstance(item, dict)}
    owned_entries = [item for item in ledger.get("owned_residuals", []) if isinstance(item, dict)]
    unproven_entries = [
        item for item in ledger.get("unproven_residuals", []) if isinstance(item, dict)
    ]
    categorized = {
        str(item.get("path"))
        for item in [*owned_entries, *unproven_entries]
        if item.get("path") is not None
    }
    if current != categorized:
        errors.append("temp ownership categories do not cover exact before-scan")
    for item in owned_entries:
        path = Path(str(item.get("path"))).resolve()
        if (
            temp_root not in path.parents
            or not path.name.startswith("is-")
            or not path.name.endswith(".tmp")
        ):
            errors.append(f"owned path escapes temp: {path}")
        if require_present_owned and not path.exists():
            errors.append(f"owned residual missing before cleanup: {path}")
        if require_present_owned:
            for record in item.get("files", []):
                child = path / str(record.get("relative", ""))
                if not child.is_file():
                    errors.append(f"owned evidence file missing: {child}")
    if ledger.get("cleanup_status") == "passed" and ledger.get("remaining_owned"):
        errors.append("cleanup passed but remaining_owned is non-empty")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--require-present-owned", action="store_true")
    args = parser.parse_args()
    errors = verify(
        args.artifact_root.resolve(),
        args.ledger.resolve(),
        require_present_owned=args.require_present_owned,
    )
    result = {"passed": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
