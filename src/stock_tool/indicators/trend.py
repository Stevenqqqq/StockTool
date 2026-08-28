"""Trend indicators such as moving averages and price bias."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from stock_tool.indicators.common import (
    grouped_transform,
    normalize_periods,
    prepare_frame,
    restore_frame,
)

DEFAULT_SMA_PERIODS = (5, 10, 20, 60, 120, 240)
DEFAULT_EMA_PERIODS = (12, 26)


def add_sma(
    df: pd.DataFrame,
    *,
    periods: Sequence[int] = DEFAULT_SMA_PERIODS,
    price_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with simple moving average columns.

    SMA is the rolling arithmetic mean of ``price_col`` using only current and
    historical rows within the same symbol. Insufficient history produces
    ``NaN``.
    """

    normalized_periods = normalize_periods(periods)
    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)

    for period in normalized_periods:
        work[f"sma_{period}"] = grouped_transform(
            work,
            price_col,
            lambda series, window=period: series.rolling(
                window=window,
                min_periods=window,
            ).mean(),
            symbol_col=symbol_col,
        )

    return restore_frame(work, order_col)


def add_ema(
    df: pd.DataFrame,
    *,
    periods: Sequence[int] = DEFAULT_EMA_PERIODS,
    price_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with exponential moving average columns.

    EMA uses ``pandas.Series.ewm`` with ``adjust=False`` and ``min_periods``
    equal to the EMA period, so early rows remain ``NaN`` when history is
    insufficient.
    """

    normalized_periods = normalize_periods(periods)
    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)

    for period in normalized_periods:
        work[f"ema_{period}"] = grouped_transform(
            work,
            price_col,
            lambda series, span=period: series.ewm(
                span=span,
                adjust=False,
                min_periods=span,
            ).mean(),
            symbol_col=symbol_col,
        )

    return restore_frame(work, order_col)


def add_bias(
    df: pd.DataFrame,
    *,
    periods: Sequence[int] = DEFAULT_SMA_PERIODS,
    price_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with price bias ratio columns.

    Bias is ``(close / SMA_N - 1) * 100``. It uses the same backward-looking
    rolling window as SMA and returns ``NaN`` when the window is incomplete or
    the moving average is zero.
    """

    normalized_periods = normalize_periods(periods)
    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)

    for period in normalized_periods:
        sma = grouped_transform(
            work,
            price_col,
            lambda series, window=period: series.rolling(
                window=window,
                min_periods=window,
            ).mean(),
            symbol_col=symbol_col,
        )
        work[f"bias_{period}"] = ((work[price_col] / sma.where(sma != 0)) - 1.0) * 100.0

    return restore_frame(work, order_col)

