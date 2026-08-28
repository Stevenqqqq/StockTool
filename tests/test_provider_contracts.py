from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from stock_tool.data import auto_fetch
from stock_tool.data.auto_fetch import (
    FetchResult,
    ProviderAttempt,
    ProviderContractDisabledError,
    fetch_prices_result,
)
from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    ProviderAttemptRecord,
    ProviderError,
    ProviderErrorCode,
    ProviderStatus,
    QualityStatus,
    adapt_legacy_fetch_result,
    provider_failure_result,
    provider_result_from_price_frame,
    sanitize_provider_text,
)
from stock_tool.data.cleaner import clean_price_data
from stock_tool.data.loader import STANDARD_COLUMNS
from stock_tool.data.providers import (
    CSVPriceDataProvider,
    LegacyPriceDataProviderAdapter,
)
from stock_tool.domain.models import Market, Symbol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPRINT1_BASELINE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "sprint1_baseline.json"
VERSIONED_PRICE_FIXTURE_PATH = (
    PROJECT_ROOT / "data" / "sample" / "sample_tw_prices_for_indicators.csv"
)


def _price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "symbol": ["2330", "2330"],
            "open": [100.0, 102.0],
            "high": [103.0, 104.0],
            "low": [99.0, 101.0],
            "close": [102.0, 103.0],
            "volume": [1000, 1200],
            "adjusted_close": [102.0, 103.0],
        }
    )


def _metadata(
    *,
    source_type: DataSourceType = DataSourceType.ONLINE,
    provider_symbol: str = "2330.TW",
) -> DataSourceMetadata:
    requested = Symbol.parse("2330", market="TWSE")
    return DataSourceMetadata(
        provider="yfinance",
        source_type=source_type,
        requested_symbol=requested,
        resolved_symbol=requested,
        provider_symbol=provider_symbol,
        request_start="2024-01-02",
        request_end="2024-01-03",
        interval="1d",
    )


def _legacy_fetch_result(
    *,
    data: pd.DataFrame | None = None,
    provider_symbol: str = "2330.TW",
    market: str = "TWSE",
    source_type: str = "cache",
) -> FetchResult:
    return FetchResult(
        data=_price_frame() if data is None else data,
        source="yfinance",
        symbol="2330",
        provider_symbol=provider_symbol,
        from_cache=source_type == "cache",
        cache_file=Path("data/cache/yfinance_2330.TW.csv") if source_type == "cache" else None,
        market=market,
        start_date="2024-01-02",
        end_date="2024-01-03",
        source_type=source_type,
        warnings=("fallback used",) if source_type == "cache" else (),
        attempts=(
            ProviderAttempt("yfinance:2330.TW", False, "network unavailable"),
            ProviderAttempt("cache:yfinance", True, "loaded 2 rows"),
        ),
    )


def _versioned_market_cases() -> list[dict[str, Any]]:
    """Load the immutable Sprint 1 market cases used for adapter equivalence."""

    baseline = json.loads(SPRINT1_BASELINE_PATH.read_text(encoding="utf-8"))
    return list(baseline["market_acceptance"])


def _versioned_price_rows_for_symbol(symbol: str) -> list[dict[str, Any]]:
    """Reuse the versioned sample OHLCV payload without inventing price values."""

    rows = CSVPriceDataProvider(VERSIONED_PRICE_FIXTURE_PATH).load_price_data()
    return [{**row, "symbol": symbol} for row in rows]


def test_success_contract_normalizes_data_without_mutating_input() -> None:
    original = _price_frame()
    snapshot = original.copy(deep=True)

    result = provider_result_from_price_frame(
        original,
        metadata=_metadata(),
        attempts=(ProviderAttemptRecord("yfinance", True, "loaded 2 rows"),),
    )

    assert result.status is ProviderStatus.SUCCESS
    assert result.quality.status is QualityStatus.VALID
    assert result.quality.input_rows == 2
    assert result.quality.output_rows == 2
    assert result.data is not None
    assert list(result.data.columns) == list(STANDARD_COLUMNS)
    assert_frame_equal(original, snapshot)

    result.data.loc[0, "close"] = 1.0
    assert_frame_equal(original, snapshot)


def test_empty_provider_data_has_explicit_empty_contract() -> None:
    result = provider_result_from_price_frame(
        pd.DataFrame(columns=STANDARD_COLUMNS),
        metadata=_metadata(),
    )

    assert result.status is ProviderStatus.EMPTY
    assert result.data is None
    assert result.quality.status is QualityStatus.EMPTY
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.EMPTY_DATASET


def test_schema_drift_is_reported_and_extra_columns_are_not_forwarded() -> None:
    source = _price_frame().assign(vendor_flag=["ok", "ok"])

    result = provider_result_from_price_frame(source, metadata=_metadata())

    assert result.status is ProviderStatus.PARTIAL
    assert result.quality.status is QualityStatus.PARTIAL
    assert result.quality.extra_columns == ("vendor_flag",)
    assert result.data is not None
    assert "vendor_flag" not in result.data.columns
    assert any(issue.code == "extra_columns" for issue in result.quality.issues)


def test_partial_rows_are_removed_without_inventing_adjusted_close() -> None:
    source = _price_frame().drop(columns="adjusted_close")
    source.loc[1, "volume"] = None

    result = provider_result_from_price_frame(source, metadata=_metadata())

    assert result.status is ProviderStatus.PARTIAL
    assert result.quality.input_rows == 2
    assert result.quality.output_rows == 1
    assert result.quality.missing_optional_columns == ("adjusted_close",)
    assert result.data is not None
    assert result.data["adjusted_close"].isna().all()


def test_missing_required_schema_returns_structured_error() -> None:
    source = _price_frame().drop(columns="volume")

    result = provider_result_from_price_frame(source, metadata=_metadata())

    assert result.status is ProviderStatus.ERROR
    assert result.data is None
    assert result.quality.status is QualityStatus.INVALID
    assert result.quality.missing_required_columns == ("volume",)
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.SCHEMA_MISMATCH


def test_duplicate_standard_columns_return_structured_schema_error() -> None:
    source = pd.concat([_price_frame(), _price_frame().loc[:, ["close"]]], axis=1)
    snapshot = source.copy(deep=True)

    result = provider_result_from_price_frame(source, metadata=_metadata())

    assert result.status is ProviderStatus.ERROR
    assert result.data is None
    assert result.quality.status is QualityStatus.INVALID
    assert result.quality.duplicate_columns == ("close",)
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.SCHEMA_MISMATCH
    assert any(issue.code == "duplicate_columns" for issue in result.quality.issues)
    assert_frame_equal(source, snapshot)


def test_legacy_fetch_adapter_preserves_metadata_and_fallback_history() -> None:
    legacy = _legacy_fetch_result()
    original = legacy.data.copy(deep=True)

    result = adapt_legacy_fetch_result(legacy)

    assert result.status is ProviderStatus.SUCCESS
    assert result.metadata.source_type is DataSourceType.CACHE
    assert result.metadata.requested_symbol == Symbol.parse("2330", market="TWSE")
    assert result.metadata.resolved_symbol == Symbol.parse("2330.TW", market="TWSE")
    assert result.metadata.provider_symbol == "2330.TW"
    assert result.fallback_attempted is True
    assert result.used_fallback is True
    assert [attempt.success for attempt in result.attempts] == [False, True]
    assert_frame_equal(legacy.data, original)


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("api_key=value", "api_key=[REDACTED]"),
        ("api-key: value", "api-key: [REDACTED]"),
        ("API key: secret-value", "API key: [REDACTED]"),
        ("token=value", "token=[REDACTED]"),
        ("Authorization: Bearer value", "Authorization: [REDACTED]"),
        (
            "https://provider.example/data?symbol=2330&token=secret-value",
            "https://provider.example/data?symbol=2330&token=[REDACTED]",
        ),
    ],
)
def test_sanitize_provider_text_is_idempotent_for_common_credential_forms(
    raw_text: str,
    expected: str,
) -> None:
    once = sanitize_provider_text(raw_text)
    twice = sanitize_provider_text(once)
    three_times = sanitize_provider_text(twice)

    assert once == expected
    assert twice == expected
    assert three_times == expected
    assert once.count("[REDACTED]") == 1
    assert "[REDACTED]]" not in once


def test_sanitize_provider_text_keeps_non_sensitive_diagnostics_unchanged() -> None:
    diagnostic = "HTTP 429: rate limit exceeded after 30 seconds."

    assert sanitize_provider_text(diagnostic) == diagnostic


def test_legacy_fetch_adapter_redacts_sensitive_attempt_reasons_in_serialization() -> None:
    legacy = replace(
        _legacy_fetch_result(source_type="online"),
        warnings=("upstream api_key=api-key-value",),
        attempts=(
            ProviderAttempt(
                "yfinance:2330.TW",
                False,
                "upstream rejected token=secret-value",
            ),
        ),
    )

    result = adapt_legacy_fetch_result(legacy)
    serialized = json.dumps(result.to_dict(), sort_keys=True)

    assert "secret-value" not in serialized
    assert "api-key-value" not in serialized
    assert "upstream rejected" in serialized
    assert "[REDACTED]" in serialized
    assert "[REDACTED]]" not in serialized
    assert result.warnings == ("upstream api_key=[REDACTED]",)
    assert result.attempts[0].reason == "upstream rejected token=[REDACTED]"


def test_provider_contract_redacts_sensitive_warnings_attempts_and_errors() -> None:
    warning = (
        "Request failed for https://provider.example/data?symbol=2330&token=url-secret"
        "&session=diagnostic-session; api_key=api-key-value"
    )
    attempt = ProviderAttemptRecord(
        provider="yfinance",
        success=False,
        reason="authorization=Bearer auth-secret password=password-value",
    )
    failure = provider_failure_result(
        metadata=_metadata(),
        message="Provider secret=error-secret at https://provider.example/data?token=error-token",
        attempts=(attempt,),
    )
    success = provider_result_from_price_frame(
        _price_frame(),
        metadata=_metadata(),
        warnings=(warning,),
        attempts=(attempt,),
    )

    serialized = json.dumps(
        {"failure": failure.to_dict(), "success": success.to_dict()}, sort_keys=True
    )

    for secret in (
        "url-secret",
        "api-key-value",
        "auth-secret",
        "password-value",
        "error-secret",
        "error-token",
    ):
        assert secret not in serialized
    assert "provider.example/data?symbol=2330" in serialized
    assert "session=diagnostic-session" in serialized
    assert "[REDACTED]" in serialized


def test_provider_contract_keeps_non_sensitive_diagnostics() -> None:
    result = provider_failure_result(
        metadata=_metadata(),
        message="HTTP 503: upstream service unavailable after 2 retries.",
        attempts=(
            ProviderAttemptRecord(
                provider="yfinance",
                success=False,
                reason="HTTP 429: rate limit exceeded after 30 seconds.",
            ),
        ),
    )

    serialized = result.to_dict()

    assert (
        serialized["error"]["message"] == "HTTP 503: upstream service unavailable after 2 retries."
    )
    assert serialized["attempts"][0]["reason"] == "HTTP 429: rate limit exceeded after 30 seconds."


def test_provider_error_direct_construction_uses_redaction_policy() -> None:
    error = ProviderError(
        code=ProviderErrorCode.PROVIDER_FAILURE,
        message="authorization=Bearer direct-auth-secret",
        provider="provider?api_key=direct-api-key",
    )

    serialized = json.dumps(error.to_dict(), sort_keys=True)

    assert "direct-auth-secret" not in serialized
    assert "direct-api-key" not in serialized
    assert "[REDACTED]" in serialized


def test_versioned_sample_legacy_file_provider_matches_contract_adapter() -> None:
    legacy_provider = CSVPriceDataProvider(VERSIONED_PRICE_FIXTURE_PATH)
    legacy_rows = legacy_provider.load_price_data()
    legacy_cleaned = clean_price_data(legacy_rows)
    expected = pd.DataFrame(legacy_cleaned.records, columns=STANDARD_COLUMNS)
    adapter = LegacyPriceDataProviderAdapter(
        provider=legacy_provider,
        symbol=Symbol.parse("2330", market=Market.TWSE),
        provider_name="versioned-sample-csv",
        source_type=DataSourceType.LOCAL_FILE,
        provider_symbol="2330.TW",
        request_start="2024-01-02",
        request_end="2024-12-30",
        interval="1d",
    )

    result = adapter.load_price_result()

    assert result.data is not None
    assert_frame_equal(result.data.reset_index(drop=True), expected.reset_index(drop=True))
    assert result.metadata.requested_symbol == Symbol.parse("2330", market=Market.TWSE)
    assert result.metadata.resolved_symbol == Symbol.parse("2330.TW", market=Market.TWSE)
    assert result.metadata.provider_symbol == "2330.TW"
    assert result.metadata.source_type is DataSourceType.LOCAL_FILE
    assert result.warnings == ()
    assert result.attempts == (
        ProviderAttemptRecord("versioned-sample-csv", True, "legacy provider returned 260 rows"),
    )


@pytest.mark.parametrize(
    ("case", "source_type", "warnings", "attempts"),
    [
        (
            _versioned_market_cases()[0],
            "online",
            ("fixed fixture online response",),
            (ProviderAttempt("yfinance:2330.TW", True, "fixture returned 260 rows"),),
        ),
        (
            _versioned_market_cases()[1],
            "cache",
            ("cache fallback used after upstream timeout",),
            (
                ProviderAttempt("yfinance:6488.TWO", False, "HTTP 503: provider unavailable"),
                ProviderAttempt("cache:yfinance", True, "cache loaded 260 rows"),
            ),
        ),
        (
            _versioned_market_cases()[2],
            "online",
            ("fixed fixture online response",),
            (ProviderAttempt("yfinance:AAPL", True, "fixture returned 260 rows"),),
        ),
    ],
    ids=["twse", "tpex-fallback", "us"],
)
def test_versioned_fixture_legacy_fetch_result_matches_contract_adapter(
    case: dict[str, Any],
    source_type: str,
    warnings: tuple[str, ...],
    attempts: tuple[ProviderAttempt, ...],
) -> None:
    rows = _versioned_price_rows_for_symbol(case["input_symbol"])
    legacy_frame = pd.DataFrame(clean_price_data(rows).records, columns=STANDARD_COLUMNS)
    legacy = FetchResult(
        data=pd.DataFrame(rows, columns=STANDARD_COLUMNS),
        source="yfinance",
        symbol=case["input_symbol"],
        provider_symbol=case["query_symbol"],
        from_cache=source_type == "cache",
        cache_file=Path("data/cache/versioned_fixture.csv") if source_type == "cache" else None,
        market=case["market"],
        start_date="2024-01-02",
        end_date="2024-12-30",
        source_type=source_type,
        warnings=warnings,
        attempts=attempts,
    )
    original = legacy.data.copy(deep=True)

    result = adapt_legacy_fetch_result(legacy, interval="1d")

    expected_requested = Symbol.parse(case["input_symbol"], market=case["market"])
    expected_resolved = Symbol.parse(
        case["query_symbol"],
        market=Market.AUTO if "." in case["query_symbol"] else case["market"],
    )
    assert result.data is not None
    assert_frame_equal(result.data.reset_index(drop=True), legacy_frame.reset_index(drop=True))
    assert_frame_equal(legacy.data, original)
    assert result.metadata.requested_symbol == expected_requested
    assert result.metadata.resolved_symbol == expected_resolved
    assert result.metadata.provider_symbol == case["query_symbol"]
    assert result.metadata.request_start == "2024-01-02"
    assert result.metadata.request_end == "2024-12-30"
    assert result.metadata.source_type is DataSourceType.parse(source_type)
    assert result.warnings == warnings
    assert tuple((item.provider, item.success, item.reason) for item in result.attempts) == tuple(
        (item.provider, item.success, item.reason) for item in attempts
    )
    assert result.fallback_attempted is (len(attempts) > 1)
    assert result.used_fallback is (source_type == "cache")


def test_legacy_adapter_records_cross_market_resolution() -> None:
    legacy = _legacy_fetch_result(provider_symbol="3105.TWO", market="TWSE", source_type="online")
    legacy = replace(
        legacy,
        symbol="3105",
        attempts=(ProviderAttempt("yfinance:3105.TWO", True, "loaded 2 rows"),),
    )

    result = adapt_legacy_fetch_result(legacy)

    assert result.metadata.requested_symbol == Symbol.parse("3105", market="TWSE")
    assert result.metadata.resolved_symbol == Symbol.parse("3105.TWO", market="AUTO")
    assert result.metadata.resolved_symbol.market is Market.TPEX


def test_contract_wrapper_is_default_off_and_can_adapt_legacy_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ProviderContractDisabledError, match="尚未啟用"):
        fetch_prices_result("2330", market="TWSE")

    legacy = _legacy_fetch_result(source_type="online")
    monkeypatch.setattr(auto_fetch, "fetch_prices", lambda *args, **kwargs: legacy)

    result = fetch_prices_result("2330", market="TWSE", contracts_enabled=True)

    assert result.status is ProviderStatus.SUCCESS
    assert result.metadata.provider_symbol == "2330.TW"
    assert result.metadata.interval == "1d"


def test_legacy_file_provider_adapter_returns_new_contract(tmp_path: Path) -> None:
    csv_path = tmp_path / "prices.csv"
    _price_frame().to_csv(csv_path, index=False)
    adapter = LegacyPriceDataProviderAdapter(
        provider=CSVPriceDataProvider(csv_path),
        symbol=Symbol.parse("2330", market="TWSE"),
        provider_name="csv",
        source_type=DataSourceType.LOCAL_FILE,
    )

    result = adapter.load_price_result()

    assert result.status is ProviderStatus.SUCCESS
    assert result.metadata.provider == "csv"
    assert result.metadata.source_type is DataSourceType.LOCAL_FILE
    assert result.data is not None
    assert len(result.data) == 2


def test_legacy_file_provider_adapter_returns_structured_failure() -> None:
    class FailingProvider:
        def load_price_data(self) -> list[dict[str, Any]]:
            raise ValueError("token=secret-value")

    adapter = LegacyPriceDataProviderAdapter(
        provider=FailingProvider(),
        symbol=Symbol.parse("AAPL", market="US"),
        provider_name="failing-provider",
        source_type=DataSourceType.LOCAL_FILE,
    )

    result = adapter.load_price_result()

    assert result.status is ProviderStatus.ERROR
    assert result.data is None
    assert result.error is not None
    assert result.error.code is ProviderErrorCode.PROVIDER_FAILURE
    assert "secret-value" not in result.error.message
    assert result.error.message == "failing-provider provider 發生 ValueError。"
    assert result.attempts[0].success is False
    assert "secret-value" not in result.attempts[0].reason


def test_contract_metadata_and_quality_are_json_serializable() -> None:
    result = provider_result_from_price_frame(_price_frame(), metadata=_metadata())

    encoded = json.dumps(result.to_dict(), sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["status"] == "success"
    assert decoded["metadata"]["requested_symbol"] == {"code": "2330", "market": "TWSE"}
    assert decoded["quality"]["status"] == "valid"
    assert decoded["data_present"] is True


def test_metadata_rejects_reversed_date_range() -> None:
    symbol = Symbol.parse("AAPL", market="US")

    with pytest.raises(ValueError, match="request_start"):
        DataSourceMetadata(
            provider="yfinance",
            source_type=DataSourceType.ONLINE,
            requested_symbol=symbol,
            resolved_symbol=symbol,
            provider_symbol="AAPL",
            request_start="2024-02-01",
            request_end="2024-01-01",
        )
