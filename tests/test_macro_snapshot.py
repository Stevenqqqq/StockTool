from __future__ import annotations

from pathlib import Path
from datetime import datetime
from dataclasses import replace
import json
from typing import Any, cast

import pandas as pd
import pytest

from stock_tool.application.macro_snapshot import (
    FRED_SERIES,
    FredMacroProvider,
    FredPayloadError,
    MACRO_SCHEMA_VERSION,
    MacroEvidenceReference,
    MacroObservation,
    MacroProviderResult,
    MacroObservationPoint,
    MacroRevisionLedgerStore,
    MacroRuleRegistry,
    MacroSnapshot,
    MacroSnapshotApplicationService,
    MacroSnapshotError,
    MacroSnapshotStore,
    build_macro_links,
)
from stock_tool.application.daily_research_brief import DailyResearchBriefApplicationService

NOW = "2026-08-10T10:00:00+00:00"


class _CsvResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_CsvResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _payload_hash(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode()).hexdigest()


def _provider_result(
    *, value_offset: float = 0.0, observed_date: str = "2026-08-07"
) -> MacroProviderResult:
    references = []
    observations = []
    for index, (key, (fred_id, _title, unit)) in enumerate(FRED_SERIES.items()):
        reference_id = f"ref-{key.lower()}"
        references.append(
            MacroEvidenceReference(
                reference_id=reference_id,
                provider="fixture-fred",
                series_id=fred_id,
                source_url=f"https://example.test/{fred_id}",
                observed_date=observed_date,
                fetched_at=NOW,
                payload_sha256=_payload_hash(fred_id),
            )
        )
        observations.append(
            MacroObservation(
                series_id=key,
                observation_period=observed_date,
                value=float(index + 1) + value_offset,
                unit=unit,
                source="fixture-fred",
                source_url=f"https://example.test/{fred_id}",
                fetched_at=NOW,
                observed_date=observed_date,
                release_date=observed_date,
                freshness_status="fresh",
                snapshot_fingerprint="0" * 64,
                schema_version=MACRO_SCHEMA_VERSION,
                reference_id=reference_id,
            )
        )
    return MacroProviderResult(tuple(observations), tuple(references), source="FRED fixture")


class _Provider:
    def __init__(
        self, result: MacroProviderResult | None = None, error: Exception | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def fetch(self) -> MacroProviderResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_macro_snapshot_round_trip_and_deterministic_fingerprint() -> None:
    result = _provider_result()
    first = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    second = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat("2026-08-11T10:00:00+00:00"),
        as_of_date="2026-08-07",
    )
    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    assert MacroSnapshot.from_dict(first.to_dict()) == first


def test_macro_snapshot_rejects_tampered_fingerprint_reference_and_future_timestamp() -> None:
    result = _provider_result()
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    payload = cast(dict[str, Any], snapshot.to_dict())
    payload["warnings"] = ["tampered"]
    with pytest.raises(MacroSnapshotError):
        MacroSnapshot.from_dict(payload)
    payload = cast(dict[str, Any], snapshot.to_dict())
    payload["observations"][0]["reference_id"] = "unknown"
    with pytest.raises(MacroSnapshotError):
        MacroSnapshot.from_dict(payload)
    payload = cast(dict[str, Any], snapshot.to_dict())
    payload["generated_at"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(MacroSnapshotError):
        MacroSnapshot.from_dict(payload)


def test_store_is_atomic_and_history_rejects_corruption(tmp_path) -> None:
    result = _provider_result()
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")
    store.save(snapshot)
    assert store.load_latest() == snapshot
    assert store.history() == (snapshot,)
    (tmp_path / "history" / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MacroSnapshotError):
        store.history()


def test_refresh_attempts_provider_and_uses_stale_validated_snapshot_on_failure(tmp_path) -> None:
    result = _provider_result()
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")
    service = MacroSnapshotApplicationService(store, provider=_Provider(result))
    ready = service.refresh()
    failing = MacroSnapshotApplicationService(
        store, provider=_Provider(error=RuntimeError("offline"))
    )
    stale = failing.refresh()
    assert ready.status == "ready"
    assert stale.status == "stale"
    assert all(item.freshness_status == "stale" for item in stale.observations)
    assert "offline" not in stale.warnings[0]


def test_refresh_without_cache_is_unavailable_and_does_not_invent_values(tmp_path) -> None:
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")
    snapshot = MacroSnapshotApplicationService(
        store, provider=_Provider(error=RuntimeError("network"))
    ).refresh()
    assert snapshot.status == "unavailable"
    assert snapshot.observations == ()
    assert snapshot.references == ()


def test_rule_registry_exposes_statuses_and_references() -> None:
    result = _provider_result()
    current = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    previous_result = _provider_result(value_offset=-0.5, observed_date="2026-08-06")
    previous = MacroSnapshot.create(
        status="ready",
        source=previous_result.source,
        observations=previous_result.observations,
        references=previous_result.references,
        generated_at=datetime.fromisoformat("2026-08-09T10:00:00+00:00"),
        as_of_date="2026-08-06",
    )
    signals = MacroRuleRegistry().evaluate(current, previous)
    assert len(signals) == len(FRED_SERIES)
    assert {signal.status for signal in signals} == {"rising"}
    assert all(signal.reference_ids for signal in signals)
    assert all(signal.next_condition for signal in signals)


def test_rule_registry_stale_and_unavailable_fail_closed() -> None:
    result = _provider_result()
    stale_observations = tuple(
        replace(item, freshness_status="stale") for item in result.observations
    )
    stale = MacroSnapshot.create(
        status="stale",
        source=result.source,
        observations=stale_observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    unavailable = MacroSnapshot.create(
        status="unavailable",
        source="FRED official",
        observations=(),
        references=(),
        generated_at=datetime.fromisoformat(NOW),
    )
    assert {item.status for item in MacroRuleRegistry().evaluate(stale)} == {"stale"}
    assert {item.status for item in MacroRuleRegistry().evaluate(unavailable)} == {"unavailable"}


def test_macro_links_require_market_qualified_verified_classification() -> None:
    result = _provider_result()
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    portfolio = pd.DataFrame({"symbol": ["2330", "2330"], "market": ["TWSE", "TPEX"]})
    links = build_macro_links(
        snapshot,
        portfolio=portfolio,
        classifications={"TWSE:2330": {"sector": "半導體", "industry": "晶圓"}},
    )
    assert [item["identity"] for item in links] == ["TPEX:2330", "TWSE:2330"]
    assert links[0]["status"] == "unavailable"
    assert links[1]["status"] == "verified"


def test_daily_brief_macro_context_is_citation_bound() -> None:
    result = _provider_result()
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    brief = DailyResearchBriefApplicationService().generate(
        portfolio=pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]}),
        watchlist=None,
        daily_brief=None,
        loop_result=None,
        macro_snapshot=snapshot,
    )
    assert brief.macro_context
    restored = brief.from_dict(brief.to_dict())
    assert restored.macro_context == brief.macro_context
    tampered = cast(dict[str, Any], brief.to_dict())
    tampered["macro_context"][0]["reference_ids"] = ["fake"]
    with pytest.raises(ValueError):
        brief.from_dict(tampered)


def test_macro_signal_preserves_each_series_period_and_daily_brief_links() -> None:
    result = _provider_result()
    mixed = tuple(
        (
            replace(item, observation_period="2026-07-01", observed_date="2026-07-01")
            if item.series_id == "CPI"
            else item
        )
        for item in result.observations
    )
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=mixed,
        references=tuple(
            (
                replace(reference, observed_date="2026-07-01")
                if reference.series_id == "CPIAUCSL"
                else reference
            )
            for reference in result.references
        ),
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    signals = MacroRuleRegistry().evaluate(snapshot)
    cpi = next(item for item in signals if item.series_id == "CPI")
    assert cpi.observation_period == "2026-07-01"
    assert cpi.observed_date == "2026-07-01"
    assert cpi.fetched_at == NOW
    links = build_macro_links(
        snapshot,
        portfolio=pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]}),
        classifications={},
    )
    brief = DailyResearchBriefApplicationService().generate(
        portfolio=pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]}),
        watchlist=None,
        daily_brief=None,
        loop_result=None,
        macro_snapshot=snapshot,
        macro_links=links,
    )
    identity = next(item for item in brief.macro_context if item.get("kind") == "identity_link")
    assert identity["identity"] == "TWSE:2330"
    assert identity["macro_relation_status"] == "unavailable"
    limitations = identity.get("limitations")
    assert isinstance(limitations, list)
    assert "尚無可驗證總經關聯" in limitations


def test_fred_provider_parses_official_observation_date_header_and_no_release_date() -> None:
    payloads = {
        series_id: f"observation_date,{series_id}\n2026-08-07,{index + 1}.5\n".encode()
        for index, (_key, (series_id, _title, _unit)) in enumerate(FRED_SERIES.items())
    }

    def opener(url: str, *, timeout: float) -> _CsvResponse:
        del timeout
        series_id = url.split("id=", 1)[1]
        return _CsvResponse(payloads[series_id])

    result = FredMacroProvider(opener=opener).fetch()
    assert len(result.observations) == len(FRED_SERIES)
    assert all(item.release_date is None for item in result.observations)
    assert {item.observation_period for item in result.observations} == {"2026-08-07"}
    assert len(result.observation_history) == len(FRED_SERIES)


def test_fred_provider_retains_non_latest_periods_for_revision_replay() -> None:
    payloads = {
        series_id: (
            f"observation_date,{series_id}\n"
            f"2026-07-01,{index + 1}.0\n"
            f"2026-08-01,{index + 2}.0\n"
        ).encode()
        for index, (_key, (series_id, _title, _unit)) in enumerate(FRED_SERIES.items())
    }

    def opener(url: str, *, timeout: float) -> _CsvResponse:
        del timeout
        return _CsvResponse(payloads[url.split("id=", 1)[1]])

    result = FredMacroProvider(opener=opener).fetch()
    assert all(
        len([point for point in result.observation_history if point.series_id == key]) == 2
        for key in FRED_SERIES
    )


def test_revision_ledger_preserves_first_seen_and_is_idempotent(tmp_path) -> None:
    path = tmp_path / "revision-ledger.json"
    store = MacroRevisionLedgerStore(path)
    first = MacroObservationPoint("CPI", "2026-07-01", 1.0, _payload_hash("a"), NOW)
    revised = MacroObservationPoint(
        "CPI", "2026-07-01", 1.5, _payload_hash("b"), "2026-08-11T10:00:00+00:00"
    )
    store.update((first,))
    store.update((first,))
    store.update((revised,))
    entry = store.load()[0]
    assert entry.first_seen_value == 1.0
    assert entry.latest.value == 1.5
    assert entry.revised
    assert len(store.update((revised,))) == 1


def test_revision_ledger_same_value_new_fetch_time_is_not_a_revision(tmp_path) -> None:
    path = tmp_path / "revision-ledger.json"
    store = MacroRevisionLedgerStore(path)
    first = MacroObservationPoint("CPI", "2026-07-01", 1.0, _payload_hash("a"), NOW)
    refetched = MacroObservationPoint(
        "CPI", "2026-07-01", 1.0, _payload_hash("a"), "2026-08-12T10:00:00+00:00"
    )
    store.update((first,))
    before = path.read_bytes()
    entries = store.update((refetched,))
    assert len(entries) == 1
    assert not entries[0].revised
    assert path.read_bytes() == before


def test_revision_ledger_same_value_changed_payload_hash_is_not_a_revision(tmp_path) -> None:
    path = tmp_path / "revision-ledger.json"
    store = MacroRevisionLedgerStore(path)
    first = MacroObservationPoint("CPI", "2026-07-01", 1.0, _payload_hash("a"), NOW)
    refetched = MacroObservationPoint(
        "CPI",
        "2026-07-01",
        1.0,
        _payload_hash("different-csv"),
        "2026-08-12T10:00:00+00:00",
    )
    store.update((first,))
    before = path.read_bytes()
    entries = store.update((refetched,))
    assert len(entries) == 1
    assert not entries[0].revised
    assert path.read_bytes() == before


def test_revision_ledger_non_latest_change_is_recorded_when_latest_is_unchanged(tmp_path) -> None:
    path = tmp_path / "revision-ledger.json"
    store = MacroRevisionLedgerStore(path)
    first = (
        MacroObservationPoint("CPI", "2026-07-01", 1.0, _payload_hash("july"), NOW),
        MacroObservationPoint("CPI", "2026-08-01", 2.0, _payload_hash("august"), NOW),
    )
    store.update(first)
    july_revision = MacroObservationPoint(
        "CPI",
        "2026-07-01",
        1.5,
        _payload_hash("july-revised"),
        "2026-08-12T10:00:00+00:00",
    )
    latest_refetch = MacroObservationPoint(
        "CPI",
        "2026-08-01",
        2.0,
        _payload_hash("august-new-csv"),
        "2026-08-12T10:00:00+00:00",
    )
    entries = store.update((july_revision, latest_refetch))
    by_period = {entry.observation_period: entry for entry in entries}
    assert [point.value for point in by_period["2026-07-01"].observations] == [1.0, 1.5]
    assert [point.value for point in by_period["2026-08-01"].observations] == [2.0]


def test_revision_ledger_restart_replay_is_byte_idempotent(tmp_path) -> None:
    path = tmp_path / "revision-ledger.json"
    point = MacroObservationPoint("CPI", "2026-07-01", 1.0, _payload_hash("a"), NOW)
    MacroRevisionLedgerStore(path).update((point,))
    before = path.read_bytes()
    MacroRevisionLedgerStore(path).update((point,))
    assert path.read_bytes() == before


def test_revision_ledger_atomic_fault_preserves_previous_bytes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "revision-ledger.json"
    store = MacroRevisionLedgerStore(path)
    first = MacroObservationPoint("CPI", "2026-07-01", 1.0, _payload_hash("a"), NOW)
    revised = MacroObservationPoint("CPI", "2026-07-01", 1.5, _payload_hash("b"), NOW)
    store.update((first,))
    before = path.read_bytes()
    monkeypatch.setattr(
        store, "_write_atomic", lambda _path, _payload: (_ for _ in ()).throw(OSError("fault"))
    )
    with pytest.raises(OSError):
        store.update((revised,))
    assert path.read_bytes() == before


def test_revision_ledger_corruption_and_publish_failure_fail_closed(tmp_path, monkeypatch) -> None:
    path = tmp_path / "revision-ledger.json"
    store = MacroRevisionLedgerStore(path)
    point = MacroObservationPoint("CPI", "2026-07-01", 1.0, _payload_hash("a"), NOW)
    store.update((point,))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ledger_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MacroSnapshotError):
        store.load()
    path.unlink()
    monkeypatch.setattr(
        store, "_write_atomic", lambda _path, _payload: (_ for _ in ()).throw(OSError("fault"))
    )
    with pytest.raises(OSError):
        store.update((point,))
    assert not path.exists()


@pytest.mark.parametrize(
    ("header", "body"),
    [
        ("wrong_date,UNRATE", "2026-08-07,1.2"),
        ("observation_date,WRONG", "2026-08-07,1.2"),
        ("observation_date,UNRATE", "2026-08-07,not-a-number"),
        ("observation_date,UNRATE", "2026-08-07,."),
    ],
)
def test_fred_provider_rejects_malformed_payload_instead_of_calling_it_unavailable(
    header: str, body: str
) -> None:
    payload = f"{header}\n{body}\n".encode()
    provider = FredMacroProvider(opener=lambda _url, timeout: _CsvResponse(payload))
    with pytest.raises(FredPayloadError):
        provider._parse_csv_payload(payload, series_id="UNRATE")


def test_fred_fetch_surfaces_parser_contract_error_not_endpoint_warning() -> None:
    payload = b"wrong_date,UNRATE\n2026-08-07,1.2\n"
    provider = FredMacroProvider(opener=lambda _url, timeout: _CsvResponse(payload))
    with pytest.raises(FredPayloadError):
        provider.fetch()


def test_snapshot_timestamps_and_reference_fetch_time_are_record_integrity_bound() -> None:
    result = _provider_result()
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    payload = cast(dict[str, Any], snapshot.to_dict())
    payload["generated_at"] = "2026-08-11T10:00:00+00:00"
    with pytest.raises(MacroSnapshotError):
        MacroSnapshot.from_dict(payload)
    payload = cast(dict[str, Any], snapshot.to_dict())
    payload["references"][0]["fetched_at"] = "2026-08-11T10:00:00+00:00"
    with pytest.raises(MacroSnapshotError):
        MacroSnapshot.from_dict(payload)


def test_snapshot_exact_records_have_distinct_immutable_history_names(tmp_path) -> None:
    result = _provider_result()
    first = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    second = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat("2026-08-11T10:00:00+00:00"),
        as_of_date="2026-08-07",
    )
    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    assert first.record_sha256 != second.record_sha256
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")
    store.save(first)
    store.save(second)
    assert len(store.history()) == 2
    assert store.load_latest() == second


def test_repeated_identical_record_is_idempotent(tmp_path) -> None:
    result = _provider_result()
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")
    store.save(snapshot)
    store.save(snapshot)
    assert store.history() == (snapshot,)
    assert store.load_latest() == snapshot


def test_history_publish_failure_cleans_only_own_partial_record(tmp_path, monkeypatch) -> None:
    result = _provider_result()
    snapshot = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")

    def fail_write(_descriptor: int, _payload: bytes) -> int:
        raise OSError("injected history failure")

    monkeypatch.setattr("stock_tool.application.macro_snapshot.os.write", fail_write)
    with pytest.raises(OSError):
        store.save(snapshot)
    assert not list((tmp_path / "history").glob("snapshot-*.json"))


@pytest.mark.parametrize(
    ("current_offset", "previous_offset", "expected"),
    [(1.0, 0.0, "rising"), (-1.0, 0.0, "falling"), (0.0, 0.0, "unchanged")],
)
def test_rule_registry_detects_previous_period_direction(
    current_offset: float, previous_offset: float, expected: str
) -> None:
    current_result = _provider_result(value_offset=current_offset, observed_date="2026-08-07")
    previous_result = _provider_result(value_offset=previous_offset, observed_date="2026-08-06")
    current = MacroSnapshot.create(
        status="ready",
        source=current_result.source,
        observations=current_result.observations,
        references=current_result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    previous = MacroSnapshot.create(
        status="ready",
        source=previous_result.source,
        observations=previous_result.observations,
        references=previous_result.references,
        generated_at=datetime.fromisoformat("2026-08-09T10:00:00+00:00"),
        as_of_date="2026-08-06",
    )
    assert {item.status for item in MacroRuleRegistry().evaluate(current, previous)} == {expected}


def test_rule_registry_marks_same_period_revision_and_first_seen() -> None:
    current_result = _provider_result(value_offset=1.0, observed_date="2026-08-07")
    previous_result = _provider_result(value_offset=0.0, observed_date="2026-08-07")
    current = MacroSnapshot.create(
        status="ready",
        source=current_result.source,
        observations=current_result.observations,
        references=current_result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    previous = MacroSnapshot.create(
        status="ready",
        source=previous_result.source,
        observations=previous_result.observations,
        references=previous_result.references,
        generated_at=datetime.fromisoformat("2026-08-09T10:00:00+00:00"),
        as_of_date="2026-08-07",
    )
    assert {item.status for item in MacroRuleRegistry().evaluate(current, previous)} == {"revised"}
    assert {item.status for item in MacroRuleRegistry().evaluate(current, previous=None)} == {
        "insufficient_data"
    }


def test_latest_publish_failure_keeps_previous_latest_and_immutable_history(
    tmp_path, monkeypatch
) -> None:
    result = _provider_result()
    first = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat(NOW),
        as_of_date="2026-08-07",
    )
    second = MacroSnapshot.create(
        status="ready",
        source=result.source,
        observations=result.observations,
        references=result.references,
        generated_at=datetime.fromisoformat("2026-08-11T10:00:00+00:00"),
        as_of_date="2026-08-07",
    )
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")
    store.save(first)
    original = store._write_atomic

    def fail_latest(path: Path, payload: bytes) -> None:
        if path == store.latest_path:
            raise OSError("injected latest failure")
        original(path, payload)

    monkeypatch.setattr(store, "_write_atomic", fail_latest)
    with pytest.raises(OSError):
        store.save(second)
    assert store.load_latest() == first
    assert {item.record_sha256 for item in store.history()} == {
        first.record_sha256,
        second.record_sha256,
    }


def test_zero_provider_result_degrades_to_stale_or_unavailable(tmp_path) -> None:
    result = _provider_result()
    store = MacroSnapshotStore(tmp_path / "latest.json", tmp_path / "history")
    service = MacroSnapshotApplicationService(store, provider=_Provider(result))
    ready = service.refresh()
    empty = MacroProviderResult((), (), ("official returned no rows",), source="FRED official")
    stale = service.refresh(provider=_Provider(empty))
    assert ready.status == "ready"
    assert stale.status == "stale"
    assert stale.observations and all(
        item.freshness_status == "stale" for item in stale.observations
    )

    no_cache_store = MacroSnapshotStore(tmp_path / "no-cache.json", tmp_path / "no-cache-history")
    unavailable = MacroSnapshotApplicationService(no_cache_store).refresh(provider=_Provider(empty))
    assert unavailable.status == "unavailable"
    assert unavailable.observations == ()
    assert unavailable.references == ()


@pytest.mark.parametrize("status", ["ready", "partial", "stale", "unavailable"])
def test_status_invariants_fail_closed(status: str) -> None:
    result = _provider_result()
    if status == "ready":
        observations = result.observations[:-1]
        references = result.references[:-1]
        as_of = "2026-08-07"
    elif status == "partial":
        observations = result.observations
        references = result.references
        as_of = "2026-08-07"
    elif status == "stale":
        observations = tuple(
            replace(item, freshness_status="fresh") for item in result.observations
        )
        references = result.references
        as_of = "2026-08-07"
    else:
        observations = result.observations[:1]
        references = result.references[:1]
        as_of = "2026-08-07"
    with pytest.raises(MacroSnapshotError):
        MacroSnapshot.create(
            status=status,
            source=result.source,
            observations=observations,
            references=references,
            generated_at=datetime.fromisoformat(NOW),
            as_of_date=as_of,
        )
