"""RED contract tests for Sprint 33 Prediction Lab Phase 1 settlement."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from stock_tool.application.prediction_lab import (
    BenchmarkEvidence,
    MarketTradingCalendar,
    PredictionLabStore,
    PredictionOutcomeEvaluator,
    PredictionRecord,
    PriceEvidence,
    _target_date,
    _atomic_create_json,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
DATES = tuple(f"2026-08-{day:02d}" for day in range(13, 22))


def _record() -> PredictionRecord:
    return PredictionRecord.create(
        created_at=datetime(2026, 8, 13, 9, tzinfo=timezone.utc),
        trading_date="2026-08-13",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=4.2,
        source_hashes=(HASH_A,),
        entry_price_reference={
            "identity": "TWSE:2330",
            "value": 100.0,
            "effective_trading_date": "2026-08-13",
            "provider": "official-replay",
            "payload_hash": HASH_A,
        },
    )


class _Provider:
    def __init__(self, *, exit_price: float | None = 105.0) -> None:
        self.calendar_calls = 0
        self.price_calls: list[tuple[str, str]] = []
        self.benchmark_calls: list[tuple[str, str]] = []
        self.exit_price = exit_price

    def calendar(self, market: str) -> MarketTradingCalendar:
        self.calendar_calls += 1
        return MarketTradingCalendar.from_dates(market=market, dates=DATES, source_hash=HASH_B)

    def price(self, identity: str, effective_date: str) -> PriceEvidence | None:
        self.price_calls.append((identity, effective_date))
        if effective_date == "2026-08-13":
            value = 100.0
        else:
            value = self.exit_price
        if value is None:
            return None
        return PriceEvidence(
            identity=identity,
            value=value,
            effective_trading_date=effective_date,
            provider="official-replay",
            payload_hash=HASH_A,
        )

    def benchmark(self, identity: str, effective_date: str) -> BenchmarkEvidence | None:
        self.benchmark_calls.append((identity, effective_date))
        return BenchmarkEvidence(
            identity=identity,
            return_value=0.02,
            effective_trading_date=effective_date,
            provider="official-replay",
            payload_hash=HASH_B,
        )


def test_phase1_evaluator_settles_due_5_day_sample_and_is_idempotent(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    record = store.save_prediction(_record())
    provider = _Provider()
    evaluator = PredictionOutcomeEvaluator(
        store,
        provider,
        transaction_cost_assumption=0.001,
        now_fn=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    first = evaluator.evaluate_due(as_of="2026-08-20")
    assert first.evaluated_count == 1
    assert first.outcomes[0].status == "evaluated"
    assert first.outcomes[0].net_return == pytest.approx(0.049)
    before = (
        store.outcomes_dir / f"outcome-{first.outcomes[0].outcome_fingerprint}.json"
    ).read_bytes()

    replay = evaluator.evaluate_due(as_of="2026-08-20")
    assert replay.evaluated_count == 1
    assert replay.outcomes[0].outcome_fingerprint == first.outcomes[0].outcome_fingerprint
    assert (
        store.outcomes_dir / f"outcome-{first.outcomes[0].outcome_fingerprint}.json"
    ).read_bytes() == before
    assert len(store.outcomes()) == 1
    assert record.prediction_id == store.predictions()[0].prediction_id


def test_phase1_evaluator_keeps_future_sample_pending(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    store.save_prediction(_record())
    result = PredictionOutcomeEvaluator(
        store,
        _Provider(),
        now_fn=lambda: datetime(2026, 8, 14, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-14")
    assert result.pending_count == 1
    assert result.outcomes[0].status == "pending"


def test_phase1_evaluator_marks_missing_exit_as_eligible_not_fake_evaluated(
    tmp_path: Path,
) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    store.save_prediction(_record())
    result = PredictionOutcomeEvaluator(
        store,
        _Provider(exit_price=None),
        now_fn=lambda: datetime(2026, 8, 20, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")
    assert result.eligible_count == 1
    assert result.outcomes[0].status == "eligible"
    assert result.outcomes[0].entry_price is None
    assert result.outcomes[0].net_return is None


def test_phase1_transient_provider_failure_remains_retryable(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    store.save_prediction(_record())

    class TransientProvider(_Provider):
        def price(self, identity: str, effective_date: str) -> PriceEvidence | None:
            if effective_date != "2026-08-13":
                raise OSError("temporary provider timeout")
            return super().price(identity, effective_date)

    result = PredictionOutcomeEvaluator(
        store,
        TransientProvider(),
        now_fn=lambda: datetime(2026, 8, 20, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")

    assert result.eligible_count == 1
    assert result.unavailable_count == 0
    assert result.outcomes[0].status == "eligible"


def test_phase1_evaluator_rejects_provider_identity_mismatch(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    store.save_prediction(_record())

    class BadProvider(_Provider):
        def price(self, identity: str, effective_date: str) -> PriceEvidence | None:
            value = super().price(identity, effective_date)
            if value is None:
                return None
            return PriceEvidence(
                identity="TPEX:2330",
                value=value.value,
                effective_trading_date=value.effective_trading_date,
                provider=value.provider,
                payload_hash=value.payload_hash,
            )

    result = PredictionOutcomeEvaluator(
        store,
        BadProvider(),
        now_fn=lambda: datetime(2026, 8, 20, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")
    assert result.unavailable_count == 1
    assert result.outcomes[0].status == "unavailable"


def test_summary_exposes_insufficient_sample_warning_and_bucket_metrics(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path / "lab").ensure()
    record = store.save_prediction(_record())

    summary = store.summary(trading_date=record.trading_date)

    assert summary.warnings == ("樣本不足 30 筆，只能觀察，不能判定有效性。",)
    assert set(summary.bucket_metrics) == {"top", "middle", "bottom"}
    assert summary.bucket_metrics["top"]["count"] == 0


def test_phase1_supports_both_five_and_twenty_trading_day_horizons(tmp_path: Path) -> None:
    store = PredictionLabStore(tmp_path).ensure()
    five = _record()
    twenty = PredictionRecord.create(
        created_at=datetime(2026, 8, 13, 9, tzinfo=timezone.utc),
        trading_date=five.trading_date,
        market=five.market,
        symbol=five.symbol,
        horizon=20,
        bucket="bottom",
        rank=3,
        universe_size=3,
        deterministic_score=-2.0,
        source_hashes=(HASH_A,),
        entry_price_reference=five.entry_price_reference,
    )
    store.save_prediction(five)
    store.save_prediction(twenty)

    class LongProvider(_Provider):
        def calendar(self, market: str) -> MarketTradingCalendar:
            return MarketTradingCalendar.from_dates(
                market=market,
                dates=tuple(f"2026-08-{day:02d}" for day in range(13, 32))
                + tuple(f"2026-09-{day:02d}" for day in range(1, 16)),
                source_hash=HASH_B,
            )

    result = PredictionOutcomeEvaluator(
        store,
        LongProvider(),
        now_fn=lambda: datetime(2026, 8, 20, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")

    assert result.evaluated_count == 1
    assert result.pending_count == 1
    assert {item.status for item in result.outcomes} == {"evaluated", "pending"}


def test_atomic_prediction_publish_rejects_existing_winner_without_mutation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "records" / "prediction.json"
    payload = {"prediction_id": "prediction-1", "value": 1}
    _atomic_create_json(target, payload)
    before = target.read_bytes()

    with pytest.raises(FileExistsError):
        _atomic_create_json(target, {"prediction_id": "prediction-1", "value": 2})

    assert target.read_bytes() == before
    assert not list(target.parent.glob("*.claim"))
    assert not list(target.parent.glob("*.tmp"))


def test_prediction_store_explicit_layout_and_target_calendar_contract(
    tmp_path: Path,
) -> None:
    predictions = tmp_path / "predictions"
    outcomes = tmp_path / "outcomes"
    index = tmp_path / "projection.json"
    store = PredictionLabStore(
        predictions,
        outcomes_dir=outcomes,
        index_path=index,
    )
    assert store.root == tmp_path
    assert store.predictions_dir == predictions
    assert store.outcomes_dir == outcomes
    assert store.index_path == index
    with pytest.raises(ValueError, match="max_records"):
        PredictionLabStore(predictions, outcomes_dir=outcomes, max_records=0)

    calendar = MarketTradingCalendar.from_dates(market="TWSE", dates=DATES, source_hash=HASH_B)
    assert _target_date("2026-08-13", 5, calendar=calendar) == "2026-08-18"
