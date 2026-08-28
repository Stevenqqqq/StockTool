"""Orchestration service for request-bound provider hydration and lineage storage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Callable, Protocol
from uuid import uuid4

import pandas as pd

from stock_tool.application.results import (
    DataHydrationRequest,
    DataSnapshot,
    HydrationMetadata,
)
from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    ProviderAttemptRecord,
    ProviderResult,
    ProviderStatus,
    provider_failure_result,
    sanitize_provider_text,
)
from stock_tool.data.providers import ContractPriceDataProvider
from stock_tool.data.storage import SQLitePriceStorage
from stock_tool.domain.models import Market, MissingData, MissingDataState, Symbol

LOGGER = logging.getLogger(__name__)


class ContractPriceDataProviderResolver(Protocol):
    """Resolve a contract provider from a canonical application request."""

    def resolve(self, request: DataHydrationRequest) -> ContractPriceDataProvider:
        """Return a provider configured for the given request without exposing ticker rules."""


@dataclass(slots=True)
class DataHydrationService:
    """Coordinate request-aware providers, SQLite storage, and safe ingestion lineage.

    ``hydrate(request)`` is the formal application boundary. The optional
    pre-bound ``provider`` remains only for transitional callers that have not
    migrated to a resolver yet; it is not used by new request-bound tests or UI.
    """

    provider: ContractPriceDataProvider | None = None
    provider_resolver: ContractPriceDataProviderResolver | None = None
    storage: SQLitePriceStorage | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    run_id_factory: Callable[[], str] = lambda: str(uuid4())
    as_of_date: str | None = None
    stale_after_days: int | None = None

    def hydrate(self, request: DataHydrationRequest | None = None) -> DataSnapshot:
        """Load validated data and retain secret-safe lineage for one application request."""

        started_at = _as_utc(self.clock())
        result = self._load_provider_result(request)
        completed_at = _as_utc(self.clock())
        data = _copy_result_data(result)
        last_data_date = _last_data_date(data)
        is_stale = _is_stale(
            last_data_date,
            as_of_date=self.as_of_date,
            stale_after_days=self.stale_after_days,
        )
        warnings = list(result.warnings)
        errors = [result.error.message] if result.error is not None else []
        missing_data = _missing_data_for_result(result, is_stale=is_stale)

        if self.storage is not None and data is not None:
            try:
                self.storage.save_price_data(data.to_dict(orient="records"))
            except Exception as exc:
                warning = _persistence_warning("price persistence", exc)
                warnings.append(warning)
                LOGGER.warning("%s", warning)

        metadata = HydrationMetadata(
            run_id=str(self.run_id_factory()),
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            source=result.metadata,
            cache_hit=result.metadata.source_type is DataSourceType.CACHE,
            status=result.status,
            input_rows=result.quality.input_rows,
            output_rows=result.quality.output_rows,
            last_data_date=last_data_date,
            warnings=tuple(warnings),
            errors=tuple(errors),
            attempts=result.attempts,
        )

        if self.storage is not None:
            try:
                self.storage.record_ingestion_run(
                    metadata.to_storage_record(quality=result.quality)
                )
                metadata = replace(metadata, ingestion_persisted=True)
            except Exception as exc:
                warning = _persistence_warning("ingestion metadata persistence", exc)
                warnings.append(warning)
                LOGGER.warning("%s", warning)
                metadata = replace(metadata, warnings=tuple(warnings), ingestion_persisted=False)

        return DataSnapshot(
            symbol=result.metadata.resolved_symbol,
            status=result.status,
            data=data,
            metadata=metadata,
            quality=result.quality,
            warnings=tuple(warnings),
            attempts=result.attempts,
            error=result.error,
            missing_data=missing_data,
            is_stale=is_stale,
            request=request,
        )

    def _load_provider_result(
        self,
        request: DataHydrationRequest | None,
    ) -> ProviderResult[pd.DataFrame]:
        """Resolve and call a provider without allowing external exceptions to escape."""

        try:
            provider = self._resolve_provider(request)
            result = provider.load_price_result()
        except Exception as exc:
            safe_detail = sanitize_provider_text(str(exc))
            LOGGER.warning("Contract provider execution failed safely: %s", safe_detail)
            return provider_failure_result(
                metadata=_request_metadata(request),
                message="Unable to retrieve validated price data from the configured provider.",
                attempts=(
                    ProviderAttemptRecord(
                        provider="application",
                        success=False,
                        reason="provider execution failed",
                    ),
                ),
            )

        if request is None or _metadata_matches_request(result.metadata, request):
            return result

        LOGGER.warning("Provider result metadata did not match the canonical application request.")
        return provider_failure_result(
            metadata=_request_metadata(
                request,
                provider=result.metadata.provider,
                source_type=result.metadata.source_type,
            ),
            message="Provider result metadata did not match the canonical application request.",
            attempts=(
                *result.attempts,
                ProviderAttemptRecord(
                    provider="application",
                    success=False,
                    reason="provider result metadata did not match the application request",
                ),
            ),
        )

    def _resolve_provider(
        self,
        request: DataHydrationRequest | None,
    ) -> ContractPriceDataProvider:
        """Resolve request-bound providers while retaining the temporary legacy adapter path."""

        if request is not None and self.provider_resolver is not None:
            return self.provider_resolver.resolve(request)
        if self.provider is not None:
            return self.provider
        if request is None:
            raise RuntimeError("A provider or a request-aware provider resolver is required.")
        raise RuntimeError("No provider resolver was configured for the application request.")


def _request_metadata(
    request: DataHydrationRequest | None,
    *,
    provider: str = "application",
    source_type: DataSourceType = DataSourceType.UNKNOWN,
) -> DataSourceMetadata:
    """Build safe fallback provenance when a provider cannot produce its own contract."""

    if request is None:
        symbol = Symbol(code="UNKNOWN", market=Market.CUSTOM)
        return DataSourceMetadata(
            provider=sanitize_provider_text(provider),
            source_type=source_type,
            requested_symbol=symbol,
            resolved_symbol=symbol,
            provider_symbol=symbol.code,
        )
    return DataSourceMetadata(
        provider=sanitize_provider_text(provider),
        source_type=source_type,
        requested_symbol=request.symbol,
        resolved_symbol=request.symbol,
        provider_symbol=request.symbol.code,
        request_start=request.start_date,
        request_end=request.end_date,
        interval=request.interval,
    )


def _metadata_matches_request(metadata: DataSourceMetadata, request: DataHydrationRequest) -> bool:
    """Require provider provenance to agree with the canonical application request."""

    if metadata.requested_symbol != request.symbol or metadata.resolved_symbol != request.symbol:
        return False
    if metadata.request_start != request.start_date or metadata.request_end != request.end_date:
        return False
    return request.interval is None or metadata.interval == request.interval


def _copy_result_data(result: ProviderResult[pd.DataFrame]) -> pd.DataFrame | None:
    """Return a private copy only for successful or partial contract results."""

    if not result.succeeded or result.data is None:
        return None
    return result.data.copy(deep=True)


def _last_data_date(data: pd.DataFrame | None) -> str | None:
    """Return the latest canonical data date without inferring values."""

    if data is None or data.empty or "date" not in data.columns:
        return None
    dates = pd.to_datetime(data["date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date().isoformat()


def _is_stale(
    last_data_date: str | None,
    *,
    as_of_date: str | None,
    stale_after_days: int | None,
) -> bool:
    """Return freshness state only when a caller explicitly configured a policy."""

    if last_data_date is None or as_of_date is None or stale_after_days is None:
        return False
    if stale_after_days < 0:
        raise ValueError("stale_after_days must be zero or positive.")
    latest = date.fromisoformat(last_data_date)
    as_of = date.fromisoformat(as_of_date)
    return latest < as_of - timedelta(days=stale_after_days)


def _missing_data_for_result(
    result: ProviderResult[pd.DataFrame],
    *,
    is_stale: bool,
) -> tuple[MissingData, ...]:
    """Represent unavailable and stale data with canonical domain states."""

    missing: list[MissingData] = []
    if result.status is ProviderStatus.ERROR:
        missing.append(
            MissingData(
                field="price_data",
                state=MissingDataState.UNKNOWN,
                reason="The provider failed before validated price data was available.",
            )
        )
    elif result.status is ProviderStatus.EMPTY:
        missing.append(
            MissingData(
                field="price_data",
                state=MissingDataState.MISSING,
                reason="The provider returned no validated price rows for the requested period.",
            )
        )
    elif result.status is ProviderStatus.PARTIAL:
        missing.append(
            MissingData(
                field="price_data_quality",
                state=MissingDataState.UNKNOWN,
                reason="Price data is usable but provider validation reported partial quality.",
            )
        )
    if is_stale:
        missing.append(
            MissingData(
                field="price_data",
                state=MissingDataState.STALE,
                reason="The latest available price date is older than the configured freshness policy.",
            )
        )
    return tuple(missing)


def _persistence_warning(operation: str, exc: Exception) -> str:
    """Return a redacted diagnostic without exposing a stack trace."""

    safe_detail = sanitize_provider_text(str(exc)).strip()
    exception_name = sanitize_provider_text(type(exc).__name__)
    detail_suffix = f": {safe_detail}" if safe_detail else ""
    return (
        f"{operation} failed ({exception_name}{detail_suffix}); "
        "analysis continues without that persistence step."
    )


def _as_utc(value: datetime) -> datetime:
    """Normalize injected clocks for deterministic, timezone-aware lineage timestamps."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
