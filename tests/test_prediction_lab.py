"""Adversarial and deterministic tests for Prediction Lab Phase 0."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from stock_tool.application.market_monitor import (
    MarketBreadth,
    MarketQuoteRow,
    MarketSnapshot,
    MarketSnapshotMetadata,
    MarketSourceMetadata,
)
from stock_tool.application.prediction_lab import (
    PredictionLabApplicationService,
    PredictionLabError,
    PredictionLabStore,
    PredictionOutcome,
    PredictionRecord,
    MarketTradingCalendar,
    economic_input_fingerprint,
    _atomic_create_json,
)
import stock_tool.application.prediction_lab as prediction_lab_module

HASH_A = "a" * 64
HASH_B = "b" * 64


def _record(*, created_at: datetime | None = None, score: float = 1.0) -> PredictionRecord:
    return PredictionRecord.create(
        created_at=created_at or datetime(2026, 8, 13, 10, tzinfo=timezone.utc),
        trading_date="2026-08-13",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=score,
        input_hashes=(HASH_A,),
        source_hashes=(HASH_B,),
    )


def _snapshot(*, status: str = "ready", freshness: str = "fresh", count: int = 3) -> MarketSnapshot:
    rows = tuple(
        MarketQuoteRow(
            symbol=str(2330 + index),
            market="TWSE",
            name=f"公司{index}",
            close=100 + index,
            change_pct=float(count - index),
            volume=1000,
            value=100000,
        )
        for index in range(count)
    )
    metadata = MarketSnapshotMetadata(
        schema_version=2,
        source="official",
        endpoint="https://example.test/twse",
        market="TWSE",
        data_date="2026-08-13",
        fetched_at="2026-08-13T09:00:00+00:00",
        valid_rows=count,
        excluded_rows=0,
        coverage=1.0,
        payload_sha256=HASH_B,
        status=status,
        freshness=freshness,
    )
    source = MarketSourceMetadata(
        market="TWSE",
        source="official",
        endpoint="https://example.test/twse",
        data_date="2026-08-13",
        fetched_at="2026-08-13T09:00:00+00:00",
        valid_rows=count,
        excluded_rows=0,
        coverage=1.0,
        payload_sha256=HASH_B,
    )
    return MarketSnapshot(
        metadata=metadata,
        quotes=rows,
        breadth=MarketBreadth(up=count, down=0, flat=0, unknown=0, valid_total=count),
        source_metadata=(source,),
    )


def test_prediction_record_round_trip_and_exact_integrity() -> None:
    record = _record()
    assert len(record.prediction_id.removeprefix("prediction-")) == 64
    assert record.horizon_trading_days == 5
    assert record.to_dict()["horizon_trading_days"] == 5
    assert PredictionRecord.from_dict(record.to_dict()) == record
    tampered = record.to_dict()
    tampered["created_at"] = "2026-08-13T11:00:00+00:00"
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(tampered)
    tampered = record.to_dict()
    tampered["identity"] = "TPEX:2330"
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(tampered)
    tampered = record.to_dict()
    tampered["horizon_trading_days"] = 20
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(tampered)
    tampered = record.to_dict()
    tampered["created_at"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(tampered)


def test_store_is_append_only_and_replay_is_idempotent(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    original = store.save_prediction(_record())
    replay = store.save_prediction(
        _record(created_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc))
    )
    assert replay == original
    path = store.predictions_dir / f"{original.prediction_id}.json"
    before = path.read_bytes()
    changed = store.save_prediction(_record(score=2.0))
    assert changed.prediction_id != original.prediction_id
    assert len(store.predictions()) == 2
    assert path.read_bytes() == before


def test_atomic_create_file_exists_preserves_winner(tmp_path: Path) -> None:
    target = tmp_path / "prediction.json"
    target.write_bytes(b'{"winner":true}\n')
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        _atomic_create_json(target, {"loser": True})
    assert target.read_bytes() == before


def test_atomic_create_failure_cleans_only_its_own_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "partial.json"

    def fail_fsync(_fd: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(prediction_lab_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError):
        _atomic_create_json(target, {"value": 1})
    assert not target.exists()


def test_concurrent_exclusive_create_has_one_winner(tmp_path: Path) -> None:
    target = tmp_path / "claim.json"
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt(value: str) -> None:
        barrier.wait()
        try:
            _atomic_create_json(target, {"value": value})
            results.append("winner")
        except FileExistsError:
            results.append("duplicate")

    threads = [threading.Thread(target=attempt, args=(str(index),)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["duplicate", "winner"]
    assert json.loads(target.read_text(encoding="utf-8"))["value"] in {"0", "1"}


def test_registers_top_middle_bottom_for_both_horizons(tmp_path: Path) -> None:
    service = PredictionLabApplicationService(PredictionLabStore(tmp_path).ensure())
    result = service.register_from_market_snapshot(
        _snapshot(), trading_date="2026-08-13", input_hashes=(HASH_A,)
    )
    assert result.status == "success"
    assert {(record.bucket, record.horizon) for record in result.records} == {
        (bucket, horizon) for bucket in ("top", "middle", "bottom") for horizon in (5, 20)
    }
    summary = service.summary(trading_date="2026-08-13")
    assert summary.registered_today == 6
    assert summary.bucket_counts == {"top": 2, "middle": 2, "bottom": 2}
    assert summary.outcome_counts["5"]["pending"] == 3
    assert summary.outcome_counts["20"]["pending"] == 3


def test_snapshot_that_is_stale_or_too_small_fails_closed(tmp_path: Path) -> None:
    service = PredictionLabApplicationService(PredictionLabStore(tmp_path).ensure())
    stale = service.register_from_market_snapshot(
        _snapshot(status="stale", freshness="stale"),
        trading_date="2026-08-13",
        input_hashes=(HASH_A,),
    )
    small = service.register_from_market_snapshot(
        _snapshot(count=2), trading_date="2026-08-13", input_hashes=(HASH_A,)
    )
    assert stale.status == "unavailable" and small.status == "unavailable"
    assert service.summary().prediction_count == 0


def test_outcome_is_bound_to_prediction_and_does_not_mutate_prediction(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    outcome = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        entry_price=100,
        exit_price=105,
        benchmark_return=0.02,
        calendar=MarketTradingCalendar.default_for("TWSE"),
        entry_price_identity={
            "identity": "TWSE:2330",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        exit_price_identity={
            "identity": "TWSE:2330",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        benchmark_identity={
            "identity": "TWSE:TAIEX",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        source_hashes=(HASH_B,),
    )
    assert outcome.status == "evaluated"
    store.save_outcome(outcome)
    assert store.save_outcome(outcome) == outcome
    assert store.predictions()[0] == record
    assert store.outcomes()[0].raw_return == pytest.approx(0.05)


def test_outcome_unknown_prediction_and_tampered_hash_are_rejected(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = _record()
    outcome = PredictionOutcome.create(prediction=record, evaluated_at=datetime.now(timezone.utc))
    with pytest.raises(PredictionLabError):
        store.save_outcome(outcome)
    payload = record.to_dict()
    payload["record_sha256"] = "0" * 64
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", True),
        ("horizon", 7),
        ("bucket", "unknown"),
        ("rank", 0),
        ("universe_size", 2),
        ("created_at", "2026-08-13T10:00:00"),
        ("input_hashes", ["bad"]),
    ),
)
def test_prediction_adversarial_fields_fail_closed(field: str, value: object) -> None:
    payload = _record().to_dict()
    payload[field] = value
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(payload)


def test_store_rejects_unexpected_files_and_stale_index(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    store.save_prediction(_record())
    (store.predictions_dir / "unexpected.txt").write_text("no", encoding="utf-8")
    with pytest.raises(PredictionLabError):
        store.predictions()
    (store.predictions_dir / "unexpected.txt").unlink()
    store.index_path.write_text("{}", encoding="utf-8")
    with pytest.raises(PredictionLabError):
        store.load_index()
    assert store.rebuild_index()["schema_version"] == 1


def test_store_rebuilds_missing_index_from_immutable_records(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    store.index_path.unlink()
    rebuilt = store.load_index()
    assert rebuilt["predictions"] == [record.prediction_id]


def test_store_rejects_corrupt_immutable_record(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    path = store.predictions_dir / "prediction-corrupt.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(PredictionLabError):
        store.predictions()


def test_outcome_statuses_and_invalid_payloads(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    pending = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
    )
    eligible = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        status="eligible",
    )
    unavailable = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        status="unavailable",
        missing_reason="no benchmark",
    )
    assert pending.status == "pending"
    assert eligible.status == "eligible"
    assert unavailable.status == "unavailable"
    payload = pending.to_dict()
    payload["status"] = "not-a-status"
    with pytest.raises(PredictionLabError):
        PredictionOutcome.from_dict(payload, prediction=record)
    with pytest.raises(PredictionLabError):
        PredictionOutcome.create(
            prediction=record,
            evaluated_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
            status="eligible",
        )
    with pytest.raises(PredictionLabError):
        PredictionOutcome.create(
            prediction=record,
            evaluated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            actual_available_date="2026-08-20",
            status="unavailable",
        )
    payload = pending.to_dict()
    payload["schema_version"] = True
    with pytest.raises(PredictionLabError):
        PredictionOutcome.from_dict(payload, prediction=record)


def test_service_rejects_missing_source_and_unknown_benchmark(tmp_path: Path) -> None:
    service = PredictionLabApplicationService(PredictionLabStore(tmp_path).ensure())
    no_source = _snapshot()
    no_source = MarketSnapshot(
        metadata=no_source.metadata,
        quotes=no_source.quotes,
        breadth=no_source.breadth,
        source_metadata=(),
    )
    assert (
        service.register_from_market_snapshot(no_source, trading_date="2026-08-13").status
        == "unavailable"
    )
    assert (
        service.register_from_market_snapshot(
            _snapshot(), trading_date="2026-08-13", benchmark_identity="BAD:INDEX"
        ).status
        == "unavailable"
    )


def test_registration_uses_market_qualified_benchmarks_for_mixed_markets(
    tmp_path: Path,
) -> None:
    base = _snapshot()
    tpex_quotes = tuple(replace(quote, market="TPEX") for quote in base.quotes)
    tpex_source = replace(base.source_metadata[0], market="TPEX")
    mixed = replace(
        base,
        quotes=base.quotes + tpex_quotes,
        source_metadata=base.source_metadata + (tpex_source,),
    )

    result = PredictionLabApplicationService(
        PredictionLabStore(tmp_path).ensure()
    ).register_from_market_snapshot(mixed, trading_date="2026-08-13")

    assert result.status == "success"
    assert {record.benchmark_identity for record in result.records if record.market == "TWSE"} == {
        "TWSE:TAIEX"
    }
    assert {record.benchmark_identity for record in result.records if record.market == "TPEX"} == {
        "TPEX:OTC"
    }


def test_economic_fingerprint_ignores_fetch_check_and_creation_times(tmp_path: Path) -> None:
    snapshot = _snapshot()
    changed_metadata = replace(
        snapshot.metadata,
        fetched_at="2026-08-13T10:00:00+00:00",
    )
    changed_source = replace(
        snapshot.source_metadata[0],
        fetched_at="2026-08-13T10:00:00+00:00",
    )
    replay = replace(snapshot, metadata=changed_metadata, source_metadata=(changed_source,))
    assert economic_input_fingerprint(
        snapshot, trading_date="2026-08-13"
    ) == economic_input_fingerprint(replay, trading_date="2026-08-13")
    store = PredictionLabStore(tmp_path).ensure()
    service = PredictionLabApplicationService(store)
    first = service.register_from_market_snapshot(snapshot, trading_date="2026-08-13")
    second = service.register_from_market_snapshot(replay, trading_date="2026-08-13")
    assert first.status == second.status == "success"
    assert [item.prediction_id for item in first.records] == [
        item.prediction_id for item in second.records
    ]
    assert len(store.predictions()) == 6
    assert len({item.prediction_id for item in store.predictions()}) == 6


def test_metadata_only_replay_preserves_prediction_winner_bytes(tmp_path: Path) -> None:
    snapshot = _snapshot()
    replay = replace(
        snapshot,
        metadata=replace(snapshot.metadata, fetched_at="2026-08-13T23:00:00+00:00"),
        source_metadata=(
            replace(snapshot.source_metadata[0], fetched_at="2026-08-13T23:00:00+00:00"),
        ),
    )
    first_service = PredictionLabApplicationService(
        PredictionLabStore(tmp_path).ensure(),
        now_fn=lambda: datetime(2026, 8, 13, 10, tzinfo=timezone.utc),
    )
    first = first_service.register_from_market_snapshot(snapshot, trading_date="2026-08-13")
    before = {
        path.name: path.read_bytes() for path in first_service.store.predictions_dir.glob("*.json")
    }
    second_service = PredictionLabApplicationService(
        PredictionLabStore(tmp_path).ensure(),
        now_fn=lambda: datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
    )
    second = second_service.register_from_market_snapshot(replay, trading_date="2026-08-13")
    after = {
        path.name: path.read_bytes() for path in second_service.store.predictions_dir.glob("*.json")
    }
    assert first.status == second.status == "success"
    assert [item.prediction_id for item in first.records] == [
        item.prediction_id for item in second.records
    ]
    assert len(after) == len(before) == 6
    assert after == before


def test_economic_change_creates_new_records(tmp_path: Path) -> None:
    snapshot = _snapshot()
    changed = replace(
        snapshot,
        quotes=tuple(
            replace(quote, change_pct=(99.0 if quote.symbol == "2330" else quote.change_pct))
            for quote in snapshot.quotes
        ),
    )
    service = PredictionLabApplicationService(PredictionLabStore(tmp_path).ensure())
    first = service.register_from_market_snapshot(snapshot, trading_date="2026-08-13")
    second = service.register_from_market_snapshot(changed, trading_date="2026-08-13")
    assert first.status == second.status == "success"
    assert len(service.store.predictions()) == 12
    assert {item.prediction_id for item in first.records}.isdisjoint(
        {item.prediction_id for item in second.records}
    )


def test_manual_and_scheduler_competition_share_economic_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot()
    services = [
        PredictionLabApplicationService(PredictionLabStore(tmp_path).ensure()),
        PredictionLabApplicationService(PredictionLabStore(tmp_path).ensure()),
    ]
    barrier = threading.Barrier(2)
    first_prediction_barrier = threading.Barrier(2)
    first_prediction_calls = 0
    calls_lock = threading.Lock()
    original_atomic = prediction_lab_module._atomic_create_json

    def gate_first_prediction(path: Path, payload: dict[str, Any]) -> None:
        nonlocal first_prediction_calls
        wait_for_peer = False
        if path.name.startswith("prediction-"):
            with calls_lock:
                if first_prediction_calls < 2:
                    first_prediction_calls += 1
                    wait_for_peer = True
        if wait_for_peer:
            first_prediction_barrier.wait(timeout=10)
        original_atomic(path, payload)

    monkeypatch.setattr(prediction_lab_module, "_atomic_create_json", gate_first_prediction)
    results: list[Any] = []
    results_lock = threading.Lock()

    def run(service: PredictionLabApplicationService) -> None:
        barrier.wait()
        result = service.register_from_market_snapshot(snapshot, trading_date="2026-08-13")
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=run, args=(service,)) for service in services]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 2
    assert [result.status for result in results] == ["success", "success"]
    result_ids = [{record.prediction_id for record in result.records} for result in results]
    assert result_ids[0] == result_ids[1]
    assert len(result_ids[0]) == 6
    records = services[0].store.predictions()
    assert len(records) == 6
    winner_bytes = {
        path.name: path.read_bytes() for path in services[0].store.predictions_dir.glob("*.json")
    }
    assert winner_bytes == {
        path.name: path.read_bytes() for path in services[1].store.predictions_dir.glob("*.json")
    }
    assert set(services[0].store.load_index()["predictions"]) == result_ids[0]
    assert services[0].store.orphan_artifacts() == ()


def test_partial_visibility_fails_closed_then_bounded_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = _record()

    def pending_publish(_path: Path, _payload: dict[str, Any]) -> None:
        raise FileExistsError("winner is still publishing")

    monkeypatch.setattr(prediction_lab_module, "_atomic_create_json", pending_publish)
    started = time.monotonic()
    with pytest.raises(PredictionLabError, match="still pending"):
        store.save_prediction(record)
    assert time.monotonic() - started < 1.0
    assert tuple(store.predictions_dir.glob("*.json")) == ()

    monkeypatch.setattr(prediction_lab_module, "_atomic_create_json", _atomic_create_json)
    assert store.save_prediction(record) == record
    assert store.orphan_artifacts() == ()


def test_manual_and_scheduler_competition_in_independent_processes(
    tmp_path: Path,
) -> None:
    script = (
        "from datetime import datetime, timezone\n"
        "from pathlib import Path\n"
        "import json, sys, time\n"
        "from stock_tool.application.market_monitor import (MarketBreadth, MarketQuoteRow, "
        "MarketSnapshot, MarketSnapshotMetadata, MarketSourceMetadata)\n"
        "from stock_tool.application.prediction_lab import (PredictionLabApplicationService, "
        "PredictionLabStore)\n"
        "root=Path(sys.argv[1]); delay=float(sys.argv[2]); time.sleep(delay)\n"
        "ha='a'*64; hb='b'*64\n"
        "rows=tuple(MarketQuoteRow(symbol=str(2330+i), market='TWSE', name='fixture', "
        "close=100+i, change_pct=float(3-i), volume=1000, value=100000) for i in range(3))\n"
        "meta=MarketSnapshotMetadata(schema_version=2, source='official', "
        "endpoint='https://example.test/twse', market='TWSE', data_date='2026-08-13', "
        "fetched_at='2026-08-13T09:00:00+00:00', valid_rows=3, excluded_rows=0, "
        "coverage=1.0, payload_sha256=hb, status='ready', freshness='fresh')\n"
        "source=MarketSourceMetadata(market='TWSE', source='official', "
        "endpoint='https://example.test/twse', data_date='2026-08-13', "
        "fetched_at='2026-08-13T09:00:00+00:00', valid_rows=3, excluded_rows=0, "
        "coverage=1.0, payload_sha256=hb)\n"
        "snapshot=MarketSnapshot(metadata=meta, quotes=rows, "
        "breadth=MarketBreadth(up=3, down=0, flat=0, unknown=0, valid_total=3), "
        "source_metadata=(source,))\n"
        "service=PredictionLabApplicationService(PredictionLabStore(root).ensure(), "
        "now_fn=lambda: datetime(2026,8,13,10,tzinfo=timezone.utc))\n"
        "result=service.register_from_market_snapshot(snapshot, trading_date='2026-08-13')\n"
        "print(json.dumps({'status':result.status, 'ids':sorted(r.prediction_id for r in result.records)}))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parents[1])]
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), str(delay)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for delay in (0.0, 0.05)
    ]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        outputs.append(json.loads(stdout.strip()))
    assert [output["status"] for output in outputs] == ["success", "success"]
    assert outputs[0]["ids"] == outputs[1]["ids"]
    assert len(outputs[0]["ids"]) == 6
    store = PredictionLabStore(tmp_path).ensure()
    assert len(store.predictions()) == 6
    assert store.orphan_artifacts() == ()


def test_trading_calendar_is_explicit_and_market_qualified() -> None:
    calendar = MarketTradingCalendar.from_dates(
        market="TWSE",
        dates=("2026-02-12", "2026-02-13", "2026-02-19", "2026-02-20", "2026-02-23"),
        source_hash=HASH_A,
    )
    assert calendar.target_date("2026-02-12", 1) == "2026-02-13"
    assert calendar.target_date("2026-02-13", 1) == "2026-02-19"
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dates(
            market="US", dates=("2026-02-13", "2026-02-19"), source_hash=HASH_A
        ).target_date("2026-02-13", 5)


def test_evaluated_outcome_requires_complete_provenance_and_cost_contract() -> None:
    record = _record()
    calendar = MarketTradingCalendar.default_for(record.market)
    kwargs = dict(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        entry_price=100.0,
        exit_price=105.0,
        benchmark_return=0.02,
        transaction_cost_assumption=0.001,
        calendar=calendar,
        entry_price_identity={
            "identity": "TWSE:2330",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        exit_price_identity={
            "identity": "TWSE:2330",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        benchmark_identity={
            "identity": "TWSE:TAIEX",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        source_hashes=(HASH_B,),
    )
    outcome = PredictionOutcome.create(**kwargs)
    assert outcome.status == "evaluated"
    assert outcome.gross_return == pytest.approx(0.05)
    assert outcome.net_return < outcome.gross_return
    for bad in (
        {**kwargs, "benchmark_return": None},
        {**kwargs, "entry_price": 0},
        {**kwargs, "transaction_cost_assumption": -0.1},
    ):
        with pytest.raises(PredictionLabError):
            PredictionOutcome.create(**bad)


def test_outcome_state_cannot_downgrade_evaluated(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    calendar = MarketTradingCalendar.default_for(record.market)
    evaluated = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        entry_price=100,
        exit_price=105,
        benchmark_return=0.02,
        calendar=calendar,
        entry_price_identity={
            "identity": "TWSE:2330",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        exit_price_identity={
            "identity": "TWSE:2330",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        benchmark_identity={
            "identity": "TWSE:TAIEX",
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        source_hashes=(HASH_B,),
    )
    store.save_outcome(evaluated)
    pending = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        calendar=calendar,
    )
    with pytest.raises(PredictionLabError):
        store.save_outcome(pending)


def _evaluated_outcome(record: PredictionRecord, *, evaluated_at: datetime) -> PredictionOutcome:
    return PredictionOutcome.create(
        prediction=record,
        evaluated_at=evaluated_at,
        actual_available_date="2026-08-20",
        entry_price=100,
        exit_price=105,
        benchmark_return=0.02,
        calendar=MarketTradingCalendar.default_for(record.market),
        entry_price_identity={
            "identity": record.identity,
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        exit_price_identity={
            "identity": record.identity,
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        benchmark_identity={
            "identity": record.benchmark_identity,
            "effective_date": "2026-08-20",
            "payload_hash": HASH_B,
        },
        source_hashes=(HASH_B,),
    )


def test_outcome_transition_policy_allows_pending_to_evaluated(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    pending = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
    )
    store.save_outcome(pending)
    evaluated = _evaluated_outcome(
        record, evaluated_at=datetime(2026, 8, 20, 11, tzinfo=timezone.utc)
    )
    assert store.save_outcome(evaluated) == evaluated
    assert {item.status for item in store.outcomes()} == {"pending", "evaluated"}
    store.validate_graph()


def test_outcome_transition_policy_allows_pending_eligible_evaluated(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    pending = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
    )
    store.save_outcome(pending)
    eligible = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, 11, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        status="eligible",
    )
    store.save_outcome(eligible)
    evaluated = _evaluated_outcome(
        record, evaluated_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    )
    store.save_outcome(evaluated)
    assert [
        item.status for item in sorted(store.outcomes(), key=lambda item: item.evaluated_at)
    ] == [
        "pending",
        "eligible",
        "evaluated",
    ]
    store.validate_graph()


def test_rejected_downgrade_is_transactionally_inert(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    evaluated = _evaluated_outcome(
        record, evaluated_at=datetime(2026, 8, 20, 11, tzinfo=timezone.utc)
    )
    store.save_outcome(evaluated)
    before_files = {
        path.name: path.read_bytes()
        for path in (*store.outcomes_dir.glob("*"), store.index_path)
        if path.is_file()
    }
    pending = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 21, 11, tzinfo=timezone.utc),
    )
    with pytest.raises(PredictionLabError):
        store.save_outcome(pending)
    after_files = {
        path.name: path.read_bytes()
        for path in (*store.outcomes_dir.glob("*"), store.index_path)
        if path.is_file()
    }
    assert after_files == before_files
    assert len(tuple(store.outcomes_dir.glob("*.json"))) == 1
    store.validate_graph()


@pytest.mark.parametrize("downgrade_status", ("pending", "eligible", "unavailable"))
def test_evaluated_is_terminal_for_every_lower_status(
    tmp_path: Path, downgrade_status: str
) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    evaluated = _evaluated_outcome(
        record, evaluated_at=datetime(2026, 8, 20, 11, tzinfo=timezone.utc)
    )
    store.save_outcome(evaluated)
    kwargs: dict[str, Any] = {
        "prediction": record,
        "evaluated_at": datetime(2026, 8, 21, 11, tzinfo=timezone.utc),
        "calendar": MarketTradingCalendar.default_for(record.market),
        "status": downgrade_status,
    }
    if downgrade_status != "pending":
        kwargs["actual_available_date"] = "2026-08-20"
    if downgrade_status == "unavailable":
        kwargs["missing_reason"] = "late evidence unavailable"
    candidate = PredictionOutcome.create(**kwargs)
    before = {
        path.name: path.read_bytes()
        for path in (*store.outcomes_dir.glob("*.json"), store.index_path)
    }
    with pytest.raises(PredictionLabError):
        store.save_outcome(candidate)
    assert {
        path.name: path.read_bytes()
        for path in (*store.outcomes_dir.glob("*.json"), store.index_path)
    } == before
    store.validate_graph()


def test_unavailable_is_terminal_and_rejection_is_transactionally_inert(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    unavailable = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, 11, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        status="unavailable",
        missing_reason="benchmark unavailable",
    )
    store.save_outcome(unavailable)
    before = {path.name: path.read_bytes() for path in store.outcomes_dir.glob("*.json")}
    eligible = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        actual_available_date="2026-08-20",
        status="eligible",
    )
    with pytest.raises(PredictionLabError):
        store.save_outcome(eligible)
    assert {path.name: path.read_bytes() for path in store.outcomes_dir.glob("*.json")} == before
    store.validate_graph()


def test_index_publish_fault_keeps_immutable_outcome_rebuildable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    evaluated = _evaluated_outcome(
        record, evaluated_at=datetime(2026, 8, 20, 11, tzinfo=timezone.utc)
    )
    original_rebuild = store.rebuild_index

    def fail_projection() -> dict[str, Any]:
        raise OSError("injected index publish failure")

    monkeypatch.setattr(store, "rebuild_index", fail_projection)
    with pytest.raises(OSError):
        store.save_outcome(evaluated)
    assert len(tuple(store.outcomes_dir.glob("*.json"))) == 1
    store.validate_graph()
    monkeypatch.setattr(store, "rebuild_index", original_rebuild)
    rebuilt = store.rebuild_index()
    assert evaluated.outcome_fingerprint in rebuilt["outcomes"]


def test_atomic_publish_competition_uses_independent_processes(tmp_path: Path) -> None:
    target = tmp_path / "process.json"
    script = (
        "from pathlib import Path\nimport sys\n"
        "from stock_tool.application.prediction_lab import _atomic_create_json\n"
        "p=Path(sys.argv[1]); v=sys.argv[2]\n"
        "try:\n _atomic_create_json(p, {'value': v}); print('winner')\n"
        "except FileExistsError:\n print('duplicate')\n"
    )
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    one = subprocess.Popen(
        [sys.executable, "-c", script, str(target), "one"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
    )
    two = subprocess.Popen(
        [sys.executable, "-c", script, str(target), "two"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
    )
    outputs = [one.communicate(timeout=20)[0].strip(), two.communicate(timeout=20)[0].strip()]
    assert sorted(outputs) == ["duplicate", "winner"]
    assert json.loads(target.read_text(encoding="utf-8"))["value"] in {"one", "two"}


def test_prediction_lab_contract_rejects_calendar_identity_and_outcome_variants(
    tmp_path: Path,
) -> None:
    """Exercise fail-closed branches for malformed calendar/record graphs."""

    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dates(market="CUSTOM", dates=("2026-08-13",), source_hash=HASH_A)
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dates(market="TWSE", dates=("bad-date",), source_hash=HASH_A)
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dates(
            market="TWSE", dates=("2026-08-13", "2026-08-13"), source_hash=HASH_A
        )
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dates(
            market="TWSE", dates=("2026-08-14", "2026-08-13"), source_hash=HASH_A
        )
    calendar = MarketTradingCalendar.default_for("TWSE")
    us_calendar = MarketTradingCalendar.default_for("US")
    assert us_calendar.market == "US"
    assert us_calendar.target_date("2026-08-13", 1) > "2026-08-13"
    with pytest.raises(PredictionLabError):
        calendar.target_date("2026-08-13", True)
    calendar_payload = calendar.to_dict()
    calendar_payload["schema_version"] = True
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dict(calendar_payload)
    calendar_payload = calendar.to_dict()
    calendar_payload["source_hash"] = HASH_B
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dict(calendar_payload)
    calendar_payload = calendar.to_dict()
    calendar_payload["identity"] = "calendar-forged"
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dict(calendar_payload)

    record_payload = _record().to_dict()
    record_payload.pop("market")
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(record_payload)
    record_payload = _record().to_dict()
    record_payload["symbol"] = "2330.TW"
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(record_payload)
    record_payload = _record().to_dict()
    record_payload["horizon"] = 99
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(record_payload)
    record_payload = _record().to_dict()
    record_payload["deterministic_score"] = "not-a-number"
    with pytest.raises(PredictionLabError):
        PredictionRecord.from_dict(record_payload)

    record = _record()
    pending = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
    )
    pending_payload = pending.to_dict()
    pending_payload["source_hashes"] = "bad"
    with pytest.raises(PredictionLabError):
        PredictionOutcome.from_dict(pending_payload, prediction=record)
    pending_payload = pending.to_dict()
    pending_payload["actual_available_date"] = "2026-08-20"
    with pytest.raises(PredictionLabError):
        PredictionOutcome.from_dict(pending_payload, prediction=record)
    unavailable = PredictionOutcome.create(
        prediction=record,
        evaluated_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
        status="unavailable",
        missing_reason="no verified price",
    )
    unavailable_payload = unavailable.to_dict()
    unavailable_payload["missing_reason"] = ""
    with pytest.raises(PredictionLabError):
        PredictionOutcome.from_dict(unavailable_payload, prediction=record)
    with pytest.raises(PredictionLabError):
        PredictionOutcome.create(
            prediction=record,
            evaluated_at=datetime(2026, 8, 13, 11, tzinfo=timezone.utc),
            status=cast(Any, "unknown"),
        )

    store = PredictionLabStore(tmp_path).ensure()
    store.save_prediction(record)
    service = PredictionLabApplicationService(store)
    corrupt = store.predictions_dir / f"{record.prediction_id}.json"
    corrupt.write_text("{}", encoding="utf-8")
    assert service.summary().status == "unavailable"
