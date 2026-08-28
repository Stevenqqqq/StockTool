"""Headless daily-research orchestration and Windows Task Scheduler contracts.

The scheduler boundary is deliberately independent from Streamlit.  It reads
existing local inputs, delegates price refreshes to the existing provider
contract, and writes only derived scheduler/brief state under ``RuntimePaths``.
Portfolio and watchlist files are never written by this module.
"""

from __future__ import annotations

import json
import locale
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from stock_tool.application.daily_brief import DailyBriefService, ResearchContinuation
from stock_tool.application.daily_research_brief import (
    DailyResearchBrief,
    DailyResearchBriefApplicationService,
    DailyResearchBriefStore,
)
from stock_tool.application.daily_research_changes import (
    DailyResearchChangeApplicationService,
    DailyResearchChangeStore,
)
from stock_tool.application.daily_research_loop import (
    DailyResearchLoopService,
    DailyResearchSnapshotStore,
    DailyResearchSource,
)
from stock_tool.application.market_monitor import (
    MarketMonitorApplicationService,
    MarketRefreshResult,
)
from stock_tool.application.prediction_lab import (
    BenchmarkRefreshResult,
    BenchmarkRefreshService,
    build_runtime_cached_outcome_provider,
    PredictionLabApplicationService,
    PredictionOutcomeEvaluator,
    PredictionOutcomeProvider,
    PredictionLabStore,
    economic_input_fingerprint,
)
from stock_tool.data.auto_fetch import default_date_range, fetch_prices_result
from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.data.storage import PersistedPriceProvenance, SQLitePriceStorage
from stock_tool.domain.models import Market, Symbol
from stock_tool.fundamentals import load_fundamentals_csv, score_fundamentals
from stock_tool.portfolio_valuation import PortfolioValuationResult, PortfolioValuationService
from stock_tool.portfolio_management import load_portfolio
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.watchlist import build_effective_watchlist, load_watchlist

SCHEDULE_SCHEMA_VERSION = 1
RUN_RECORD_SCHEMA_VERSION = 1
DAILY_RESEARCH_TASK_NAME = r"\StockTool\DailyResearchBrief"
EXIT_SUCCESS = 0
EXIT_PARTIAL = 10
EXIT_SKIPPED = 20
EXIT_ALREADY_RUNNING = 30
EXIT_FAILED = 40
RUN_TRIGGER = Literal["scheduled", "manual"]
RUN_STATUSES = frozenset(
    {
        "success",
        "partial",
        "failed",
        "already_running",
        "skipped_disabled",
        "skipped_no_targets",
        "skipped_no_new_data",
        "skipped_missed_window",
        "skipped_dry_run",
    }
)
RUN_STAGE_NAMES = (
    "target_refresh",
    "market_refresh",
    "brief",
    "change",
    "prediction_registration",
    "prediction_outcome_evaluation",
    "notification",
)
RUN_STAGE_STATUSES = frozenset({"success", "partial", "skipped", "unavailable", "failure"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    import hashlib

    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
    """Write UTF-8 JSON and atomically publish it after fsync."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False, suffix=".tmp"
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_reason(value: object) -> str:
    """Redact provider details, credentials and absolute paths from run records."""

    text = sanitize_provider_text(str(value or "")).replace("\r", " ").replace("\n", " ")
    text = re.sub(
        r"(?i)(api[_ -]?key|token|password|credential)\s*[:=]\s*\S+", r"\1=<redacted>", text
    )
    text = re.sub(r"(?i)[A-Z]:\\[^\s;]+", "<path>", text)
    text = re.sub(r"[/\\]Users[/\\][^\s;]+", "<path>", text)
    return text[:400]


def _safe_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("unsupported timezone") from exc


def _parse_local_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("local_time must be HH:MM") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError("local_time must be HH:MM")
    return parsed


@dataclass(frozen=True, slots=True)
class DailyScheduleSettings:
    """Validated, versioned schedule configuration; disabled by default."""

    schema_version: int = SCHEDULE_SCHEMA_VERSION
    enabled: bool = False
    timezone: str = "Asia/Taipei"
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    local_time: str = "18:30"
    start_when_available: bool = True
    missed_run_grace_minutes: int = 60
    execution_time_limit_minutes: int = 30
    updated_at: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise ValueError("unsupported schedule schema")
        if self.schema_version != SCHEDULE_SCHEMA_VERSION:
            raise ValueError("unsupported schedule schema")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(self.start_when_available, bool):
            raise ValueError("start_when_available must be a boolean")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty string")
        if not isinstance(self.local_time, str):
            raise ValueError("local_time must be a string")
        if not isinstance(self.updated_at, str):
            raise ValueError("updated_at must be a string")
        if not isinstance(self.weekdays, (list, tuple)):
            raise ValueError("weekdays must be a list")
        if any(isinstance(day, bool) or not isinstance(day, int) for day in self.weekdays):
            raise ValueError("weekdays must contain integers")
        days = tuple(sorted(set(self.weekdays)))
        if any(day < 0 or day > 6 for day in days) or not days:
            raise ValueError("weekdays must contain values from 0 to 6")
        if isinstance(self.missed_run_grace_minutes, bool) or not isinstance(
            self.missed_run_grace_minutes, int
        ):
            raise ValueError("missed_run_grace_minutes must be an integer")
        if isinstance(self.execution_time_limit_minutes, bool) or not isinstance(
            self.execution_time_limit_minutes, int
        ):
            raise ValueError("execution_time_limit_minutes must be an integer")
        if not 0 <= self.missed_run_grace_minutes <= 24 * 60:
            raise ValueError("missed_run_grace_minutes is out of range")
        if not 1 <= self.execution_time_limit_minutes <= 30:
            raise ValueError("execution_time_limit_minutes must be between 1 and 30")
        object.__setattr__(self, "weekdays", days)
        object.__setattr__(self, "timezone", self.timezone.strip())
        object.__setattr__(self, "local_time", self.local_time.strip())
        _safe_timezone(self.timezone)
        _parse_local_time(self.local_time)

    @classmethod
    def default(cls, *, now: datetime | None = None) -> "DailyScheduleSettings":
        return cls(updated_at=(now or _utc_now()).astimezone(timezone.utc).isoformat())

    @property
    def local_clock(self) -> time:
        return _parse_local_time(self.local_time)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["weekdays"] = list(self.weekdays)
        return payload

    @classmethod
    def from_dict(cls, payload: object) -> "DailyScheduleSettings":
        if not isinstance(payload, Mapping):
            raise ValueError("schedule settings must be an object")
        raw_days = payload.get("weekdays", (0, 1, 2, 3, 4))
        if not isinstance(raw_days, (list, tuple)):
            raise ValueError("schedule weekdays are invalid")
        enabled = payload.get("enabled", False)
        start_when_available = payload.get("start_when_available", True)
        if not isinstance(enabled, bool) or not isinstance(start_when_available, bool):
            raise ValueError("schedule boolean values are invalid")
        return cls(
            schema_version=payload.get("schema_version", 0),
            enabled=enabled,
            timezone=payload.get("timezone", ""),
            weekdays=tuple(raw_days),
            local_time=payload.get("local_time", ""),
            start_when_available=start_when_available,
            missed_run_grace_minutes=payload.get("missed_run_grace_minutes", -1),
            execution_time_limit_minutes=payload.get("execution_time_limit_minutes", -1),
            updated_at=payload.get("updated_at", ""),
        )


class DailyScheduleSettingsStore:
    """Atomic settings store with fail-closed corrupt-state handling."""

    def __init__(self, path: str | Path, *, now_fn: Callable[[], datetime] = _utc_now) -> None:
        self.path = Path(path)
        self.now_fn = now_fn
        self.last_warning: str | None = None

    def load(self) -> DailyScheduleSettings:
        self.last_warning = None
        if not self.path.is_file():
            return DailyScheduleSettings.default(now=self.now_fn())
        try:
            return DailyScheduleSettings.from_dict(
                json.loads(self.path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
            self.last_warning = "schedule settings are unavailable or corrupt"
            return DailyScheduleSettings.default(now=self.now_fn())

    def save(self, settings: DailyScheduleSettings) -> None:
        validated = DailyScheduleSettings.from_dict(settings.to_dict())
        _atomic_json_write(self.path, validated.to_dict())


@dataclass(frozen=True, slots=True)
class ScheduledRunRecord:
    """Secret-free outcome for one manual or scheduled invocation."""

    run_id: str
    trigger: RUN_TRIGGER
    scheduled_for: str | None
    started_at: str
    completed_at: str
    status: str
    exit_code: int
    input_snapshot_hash: str | None
    output_brief_fingerprint: str | None
    data_as_of: str | None
    deterministic_fallback_used: bool
    reason: str | None
    duration_seconds: float
    schema_version: int = RUN_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_RECORD_SCHEMA_VERSION or self.status not in RUN_STATUSES:
            raise ValueError("scheduled run record is invalid")
        if self.trigger not in {"scheduled", "manual"}:
            raise ValueError("scheduled run trigger is invalid")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise ValueError("scheduled run exit code is invalid")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "ScheduledRunRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("scheduled run record must be an object")
        return cls(
            run_id=str(payload.get("run_id", "")),
            trigger=payload.get("trigger", ""),  # type: ignore[arg-type]
            scheduled_for=payload.get("scheduled_for"),  # type: ignore[arg-type]
            started_at=str(payload.get("started_at", "")),
            completed_at=str(payload.get("completed_at", "")),
            status=str(payload.get("status", "")),
            exit_code=payload.get("exit_code", -1),  # type: ignore[arg-type]
            input_snapshot_hash=payload.get("input_snapshot_hash"),  # type: ignore[arg-type]
            output_brief_fingerprint=payload.get("output_brief_fingerprint"),  # type: ignore[arg-type]
            data_as_of=payload.get("data_as_of"),  # type: ignore[arg-type]
            deterministic_fallback_used=bool(payload.get("deterministic_fallback_used", False)),
            reason=payload.get("reason"),  # type: ignore[arg-type]
            duration_seconds=float(payload.get("duration_seconds", -1)),
            schema_version=int(payload.get("schema_version", 0)),
        )


class ScheduledRunStore:
    """Immutable run records plus rebuildable latest/history projections.

    ``run-*.json`` files are the authority.  ``latest.json`` and
    ``history.json`` are projections and can be rebuilt after any publication
    failure without losing an immutable record.
    """

    def __init__(
        self,
        latest_path: str | Path,
        history_dir: str | Path,
        *,
        max_history: int = 30,
        atomic_write: Callable[[Path, Mapping[str, object]], None] = _atomic_json_write,
    ) -> None:
        self.latest_path = Path(latest_path)
        self.history_dir = Path(history_dir)
        self.history_path = self.history_dir / "history.json"
        self.max_history = max(1, int(max_history))
        self.atomic_write = atomic_write

    def _immutable_records(self) -> list[ScheduledRunRecord]:
        records: list[ScheduledRunRecord] = []
        if not self.history_dir.is_dir():
            return records
        for path in sorted(self.history_dir.glob("run-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = ScheduledRunRecord.from_dict(payload)
            except (
                OSError,
                UnicodeDecodeError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise ValueError("immutable scheduled run record is corrupt") from exc
            records.append(record)
        return sorted(records, key=lambda item: (item.completed_at, item.run_id))

    def _projection_payloads(
        self, records: Sequence[ScheduledRunRecord]
    ) -> tuple[dict[str, object], ScheduledRunRecord | None]:
        recent = records[-self.max_history :]
        history = {
            "schema_version": RUN_RECORD_SCHEMA_VERSION,
            "runs": [
                {
                    "run_id": record.run_id,
                    "status": record.status,
                    "completed_at": record.completed_at,
                }
                for record in recent
            ],
        }
        return history, (records[-1] if records else None)

    def _publish_projections(self, records: Sequence[ScheduledRunRecord]) -> None:
        history, latest = self._projection_payloads(records)
        self.atomic_write(self.history_path, history)
        if latest is not None:
            self.atomic_write(self.latest_path, latest.to_dict())

    def rebuild_projections(self) -> None:
        """Rebuild derived files from immutable records after a fault."""

        records = self._immutable_records()
        self._publish_projections(records)

    def records(self) -> tuple[ScheduledRunRecord, ...]:
        return tuple(self._immutable_records())

    def load_history(self) -> tuple[ScheduledRunRecord, ...]:
        return tuple(self._immutable_records()[-self.max_history :])

    def has_scheduled_for(self, scheduled_for: str) -> bool:
        return any(
            record.trigger == "scheduled" and record.scheduled_for == scheduled_for
            for record in self._immutable_records()
        )

    def load_latest(self) -> ScheduledRunRecord | None:
        records = self._immutable_records()
        return records[-1] if records else None

    def save(self, record: ScheduledRunRecord) -> None:
        validated = ScheduledRunRecord.from_dict(record.to_dict())
        immutable_path = self.history_dir / f"{validated.run_id}.json"
        if immutable_path.exists():
            raise FileExistsError("scheduled run record already exists")
        self.atomic_write(immutable_path, validated.to_dict())
        records = self._immutable_records()
        self._publish_projections(records)


class ScheduleLockError(RuntimeError):
    """Raised when the daily runner cannot safely acquire its single-run lock."""


def _default_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class ScheduleRunLock:
    """Exclusive lock that only removes stale locks whose owner is gone."""

    def __init__(
        self, path: str | Path, *, pid_alive: Callable[[int], bool] = _default_pid_alive
    ) -> None:
        self.path = Path(path)
        self.pid_alive = pid_alive
        self._owned = False

    def acquire(self, *, run_id: str, now: datetime) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "pid": os.getpid(),
            "run_id": run_id,
            "started_at": now.isoformat(),
        }
        for attempt in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(descriptor, (_canonical_json(payload) + "\n").encode("utf-8"))
                finally:
                    os.close(descriptor)
                self._owned = True
                return
            except FileExistsError:
                try:
                    current = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(current.get("pid", 0)) if isinstance(current, Mapping) else 0
                except (
                    OSError,
                    UnicodeDecodeError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ) as exc:
                    raise ScheduleLockError(
                        "schedule lock is malformed; refusing to remove it"
                    ) from exc
                if self.pid_alive(pid):
                    raise ScheduleLockError("daily research runner is already running")
                if attempt == 0:
                    self.path.unlink(missing_ok=False)
                    continue
                raise ScheduleLockError("stale schedule lock could not be replaced safely")

    def release(self) -> None:
        if self._owned:
            self.path.unlink(missing_ok=True)
            self._owned = False

    def __enter__(self) -> "ScheduleRunLock":
        if not self._owned:
            raise ScheduleLockError("schedule lock must be acquired before entering")
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class TaskSchedulerState:
    status: Literal["not_installed", "disabled", "enabled", "error"]
    detail: str = ""
    xml: str | None = None


class CommandRunner(Protocol):
    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


def _resolve_schtasks_executable() -> str:
    """Resolve the Windows scheduler binary independently of frozen PATH state."""

    roots: list[str] = []
    for variable in ("SystemRoot", "WINDIR"):
        value = os.environ.get(variable, "").strip()
        if value and value.casefold() not in {item.casefold() for item in roots}:
            roots.append(value)
    for root in roots:
        candidate = Path(root) / "System32" / "schtasks.exe"
        if candidate.is_file():
            return str(candidate)
    resolved = shutil.which("schtasks.exe")
    return resolved or "schtasks.exe"


def _windows_command_encoding() -> str:
    """Use the active Windows code page so localized task errors remain parseable."""

    if os.name == "nt":
        return "mbcs"
    return locale.getpreferredencoding(False) or "utf-8"


def _subprocess_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    values = list(command)
    # Frozen launches may not inherit the interactive shell PATH. Resolve the
    # scheduler binary explicitly while preserving the injectable command shape.
    if values and str(values[0]).lower() == "schtasks.exe":
        values[0] = _resolve_schtasks_executable()
    return subprocess.run(
        values,
        capture_output=True,
        text=True,
        encoding=_windows_command_encoding(),
        errors="replace",
        check=False,
    )


def _task_not_found(output: str) -> bool:
    """Return whether ``schtasks`` reported that the requested task is absent."""

    normalized = str(output).lower()
    return any(
        marker in normalized
        for marker in (
            "not found",
            "does not exist",
            "cannot find the file",
            "cannot find the path",
            "not exist",
            "找不到",
            "不存在",
            "無法找到",
            "存在しません",
            "見つかりません",
        )
    )


@dataclass(frozen=True, slots=True)
class TaskSchedulerPlan:
    task_name: str
    command: tuple[str, ...]
    xml: str
    stable_entry: str


class WindowsTaskSchedulerAdapter:
    """Safe ``schtasks.exe`` adapter using list arguments and injectable execution."""

    def __init__(
        self,
        *,
        task_name: str = DAILY_RESEARCH_TASK_NAME,
        command_runner: CommandRunner = _subprocess_runner,
        username: str | None = None,
    ) -> None:
        self.task_name = task_name
        self.command_runner = command_runner
        self.username = username or os.environ.get("USERNAME") or "CURRENT_USER"

    def plan(
        self, settings: DailyScheduleSettings, *, stable_entry: str | Path
    ) -> TaskSchedulerPlan:
        stable = str(Path(stable_entry))
        xml = build_task_xml(
            settings, task_name=self.task_name, stable_entry=stable, username=self.username
        )
        command = ("schtasks.exe", "/Create", "/TN", self.task_name, "/XML", "<generated-task.xml>")
        return TaskSchedulerPlan(self.task_name, command, xml, stable)

    def query(self) -> TaskSchedulerState:
        try:
            result = self.command_runner(("schtasks.exe", "/Query", "/TN", self.task_name, "/XML"))
        except OSError:
            return TaskSchedulerState("error", "Task Scheduler is unavailable")
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            if _task_not_found(output):
                return TaskSchedulerState("not_installed", "task not installed")
            return TaskSchedulerState("error", _safe_reason(output) or "task query failed")
        try:
            root = ET.fromstring(result.stdout or "")
            enabled = next(
                (
                    element.text
                    for element in root.iter()
                    if element.tag.rsplit("}", 1)[-1] == "Enabled"
                ),
                None,
            )
            if enabled is not None:
                return TaskSchedulerState(
                    "enabled" if str(enabled).lower() == "true" else "disabled", "", result.stdout
                )
            state = self._query_task_state_text()
            if state == "not_installed":
                return TaskSchedulerState("not_installed", "task not installed")
            if state is not None:
                return TaskSchedulerState(state, "", result.stdout)
            return TaskSchedulerState(
                "error", "task XML did not expose an enabled state", result.stdout
            )
        except ET.ParseError:
            if _task_not_found(output):
                return TaskSchedulerState("not_installed", "task not installed")
            normalized = (result.stdout or "").lower()
            if "scheduled task state:" in normalized:
                state_line = normalized.split("scheduled task state:", 1)[1].splitlines()[0]
                if "disabled" in state_line:
                    return TaskSchedulerState("disabled", "", result.stdout)
                if "enabled" in state_line:
                    return TaskSchedulerState("enabled", "", result.stdout)
            if "status:" in normalized and "ready" in normalized:
                return TaskSchedulerState("enabled", "", result.stdout)
            return TaskSchedulerState("error", "task query returned an unknown format")

    def _query_task_state_text(
        self,
    ) -> Literal["disabled", "enabled", "not_installed"] | None:
        """Read only the stable state field when Task XML omits enabled state."""

        try:
            result = self.command_runner(
                ("schtasks.exe", "/Query", "/TN", self.task_name, "/FO", "LIST", "/V")
            )
        except OSError:
            return None
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            return "not_installed" if _task_not_found(output) else None
        for line in output.splitlines():
            key, separator, value = line.partition(":")
            if not separator or "state" not in key.lower():
                continue
            normalized = value.strip().lower()
            if normalized in {"enabled", "ready", "啟用", "已啟用"}:
                return "enabled"
            if normalized in {"disabled", "停用", "已停用"}:
                return "disabled"
        return None

    def install(
        self, settings: DailyScheduleSettings, *, stable_entry: str | Path
    ) -> TaskSchedulerState:
        existing = self.query()
        if existing.status != "not_installed":
            raise RuntimeError("refusing to overwrite an existing Task Scheduler task")
        plan = self.plan(settings, stable_entry=stable_entry)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".xml", delete=False
        ) as handle:
            handle.write(plan.xml)
            handle.flush()
            os.fsync(handle.fileno())
            xml_path = Path(handle.name)
        try:
            result = self.command_runner(
                ("schtasks.exe", "/Create", "/TN", self.task_name, "/XML", str(xml_path))
            )
        finally:
            xml_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError("Task Scheduler task creation failed")
        return self.query()

    def enable(self) -> TaskSchedulerState:
        self._simple_action("/Change", "/ENABLE")
        return self.query()

    def disable(self) -> TaskSchedulerState:
        self._simple_action("/Change", "/DISABLE")
        return self.query()

    def run_now(self) -> TaskSchedulerState:
        state = self.query()
        if state.status == "not_installed":
            return TaskSchedulerState("not_installed", "task not installed; enable before run-now")
        self._simple_action("/Run")
        return self.query()

    def uninstall(self) -> TaskSchedulerState:
        state = self.query()
        if state.status == "not_installed":
            return state
        try:
            self._simple_action("/Delete", "/F")
        except RuntimeError:
            # Task Scheduler can report a path error after a concurrent cleanup;
            # verify the postcondition rather than treating that as a success.
            if self.query().status != "not_installed":
                raise
        return self.query()

    def _simple_action(self, action: str, *extra: str) -> None:
        result = self.command_runner(("schtasks.exe", action, "/TN", self.task_name, *extra))
        if result.returncode != 0:
            raise RuntimeError("Task Scheduler operation failed")


class DailyScheduleApplicationService:
    """Application boundary for explicit settings-page scheduler actions."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        stable_entry: str | Path,
        adapter: WindowsTaskSchedulerAdapter | None = None,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.paths = paths
        self.stable_entry = Path(stable_entry)
        self.adapter = adapter or WindowsTaskSchedulerAdapter()
        self.now_fn = now_fn
        self.settings_store = DailyScheduleSettingsStore(
            paths.daily_schedule_settings_file, now_fn=now_fn
        )
        self.run_store = ScheduledRunStore(
            paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir
        )

    def settings(self) -> DailyScheduleSettings:
        return self.settings_store.load()

    def settings_warning(self) -> str | None:
        """Return the latest fail-closed settings warning, if any."""

        return self.settings_store.last_warning

    def state(self) -> TaskSchedulerState:
        return self.adapter.query()

    def latest_run(self) -> ScheduledRunRecord | None:
        return self.run_store.load_latest()

    def plan(self) -> TaskSchedulerPlan:
        return self.adapter.plan(self.settings(), stable_entry=self.stable_entry)

    def enable(self) -> TaskSchedulerState:
        current = self.settings()
        desired = replace(current, enabled=True, updated_at=self.now_fn().isoformat())
        state = self.adapter.query()
        if state.status == "not_installed":
            result = self.adapter.install(desired, stable_entry=self.stable_entry)
        else:
            result = self.adapter.enable()
        self.settings_store.save(desired)
        return result

    def disable(self) -> TaskSchedulerState:
        state = self.adapter.query()
        result = state if state.status == "not_installed" else self.adapter.disable()
        current = self.settings()
        self.settings_store.save(
            replace(current, enabled=False, updated_at=self.now_fn().isoformat())
        )
        return result

    def run_now(self) -> TaskSchedulerState:
        return self.adapter.run_now()

    def uninstall(self) -> TaskSchedulerState:
        result = self.adapter.uninstall()
        current = self.settings()
        self.settings_store.save(
            replace(current, enabled=False, updated_at=self.now_fn().isoformat())
        )
        return result


def build_task_xml(
    settings: DailyScheduleSettings,
    *,
    task_name: str,
    stable_entry: str,
    username: str,
) -> str:
    """Build a fully escaped, least-privilege weekday task definition."""

    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)

    def q(name: str) -> str:
        return f"{{{ns}}}{name}"

    task = ET.Element(q("Task"), {"version": "1.4"})
    registration = ET.SubElement(task, q("RegistrationInfo"))
    ET.SubElement(registration, q("Description")).text = (
        "StockTool daily evidence-chain research brief " f"({settings.timezone})"
    )
    principals = ET.SubElement(task, q("Principals"))
    principal = ET.SubElement(principals, q("Principal"), {"id": "Author"})
    ET.SubElement(principal, q("UserId")).text = username
    ET.SubElement(principal, q("LogonType")).text = "InteractiveToken"
    ET.SubElement(principal, q("RunLevel")).text = "LeastPrivilege"
    triggers = ET.SubElement(task, q("Triggers"))
    trigger = ET.SubElement(triggers, q("CalendarTrigger"))
    start = datetime(2000, 1, 3, settings.local_clock.hour, settings.local_clock.minute)
    ET.SubElement(trigger, q("StartBoundary")).text = start.strftime("%Y-%m-%dT%H:%M:%S")
    ET.SubElement(trigger, q("Enabled")).text = str(settings.enabled).lower()
    weekly = ET.SubElement(trigger, q("ScheduleByWeek"))
    ET.SubElement(weekly, q("WeeksInterval")).text = "1"
    days = ET.SubElement(weekly, q("DaysOfWeek"))
    names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    for day in settings.weekdays:
        ET.SubElement(days, q(names[day]))
    settings_node = ET.SubElement(task, q("Settings"))
    ET.SubElement(settings_node, q("MultipleInstancesPolicy")).text = "IgnoreNew"
    ET.SubElement(settings_node, q("StartWhenAvailable")).text = str(
        settings.start_when_available
    ).lower()
    ET.SubElement(settings_node, q("ExecutionTimeLimit")).text = "PT30M"
    ET.SubElement(settings_node, q("DisallowStartIfOnBatteries")).text = "false"
    actions = ET.SubElement(task, q("Actions"), {"Context": "Author"})
    exec_node = ET.SubElement(actions, q("Exec"))
    ET.SubElement(exec_node, q("Command")).text = stable_entry
    ET.SubElement(exec_node, q("Arguments")).text = "--daily-research-run --trigger scheduled"
    ET.SubElement(exec_node, q("WorkingDirectory")).text = str(Path(stable_entry).parent)
    return ET.tostring(task, encoding="unicode")


@dataclass(frozen=True, slots=True)
class DailyResearchStageResult:
    """Typed result for one actual stage of a daily research run."""

    name: str
    status: str
    input_snapshot_hash: str | None = None
    output_fingerprint: str | None = None
    data_as_of: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.name not in RUN_STAGE_NAMES:
            raise ValueError("unknown daily research stage")
        if self.status not in RUN_STAGE_STATUSES:
            raise ValueError("unknown daily research stage status")


@dataclass(frozen=True, slots=True)
class DailyResearchRunOutcome:
    """Runner result exposed to CLI/UI and converted to a persisted record."""

    status: str
    exit_code: int
    reason: str | None
    record: ScheduledRunRecord
    stages: tuple[DailyResearchStageResult, ...] = ()
    market_result: MarketRefreshResult | None = None
    market_snapshot_hash: str | None = None


class DailyResearchRefreshCallback(Protocol):
    def __call__(self, identities: tuple[Symbol, ...], paths: RuntimePaths) -> tuple[str, ...]: ...


def _market_snapshot_fingerprint(result: MarketRefreshResult | None) -> str | None:
    """Return the stable economic identity of one refresh result.

    Fetch timestamps are operational metadata and must not cause a replay of the
    same official snapshot to look like a different market input.
    """

    if result is None or result.snapshot is None:
        return None
    body = result.snapshot.to_dict()
    metadata = dict(body.get("metadata", {}))
    metadata.pop("fetched_at", None)
    body["metadata"] = metadata
    sources = []
    for source in body.get("source_metadata", []):
        item = dict(source)
        item.pop("fetched_at", None)
        sources.append(item)
    body["source_metadata"] = sources
    return _sha256(body)


def _stage(
    name: str,
    status: str,
    *,
    input_snapshot_hash: str | None = None,
    output_fingerprint: str | None = None,
    data_as_of: str | None = None,
    reason: str | None = None,
) -> DailyResearchStageResult:
    return DailyResearchStageResult(
        name=name,
        status=status,
        input_snapshot_hash=input_snapshot_hash,
        output_fingerprint=output_fingerprint,
        data_as_of=data_as_of,
        reason=reason,
    )


class _StageTrace:
    """Mutable run-local trace that always materializes the seven stage contract.

    The core orchestration deliberately keeps this object private.  It is not a
    second persistence model: it only protects the already-completed stage
    results when an unexpected exception crosses the outer runner boundary.
    """

    def __init__(self) -> None:
        self._results: dict[str, DailyResearchStageResult] = {}
        self.current: str | None = None

    def enter(self, name: str) -> None:
        if name not in RUN_STAGE_NAMES:
            raise ValueError("unknown daily research stage")
        self.current = name

    def append(self, result: DailyResearchStageResult) -> None:
        self._results[result.name] = result
        self.current = None

    def extend(self, results: Iterable[DailyResearchStageResult]) -> None:
        for result in results:
            self.append(result)

    def clear_current(self) -> None:
        self.current = None

    def mark_failure(self, reason: str) -> None:
        name = self.current
        if name is None:
            name = next(
                (stage for stage in RUN_STAGE_NAMES if stage not in self._results),
                RUN_STAGE_NAMES[-1],
            )
        existing = self._results.get(name)
        if existing is not None and existing.status == "success":
            # A completed stage is immutable for this run.  The next unexecuted
            # stage is the only safe place to attribute a boundary exception.
            name = next(
                (stage for stage in RUN_STAGE_NAMES if stage not in self._results),
                name,
            )
        self._results[name] = _stage(
            name,
            "failure",
            input_snapshot_hash=existing.input_snapshot_hash if existing else None,
            output_fingerprint=existing.output_fingerprint if existing else None,
            data_as_of=existing.data_as_of if existing else None,
            reason=reason,
        )
        self.skip_after(name, "前一階段未完成")
        self.current = None

    def skip_after(self, name: str, reason: str) -> None:
        index = RUN_STAGE_NAMES.index(name)
        for stage in RUN_STAGE_NAMES[index + 1 :]:
            if stage not in self._results:
                self._results[stage] = _stage(stage, "skipped", reason=reason)

    def as_tuple(self) -> tuple[DailyResearchStageResult, ...]:
        return tuple(
            self._results.get(name, _stage(name, "skipped", reason="前一階段未完成"))
            for name in RUN_STAGE_NAMES
        )

    def __iter__(self):
        return iter(self.as_tuple())

    def __len__(self) -> int:
        return len(self.as_tuple())


def _market_result_is_sample_eligible(result: MarketRefreshResult) -> bool:
    """Allow samples only from one complete, same-date fresh market snapshot."""

    snapshot = result.snapshot
    source_dates = {item.data_date for item in (snapshot.source_metadata if snapshot else ())}
    dates_consistent = bool(source_dates) and None not in source_dates and len(source_dates) == 1
    return bool(
        result.status == "fresh"
        and snapshot is not None
        and snapshot.metadata.status == "ready"
        and snapshot.metadata.freshness == "fresh"
        and dates_consistent
    )


def _skipped_stages(reason: str) -> tuple[DailyResearchStageResult, ...]:
    return tuple(_stage(name, "skipped", reason=reason) for name in RUN_STAGE_NAMES)


class HeadlessDailyResearchRunner:
    """Run one bounded daily research attempt without Streamlit or daemon state."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        now_fn: Callable[[], datetime] = _utc_now,
        refresh_callback: DailyResearchRefreshCallback | None = None,
        market_refresh_callback: Callable[[], MarketRefreshResult] | None = None,
        benchmark_refresh_callback: Callable[[], BenchmarkRefreshResult] | None = None,
        on_success: Callable[..., object] | None = None,
        prediction_outcome_provider: PredictionOutcomeProvider | None = None,
        max_symbols: int = 20,
        lock: ScheduleRunLock | None = None,
    ) -> None:
        if max_symbols <= 0:
            raise ValueError("max_symbols must be positive")
        self.paths = paths
        self.now_fn = now_fn
        self.refresh_callback = refresh_callback
        self.market_refresh_callback = market_refresh_callback
        self.benchmark_refresh_callback = benchmark_refresh_callback
        self.on_success = on_success
        self._benchmark_provider_injected = prediction_outcome_provider is not None
        self.prediction_outcome_provider = (
            prediction_outcome_provider
            or build_runtime_cached_outcome_provider(
                paths.processed_dir / "stock_data.sqlite",
                corporate_actions_path=paths.corporate_actions_file,
            )
        )
        self.max_symbols = max_symbols
        self.settings_store = DailyScheduleSettingsStore(
            paths.daily_schedule_settings_file, now_fn=now_fn
        )
        self.run_store = ScheduledRunStore(
            paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir
        )
        self.lock = lock or ScheduleRunLock(paths.daily_schedule_lock_file)

    def run(
        self, *, trigger: RUN_TRIGGER = "manual", dry_run: bool = False
    ) -> DailyResearchRunOutcome:
        run_id = f"run-{self.now_fn().astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
        started = self.now_fn().astimezone(timezone.utc)
        stage_trace = _StageTrace()
        try:
            self.lock.acquire(run_id=run_id, now=started)
        except ScheduleLockError as exc:
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="already_running",
                exit_code=EXIT_ALREADY_RUNNING,
                reason=str(exc),
                scheduled_for=None,
                stages=_skipped_stages("已有執行中的流程"),
            )
        try:
            outcome = self._run_locked(
                run_id=run_id,
                trigger=trigger,
                dry_run=dry_run,
                started=started,
                stage_trace=stage_trace,
            )
        except Exception as exc:  # defensive boundary for scheduled invocation
            stage_trace.mark_failure(f"流程未完成：{_safe_reason(type(exc).__name__)}")
            outcome = self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="failed",
                exit_code=EXIT_FAILED,
                reason=_safe_reason(type(exc).__name__),
                scheduled_for=None,
                stages=stage_trace.as_tuple(),
            )
        finally:
            self.lock.release()
        return outcome

    def _refresh_market_snapshot(self) -> MarketRefreshResult:
        """Refresh both official market endpoints exactly once for this run."""

        if self.market_refresh_callback is not None:
            return self.market_refresh_callback()
        return MarketMonitorApplicationService(self.paths.market_snapshot_file).refresh(
            markets=("TWSE", "TPEX")
        )

    def _refresh_benchmark_evidence(self) -> BenchmarkRefreshResult:
        """Refresh benchmark evidence once, then replace the read-only provider.

        A caller may inject the same service boundary for deterministic tests or
        an evidence replay.  Without an injected callback the production
        scheduler uses the existing bounded provider/cache contract.  The
        evaluator only sees the provider loaded *after* this refresh.
        """

        if self.benchmark_refresh_callback is not None:
            # Do not let a refresh failure fall through to the provider that
            # was loaded before this run.  A provider is authoritative only
            # after this run's refresh has persisted and reloaded it.
            self.prediction_outcome_provider = None
            result = self.benchmark_refresh_callback()
            if result.identities:
                database = self.paths.processed_dir / "stock_data.sqlite"
                refreshed = BenchmarkRefreshService(database).load_provider()
                if refreshed is not None:
                    self.prediction_outcome_provider = refreshed
            return result
        if self._benchmark_provider_injected and self.prediction_outcome_provider is not None:
            # An explicitly injected provider is already a verified snapshot;
            # do not unexpectedly issue network traffic in tests/replays.  The
            # dashboard composition supplies the callback for a user-triggered
            # refresh, while headless production starts with no provider.
            return BenchmarkRefreshResult("skipped", warnings=("provider already loaded",))
        if self.market_refresh_callback is not None or self.refresh_callback is not None:
            # A caller that injects the market refresh boundary must also
            # inject the benchmark boundary (or an already verified provider).
            # Falling through to the default network provider here would make
            # deterministic replays unexpectedly depend on external state and
            # could attach a live provider to a synthetic market snapshot.
            return BenchmarkRefreshResult(
                "skipped", warnings=("benchmark refresh boundary not configured",)
            )
        service = BenchmarkRefreshService(
            self.paths.processed_dir / "stock_data.sqlite",
            now_fn=self.now_fn,
            cache_dir=self.paths.cache_dir,
            log_dir=self.paths.logs_dir,
        )
        result = service.refresh(markets=("TWSE", "TPEX", "US"))
        if result.identities:
            self.prediction_outcome_provider = service.load_provider()
        return result

    def _evaluate_outcomes_stage(
        self,
        *,
        input_snapshot_hash: str | None,
        data_as_of: str | None,
    ) -> DailyResearchStageResult:
        """Evaluate due/retryable samples independently of registration.

        Registration may be skipped because a snapshot is unchanged, already
        contains the samples, or is not eligible.  That must not suppress the
        seventh stage when an older sample is due.  The evaluator remains
        read-only with respect to market data and uses the one injected
        provider shared by the runner.
        """

        if self.prediction_outcome_provider is None:
            return _stage(
                "prediction_outcome_evaluation",
                "skipped",
                input_snapshot_hash=input_snapshot_hash,
                data_as_of=data_as_of,
                reason="沒有注入可驗證的歷史價格／基準資料；結算未執行",
            )
        try:
            evaluator = PredictionOutcomeEvaluator(
                PredictionLabStore.from_runtime_paths(self.paths).ensure(),
                self.prediction_outcome_provider,
                now_fn=self.now_fn,
            )
            as_of = self.now_fn().astimezone(timezone.utc).date().isoformat()
            preflight = getattr(evaluator, "has_due_or_retryable", None)
            if callable(preflight) and not preflight(as_of=as_of):
                return _stage(
                    "prediction_outcome_evaluation",
                    "skipped",
                    input_snapshot_hash=input_snapshot_hash,
                    data_as_of=data_as_of,
                    reason="目前沒有到期或可重試樣本",
                )
            evaluation = evaluator.evaluate_due(as_of=as_of)
            output = _sha256(
                [
                    {
                        "prediction_id": item.prediction_id,
                        "status": item.status,
                        "fingerprint": item.outcome_fingerprint,
                    }
                    for item in evaluation.outcomes
                ]
            )
            status = "success" if evaluation.status == "success" else "partial"
            reason = None if evaluation.status == "success" else evaluation.message
            return _stage(
                "prediction_outcome_evaluation",
                status,
                input_snapshot_hash=input_snapshot_hash,
                output_fingerprint=output,
                data_as_of=data_as_of,
                reason=reason,
            )
        except Exception as exc:
            return _stage(
                "prediction_outcome_evaluation",
                "failure",
                input_snapshot_hash=input_snapshot_hash,
                data_as_of=data_as_of,
                reason=f"Prediction Lab 到期結算失敗: {_safe_reason(type(exc).__name__)}",
            )

    def _run_locked(
        self,
        *,
        run_id: str,
        trigger: RUN_TRIGGER,
        dry_run: bool,
        started: datetime,
        stage_trace: _StageTrace,
    ) -> DailyResearchRunOutcome:
        settings = self.settings_store.load()
        scheduled_for = _scheduled_for(started, settings)
        if trigger == "scheduled" and not settings.enabled:
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="skipped_disabled",
                exit_code=EXIT_SKIPPED,
                reason="schedule disabled",
                scheduled_for=scheduled_for,
                stages=_skipped_stages("schedule disabled"),
            )
        if trigger == "scheduled" and scheduled_for is None:
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="skipped_missed_window",
                exit_code=EXIT_SKIPPED,
                reason="outside configured schedule window",
                scheduled_for=None,
                stages=_skipped_stages("outside configured schedule window"),
            )

        portfolio = load_portfolio(self.paths.portfolio_file)
        watchlist = load_watchlist(self.paths.watchlist_file)
        effective = build_effective_watchlist(watchlist, portfolio)
        identities = _identities(effective)[: self.max_symbols]
        if not identities:
            # No new targets does not imply no due samples.  Keep the first
            # five stages explicitly skipped, then let the shared evaluator
            # settle any older retryable sample without touching portfolio or
            # market data.
            no_target_stages = [
                _stage(name, "skipped", reason="沒有 market-qualified research targets")
                for name in (
                    "target_refresh",
                    "market_refresh",
                    "brief",
                    "change",
                    "prediction_registration",
                )
            ]
            evaluation_stage = self._evaluate_outcomes_stage(
                input_snapshot_hash=None,
                data_as_of=None,
            )
            no_target_stages.append(evaluation_stage)
            no_target_stages.append(
                _stage("notification", "skipped", reason="沒有新的研究簡報可通知")
            )
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="skipped_no_targets",
                exit_code=EXIT_SKIPPED,
                reason="no market-qualified targets",
                scheduled_for=scheduled_for,
                stages=tuple(no_target_stages),
            )

        if (
            trigger == "scheduled"
            and scheduled_for is not None
            and self.run_store.has_scheduled_for(scheduled_for)
        ):
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="skipped_no_new_data",
                exit_code=EXIT_SKIPPED,
                reason="scheduled window already completed",
                scheduled_for=scheduled_for,
                stages=_skipped_stages("scheduled window already completed"),
            )

        before_hash = _input_snapshot_hash(identities, self.paths)
        latest = self.run_store.load_latest()
        if dry_run:
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="skipped_dry_run",
                exit_code=EXIT_SKIPPED,
                reason="dry run requested",
                scheduled_for=scheduled_for,
                input_snapshot_hash=before_hash,
                stages=_skipped_stages("dry run requested"),
            )

        stage_results = stage_trace
        stage_trace.enter("target_refresh")
        refresh_reasons: tuple[str, ...] = ()
        target_reason: str | None = None
        target_status = "success"
        try:
            if self.refresh_callback is not None:
                refresh_reasons = tuple(self.refresh_callback(identities, self.paths))
            else:
                refresh_reasons = _refresh_existing_provider(identities, self.paths)
            if refresh_reasons:
                target_status = "partial"
                target_reason = "; ".join(_safe_reason(item) for item in refresh_reasons)
        except Exception as exc:
            target_status = "failure"
            target_reason = f"target refresh failed: {_safe_reason(type(exc).__name__)}"

        stage_results.append(
            _stage(
                "target_refresh",
                target_status,
                input_snapshot_hash=before_hash,
                reason=target_reason,
            )
        )

        if target_status == "failure":
            stage_trace.skip_after("target_refresh", "前一階段未完成")
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="failed",
                exit_code=EXIT_FAILED,
                reason=target_reason,
                scheduled_for=scheduled_for,
                input_snapshot_hash=before_hash,
                stages=stage_trace.as_tuple(),
            )

        stage_trace.enter("market_refresh")
        try:
            market_result = self._refresh_market_snapshot()
        except Exception as exc:
            reason = f"市場資料更新失敗：{_safe_reason(type(exc).__name__)}"
            stage_results.append(_stage("market_refresh", "failure", reason=reason))
            stage_trace.skip_after("market_refresh", "前一階段未完成")
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="failed",
                exit_code=EXIT_FAILED,
                reason=reason,
                scheduled_for=scheduled_for,
                input_snapshot_hash=before_hash,
                stages=stage_trace.as_tuple(),
            )
        market_snapshot_hash = _market_snapshot_fingerprint(market_result)
        market_snapshot = market_result.snapshot
        market_data_as_of = (
            market_snapshot.metadata.data_date if market_snapshot is not None else None
        )
        market_is_fresh = _market_result_is_sample_eligible(market_result)
        if market_is_fresh:
            market_stage_status = "success"
        elif market_result.status == "partial":
            market_stage_status = "partial"
        else:
            market_stage_status = "unavailable"
        market_reason = "; ".join(_safe_reason(item) for item in market_result.warnings) or None
        stage_results.append(
            _stage(
                "market_refresh",
                market_stage_status,
                input_snapshot_hash=before_hash,
                output_fingerprint=market_snapshot_hash,
                data_as_of=market_data_as_of,
                reason=market_reason,
            )
        )

        # Benchmark refresh is an explicit data-boundary operation.  It does
        # not create another stage in the public run contract, but its result
        # determines whether the shared evaluator can settle samples.  Any
        # failure is retained as a safe warning and never turns a stale
        # provider into fresh evidence.
        try:
            benchmark_result = self._refresh_benchmark_evidence()
        except Exception as exc:
            benchmark_result = BenchmarkRefreshResult(
                "unavailable",
                warnings=(f"benchmark refresh failed: {_safe_reason(type(exc).__name__)}",),
            )
        if benchmark_result.warnings:
            logging.getLogger(__name__).warning(
                "benchmark evidence refresh status=%s warnings=%s",
                benchmark_result.status,
                benchmark_result.warnings,
            )

        stage_trace.enter("brief")
        prices, source_map = _load_price_context(self.paths)
        input_hash = _input_snapshot_hash(
            identities, self.paths, prices=prices, market_result=market_result
        )
        if (
            latest is not None
            and latest.status == "success"
            and latest.input_snapshot_hash == input_hash
        ):
            stage_results.extend(
                _stage(
                    name,
                    "skipped",
                    input_snapshot_hash=market_snapshot_hash,
                    reason="no new evidence after refresh",
                )
                for name in (
                    "brief",
                    "change",
                    "prediction_registration",
                )
            )
            evaluation_stage = self._evaluate_outcomes_stage(
                input_snapshot_hash=market_snapshot_hash,
                data_as_of=market_data_as_of,
            )
            stage_results.append(evaluation_stage)
            stage_results.append(
                _stage(
                    "notification",
                    "skipped",
                    input_snapshot_hash=market_snapshot_hash,
                    reason="沒有新的研究簡報可通知",
                )
            )
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="skipped_no_new_data",
                exit_code=EXIT_SKIPPED,
                reason="no new evidence after refresh",
                scheduled_for=scheduled_for,
                input_snapshot_hash=input_hash,
                stages=tuple(stage_results),
                market_result=market_result,
                market_snapshot_hash=market_snapshot_hash,
            )
        try:
            valuation = _load_local_valuation(portfolio, prices)
            continuations = _load_local_research_continuations(self.paths, identities=identities)
            fundamental_scores = _load_local_fundamental_scores(self.paths)
            daily_brief = DailyBriefService().build(
                portfolio=portfolio,
                watchlist=effective,
                prices=prices,
                valuation=valuation,
                continuations=continuations,
                reference_at=max(source_map.values()) if source_map else None,
                fundamental_scores=fundamental_scores,
            )
            previous_snapshot = (
                DailyResearchSnapshotStore(self.paths.daily_research_snapshot_file).load().snapshot
            )
            loop = DailyResearchLoopService().complete_success(
                brief=daily_brief,
                previous_snapshot=previous_snapshot,
                successful_at=started.isoformat(),
                sources={
                    key: DailyResearchSource(
                        provider="local",
                        source_type="cache",
                        provider_symbol=None,
                        last_data_date=str(value)[:10] if value else None,
                        checked_at=value,
                    )
                    for key, value in source_map.items()
                },
            )
            brief = DailyResearchBriefApplicationService(now_fn=self.now_fn).generate(
                portfolio=portfolio,
                watchlist=effective,
                daily_brief=daily_brief,
                loop_result=loop,
                market_result=market_result,
                assistant_brief=None,
                previous_snapshot_id=previous_snapshot.successful_at if previous_snapshot else None,
            )
        except Exception as exc:
            reason = f"研究簡報產生失敗：{_safe_reason(type(exc).__name__)}"
            stage_results.append(
                _stage("brief", "failure", input_snapshot_hash=market_snapshot_hash, reason=reason)
            )
            stage_trace.skip_after("brief", "前一階段未完成")
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="failed",
                exit_code=EXIT_FAILED,
                reason=reason,
                scheduled_for=scheduled_for,
                input_snapshot_hash=input_hash,
                stages=stage_trace.as_tuple(),
                market_result=market_result,
                market_snapshot_hash=market_snapshot_hash,
            )
        if brief.status != "success":
            reason = "partial or unavailable evidence; previous successful brief retained"
            if refresh_reasons:
                reason = "; ".join((reason, *(_safe_reason(item) for item in refresh_reasons)))
            stage_results.append(
                _stage(
                    "brief",
                    "partial" if market_result.status == "partial" else "unavailable",
                    input_snapshot_hash=market_snapshot_hash,
                    data_as_of=brief.manifest.as_of_date,
                    reason=reason,
                )
            )
            stage_trace.skip_after("brief", "前一階段未完成")
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="partial",
                exit_code=EXIT_PARTIAL,
                reason=reason,
                scheduled_for=scheduled_for,
                input_snapshot_hash=input_hash,
                data_as_of=brief.manifest.as_of_date,
                stages=tuple(stage_results),
                market_result=market_result,
                market_snapshot_hash=market_snapshot_hash,
            )
        store = DailyResearchBriefStore(
            self.paths.daily_research_brief_file,
            self.paths.daily_research_brief_html_file,
            self.paths.daily_research_brief_history_dir,
        )
        previous_brief: DailyResearchBrief | None = None
        change_history_error: ValueError | None = None
        try:
            history = store.history()
            if history:
                previous_brief = history[-1]
        except ValueError as exc:
            # A history directory that contains an invalid immutable brief is
            # not equivalent to "no prior brief".  Do not mint a fabricated
            # first baseline or overwrite the last verified change summary.
            change_history_error = exc
            logging.getLogger(__name__).warning(
                "daily research change history rejected; preserving prior summary: %s",
                type(exc).__name__,
            )
        try:
            # Persist the loop snapshot as part of the brief stage before the
            # authoritative brief bytes are published.  A failure therefore
            # cannot leave a new brief paired with an older snapshot.
            if loop.snapshot is not None:
                DailyResearchSnapshotStore(self.paths.daily_research_snapshot_file).save(
                    loop.snapshot
                )
            store.save(brief)
            stage_results.append(
                _stage(
                    "brief",
                    "success",
                    input_snapshot_hash=market_snapshot_hash,
                    output_fingerprint=brief.manifest.content_fingerprint,
                    data_as_of=brief.manifest.as_of_date,
                )
            )
        except Exception as exc:
            reason = f"brief 保存失敗: {_safe_reason(type(exc).__name__)}"
            stage_results.append(
                _stage(
                    "brief",
                    "failure",
                    input_snapshot_hash=market_snapshot_hash,
                    data_as_of=brief.manifest.as_of_date,
                    reason=reason,
                )
            )
            stage_trace.skip_after("brief", "前一階段未完成")
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="failed",
                exit_code=EXIT_FAILED,
                reason=reason,
                scheduled_for=scheduled_for,
                input_snapshot_hash=input_hash,
                data_as_of=brief.manifest.as_of_date,
                stages=tuple(stage_results),
                market_result=market_result,
                market_snapshot_hash=market_snapshot_hash,
            )

        change_summary: object | None = None
        if change_history_error is not None:
            change_reason = "change history 無法驗證；保留上一份摘要"
            stage_results.append(
                _stage(
                    "change",
                    "unavailable",
                    input_snapshot_hash=market_snapshot_hash,
                    reason=change_reason,
                )
            )
        else:
            stage_trace.enter("change")
            try:
                change_summary = DailyResearchChangeApplicationService(now_fn=self.now_fn).compare(
                    brief, previous_brief
                )
                DailyResearchChangeStore(
                    self.paths.daily_research_change_file,
                    self.paths.daily_research_change_history_dir,
                ).save(change_summary)
                stage_results.append(
                    _stage(
                        "change",
                        "success",
                        input_snapshot_hash=market_snapshot_hash,
                        output_fingerprint=getattr(change_summary, "content_fingerprint", None),
                        data_as_of=brief.manifest.as_of_date,
                    )
                )
            except Exception as exc:
                change_summary = None
                change_reason = f"change 保存失敗: {_safe_reason(type(exc).__name__)}"
                logging.getLogger(__name__).warning(
                    "daily research change summary unavailable", exc_info=True
                )
                stage_results.append(
                    _stage(
                        "change",
                        "failure",
                        input_snapshot_hash=market_snapshot_hash,
                        reason=change_reason,
                    )
                )
                stage_trace.skip_after("change", "前一階段未完成")
                return self._finish(
                    run_id=run_id,
                    trigger=trigger,
                    started=started,
                    status="failed",
                    exit_code=EXIT_FAILED,
                    reason=change_reason,
                    scheduled_for=scheduled_for,
                    input_snapshot_hash=input_hash,
                    data_as_of=brief.manifest.as_of_date,
                    stages=stage_trace.as_tuple(),
                    market_result=market_result,
                    market_snapshot_hash=market_snapshot_hash,
                )
        stage_trace.enter("prediction_registration")
        prediction_status = "skipped"
        prediction_reason: str | None = "市場 snapshot 未達 fresh/full 條件；樣本未登錄"
        prediction_output: str | None = None
        if market_is_fresh and market_result.snapshot is not None:
            try:
                registration = PredictionLabApplicationService(
                    PredictionLabStore.from_runtime_paths(self.paths).ensure(),
                    now_fn=self.now_fn,
                ).register_from_market_snapshot(
                    market_result.snapshot,
                    trading_date=brief.manifest.brief_date,
                    input_hashes=(
                        economic_input_fingerprint(
                            market_result.snapshot, trading_date=brief.manifest.brief_date
                        ),
                    ),
                )
                created_count = int(
                    getattr(registration, "created_count", len(registration.records))
                )
                if registration.status == "success" and created_count > 0:
                    prediction_status = "success"
                    prediction_output = _sha256(
                        [item.prediction_id for item in registration.records]
                    )
                    prediction_reason = None
                elif registration.status == "success":
                    prediction_status = "skipped"
                    prediction_reason = "樣本已存在；本次登錄已冪等略過"
                else:
                    prediction_status = "unavailable"
                    prediction_reason = getattr(registration, "message", "Prediction Lab 暫不可用")
            except Exception as exc:
                prediction_status = "failure"
                prediction_reason = f"Prediction Lab 登錄失敗: {_safe_reason(type(exc).__name__)}"
        stage_results.append(
            _stage(
                "prediction_registration",
                prediction_status,
                input_snapshot_hash=market_snapshot_hash,
                output_fingerprint=prediction_output,
                data_as_of=market_data_as_of,
                reason=prediction_reason,
            )
        )

        if prediction_status == "failure":
            stage_trace.skip_after("prediction_registration", "前一階段未完成")
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="failed",
                exit_code=EXIT_FAILED,
                reason=prediction_reason,
                scheduled_for=scheduled_for,
                input_snapshot_hash=input_hash,
                output_brief_fingerprint=brief.manifest.content_fingerprint,
                data_as_of=brief.manifest.as_of_date,
                deterministic_fallback_used=True,
                stages=stage_trace.as_tuple(),
                market_result=market_result,
                market_snapshot_hash=market_snapshot_hash,
            )

        stage_trace.enter("prediction_outcome_evaluation")
        evaluation_stage = self._evaluate_outcomes_stage(
            input_snapshot_hash=market_snapshot_hash,
            data_as_of=brief.manifest.as_of_date,
        )
        stage_results.append(evaluation_stage)
        evaluation_status = evaluation_stage.status
        evaluation_reason = evaluation_stage.reason

        if evaluation_status == "failure":
            stage_trace.skip_after("prediction_outcome_evaluation", "前一階段未完成")
            return self._finish(
                run_id=run_id,
                trigger=trigger,
                started=started,
                status="failed",
                exit_code=EXIT_FAILED,
                reason=evaluation_reason,
                scheduled_for=scheduled_for,
                input_snapshot_hash=input_hash,
                output_brief_fingerprint=brief.manifest.content_fingerprint,
                data_as_of=brief.manifest.as_of_date,
                deterministic_fallback_used=True,
                stages=stage_trace.as_tuple(),
                market_result=market_result,
                market_snapshot_hash=market_snapshot_hash,
            )

        stage_trace.enter("notification")
        completed = self.now_fn().astimezone(timezone.utc)
        provisional = self._build_record(
            run_id=run_id,
            trigger=trigger,
            started=started,
            completed=completed,
            status="success",
            exit_code=EXIT_SUCCESS,
            reason=None,
            scheduled_for=scheduled_for,
            input_snapshot_hash=input_hash,
            output_brief_fingerprint=brief.manifest.content_fingerprint,
            data_as_of=brief.manifest.as_of_date,
            deterministic_fallback_used=True,
        )
        notification_status = "unavailable"
        notification_reason: str | None = "通知未設定"
        if self.on_success is not None:
            try:
                notification_result = self.on_success(
                    provisional, brief, change_summary=change_summary
                )
                raw_status = str(getattr(notification_result, "status", "failed"))
                raw_reason = getattr(notification_result, "reason", None)
                if raw_status == "sent":
                    notification_status = "success"
                    notification_reason = None
                elif raw_status == "unavailable" and "去重" in str(raw_reason or ""):
                    notification_status = "skipped"
                    notification_reason = str(raw_reason)
                elif raw_status == "unavailable":
                    notification_status = "unavailable"
                    notification_reason = str(raw_reason or "通知不可用")
                else:
                    notification_status = "failure"
                    notification_reason = str(raw_reason or "通知發送失敗")
            except Exception as exc:
                notification_status = "failure"
                notification_reason = f"通知發送失敗: {_safe_reason(type(exc).__name__)}"
        stage_results.append(
            _stage(
                "notification",
                notification_status,
                input_snapshot_hash=market_snapshot_hash,
                output_fingerprint=brief.manifest.content_fingerprint,
                data_as_of=brief.manifest.as_of_date,
                reason=notification_reason,
            )
        )
        stage_trace.clear_current()
        core_statuses = {item.status for item in stage_results}
        blocking_statuses = {"partial", "unavailable", "failure"}
        overall_status = "partial" if core_statuses & blocking_statuses else "success"
        overall_exit = EXIT_PARTIAL if overall_status == "partial" else EXIT_SUCCESS
        reasons = tuple(item.reason for item in stage_results if item.reason)
        outcome = self._finish(
            run_id=run_id,
            trigger=trigger,
            started=started,
            status=overall_status,
            exit_code=overall_exit,
            reason="; ".join(reasons) if reasons else None,
            scheduled_for=scheduled_for,
            input_snapshot_hash=input_hash,
            output_brief_fingerprint=brief.manifest.content_fingerprint,
            data_as_of=brief.manifest.as_of_date,
            deterministic_fallback_used=True,
            completed_at=completed,
            stages=stage_trace.as_tuple(),
            market_result=market_result,
            market_snapshot_hash=market_snapshot_hash,
        )
        return outcome

    def _build_record(
        self,
        *,
        run_id: str,
        trigger: RUN_TRIGGER,
        started: datetime,
        completed: datetime,
        status: str,
        exit_code: int,
        reason: str | None,
        scheduled_for: str | None,
        input_snapshot_hash: str | None = None,
        output_brief_fingerprint: str | None = None,
        data_as_of: str | None = None,
        deterministic_fallback_used: bool = True,
    ) -> ScheduledRunRecord:
        return ScheduledRunRecord(
            run_id=run_id,
            trigger=trigger,
            scheduled_for=scheduled_for,
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            status=status,
            exit_code=exit_code,
            input_snapshot_hash=input_snapshot_hash,
            output_brief_fingerprint=output_brief_fingerprint,
            data_as_of=data_as_of,
            deterministic_fallback_used=deterministic_fallback_used,
            reason=_safe_reason(reason) if reason else None,
            duration_seconds=max(0.0, (completed - started).total_seconds()),
        )

    def _finish(
        self,
        *,
        run_id: str,
        trigger: RUN_TRIGGER,
        started: datetime,
        status: str,
        exit_code: int,
        reason: str | None,
        scheduled_for: str | None,
        input_snapshot_hash: str | None = None,
        output_brief_fingerprint: str | None = None,
        data_as_of: str | None = None,
        deterministic_fallback_used: bool = True,
        completed_at: datetime | None = None,
        stages: tuple[DailyResearchStageResult, ...] = (),
        market_result: MarketRefreshResult | None = None,
        market_snapshot_hash: str | None = None,
    ) -> DailyResearchRunOutcome:
        completed = completed_at or self.now_fn().astimezone(timezone.utc)
        if not stages:
            # Every externally visible run carries the complete ordered stage
            # contract, including lock/early-exit outcomes.  This prevents the
            # manifest facade from inventing six ``unavailable`` stages.
            stages = _skipped_stages(reason or "流程未執行")
        record = self._build_record(
            run_id=run_id,
            trigger=trigger,
            started=started,
            completed=completed,
            status=status,
            exit_code=exit_code,
            reason=reason,
            scheduled_for=scheduled_for,
            input_snapshot_hash=input_snapshot_hash,
            output_brief_fingerprint=output_brief_fingerprint,
            data_as_of=data_as_of,
            deterministic_fallback_used=deterministic_fallback_used,
        )
        try:
            self.run_store.save(record)
        except (OSError, ValueError, TypeError):
            # A run record failure is surfaced as failed, but cannot damage a brief already saved.
            record = replace(
                record,
                status="failed",
                exit_code=EXIT_FAILED,
                reason="run record persistence failed",
            )
        return DailyResearchRunOutcome(
            record.status,
            record.exit_code,
            record.reason,
            record,
            stages=stages,
            market_result=market_result,
            market_snapshot_hash=market_snapshot_hash,
        )


def _scheduled_for(now: datetime, settings: DailyScheduleSettings) -> str | None:
    local = now.astimezone(_safe_timezone(settings.timezone))
    if local.weekday() not in settings.weekdays:
        return None
    target = datetime.combine(local.date(), settings.local_clock, tzinfo=local.tzinfo)
    if local < target:
        return None
    if not settings.start_when_available and (local.hour, local.minute) != (
        target.hour,
        target.minute,
    ):
        return None
    if local - target > timedelta(minutes=settings.missed_run_grace_minutes):
        return None
    return target.astimezone(timezone.utc).isoformat()


def next_scheduled_for(now: datetime, settings: DailyScheduleSettings) -> str | None:
    """Return the next configured weekday occurrence in UTC for UI/status evidence."""

    local = now.astimezone(_safe_timezone(settings.timezone))
    for offset in range(0, 8):
        candidate_date = local.date() + timedelta(days=offset)
        if candidate_date.weekday() not in settings.weekdays:
            continue
        candidate = datetime.combine(candidate_date, settings.local_clock, tzinfo=local.tzinfo)
        if candidate <= local:
            continue
        return candidate.astimezone(timezone.utc).isoformat()
    return None


def format_next_scheduled_for(now: datetime, settings: DailyScheduleSettings) -> str | None:
    """Format the next occurrence in the configured local timezone for UI."""

    scheduled = next_scheduled_for(now, settings)
    if scheduled is None:
        return None
    local = datetime.fromisoformat(scheduled).astimezone(_safe_timezone(settings.timezone))
    return f"{local:%Y-%m-%d %H:%M} ({settings.timezone})"


def _identities(frame: pd.DataFrame) -> tuple[Symbol, ...]:
    found: dict[str, Symbol] = {}
    if frame is None or frame.empty or not {"symbol", "market"}.issubset(frame.columns):
        return ()
    for row in frame.loc[:, ["symbol", "market"]].itertuples(index=False):
        try:
            symbol = Symbol.parse(str(row.symbol), market=str(row.market))
        except ValueError:
            continue
        if symbol.market in {Market.TWSE, Market.TPEX, Market.US}:
            found.setdefault(symbol.canonical, symbol)
    return tuple(found[key] for key in sorted(found))


def _load_price_context(paths: RuntimePaths) -> tuple[pd.DataFrame, dict[str, str]]:
    storage = SQLitePriceStorage(paths.processed_dir / "stock_data.sqlite")
    if not storage.price_identity_sidecar_path.is_file():
        return pd.DataFrame(columns=["symbol", "market", "date", "close", "volume"]), {}
    context = storage.load_market_qualified_price_context()
    if context.warnings or not context.records:
        return pd.DataFrame(columns=["symbol", "market", "date", "close", "volume"]), {}
    frame = pd.DataFrame(list(context.records))
    checked = {
        item.symbol.canonical: item.checked_at for item in context.provenance if item.checked_at
    }
    return frame, checked


def _load_local_valuation(
    portfolio: pd.DataFrame, prices: pd.DataFrame
) -> PortfolioValuationResult | None:
    """Value local positions without a network request or an invented FX rate."""

    if portfolio is None or portfolio.empty:
        return None
    try:
        return PortfolioValuationService().value(positions=portfolio, prices=prices)
    except (TypeError, ValueError, KeyError):
        return None


def _load_local_fundamental_scores(paths: RuntimePaths) -> pd.DataFrame | None:
    """Load only an existing, local fundamental score file; never fetch here."""

    path = paths.processed_dir / "fundamentals_auto.csv"
    if not path.is_file():
        return None
    try:
        frame = load_fundamentals_csv(path)
        scores = score_fundamentals(frame)
    except (OSError, TypeError, ValueError, UnicodeError):
        return None
    return scores if not scores.empty else None


def _load_local_research_continuations(
    paths: RuntimePaths, *, identities: Sequence[Symbol]
) -> tuple[ResearchContinuation, ...]:
    """Reuse successful local evidence items as explicit research continuations."""

    brief = DailyResearchBriefStore(
        paths.daily_research_brief_file, paths.daily_research_brief_html_file
    ).load()
    allowed = {item.canonical for item in identities}
    continuations: list[ResearchContinuation] = []
    if brief is not None:
        for item in brief.items:
            if not item.symbol or not item.market or item.status not in {"fresh", "partial"}:
                continue
            try:
                symbol = Symbol.parse(item.symbol, market=item.market)
            except ValueError:
                continue
            if symbol.canonical not in allowed:
                continue
            continuations.append(
                ResearchContinuation(
                    symbol=symbol,
                    researched_at=brief.generated_at,
                    data_as_of_date=item.data_as_of,
                    coverage=item.completeness,
                    status="available",
                )
            )
        return tuple(sorted(continuations, key=lambda item: item.symbol.canonical))

    # A headless/offline run may legitimately have a previous loop snapshot but
    # no current evidence-chain JSON yet.  Reuse only the explicit research
    # coverage events from that immutable snapshot; do not infer coverage from
    # prices or create a synthetic brief.
    snapshot = DailyResearchSnapshotStore(paths.daily_research_snapshot_file).load().snapshot
    if snapshot is None:
        return ()
    for event in snapshot.events:
        if event.field != "research_coverage" or not event.identity:
            continue
        try:
            symbol = Symbol.parse(
                event.identity.split(":", maxsplit=1)[1],
                market=event.identity.split(":", maxsplit=1)[0],
            )
        except (IndexError, ValueError):
            continue
        if symbol.canonical not in allowed:
            continue
        value = event.current_value.strip().removesuffix("%").strip()
        try:
            coverage = float(value) / (100.0 if event.current_value.strip().endswith("%") else 1.0)
        except (TypeError, ValueError):
            continue
        if not 0.0 <= coverage <= 1.0:
            continue
        continuations.append(
            ResearchContinuation(
                symbol=symbol,
                researched_at=snapshot.successful_at,
                data_as_of_date=event.as_of_date or snapshot.data_as_of_date,
                coverage=coverage,
                status="available",
            )
        )
    return tuple(sorted(continuations, key=lambda item: item.symbol.canonical))


def _input_snapshot_hash(
    identities: Sequence[Symbol],
    paths: RuntimePaths,
    *,
    prices: pd.DataFrame | None = None,
    market_result: MarketRefreshResult | None = None,
) -> str:
    if prices is None:
        prices, _ = _load_price_context(paths)
    price_payload = []
    if prices is not None and not prices.empty:
        columns = [
            item
            for item in ("symbol", "market", "date", "close", "volume")
            if item in prices.columns
        ]
        if columns:
            price_payload = (
                prices.loc[:, columns]
                .fillna("")
                .astype(str)
                .sort_values(columns)
                .to_dict(orient="records")
            )
    market_hash = _market_snapshot_fingerprint(market_result)
    if market_hash is None and paths.market_snapshot_file.is_file():
        try:
            market_hash = _sha256(
                json.loads(paths.market_snapshot_file.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            market_hash = "corrupt"
    return _sha256(
        {
            "identities": [item.canonical for item in identities],
            "prices": price_payload,
            "market_snapshot": market_hash,
        }
    )


def _refresh_existing_provider(
    identities: Sequence[Symbol], paths: RuntimePaths
) -> tuple[str, ...]:
    """Refresh explicit identities through the existing bounded provider contract."""

    if os.environ.get("STOCK_TOOL_EVIDENCE_MODE", "").strip() == "sprint32.1.1":
        # Evidence-only replay: target rows must already be present in the
        # isolated runtime SQLite snapshot.  This keeps the normal provider
        # path untouched while proving the same runner can operate offline
        # from deterministic, prevalidated data.
        frame, _source_map = _load_price_context(paths)
        available = {
            f"{row.market}:{row.symbol}"
            for row in frame.itertuples(index=False)
            if getattr(row, "symbol", None) and getattr(row, "market", None)
        }
        return tuple(
            f"{symbol.canonical}:fixture_missing"
            for symbol in identities
            if symbol.canonical not in available
        )

    start, end = default_date_range(None, None)
    storage = SQLitePriceStorage(paths.processed_dir / "stock_data.sqlite")
    reasons: list[str] = []
    for symbol in identities:
        try:
            result = fetch_prices_result(
                symbol.code,
                market=symbol.market.value,
                start=start,
                end=end,
                interval="1d",
                provider="auto",
                use_cache=True,
                force_refresh=True,
                cache_dir=paths.cache_dir,
                log_dir=paths.logs_dir,
                contracts_enabled=True,
            )
            if not result.succeeded or result.data is None or result.data.empty:
                reasons.append(f"{symbol.canonical}:unavailable")
                continue
            frame = result.data.copy(deep=True)
            records = frame.to_dict(orient="records")
            source = result.metadata
            storage.save_market_qualified_price_data(
                records,
                provenance=PersistedPriceProvenance(
                    symbol=symbol,
                    provider=source.provider,
                    provider_symbol=source.provider_symbol,
                    source_type=source.source_type.value,
                    last_data_date=source.last_data_date,
                    checked_at=source.fetched_at,
                    fetched_at=source.fetched_at,
                ),
            )
        except Exception:
            reasons.append(f"{symbol.canonical}:refresh_failed")
    return tuple(reasons)


__all__ = [
    "DAILY_RESEARCH_TASK_NAME",
    "DailyScheduleApplicationService",
    "EXIT_ALREADY_RUNNING",
    "EXIT_FAILED",
    "EXIT_PARTIAL",
    "EXIT_SKIPPED",
    "EXIT_SUCCESS",
    "DailyResearchRunOutcome",
    "DailyResearchStageResult",
    "DailyScheduleSettings",
    "DailyScheduleSettingsStore",
    "HeadlessDailyResearchRunner",
    "RUN_RECORD_SCHEMA_VERSION",
    "ScheduleLockError",
    "ScheduleRunLock",
    "ScheduledRunRecord",
    "ScheduledRunStore",
    "TaskSchedulerPlan",
    "TaskSchedulerState",
    "WindowsTaskSchedulerAdapter",
    "build_task_xml",
    "format_next_scheduled_for",
    "next_scheduled_for",
]
