from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any, Callable

import pytest

from stock_tool.application.prediction_lab import (
    BenchmarkEvidence,
    build_runtime_cached_outcome_provider,
    MarketTradingCalendar,
    PredictionCostPolicy,
    PredictionLabError,
    PriceEvidence,
    RuntimeCachedOutcomeProvider,
    default_prediction_cost_policy,
)
import stock_tool.application.prediction_lab as prediction_lab_module
from stock_tool.data.storage import PersistedPriceProvenance, SQLitePriceStorage
from stock_tool.domain.models import Symbol

HASH = "a" * 64


def _row(symbol: str, market: str, day: str, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "market": market,
        "date": day,
        "close": close,
        "provider": "official-sidecar",
        "source_type": "cache",
    }


def test_official_calendar_has_hash_bound_provenance_and_known_twse_closures() -> None:
    calendar = MarketTradingCalendar.default_for("TWSE")

    assert calendar.source.startswith("TWSE official")
    assert calendar.endpoint.startswith("https://")
    assert calendar.fetched_at.endswith("+00:00")
    assert calendar.schema_version >= 2
    assert len(calendar.raw_payload_sha256 or "") == 64
    assert "2026-02-11" in calendar.dates
    assert "2026-02-23" in calendar.dates
    assert "2026-02-27" not in calendar.dates
    assert "2026-04-03" not in calendar.dates
    assert "2026-04-06" not in calendar.dates
    assert "2026-12-31" in calendar.dates
    assert calendar.target_date("2026-02-11", 1) == "2026-02-23"


@pytest.mark.parametrize("market", ["TWSE", "TPEX", "US"])
def test_official_calendar_supports_cross_year_without_weekday_fallback(market: str) -> None:
    calendar = MarketTradingCalendar.default_for(market)
    if market in {"TWSE", "TPEX"}:
        assert "2025-12-30" in calendar.dates
    else:
        # The bundled US payload is only proven for 2026; an unproven year
        # must not be synthesized merely to make a cross-year sequence.
        assert "2025-12-30" not in calendar.dates
    assert "2026-01-01" not in calendar.dates
    assert "2027-01-04" not in calendar.dates
    with pytest.raises(PredictionLabError, match="unavailable"):
        MarketTradingCalendar.default_for(market, year=2027)


def test_official_calendar_missing_payload_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "stock_tool.application.prediction_lab.OFFICIAL_CALENDAR_DATA_PATH",
        Path("does-not-exist/official-calendar.json"),
        raising=False,
    )
    with pytest.raises(PredictionLabError, match="calendar"):
        MarketTradingCalendar.default_for("TWSE")


def test_runtime_provider_exposes_market_benchmarks_for_all_supported_markets() -> None:
    rows = [
        _row("TAIEX", "TWSE", "2026-08-13", 100.0),
        _row("TAIEX", "TWSE", "2026-08-20", 101.0),
        _row("OTC", "TPEX", "2026-08-13", 200.0),
        _row("OTC", "TPEX", "2026-08-20", 202.0),
        _row("SPX", "US", "2026-08-13", 300.0),
        _row("SPX", "US", "2026-08-20", 303.0),
    ]
    provider = RuntimeCachedOutcomeProvider(rows)

    for identity, expected in (("TWSE:TAIEX", 0.01), ("TPEX:OTC", 0.01), ("US:SPX", 0.01)):
        evidence = provider.benchmark(identity, "2026-08-20", "2026-08-13")
        assert isinstance(evidence, BenchmarkEvidence)
        assert evidence.return_value == pytest.approx(expected)
        assert evidence.start_trading_date == "2026-08-13"
        assert evidence.end_trading_date == "2026-08-20"
        assert len(evidence.payload_hashes) == 2


def test_installed_like_sidecar_replays_market_benchmark_provenance(tmp_path: Path) -> None:
    storage = SQLitePriceStorage(tmp_path / "stock_data.sqlite")
    for symbol, market, first, last in (
        ("TAIEX", "TWSE", 100.0, 101.0),
        ("OTC", "TPEX", 200.0, 202.0),
        ("SPX", "US", 300.0, 303.0),
    ):
        storage.save_market_qualified_price_data(
            [
                {
                    "date": "2026-08-13",
                    "symbol": symbol,
                    "open": first,
                    "high": first,
                    "low": first,
                    "close": first,
                    "volume": 1.0,
                    "adjusted_close": None,
                },
                {
                    "date": "2026-08-20",
                    "symbol": symbol,
                    "open": last,
                    "high": last,
                    "low": last,
                    "close": last,
                    "volume": 1.0,
                    "adjusted_close": None,
                },
            ],
            provenance=PersistedPriceProvenance(
                symbol=Symbol.parse(symbol, market=market),
                provider="official-sidecar",
                provider_symbol=symbol,
                source_type="cache",
                last_data_date="2026-08-20",
                checked_at="2026-08-21T00:00:00+00:00",
            ),
        )
    provider = build_runtime_cached_outcome_provider(storage.database_path)
    assert provider is not None
    assert provider.benchmark("TWSE:TAIEX", "2026-08-20", "2026-08-13") is not None
    assert provider.benchmark("TPEX:OTC", "2026-08-20", "2026-08-13") is not None
    assert provider.benchmark("US:SPX", "2026-08-20", "2026-08-13") is not None


def test_calendar_payload_tamper_is_rejected() -> None:
    payload = MarketTradingCalendar.default_for("US").to_dict()
    payload["fetched_at"] = "2026-08-28T00:00:00+00:00"
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dict(payload)


def test_market_calendar_from_dates_without_official_provenance_is_explicit_only() -> None:
    calendar = MarketTradingCalendar.from_dates(
        market="TWSE",
        dates=("2026-08-13", "2026-08-14"),
        source_hash=HASH,
    )
    assert calendar.source == "explicit-test"
    assert calendar.raw_payload_sha256 == HASH


def _calendar_payload() -> dict[str, Any]:
    return json.loads(prediction_lab_module.OFFICIAL_CALENDAR_DATA_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(schema_version=99), "schema"),
        (lambda payload: payload.update(calendars={}), "payload"),
    ],
)
def test_official_calendar_rejects_invalid_top_level_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    payload = _calendar_payload()
    mutate(payload)
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(prediction_lab_module, "OFFICIAL_CALENDAR_DATA_PATH", path)
    with pytest.raises(PredictionLabError, match=message):
        MarketTradingCalendar.default_for("TWSE")


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "year",
        "dates",
        "source",
        "endpoint",
        "fetched_at",
        "raw_payload_sha256",
    ],
)
def test_official_calendar_rejects_malformed_record_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    payload = _calendar_payload()
    row = next(item for item in payload["calendars"] if item["market"] == "TWSE")
    if field == "schema_version":
        row[field] = 1
    elif field == "year":
        row[field] = "2026"
    elif field == "dates":
        row[field] = "not-a-list"
    elif field == "source":
        row[field] = None
    elif field == "endpoint":
        row[field] = None
    elif field == "fetched_at":
        row[field] = 1
    elif field == "raw_payload_sha256":
        row[field] = None
    else:
        raise AssertionError(field)
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(prediction_lab_module, "OFFICIAL_CALENDAR_DATA_PATH", path)
    with pytest.raises(PredictionLabError, match="provenance|schema"):
        MarketTradingCalendar.default_for("TWSE")


@pytest.mark.parametrize("mode", ["hash", "duplicate", "unsorted", "fetched"])
def test_official_calendar_rejects_integrity_and_provenance_tampering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    payload = _calendar_payload()
    rows = [item for item in payload["calendars"] if item["market"] == "TWSE"]
    if mode == "hash":
        rows[0]["raw_payload_sha256"] = HASH
    elif mode == "duplicate":
        rows[0]["dates"] = list(rows[0]["dates"]) + [rows[0]["dates"][0]]
        rows[0]["normalized_payload_sha256"] = prediction_lab_module._sha(
            {"market": "TWSE", "year": rows[0]["year"], "dates": rows[0]["dates"]}
        )
    elif mode == "unsorted":
        dates = list(rows[0]["dates"])
        dates[0], dates[1] = dates[1], dates[0]
        rows[0]["dates"] = dates
        rows[0]["normalized_payload_sha256"] = prediction_lab_module._sha(
            {"market": "TWSE", "year": rows[0]["year"], "dates": dates}
        )
    else:
        rows[1]["fetched_at"] = "2026-08-28T00:00:00+00:00"
        rows[1]["normalized_payload_sha256"] = prediction_lab_module._sha(
            {"market": "TWSE", "year": rows[1]["year"], "dates": rows[1]["dates"]}
        )
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(prediction_lab_module, "OFFICIAL_CALENDAR_DATA_PATH", path)
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.default_for("TWSE")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"market": "AUTO"}, "known market"),
        ({"dates": []}, "unique"),
        ({"dates": ["2026-08-14", "2026-08-13"]}, "sorted"),
        ({"schema_version": True}, "schema"),
        ({"schema_version": 3}, "provenance"),
        ({"source": ""}, "source"),
        ({"endpoint": 1}, "endpoint"),
        ({"year": True}, "year"),
        ({"calendar_years": (2026, True)}, "years"),
        ({"schema_version": 2}, "unsupported"),
    ],
)
def test_calendar_constructor_rejects_invalid_contracts(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "market": "TWSE",
        "dates": ["2026-08-13", "2026-08-14"],
        "source_hash": HASH,
    }
    values.update(kwargs)
    with pytest.raises(PredictionLabError, match=message):
        MarketTradingCalendar.from_dates(**values)  # type: ignore[arg-type]


def test_calendar_from_dict_rejects_missing_and_bad_provenance() -> None:
    valid = MarketTradingCalendar.default_for("TWSE").to_dict()
    missing = dict(valid)
    missing.pop("source")
    with pytest.raises(PredictionLabError, match="incomplete"):
        MarketTradingCalendar.from_dict(missing)
    bad_years = dict(valid)
    bad_years["calendar_years"] = [True]
    with pytest.raises(PredictionLabError, match="years"):
        MarketTradingCalendar.from_dict(bad_years)
    bad_schema = dict(valid)
    bad_schema["schema_version"] = True
    with pytest.raises(PredictionLabError, match="schema"):
        MarketTradingCalendar.from_dict(bad_schema)


def test_calendar_target_date_rejects_invalid_horizon_and_unknown_start() -> None:
    calendar = MarketTradingCalendar.default_for("TWSE")
    with pytest.raises(PredictionLabError, match="horizon"):
        calendar.target_date("2026-08-13", 0)
    with pytest.raises(PredictionLabError, match="insufficient"):
        calendar.target_date("1900-01-01", 1)


def test_versioned_cost_policy_covers_us_and_rejects_unknown_market() -> None:
    policy = default_prediction_cost_policy("US")
    assert policy.market == "US"
    assert policy.tax_rate == 0.0
    with pytest.raises(PredictionLabError, match="unavailable"):
        default_prediction_cost_policy("CUSTOM")


def test_prediction_evidence_boundary_helpers_fail_closed() -> None:
    with pytest.raises(PredictionLabError, match="ISO-8601"):
        prediction_lab_module._aware_datetime(None, field="created_at")
    with pytest.raises(PredictionLabError, match="invalid"):
        prediction_lab_module._aware_datetime("not-a-date", field="created_at")
    with pytest.raises(PredictionLabError, match="timezone"):
        prediction_lab_module._aware_datetime("2026-08-27T00:00:00", field="created_at")
    with pytest.raises(PredictionLabError, match="required"):
        prediction_lab_module._date(None, field="trading_date")
    with pytest.raises(PredictionLabError, match="invalid"):
        prediction_lab_module._date("2026-99-99", field="trading_date")
    with pytest.raises(PredictionLabError, match="market-qualified"):
        prediction_lab_module._parse_canonical_identity("TWSE")
    with pytest.raises(PredictionLabError, match="canonical"):
        prediction_lab_module._parse_canonical_identity("TWSE:2330.TW")
    with pytest.raises(PredictionLabError, match="finite"):
        prediction_lab_module._finite_number(True, field="price")
    with pytest.raises(PredictionLabError, match="finite"):
        prediction_lab_module._finite_number(float("nan"), field="price")
    assert len(prediction_lab_module._hashes((prediction_lab_module._sha(b"bytes"),))[0]) == 64
    with pytest.raises(PredictionLabError, match="reference"):
        prediction_lab_module._normalize_reference(
            {"identity": "not-qualified"},
            identity="TWSE:2330",
            effective_date="2026-08-27",
            field="price",
        )
    with pytest.raises(PredictionLabError, match="mismatch"):
        prediction_lab_module._normalize_reference(
            {"identity": "TWSE:2331", "payload_hash": HASH},
            identity="TWSE:2330",
            effective_date="2026-08-27",
            field="price",
        )
    with pytest.raises(PredictionLabError, match="date"):
        prediction_lab_module._normalize_reference(
            {"identity": "TWSE:2330", "payload_hash": HASH, "effective_date": "2026-08-26"},
            identity="TWSE:2330",
            effective_date="2026-08-27",
            field="price",
        )


def test_benchmark_evidence_rejects_incomplete_or_inconsistent_provenance() -> None:
    base: dict[str, Any] = {
        "identity": "TWSE:TAIEX",
        "return_value": 0.1,
        "effective_trading_date": "2026-08-20",
        "provider": "official-replay",
        "payload_hash": HASH,
        "start_trading_date": "2026-08-13",
        "end_trading_date": "2026-08-20",
        "start_value": 100.0,
        "end_value": 110.0,
    }
    evidence = BenchmarkEvidence(**base)
    assert evidence.to_reference()["payload_hashes"] == [HASH]
    for mutation in (
        {"start_value": None},
        {"end_trading_date": "2026-08-19"},
        {"return_value": 0.2},
        {"price_field": "open"},
        {"adjusted_raw_policy": "mixed"},
    ):
        with pytest.raises(PredictionLabError):
            BenchmarkEvidence(**{**base, **mutation})


def test_price_evidence_and_runtime_provider_fail_closed_branches() -> None:
    with pytest.raises(PredictionLabError, match="corporate-action"):
        RuntimeCachedOutcomeProvider([], price_policy="mixed")
    with pytest.raises(PredictionLabError, match="price provider"):
        PriceEvidence(
            identity="TWSE:2330",
            value=100.0,
            effective_trading_date="2026-08-20",
            provider="",
            payload_hash=HASH,
        )
    with pytest.raises(PredictionLabError, match="price field"):
        PriceEvidence(
            identity="TWSE:2330",
            value=100.0,
            effective_trading_date="2026-08-20",
            provider="fixture",
            payload_hash=HASH,
            price_field="open",
        )
    rows = [
        _row("2330", "TWSE", "2026-08-20", 100.0),
        {
            **_row("2330", "TWSE", "2026-08-21", 101.0),
            "corporate_action_required": True,
        },
        _row("TAIEX", "TWSE", "2026-08-20", 200.0),
    ]
    provider = RuntimeCachedOutcomeProvider(rows)
    assert provider.price("TWSE:missing", "2026-08-20") is None
    assert provider.price("TWSE:2330", "2026-08-21") is None
    assert provider.benchmark("TPEX:OTC", "2026-08-20") is None
    assert provider.benchmark("TWSE:TAIEX", "2026-08-19") is None
    assert provider.benchmark("TWSE:TAIEX", "2026-08-20", "2026-08-19") is None
    adjusted = RuntimeCachedOutcomeProvider(rows, price_policy="adjusted")
    assert adjusted.price("TWSE:2330", "2026-08-20") is None


def test_calendar_schema_one_roundtrip_and_cost_policy_contract() -> None:
    calendar = MarketTradingCalendar.from_dates(
        market="TWSE", dates=("2026-08-20", "2026-08-21"), source_hash=HASH
    )
    assert MarketTradingCalendar.from_dict(calendar.to_dict()) == calendar
    with pytest.raises(PredictionLabError, match="known market"):
        MarketTradingCalendar.default_for("CUSTOM")
    with pytest.raises(PredictionLabError, match="known market"):
        PredictionCostPolicy("CUSTOM", "v1", 0.0, 0.0, 0.0)
    with pytest.raises(PredictionLabError, match="version"):
        PredictionCostPolicy("TWSE", "", 0.0, 0.0, 0.0)
    with pytest.raises(PredictionLabError, match="commission"):
        PredictionCostPolicy("TWSE", "v1", -0.1, 0.0, 0.0)


def test_prediction_record_from_dict_rejects_future_and_invalid_fields() -> None:
    record = prediction_lab_module.PredictionRecord.create(
        created_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        trading_date="2026-08-20",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=1.0,
        source_hashes=(HASH,),
    )
    for mutation in (
        {"created_at": "2099-01-01T00:00:00+00:00"},
        {"bucket": "unknown"},
        {"rank": True},
        {"universe_size": 2},
        {"input_hashes": ["bad"]},
    ):
        payload = {**record.to_dict(), **mutation}
        with pytest.raises(PredictionLabError):
            prediction_lab_module.PredictionRecord.from_dict(payload)
