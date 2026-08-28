"""Sprint 33.1 trust-boundary regressions for production outcome composition."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from stock_tool.application.prediction_lab import (
    BenchmarkEvidence,
    MarketTradingCalendar,
    PriceEvidence,
    PredictionLabError,
    PredictionLabStore,
    PredictionOutcomeEvaluator,
    PredictionRecord,
    RuntimeCachedOutcomeProvider,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def _payload_hash(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def _price_row(
    symbol: str, market: str, day: str, close: float, provider: str = "official"
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "market": market,
        "date": day,
        "close": close,
        "provider": provider,
    }


def test_runtime_provider_benchmark_uses_market_qualified_taiex_rows() -> None:
    rows = [
        _price_row("TAIEX", "TWSE", "2026-08-13", 20_000.0),
        _price_row("TAIEX", "TWSE", "2026-08-20", 20_400.0),
    ]
    provider = RuntimeCachedOutcomeProvider(rows)

    evidence = provider.benchmark("TWSE:TAIEX", "2026-08-20", "2026-08-13")

    assert evidence is not None
    assert evidence.identity == "TWSE:TAIEX"
    assert evidence.start_trading_date == "2026-08-13"
    assert evidence.end_trading_date == "2026-08-20"
    assert evidence.start_value == 20_000.0
    assert evidence.end_value == 20_400.0
    assert evidence.return_value == pytest.approx(0.02)
    assert len(evidence.payload_hashes) == 2
    assert all(len(item) == 64 for item in evidence.payload_hashes)


def test_runtime_provider_calendar_is_verified_not_local_row_inference() -> None:
    provider = RuntimeCachedOutcomeProvider([_price_row("2330", "TWSE", "2026-08-13", 100.0)])

    calendar = provider.calendar("TWSE")

    assert calendar.identity.startswith("calendar-")
    assert len(calendar.source_hash) == 64
    # A missing security row does not remove a verified market date.
    assert "2026-08-14" in calendar.dates
    assert calendar.target_date("2026-08-13", 1) == "2026-08-14"


def test_benchmark_evidence_cannot_be_tampered_or_use_malformed_identity() -> None:
    with pytest.raises(PredictionLabError):
        BenchmarkEvidence(
            identity="TWSE:TAIEX",
            return_value=0.5,
            effective_trading_date="2026-08-20",
            provider="official",
            payload_hash=HASH_A,
            start_trading_date="2026-08-13",
            end_trading_date="2026-08-20",
            start_value=20_000.0,
            end_value=20_400.0,
        )
    with pytest.raises(PredictionLabError):
        BenchmarkEvidence(
            identity="TAIEX",
            return_value=0.02,
            effective_trading_date="2026-08-20",
            provider="official",
            payload_hash=HASH_A,
        )
    with pytest.raises(PredictionLabError, match="provider"):
        BenchmarkEvidence(
            identity="TWSE:TAIEX",
            return_value=0.02,
            effective_trading_date="2026-08-20",
            provider="",
            payload_hash=HASH_A,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"identity": "2330"}, "market-qualified"),
        ({"provider": ""}, "provider"),
        ({"price_field": "open"}, "price field"),
        ({"adjusted_raw_policy": "mixed"}, "adjusted/raw"),
    ],
)
def test_price_evidence_contract_rejects_untrusted_fields(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "identity": "TWSE:2330",
        "value": 100.0,
        "effective_trading_date": "2026-08-13",
        "provider": "official",
        "payload_hash": HASH_A,
    }
    values.update(kwargs)
    with pytest.raises(PredictionLabError, match=message):
        PriceEvidence(**values)  # type: ignore[arg-type]


def test_runtime_provider_benchmark_fails_closed_for_wrong_or_incomplete_rows() -> None:
    provider = RuntimeCachedOutcomeProvider([_price_row("TAIEX", "TWSE", "2026-08-20", 20_000.0)])
    assert provider.benchmark("TPEX:OTC", "2026-08-20") is None
    assert provider.benchmark("TWSE:TAIEX", "2026-08-19") is None
    assert provider.benchmark("TWSE:TAIEX", "2026-08-20", "2026-08-19") is None


def test_strict_runtime_evaluator_records_recomputable_benchmark_and_costs(tmp_path: Path) -> None:
    entry_hash = _payload_hash("entry")
    rows = [
        _price_row("2330", "TWSE", "2026-08-13", 100.0),
        _price_row("2330", "TWSE", "2026-08-20", 105.0),
        _price_row("TAIEX", "TWSE", "2026-08-13", 20_000.0),
        _price_row("TAIEX", "TWSE", "2026-08-20", 20_200.0),
    ]
    provider = RuntimeCachedOutcomeProvider(
        rows,
        corporate_actions=(
            {
                "identity": "TWSE:2330",
                "coverage_start": "2026-08-01",
                "coverage_end": "2026-08-31",
                "source": "official-corporate-action-coverage",
                "payload_hash": HASH_A,
                "policy_version": "corporate-action-coverage-v1",
                "no_action_confirmed": True,
            },
        ),
    )
    record = PredictionRecord.create(
        created_at=datetime(2026, 8, 13, 10, tzinfo=timezone.utc),
        trading_date="2026-08-13",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=1.0,
        input_hashes=(HASH_A,),
        source_hashes=(HASH_B,),
        benchmark_identity="TWSE:TAIEX",
        entry_price_reference={
            "identity": "TWSE:2330",
            "value": 100.0,
            "effective_trading_date": "2026-08-13",
            "provider": "official",
            "payload_hash": entry_hash,
            "price_field": "close",
            "adjusted_raw_policy": "raw",
        },
    )
    store = PredictionLabStore(tmp_path).ensure()
    store.save_prediction(record)

    result = PredictionOutcomeEvaluator(
        store,
        provider,
        now_fn=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")

    assert result.status == "success"
    outcome = result.outcomes[0]
    assert outcome.status == "evaluated"
    assert outcome.benchmark_identity is not None
    assert outcome.benchmark_identity["start_value"] == 20_000.0
    assert outcome.benchmark_identity["end_value"] == 20_200.0
    assert outcome.cost_policy_version == "backtest-cost-policy-v1"
    # The production policy is a complete round-trip assumption: buy/sell
    # commission, buy/sell slippage, and sell tax are all retained.
    assert outcome.transaction_cost_assumption == pytest.approx(0.00785)
    assert outcome.cost_components is not None
    assert outcome.cost_components["buy_commission_rate"] == pytest.approx(0.001425)
    assert outcome.cost_components["sell_commission_rate"] == pytest.approx(0.001425)
    assert outcome.cost_components["buy_slippage_rate"] == pytest.approx(0.001)
    assert outcome.cost_components["sell_slippage_rate"] == pytest.approx(0.001)
    assert outcome.cost_components["sell_tax_rate"] == pytest.approx(0.003)
    # The broker cash-flow formula applies slippage and fees to each leg;
    # it is intentionally not gross return minus a sum of rates.
    buy_price = 100.0 * (1.0 + 0.001)
    sell_price = 105.0 * (1.0 - 0.001)
    entry_cash = buy_price * (1.0 + 0.001425)
    exit_cash = sell_price * (1.0 - 0.001425 - 0.003)
    assert outcome.net_return == pytest.approx(exit_cash / entry_cash - 1.0)


def test_verified_calendar_hash_round_trip_rejects_tamper() -> None:
    calendar = MarketTradingCalendar.default_for("TPEX")
    payload = calendar.to_dict()
    payload["dates"] = list(payload["dates"])[1:]
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dict(payload)
