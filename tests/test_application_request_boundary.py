from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from stock_tool.application.analysis import AnalysisService
from stock_tool.application.data_hydration import DataHydrationService
from stock_tool.application.results import (
    AnalysisRequest,
    AnalysisStatus,
    DataHydrationRequest,
)
from stock_tool.data.cleaner import clean_price_data
from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    ProviderResult,
    ProviderStatus,
    provider_result_from_price_frame,
)
from stock_tool.data.loader import load_csv
from stock_tool.data.storage import SQLitePriceStorage
from stock_tool.domain.models import Market, MissingDataState, Symbol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PRICE_PATH = PROJECT_ROOT / "data" / "sample" / "sample_tw_prices_for_indicators.csv"
FIXED_TIME = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class StaticResolver:
    """Request-aware contract-provider resolver used at the application boundary."""

    def __init__(self, provider: object) -> None:
        self.provider = provider
        self.requests: list[DataHydrationRequest] = []

    def resolve(self, request: DataHydrationRequest) -> object:
        self.requests.append(request)
        return self.provider


class StaticContractProvider:
    """Provider fixture returning one deterministic contract result."""

    def __init__(self, result: ProviderResult[pd.DataFrame]) -> None:
        self.result = result

    def load_price_result(self) -> ProviderResult[pd.DataFrame]:
        return self.result


class RaisingContractProvider:
    """Provider fixture that simulates an unexpected external failure."""

    def load_price_result(self) -> ProviderResult[pd.DataFrame]:
        raise RuntimeError("network failure token=secret-value")


class SaveFailureStorage(SQLitePriceStorage):
    """SQLite test double that fails only the price persistence step."""

    def save_price_data(self, records: list[dict[str, object]]) -> int:
        raise RuntimeError("price write token=secret-value")


class IngestionFailureStorage(SQLitePriceStorage):
    """SQLite test double that fails only the lineage persistence step."""

    def record_ingestion_run(self, record: object) -> None:
        raise RuntimeError("lineage write api_key=secret-value")


def _request() -> DataHydrationRequest:
    return DataHydrationRequest(
        symbol=Symbol("2330", Market.TWSE),
        start_date="2024-01-01",
        end_date="2024-12-31",
        interval="1d",
    )


def _sample_prices() -> pd.DataFrame:
    return pd.DataFrame(clean_price_data(load_csv(SAMPLE_PRICE_PATH)).records)


def _result_for_request(
    request: DataHydrationRequest,
    *,
    resolved_symbol: Symbol | None = None,
) -> ProviderResult[pd.DataFrame]:
    return provider_result_from_price_frame(
        _sample_prices(),
        metadata=DataSourceMetadata(
            provider="fixture-provider",
            source_type=DataSourceType.ONLINE,
            requested_symbol=request.symbol,
            resolved_symbol=resolved_symbol or request.symbol,
            provider_symbol="2330.TW",
            request_start=request.start_date,
            request_end=request.end_date,
            interval=request.interval,
        ),
    )


def _hydration_service(
    resolver: StaticResolver,
    *,
    storage: SQLitePriceStorage | None = None,
) -> DataHydrationService:
    return DataHydrationService(
        provider_resolver=resolver,
        storage=storage,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "request-boundary-run",
    )


def test_request_boundary_passes_canonical_symbol_and_dates_to_resolver() -> None:
    request = _request()
    resolver = StaticResolver(StaticContractProvider(_result_for_request(request)))

    snapshot = _hydration_service(resolver).hydrate(request)

    assert resolver.requests == [request]
    assert snapshot.status is ProviderStatus.SUCCESS
    assert snapshot.request == request
    assert snapshot.to_dict()["request"] == request.to_dict()


def test_request_and_provider_metadata_mismatch_returns_safe_structured_error() -> None:
    request = _request()
    mismatch = _result_for_request(request, resolved_symbol=Symbol("2317", Market.TWSE))
    resolver = StaticResolver(StaticContractProvider(mismatch))

    snapshot = _hydration_service(resolver).hydrate(request)

    assert snapshot.status is ProviderStatus.ERROR
    assert snapshot.data is None
    assert snapshot.error is not None
    assert "metadata" in snapshot.error.message.lower()
    assert "2317" not in snapshot.error.message


def test_request_date_range_and_provider_metadata_mismatch_returns_safe_error() -> None:
    request = _request()
    result = _result_for_request(request)
    mismatched_metadata = DataSourceMetadata(
        provider=result.metadata.provider,
        source_type=result.metadata.source_type,
        requested_symbol=request.symbol,
        resolved_symbol=request.symbol,
        provider_symbol=result.metadata.provider_symbol,
        request_start=request.start_date,
        request_end="2024-12-30",
        interval=request.interval,
    )
    mismatch = provider_result_from_price_frame(_sample_prices(), metadata=mismatched_metadata)

    snapshot = _hydration_service(StaticResolver(StaticContractProvider(mismatch))).hydrate(request)

    assert snapshot.status is ProviderStatus.ERROR
    assert snapshot.error is not None
    assert "metadata" in snapshot.error.message.lower()


def test_provider_exception_is_structured_and_redacted_at_request_boundary() -> None:
    resolver = StaticResolver(RaisingContractProvider())

    snapshot = _hydration_service(resolver).hydrate(_request())

    serialized = snapshot.to_dict()
    assert snapshot.status is ProviderStatus.ERROR
    assert snapshot.error is not None
    assert "secret-value" not in str(serialized)
    assert "validated price data" in snapshot.error.message.lower()


def test_stock_scorer_failure_returns_partial_with_canonical_missing_data() -> None:
    request = AnalysisRequest(data_request=_request())
    resolver = StaticResolver(StaticContractProvider(_result_for_request(request.data_request)))

    def indicators(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.copy(deep=True)

    def failing_scorer(**_: object) -> object:
        raise RuntimeError("score failed authorization=secret-value")

    result = AnalysisService(
        hydration_service=_hydration_service(resolver),
        indicator_calculator=indicators,
        stock_scorer=failing_scorer,
    ).analyze(request)

    composite = [item for item in result.missing_data if item.field == "composite_score"]
    assert result.status is AnalysisStatus.PARTIAL
    assert result.stock_score is None
    assert composite[0].state is MissingDataState.UNKNOWN
    assert "secret-value" not in str(result.to_dict())


def test_missing_indicator_and_unconfigured_composite_use_not_applicable_state() -> None:
    request = AnalysisRequest(data_request=_request())
    resolver = StaticResolver(StaticContractProvider(_result_for_request(request.data_request)))

    result = AnalysisService(hydration_service=_hydration_service(resolver)).analyze(request)

    missing = {item.field: item.state for item in result.missing_data}
    assert result.status is AnalysisStatus.PARTIAL
    assert missing["technical_indicators"] is MissingDataState.NOT_APPLICABLE
    assert missing["composite_score"] is MissingDataState.NOT_APPLICABLE


def test_indicator_failure_uses_canonical_unknown_state_without_a_fake_score() -> None:
    request = AnalysisRequest(data_request=_request())
    resolver = StaticResolver(StaticContractProvider(_result_for_request(request.data_request)))

    def failing_indicators(_: pd.DataFrame) -> pd.DataFrame:
        raise RuntimeError("indicator authorization=secret-value")

    result = AnalysisService(
        hydration_service=_hydration_service(resolver),
        indicator_calculator=failing_indicators,
    ).analyze(request)

    technical = [item for item in result.missing_data if item.field == "technical_indicators"]
    assert result.status is AnalysisStatus.PARTIAL
    assert result.stock_score is None
    assert technical[0].state is MissingDataState.UNKNOWN
    assert "secret-value" not in str(result.to_dict())


def test_price_and_ingestion_persistence_failures_do_not_discard_hydrated_data(
    tmp_path: Path,
) -> None:
    request = _request()
    provider = StaticContractProvider(_result_for_request(request))

    price_snapshot = _hydration_service(
        StaticResolver(provider),
        storage=SaveFailureStorage(tmp_path / "save-failure.sqlite"),
    ).hydrate(request)
    lineage_snapshot = _hydration_service(
        StaticResolver(provider),
        storage=IngestionFailureStorage(tmp_path / "lineage-failure.sqlite"),
    ).hydrate(request)

    assert price_snapshot.data is not None
    assert price_snapshot.metadata.ingestion_persisted is True
    assert lineage_snapshot.data is not None
    assert lineage_snapshot.metadata.ingestion_persisted is False
    assert "secret-value" not in str(price_snapshot.to_dict())
    assert "secret-value" not in str(lineage_snapshot.to_dict())
    assert "[REDACTED]" in " ".join(price_snapshot.warnings)
    assert "[REDACTED]" in " ".join(lineage_snapshot.warnings)
