from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

import pytest

from stock_tool.application.daily_research_brief import (
    DailyBriefSource,
    DailyResearchBrief,
    DailyResearchBriefManifest,
    DailyResearchBriefStore,
    _content_fingerprint,
)
from stock_tool.application.daily_research_changes import (
    DailyResearchChangeApplicationService,
    DailyResearchChangeStore,
)
from stock_tool.application.daily_research_inbox import (
    DailyResearchInboxService,
    DailyResearchNotificationService,
    DeterministicFakeNotifier,
    NotificationLedgerError,
    NotificationClaimRecord,
    NotificationLedgerRecord,
    NotificationLedgerStore,
    NotificationRequest,
    WindowsNotificationAdapter,
    NotificationResult,
    NotificationSettings,
    NotificationSettingsStore,
    _atomic_create_json,
)
from stock_tool.application.daily_research_scheduler import ScheduledRunRecord
from stock_tool.runtime_paths import RuntimePaths


def _brief(*, fingerprint_source: str = "cache") -> DailyResearchBrief:
    manifest = DailyResearchBriefManifest(
        schema_version=2,
        brief_date="2026-08-09",
        as_of_date="2026-08-08",
        input_snapshot_id="snapshot-1",
        input_snapshot_hash="input-hash",
        processed_count=1,
        source_summaries=(
            DailyBriefSource(
                market="TWSE",
                source=fingerprint_source,
                data_date="2026-08-08",
                fetched_at="2026-08-09T10:00:00+00:00",
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
    fingerprint = _content_fingerprint(manifest, (), status="success", message="可用")
    manifest = replace(manifest, content_fingerprint=fingerprint)
    return DailyResearchBrief(
        generated_at="2026-08-09T10:00:00+00:00",
        status="success",
        manifest=manifest,
        items=(),
        message="可用",
    )


def _record(
    run_id: str,
    brief: DailyResearchBrief,
    completed_at: datetime,
    *,
    status: str = "success",
    exit_code: int = 0,
) -> ScheduledRunRecord:
    return ScheduledRunRecord(
        run_id=run_id,
        trigger="manual",
        scheduled_for=None,
        started_at=(completed_at - timedelta(seconds=1)).isoformat(),
        completed_at=completed_at.isoformat(),
        status=status,
        exit_code=exit_code,
        input_snapshot_hash="input",
        output_brief_fingerprint=(
            brief.manifest.content_fingerprint if status == "success" else None
        ),
        data_as_of="2026-08-08",
        deterministic_fallback_used=True,
        reason="資料不足" if status != "success" else None,
        duration_seconds=1.0,
    )


def test_notification_settings_are_disabled_and_strict(tmp_path: Path) -> None:
    path = tmp_path / "notification-settings.json"
    store = NotificationSettingsStore(path)
    assert store.load().enabled is False
    values: tuple[object, ...] = ("false", "true", 0, 1, [], {})
    for value in values:
        payload = NotificationSettings().to_dict()
        payload["enabled"] = value
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert store.load().enabled is False
        assert store.last_warning is not None


def test_success_brief_notifies_once_across_recreated_service(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    brief_store = DailyResearchBriefStore(
        paths.daily_research_brief_file, paths.daily_research_brief_html_file
    )
    brief_store.save(brief)
    record = _record("run-1", brief, datetime(2026, 8, 9, tzinfo=timezone.utc))
    notifier = DeterministicFakeNotifier()
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)
    first = service.notify_success(record, brief)
    assert first.status == "sent"
    assert len(notifier.requests) == 1

    second_notifier = DeterministicFakeNotifier()
    second = DailyResearchNotificationService(paths, notifier=second_notifier)
    assert second.notify_success(record, brief).reason == "通知已去重"
    assert second_notifier.requests == []


@pytest.mark.parametrize("status,exit_code", [("partial", 10), ("failed", 40)])
def test_non_success_runs_never_send_success_notification(
    tmp_path: Path, status: str, exit_code: int
) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    notifier = DeterministicFakeNotifier()
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)
    result = service.notify_success(
        _record("run", brief, datetime.now(timezone.utc), status=status, exit_code=exit_code),
        brief,
    )
    assert result.status == "unavailable"
    assert notifier.requests == []


def test_notifier_failure_is_recorded_without_mutating_brief(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    store = DailyResearchBriefStore(
        paths.daily_research_brief_file, paths.daily_research_brief_html_file
    )
    store.save(brief)
    notifier = DeterministicFakeNotifier(NotificationResult("failed", "暫時不可用"))
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)
    record = _record("run", brief, datetime.now(timezone.utc))
    result = service.notify_success(record, brief)
    assert result.status == "failed"
    assert store.load() == brief
    assert service.status().last_status == "failed"


def test_notification_reason_is_redacted_and_does_not_expose_paths_or_tokens(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    notifier = DeterministicFakeNotifier(
        NotificationResult("failed", r"token=secret C:\Users\steve\private.csv")
    )
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)
    service.notify_success(_record("run", brief, datetime.now(timezone.utc)), brief)
    reason = service.status().last_reason or ""
    assert "secret" not in reason
    assert "C:\\Users\\steve" not in reason


def test_notification_ledger_is_bounded_and_corrupt_state_fails_closed(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    store = NotificationLedgerStore(records, tmp_path / "history.json", max_records=30)
    for index in range(31):
        from stock_tool.application.daily_research_inbox import NotificationLedgerRecord

        store.save(
            NotificationLedgerRecord(
                ledger_id=str(index),
                run_id=f"run-{index}",
                brief_fingerprint=f"brief-{index}",
                status="sent",
                created_at=f"2026-08-09T00:00:{index:03d}+00:00",
                claim_id=f"claim-{index}",
            )
        )
    projection = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [item["run_id"] for item in projection["records"]] == [
        f"run-{index}" for index in range(1, 31)
    ]
    (records / "notification-corrupt.json").write_text("{}", encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        store.records()


def test_inbox_is_newest_first_and_fail_closed_on_missing_brief(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    from stock_tool.application.daily_research_scheduler import ScheduledRunStore

    run_store = ScheduledRunStore(
        paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir
    )
    brief = _brief()
    run_store.save(_record("run-1", brief, datetime(2026, 8, 9, tzinfo=timezone.utc)))
    run_store.save(
        _record(
            "run-2",
            brief,
            datetime(2026, 8, 9, 0, 1, tzinfo=timezone.utc),
            status="partial",
            exit_code=10,
        )
    )
    entries = DailyResearchInboxService(paths).entries()
    assert [entry.run_id for entry in entries] == ["run-2", "run-1"]
    assert entries[0].status == "部分完成"
    assert entries[1].brief_available is False

    DailyResearchBriefStore(
        paths.daily_research_brief_file, paths.daily_research_brief_html_file
    ).save(brief)
    entries = DailyResearchInboxService(paths).entries()
    assert entries[-1].brief_available is True
    paths.daily_research_brief_file.unlink()
    assert DailyResearchInboxService(paths).latest_validated_brief() is None


def test_change_summary_binds_inbox_projection_and_notification_dedup(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    summary = DailyResearchChangeApplicationService().compare(brief)
    from stock_tool.application.daily_research_scheduler import ScheduledRunStore

    run_store = ScheduledRunStore(
        paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir
    )
    run_one = _record("run-change-one", brief, datetime(2026, 8, 9, tzinfo=timezone.utc))
    run_store.save(run_one)
    DailyResearchBriefStore(
        paths.daily_research_brief_file, paths.daily_research_brief_html_file
    ).save(brief)
    DailyResearchChangeStore(
        paths.daily_research_change_file, paths.daily_research_change_history_dir
    ).save(summary)
    entry = DailyResearchInboxService(paths).entries()[0]
    assert entry.change_fingerprint == summary.content_fingerprint
    assert entry.change_status == summary.status
    assert entry.change_reference_ids == ()

    notifier = DeterministicFakeNotifier()
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)
    assert service.notify_success(run_one, brief, change_summary=summary).status == "sent"
    assert service.ledger.claims()[0].change_fingerprint == summary.content_fingerprint
    second_run = _record("run-change-two", brief, datetime(2026, 8, 9, 0, 1, tzinfo=timezone.utc))
    assert service.notify_success(second_run, brief, change_summary=summary).status == "unavailable"
    assert len(notifier.requests) == 1


def test_different_change_same_run_is_audited_but_not_sent_twice(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    summary = DailyResearchChangeApplicationService().compare(brief)
    alternate_payload = summary.to_dict()
    alternate_payload["warnings"] = ["different semantic change"]
    from stock_tool.application.daily_research_changes import _digest

    alternate_payload["content_fingerprint"] = _digest(
        {key: value for key, value in alternate_payload.items() if key != "content_fingerprint"}
    )
    alternate = type(summary).from_dict(alternate_payload)
    service = DailyResearchNotificationService(paths, notifier=DeterministicFakeNotifier())
    service.set_enabled(True)
    record = _record("run-same", brief, datetime(2026, 8, 9, tzinfo=timezone.utc))
    assert service.notify_success(record, brief, change_summary=summary).status == "sent"
    assert service.notify_success(record, brief, change_summary=alternate).status == "unavailable"


def test_claim_write_failure_never_calls_notifier(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    notifier = DeterministicFakeNotifier()
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)
    service.ledger.atomic_create = lambda *_args: (_ for _ in ()).throw(OSError("claim"))
    result = service.notify_success(_record("claim-fail", brief, datetime.now(timezone.utc)), brief)
    assert result.status == "failed"
    assert notifier.requests == []


def test_outcome_failure_leaves_claim_and_restart_deduplicates(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    notifier = DeterministicFakeNotifier()
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)
    calls = 0

    def fail_outcome(path: Path, payload: object) -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise OSError("outcome")
        from stock_tool.application.daily_research_inbox import _atomic_json_write

        _atomic_json_write(path, payload)  # type: ignore[arg-type]

    service.ledger.atomic_write = fail_outcome
    record = _record("outcome-fail", brief, datetime.now(timezone.utc))
    assert service.notify_success(record, brief).status == "failed"
    assert len(notifier.requests) == 1
    restarted = DailyResearchNotificationService(paths, notifier=DeterministicFakeNotifier())
    restarted.set_enabled(True)
    duplicate = restarted.notify_success(record, brief)
    assert duplicate.reason == "通知已去重"
    assert restarted.notifier.requests == []  # type: ignore[attr-defined]


def test_history_failure_keeps_immutable_outcome_and_rebuilds(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    fail_history = True

    def atomic(path: Path, payload: object) -> None:
        nonlocal fail_history
        if path.name == "history.json" and fail_history:
            fail_history = False
            raise OSError("history")
        from stock_tool.application.daily_research_inbox import _atomic_json_write

        _atomic_json_write(path, payload)  # type: ignore[arg-type]

    store = NotificationLedgerStore(records, tmp_path / "history.json", atomic_write=atomic)
    record = NotificationLedgerRecord(
        ledger_id="history-fail",
        run_id="history-run",
        brief_fingerprint="history-brief",
        status="sent",
        created_at="2026-08-09T00:00:00+00:00",
        claim_id="history-claim",
    )
    with pytest.raises(NotificationLedgerError):
        store.save(record)
    assert list(records.glob("claim-*.json"))
    assert list(records.glob("outcome-*.json")) == []
    store.rebuild_history()
    assert json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))["records"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": True},
        {"schema_version": 2, "ledger_id": "x"},
        {
            "schema_version": 2,
            "ledger_id": "x",
            "run_id": "r",
            "brief_fingerprint": "b",
            "status": "sent",
            "created_at": "2026-08-09T00:00:00",
        },
        {
            "schema_version": 2,
            "ledger_id": "x",
            "run_id": "r",
            "brief_fingerprint": "b",
            "status": "unknown",
            "created_at": "2026-08-09T00:00:00+00:00",
        },
    ],
)
def test_strict_ledger_rejects_invalid_payloads(tmp_path: Path, payload: dict[str, object]) -> None:
    path = tmp_path / "ledger"
    path.mkdir()
    (path / "outcome-x.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        NotificationLedgerStore(path, tmp_path / "history.json").records()


def test_windows_adapter_uses_existing_identity_and_injected_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("stock_tool.application.daily_research_inbox.os.name", "nt")
    calls: list[tuple[list[str], float]] = []

    def runner(command: Sequence[str], timeout: float) -> object:
        calls.append((list(command), timeout))
        return type("Completed", (), {"returncode": 0})()

    adapter = WindowsNotificationAdapter(
        identity_probe=lambda: "StockTool.Test!App", system_runner=runner
    )
    capability = adapter.capability()
    assert capability.available is True
    result = adapter.send(NotificationRequest("標題", "內容"))
    assert result.status == "sent"
    assert len(calls) == 3
    assert "ContentType = WindowsRuntime" in calls[0][0][-1]
    assert "Show($toast)" not in calls[1][0][-1]
    assert "Show($toast)" in calls[2][0][-1]


def test_windows_adapter_without_identity_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("stock_tool.application.daily_research_inbox.os.name", "nt")
    adapter = WindowsNotificationAdapter(identity_probe=lambda: None)
    assert adapter.send(NotificationRequest("標題", "內容")).status == "unavailable"


def test_strict_notification_value_validation() -> None:
    with pytest.raises(ValueError):
        NotificationClaimRecord(
            claim_id="c",
            run_id="r",
            brief_fingerprint="b",
            created_at="2026-08-09T00:00:00+00:00",
            schema_version=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        NotificationClaimRecord(
            claim_id="c",
            run_id="r",
            brief_fingerprint="b",
            created_at="2026-08-09T00:00:00+00:00",
            schema_version=1,
        )
    with pytest.raises(ValueError):
        NotificationSettings(schema_version=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        NotificationSettings(schema_version=1)
    with pytest.raises(ValueError):
        NotificationSettings(enabled="false")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        NotificationSettings(updated_at=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        NotificationSettings.from_dict([])
    with pytest.raises(ValueError):
        NotificationSettings.from_dict({"enabled": False, "schema_version": 2, "updated_at": 1})
    with pytest.raises(ValueError):
        NotificationLedgerRecord.from_dict([])
    with pytest.raises(ValueError):
        NotificationLedgerRecord.from_dict(
            {
                "schema_version": 2,
                "ledger_id": "../bad",
                "run_id": "r",
                "brief_fingerprint": "b",
                "status": "sent",
                "created_at": "2026-08-09T00:00:00+00:00",
            }
        )
    with pytest.raises(ValueError):
        NotificationClaimRecord.from_dict([])
    with pytest.raises(ValueError):
        NotificationClaimRecord.from_dict(
            {
                "schema_version": 2,
                "claim_id": "c",
                "run_id": "r",
                "brief_fingerprint": "b",
                "created_at": "not-a-date",
            }
        )


def test_strict_notification_validation_covers_constructor_and_schema_guards() -> None:
    with pytest.raises(ValueError):
        NotificationClaimRecord(
            claim_id="claim",
            run_id="run",
            brief_fingerprint="brief",
            created_at=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        NotificationSettings.from_dict({"enabled": False, "schema_version": True, "updated_at": ""})
    with pytest.raises(ValueError):
        NotificationLedgerRecord(
            ledger_id="ledger",
            run_id="run",
            brief_fingerprint="brief",
            status="unknown",  # type: ignore[arg-type]
            created_at="2026-08-09T00:00:00+00:00",
            claim_id="claim",
        )
    with pytest.raises(ValueError):
        NotificationLedgerRecord(
            ledger_id="ledger",
            run_id="run",
            brief_fingerprint="brief",
            status="sent",
            created_at="2026-08-09T00:00:00+00:00",
            claim_id="one-claim",
            reason=123,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        NotificationClaimRecord.from_dict(
            {
                "schema_version": 2,
                "claim_id": "c",
                "run_id": "r",
                "brief_fingerprint": "b",
                "created_at": "2026-08-09T00:00:00",
            }
        )


def test_claim_and_outcome_filename_and_duplicate_validation(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    store = NotificationLedgerStore(records, tmp_path / "history.json")
    store.save(
        NotificationLedgerRecord(
            ledger_id="one",
            run_id="run-one",
            brief_fingerprint="brief-one",
            status="sent",
            created_at="2026-08-09T00:00:00+00:00",
            claim_id="claim-one",
        )
    )
    outcome = records / "outcome-one.json"
    outcome.rename(records / "outcome-renamed.json")
    with pytest.raises(NotificationLedgerError):
        store.records()

    records2 = tmp_path / "ledger2"
    store2 = NotificationLedgerStore(records2, tmp_path / "history2.json")
    store2.save(
        NotificationLedgerRecord(
            ledger_id="two",
            run_id="run-two",
            brief_fingerprint="brief-two",
            status="sent",
            created_at="2026-08-09T00:00:00+00:00",
            claim_id="claim-two",
        )
    )
    claim = next(records2.glob("claim-*.json"))
    payload = json.loads(claim.read_text(encoding="utf-8"))
    payload["run_id"] = "run-two"
    (records2 / "claim-duplicate.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        store2.claims()


def test_ledger_graph_rejects_orphan_null_mismatch_and_corrupt_claim(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    records.mkdir()
    outcome = {
        "schema_version": 2,
        "ledger_id": "orphan-ledger",
        "run_id": "orphan-run",
        "brief_fingerprint": "orphan-brief",
        "status": "sent",
        "created_at": "2026-08-09T00:00:00+00:00",
        "claim_id": "missing-claim",
    }
    (records / "outcome-orphan-ledger.json").write_text(json.dumps(outcome), encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        NotificationLedgerStore(records, tmp_path / "history.json").records()

    (records / "outcome-orphan-ledger.json").unlink()
    claim = {
        "schema_version": 2,
        "claim_id": "claim-1",
        "run_id": "run-1",
        "brief_fingerprint": "brief-1",
        "created_at": "2026-08-09T00:00:00+00:00",
    }
    (records / "claim-claim-1.json").write_text(json.dumps(claim), encoding="utf-8")
    mismatched = dict(outcome, ledger_id="mismatch", claim_id="claim-1")
    (records / "outcome-mismatch.json").write_text(json.dumps(mismatched), encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        NotificationLedgerStore(records, tmp_path / "history.json").records()

    mismatched["claim_id"] = None
    (records / "outcome-mismatch.json").write_text(json.dumps(mismatched), encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        NotificationLedgerStore(records, tmp_path / "history.json").records()

    (records / "claim-claim-1.json").write_text("{", encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        NotificationLedgerStore(records, tmp_path / "history.json").claims()


def test_ledger_graph_rejects_cross_linked_outcomes(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    store = NotificationLedgerStore(records, tmp_path / "history.json")
    first = store.create_claim(
        run_id="run-one",
        brief_fingerprint="brief-one",
        created_at="2026-08-09T00:00:00+00:00",
    )
    second = store.create_claim(
        run_id="run-two",
        brief_fingerprint="brief-two",
        created_at="2026-08-09T00:01:00+00:00",
    )
    (records / "outcome-cross-linked.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "ledger_id": "cross-linked",
                "run_id": first.run_id,
                "brief_fingerprint": first.brief_fingerprint,
                "status": "sent",
                "created_at": "2026-08-09T00:02:00+00:00",
                "claim_id": second.claim_id,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(NotificationLedgerError):
        store.records()


def test_claim_without_outcome_is_pending_and_never_retried(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    store = NotificationLedgerStore(records, tmp_path / "history.json")
    claim = store.create_claim(
        run_id="pending-run",
        brief_fingerprint="pending-brief",
        created_at="2026-08-09T00:00:00+00:00",
    )
    assert store.records() == ()
    assert store.claims() == (claim,)
    assert store.contains("pending-run", "pending-brief")


def test_notification_service_exposes_pending_claim_without_resend(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    record = _record("pending-run", brief, datetime.now(timezone.utc))
    service = DailyResearchNotificationService(paths, notifier=DeterministicFakeNotifier())
    service.set_enabled(True)
    service.ledger.create_claim(
        run_id=record.run_id,
        brief_fingerprint=brief.manifest.content_fingerprint,
        created_at="2026-08-09T00:00:00+00:00",
    )
    assert service.status().last_status == "pending"
    restarted_notifier = DeterministicFakeNotifier()
    restarted = DailyResearchNotificationService(paths, notifier=restarted_notifier)
    restarted.set_enabled(True)
    assert restarted.notify_success(record, brief).status == "unavailable"
    assert restarted_notifier.requests == []


def test_outcome_requires_non_empty_matching_claim_id(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    store = NotificationLedgerStore(records, tmp_path / "history.json")
    claim = store.create_claim(
        run_id="strict-run",
        brief_fingerprint="strict-brief",
        created_at="2026-08-09T00:00:00+00:00",
    )
    with pytest.raises(ValueError):
        NotificationLedgerRecord.from_dict(
            {
                "schema_version": 2,
                "ledger_id": "strict-ledger",
                "run_id": "strict-run",
                "brief_fingerprint": "strict-brief",
                "status": "sent",
                "created_at": "2026-08-09T00:00:00+00:00",
                "claim_id": None,
            }
        )
    with pytest.raises(NotificationLedgerError):
        store.save_outcome(
            NotificationLedgerRecord(
                ledger_id="strict-ledger",
                run_id="strict-run",
                brief_fingerprint="strict-brief",
                status="sent",
                created_at="2026-08-09T00:00:00+00:00",
                claim_id="other-claim",
            )
        )
    store.save_outcome(
        NotificationLedgerRecord(
            ledger_id="strict-ledger",
            run_id="strict-run",
            brief_fingerprint="strict-brief",
            status="sent",
            created_at="2026-08-09T00:00:00+00:00",
            claim_id=claim.claim_id,
        )
    )
    assert store.records()[0].claim_id == claim.claim_id


def test_claim_identity_is_recomputed_and_outcome_order_is_checked(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    store = NotificationLedgerStore(records, tmp_path / "history.json")
    claim = store.create_claim(
        run_id="identity-run",
        brief_fingerprint="identity-brief",
        created_at="2026-08-09T00:01:00+00:00",
    )

    payload = json.loads((records / f"claim-{claim.claim_id}.json").read_text(encoding="utf-8"))
    payload["run_id"] = "tampered-run"
    (records / f"claim-{claim.claim_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NotificationLedgerError):
        store.records()

    (records / f"claim-{claim.claim_id}.json").write_text(
        json.dumps(claim.to_dict()), encoding="utf-8"
    )
    (records / "outcome-early.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "ledger_id": "early",
                "run_id": claim.run_id,
                "brief_fingerprint": claim.brief_fingerprint,
                "status": "sent",
                "created_at": "2026-08-09T00:00:00+00:00",
                "claim_id": claim.claim_id,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(NotificationLedgerError, match="precedes"):
        store.records()


def test_claim_filename_and_forged_deterministic_id_fail_closed(tmp_path: Path) -> None:
    records = tmp_path / "ledger"
    records.mkdir()
    claim = {
        "schema_version": 2,
        "claim_id": "forged-id",
        "run_id": "run",
        "brief_fingerprint": "brief",
        "created_at": "2026-08-09T00:00:00+00:00",
    }
    (records / "claim-forged-id.json").write_text(json.dumps(claim), encoding="utf-8")
    with pytest.raises(NotificationLedgerError, match="deterministic"):
        NotificationLedgerStore(records, tmp_path / "history.json").claims()

    expected = NotificationLedgerStore.claim_id_for("run", "brief")
    (records / "claim-wrong-name.json").write_text(
        json.dumps({**claim, "claim_id": expected}), encoding="utf-8"
    )
    (records / "claim-forged-id.json").unlink()
    with pytest.raises(NotificationLedgerError):
        NotificationLedgerStore(records, tmp_path / "history.json").claims()


def test_filesystem_exclusive_create_allows_only_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "ledger" / "claim.json"
    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=5)
        try:
            _atomic_create_json(path, {"claim": "one"})
            result = "created"
        except FileExistsError:
            result = "duplicate"
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert sorted(results) == ["created", "duplicate"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"claim": "one"}


def test_exclusive_create_loser_preserves_existing_claim_bytes(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    store = NotificationLedgerStore(
        paths.daily_notification_ledger_dir, paths.daily_notification_history_file
    )
    claim = store.create_claim(
        run_id="winner-run",
        brief_fingerprint="winner-brief",
        created_at="2026-08-11T00:00:00+00:00",
    )
    path = paths.daily_notification_ledger_dir / f"claim-{claim.claim_id}.json"
    before = path.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    with pytest.raises(FileExistsError):
        _atomic_create_json(path, {"forged": True})
    assert path.read_bytes() == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash
    assert store.claims() == (claim,)


def test_exclusive_create_cleans_only_its_owned_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "owned.json"

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr("stock_tool.application.daily_research_inbox.os.fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated"):
        _atomic_create_json(path, {"owned": True})
    assert not path.exists()


def test_delayed_loser_after_winner_close_is_duplicate_and_preserves_claim(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    winner = NotificationLedgerStore(
        paths.daily_notification_ledger_dir, paths.daily_notification_history_file
    )
    loser = NotificationLedgerStore(
        paths.daily_notification_ledger_dir, paths.daily_notification_history_file
    )
    winner._validated_graph()
    loser._validated_graph()
    claim = NotificationClaimRecord(
        claim_id=winner.claim_id_for("delayed-run", "delayed-brief"),
        run_id="delayed-run",
        brief_fingerprint="delayed-brief",
        created_at="2026-08-11T00:00:00+00:00",
    )
    path = paths.daily_notification_ledger_dir / f"claim-{claim.claim_id}.json"
    _atomic_create_json(path, claim.to_dict())
    winner_bytes = path.read_bytes()
    with pytest.raises(FileExistsError):
        _atomic_create_json(path, claim.to_dict())
    assert path.read_bytes() == winner_bytes
    assert loser.claims() == (claim,)


def test_service_delayed_loser_restart_deduplicates_after_winner_outcome(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    record = _record("delayed-service-run", brief, datetime.now(timezone.utc))
    loser = DailyResearchNotificationService(paths, notifier=DeterministicFakeNotifier())
    winner_send_count = 0
    loser_result: list[NotificationResult] = []

    class WinnerNotifier:
        def send(self, _request: NotificationRequest) -> NotificationResult:
            nonlocal winner_send_count
            winner_send_count += 1
            loser_result.append(loser.notify_success(record, brief))
            return NotificationResult("sent")

    winner = DailyResearchNotificationService(paths, notifier=WinnerNotifier())
    winner.set_enabled(True)
    loser.set_enabled(True)
    assert winner.notify_success(record, brief).status == "sent"
    assert loser_result[0].status == "unavailable"
    assert winner_send_count == 1
    restarted = DailyResearchNotificationService(paths, notifier=DeterministicFakeNotifier())
    assert restarted.notify_success(record, brief).status == "unavailable"
    assert winner_send_count == 1
    assert len(winner.ledger.claims()) == 1
    assert len(winner.ledger.records()) == 1


def test_staggered_independent_python_processes_preserve_winner_claim(
    tmp_path: Path,
) -> None:
    records = tmp_path / "records"
    records.mkdir()
    claim_path = records / "claim-placeholder.json"
    winner_ready = tmp_path / "winner.ready"
    loser_done = tmp_path / "loser.done"
    child = r"""
import json, sys, time
from pathlib import Path
from stock_tool.application.daily_research_inbox import NotificationClaimRecord, _atomic_create_json
path = Path(sys.argv[1])
winner_ready = Path(sys.argv[2])
loser_done = Path(sys.argv[3])
role = sys.argv[4]
run_id, brief = "process-run", "process-brief"
claim = NotificationClaimRecord(
    claim_id=__import__("stock_tool.application.daily_research_inbox", fromlist=["NotificationLedgerStore"]).NotificationLedgerStore.claim_id_for(run_id, brief),
    run_id=run_id, brief_fingerprint=brief, created_at="2026-08-11T00:00:00+00:00"
)
if role == "winner":
    _atomic_create_json(path, claim.to_dict())
    winner_ready.write_text("ready", encoding="utf-8")
    deadline = time.time() + 10
    while not loser_done.exists() and time.time() < deadline: time.sleep(0.02)
    raise SystemExit(0 if loser_done.exists() else 2)
while not winner_ready.exists(): time.sleep(0.02)
try:
    _atomic_create_json(path, claim.to_dict())
except FileExistsError:
    loser_done.write_text("duplicate", encoding="utf-8")
    raise SystemExit(0)
raise SystemExit(3)
"""
    claim_path = (
        records
        / f"claim-{NotificationLedgerStore.claim_id_for('process-run', 'process-brief')}.json"
    )
    winner = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child,
            str(claim_path),
            str(winner_ready),
            str(loser_done),
            "winner",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    loser = subprocess.Popen(
        [sys.executable, "-c", child, str(claim_path), str(winner_ready), str(loser_done), "loser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    winner_code = winner.wait(timeout=20)
    loser_code = loser.wait(timeout=20)
    assert winner_code == 0
    assert loser_code == 0
    store = NotificationLedgerStore(records, tmp_path / "history.json")
    assert len(store.claims()) == 1
    assert store.claims()[0].claim_id == NotificationLedgerStore.claim_id_for(
        "process-run", "process-brief"
    )


def test_two_independent_services_compete_for_one_claim_and_send_once(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    record = _record("concurrent-run", brief, datetime.now(timezone.utc))
    send_count = 0
    send_lock = threading.Lock()

    class CountingNotifier:
        def send(self, _request: NotificationRequest) -> NotificationResult:
            nonlocal send_count
            with send_lock:
                send_count += 1
            return NotificationResult("sent")

    services = [
        DailyResearchNotificationService(paths, notifier=CountingNotifier()),
        DailyResearchNotificationService(paths, notifier=CountingNotifier()),
    ]
    for service in services:
        service.set_enabled(True)
    barrier = threading.Barrier(2)
    for service in services:
        original = service.ledger.create_claim

        def compete(*args: object, _original=original, **kwargs: object) -> object:
            barrier.wait(timeout=5)
            return _original(*args, **kwargs)

        setattr(service.ledger, "create_claim", compete)
    results: list[NotificationResult] = []

    def run(service: DailyResearchNotificationService) -> None:
        results.append(service.notify_success(record, brief))

    threads = [threading.Thread(target=run, args=(service,)) for service in services]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert send_count == 1
    assert sorted(result.status for result in results) == ["sent", "unavailable"]
    assert any(isinstance(result, NotificationResult) for result in results)


@pytest.mark.parametrize("old_status", ["sent", "failed", "unavailable"])
def test_newer_pending_claim_is_not_hidden_by_old_outcome(tmp_path: Path, old_status: str) -> None:
    paths = RuntimePaths(tmp_path / old_status).ensure_directories()
    old_brief = _brief()
    old_record = _record("old-run", old_brief, datetime(2026, 8, 9, tzinfo=timezone.utc))
    service = DailyResearchNotificationService(
        paths,
        notifier=DeterministicFakeNotifier(
            NotificationResult(cast(Literal["sent", "failed", "unavailable"], old_status))
        ),
    )
    service.set_enabled(True)
    assert service.notify_success(old_record, old_brief).status == old_status
    newer_brief = _brief(fingerprint_source="online")
    newer_record = _record("new-run", newer_brief, datetime(2026, 8, 10, tzinfo=timezone.utc))
    service.ledger.create_claim(
        run_id=newer_record.run_id,
        brief_fingerprint=newer_brief.manifest.content_fingerprint,
        created_at="2026-08-12T00:00:00+00:00",
    )
    status = service.status()
    assert status.last_status == "pending"
    assert status.last_reason

    claim = service.ledger.claims()[-1]
    service.ledger.save_outcome(
        NotificationLedgerRecord(
            ledger_id="new-outcome",
            run_id=newer_record.run_id,
            brief_fingerprint=newer_record.output_brief_fingerprint or "",
            status="sent",
            created_at="2026-08-12T00:01:00+00:00",
            claim_id=claim.claim_id,
        )
    )
    assert service.status().last_status == "sent"


def test_partial_claim_write_leaves_invalid_state_fail_closed(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    notifier = DeterministicFakeNotifier()
    service = DailyResearchNotificationService(paths, notifier=notifier)
    service.set_enabled(True)

    def partial(path: Path, _payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
        raise OSError("interrupted")

    service.ledger.atomic_create = partial
    assert (
        service.notify_success(
            _record("partial-claim", brief, datetime.now(timezone.utc)), brief
        ).status
        == "failed"
    )
    assert notifier.requests == []
    claim_files = list(paths.daily_notification_ledger_dir.glob("claim-*.json"))
    if claim_files:
        with pytest.raises(NotificationLedgerError):
            service.ledger.records()


def test_windows_runtime_probe_executes_real_powershell_construction() -> None:
    if os.name != "nt":
        pytest.skip("Windows Runtime probe is Windows-only")
    command = WindowsNotificationAdapter._runtime_probe_command("StockTool.Test!App")
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    assert "ContentType = WindowsRuntime" in command[4]
    assert "Show" not in command[4]
    assert completed.returncode in range(0, 256)


@pytest.mark.parametrize("result", [True, False])
def test_injected_windows_send_function_paths(
    monkeypatch: pytest.MonkeyPatch, result: bool
) -> None:
    monkeypatch.setattr("stock_tool.application.daily_research_inbox.os.name", "nt")
    adapter = WindowsNotificationAdapter(send_fn=lambda _request: result)
    assert adapter.capability().available
    assert adapter.send(NotificationRequest("標題", "內容")).status == (
        "sent" if result else "failed"
    )


def test_injected_windows_send_exception_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("stock_tool.application.daily_research_inbox.os.name", "nt")
    adapter = WindowsNotificationAdapter(
        send_fn=lambda _request: (_ for _ in ()).throw(RuntimeError())
    )
    assert adapter.send(NotificationRequest("標題", "內容")).status == "failed"


def test_notifier_exception_persists_failed_outcome(tmp_path: Path) -> None:
    class RaisingNotifier:
        def send(self, _request: NotificationRequest) -> NotificationResult:
            raise RuntimeError("provider failure")

    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    service = DailyResearchNotificationService(paths, notifier=RaisingNotifier())
    service.set_enabled(True)
    result = service.notify_success(_record("raising", brief, datetime.now(timezone.utc)), brief)
    assert result.status == "failed"
    assert service.status().last_status == "failed"


def test_windows_adapter_runner_failure_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("stock_tool.application.daily_research_inbox.os.name", "nt")
    nonzero_calls = iter([type("Completed", (), {"returncode": 0})(), (1, "", "error")])
    nonzero = WindowsNotificationAdapter(
        identity_probe=lambda: "StockTool.Test!App",
        system_runner=lambda _command, _timeout: next(nonzero_calls),
    )
    assert nonzero.send(NotificationRequest("標題", "內容")).status == "failed"
    raising_calls: list[object] = [type("Completed", (), {"returncode": 0})(), TimeoutError()]

    def raising_runner(_command: Sequence[str], _timeout: float) -> object:
        value = raising_calls.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    raising = WindowsNotificationAdapter(
        identity_probe=lambda: "StockTool.Test!App",
        system_runner=raising_runner,
    )
    assert raising.send(NotificationRequest("標題", "內容")).status == "failed"
    broken_probe = WindowsNotificationAdapter(
        identity_probe=lambda: (_ for _ in ()).throw(RuntimeError())
    )
    assert broken_probe.capability().available is False


def test_notification_service_fail_closed_branches(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    brief = _brief()
    notifier = DeterministicFakeNotifier()
    service = DailyResearchNotificationService(paths, notifier=notifier)
    record = _record("run", brief, datetime.now(timezone.utc))
    mismatch = replace(record, output_brief_fingerprint="other")
    assert service.notify_success(mismatch, brief).status == "failed"
    service.set_enabled(True)
    assert service.notify_success(record, brief).status == "sent"
    assert service.send_test_notification().status == "sent"


@pytest.mark.parametrize("source", ["online", "cache", "other"])
def test_inbox_source_mode_labels(tmp_path: Path, source: str) -> None:
    paths = RuntimePaths(tmp_path / source).ensure_directories()
    brief = _brief(fingerprint_source=source)
    DailyResearchBriefStore(
        paths.daily_research_brief_file, paths.daily_research_brief_html_file
    ).save(brief)
    from stock_tool.application.daily_research_scheduler import ScheduledRunStore

    ScheduledRunStore(paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir).save(
        _record(f"run-{source}", brief, datetime.now(timezone.utc))
    )
    entry = DailyResearchInboxService(paths).entries()[0]
    assert entry.source_mode == (
        "online" if source == "online" else "cache" if source == "cache" else "本機資料"
    )
