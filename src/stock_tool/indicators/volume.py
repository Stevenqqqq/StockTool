"""Volume-based technical indicators."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from stock_tool.indicators.common import (
    grouped_transform,
    normalize_periods,
    prepare_frame,
    restore_frame,
)


def add_volume_moving_average(
    df: pd.DataFrame,
    *,
    periods: Sequence[int] = (5, 20),
    volume_col: str = "volume",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with volume moving average columns.

    The calculation is a backward-looking rolling mean of ``volume_col``.
    Insufficient history produces ``NaN``.
    """

    normalized_periods = normalize_periods(periods)
    work, order_col = prepare_frame(df, [volume_col], date_col=date_col, symbol_col=symbol_col)

    for period in normalized_periods:
        work[f"volume_ma_{period}"] = grouped_transform(
            work,
            volume_col,
            lambda series, window=period: series.rolling(
                window=window,
                min_periods=window,
            ).mean(),
            symbol_col=symbol_col,
        )

    return restore_frame(work, order_col)

