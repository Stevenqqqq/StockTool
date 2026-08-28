"""Canonical provider result, metadata, and price quality contracts."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Iterable, TypeVar

import pandas as pd

from stock_tool.data.cleaner import PriceDataWarning, clean_price_data
from stock_tool.data.loader import REQUIRED_COLUMNS, STANDARD_COLUMNS
from stock_tool.domain.models import Market, Symbol

if TYPE_CHECKING:
    from stock_tool.data.auto_fetch import FetchResult

T = TypeVar("T")

_REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_QUERY_PARAMETER = re.compile(
    r"(?P<prefix>[?&][^=&\s#]*(?:token|api(?:[\s_-]*key)|authorization|password|secret)"
    r"[^=&\s#]*=)(?P<value>[^&#\s,;)}]+)",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?P<key>[\"']?(?:[A-Za-z0-9_.-]*(?:token|authorization|password|secret)"
    r"[A-Za-z0-9_.-]*|[A-Za-z0-9_.-]*api(?:[\s_-]*key)[A-Za-z0-9_.-]*)[\"']?)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<value>\"(?:Bearer\s+)?[^\"]*\"|'(?:Bearer\s+)?[^']*'|"
    r"(?:Bearer\s+)?[^\s,;)&}]+)",
    re.IGNORECASE,
)
_BEARER_TOKEN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def sanitize_provider_text(value: object) -> str:
    """Redact common credential values from provider text exposed to users.

    Provider warnings, fallback reasons, and exception messages originate outside
    the application boundary. This helper preserves non-sensitive diagnostics
    while replacing token, API key, authorization, password, secret, and URL
    query parameter values with a stable marker.
    """

    if value is None:
        return ""
    text = str(value)
    text = _SENSITIVE_QUERY_PARAMETER.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED_VALUE}",
        text,
    )
    text = _SENSITIVE_ASSIGNMENT.sub(_redact_assignment_value, text)
    return _BEARER_TOKEN.sub(f"Bearer {_REDACTED_VALUE}", text)


def _redact_assignment_value(match: re.Match[str]) -> str:
    """Keep assignment syntax while replacing the matched sensitive value."""

    value = match.group("value")
    quote = value[0] if value[:1] in {"'", '"'} and value.endswith(value[:1]) else ""
    return f"{match.group('key')}{match.group('separator')}{quote}{_REDACTED_VALUE}{quote}"


class DataSourceType(str, Enum):
    """How a provider payload entered the application."""

    ONLINE = "online"
    CACHE = "cache"
    LOCAL_FILE = "local_file"
    USER_UPLOAD = "user_upload"
    SAMPLE = "sample"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: DataSourceType | str) -> DataSourceType:
        """Normalize legacy source labels without guessing provenance."""

        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower()
        aliases = {
            "online": cls.ONLINE,
            "cache": cls.CACHE,
            "local": cls.LOCAL_FILE,
            "local_file": cls.LOCAL_FILE,
            "csv": cls.LOCAL_FILE,
            "excel": cls.LOCAL_FILE,
            "upload": cls.USER_UPLOAD,
            "user_upload": cls.USER_UPLOAD,
            "sample": cls.SAMPLE,
        }
        return aliases.get(normalized, cls.UNKNOWN)


class ProviderStatus(str, Enum):
    """Outcome of one provider request after validation."""

    SUCCESS = "success"
    PARTIAL = "partial"
    EMPTY = "empty"
    ERROR = "error"


class ProviderErrorCode(str, Enum):
    """Stable error categories for provider orchestration and UI recovery."""

    EMPTY_DATASET = "empty_dataset"
    SCHEMA_MISMATCH = "schema_mismatch"
    VALIDATION_FAILED = "validation_failed"
    PROVIDER_FAILURE = "provider_failure"


class QualityStatus(str, Enum):
    """Overall usability of a provider payload."""

    NOT_EVALUATED = "not_evaluated"
    EMPTY = "empty"
    VALID = "valid"
    PARTIAL = "partial"
    INVALID = "invalid"


class QualitySeverity(str, Enum):
    """Severity of one quality issue."""

    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DataSourceMetadata:
    """Provider provenance attached to one normalized payload."""

    provider: str
    source_type: DataSourceType
    requested_symbol: Symbol
    resolved_symbol: Symbol
    provider_symbol: str
    request_start: str | None = None
    request_end: str | None = None
    interval: str | None = None
    cache_path: str | None = None
    fetched_at: str | None = None
    last_data_date: str | None = None
    cache_state: str | None = None
    cache_age_seconds: float | None = None
    point_in_time_universe: str | None = None

    def __post_init__(self) -> None:
        provider = str(self.provider).strip()
        provider_symbol = str(self.provider_symbol).strip().upper()
        if not provider:
            raise ValueError("DataSourceMetadata.provider 不可為空。")
        if not provider_symbol:
            raise ValueError("DataSourceMetadata.provider_symbol 不可為空。")
        if not isinstance(self.requested_symbol, Symbol):
            raise TypeError("requested_symbol 必須是 Symbol。")
        if not isinstance(self.resolved_symbol, Symbol):
            raise TypeError("resolved_symbol 必須是 Symbol。")

        start = _parse_iso_date(self.request_start, field="request_start")
        end = _parse_iso_date(self.request_end, field="request_end")
        if start is not None and end is not None and start > end:
            raise ValueError("request_start 不可晚於 request_end。")

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "source_type", DataSourceType.parse(self.source_type))
        object.__setattr__(self, "provider_symbol", provider_symbol)
        object.__setattr__(self, "request_start", start.isoformat() if start else None)
        object.__setattr__(self, "request_end", end.isoformat() if end else None)
        object.__setattr__(self, "interval", _optional_text(self.interval))
        object.__setattr__(self, "cache_path", _optional_text(self.cache_path))
        object.__setattr__(self, "fetched_at", _optional_text(self.fetched_at))
        object.__setattr__(self, "last_data_date", _optional_text(self.last_data_date))
        object.__setattr__(self, "cache_state", _optional_text(self.cache_state))
        if self.cache_age_seconds is not None and self.cache_age_seconds < 0:
            raise ValueError("cache_age_seconds 不可為負數。")
        object.__setattr__(
            self,
            "point_in_time_universe",
            _optional_text(self.point_in_time_universe),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize provider provenance without raw market data."""

        return {
            "provider": self.provider,
            "source_type": self.source_type.value,
            "requested_symbol": self.requested_symbol.to_dict(),
            "resolved_symbol": self.resolved_symbol.to_dict(),
            "provider_symbol": self.provider_symbol,
            "request_start": self.request_start,
            "request_end": self.request_end,
            "interval": self.interval,
            "cache_path": self.cache_path,
            "fetched_at": self.fetched_at,
            "last_data_date": self.last_data_date,
            "cache_state": self.cache_state,
            "cache_age_seconds": self.cache_age_seconds,
            "point_in_time_universe": self.point_in_time_universe,
        }


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One structured validation or schema issue."""

    severity: QualitySeverity
    code: str
    message: str
    row_index: int | None = None
    symbol: str | None = None
    date: str | None = None

    def __post_init__(self) -> None:
        """Keep validation messages safe if an external provider supplied text."""

        object.__setattr__(self, "message", sanitize_provider_text(self.message))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the issue for reports and logs."""

        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "row_index": self.row_index,
            "symbol": self.symbol,
            "date": self.date,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Immutable summary of schema checks and canonical cleaner output."""

    status: QualityStatus
    input_rows: int
    output_rows: int
    missing_required_columns: tuple[str, ...] = ()
    missing_optional_columns: tuple[str, ...] = ()
    duplicate_columns: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()
    null_counts: tuple[tuple[str, int], ...] = ()
    issues: tuple[QualityIssue, ...] = ()

    @property
    def is_usable(self) -> bool:
        """Return whether validated rows are available to downstream code."""

        return self.status in {QualityStatus.VALID, QualityStatus.PARTIAL} and self.output_rows > 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report using JSON-compatible values."""

        return {
            "status": self.status.value,
            "input_rows": self.input_rows,
            "output_rows": self.output_rows,
            "missing_required_columns": list(self.missing_required_columns),
            "missing_optional_columns": list(self.missing_optional_columns),
            "duplicate_columns": list(self.duplicate_columns),
            "extra_columns": list(self.extra_columns),
            "null_counts": dict(self.null_counts),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class ProviderError:
    """Structured provider failure safe for orchestration and user messaging."""

    code: ProviderErrorCode
    message: str
    provider: str
    retryable: bool = False

    def __post_init__(self) -> None:
        """Ensure user-visible provider failures never include raw credentials."""

        object.__setattr__(self, "message", sanitize_provider_text(self.message))
        object.__setattr__(self, "provider", sanitize_provider_text(self.provider))

    def to_dict(self) -> dict[str, Any]:
        """Serialize a provider error."""

        return {
            "code": self.code.value,
            "message": self.message,
            "provider": self.provider,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class ProviderAttemptRecord:
    """One normalized provider or fallback attempt."""

    provider: str
    success: bool
    reason: str

    def __post_init__(self) -> None:
        """Ensure fallback diagnostics use the contract redaction policy."""

        object.__setattr__(self, "provider", sanitize_provider_text(self.provider))
        object.__setattr__(self, "reason", sanitize_provider_text(self.reason))

    def to_dict(self) -> dict[str, Any]:
        """Serialize an attempt without provider-specific objects."""

        return {
            "provider": self.provider,
            "success": self.success,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    """Validated provider payload with provenance, quality, and fallback history."""

    status: ProviderStatus
    data: T | None
    metadata: DataSourceMetadata
    quality: QualityReport
    warnings: tuple[str, ...] = ()
    attempts: tuple[ProviderAttemptRecord, ...] = ()
    error: ProviderError | None = None

    def __post_init__(self) -> None:
        if self.status in {ProviderStatus.SUCCESS, ProviderStatus.PARTIAL}:
            if self.data is None:
                raise ValueError("成功或部分成功的 ProviderResult 必須包含 data。")
            if self.error is not None:
                raise ValueError("成功或部分成功的 ProviderResult 不可包含 error。")
        elif self.data is not None or self.error is None:
            raise ValueError("空資料或失敗的 ProviderResult 必須只有 error，不可包含 data。")

        if isinstance(self.data, pd.DataFrame):
            object.__setattr__(self, "data", self.data.copy(deep=True))
        object.__setattr__(
            self,
            "warnings",
            tuple(sanitize_provider_text(item) for item in self.warnings),
        )
        object.__setattr__(self, "attempts", tuple(self.attempts))

    @property
    def succeeded(self) -> bool:
        """Return whether at least some validated data is available."""

        return self.status in {ProviderStatus.SUCCESS, ProviderStatus.PARTIAL}

    @property
    def fallback_attempted(self) -> bool:
        """Return whether more than one provider/source attempt was recorded."""

        return len(self.attempts) > 1

    @property
    def used_fallback(self) -> bool:
        """Return whether a success occurred after an earlier failed attempt."""

        if not self.succeeded:
            return False
        for index, attempt in enumerate(self.attempts):
            if attempt.success:
                return any(not earlier.success for earlier in self.attempts[:index])
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize contract metadata without embedding the raw payload."""

        row_count = len(self.data) if self.data is not None and hasattr(self.data, "__len__") else 0
        return {
            "status": self.status.value,
            "data_present": self.data is not None,
            "row_count": row_count,
            "metadata": self.metadata.to_dict(),
            "quality": self.quality.to_dict(),
            "warnings": list(self.warnings),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "error": self.error.to_dict() if self.error is not None else None,
        }


def provider_result_from_price_frame(
    frame: pd.DataFrame,
    *,
    metadata: DataSourceMetadata,
    warnings: Iterable[str] = (),
    attempts: Iterable[ProviderAttemptRecord] = (),
) -> ProviderResult[pd.DataFrame]:
    """Validate an untrusted price frame and return the canonical contract."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("price provider data 必須是 pandas DataFrame。")
    cleaned_frame, quality = _validate_price_frame(frame)
    normalized_attempts = tuple(attempts)
    normalized_warnings = tuple(warnings)

    if quality.status is QualityStatus.EMPTY:
        return ProviderResult(
            status=ProviderStatus.EMPTY,
            data=None,
            metadata=metadata,
            quality=quality,
            warnings=normalized_warnings,
            attempts=normalized_attempts,
            error=ProviderError(
                code=ProviderErrorCode.EMPTY_DATASET,
                message="Provider 沒有回傳資料列。",
                provider=metadata.provider,
            ),
        )
    if quality.status is QualityStatus.INVALID:
        code = (
            ProviderErrorCode.SCHEMA_MISMATCH
            if quality.missing_required_columns or quality.duplicate_columns
            else ProviderErrorCode.VALIDATION_FAILED
        )
        return ProviderResult(
            status=ProviderStatus.ERROR,
            data=None,
            metadata=metadata,
            quality=quality,
            warnings=normalized_warnings,
            attempts=normalized_attempts,
            error=ProviderError(
                code=code,
                message="Provider 資料未通過標準 OHLCV 驗證。",
                provider=metadata.provider,
            ),
        )

    status = (
        ProviderStatus.SUCCESS if quality.status is QualityStatus.VALID else ProviderStatus.PARTIAL
    )
    return ProviderResult(
        status=status,
        data=cleaned_frame,
        metadata=metadata,
        quality=quality,
        warnings=normalized_warnings,
        attempts=normalized_attempts,
    )


def provider_failure_result(
    *,
    metadata: DataSourceMetadata,
    message: str,
    attempts: Iterable[ProviderAttemptRecord] = (),
    retryable: bool = False,
) -> ProviderResult[pd.DataFrame]:
    """Return a structured failure when a legacy provider raises an exception."""

    quality = QualityReport(
        status=QualityStatus.NOT_EVALUATED,
        input_rows=0,
        output_rows=0,
    )
    return ProviderResult(
        status=ProviderStatus.ERROR,
        data=None,
        metadata=metadata,
        quality=quality,
        attempts=tuple(attempts),
        error=ProviderError(
            code=ProviderErrorCode.PROVIDER_FAILURE,
            message=message,
            provider=metadata.provider,
            retryable=retryable,
        ),
    )


def adapt_legacy_fetch_result(
    result: FetchResult,
    *,
    interval: str | None = None,
) -> ProviderResult[pd.DataFrame]:
    """Wrap the existing ``FetchResult`` without changing its public behavior."""

    selected_market = Market.parse(result.market)
    requested_symbol = Symbol.parse(str(result.symbol), market=selected_market)
    resolved_symbol = _resolved_provider_symbol(
        str(result.provider_symbol),
        fallback_market=requested_symbol.market,
    )
    metadata = DataSourceMetadata(
        provider=str(result.source),
        source_type=DataSourceType.parse(result.source_type),
        requested_symbol=requested_symbol,
        resolved_symbol=resolved_symbol,
        provider_symbol=str(result.provider_symbol),
        request_start=str(result.start_date),
        request_end=str(result.end_date),
        interval=interval,
        cache_path=str(result.cache_file) if result.cache_file is not None else None,
        fetched_at=getattr(result, "fetched_at", None),
        last_data_date=getattr(result, "last_data_date", None),
        cache_state=getattr(result, "cache_state", None),
        cache_age_seconds=getattr(result, "cache_age_seconds", None),
        point_in_time_universe=getattr(result, "point_in_time_universe", None),
    )
    attempts = tuple(
        ProviderAttemptRecord(
            provider=str(attempt.provider),
            success=bool(attempt.success),
            reason=str(attempt.reason),
        )
        for attempt in result.attempts
    )
    return provider_result_from_price_frame(
        result.data,
        metadata=metadata,
        warnings=result.warnings,
        attempts=attempts,
    )


def _validate_price_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    source = frame.copy(deep=True)
    input_rows = len(source)
    source_columns = tuple(str(column) for column in source.columns)
    missing_required = tuple(column for column in REQUIRED_COLUMNS if column not in source.columns)
    optional_columns = tuple(
        column for column in STANDARD_COLUMNS if column not in REQUIRED_COLUMNS
    )
    missing_optional = tuple(column for column in optional_columns if column not in source.columns)
    duplicate_columns = tuple(
        dict.fromkeys(
            str(column) for column in source.columns[source.columns.duplicated(keep=False)]
        )
    )
    extra_columns = tuple(
        sorted(column for column in source_columns if column not in STANDARD_COLUMNS)
    )
    null_counts = tuple(
        (
            column,
            (
                input_rows
                if column not in source.columns or column in duplicate_columns
                else int(source[column].isna().sum())
            ),
        )
        for column in STANDARD_COLUMNS
    )
    issues: list[QualityIssue] = []

    if duplicate_columns:
        issues.append(
            QualityIssue(
                severity=QualitySeverity.ERROR,
                code="duplicate_columns",
                message=f"Provider 回傳重複欄位：{', '.join(duplicate_columns)}。",
            )
        )
        return _empty_price_frame(), QualityReport(
            status=QualityStatus.INVALID,
            input_rows=input_rows,
            output_rows=0,
            missing_required_columns=missing_required,
            missing_optional_columns=missing_optional,
            duplicate_columns=duplicate_columns,
            extra_columns=extra_columns,
            null_counts=null_counts,
            issues=tuple(issues),
        )

    if input_rows == 0:
        return _empty_price_frame(), QualityReport(
            status=QualityStatus.EMPTY,
            input_rows=0,
            output_rows=0,
            missing_required_columns=missing_required,
            missing_optional_columns=missing_optional,
            duplicate_columns=duplicate_columns,
            extra_columns=extra_columns,
            null_counts=null_counts,
        )

    if missing_required:
        issues.append(
            QualityIssue(
                severity=QualitySeverity.ERROR,
                code="missing_required_columns",
                message=f"缺少必要欄位：{', '.join(missing_required)}。",
            )
        )
        return _empty_price_frame(), QualityReport(
            status=QualityStatus.INVALID,
            input_rows=input_rows,
            output_rows=0,
            missing_required_columns=missing_required,
            missing_optional_columns=missing_optional,
            duplicate_columns=duplicate_columns,
            extra_columns=extra_columns,
            null_counts=null_counts,
            issues=tuple(issues),
        )

    if missing_optional:
        issues.append(
            QualityIssue(
                severity=QualitySeverity.WARNING,
                code="missing_optional_columns",
                message=f"缺少選用欄位：{', '.join(missing_optional)}。不會填入假資料。",
            )
        )
    if extra_columns:
        issues.append(
            QualityIssue(
                severity=QualitySeverity.WARNING,
                code="extra_columns",
                message=f"偵測到 provider 額外欄位：{', '.join(extra_columns)}。",
            )
        )

    adjusted_nulls = dict(null_counts).get("adjusted_close", 0)
    if adjusted_nulls and not missing_optional:
        issues.append(
            QualityIssue(
                severity=QualitySeverity.WARNING,
                code="missing_optional_values",
                message=f"adjusted_close 有 {adjusted_nulls} 筆缺值；缺值保持空白。",
            )
        )

    working = source.copy(deep=True)
    for column in missing_optional:
        working[column] = None
    standard_records = working.loc[:, list(STANDARD_COLUMNS)].to_dict("records")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PriceDataWarning)
        cleaned = clean_price_data(standard_records, fail_on_errors=False)

    for issue in (*cleaned.warnings, *cleaned.errors):
        issues.append(
            QualityIssue(
                severity=QualitySeverity(issue.severity),
                code=issue.code,
                message=issue.message,
                row_index=issue.row_index,
                symbol=issue.symbol,
                date=issue.date,
            )
        )

    cleaned_frame = pd.DataFrame(cleaned.records, columns=STANDARD_COLUMNS)
    output_rows = len(cleaned_frame)
    if output_rows == 0:
        issues.append(
            QualityIssue(
                severity=QualitySeverity.ERROR,
                code="no_usable_rows",
                message="資料清洗後沒有可用 OHLCV 資料列。",
            )
        )
        status = QualityStatus.INVALID
    elif output_rows != input_rows or issues:
        status = QualityStatus.PARTIAL
    else:
        status = QualityStatus.VALID

    return cleaned_frame, QualityReport(
        status=status,
        input_rows=input_rows,
        output_rows=output_rows,
        missing_required_columns=missing_required,
        missing_optional_columns=missing_optional,
        duplicate_columns=duplicate_columns,
        extra_columns=extra_columns,
        null_counts=null_counts,
        issues=tuple(issues),
    )


def _resolved_provider_symbol(provider_symbol: str, *, fallback_market: Market) -> Symbol:
    value = str(provider_symbol).strip().upper()
    if value.endswith((".TW", ".TWO")):
        return Symbol.parse(value, market=Market.AUTO)
    return Symbol.parse(value, market=fallback_market)


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def _parse_iso_date(value: str | None, *, field: str) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field} 必須是 YYYY-MM-DD 日期。") from exc


def _optional_text(value: str | Path | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
