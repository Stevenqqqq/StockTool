"""Replay a disposable Task Scheduler lifecycle without running StockTool.

The script intentionally uses a unique task name and a harmless ``cmd.exe``
action.  It never creates the production task and always audits cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from stock_tool.application.daily_research_scheduler import (
    DailyScheduleSettings,
    WindowsTaskSchedulerAdapter,
)


def _state_payload(state: object) -> dict[str, object]:
    return {
        "status": getattr(state, "status", "error"),
        "detail": getattr(state, "detail", ""),
        "xml_present": bool(getattr(state, "xml", None)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/sprint26.2.1/task-scheduler-lifecycle.json"),
    )
    args = parser.parse_args()
    task_name = rf"\StockTool\Acceptance\Sprint26_2_{uuid.uuid4().hex[:12]}"
    adapter = WindowsTaskSchedulerAdapter(task_name=task_name)
    steps: list[dict[str, object]] = []
    before = adapter.query()
    cleanup_error: str | None = None
    operation_error: str | None = None
    after = before
    plan_xml = ""
    xml_path = args.output.with_name(args.output.stem + ".xml")
    try:
        if before.status != "not_installed":
            raise RuntimeError("unique acceptance task name is already installed")
        schedule_settings = DailyScheduleSettings(enabled=True)
        plan = adapter.plan(
            schedule_settings,
            # The temporary task is never run; cmd.exe is a harmless action if
            # an administrator manually starts it during diagnosis.
            stable_entry=os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
        )
        plan_xml = plan.xml
        steps.append(
            {
                "operation": "plan",
                "status": "planned",
                "task_name": plan.task_name,
                "xml_path": str(xml_path).replace("\\", "/"),
            }
        )
        created = adapter.install(schedule_settings, stable_entry=plan.stable_entry)
        steps.append({"operation": "create", **_state_payload(created)})
        queried = adapter.query()
        steps.append({"operation": "query", **_state_payload(queried)})
        disabled = adapter.disable()
        steps.append({"operation": "disable", **_state_payload(disabled)})
        enabled = adapter.enable()
        steps.append({"operation": "enable", **_state_payload(enabled)})
        removed = adapter.uninstall()
        steps.append({"operation": "delete", **_state_payload(removed)})
    except Exception as exc:
        operation_error = type(exc).__name__
        steps.append({"operation": "error", "reason": operation_error})
    finally:
        try:
            state = adapter.query()
            if state.status != "not_installed":
                adapter.uninstall()
        except Exception as exc:
            cleanup_error = type(exc).__name__
        after = adapter.query()

    cleanup_verified = after.status == "not_installed" and cleanup_error is None
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(plan_xml, encoding="utf-8", newline="\n")
    xml_hash = hashlib.sha256(xml_path.read_bytes()).hexdigest().upper()
    payload = {
        "schema_version": 1,
        "task_name": task_name,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "before": _state_payload(before),
        "steps": steps,
        "after": _state_payload(after),
        "cleanup_verified": cleanup_verified,
        "cleanup_error": cleanup_error,
        "operation_error": operation_error,
        "lifecycle_passed": operation_error is None,
        "task_executed": False,
        "real_data_touched": False,
        "production_task_touched": task_name == r"\StockTool\DailyResearchBrief",
        "task_xml": {
            "path": str(xml_path).replace("\\", "/"),
            "sha256": xml_hash,
            "size_bytes": xml_path.stat().st_size,
            "utf8_bom": xml_path.read_bytes().startswith(b"\xef\xbb\xbf"),
            "content": plan_xml,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return (
        0
        if cleanup_verified and operation_error is None and not payload["production_task_touched"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
