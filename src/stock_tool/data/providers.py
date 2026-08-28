"""Replaceable data provider interfaces for price data sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd

from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    ProviderAttemptRecord,
    ProviderResult,
    provider_failure_result,
    provider_result_from_price_frame,
)
from stock_tool.data.loader import load_csv, load_excel
from stock_tool.domain.models import Symbol


class PriceDataProvider(Protocol):
    """Interface implemented by replaceable OHLCV data providers."""

    def load_price_data(self) -> list[dict[str, Any]]:
        """Return raw rows normalized to the standard price schema."""


class ContractPriceDataProvider(Protocol):
    """Interface for providers returning the canonical Sprint 2 contract."""

    def load_price_result(self) -> ProviderResult[pd.DataFrame]:
        """Return validated data, provenance, quality, and error metadata."""


@dataclass(frozen=True)
class CSVPriceDataProvider:
    """Price provider that reads local CSV files."""

    file_path: str | Path
    encoding: str = "utf-8-sig"
    column_mapping: Mapping[str, str] | None = None
    point_in_time_universe: str | Path | None = None
    """Optional point-in-time universe metadata supplied by the user."""

    def load_price_data(self) -> list[dict[str, Any]]:
        """Load standardized price rows from CSV."""

        return load_csv(
            self.file_path,
            encoding=self.encoding,
            column_mapping=self.column_mapping,
        )


@dataclass(frozen=True)
class ExcelPriceDataProvider:
    """Price provider that reads local Excel workbooks."""

    file_path: str | Path
    sheet_name: str | None = None
    column_mapping: Mapping[str, str] | None = None
    point_in_time_universe: str | Path | None = None
    """Optional point-in-time universe metadata supplied by the user."""

    def load_price_data(self) -> list[dict[str, Any]]:
        """Load standardized price rows from Excel."""

        return load_excel(
            self.file_path,
            sheet_name=self.sheet_name,
            column_mapping=self.column_mapping,
        )


@dataclass(frozen=True)
class LegacyPriceDataProviderAdapter:
    """Add the new provider contract around an unchanged legacy provider."""

    provider: PriceDataProvider
    symbol: Symbol
    provider_name: str
    source_type: DataSourceType = DataSourceType.LOCAL_FILE
    provider_symbol: str | None = None
    request_start: str | None = None
    request_end: str | None = None
    interval: str | None = None
    point_in_time_universe: str | Path | None = None

    def load_price_result(self) -> ProviderResult[pd.DataFrame]:
        """Load legacy rows and return a structured, validated result."""

        metadata = self._metadata()
        try:
            rows = self.provider.load_price_data()
        except Exception as exc:
            safe_message = f"{self.provider_name} provider 發生 {type(exc).__name__}。"
            return provider_failure_result(
                metadata=metadata,
                message=safe_message,
                attempts=(
                    ProviderAttemptRecord(
                        provider=self.provider_name,
                        success=False,
                        reason=safe_message,
                    ),
                ),
            )

        frame = pd.DataFrame(rows)
        return provider_result_from_price_frame(
            frame,
            metadata=metadata,
            attempts=(
                ProviderAttemptRecord(
                    provider=self.provider_name,
                    success=True,
                    reason=f"legacy provider returned {len(frame)} rows",
                ),
            ),
        )

    def _metadata(self) -> DataSourceMetadata:
        provider_symbol = self.provider_symbol or self.symbol.code
        point_in_time = self.point_in_time_universe
        if point_in_time is None:
            point_in_time = getattr(self.provider, "point_in_time_universe", None)
        return DataSourceMetadata(
            provider=self.provider_name,
            source_type=self.source_type,
            requested_symbol=self.symbol,
            resolved_symbol=self.symbol,
            provider_symbol=provider_symbol,
            request_start=self.request_start,
            request_end=self.request_end,
            interval=self.interval,
            point_in_time_universe=str(point_in_time) if point_in_time is not None else None,
        )


def provider_for_file(
    file_path: str | Path,
    *,
    encoding: str = "utf-8-sig",
    sheet_name: str | None = None,
    column_mapping: Mapping[str, str] | None = None,
    point_in_time_universe: str | Path | None = None,
) -> PriceDataProvider:
    """Return a local file provider based on the file suffix.

    ``point_in_time_universe`` is reserved metadata for callers that can
    supply historical universe or delisted-security data. The local file
    providers do not infer such data automatically.
    """

    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return ExcelPriceDataProvider(
            file_path=path,
            sheet_name=sheet_name,
            column_mapping=column_mapping,
            point_in_time_universe=point_in_time_universe,
        )
    if suffix == ".xls":
        raise ValueError("Legacy .xls files are not supported. Please save as .xlsx or CSV.")
    return CSVPriceDataProvider(
        file_path=path,
        encoding=encoding,
        column_mapping=column_mapping,
        point_in_time_universe=point_in_time_universe,
    )
