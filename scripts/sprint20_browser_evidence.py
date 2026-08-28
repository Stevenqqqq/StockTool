"""Write an honest machine-readable browser evidence record when the surface is unavailable."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def build_blocked_result(
    candidate_hashes: dict[str, object], isolated_root: Path
) -> dict[str, object]:
    scenarios = []
    for symbol, market in (("2330", "TWSE"), ("6488", "TPEX"), ("AAPL", "US")):
        provider_symbol = {
            "TWSE": f"{symbol}.TW",
            "TPEX": f"{symbol}.TWO",
            "US": symbol,
        }[market]
        for mode in ("online-first", "offline-cache", "partial-failure"):
            scenarios.append(
                {
                    "scenario": mode,
                    "symbol": symbol,
                    "market": market,
                    "provider_symbol": provider_symbol,
                    "expected": "以真正瀏覽器完成探索搜尋與狀態呈現",
                    "observed": "瀏覽器控制面目前不可用，未以單元測試冒充產品旅程",
                    "status": "BLOCKED",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "candidate_hashes": candidate_hashes,
                    "isolated_data_root": str(isolated_root.resolve()),
                    "screenshot": None,
                    "dom_snapshot": None,
                    "active_console": None,
                    "transport_log": None,
                    "provider_metadata": None,
                    "blocker": "No browser is available in the configured browser control surface.",
                    "cleanup": {"owned_processes_stopped": True, "listeners_clear": True},
                }
            )
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_hashes": candidate_hashes,
        "isolated_data_root": str(isolated_root.resolve()),
        "scenarios": scenarios,
        "overall_passed": False,
        "status": "BLOCKED",
        "blockers": ["真正瀏覽器控制面不可用；未以 AppTest 或 fixture 取代瀏覽器證據。"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-hashes", type=Path, required=True)
    parser.add_argument("--isolated-root", type=Path, required=True)
    args = parser.parse_args()
    payload = build_blocked_result(
        json.loads(args.candidate_hashes.read_text(encoding="utf-8")),
        args.isolated_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": payload["status"], "scenarios": len(payload["scenarios"])}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
