from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from stock_tool.application.analysis import AnalysisService
from stock_tool.application.data_hydration import DataHydrationService
from stock_tool.application.results import AnalysisStatus
from stock_tool.data.cleaner import clean_price_data
from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    ProviderAttemptRecord,
    ProviderResult,
    ProviderStatus,
    provider_failure_result,
    provider_result_from_price_frame,
)
from stock_tool.data.loader import load_csv
from stock_tool.data.storage import SQLitePriceStorage
from stock_tool.domain.models import Market, Symbol
from stock_tool.fundamentals import load_fundamentals_csv, score_fundamentals
from stock_tool.indicators import add_atr, add_macd, add_rolling_return, add_rsi, add_sma
from stock_tool.stock_scoring import score_stock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PRICE_PATH = PROJECT_ROOT / "data" / "sample" / "sample_tw_prices_for_indicators.csv"
SAMPLE_FUNDAMENTAL_PATH = PROJECT_ROOT / "data" / "sample" / "sample_fundamentals.csv"
FIXED_TIME = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class StaticContractProvider:
    """Deterministic Provider Contract fixture used by application tests."""

    def __init__(self, result: ProviderResult[pd.DataFrame]) -> None:
        self.result = result

    def load_price_result(self) -> ProviderResult[pd.DataFrame]:
        return self.result


def _sample_prices() -> pd.DataFrame:
    rows = load_csv(SAMPLE_PRICE_PATH)
    return pd.DataFrame(clean_price_data(rows).records)


def _metadata(source_type: DataSourceType = DataSourceType.ONLINE) -> DataSourceMetadata:
    symbol = Symbol(code="2330", market=Market.TWSE)
    return DataSourceMetadata(
        provider="fixture-provider",
        source_type=source_type,
        requested_symbol=symbol,
        resolved_symbol=symbol,
        provider_symbol="2330.TW",
        request_start="2024-01-01",
        request_end="2024-12-31",
    )


def _success_result(
    *,
    source_type: DataSourceType = DataSourceType.ONLINE,
    warnings: tuple[str, ...] = (),
) -> ProviderResult[pd.DataFrame]:
    return provider_result_from_price_frame(
        _sample_prices(),
        metadata=_metadata(source_type),
        warnings=warnings,
        attempts=(ProviderAttemptRecord("fixture-provider", True, "fixture completed"),),
    )


def _standard_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    output = add_sma(prices, periods=(20, 60))
    output = add_rsi(output)
    output = add_macd(output)
    output = add_atr(output)
    return add_rolling_return(output, periods=(20,))


def _fundamentals_for_symbol(symbol: Symbol) -> pd.DataFrame:
    frame = load_fundamentals_csv(SAMPLE_FUNDAMENTAL_PATH)
    return frame.loc[frame["symbol"] == symbol.code].copy(deep=True)


def _hydration_service(
    result: ProviderResult[pd.DataFrame],
    storage: SQLitePriceStorage | None = None,
) -> DataHydrationService:
    return DataHydrationService(
        provider=StaticContractProvider(result),
        storage=storage,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-fixed-001",
    )


def test_hydration_records_provenance_for_online_cache_upload_and_sample_sources(
    tmp_path: Path,
) -> None:
    expected_source_labels = {
        DataSourceType.ONLINE: "online",
        DataSourceType.CACHE: "cache",
        DataSourceType.USER_UPLOAD: "user_upload",
        DataSourceType.SAMPLE: "sample",
    }

    for source_type, expected_label in expected_source_labels.items():
        storage = SQLitePriceStorage(tmp_path / f"{source_type.value}.sqlite")
        snapshot = _hydration_service(_success_result(source_type=source_type), storage).hydrate()

        serialized = snapshot.to_dict()
        runs = storage.list_ingestion_runs()

        assert snapshot.data is not None
        assert serialized["metadata"]["source_type"] == expected_label
        assert serialized["metadata"]["cache_hit"] is (source_type is DataSourceType.CACHE)
        assert serialized["metadata"]["last_data_date"] == "2024-12-30"
        assert len(runs) == 1
        assert runs[0]["source_type"] == expected_label


def test_analysis_service_matches_direct_indicator_fundamental_and_score_modules(
    tmp_path: Path,
) -> None:
    prices = _sample_prices()
    input_copy = prices.copy(deep=True)
    provider_result = provider_result_from_price_frame(prices, metadata=_metadata())
    storage = SQLitePriceStorage(tmp_path / "analysis.sqlite")
    hydration = _hydration_service(provider_result, storage)
    service = AnalysisService(
        hydration_service=hydration,
        indicator_calculator=_standard_indicators,
        fundamental_loader=_fundamentals_for_symbol,
        fundamental_scorer=score_fundamentals,
        stock_scorer=score_stock,
    )

    result = service.analyze()
    direct_indicators = _standard_indicators(prices)
    direct_fundamentals = score_fundamentals(_fundamentals_for_symbol(Symbol("2330", Market.TWSE)))
    direct_score = score_stock(
        symbol="2330",
        price_data=prices,
        technical_indicators=direct_indicators,
        fundamental_scores=direct_fundamentals,
    )

    assert result.status is AnalysisStatus.SUCCESS
    assert result.indicators is not None
    assert result.fundamental_scores is not None
    assert result.stock_score == direct_score
    pd.testing.assert_frame_equal(result.indicators, direct_indicators)
    pd.testing.assert_frame_equal(result.fundamental_scores, direct_fundamentals)
    pd.testing.assert_frame_equal(prices, input_copy)
    assert result.to_dict()["stock_score"]["total_score"] == direct_score.total_score


def test_missing_fundamentals_remain_unknown_and_mark_analysis_partial() -> None:
    service = AnalysisService(
        hydration_service=_hydration_service(_success_result()),
        indicator_calculator=_standard_indicators,
        stock_scorer=score_stock,
    )

    result = service.analyze()

    assert result.status is AnalysisStatus.PARTIAL
    assert result.stock_score is not None
    assert result.stock_score.total_score == "unknown"
    assert any(item.field == "fundamental_data" for item in result.missing_data)


def test_partial_provider_result_returns_partial_analysis_without_fake_total_score() -> None:
    prices = _sample_prices().drop(columns=["adjusted_close"])
    partial_result = provider_result_from_price_frame(
        prices,
        metadata=_metadata(),
        warnings=("adjusted_close was not supplied",),
    )
    service = AnalysisService(
        hydration_service=_hydration_service(partial_result),
        indicator_calculator=_standard_indicators,
        stock_scorer=score_stock,
    )

    result = service.analyze()

    assert result.status is AnalysisStatus.PARTIAL
    assert result.indicators is not None
    assert result.stock_score is not None
    assert result.stock_score.total_score == "unknown"
    assert any(item.field == "fundamental_data" for item in result.missing_data)


def test_provider_error_short_circuits_without_fake_analysis_or_score(tmp_path: Path) -> None:
    failed_result = provider_failure_result(
        metadata=_metadata(),
        message="network unavailable token=secret-value",
        attempts=(ProviderAttemptRecord("fixture-provider", False, "network unavailable"),),
    )
    storage = SQLitePriceStorage(tmp_path / "failure.sqlite")
    result = AnalysisService(hydration_service=_hydration_service(failed_result, storage)).analyze()

    assert result.status is AnalysisStatus.ERROR
    assert result.indicators is None
    assert result.fundamental_scores is None
    assert result.stock_score is None
    assert result.to_dict()["stock_score"] is None
    assert "secret-value" not in str(result.to_dict())
    assert storage.list_ingestion_runs()[0]["status"] == ProviderStatus.ERROR.value
    assert "secret-value" not in str(storage.list_ingestion_runs())


def test_hydration_is_deterministic_and_persists_quality_warnings_and_attempts(
    tmp_path: Path,
) -> None:
    warning = "cache refresh skipped; api_key=top-secret"
    result = _success_result(warnings=(warning,))
    storage = SQLitePriceStorage(tmp_path / "lineage.sqlite")

    first = _hydration_service(result, storage).hydrate()
    second = _hydration_service(result, storage).hydrate()
    persisted = storage.list_ingestion_runs()[0]

    assert first.to_dict() == second.to_dict()
    assert persisted["quality_summary"]["output_rows"] == len(_sample_prices())
    assert persisted["attempts"][0]["provider"] == "fixture-provider"
    assert "top-secret" not in str(persisted)
    assert "[REDACTED]" in persisted["warnings"][0]


def test_hydration_records_download_cache_and_cleaning_warnings_without_secrets(
    tmp_path: Path,
) -> None:
    warnings = (
        "download retry after HTTP 429",
        "cache entry was older than the configured refresh window",
        "cleaner removed duplicate rows from api_key=private-key",
    )
    storage = SQLitePriceStorage(tmp_path / "warnings.sqlite")
    snapshot = _hydration_service(_success_result(warnings=warnings), storage).hydrate()
    persisted = storage.list_ingestion_runs()[0]

    assert len(snapshot.warnings) == 3
    assert persisted["warnings"][0] == "download retry after HTTP 429"
    assert persisted["warnings"][1] == "cache entry was older than the configured refresh window"
    assert "private-key" not in str(persisted)
    assert "[REDACTED]" in persisted["warnings"][2]


def test_stale_and_missing_data_states_are_serializable() -> None:
    result = _success_result(source_type=DataSourceType.CACHE)
    service = DataHydrationService(
        provider=StaticContractProvider(result),
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-fixed-stale",
        as_of_date="2025-03-01",
        stale_after_days=7,
    )

    snapshot = service.hydrate()
    serialized = snapshot.to_dict()

    assert snapshot.is_stale is True
    assert any(item["state"] == "stale" for item in serialized["missing_data"])
    assert serialized["metadata"]["last_data_date"] == "2024-12-30"
