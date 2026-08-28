"""Stable installed StockTool entry point that dispatches through current-version.json."""

from __future__ import annotations

import subprocess
import sys
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from stock_tool.stable_entry import AuthorityError, activate_version, resolve_current_payload


def _program_root() -> Path:
    return (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )


def main(argv: list[str] | None = None) -> int:
    """Activate a copied payload or dispatch only the verified current payload."""

    _write_startup_timing("stable_python_started")
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = _program_root()
    try:
        if len(arguments) == 2 and arguments[0] == "--activate-version":
            activate_version(root, arguments[1])
            return 0
        payload = resolve_current_payload(root)
        _write_startup_timing("authority_resolved")
    except AuthorityError as exc:
        print(f"StockTool stable entry refused to launch: {exc}", file=sys.stderr)
        return 1
    if arguments == ["--version"]:
        print(payload.version)
        return 0
    try:
        _write_startup_timing("payload_spawn_requested")
        return subprocess.Popen([str(payload.executable), *arguments]).wait()
    except OSError as exc:
        print(f"StockTool stable entry failed to start payload: {exc}", file=sys.stderr)
        return 1


def _write_startup_timing(stage: str) -> None:
    """Append an opt-in timing marker without affecting normal launches."""

    target = os.environ.get("STOCK_TOOL_STARTUP_TIMING_FILE", "").strip()
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
