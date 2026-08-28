"""Sprint 33.1.1 production-path RED contracts.

These tests intentionally exercise the application boundaries rather than
constructing evaluator output by hand.  They are added before the fixes so a
regression cannot be hidden behind an evidence-only fixture.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import stock_tool.application.prediction_lab as prediction_lab

from stock_tool.application.prediction_lab import (
    BenchmarkRefreshService,
    MarketTradingCalendar,
    PredictionLabError,
    PredictionCostPolicy,
    PredictionLabStore,
    PredictionOutcomeEvaluator,
    PredictionRecord,
)
from stock_tool.data.storage import PersistedPriceProvenance, SQLitePriceStorage
from stock_tool.data.contracts import DataSourceType
from stock_tool.data.corporate_actions import CorporateAction, CorporateActionType
from stock_tool.domain.models import Symbol

RAW_TWSE_2026 = "7FEFE785EA7155A5004A2EB74486AD865EA5C4B5F02EE0CFFBBDACB1CA2EA390".lower()
RAW_TPEX_2026 = "01C25DD3052C9E108007ED2AF0FC06173188F1C56676BE49AE8B556ACF35CD9F".lower()
RAW_NYSE_2026 = "F90B6D08C4F3E82AF53E6139837058ABB7A1E7770EA6C716B1AB5DBCB413139F".lower()

VALID_HASH = hashlib.sha256(b"valid-provenance").hexdigest()


def _official_calendar_payload() -> dict[str, object]:
    """Return a fully serialized official calendar for tamper-contract tests."""

    return MarketTradingCalendar.default_for("TWSE").to_dict()


def _benchmark_fetcher(market: str, provider_symbol: str):
    values = {
        "TWSE": ("TAIEX", 20_000.0, 20_400.0),
        "TPEX": ("OTC", 15_000.0, 15_150.0),
        "US": ("SPX", 5_000.0, 5_050.0),
    }
    symbol, first, last = values[market]
    return {
        "market": market,
        "symbol": symbol,
        "provider": "official-benchmark-replay",
        "provider_symbol": provider_symbol,
        "source_type": "online",
        "last_data_date": "2026-08-20",
        "fetched_at": "2026-08-21T00:00:00+00:00",
        "records": [
            {
                "date": "2026-08-13",
                "open": first,
                "high": first,
                "low": first,
                "close": first,
                "volume": 1.0,
                "adjusted_close": None,
            },
            {
                "date": "2026-08-20",
                "open": last,
                "high": last,
                "low": last,
                "close": last,
                "volume": 1.0,
                "adjusted_close": None,
            },
        ],
    }


def test_official_calendar_uses_raw_source_hash_and_rejects_unproven_years() -> None:
    twse = MarketTradingCalendar.default_for("TWSE")
    tpex = MarketTradingCalendar.default_for("TPEX")
    us = MarketTradingCalendar.default_for("US")
    assert twse.raw_payload_sha256 == RAW_TWSE_2026
    assert tpex.raw_payload_sha256 == RAW_TPEX_2026
    assert us.raw_payload_sha256 == RAW_NYSE_2026
    assert twse.normalized_payload_sha256 != twse.raw_payload_sha256
    assert "2026-12-31" in twse.dates
    with pytest.raises(PredictionLabError, match="unavailable"):
        MarketTradingCalendar.default_for("TWSE", year=2027)


def test_benchmark_refresh_persists_all_market_qualified_benchmarks_and_reloads(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stock_data.sqlite"
    service = BenchmarkRefreshService(database, fetcher=_benchmark_fetcher)
    result = service.refresh()
    assert result.status == "fresh"
    assert set(result.identities) == {"TWSE:TAIEX", "TPEX:OTC", "US:SPX"}
    reloaded = service.load_provider()
    assert reloaded is not None
    for identity in result.identities:
        evidence = reloaded.benchmark(identity, "2026-08-20", "2026-08-13")
        assert evidence is not None
        assert evidence.provider == "official-benchmark-replay"
        assert len(evidence.payload_hashes) == 2


def test_benchmark_index_symbols_keep_provider_identity_and_cache_hash(tmp_path: Path) -> None:
    from stock_tool.data.auto_fetch import normalize_yfinance_symbol

    assert normalize_yfinance_symbol("^TWII", market="TWSE") == "^TWII"
    assert normalize_yfinance_symbol("^TWO", market="TPEX") == "^TWO"
    assert normalize_yfinance_symbol("^GSPC", market="US") == "^GSPC"

    cache_path = tmp_path / "benchmark.csv"
    cache_bytes = b"date,close\n2026-08-13,100\n2026-08-20,101\n"
    cache_path.write_bytes(cache_bytes)

    class _Frame:
        def to_dict(self, *, orient: str) -> list[dict[str, object]]:
            assert orient == "records"
            return [
                {"date": "2026-08-13", "close": 100.0},
                {"date": "2026-08-20", "close": 101.0},
            ]

    raw = SimpleNamespace(
        metadata=SimpleNamespace(
            provider="yfinance",
            provider_symbol="^TWII",
            source_type=DataSourceType.CACHE,
            last_data_date="2026-08-20",
            fetched_at="2026-08-21T00:00:00+00:00",
            cache_path=str(cache_path),
        ),
        data=_Frame(),
        succeeded=True,
    )
    metadata, records = BenchmarkRefreshService._normalize_fetch("TWSE", "^TWII", raw)
    assert metadata["provider"] == "yfinance"
    assert metadata["provider"] != "official-benchmark"
    assert metadata["source_type"] == "cache"
    assert metadata["payload_sha256"] == hashlib.sha256(cache_bytes).hexdigest()
    assert len(records) == 2


def test_benchmark_mapping_reads_nested_payload_hash_and_enum_value() -> None:
    """Installed-like metadata must preserve the enum scalar and payload identity."""

    raw = {
        "metadata": {
            "market": "TWSE",
            "symbol": "TAIEX",
            "provider": "yfinance",
            "provider_symbol": "^TWII",
            "source_type": DataSourceType.CACHE,
            "last_data_date": "2026-08-20",
            "fetched_at": "2026-08-21T00:00:00+00:00",
            "payload_hash": VALID_HASH,
        },
        "records": [
            {"date": "2026-08-13", "close": 100.0},
            {"date": "2026-08-20", "close": 101.0},
        ],
    }
    metadata, records = BenchmarkRefreshService._normalize_fetch("TWSE", "^TWII", raw)
    assert metadata["source_type"] == "cache"
    assert metadata["payload_sha256"] == VALID_HASH
    assert metadata["provider_symbol"] == "^TWII"
    assert len(records) == 2


def test_official_index_parser_accepts_naive_injected_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An injected naive test clock must not invalidate a verified response."""

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                '{"fields":["日期","開盤指數","最高指數","最低指數","收盤指數"],'
                '"data":[["115/08/20","20000","20100","19900","20050"]]}'
            ).encode("utf-8")

    monkeypatch.setattr(
        prediction_lab.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response()
    )
    service = BenchmarkRefreshService(Path("unused.sqlite"), now_fn=lambda: datetime(2026, 8, 21))
    payload = service._fetch_official_index("TWSE", "^TWII")
    assert payload["fetched_at"] == "2026-08-21T00:00:00+00:00"
    assert payload["records"][0]["date"] == "2026-08-20"


def test_benchmark_refresh_is_all_or_nothing_when_one_market_fails(tmp_path: Path) -> None:
    database = tmp_path / "stock_data.sqlite"
    initial = BenchmarkRefreshService(database, fetcher=_benchmark_fetcher)
    assert initial.refresh(markets=("TWSE", "TPEX", "US")).status == "fresh"
    sidecar = database.with_name("stock_data.price_identity.json")
    before = sidecar.read_bytes()

    def partially_broken(market: str, provider_symbol: str):
        if market == "TPEX":
            raise RuntimeError("provider unavailable")
        return _benchmark_fetcher(market, provider_symbol)

    result = BenchmarkRefreshService(database, fetcher=partially_broken).refresh()
    assert result.status == "partial"
    assert sidecar.read_bytes() == before
    assert set(
        BenchmarkRefreshService(database, fetcher=_benchmark_fetcher).load_provider()._by_identity
    ) == {
        "TWSE:TAIEX",
        "TPEX:OTC",
        "US:SPX",
    }  # type: ignore[union-attr]


def test_benchmark_refresh_requires_verified_payload_and_does_not_write_partial(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stock_data.sqlite"

    def broken_fetcher(_market: str, _provider_symbol: str):
        return {"records": [], "symbol": "TAIEX"}

    result = BenchmarkRefreshService(database, fetcher=broken_fetcher).refresh(markets=("TWSE",))
    assert result.status == "unavailable"
    assert not database.with_name("stock_data.price_identity.json").exists()


def test_installed_like_refresh_reload_then_evaluate_uses_new_benchmark_provider(
    tmp_path: Path,
) -> None:
    """A production-shaped run must refresh, persist, reload and then settle."""

    database = tmp_path / "stock_data.sqlite"
    service = BenchmarkRefreshService(database, fetcher=_benchmark_fetcher)
    assert service.load_provider() is None
    refreshed = service.refresh(markets=("TWSE",))
    assert refreshed.status == "fresh"

    source_hash = hashlib.sha256(b"security-payload").hexdigest()
    storage = SQLitePriceStorage(database)
    storage.save_market_qualified_price_data(
        [
            {
                "date": "2026-08-13",
                "symbol": "2330",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
                "adjusted_close": None,
                "payload_sha256": source_hash,
                "provider": "official-security-replay",
                "corporate_action_coverage": {
                    "coverage_start": "2026-08-01",
                    "coverage_end": "2026-08-31",
                    "source": "official-corporate-action-coverage",
                    "payload_hash": source_hash,
                    "policy_version": "corporate-action-coverage-v1",
                    "no_action_confirmed": True,
                },
            },
            {
                "date": "2026-08-20",
                "symbol": "2330",
                "open": 110.0,
                "high": 110.0,
                "low": 110.0,
                "close": 110.0,
                "volume": 1.0,
                "adjusted_close": None,
                "payload_sha256": source_hash,
                "provider": "official-security-replay",
                "corporate_action_coverage": {
                    "coverage_start": "2026-08-01",
                    "coverage_end": "2026-08-31",
                    "source": "official-corporate-action-coverage",
                    "payload_hash": source_hash,
                    "policy_version": "corporate-action-coverage-v1",
                    "no_action_confirmed": True,
                },
            },
        ],
        provenance=PersistedPriceProvenance(
            symbol=Symbol.parse("2330", market="TWSE"),
            provider="official-security-replay",
            provider_symbol="2330.TW",
            source_type="online",
            last_data_date="2026-08-20",
            checked_at="2026-08-21T00:00:00+00:00",
            fetched_at="2026-08-21T00:00:00+00:00",
            payload_sha256=source_hash,
        ),
    )
    provider = service.load_provider()
    assert provider is not None
    store = PredictionLabStore(tmp_path / "prediction-lab")
    prediction = PredictionRecord.create(
        created_at=datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
        trading_date="2026-08-13",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=1.0,
        source_cutoff="2026-08-13",
        input_hashes=(source_hash,),
        source_hashes=(source_hash,),
        benchmark_identity="TWSE:TAIEX",
        entry_price_reference={
            "identity": "TWSE:2330",
            "value": 100.0,
            "effective_trading_date": "2026-08-13",
            "provider": "official-security-replay",
            "payload_hash": source_hash,
            "price_field": "close",
            "adjusted_raw_policy": "raw",
        },
    )
    store.save_prediction(prediction)
    result = PredictionOutcomeEvaluator(
        store,
        provider,
        now_fn=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")
    assert result.status == "success"
    assert result.evaluated_count == 1
    assert result.outcomes[0].status == "evaluated"
    assert result.outcomes[0].benchmark_identity["identity"] == "TWSE:TAIEX"


def test_cost_policy_exposes_round_trip_components_for_long_and_short() -> None:
    policy = PredictionCostPolicy(
        market="TWSE",
        version="cost-v2",
        commission_rate=0.001,
        tax_rate=0.003,
        slippage_rate=0.0005,
    )
    components = policy.components(position_side="long")
    assert set(components) >= {
        "buy_commission_rate",
        "sell_commission_rate",
        "buy_slippage_rate",
        "sell_slippage_rate",
        "sell_tax_rate",
        "total_rate",
    }
    assert policy.components(position_side="short")["total_rate"] == pytest.approx(
        components["total_rate"]
    )


def test_persisted_corporate_action_evidence_survives_restart(tmp_path: Path) -> None:
    storage = SQLitePriceStorage(tmp_path / "stock_data.sqlite")
    symbol = Symbol.parse("2330", market="TWSE")
    evidence_hash = hashlib.sha256(b"corporate-action").hexdigest()
    storage.save_market_qualified_price_data(
        [
            {
                "date": "2026-08-13",
                "symbol": "2330",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
                "adjusted_close": None,
                "corporate_action_required": True,
                "corporate_action_evidence": {
                    "source": "official-action-feed",
                    "effective_date": "2026-08-14",
                    "payload_hash": evidence_hash,
                    "policy_version": "corporate-action-v1",
                },
            }
        ],
        provenance=PersistedPriceProvenance(
            symbol=symbol,
            provider="official",
            provider_symbol="2330.TW",
            source_type="online",
            last_data_date="2026-08-13",
            checked_at="2026-08-14T00:00:00+00:00",
        ),
    )
    context = storage.load_market_qualified_price_context()
    assert context.warnings == ()
    assert context.records[0]["corporate_action_required"] is True
    assert context.records[0]["corporate_action_evidence"]["payload_hash"] == evidence_hash
    # Missing publication/availability evidence remains retryable after a
    # restart; the row must not be interpreted as an implicit clear.
    reloaded = prediction_lab.build_runtime_cached_outcome_provider(storage.database_path)
    assert reloaded is not None
    assert reloaded.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")[0] == (
        "insufficient"
    )


def test_complete_corporate_action_evidence_survives_restart_as_retryable_raw(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stock_data.sqlite"
    symbol = Symbol.parse("2330", market="TWSE")
    evidence_hash = hashlib.sha256(b"corporate-action-complete").hexdigest()
    storage = SQLitePriceStorage(database)
    storage.save_market_qualified_price_data(
        [
            {
                "date": "2026-08-13",
                "symbol": "2330",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
                "adjusted_close": None,
                "corporate_action_required": True,
                "corporate_action_evidence": {
                    "source": "official-action-feed",
                    "effective_date": "2026-08-14",
                    "available_date": "2026-08-15",
                    "payload_hash": evidence_hash,
                    "policy_version": "corporate-action-v1",
                    "adjusted_raw_policy": "raw",
                    "event_id": "action-1",
                    "terms": "split:2",
                },
            },
            {
                "date": "2026-08-20",
                "symbol": "2330",
                "open": 110.0,
                "high": 110.0,
                "low": 110.0,
                "close": 110.0,
                "volume": 1.0,
                "adjusted_close": None,
                "corporate_action_required": True,
                "corporate_action_evidence": {
                    "source": "official-action-feed",
                    "effective_date": "2026-08-14",
                    "available_date": "2026-08-15",
                    "payload_hash": evidence_hash,
                    "policy_version": "corporate-action-v1",
                    "adjusted_raw_policy": "raw",
                    "event_id": "action-1",
                    "terms": "split:2",
                },
            },
        ],
        provenance=PersistedPriceProvenance(
            symbol=symbol,
            provider="official",
            provider_symbol="2330.TW",
            source_type="online",
            last_data_date="2026-08-20",
            checked_at="2026-08-21T00:00:00+00:00",
        ),
    )
    reloaded = prediction_lab.build_runtime_cached_outcome_provider(database)
    assert reloaded is not None
    status, reason = reloaded.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")
    assert status == "insufficient"
    assert reason and "raw" in reason


def test_corporate_action_requires_explicit_no_action_coverage(tmp_path: Path) -> None:
    rows = [
        {
            "market": "TWSE",
            "symbol": "2330",
            "date": "2026-08-13",
            "close": 100.0,
            "provider": "official",
        }
    ]
    provider = prediction_lab.RuntimeCachedOutcomeProvider(rows)
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-13")[0] == (
        "insufficient"
    )
    provider_with_coverage = prediction_lab.RuntimeCachedOutcomeProvider(
        rows,
        corporate_actions=(
            {
                "identity": "TWSE:2330",
                "coverage_start": "2026-08-01",
                "coverage_end": "2026-08-31",
                "source": "official-corporate-action-coverage",
                "payload_hash": VALID_HASH,
                "policy_version": "corporate-action-coverage-v1",
                "no_action_confirmed": True,
            },
        ),
    )
    assert provider_with_coverage.corporate_action_status(
        "TWSE:2330", "2026-08-13", "2026-08-13"
    ) == ("clear", None)


def test_persisted_no_action_coverage_survives_reload(tmp_path: Path) -> None:
    database = tmp_path / "stock_data.sqlite"
    symbol = Symbol.parse("2330", market="TWSE")
    prediction_lab.CorporateActionImportService().import_no_action_coverage(
        database,
        [
            {
                "date": "2026-08-13",
                "symbol": "2330",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
                "adjusted_close": None,
                "corporate_action_coverage": {
                    "coverage_start": "2026-08-01",
                    "coverage_end": "2026-08-31",
                    "source": "official-corporate-action-coverage",
                    "payload_hash": VALID_HASH,
                    "policy_version": "corporate-action-coverage-v1",
                    "no_action_confirmed": True,
                },
            }
        ],
        provenance=PersistedPriceProvenance(
            symbol=symbol,
            provider="official",
            provider_symbol="2330.TW",
            source_type="online",
            last_data_date="2026-08-13",
            checked_at="2026-08-14T00:00:00+00:00",
        ),
    )
    reloaded = prediction_lab.build_runtime_cached_outcome_provider(database)
    assert reloaded is not None
    assert reloaded.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-13") == (
        "clear",
        None,
    )


def test_production_builder_loads_contract_corporate_actions_from_runtime_sidecar(
    tmp_path: Path,
) -> None:
    """The shared composition root must load the existing CorporateAction contract."""

    database = tmp_path / "stock_data.sqlite"
    symbol = Symbol.parse("2330", market="TWSE")
    SQLitePriceStorage(database).save_market_qualified_price_data(
        [
            {
                "date": "2026-08-13",
                "symbol": "2330",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
                "adjusted_close": None,
            },
            {
                "date": "2026-08-08",
                "symbol": "2330",
                "open": 90.0,
                "high": 90.0,
                "low": 90.0,
                "close": 90.0,
                "volume": 1.0,
                "adjusted_close": None,
            },
        ],
        provenance=PersistedPriceProvenance(
            symbol=symbol,
            provider="official",
            provider_symbol="2330.TW",
            source_type="online",
            last_data_date="2026-08-13",
            checked_at="2026-08-14T00:00:00+00:00",
        ),
    )
    action_source = tmp_path / "official-actions.csv"
    action_source.write_bytes(
        (
            "symbol,market,action_type,effective_date,available_date,payable_date,"
            "split_ratio,cash_per_share,currency,tax_rate,source,confidence,completeness,"
            "notes,adjusted_raw_policy\n"
            "2330,TWSE,split,2026-08-10,2026-08-11,,2.0,,,0.0,official-actions,"
            "complete,complete,,raw\n"
        ).encode("utf-8")
    )
    action_file = database.with_name("corporate_actions.csv")
    prediction_lab.CorporateActionImportService().import_source(action_source, action_file)

    provider = prediction_lab.build_runtime_cached_outcome_provider(database)

    assert provider is not None
    status, reason = provider.corporate_action_status("TWSE:2330", "2026-08-08", "2026-08-13")
    assert status == "insufficient"
    assert reason and "raw" in reason
    # The CSV loader contributes source-backed provenance to the contract;
    # this is what makes the action replayable after a process restart.
    action = provider._corporate_actions["TWSE:2330"][0]
    assert action["source"] == "official-actions"
    assert len(action["payload_hash"]) == 64
    assert action["policy_version"] == "corporate-action-contract-v1"


def test_production_builder_rejects_corrupt_corporate_action_sidecar(tmp_path: Path) -> None:
    database = tmp_path / "stock_data.sqlite"
    SQLitePriceStorage(database).save_market_qualified_price_data(
        [
            {
                "date": "2026-08-13",
                "symbol": "TAIEX",
                "open": 20_000.0,
                "high": 20_000.0,
                "low": 20_000.0,
                "close": 20_000.0,
                "volume": 1.0,
                "adjusted_close": None,
            }
        ],
        provenance=PersistedPriceProvenance(
            symbol=Symbol.parse("TAIEX", market="TWSE"),
            provider="official",
            provider_symbol="^TWII",
            source_type="online",
            last_data_date="2026-08-13",
            checked_at="2026-08-14T00:00:00+00:00",
        ),
    )
    database.with_name("corporate_actions.csv").write_text(
        "not,a,valid,contract\n", encoding="utf-8"
    )

    assert prediction_lab.build_runtime_cached_outcome_provider(database) is None


def test_broker_cashflow_costs_are_recomputable_for_long_and_short() -> None:
    policy = PredictionCostPolicy(
        market="TWSE",
        version="cost-v2",
        commission_rate=0.001,
        tax_rate=0.003,
        slippage_rate=0.0005,
    )
    long_cost = prediction_lab._round_trip_cost(
        100.0, 110.0, policy.components(position_side="long"), position_side="long"
    )
    assert long_cost["buy_execution_price"] == pytest.approx(100.05)
    assert long_cost["sell_execution_price"] == pytest.approx(109.945)
    assert long_cost["buy_slippage_amount"] == pytest.approx(0.05)
    assert long_cost["sell_slippage_amount"] == pytest.approx(0.055)
    assert long_cost["buy_commission_amount"] == pytest.approx(0.10005)
    assert long_cost["sell_commission_amount"] == pytest.approx(0.109945)
    assert long_cost["sell_tax_amount"] == pytest.approx(0.329835)
    assert long_cost["net_return"] < long_cost["gross_return"]
    short_cost = prediction_lab._round_trip_cost(
        100.0, 90.0, policy.components(position_side="short"), position_side="short"
    )
    assert short_cost["buy_slippage_amount"] == pytest.approx(0.045)
    assert short_cost["sell_slippage_amount"] == pytest.approx(0.05)
    assert short_cost["gross_return"] == pytest.approx(100.0 / 90.0 - 1.0)
    assert short_cost["net_return"] < short_cost["gross_return"]


def test_reloaded_corporate_action_requirement_blocks_evaluation_without_evidence(
    tmp_path: Path,
) -> None:
    """The evaluator must honour persisted action flags after a restart."""

    database = tmp_path / "stock_data.sqlite"
    benchmark = BenchmarkRefreshService(database, fetcher=_benchmark_fetcher)
    assert benchmark.refresh(markets=("TWSE",)).status == "fresh"
    security_hash = hashlib.sha256(b"security-with-action").hexdigest()
    SQLitePriceStorage(database).save_market_qualified_price_data(
        [
            {
                "date": day,
                "symbol": "2330",
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "volume": 1.0,
                "adjusted_close": None,
                "payload_sha256": security_hash,
                "provider": "official-security-replay",
                "corporate_action_required": True,
            }
            for day, value in (("2026-08-13", 100.0), ("2026-08-20", 110.0))
        ],
        provenance=PersistedPriceProvenance(
            symbol=Symbol.parse("2330", market="TWSE"),
            provider="official-security-replay",
            provider_symbol="2330.TW",
            source_type="online",
            last_data_date="2026-08-20",
            checked_at="2026-08-21T00:00:00+00:00",
            fetched_at="2026-08-21T00:00:00+00:00",
            payload_sha256=security_hash,
        ),
    )
    provider = benchmark.load_provider()
    assert provider is not None
    store = PredictionLabStore(tmp_path / "prediction-lab").ensure()
    prediction = PredictionRecord.create(
        created_at=datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
        trading_date="2026-08-13",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=1.0,
        input_hashes=(security_hash,),
        source_hashes=(security_hash,),
        benchmark_identity="TWSE:TAIEX",
        entry_price_reference={
            "identity": "TWSE:2330",
            "value": 100.0,
            "effective_trading_date": "2026-08-13",
            "provider": "official-security-replay",
            "payload_hash": security_hash,
            "price_field": "close",
            "adjusted_raw_policy": "raw",
        },
    )
    store.save_prediction(prediction)
    result = PredictionOutcomeEvaluator(
        store,
        provider,
        now_fn=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")
    assert result.status == "partial"
    assert result.eligible_count == 1
    assert result.evaluated_count == 0
    assert result.outcomes[0].missing_reason


def test_prediction_lab_boundary_normalizers_reject_unsafe_inputs() -> None:
    """Exercise the shared provenance parsers used by every production path."""

    assert prediction_lab._safe_reason("credential=/private/token") == "provider error"
    assert prediction_lab._safe_reason("C:/private/file") == "provider error"
    assert prediction_lab._safe_reason("") == "provider error"
    assert prediction_lab._safe_reason("temporary provider outage") == "temporary provider outage"

    with pytest.raises(PredictionLabError):
        prediction_lab._aware_datetime(None, field="when")
    with pytest.raises(PredictionLabError):
        prediction_lab._aware_datetime("not-a-date", field="when")
    with pytest.raises(PredictionLabError):
        prediction_lab._aware_datetime("2026-08-20T00:00:00", field="when")
    assert prediction_lab._aware_datetime("2026-08-20T00:00:00Z", field="when").tzinfo

    with pytest.raises(PredictionLabError):
        prediction_lab._date(None, field="day")
    with pytest.raises(PredictionLabError):
        prediction_lab._date("2026-99-99", field="day")
    assert prediction_lab._date("2026-08-20", field="day") == "2026-08-20"

    with pytest.raises(PredictionLabError):
        prediction_lab._market_symbol("AUTO", "2330")
    with pytest.raises(PredictionLabError):
        prediction_lab._market_symbol("CUSTOM", "2330")
    with pytest.raises(PredictionLabError):
        prediction_lab._parse_canonical_identity("TWSE")
    with pytest.raises(PredictionLabError):
        prediction_lab._parse_canonical_identity("TWSE:")
    with pytest.raises(PredictionLabError):
        prediction_lab._parse_canonical_identity("TWSE:2330:extra")
    with pytest.raises(PredictionLabError):
        prediction_lab._finite_number(True, field="value")
    with pytest.raises(PredictionLabError):
        prediction_lab._finite_number(float("inf"), field="value")
    assert prediction_lab._finite_number(1.5, field="value", minimum=1.0) == 1.5

    assert (
        prediction_lab._normalize_reference(
            None, identity="TWSE:2330", effective_date="2026-08-13", field="entry"
        )
        is None
    )
    with pytest.raises(PredictionLabError):
        prediction_lab._normalize_reference(
            [], identity="TWSE:2330", effective_date="2026-08-13", field="entry"
        )
    with pytest.raises(PredictionLabError):
        prediction_lab._normalize_reference(
            {"identity": "2330"},
            identity="TWSE:2330",
            effective_date="2026-08-13",
            field="entry",
        )
    with pytest.raises(PredictionLabError):
        prediction_lab._normalize_reference(
            {
                "identity": "TWSE:2330",
                "effective_trading_date": "2026-08-14",
                "payload_hash": VALID_HASH,
            },
            identity="TWSE:2330",
            effective_date="2026-08-13",
            field="entry",
        )
    reference = prediction_lab._normalize_reference(
        {
            "identity": "TWSE:2330",
            "effective_trading_date": "2026-08-13",
            "value": 100.0,
            "payload_hash": VALID_HASH,
            "provider": "fixture-provider",
        },
        identity="TWSE:2330",
        effective_date="2026-08-13",
        field="entry",
        include_value=True,
    )
    assert reference is not None and reference["value"] == 100.0


def test_price_and_benchmark_evidence_provenance_contract() -> None:
    price = prediction_lab.PriceEvidence(
        identity="TWSE:2330",
        value=100.0,
        effective_trading_date="2026-08-13",
        provider="official",
        payload_hash=VALID_HASH,
    )
    assert price.to_reference()["identity"] == "TWSE:2330"
    with pytest.raises(PredictionLabError):
        prediction_lab.PriceEvidence(
            identity="2330",
            value=100.0,
            effective_trading_date="2026-08-13",
            provider="official",
            payload_hash=VALID_HASH,
        )
    with pytest.raises(PredictionLabError):
        prediction_lab.PriceEvidence(
            identity="TWSE:2330",
            value=0.0,
            effective_trading_date="2026-08-13",
            provider="official",
            payload_hash=VALID_HASH,
        )

    benchmark = prediction_lab.BenchmarkEvidence(
        identity="TWSE:TAIEX",
        return_value=0.02,
        effective_trading_date="2026-08-20",
        provider="official-fred-like",
        payload_hash=VALID_HASH,
        payload_hashes=(VALID_HASH, VALID_HASH),
        start_trading_date="2026-08-13",
        end_trading_date="2026-08-20",
        start_value=100.0,
        end_value=102.0,
        provider_symbol="^TWII",
        source_type="ONLINE",
        checked_at="2026-08-21T00:00:00+00:00",
        fetched_at="2026-08-21T00:00:00Z",
    )
    reference = benchmark.to_reference()
    assert reference["provider_symbol"] == "^TWII"
    assert reference["source_type"] == "online"
    assert reference["fetched_at"].endswith("+00:00")
    with pytest.raises(PredictionLabError):
        prediction_lab.BenchmarkEvidence(
            identity="TWSE:TAIEX",
            return_value=0.02,
            effective_trading_date="2026-08-20",
            provider="official",
            payload_hash=VALID_HASH,
            provider_symbol="^GSPC",
        )
    with pytest.raises(PredictionLabError):
        prediction_lab.BenchmarkEvidence(
            identity="TWSE:TAIEX",
            return_value=0.02,
            effective_trading_date="2026-08-20",
            provider="official",
            payload_hash=VALID_HASH,
            source_type="unknown",
        )
    with pytest.raises(PredictionLabError):
        prediction_lab.BenchmarkEvidence(
            identity="TWSE:TAIEX",
            return_value=0.02,
            effective_trading_date="2026-08-20",
            provider="official",
            payload_hash=VALID_HASH,
            start_trading_date="2026-08-13",
            end_trading_date="2026-08-20",
            start_value=100.0,
            end_value=103.0,
        )


def test_official_calendar_roundtrip_and_tamper_matrix() -> None:
    legacy = MarketTradingCalendar.from_dates(
        market="TWSE",
        dates=("2026-08-13", "2026-08-14"),
        source_hash=VALID_HASH,
        schema_version=1,
    )
    assert MarketTradingCalendar.from_dict(legacy.to_dict()).dates == legacy.dates
    for payload in (
        {"schema_version": 2},
        {"schema_version": True},
        {"schema_version": 1, "market": "TWSE", "dates": [], "source_hash": VALID_HASH},
    ):
        with pytest.raises(PredictionLabError):
            MarketTradingCalendar.from_dict(payload)

    official = _official_calendar_payload()
    for field, replacement in (
        ("raw_payload_hashes", []),
        ("raw_payload_sha256", VALID_HASH),
        ("normalized_payload_sha256", VALID_HASH),
        ("source_hash", VALID_HASH),
        ("calendar_years", [2026, 2025]),
        ("year", 2025),
    ):
        tampered = dict(official)
        tampered[field] = replacement
        with pytest.raises(PredictionLabError):
            MarketTradingCalendar.from_dict(tampered)
    extra = dict(official)
    extra["unexpected"] = True
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.from_dict(extra)


def test_cost_and_corporate_action_contract_matrix() -> None:
    for market in ("TWSE", "TPEX", "US"):
        assert prediction_lab.default_prediction_cost_policy(market).total_rate > 0
    with pytest.raises(PredictionLabError):
        prediction_lab.default_prediction_cost_policy("CUSTOM")
    policy = PredictionCostPolicy(
        market="US",
        version="v1",
        commission_rate=0.001,
        tax_rate=0.0,
        slippage_rate=0.0005,
        formula_version="round-trip-v2",
    )
    with pytest.raises(PredictionLabError):
        policy.components(position_side="sideways")
    assert prediction_lab._normalize_cost_components(None) is None
    with pytest.raises(PredictionLabError):
        prediction_lab._normalize_cost_components([])
    with pytest.raises(PredictionLabError):
        prediction_lab._normalize_cost_components({"unexpected": 1.0})
    with pytest.raises(PredictionLabError):
        prediction_lab._normalize_cost_components({"formula_version": ""})
    with pytest.raises(PredictionLabError):
        prediction_lab._normalize_cost_components(
            {
                "buy_commission_rate": 0.1,
                "sell_commission_rate": 0.1,
                "buy_slippage_rate": 0.1,
                "sell_slippage_rate": 0.1,
                "sell_tax_rate": 0.1,
                "total_rate": 0.0,
            }
        )
    assert prediction_lab._normalize_cost_components(policy.components())

    assert prediction_lab._action_payload_hash({"payload_sha256": VALID_HASH}) == VALID_HASH
    assert prediction_lab._action_payload_hash({"payload_hash": "invalid"}) is None
    assert not prediction_lab._row_corporate_action_event(None, row_date="2026-08-13")["valid"]
    row_event = prediction_lab._row_corporate_action_event(
        {
            "source": "official-action",
            "effective_date": "2026-08-14",
            "available_date": "2026-08-15",
            "payload_hash": VALID_HASH,
            "policy_version": "action-v1",
        },
        row_date="2026-08-13",
    )
    assert row_event["valid"] is True
    assert (
        prediction_lab._row_corporate_action_event(
            {"source": "", "payload_hash": VALID_HASH}, row_date="bad"
        )["valid"]
        is False
    )

    valid_action = SimpleNamespace(
        symbol=Symbol.parse("2330", market="TWSE"),
        source="official-action",
        effective_date="2026-08-14",
        available_date="2026-08-15",
        confidence="complete",
        completeness="complete",
        event_id="event-1",
        economic_terms_key="terms-1",
        provenance={"payload_hash": VALID_HASH, "adjusted_raw_policy": "raw"},
        source_evidence=(),
        to_dict=lambda: {"event": "split"},
    )
    assert prediction_lab._corporate_action_event(valid_action)["valid"] is True
    assert (
        prediction_lab._corporate_action_event({"market": "TWSE", "symbol": "2330"})["valid"]
        is False
    )
    mapping_action = prediction_lab._corporate_action_event(
        {
            "identity": "TWSE:2330",
            "effective_date": "2026-08-14",
            "available_date": "2026-08-15",
            "source": "official-action",
            "payload_hash": VALID_HASH,
            "action_type": "split",
            "split_ratio": 2.0,
        }
    )
    assert mapping_action["valid"] is True
    assert prediction_lab._corporate_action_event({"identity": "bad"})["valid"] is False


def test_calendar_schema_three_rejects_provenance_tampering() -> None:
    dates = ("2026-08-13", "2026-08-14")
    normalized_hash = prediction_lab._sha({"market": "TWSE", "year": 2026, "dates": list(dates)})
    common: dict[str, object] = {
        "market": "TWSE",
        "dates": dates,
        "source_hash": VALID_HASH,
        "source": "official",
        "endpoint": "https://example.invalid/calendar",
        "fetched_at": "2026-08-01T00:00:00+00:00",
        "schema_version": 3,
        "raw_payload_sha256": VALID_HASH,
        "raw_payload_hashes": (VALID_HASH,),
        "normalized_payload_sha256": normalized_hash,
        "normalization_algorithm_version": "calendar-v1",
        "raw_payload_size_bytes": 10,
        "year": 2026,
        "calendar_years": (2026,),
    }
    assert MarketTradingCalendar.from_dates(**common).schema_version == 3
    for field, value in (
        ("normalization_algorithm_version", None),
        ("year", 2025),
        ("normalized_payload_sha256", VALID_HASH),
        ("raw_payload_size_bytes", True),
    ):
        payload = dict(common)
        payload[field] = value
        with pytest.raises(PredictionLabError):
            MarketTradingCalendar.from_dates(**payload)


def test_default_calendar_loader_rejects_malformed_external_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "calendar.json"
    monkeypatch.setattr(prediction_lab, "OFFICIAL_CALENDAR_DATA_PATH", str(path))
    base = {"schema_version": 3, "calendars": [], "fetched_at": "2026-08-01T00:00:00+00:00"}
    malformed = [
        [],
        {"schema_version": 2, "calendars": [], "fetched_at": base["fetched_at"]},
        {"schema_version": 3, "calendars": [], "fetched_at": 1},
        {"schema_version": 3, "calendars": {}, "fetched_at": base["fetched_at"]},
        {"schema_version": 3, "calendars": ["bad"], "fetched_at": base["fetched_at"]},
        {
            "schema_version": 3,
            "calendars": [{"market": "TWSE", "unexpected": True}],
            "fetched_at": base["fetched_at"],
        },
    ]
    for payload in malformed:
        path.write_text(__import__("json").dumps(payload), encoding="utf-8")
        with pytest.raises(PredictionLabError):
            MarketTradingCalendar.default_for("TWSE")
    path.write_text(__import__("json").dumps(base), encoding="utf-8")
    with pytest.raises(PredictionLabError):
        MarketTradingCalendar.default_for("TWSE", year=True)


def test_runtime_provider_edge_cases_remain_fail_closed() -> None:
    rows = [
        {
            "market": "TWSE",
            "symbol": "TAIEX",
            "date": "2026-08-13",
            "close": 100.0,
            "provider": "official",
        },
        {
            "market": "TWSE",
            "symbol": "TAIEX",
            "date": "2026-08-20",
            "close": 102.0,
            "provider": "official",
        },
        {
            "market": "TWSE",
            "symbol": "2330",
            "date": "2026-08-13",
            "close": 100.0,
            "provider": "official",
        },
        {
            "market": "TWSE",
            "symbol": "2330",
            "date": "2026-08-20",
            "close": 110.0,
            "provider": "official",
        },
    ]
    provider = prediction_lab.RuntimeCachedOutcomeProvider(rows)
    assert provider.price("TWSE:2330", "missing") is None
    assert provider.benchmark("TPEX:OTC", "2026-08-20", "2026-08-13") is None
    assert provider.benchmark("TWSE:TAIEX", "2026-08-20", None) is not None
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")[0] == (
        "insufficient"
    )
    with pytest.raises(PredictionLabError):
        provider.corporate_action_status("TWSE:2330", "2026-08-21", "2026-08-20")

    provider._corporate_actions["TWSE:2330"] = [
        {
            "effective_date": "2026-08-14",
            "available_date": None,
            "requires_availability": True,
            "valid": False,
            "event_id": "bad",
            "terms": "",
        }
    ]
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")[0] == (
        "insufficient"
    )
    provider._corporate_actions["TWSE:2330"] = [
        {
            "effective_date": "2026-08-14",
            "available_date": "2026-08-15",
            "requires_availability": True,
            "valid": True,
            "event_id": "policy",
            "terms": "terms",
            "adjusted_raw_policy": "adjusted",
        }
    ]
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")[0] == (
        "insufficient"
    )
    provider._corporate_actions["TWSE:2330"][0]["adjusted_raw_policy"] = None
    provider._corporate_actions["TWSE:2330"][0]["available_date"] = "2026-08-30"
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")[0] == (
        "insufficient"
    )
    provider._corporate_actions["TWSE:2330"][0]["available_date"] = None
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")[0] == (
        "insufficient"
    )
    provider._corporate_actions["TWSE:2330"] = [
        {
            "effective_date": "2026-08-14",
            "available_date": "2026-08-15",
            "requires_availability": False,
            "valid": True,
            "event_id": "same",
            "terms": "one",
        },
        {
            "effective_date": "2026-08-14",
            "available_date": "2026-08-15",
            "requires_availability": False,
            "valid": True,
            "event_id": "same",
            "terms": "two",
        },
    ]
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")[0] == (
        "insufficient"
    )


def _corporate_action_for_test(
    action_type: CorporateActionType,
    *,
    policy: str | None,
) -> CorporateAction:
    """Build a source-backed event for production policy-boundary tests."""

    provenance: dict[str, object] = {"payload_hash": VALID_HASH}
    if policy is not None:
        provenance["adjusted_raw_policy"] = policy
    return CorporateAction(
        symbol=Symbol.parse("2330", market="TWSE"),
        action_type=action_type,
        effective_date="2026-08-14",
        available_date="2026-08-15",
        split_ratio=2.0 if action_type is CorporateActionType.SPLIT else None,
        cash_per_share=1.0 if action_type is CorporateActionType.CASH_DIVIDEND else None,
        currency="TWD" if action_type is CorporateActionType.CASH_DIVIDEND else None,
        source="official-corporate-action-replay",
        confidence="complete",
        completeness="complete",
        provenance=provenance,
    )


def _policy_boundary_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for symbol, first, last in (
        ("2330", 100.0, 50.0),
        ("TAIEX", 20_000.0, 20_100.0),
    ):
        rows.extend(
            {
                "market": "TWSE",
                "symbol": symbol,
                "date": day,
                "close": value,
                "provider": "official-replay",
            }
            for day, value in (("2026-08-13", first), ("2026-08-20", last))
        )
    return rows


def test_action_in_window_without_policy_is_insufficient_for_split_and_dividend() -> None:
    rows = _policy_boundary_rows()
    for action_type in (CorporateActionType.SPLIT, CorporateActionType.CASH_DIVIDEND):
        provider = prediction_lab.RuntimeCachedOutcomeProvider(
            rows,
            corporate_actions=(_corporate_action_for_test(action_type, policy=None),),
        )
        status, reason = provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")
        assert status == "insufficient"
        assert reason


@pytest.mark.parametrize(
    "action_type", [CorporateActionType.SPLIT, CorporateActionType.CASH_DIVIDEND]
)
def test_raw_price_policy_event_is_always_insufficient(action_type: CorporateActionType) -> None:
    """Raw events cannot be evaluated until the evaluator supports adjustments."""

    provider = prediction_lab.RuntimeCachedOutcomeProvider(
        _policy_boundary_rows(),
        price_policy="raw",
        corporate_actions=(_corporate_action_for_test(action_type, policy="raw"),),
    )
    status, reason = provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")
    assert status == "insufficient"
    assert reason and "調整" in reason


def test_matching_adjusted_policy_is_the_only_action_clear_path() -> None:
    rows = [
        {
            "market": "TWSE",
            "symbol": "2330",
            "date": day,
            "close": close,
            "adjusted_close": adjusted,
            "provider": "official-adjusted-replay",
        }
        for day, close, adjusted in (
            ("2026-08-13", 100.0, 50.0),
            ("2026-08-20", 50.0, 50.0),
        )
    ]
    provider = prediction_lab.RuntimeCachedOutcomeProvider(
        rows,
        price_policy="adjusted",
        corporate_actions=(
            _corporate_action_for_test(CorporateActionType.SPLIT, policy="adjusted"),
        ),
    )
    assert provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20") == (
        "clear",
        None,
    )
    evidence = provider.price("TWSE:2330", "2026-08-20")
    assert evidence is not None and evidence.price_field == "adjusted_close"


def test_adjusted_action_without_adjusted_close_is_retryable() -> None:
    provider = prediction_lab.RuntimeCachedOutcomeProvider(
        _policy_boundary_rows(),
        price_policy="adjusted",
        corporate_actions=(
            _corporate_action_for_test(CorporateActionType.SPLIT, policy="adjusted"),
        ),
    )
    status, reason = provider.corporate_action_status("TWSE:2330", "2026-08-13", "2026-08-20")
    assert status == "insufficient"
    assert reason and "adjusted_close" in reason


@pytest.mark.parametrize(
    ("action_type", "action_policy"),
    [
        (CorporateActionType.SPLIT, None),
        (CorporateActionType.SPLIT, "raw"),
        (CorporateActionType.CASH_DIVIDEND, "raw"),
    ],
)
def test_raw_corporate_action_cannot_emit_negative_return(
    tmp_path: Path,
    action_type: CorporateActionType,
    action_policy: str | None,
) -> None:
    """Raw 100->50 data must remain retryable until policy evidence exists."""

    action = _corporate_action_for_test(action_type, policy=action_policy)
    provider = prediction_lab.RuntimeCachedOutcomeProvider(
        _policy_boundary_rows(), corporate_actions=(action,)
    )
    store = PredictionLabStore(tmp_path / "prediction-lab")
    prediction = PredictionRecord.create(
        created_at=datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
        trading_date="2026-08-13",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=1.0,
        input_hashes=(VALID_HASH,),
        source_hashes=(VALID_HASH,),
        benchmark_identity="TWSE:TAIEX",
        entry_price_reference={
            "identity": "TWSE:2330",
            "value": 100.0,
            "effective_trading_date": "2026-08-13",
            "provider": "official-replay",
            "payload_hash": VALID_HASH,
            "price_field": "close",
            "adjusted_raw_policy": "raw",
        },
    )
    store.save_prediction(prediction)
    result = PredictionOutcomeEvaluator(
        store,
        provider,
        now_fn=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")
    assert result.evaluated_count == 0
    assert result.outcomes[0].status in {"eligible", "unavailable"}
    assert result.outcomes[0].gross_return is None
    assert result.outcomes[0].net_return is None
    assert result.outcomes[0].net_excess_return is None


def test_adjusted_corporate_action_can_be_evaluated_with_adjusted_prices(tmp_path: Path) -> None:
    rows = [
        {
            "market": "TWSE",
            "symbol": symbol,
            "date": day,
            "close": close,
            "adjusted_close": adjusted,
            "provider": "official-adjusted-replay",
        }
        for symbol, values in (
            ("2330", (("2026-08-13", 100.0, 50.0), ("2026-08-20", 50.0, 50.0))),
            ("TAIEX", (("2026-08-13", 20_000.0, 20_000.0), ("2026-08-20", 20_100.0, 20_100.0))),
        )
        for day, close, adjusted in values
    ]
    provider = prediction_lab.RuntimeCachedOutcomeProvider(
        rows,
        price_policy="adjusted",
        corporate_actions=(
            _corporate_action_for_test(CorporateActionType.SPLIT, policy="adjusted"),
        ),
    )
    store = PredictionLabStore(tmp_path / "prediction-lab")
    prediction = PredictionRecord.create(
        created_at=datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
        trading_date="2026-08-13",
        market="TWSE",
        symbol="2330",
        horizon=5,
        bucket="top",
        rank=1,
        universe_size=3,
        deterministic_score=1.0,
        input_hashes=(VALID_HASH,),
        source_hashes=(VALID_HASH,),
        benchmark_identity="TWSE:TAIEX",
        entry_price_reference={
            "identity": "TWSE:2330",
            "value": 50.0,
            "effective_trading_date": "2026-08-13",
            "provider": "official-adjusted-replay",
            "payload_hash": VALID_HASH,
            "price_field": "adjusted_close",
            "adjusted_raw_policy": "adjusted",
        },
    )
    store.save_prediction(prediction)
    result = PredictionOutcomeEvaluator(
        store,
        provider,
        now_fn=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    ).evaluate_due(as_of="2026-08-20")
    assert result.evaluated_count == 1
    outcome = result.outcomes[0]
    assert outcome.status == "evaluated"
    assert outcome.gross_return == pytest.approx(0.0)
    assert outcome.net_return is not None
    assert outcome.net_excess_return is not None


def test_production_corporate_action_import_roundtrip_uses_atomic_source_contract(
    tmp_path: Path,
) -> None:
    source = tmp_path / "official-actions.csv"
    destination = tmp_path / "runtime" / "corporate_actions.csv"
    source.write_bytes(
        (
            "symbol,market,action_type,effective_date,available_date,payable_date,"
            "split_ratio,cash_per_share,currency,tax_rate,source,confidence,completeness,"
            "notes,adjusted_raw_policy\n"
            "2330,TWSE,split,2026-08-10,2026-08-11,,2.0,,,0.0,official-actions,"
            "complete,complete,,raw\n"
        ).encode("utf-8")
    )
    importer = prediction_lab.CorporateActionImportService()
    imported = importer.import_source(source, destination)
    assert destination.read_bytes() == source.read_bytes()
    assert (
        imported[0].provenance["payload_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    )

    database = tmp_path / "stock_data.sqlite"
    SQLitePriceStorage(database).save_market_qualified_price_data(
        [
            {
                "date": "2026-08-13",
                "symbol": "2330",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
                "adjusted_close": None,
            }
        ],
        provenance=PersistedPriceProvenance(
            symbol=Symbol.parse("2330", market="TWSE"),
            provider="official-replay",
            provider_symbol="2330.TW",
            source_type="online",
            last_data_date="2026-08-13",
            checked_at="2026-08-14T00:00:00+00:00",
        ),
    )
    provider = prediction_lab.build_runtime_cached_outcome_provider(
        database, corporate_actions_path=destination
    )
    assert provider is not None
    assert provider._corporate_actions["TWSE:2330"][0]["adjusted_raw_policy"] == "raw"
