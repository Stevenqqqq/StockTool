"""Shared helpers for technical indicator calculations."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd


class MissingIndicatorColumnError(ValueError):
    """Raised when an indicator cannot find required input columns."""

    def __init__(self, missing_columns: Sequence[str]) -> None:
        self.missing_columns = tuple(missing_columns)
        joined = ", ".join(self.missing_columns)
        super().__init__(f"Missing required indicator columns: {joined}")


def require_columns(df: pd.DataFrame, columns: Sequence[str]) -> None:
    """Validate that a DataFrame contains all required columns."""

    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise MissingIndicatorColumnError(missing)


def normalize_periods(periods: Sequence[int]) -> tuple[int, ...]:
    """Validate and normalize indicator periods."""

    normalized = tuple(int(period) for period in periods)
    invalid = [period for period in normalized if period <= 0]
    if invalid:
        raise ValueError(f"Indicator periods must be positive integers: {invalid}")
    return normalized


def prepare_frame(
    df: pd.DataFrame,
    required_columns: Sequence[str],
    *,
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> tuple[pd.DataFrame, str]:
    """Copy and sort a DataFrame for chronological indicator calculations.

    The original DataFrame is never modified. When ``symbol_col`` exists,
    calculations are performed independently by symbol. When ``date_col``
    exists, rows are sorted chronologically before rolling calculations.
    """

    require_columns(df, required_columns)
    work = df.copy(deep=True)
    order_col = _temporary_column_name(work, "__indicator_original_order")
    work[order_col] = range(len(work))

    sort_columns: list[str] = []
    if symbol_col in work.columns:
        sort_columns.append(symbol_col)
    helper_columns: list[str] = []
    if date_col in work.columns:
        date_sort_col = _temporary_column_name(work, "__indicator_date_sort")
        parsed_dates = pd.to_datetime(work[date_col], errors="coerce")
        invalid_dates = parsed_dates.isna() & work[date_col].notna()
        if invalid_dates.any():
            raise ValueError(f"{date_col} contains invalid dates for indicator calculation.")
        work[date_sort_col] = parsed_dates
        helper_columns.append(date_sort_col)
        sort_columns.append(date_sort_col)
    sort_columns.append(order_col)

    work = work.sort_values(sort_columns, kind="mergesort")
    work.attrs["_indicator_helper_columns"] = helper_columns
    return work, order_col


def restore_frame(work: pd.DataFrame, order_col: str) -> pd.DataFrame:
    """Restore the input row order and remove helper columns."""

    helper_columns = [
        column
        for column in work.attrs.get("_indicator_helper_columns", [])
        if column in work.columns
    ]
    return work.sort_values(order_col, kind="mergesort").drop(
        columns=[order_col, *helper_columns],
    )


def grouped_transform(
    work: pd.DataFrame,
    column: str,
    transform: Callable[[pd.Series], pd.Series],
    *,
    symbol_col: str = "symbol",
) -> pd.Series:
    """Apply a Series transform per symbol when a symbol column exists."""

    if symbol_col in work.columns:
        return work.groupby(symbol_col, sort=False)[column].transform(transform)
    return transform(work[column])


def grouped_apply_frame(
    work: pd.DataFrame,
    transform: Callable[[pd.DataFrame], pd.DataFrame],
    *,
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Apply a DataFrame transform per symbol while preserving row indexes."""

    if symbol_col in work.columns:
        pieces = [
            transform(group)
            for _, group in work.groupby(symbol_col, group_keys=False, sort=False)
        ]
        return pd.concat(pieces).sort_index()
    return transform(work)


def _temporary_column_name(df: pd.DataFrame, base_name: str) -> str:
    name = base_name
    suffix = 1
    while name in df.columns:
        suffix += 1
        name = f"{base_name}_{suffix}"
    return name
