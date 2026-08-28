from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stock_tool.application.daily_research_brief import (
    DailyBriefSource,
    DailyResearchBrief,
    DailyResearchBriefManifest,
    EvidenceChainItem,
    EvidenceReference,
    _content_fingerprint,
)
from stock_tool.application.daily_research_changes import (
    ChangeValidationError,
    DailyResearchChangeApplicationService,
    DailyResearchChangeSet,
    DailyResearchChangeStore,
    ResearchChange,
    _digest,
    _parse_time,
)


def _brief(
    *, risks: tuple[str, ...] = (), generated: str = "2026-08-09T10:00:00+00:00"
) -> DailyResearchBrief:
    reference = EvidenceReference(
        reference_id="ref-2330-close",
        provider="local-cache",
        market="TWSE",
        symbol="2330",
        field="close",
        as_of="2026-08-08",
        fetched_at="2026-08-09T09:00:00+00:00",
        payload_sha256="payload-hash",
    )
    item = EvidenceChainItem(
        symbol="2330",
        name="TSMC",
        market="TWSE",
        priority=3,
        reason="有可驗證資料",
        facts=("收盤 600",),
        inferences=(),
        risks=risks,
        data_as_of="2026-08-08",
        source="cache",
        reference_labels=("close",),
        confidence="high",
        completeness=1.0,
        status="fresh",
        fact_reference_ids=((reference.reference_id,),),
        inference_reference_ids=(),
        risk_reference_ids=tuple((reference.reference_id,) for _ in risks),
    )
    manifest = DailyResearchBriefManifest(
        schema_version=2,
        brief_date="2026-08-09",
        as_of_date="2026-08-08",
        input_snapshot_id="snapshot",
        input_snapshot_hash="input-hash",
        processed_count=1,
        source_summaries=(
            DailyBriefSource(
                market="TWSE",
                source="cache",
                data_date="2026-08-08",
                fetched_at="2026-08-09T09:00:00+00:00",
                status="success",
                coverage=1.0,
                payload_sha256="payload-hash",
            ),
        ),
        missing_or_stale=(),
        warnings=(),
        content_fingerprint="",
        references=(reference,),
    )
    manifest = replace(
        manifest,
        content_fingerprint=_content_fingerprint(manifest, (item,), status="success", message="ok"),
    )
    return DailyResearchBrief(generated, "success", manifest, (item,), "ok")


def test_first_baseline_and_worsened_risk_are_deterministic() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    baseline = service.compare(_brief())
    assert baseline.status == "baseline"
    assert baseline.changes[0].change_type == "baseline"
    current = _brief(risks=("資料日期較舊",), generated="2026-08-09T11:00:00+00:00")
    updated = service.compare(current, _brief())
    assert updated.status == "updated"
    assert updated.changes[0].change_type == "risk_worsened"
    assert updated.content_fingerprint == service.compare(current, _brief()).content_fingerprint


def test_compare_allows_reference_provenance_enrichment_but_rejects_payload_change() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    previous = _brief()
    previous_ref = previous.manifest.references[0]
    enriched_ref = replace(
        previous_ref,
        provider="local",
        fetched_at="2026-08-09T10:00:00+00:00",
    )
    enriched_manifest = replace(
        previous.manifest,
        references=(enriched_ref,),
        content_fingerprint="",
    )
    enriched_manifest = replace(
        enriched_manifest,
        content_fingerprint=_content_fingerprint(
            enriched_manifest,
            previous.items,
            status=previous.status,
            message=previous.message,
        ),
    )
    current = replace(
        previous, generated_at="2026-08-09T11:00:00+00:00", manifest=enriched_manifest
    )
    summary = service.compare(current, previous)
    assert summary.status == "no_change"

    tampered_ref = replace(enriched_ref, payload_sha256="different-payload")
    tampered_manifest = replace(
        enriched_manifest, references=(tampered_ref,), content_fingerprint=""
    )
    tampered_manifest = replace(
        tampered_manifest,
        content_fingerprint=_content_fingerprint(
            tampered_manifest,
            previous.items,
            status=previous.status,
            message=previous.message,
        ),
    )
    with pytest.raises(ChangeValidationError):
        service.compare(replace(current, manifest=tampered_manifest), previous)


def test_change_compare_ignores_validated_portfolio_context_without_identity() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    base = _brief()
    context = replace(base.items[0], symbol=None, market=None)
    manifest = replace(
        base.manifest,
        content_fingerprint=_content_fingerprint(
            base.manifest,
            (context, base.items[0]),
            status="success",
            message=base.message,
        ),
    )
    brief = replace(base, manifest=manifest, items=(context, base.items[0]))
    summary = service.compare(brief)
    assert summary.status == "baseline"
    assert [item.identity for item in summary.changes] == ["TWSE:2330"]


def test_no_change_and_resolution_are_explicit() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc)
    )
    assert service.compare(_brief(), _brief()).status == "no_change"
    previous = _brief(risks=("風險",))
    resolved = service.compare(_brief(generated="2026-08-10T00:00:00+00:00"), previous)
    assert resolved.changes[0].change_type == "improved"


def test_partial_stale_and_future_briefs_fail_closed() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    partial_item = replace(_brief().items[0], status="partial")
    partial_manifest = replace(_brief().manifest, content_fingerprint="")
    partial_manifest = replace(
        partial_manifest,
        content_fingerprint=_content_fingerprint(
            partial_manifest, (partial_item,), status="success", message="ok"
        ),
    )
    with pytest.raises(ChangeValidationError):
        service.compare(replace(_brief(), items=(partial_item,), manifest=partial_manifest))
    with pytest.raises(ChangeValidationError):
        service.compare(_brief(generated="2027-01-01T00:00:00+00:00"))


def test_store_roundtrip_and_fingerprint_tamper_fail_closed(tmp_path: Path) -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    summary = service.compare(_brief())
    store = DailyResearchChangeStore(tmp_path / "latest.json", tmp_path / "history")
    store.save(summary)
    loaded = store.load()
    assert loaded is not None
    assert loaded.content_fingerprint == summary.content_fingerprint
    payload = loaded.to_dict()
    payload["status"] = "updated"
    (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ChangeValidationError):
        store.load()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"identity": "x"},
        {"identity": "x", "priority": True},
        {"identity": "x", "priority": 9},
        {"identity": "x", "priority": 1, "coverage": 2.0},
        {"identity": "x", "priority": 1, "coverage": 1.0, "change_type": "bad"},
    ],
)
def test_change_item_adversarial_payloads_fail_closed(payload: object) -> None:
    with pytest.raises(ChangeValidationError):
        ResearchChange.from_dict(payload)


def test_store_history_rejects_wrong_identity_and_duplicate_payload(tmp_path: Path) -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    summary = service.compare(_brief())
    store = DailyResearchChangeStore(tmp_path / "latest.json", tmp_path / "history")
    store.save(summary)
    target = tmp_path / "history" / f"change-{summary.content_fingerprint}.json"
    target.write_text(
        target.read_text(encoding="utf-8").replace("baseline", "updated"), encoding="utf-8"
    )
    with pytest.raises(ChangeValidationError):
        store.history()


def test_invalid_timestamps_and_unresolved_references_fail_closed() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    invalid_time = replace(_brief(), generated_at="2026-08-09T10:00:00")
    with pytest.raises(ChangeValidationError):
        service.compare(invalid_time)
    current = _brief(risks=("risk",))
    broken_item = replace(current.items[0], fact_reference_ids=(("missing",),))
    broken_manifest = replace(current.manifest, content_fingerprint="")
    broken_manifest = replace(
        broken_manifest,
        content_fingerprint=_content_fingerprint(
            broken_manifest, (broken_item,), status="success", message="ok"
        ),
    )
    with pytest.raises(ChangeValidationError):
        service.compare(replace(current, items=(broken_item,), manifest=broken_manifest))


def test_change_contract_rejects_each_tamper_shape() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    summary = service.compare(_brief())
    base = summary.changes[0].to_dict()
    mutations = {
        "identity": "",
        "current_value": "not-a-list",
        "reference_ids": [123],
        "confidence": "unknown",
        "ai_allowed": "yes",
        "coverage": True,
        "priority": False,
    }
    for field, value in mutations.items():
        payload = dict(base)
        payload[field] = value
        with pytest.raises(ChangeValidationError):
            ResearchChange.from_dict(payload)
    with pytest.raises(ChangeValidationError):
        _parse_time("not-a-time")
    with pytest.raises(ChangeValidationError):
        _parse_time("2026-08-09T00:00:00")


def test_change_set_validator_rejects_schema_lists_and_duplicate_refs(tmp_path: Path) -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    summary = service.compare(_brief()).to_dict()
    mutations: dict[str, object] = {
        "schema_version": True,
        "generated_at": None,
        "status": "bad",
        "changes": {},
        "references": {},
        "warnings": {},
        "current_brief_fingerprint": "",
    }
    for field, value in mutations.items():
        payload = dict(summary)
        payload[field] = value
        with pytest.raises(ChangeValidationError):
            DailyResearchChangeSet.from_dict(payload)
    duplicate = dict(summary)
    references = summary["references"]
    assert isinstance(references, list)
    duplicate["references"] = references * 2
    with pytest.raises(ChangeValidationError):
        DailyResearchChangeSet.from_dict(duplicate)
    missing = tmp_path / "latest.json"
    store = DailyResearchChangeStore(missing, tmp_path / "history")
    assert store.load() is None
    missing.write_text("{}", encoding="utf-8")
    with pytest.raises(ChangeValidationError):
        store.load()


def test_change_store_latest_publish_failure_removes_new_archive(tmp_path, monkeypatch) -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    summary = service.compare(_brief())
    store = DailyResearchChangeStore(tmp_path / "latest.json", tmp_path / "history")
    monkeypatch.setattr(
        "stock_tool.application.daily_research_changes._atomic_json_write",
        lambda *_args: (_ for _ in ()).throw(OSError("latest replace")),
    )
    with pytest.raises(OSError):
        store.save(summary)
    assert not list((tmp_path / "history").glob("change-*.json"))


def test_change_store_archive_write_failure_removes_partial_record(tmp_path, monkeypatch) -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    summary = service.compare(_brief())
    store = DailyResearchChangeStore(tmp_path / "latest.json", tmp_path / "history")
    monkeypatch.setattr(
        "stock_tool.application.daily_research_changes.os.write",
        lambda *_args: (_ for _ in ()).throw(OSError("archive write")),
    )
    with pytest.raises(OSError):
        store.save(summary)
    assert not list((tmp_path / "history").glob("change-*.json"))


def _resign_change_payload(payload: dict[str, object]) -> dict[str, object]:
    core = {key: value for key, value in payload.items() if key != "content_fingerprint"}
    payload["content_fingerprint"] = _digest(core)
    return payload


def test_changeset_cross_field_contract_rejects_re_signed_forgery() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    baseline = service.compare(_brief()).to_dict()
    assert len(str(baseline["current_brief_fingerprint"])) == 64
    assert len(str(baseline["content_fingerprint"])) == 64

    future = dict(baseline)
    future["generated_at"] = "2027-01-01T00:00:00+00:00"
    with pytest.raises(ChangeValidationError):
        DailyResearchChangeSet.from_dict(_resign_change_payload(future))

    mismatch = dict(baseline)
    raw_changes = baseline["changes"]
    assert isinstance(raw_changes, list)
    changes = [dict(item) for item in raw_changes if isinstance(item, dict)]
    assert len(changes) == len(raw_changes)
    changes[0]["current_brief_fingerprint"] = "a" * 64
    mismatch["changes"] = changes
    with pytest.raises(ChangeValidationError):
        DailyResearchChangeSet.from_dict(_resign_change_payload(mismatch))

    identity = dict(baseline)
    raw_changes = baseline["changes"]
    assert isinstance(raw_changes, list)
    changes = [dict(item) for item in raw_changes if isinstance(item, dict)]
    assert len(changes) == len(raw_changes)
    changes[0]["market"] = "TPEX"
    identity["changes"] = changes
    with pytest.raises(ChangeValidationError):
        DailyResearchChangeSet.from_dict(_resign_change_payload(identity))

    unused_reference = dict(baseline)
    raw_references = baseline["references"]
    assert isinstance(raw_references, list)
    references = [dict(item) for item in raw_references if isinstance(item, dict)]
    assert len(references) == len(raw_references)
    references.append({**references[0], "reference_id": "forged-unused"})
    unused_reference["references"] = references
    with pytest.raises(ChangeValidationError):
        DailyResearchChangeSet.from_dict(_resign_change_payload(unused_reference))

    invalid_status = dict(baseline)
    invalid_status["status"] = "updated"
    with pytest.raises(ChangeValidationError):
        DailyResearchChangeSet.from_dict(_resign_change_payload(invalid_status))


def test_changeset_rejects_non_deterministic_order_and_duplicate_changes() -> None:
    service = DailyResearchChangeApplicationService(
        now_fn=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc)
    )
    previous = _brief()
    current = _brief(risks=("risk",), generated="2026-08-09T11:00:00+00:00")
    updated = service.compare(current, previous).to_dict()
    duplicate = dict(updated)
    raw_changes = updated["changes"]
    assert isinstance(raw_changes, list)
    changes = list(raw_changes)
    duplicate["changes"] = changes * 2
    with pytest.raises(ChangeValidationError):
        DailyResearchChangeSet.from_dict(_resign_change_payload(duplicate))
