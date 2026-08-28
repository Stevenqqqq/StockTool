"""Serializable, data-free application results for the research workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping

import pandas as pd

from stock_tool.data.contracts import (
    DataSourceMetadata,
    ProviderAttemptRecord,
    ProviderError,
    ProviderStatus,
    QualityReport,
    sanitize_provider_text,
)
from stock_tool.domain.models import MissingData, Symbol
from stock_tool.stock_scoring import StockScoreResult


@dataclass(frozen=True, slots=True)
class DataHydrationRequest:
    """Canonical, provider-independent input for one price-data hydration request."""

    symbol: Symbol
    start_date: str
    end_date: str
    interval: str | None = None

    def __post_init__(self) -> None:
        """Validate canonical identity and an inclusive ISO date range."""

        if not isinstance(self.symbol, Symbol):
            raise TypeError("DataHydrationRequest.symbol must be a Symbol.")
        start = _parse_request_date(self.start_date, field="start_date")
        end = _parse_request_date(self.end_date, field="end_date")
        if start > end:
            raise ValueError("DataHydrationRequest.start_date must not be after end_date.")
        interval = str(self.interval).strip() if self.interval is not None else None
        object.__setattr__(self, "start_date", start.isoformat())
        object.__setattr__(self, "end_date", end.isoformat())
        object.__setattr__(self, "interval", interval or None)

    def to_dict(self) -> dict[str, Any]:
        """Serialize only non-sensitive, provider-neutral query inputs."""

        return {
            "symbol": self.symbol.to_dict(),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "interval": self.interval,
        }


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Formal input boundary for one complete analysis use case."""

    data_request: DataHydrationRequest
    include_fundamentals: bool = True

    def __post_init__(self) -> None:
        """Keep the request immutable and explicit about optional analysis scope."""

        if not isinstance(self.data_request, DataHydrationRequest):
            raise TypeError("AnalysisRequest.data_request must be a DataHydrationRequest.")
        object.__setattr__(self, "include_fundamentals", bool(self.include_fundamentals))

    def to_dict(self) -> dict[str, Any]:
        """Serialize application-level inputs without provider-specific ticker rules."""

        return {
            "data_request": self.data_request.to_dict(),
            "include_fundamentals": self.include_fundamentals,
        }


class AnalysisStatus(str, Enum):
    """Explicit lifecycle state for an orchestrated research analysis."""

    SUCCESS = "success"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HydrationMetadata:
    """Traceable, secret-safe lineage for one price-data ingestion run."""

    run_id: str
    started_at: str
    completed_at: str
    source: DataSourceMetadata
    cache_hit: bool
    status: ProviderStatus
    input_rows: int
    output_rows: int
    last_data_date: str | None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    attempts: tuple[ProviderAttemptRecord, ...] = ()
    ingestion_persisted: bool = False

    def __post_init__(self) -> None:
        """Normalize externally supplied diagnostics at the application boundary."""

        object.__setattr__(self, "run_id", str(self.run_id).strip())
        object.__setattr__(self, "started_at", str(self.started_at).strip())
        object.__setattr__(self, "completed_at", str(self.completed_at).strip())
        object.__setattr__(
            self,
            "warnings",
            tuple(sanitize_provider_text(item) for item in self.warnings),
        )
        object.__setattr__(
            self,
            "errors",
            tuple(sanitize_provider_text(item) for item in self.errors),
        )
        object.__setattr__(self, "attempts", tuple(self.attempts))
        if not self.run_id:
            raise ValueError("HydrationMetadata.run_id must not be empty.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize lineage without raw rows, provider objects, or secrets."""

        source = _sanitize_payload(self.source.to_dict())
        source.update(
            {
                "run_id": self.run_id,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "cache_hit": self.cache_hit,
                "status": self.status.value,
                "input_rows": self.input_rows,
                "output_rows": self.output_rows,
                "last_data_date": self.last_data_date,
                "ingestion_persisted": self.ingestion_persisted,
            }
        )
        return source

    def to_storage_record(self, *, quality: QualityReport) -> dict[str, Any]:
        """Return the compact, redacted record persisted by ``SQLitePriceStorage``."""

        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "requested_symbol": self.source.requested_symbol.to_dict(),
            "resolved_symbol": self.source.resolved_symbol.to_dict(),
            "provider_symbol": sanitize_provider_text(self.source.provider_symbol),
            "provider": sanitize_provider_text(self.source.provider),
            "source_type": self.source.source_type.value,
            "request_start": self.source.request_start,
            "request_end": self.source.request_end,
            "cache_hit": self.cache_hit,
            "status": self.status.value,
            "input_rows": self.input_rows,
            "output_rows": self.output_rows,
            "quality_summary": _sanitize_payload(quality.to_dict()),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "attempts": [_sanitize_payload(attempt.to_dict()) for attempt in self.attempts],
            "last_data_date": self.last_data_date,
        }


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    """Validated price data and lineage returned by ``DataHydrationService``."""

    symbol: Symbol
    status: ProviderStatus
    data: pd.DataFrame | None
    metadata: HydrationMetadata
    quality: QualityReport
    warnings: tuple[str, ...] = ()
    attempts: tuple[ProviderAttemptRecord, ...] = ()
    error: ProviderError | None = None
    missing_data: tuple[MissingData, ...] = ()
    is_stale: bool = False
    request: DataHydrationRequest | None = None

    def __post_init__(self) -> None:
        """Keep the service boundary immutable to callers and downstream modules."""

        if self.data is not None:
            object.__setattr__(self, "data", self.data.copy(deep=True))
        object.__setattr__(
            self,
            "warnings",
            tuple(sanitize_provider_text(item) for item in self.warnings),
        )
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "missing_data", tuple(self.missing_data))

    @property
    def has_usable_data(self) -> bool:
        """Return whether a validated frame is available for analysis."""

        return (
            self.status in {ProviderStatus.SUCCESS, ProviderStatus.PARTIAL}
            and self.data is not None
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize data state and provenance without embedding the DataFrame."""

        return {
            "symbol": self.symbol.to_dict(),
            "status": self.status.value,
            "data_present": self.data is not None,
            "row_count": 0 if self.data is None else len(self.data),
            "metadata": self.metadata.to_dict(),
            "quality": self.quality.to_dict(),
            "warnings": list(self.warnings),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "error": self.error.to_dict() if self.error is not None else None,
            "missing_data": [item.to_dict() for item in self.missing_data],
            "is_stale": self.is_stale,
            "request": self.request.to_dict() if self.request is not None else None,
        }


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Service-level analysis result with explicit availability and limitations."""

    symbol: Symbol
    status: AnalysisStatus
    hydration: DataSnapshot
    indicators: pd.DataFrame | None = None
    fundamental_scores: pd.DataFrame | None = None
    stock_score: StockScoreResult | None = None
    missing_data: tuple[MissingData, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    request: AnalysisRequest | None = None

    def __post_init__(self) -> None:
        """Prevent consumers from mutating analysis frames held by the result."""

        if self.indicators is not None:
            object.__setattr__(self, "indicators", self.indicators.copy(deep=True))
        if self.fundamental_scores is not None:
            object.__setattr__(self, "fundamental_scores", self.fundamental_scores.copy(deep=True))
        object.__setattr__(self, "missing_data", tuple(self.missing_data))
        object.__setattr__(
            self,
            "warnings",
            tuple(sanitize_provider_text(item) for item in self.warnings),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(sanitize_provider_text(item) for item in self.limitations),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize research state without raw price, indicator, or fundamental frames."""

        return {
            "symbol": self.symbol.to_dict(),
            "status": self.status.value,
            "hydration": self.hydration.to_dict(),
            "indicators_present": self.indicators is not None,
            "fundamental_scores_present": self.fundamental_scores is not None,
            "stock_score": _serialize_stock_score(self.stock_score),
            "missing_data": [item.to_dict() for item in self.missing_data],
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "request": self.request.to_dict() if self.request is not None else None,
        }


def _serialize_stock_score(score: StockScoreResult | None) -> dict[str, Any] | None:
    """Convert the existing score dataclass into report-safe primitive values."""

    if score is None:
        return None
    return {
        "symbol": score.symbol,
        "total_score": score.total_score,
        "available_score": score.available_score,
        "coverage": score.coverage,
        "technical_score": score.technical_score,
        "fundamental_score": score.fundamental_score,
        "valuation_score": score.valuation_score,
        "risk_score": score.risk_score,
        "rating_label": score.rating_label,
        "summary": list(score.summary),
        "strengths": list(score.strengths),
        "weaknesses": list(score.weaknesses),
        "strategy_health": list(score.strategy_health),
        "missing_data": list(score.missing_data),
        "risk_notes": list(score.risk_notes),
        "components": [
            {
                "name": component.name,
                "score": component.score,
                "weight": component.weight,
                "reasons": list(component.reasons),
                "missing_data": list(component.missing_data),
            }
            for component in score.components
        ],
    }


def _sanitize_payload(value: Any) -> Any:
    """Recursively apply the provider redaction policy to persisted metadata."""

    if isinstance(value, str):
        return sanitize_provider_text(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_payload(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_sanitize_payload(item) for item in value]
    return value


def _parse_request_date(value: str, *, field: str) -> date:
    """Parse one required ISO date at the application boundary."""

    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"DataHydrationRequest.{field} must be an ISO date.") from exc
