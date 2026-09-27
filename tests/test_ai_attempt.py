import json

import pytest

from stock_tool.research.ai_attempt import record_attempt
from stock_tool.research.public_request import RequestOutcome
from stock_tool.research.work_session import (
    ResearchWorkSession,
    WorkSessionError,
    WorkSessionStore,
)
from test_public_research_request import prepared


def session():
    snapshot, request = prepared()
    timestamp = "2026-09-14T00:00:00+00:00"
    attempt = record_attempt(
        snapshot,
        request,
        RequestOutcome("failed", "safe error", timestamp),
        provider="isolated-test",
        model="fixture",
        started_at=timestamp,
        completed_at=timestamp,
    )
    return ResearchWorkSession(snapshot, "本機私人問題 CANARY", timestamp, attempt)


def test_attempt_survives_backup_restore_without_promoting_to_conclusion(tmp_path):
    original = session()
    store = WorkSessionStore(tmp_path / "original")
    key = store.save(original)
    restored = WorkSessionStore(tmp_path / "restored")
    restored.restore_bytes(store.backup_bytes())
    assert restored.load(key) == original
    assert original.to_dict()["version"] == 2
    assert "CANARY" not in original.ai_attempt_json
    local = ResearchWorkSession(
        original.snapshot, original.question, original.created_at
    )
    assert local.to_dict()["version"] == 1
    assert ResearchWorkSession.from_dict(local.to_dict()) == local


@pytest.mark.parametrize("change", ["status", "identity", "payload", "version", "time"])
def test_rehashed_tampering_is_still_rejected(change):
    value = session().to_dict()
    attempt = value["ai_attempt"]
    if change == "status":
        attempt["status"] = "valid"
    elif change == "identity":
        attempt["snapshot_fingerprint"] = "0" * 64
    elif change == "payload":
        attempt["payload"]["private_note"] = "CANARY"
    elif change == "version":
        value["version"] = 1
    else:
        attempt["completed_at"] = "2025-01-01T00:00:00+00:00"
    with pytest.raises(WorkSessionError):
        ResearchWorkSession.from_dict(value)


def test_invalid_model_output_remains_invalid_on_reopen():
    original = session()
    value = original.to_dict()
    value["ai_attempt"]["raw_response"] = '{"claims": []}'
    value["ai_attempt"]["status"] = "invalid"
    reopened = ResearchWorkSession.from_dict(value)
    assert json.loads(reopened.ai_attempt_json)["status"] == "invalid"
    value["ai_attempt"]["status"] = "unverified"
    with pytest.raises(WorkSessionError):
        ResearchWorkSession.from_dict(value)
