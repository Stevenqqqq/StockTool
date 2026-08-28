"""Validate and clean standardized stock price records."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Mapping

STANDARD_COLUMNS = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjusted_close",
)

PRICE_COLUMNS = ("open", "high", "low", "close")

Severity = Literal["warning", "error"]


@dataclass(frozen=True)
class DataIssue:
    """A data quality issue found during price data cleaning."""

    severity: Severity
    code: str
    message: str
    row_index: int | None = None
    symbol: str | None = None
    date: str | None = None


@dataclass(frozen=True)
class CleanedPriceData:
    """Cleaned price records and non-fatal data quality warnings."""

    records: list[dict[str, Any]]
    warnings: list[DataIssue]
    errors: list[DataIssue] = field(default_factory=list)


class PriceDataWarning(UserWarning):
    """Warning emitted for non-fatal data quality issues."""


class DataValidationError(ValueError):
    """Raised when fatal data quality errors are found."""

    def __init__(self, issues: list[DataIssue]) -> None:
        self.issues = issues
        preview = "; ".join(issue.message for issue in issues[:3])
        suffix = "" if len(issues) <= 3 else f"; and {len(issues) - 3} more"
        super().__init__(f"Price data validation failed: {preview}{suffix}")


def clean_price_data(
    rows: list[Mapping[str, Any]],
    *,
    fail_on_errors: bool = True,
) -> CleanedPriceData:
    """Clean standardized OHLCV price rows.

    This function never fills missing market data with synthetic values. Rows
    with missing required values are skipped and reported as warnings. Rows
    with invalid dates, invalid prices, or invalid volume are reported as
    errors because they cannot be safely used in research calculations.

    Args:
        rows: Rows that already use the standard price schema.
        fail_on_errors: Raise ``DataValidationError`` when fatal errors exist.

    Returns:
        Cleaned records sorted by ``symbol`` and ``date``. When
        ``fail_on_errors`` is false, fatal data issues are returned in
        ``errors`` instead of being hidden.

    Raises:
        DataValidationError: If fatal errors are found and ``fail_on_errors``
            is true.
    """

    cleaned_records: list[dict[str, Any]] = []
    warning_issues: list[DataIssue] = []
    error_issues: list[DataIssue] = []
    seen_keys: set[tuple[str, str]] = set()

    for row_index, raw_row in enumerate(rows, start=1):
        record, row_warnings, row_errors = _clean_one_row(raw_row, row_index)
        warning_issues.extend(row_warnings)
        error_issues.extend(row_errors)

        if record is None:
            continue

        key = (record["date"], record["symbol"])
        if key in seen_keys:
            warning_issues.append(
                DataIssue(
                    severity="warning",
                    code="duplicate_removed",
                    message=(
                        f"已移除重複股價資料：股票代號={record['symbol']}，"
                        f"日期={record['date']}"
                    ),
                    row_index=row_index,
                    symbol=record["symbol"],
                    date=record["date"],
                )
            )
            continue

        seen_keys.add(key)
        cleaned_records.append(record)

    _emit_warnings(warning_issues)

    if error_issues and fail_on_errors:
        raise DataValidationError(error_issues)

    cleaned_records.sort(key=lambda item: (item["symbol"], item["date"]))
    return CleanedPriceData(
        records=cleaned_records,
        warnings=warning_issues,
        errors=error_issues,
    )


def _clean_one_row(
    raw_row: Mapping[str, Any],
    row_index: int,
) -> tuple[dict[str, Any] | None, list[DataIssue], list[DataIssue]]:
    warnings_found: list[DataIssue] = []
    errors_found: list[DataIssue] = []

    raw_symbol = raw_row.get("symbol")
    symbol = "" if raw_symbol is None else str(raw_symbol).strip()
    raw_date = raw_row.get("date")
    parsed_date = _parse_date(raw_date)
    date_text = parsed_date.isoformat() if parsed_date else None

    context = {"row_index": row_index, "symbol": symbol or None, "date": date_text}

    if not symbol:
        errors_found.append(
            DataIssue(
                severity="error",
                code="missing_symbol",
                message=f"第 {row_index} 列缺少股票代號。",
                **context,
            )
        )

    if parsed_date is None:
        errors_found.append(
            DataIssue(
                severity="error",
                code="invalid_date",
                message=f"第 {row_index} 列日期格式無效：{raw_date!r}。",
                **context,
            )
        )

    required_values = ("date", "symbol", "open", "high", "low", "close", "volume")
    missing_required = [column for column in required_values if _is_blank(raw_row.get(column))]
    missing_required = [
        column for column in missing_required if column not in {"date", "symbol"}
    ]
    if missing_required:
        warnings_found.append(
            DataIssue(
                severity="warning",
                code="missing_required_value",
                message=(
                    f"第 {row_index} 列缺少必要欄位值："
                    f"{', '.join(missing_required)}。已略過該列。"
                ),
                **context,
            )
        )
        return None, warnings_found, errors_found

    if errors_found:
        return None, warnings_found, errors_found

    record: dict[str, Any] = {
        "date": parsed_date.isoformat(),
        "symbol": symbol,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": None,
        "adjusted_close": None,
    }

    for column in PRICE_COLUMNS:
        value = _parse_float(raw_row.get(column))
        if value is None or not _is_finite(value) or value <= 0:
            errors_found.append(
                DataIssue(
                    severity="error",
                    code="invalid_price",
                    message=f"第 {row_index} 列 {column} 價格無效：{raw_row.get(column)!r}。",
                    **context,
                )
            )
        record[column] = value

    adjusted_close = _parse_float(raw_row.get("adjusted_close"))
    if adjusted_close is not None:
        if not _is_finite(adjusted_close) or adjusted_close <= 0:
            errors_found.append(
                DataIssue(
                    severity="error",
                    code="invalid_adjusted_close",
                    message=(
                        f"第 {row_index} 列 adjusted_close 無效："
                        f"{raw_row.get('adjusted_close')!r}。"
                    ),
                    **context,
                )
            )
        else:
            record["adjusted_close"] = adjusted_close

    volume = _parse_float(raw_row.get("volume"))
    if volume is None or not _is_finite(volume) or volume < 0:
        errors_found.append(
            DataIssue(
                severity="error",
                code="invalid_volume",
                message=f"第 {row_index} 列 volume 成交量無效：{raw_row.get('volume')!r}。",
                **context,
            )
        )
    else:
        record["volume"] = volume

    if not errors_found:
        _validate_ohlc_consistency(record, row_index, errors_found)

    if errors_found:
        return None, warnings_found, errors_found

    return record, warnings_found, errors_found


def _validate_ohlc_consistency(
    record: Mapping[str, Any],
    row_index: int,
    errors_found: list[DataIssue],
) -> None:
    high = float(record["high"])
    low = float(record["low"])
    open_price = float(record["open"])
    close = float(record["close"])
    context = {
        "row_index": row_index,
        "symbol": str(record["symbol"]),
        "date": str(record["date"]),
    }

    if high < low:
        errors_found.append(
            DataIssue(
                severity="error",
                code="high_lower_than_low",
                message=f"第 {row_index} 列 high 小於 low。",
                **context,
            )
        )

    if high < max(open_price, close):
        errors_found.append(
            DataIssue(
                severity="error",
                code="high_below_open_or_close",
                message=f"第 {row_index} 列 high 小於 open 或 close。",
                **context,
            )
        )

    if low > min(open_price, close):
        errors_found.append(
            DataIssue(
                severity="error",
                code="low_above_open_or_close",
                message=f"第 {row_index} 列 low 大於 open 或 close。",
                **context,
            )
        )


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if _is_blank(value):
        return None

    text = str(value).strip()
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
        "%m/%d/%Y",
        "%Y.%m.%d",
    )
    for date_format in formats:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _is_finite(value: float) -> bool:
    return math.isfinite(value)


def _emit_warnings(issues: list[DataIssue]) -> None:
    for issue in issues:
        warnings.warn(issue.message, PriceDataWarning, stacklevel=3)
