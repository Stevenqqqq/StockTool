from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from xml.etree import ElementTree as ET

import pandas as pd
import pytest

import stock_tool.application.daily_research_scheduler as scheduler_module
from stock_tool.application.daily_research_scheduler import (
    DAILY_RESEARCH_TASK_NAME,
    EXIT_ALREADY_RUNNING,
    EXIT_SKIPPED,
    DailyScheduleSettings,
    DailyScheduleSettingsStore,
    DailyResearchRefreshCallback,
    HeadlessDailyResearchRunner,
    ScheduleLockError,
    ScheduleRunLock,
    ScheduledRunRecord,
    ScheduledRunStore,
    TaskSchedulerState,
    WindowsTaskSchedulerAdapter,
    _scheduled_for,
    format_next_scheduled_for,
    next_scheduled_for,
    build_task_xml,
)
from stock_tool.application.daily_research_loop import (
    DailyResearchEvent,
    DailyResearchSnapshot,
    DailyResearchSnapshotStore,
    DailyResearchSource,
)
from stock_tool.application.daily_research_brief import (
    DailyBriefSource,
    DailyResearchBrief,
    DailyResearchBriefApplicationService,
    DailyResearchBriefManifest,
    _content_fingerprint,
)
from stock_tool.application.daily_research_changes import (
    DailyResearchChangeApplicationService,
    DailyResearchChangeStore,
)
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.domain.models import Market, Symbol
from stock_tool.data.storage import PersistedPriceProvenance, SQLitePriceStorage


def _valid_change_brief(*, generated_at: str = "2026-08-10T10:00:00+00:00") -> DailyResearchBrief:
    manifest = DailyResearchBriefManifest(
        schema_version=2,
        brief_date="2026-08-10",
        as_of_date="2026-08-09",
        input_snapshot_id="snapshot",
        input_snapshot_hash="input-hash",
        processed_count=0,
        source_summaries=(
            DailyBriefSource(
                market="TWSE",
                source="cache",
                data_date="2026-08-09",
                fetched_at=generated_at,
                status="success",
                coverage=1.0,
                payload_sha256="payload",
            ),
        ),
        missing_or_stale=(),
        warnings=(),
        content_fingerprint="",
        references=(),
    )
    manifest = replace(
        manifest,
        content_fingerprint=_content_fingerprint(manifest, (), status="success", message="ok"),
    )
    return DailyResearchBrief(generated_at, "success", manifest, (), "ok")


def _stage_fault_market_result() -> Any:
    """Small valid same-date market result used by stage-boundary regressions."""

    snapshot = SimpleNamespace(
        metadata=SimpleNamespace(
            status="ready",
            freshness="fresh",
            data_date="2026-08-23",
        ),
        source_metadata=(SimpleNamespace(data_date="2026-08-23"),),
        to_dict=lambda: {
            "metadata": {
                "status": "ready",
                "freshness": "fresh",
                "data_date": "2026-08-23",
            },
            "source_metadata": [{"data_date": "2026-08-23"}],
        },
    )
    return SimpleNamespace(
        status="fresh",
        source_state="official",
        snapshot=snapshot,
        warnings=(),
    )


def _prepare_stage_fault_runner(monkeypatch, tmp_path: Path):
    """Configure a real HeadlessDailyResearchRunner with deterministic local inputs."""

    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    paths.portfolio_file.write_text(
        "symbol,market,quantity,average_cost\n2330,TWSE,1,600\n", encoding="utf-8"
    )
    frame = pd.DataFrame([{"symbol": "2330", "market": "TWSE", "quantity": 1.0}])
    monkeypatch.setattr(scheduler_module, "load_portfolio", lambda _path: frame)
    monkeypatch.setattr(scheduler_module, "load_watchlist", lambda _path: frame.iloc[0:0])
    monkeypatch.setattr(scheduler_module, "build_effective_watchlist", lambda _w, _p: frame)
    monkeypatch.setattr(scheduler_module, "_input_snapshot_hash", lambda *_a, **_k: "input-hash")
    monkeypatch.setattr(scheduler_module, "_refresh_existing_provider", lambda *_args: ())
    monkeypatch.setattr(
        scheduler_module,
        "_load_price_context",
        lambda _paths: (
            pd.DataFrame(
                [{"symbol": "2330", "market": "TWSE", "date": "2026-08-23", "close": 600.0}]
            ),
            {"TWSE:2330": "2026-08-23T10:00:00+00:00"},
        ),
    )
    monkeypatch.setattr(scheduler_module, "_load_local_valuation", lambda *_args: None)
    monkeypatch.setattr(
        scheduler_module, "_load_local_research_continuations", lambda *_args, **_kwargs: ()
    )
    monkeypatch.setattr(scheduler_module, "_load_local_fundamental_scores", lambda *_args: None)
    monkeypatch.setattr(scheduler_module.DailyBriefService, "build", lambda *_a, **_k: object())
    monkeypatch.setattr(
        scheduler_module.DailyResearchLoopService,
        "complete_success",
        lambda *_a, **_k: SimpleNamespace(snapshot=object()),
    )
    brief = _valid_change_brief(generated_at="2026-08-24T10:00:00+00:00")
    monkeypatch.setattr(
        scheduler_module.DailyResearchBriefApplicationService,
        "generate",
        lambda *_a, **_k: brief,
    )

    class BriefStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def load(self):
            return None

        def history(self):
            return ()

        def save(self, _brief):
            return None

    class ChangeStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def save(self, _change):
            return None

    monkeypatch.setattr(scheduler_module, "DailyResearchBriefStore", BriefStore)
    monkeypatch.setattr(scheduler_module, "DailyResearchChangeStore", ChangeStore)
    monkeypatch.setattr(
        scheduler_module.DailyResearchChangeApplicationService,
        "compare",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(scheduler_module.DailyResearchSnapshotStore, "save", lambda *_a, **_k: None)
    monkeypatch.setattr(
        scheduler_module,
        "PredictionLabApplicationService",
        lambda *_a, **_k: SimpleNamespace(
            register_from_market_snapshot=lambda *_a, **_k: SimpleNamespace(
                status="success", records=(), created_count=0, skipped_count=1
            )
        ),
    )
    monkeypatch.setattr(
        scheduler_module.PredictionLabStore,
        "from_runtime_paths",
        lambda _paths: SimpleNamespace(ensure=lambda: object()),
    )
    return paths


@pytest.mark.parametrize(
    "fault_stage",
    ["price_context", "daily_brief_build", "brief_generate", "brief_save", "snapshot_save"],
)
def test_headless_stage_exception_preserves_completed_trace(
    monkeypatch, tmp_path: Path, fault_stage: str
) -> None:
    paths = _prepare_stage_fault_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler_module, "economic_input_fingerprint", lambda *_a, **_k: "economic-hash"
    )
    if fault_stage == "price_context":
        monkeypatch.setattr(
            scheduler_module,
            "_load_price_context",
            lambda *_a: (_ for _ in ()).throw(RuntimeError("price")),
        )
    elif fault_stage == "daily_brief_build":
        monkeypatch.setattr(
            scheduler_module.DailyBriefService,
            "build",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("brief")),
        )
    elif fault_stage == "brief_generate":
        monkeypatch.setattr(
            scheduler_module.DailyResearchBriefApplicationService,
            "generate",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("generate")),
        )
    elif fault_stage == "brief_save":
        monkeypatch.setattr(
            scheduler_module.DailyResearchBriefStore,
            "save",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("save")),
        )
    elif fault_stage == "snapshot_save":
        monkeypatch.setattr(
            scheduler_module.DailyResearchSnapshotStore,
            "save",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("snapshot")),
        )

    outcome = scheduler_module.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        market_refresh_callback=lambda: _stage_fault_market_result(),
    ).run(trigger="manual")
    assert [stage.name for stage in outcome.stages] == list(scheduler_module.RUN_STAGE_NAMES)
    assert [stage.status for stage in outcome.stages] == [
        "success",
        "success",
        "failure",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]
    assert outcome.stages[2].reason
    assert all("前一階段" in (stage.reason or "") for stage in outcome.stages[3:])


def test_headless_target_exception_fails_closed_with_complete_trace(
    monkeypatch, tmp_path: Path
) -> None:
    paths = _prepare_stage_fault_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler_module,
        "_refresh_existing_provider",
        lambda *_a: (_ for _ in ()).throw(RuntimeError("target")),
    )
    market_calls: list[str] = []

    def market_callback() -> Any:
        market_calls.append("market")
        return _stage_fault_market_result()

    outcome = scheduler_module.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        market_refresh_callback=market_callback,
    ).run(trigger="manual")
    assert outcome.status == "failed"
    assert [stage.status for stage in outcome.stages] == [
        "failure",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]
    assert market_calls == []


def test_evidence_target_refresh_replays_preloaded_rows_without_provider(
    monkeypatch, tmp_path: Path
) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    symbol = Symbol.parse("2330", market="TWSE")
    SQLitePriceStorage(paths.processed_dir / "stock_data.sqlite").save_market_qualified_price_data(
        [
            {
                "date": "2026-08-23",
                "symbol": "2330",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
                "adjusted_close": None,
            }
        ],
        provenance=PersistedPriceProvenance(
            symbol=symbol,
            provider="official-fixture",
            provider_symbol="2330",
            source_type="evidence_fixture",
            last_data_date="2026-08-23",
            checked_at="2026-08-24T10:00:00+00:00",
        ),
    )
    monkeypatch.setenv("STOCK_TOOL_EVIDENCE_MODE", "sprint32.1.1")

    assert scheduler_module._refresh_existing_provider((symbol,), paths) == ()


def test_headless_market_exception_fails_closed_with_complete_trace(
    monkeypatch, tmp_path: Path
) -> None:
    paths = _prepare_stage_fault_runner(monkeypatch, tmp_path)
    outcome = scheduler_module.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        market_refresh_callback=lambda: (_ for _ in ()).throw(RuntimeError("market")),
    ).run(trigger="manual")
    assert outcome.status == "failed"
    assert [stage.status for stage in outcome.stages] == [
        "success",
        "failure",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]


@pytest.mark.parametrize(
    ("mode", "expected_stage", "expected_overall"),
    [
        ("absent", "unavailable", "partial"),
        ("disabled", "unavailable", "partial"),
        ("unavailable", "unavailable", "partial"),
        ("sent", "success", "success"),
        ("failed", "failure", "partial"),
        ("duplicate", "skipped", "success"),
        ("exception", "failure", "partial"),
    ],
)
def test_headless_notification_stage_matrix_uses_real_runner(
    monkeypatch,
    tmp_path: Path,
    mode: str,
    expected_stage: str,
    expected_overall: str,
) -> None:
    """Notification outcomes are recorded by the real six-stage runner."""

    paths = _prepare_stage_fault_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler_module, "economic_input_fingerprint", lambda *_a, **_k: "economic-hash"
    )
    monkeypatch.setattr(
        scheduler_module,
        "PredictionLabApplicationService",
        lambda *_a, **_k: SimpleNamespace(
            register_from_market_snapshot=lambda *_a, **_k: SimpleNamespace(
                status="success",
                records=(SimpleNamespace(prediction_id="TWSE:2330"),),
                created_count=1,
                skipped_count=0,
            )
        ),
    )
    calls: list[str] = []

    def callback(*_args, **_kwargs):
        calls.append(mode)
        if mode == "sent":
            return SimpleNamespace(status="sent", reason=None)
        if mode == "duplicate":
            return SimpleNamespace(status="unavailable", reason="已去重")
        if mode == "disabled":
            return SimpleNamespace(status="unavailable", reason="通知未啟用")
        if mode == "unavailable":
            return SimpleNamespace(status="unavailable", reason="Windows 通知目前不可用")
        if mode == "failed":
            return SimpleNamespace(status="failed", reason="通知發送失敗")
        if mode == "exception":
            raise RuntimeError("notifier failure")
        raise AssertionError("unexpected callback mode")

    outcome = scheduler_module.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        market_refresh_callback=_stage_fault_market_result,
        on_success=None if mode == "absent" else callback,
    ).run(trigger="manual")

    assert outcome.status == expected_overall
    assert [stage.name for stage in outcome.stages] == list(scheduler_module.RUN_STAGE_NAMES)
    assert outcome.stages[-1].status == expected_stage
    assert calls == ([] if mode == "absent" else [mode])
    assert outcome.stages[4].status == "success"


@pytest.mark.parametrize(
    ("case", "market_status", "prediction_status", "expected_overall"),
    [
        ("fresh_new", "success", "success", "success"),
        ("duplicate", "success", "skipped", "success"),
        ("stale", "unavailable", "skipped", "partial"),
        ("partial", "partial", "skipped", "partial"),
        ("unavailable", "unavailable", "skipped", "partial"),
        ("date_mismatch", "unavailable", "skipped", "partial"),
        ("registration_unavailable", "success", "unavailable", "partial"),
        ("registration_exception", "success", "failure", "failed"),
    ],
)
def test_headless_prediction_registration_matrix_is_fail_closed(
    monkeypatch,
    tmp_path: Path,
    case: str,
    market_status: str,
    prediction_status: str,
    expected_overall: str,
) -> None:
    """Only one complete fresh snapshot can create a sample."""

    paths = _prepare_stage_fault_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler_module, "economic_input_fingerprint", lambda *_a, **_k: "economic-hash"
    )
    base = _stage_fault_market_result()
    if case == "stale":
        base.status = "stale"
        base.snapshot.metadata = SimpleNamespace(
            status="stale", freshness="stale", data_date="2026-08-23"
        )
    elif case == "partial":
        base.status = "partial"
    elif case == "unavailable":
        base = SimpleNamespace(
            status="unavailable", source_state="missing", snapshot=None, warnings=()
        )
    elif case == "date_mismatch":
        base.snapshot.source_metadata = (
            SimpleNamespace(data_date="2026-08-23"),
            SimpleNamespace(data_date="2026-08-22"),
        )
    calls: list[str] = []

    def register(*_args, **_kwargs):
        calls.append(case)
        if case == "registration_exception":
            raise RuntimeError("registration")
        if case == "registration_unavailable":
            return SimpleNamespace(
                status="unavailable",
                records=(),
                created_count=0,
                skipped_count=0,
                message="暫不可用",
            )
        if case == "duplicate":
            return SimpleNamespace(status="success", records=(), created_count=0, skipped_count=1)
        return SimpleNamespace(
            status="success",
            records=(SimpleNamespace(prediction_id="TWSE:2330"),),
            created_count=1,
            skipped_count=0,
        )

    monkeypatch.setattr(
        scheduler_module,
        "PredictionLabApplicationService",
        lambda *_a, **_k: SimpleNamespace(register_from_market_snapshot=register),
    )
    outcome = scheduler_module.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        market_refresh_callback=lambda: base,
        on_success=lambda *_a, **_k: SimpleNamespace(status="sent", reason=None),
    ).run(trigger="manual")

    assert outcome.status == expected_overall
    assert outcome.stages[1].status == market_status
    assert outcome.stages[4].status == prediction_status
    assert outcome.stages[5].status == "skipped"
    assert outcome.stages[6].status == (
        "skipped" if case == "registration_exception" else "success"
    )
    assert calls == ([] if case in {"stale", "partial", "unavailable", "date_mismatch"} else [case])


def test_headless_outcome_evaluation_stage_uses_current_as_of_and_injected_provider(
    monkeypatch, tmp_path: Path
) -> None:
    paths = _prepare_stage_fault_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler_module,
        "economic_input_fingerprint",
        lambda *_a, **_k: "economic-hash",
    )
    monkeypatch.setattr(
        scheduler_module,
        "PredictionLabApplicationService",
        lambda *_a, **_k: SimpleNamespace(
            register_from_market_snapshot=lambda *_a, **_k: SimpleNamespace(
                status="success",
                records=(SimpleNamespace(prediction_id="TWSE:2330"),),
                created_count=1,
                skipped_count=0,
            )
        ),
    )
    calls: list[str] = []

    class FakeEvaluator:
        def __init__(self, _store, provider, *, now_fn):
            assert provider is provider_token
            assert now_fn() == datetime(2026, 8, 24, 10, tzinfo=timezone.utc)

        def evaluate_due(self, *, as_of: str):
            calls.append(as_of)
            return SimpleNamespace(status="success", outcomes=())

    provider_token = object()
    monkeypatch.setattr(scheduler_module, "PredictionOutcomeEvaluator", FakeEvaluator)
    outcome = scheduler_module.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        market_refresh_callback=_stage_fault_market_result,
        prediction_outcome_provider=cast(Any, provider_token),
        on_success=lambda *_a, **_k: SimpleNamespace(status="sent", reason=None),
    ).run(trigger="manual")

    assert outcome.stages[5].status == "success"
    assert calls == ["2026-08-24"]


def test_schedule_defaults_are_disabled_and_weekday_bound() -> None:
    settings = DailyScheduleSettings.default(now=datetime(2026, 8, 9, tzinfo=timezone.utc))
    assert settings.enabled is False
    assert settings.timezone == "Asia/Taipei"
    assert settings.weekdays == (0, 1, 2, 3, 4)
    assert settings.local_time == "18:30"
    assert settings.execution_time_limit_minutes == 30


def test_scheduled_window_uses_timezone_and_missed_grace() -> None:
    settings = DailyScheduleSettings(missed_run_grace_minutes=10)
    before = datetime(2026, 8, 10, 10, 29, tzinfo=timezone.utc)
    on_time = datetime(2026, 8, 10, 10, 35, tzinfo=timezone.utc)
    late = datetime(2026, 8, 10, 11, 0, tzinfo=timezone.utc)
    assert _scheduled_for(before, settings) is None
    assert _scheduled_for(on_time, settings) is not None
    assert _scheduled_for(late, settings) is None


def test_schedule_without_start_when_available_requires_configured_minute() -> None:
    settings = DailyScheduleSettings(start_when_available=False)
    assert _scheduled_for(datetime(2026, 8, 10, 10, 31, tzinfo=timezone.utc), settings) is None


def test_next_scheduled_time_skips_weekend() -> None:
    settings = DailyScheduleSettings()
    next_run = next_scheduled_for(datetime(2026, 8, 8, 10, tzinfo=timezone.utc), settings)
    assert next_run is not None
    assert "2026-08-10T10:30:00" in next_run
    assert (
        format_next_scheduled_for(datetime(2026, 8, 8, 10, tzinfo=timezone.utc), settings)
        == "2026-08-10 18:30 (Asia/Taipei)"
    )


@pytest.mark.parametrize("field", ["enabled", "start_when_available"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1, [], {}])
def test_schedule_boolean_fields_are_strict(field: str, value: object) -> None:
    payload = DailyScheduleSettings().to_dict()
    payload[field] = value
    with pytest.raises(ValueError, match="boolean"):
        DailyScheduleSettings.from_dict(payload)


def test_settings_store_rejects_corrupt_json_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "schedule-settings.json"
    path.write_text("not json", encoding="utf-8")
    store = DailyScheduleSettingsStore(path)
    loaded = store.load()
    assert loaded.enabled is False
    assert store.last_warning is not None
    assert path.read_text(encoding="utf-8") == "not json"


def test_settings_store_rejects_non_boolean_and_stays_disabled(tmp_path: Path) -> None:
    path = tmp_path / "schedule-settings.json"
    payload = DailyScheduleSettings().to_dict()
    payload["enabled"] = "false"
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = DailyScheduleSettingsStore(path)
    loaded = store.load()
    assert loaded.enabled is False
    assert store.last_warning == "schedule settings are unavailable or corrupt"


def test_settings_store_writes_utf8_atomically(tmp_path: Path) -> None:
    path = tmp_path / "schedule-settings.json"
    store = DailyScheduleSettingsStore(path)
    settings = DailyScheduleSettings(enabled=True)
    store.save(settings)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["enabled"] is True
    assert payload["schema_version"] == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_lock_rejects_live_owner_and_reclaims_dead_owner(tmp_path: Path) -> None:
    path = tmp_path / "schedule.lock"
    first = ScheduleRunLock(path, pid_alive=lambda pid: pid == 123)
    first.acquire(run_id="one", now=datetime.now(timezone.utc))
    second = ScheduleRunLock(path, pid_alive=lambda _pid: True)
    with pytest.raises(ScheduleLockError, match="already running"):
        second.acquire(run_id="two", now=datetime.now(timezone.utc))
    first.release()

    path.write_text(json.dumps({"pid": 999}), encoding="utf-8")
    reclaimed = ScheduleRunLock(path, pid_alive=lambda _pid: False)
    reclaimed.acquire(run_id="three", now=datetime.now(timezone.utc))
    assert path.is_file()
    reclaimed.release()
    assert not path.exists()


def test_malformed_lock_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "schedule.lock"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(ScheduleLockError, match="malformed"):
        ScheduleRunLock(path, pid_alive=lambda _pid: False).acquire(
            run_id="one", now=datetime.now(timezone.utc)
        )
    assert path.read_text(encoding="utf-8") == "broken"


def test_run_store_keeps_immutable_records_and_latest(tmp_path: Path) -> None:
    store = ScheduledRunStore(tmp_path / "latest.json", tmp_path / "runs")
    record = ScheduledRunRecord(
        run_id="run-1",
        trigger="manual",
        scheduled_for=None,
        started_at="2026-08-09T00:00:00+00:00",
        completed_at="2026-08-09T00:01:00+00:00",
        status="success",
        exit_code=0,
        input_snapshot_hash="A",
        output_brief_fingerprint="B",
        data_as_of="2026-08-08",
        deterministic_fallback_used=True,
        reason=None,
        duration_seconds=60.0,
    )
    store.save(record)
    assert store.load_latest() == record
    assert (tmp_path / "runs" / "run-1.json").is_file()
    with pytest.raises(FileExistsError):
        store.save(record)


def _record(
    run_id: str, completed_at: datetime, *, scheduled_for: str | None = None
) -> ScheduledRunRecord:
    return ScheduledRunRecord(
        run_id=run_id,
        trigger="scheduled" if scheduled_for else "manual",
        scheduled_for=scheduled_for,
        started_at=(completed_at - timedelta(minutes=1)).isoformat(),
        completed_at=completed_at.isoformat(),
        status="success",
        exit_code=0,
        input_snapshot_hash="same-input",
        output_brief_fingerprint=f"brief-{run_id}",
        data_as_of="2026-08-09",
        deterministic_fallback_used=True,
        reason=None,
        duration_seconds=60.0,
    )


def test_run_store_history_projection_is_object_and_bounded(tmp_path: Path) -> None:
    store = ScheduledRunStore(tmp_path / "latest.json", tmp_path / "runs")
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for index in range(31):
        store.save(_record(f"run-{index:02d}", start + timedelta(minutes=index)))
    assert len(store.records()) == 31
    assert [record.run_id for record in store.load_history()] == [
        f"run-{index:02d}" for index in range(1, 31)
    ]
    projection = json.loads((tmp_path / "runs" / "history.json").read_text(encoding="utf-8"))
    assert isinstance(projection, dict)
    assert [item["run_id"] for item in projection["runs"]] == [
        f"run-{index:02d}" for index in range(1, 31)
    ]
    latest = store.load_latest()
    assert latest is not None
    assert latest.run_id == "run-30"


@pytest.mark.parametrize("failure_name", ["run-2.json", "history.json", "latest.json"])
def test_run_store_publish_faults_leave_recoverable_authority(
    tmp_path: Path, failure_name: str
) -> None:
    armed = False

    def writer(path: Path, payload: Mapping[str, object]) -> None:
        if armed and path.name == failure_name:
            raise OSError(f"injected {failure_name} failure")
        scheduler_module._atomic_json_write(path, payload)

    store = ScheduledRunStore(tmp_path / "latest.json", tmp_path / "runs", atomic_write=writer)
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    store.save(_record("run-1", start))
    armed = True
    with pytest.raises(OSError):
        store.save(_record("run-2", start + timedelta(minutes=1)))
    armed = False
    records = store.records()
    if failure_name == "run-2.json":
        assert [record.run_id for record in records] == ["run-1"]
        store.save(_record("run-2", start + timedelta(minutes=1)))
    else:
        assert [record.run_id for record in records] == ["run-1", "run-2"]
    store.rebuild_projections()
    latest = store.load_latest()
    assert latest is not None
    assert latest.run_id == "run-2"


def test_run_store_reads_scheduled_window_from_immutable_records(tmp_path: Path) -> None:
    store = ScheduledRunStore(tmp_path / "latest.json", tmp_path / "runs")
    scheduled_for = "2026-08-10T10:30:00+00:00"
    store.save(
        _record(
            "run-scheduled",
            datetime(2026, 8, 10, 10, 31, tzinfo=timezone.utc),
            scheduled_for=scheduled_for,
        )
    )
    (tmp_path / "runs" / "history.json").write_text(
        json.dumps({"schema_version": 1, "runs": []}), encoding="utf-8"
    )
    assert store.has_scheduled_for(scheduled_for) is True


def test_task_xml_is_escaped_and_contains_safety_contract() -> None:
    settings = DailyScheduleSettings(enabled=True)
    xml = build_task_xml(
        settings,
        task_name=r"\StockTool\Acceptance\Nonce<&",
        stable_entry=r"C:\Program Files\StockTool\StockTool.exe",
        username="USER<&",
    )
    assert "InteractiveToken" in xml
    assert "LeastPrivilege" in xml
    assert "IgnoreNew" in xml
    assert "StartWhenAvailable" in xml
    assert "PT30M" in xml
    assert "Asia/Taipei" in xml
    assert "--daily-research-run --trigger scheduled" in xml
    assert "Program Files" in xml
    assert "&lt;" in xml


def test_task_xml_maps_python_weekdays_to_exact_windows_days() -> None:
    settings = DailyScheduleSettings(enabled=True)
    xml = build_task_xml(
        settings,
        task_name=DAILY_RESEARCH_TASK_NAME,
        stable_entry=r"C:\StockTool\StockTool.exe",
        username="USER",
    )
    root = ET.fromstring(xml)
    days = {
        element.tag.rsplit("}", 1)[-1]
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1]
        in {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    }
    assert days == {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}
    assert "Sunday" not in days


def test_adapter_query_and_actions_are_injected_and_non_shell() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        calls.append(normalized)
        if normalized[1] == "/Query":
            return subprocess.CompletedProcess(
                normalized, 0, "<Task><Triggers><Enabled>true</Enabled></Triggers></Task>", ""
            )
        return subprocess.CompletedProcess(normalized, 0, "", "")

    adapter = WindowsTaskSchedulerAdapter(command_runner=runner)
    assert adapter.query() == TaskSchedulerState(
        "enabled", "", "<Task><Triggers><Enabled>true</Enabled></Triggers></Task>"
    )
    adapter.disable()
    assert calls[0] == ("schtasks.exe", "/Query", "/TN", DAILY_RESEARCH_TASK_NAME, "/XML")
    assert calls[-2][:4] == ("schtasks.exe", "/Change", "/TN", DAILY_RESEARCH_TASK_NAME)
    assert all(isinstance(item, tuple) for item in calls)


def test_adapter_query_uses_xml_then_language_stable_state_field() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        calls.append(normalized)
        if normalized[-1] == "/XML":
            return subprocess.CompletedProcess(normalized, 0, "<Task />", "")
        return subprocess.CompletedProcess(normalized, 0, "Scheduled Task State: Enabled\n", "")

    state = WindowsTaskSchedulerAdapter(command_runner=runner).query()
    assert state.status == "enabled"
    assert calls[0][-1] == "/XML"
    assert calls[1][-3:] == ("/FO", "LIST", "/V")


def test_adapter_query_maps_missing_list_state_to_not_installed() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        calls.append(normalized)
        if normalized[-1] == "/XML":
            return subprocess.CompletedProcess(normalized, 0, "<Task />", "")
        return subprocess.CompletedProcess(
            normalized, 1, "", "ERROR: The system cannot find the path specified."
        )

    state = WindowsTaskSchedulerAdapter(command_runner=runner).query()
    assert state.status == "not_installed"
    assert calls[1][-3:] == ("/FO", "LIST", "/V")


def _adapter_query_localized_not_found_fixture() -> None:
    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(tuple(command), 1, "", "指定されたタスクが存在しません")

    assert WindowsTaskSchedulerAdapter(command_runner=runner).query().status == "not_installed"


def test_adapter_query_localized_not_found_is_not_installed() -> None:
    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            tuple(command), 1, "", "\u627e\u4e0d\u5230\u6307\u5b9a\u7684\u5de5\u4f5c"
        )

    assert WindowsTaskSchedulerAdapter(command_runner=runner).query().status == "not_installed"


def test_task_not_found_detection_covers_actual_english_and_localized_outputs() -> None:
    messages = (
        "ERROR: The system cannot find the path specified.",
        "ERROR: The system cannot find the file specified.",
        "\u6307\u5b9a\u3055\u308c\u305f\u30bf\u30b9\u30af\u304c\u5b58\u5728\u3057\u307e\u305b\u3093",
        "找不到指定的工作",
        "無法找到指定的工作",
    )
    assert all(scheduler_module._task_not_found(message) for message in messages)


def test_subprocess_runner_resolves_systemroot_for_frozen_launch(
    monkeypatch, tmp_path: Path
) -> None:
    scheduler = tmp_path / "System32" / "schtasks.exe"
    scheduler.parent.mkdir()
    scheduler.write_bytes(b"")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.delenv("WINDIR", raising=False)
    monkeypatch.setattr(scheduler_module.os, "name", "nt")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = tuple(command)
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            tuple(command), 1, "", "ERROR: The system cannot find the path specified."
        )

    monkeypatch.setattr(scheduler_module.subprocess, "run", fake_run)
    result = scheduler_module._subprocess_runner(("schtasks.exe", "/Query"))
    assert result.returncode == 1
    assert captured["command"] == (str(scheduler), "/Query")
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["encoding"] == "mbcs"
    assert kwargs.get("shell", False) is not True


def test_schtasks_resolution_has_safe_fallback_without_windows_roots(monkeypatch) -> None:
    monkeypatch.delenv("SystemRoot", raising=False)
    monkeypatch.delenv("WINDIR", raising=False)
    monkeypatch.setattr(scheduler_module.shutil, "which", lambda _name: None)
    assert scheduler_module._resolve_schtasks_executable() == "schtasks.exe"


def test_non_windows_scheduler_encoding_falls_back_to_utf8(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_module.os, "name", "posix")
    monkeypatch.setattr(scheduler_module.locale, "getpreferredencoding", lambda _do_set: "")
    assert scheduler_module._windows_command_encoding() == "utf-8"


@pytest.mark.skipif(os.name != "nt", reason="requires the Windows Task Scheduler binary")
def test_actual_missing_production_task_is_not_installed() -> None:
    state = WindowsTaskSchedulerAdapter().query()
    assert state.status == "not_installed"


def test_adapter_run_now_does_not_send_run_for_missing_task() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        return subprocess.CompletedProcess(tuple(command), 1, "", "The task does not exist")

    state = WindowsTaskSchedulerAdapter(command_runner=runner).run_now()
    assert state.status == "not_installed"
    assert all("/Run" not in call for call in calls)


def test_new_manual_date_with_same_hash_still_refreshes(tmp_path: Path, monkeypatch) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    paths.portfolio_file.write_text(
        "symbol,market,quantity,average_cost\n2330,TWSE,1,600\n", encoding="utf-8"
    )
    frame = pd.DataFrame([{"symbol": "2330", "market": "TWSE"}])
    monkeypatch.setattr(scheduler_module, "load_portfolio", lambda _path: frame)
    monkeypatch.setattr(scheduler_module, "load_watchlist", lambda _path: frame.iloc[0:0])
    monkeypatch.setattr(scheduler_module, "build_effective_watchlist", lambda _w, _p: frame)
    monkeypatch.setattr(
        scheduler_module, "_input_snapshot_hash", lambda *_args, **_kwargs: "same-input"
    )
    previous = _record(
        "run-yesterday",
        datetime(2026, 8, 9, 10, 31, tzinfo=timezone.utc),
        scheduled_for="2026-08-09T10:30:00+00:00",
    )
    ScheduledRunStore(paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir).save(
        previous
    )
    calls: list[tuple[str, ...]] = []
    now = datetime(2026, 8, 10, 10, 35, tzinfo=timezone.utc)

    def refresh(identities: tuple[Symbol, ...], _paths: RuntimePaths) -> tuple[str, ...]:
        calls.append(tuple(item.canonical for item in identities))
        return ()

    runner = HeadlessDailyResearchRunner(
        paths, now_fn=lambda: now, refresh_callback=cast(DailyResearchRefreshCallback, refresh)
    )
    outcome = runner.run(trigger="manual")
    assert outcome.status == "skipped_no_new_data"
    assert calls == [("TWSE:2330",)]
    assert [stage.name for stage in outcome.stages] == list(scheduler_module.RUN_STAGE_NAMES)
    assert outcome.stages[5].status == "skipped"


def test_corrupt_immutable_brief_history_never_mints_a_new_baseline(
    tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A bad history is a security event, not equivalent to no history."""

    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    frame = pd.DataFrame([{"symbol": "2330", "market": "TWSE", "quantity": 1.0}])
    monkeypatch.setattr(scheduler_module, "load_portfolio", lambda _path: frame)
    monkeypatch.setattr(scheduler_module, "load_watchlist", lambda _path: frame.iloc[0:0])
    monkeypatch.setattr(scheduler_module, "build_effective_watchlist", lambda _w, _p: frame)
    monkeypatch.setattr(
        scheduler_module, "_load_price_context", lambda _paths: (pd.DataFrame(), {})
    )
    monkeypatch.setattr(scheduler_module.DailyBriefService, "build", lambda *_a, **_k: object())
    monkeypatch.setattr(
        scheduler_module.DailyResearchLoopService,
        "complete_success",
        lambda *_a, **_k: SimpleNamespace(snapshot=None),
    )
    fresh = _valid_change_brief()
    monkeypatch.setattr(DailyResearchBriefApplicationService, "generate", lambda *_a, **_k: fresh)
    paths.daily_research_brief_history_dir.mkdir(parents=True, exist_ok=True)
    (paths.daily_research_brief_history_dir / "brief-corrupt.json").write_text(
        "{}", encoding="utf-8"
    )
    previous_change = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, 10, tzinfo=timezone.utc)
    ).compare(fresh)
    change_store = DailyResearchChangeStore(
        paths.daily_research_change_file, paths.daily_research_change_history_dir
    )
    change_store.save(previous_change)
    runner = HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 10, 10, 1, tzinfo=timezone.utc),
        refresh_callback=lambda *_args: (),
    )
    outcome = runner.run(trigger="manual")
    # The corrupt history is preserved, while the absent market snapshot keeps
    # this run partial rather than fabricating a complete success.
    assert outcome.status == "partial"
    assert change_store.load() == previous_change
    assert "preserving prior summary" in caplog.text


def test_local_continuation_falls_back_to_prior_snapshot_without_current_brief(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path).ensure_directories()
    symbol = Symbol.parse("2330", market=Market.TWSE)
    event = DailyResearchEvent(
        identity=symbol.canonical,
        category="new_change",
        priority=70,
        code="research_coverage",
        title="coverage",
        why_important="coverage evidence",
        current_value="100.0%",
        baseline_value=None,
        baseline_as_of=None,
        source=DailyResearchSource(
            provider="local",
            source_type="cache",
            provider_symbol=None,
            last_data_date="2026-08-07",
            checked_at="2026-08-08T00:00:00+00:00",
        ),
        as_of_date="2026-08-07",
        action="open_research",
        field="research_coverage",
    )
    DailyResearchSnapshotStore(paths.daily_research_snapshot_file).save(
        DailyResearchSnapshot(
            schema_version=1,
            successful_at="2026-08-08T00:00:00+00:00",
            data_as_of_date="2026-08-07",
            events=(event,),
        )
    )
    continuations = scheduler_module._load_local_research_continuations(paths, identities=(symbol,))
    assert [(item.symbol.canonical, item.coverage) for item in continuations] == [
        ("TWSE:2330", 1.0)
    ]


def test_same_scheduled_window_deduplicates_before_refresh(tmp_path: Path, monkeypatch) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    frame = pd.DataFrame([{"symbol": "2330", "market": "TWSE"}])
    paths.portfolio_file.write_text(
        "symbol,market,quantity,average_cost\n2330,TWSE,1,600\n", encoding="utf-8"
    )
    monkeypatch.setattr(scheduler_module, "load_portfolio", lambda _path: frame)
    monkeypatch.setattr(scheduler_module, "load_watchlist", lambda _path: frame.iloc[0:0])
    monkeypatch.setattr(scheduler_module, "build_effective_watchlist", lambda _w, _p: frame)
    calls: list[str] = []
    now = datetime(2026, 8, 10, 10, 35, tzinfo=timezone.utc)
    scheduled_for = "2026-08-10T10:30:00+00:00"
    ScheduledRunStore(paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir).save(
        _record("run-existing", now, scheduled_for=scheduled_for)
    )
    DailyScheduleSettingsStore(paths.daily_schedule_settings_file).save(
        DailyScheduleSettings(enabled=True)
    )

    def refresh(_identities: tuple[Symbol, ...], _paths: RuntimePaths) -> tuple[str, ...]:
        calls.append("refresh")
        return ()

    runner = HeadlessDailyResearchRunner(
        paths, now_fn=lambda: now, refresh_callback=cast(DailyResearchRefreshCallback, refresh)
    )
    outcome = runner.run(trigger="scheduled")
    assert outcome.status == "skipped_no_new_data"
    assert calls == []
    assert [stage.name for stage in outcome.stages] == list(scheduler_module.RUN_STAGE_NAMES)


def test_headless_runner_dry_run_is_bounded_and_persists_status(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    paths.portfolio_file.write_text(
        "symbol,market,quantity,average_cost\n2330,TWSE,1,600\n", encoding="utf-8"
    )
    outcome = HeadlessDailyResearchRunner(paths).run(trigger="manual", dry_run=True)
    assert outcome.exit_code == EXIT_SKIPPED
    assert outcome.status == "skipped_dry_run"
    assert outcome.record.deterministic_fallback_used is True
    assert paths.daily_schedule_latest_run_file.is_file()


def test_headless_runner_second_live_lock_returns_already_running(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    paths.daily_schedule_lock_file.write_text(
        json.dumps({"pid": 42, "run_id": "existing"}), encoding="utf-8"
    )
    runner = HeadlessDailyResearchRunner(
        paths, lock=ScheduleRunLock(paths.daily_schedule_lock_file, pid_alive=lambda _pid: True)
    )
    outcome = runner.run(trigger="manual", dry_run=True)
    assert outcome.status == "already_running"
    assert outcome.exit_code == EXIT_ALREADY_RUNNING


def test_runtime_paths_include_private_scheduler_state(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    assert paths.daily_schedule_settings_file.parent == paths.daily_schedule_dir
    assert paths.daily_schedule_runs_dir.is_dir()
    assert not (tmp_path / "runtime" / "schedule-settings.json").exists()
