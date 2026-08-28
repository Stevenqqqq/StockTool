"""Volatility indicators such as Bollinger Bands, ATR, and realized volatility."""

from __future__ import annotations

from collections.abc import Sequence
from math import sqrt

import pandas as pd

from stock_tool.indicators.common import (
    grouped_apply_frame,
    grouped_transform,
    normalize_periods,
    prepare_frame,
    restore_frame,
)


def add_bollinger_bands(
    df: pd.DataFrame,
    *,
    period: int = 20,
    num_std: float = 2.0,
    price_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with Bollinger Band columns.

    The middle band is the N-period SMA. The upper and lower bands are the
    middle band plus or minus ``num_std`` rolling standard deviations. The
    rolling window is backward-looking and grouped by symbol.
    """

    if period <= 0:
        raise ValueError("Bollinger Bands period must be a positive integer.")
    if num_std <= 0:
        raise ValueError("Bollinger Bands num_std must be positive.")

    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)

    middle = grouped_transform(
        work,
        price_col,
        lambda series: series.rolling(window=period, min_periods=period).mean(),
        symbol_col=symbol_col,
    )
    rolling_std = grouped_transform(
        work,
        price_col,
        lambda series: series.rolling(window=period, min_periods=period).std(ddof=0),
        symbol_col=symbol_col,
    )

    work[f"bb_middle_{period}"] = middle
    work[f"bb_upper_{period}"] = middle + (num_std * rolling_std)
    work[f"bb_lower_{period}"] = middle - (num_std * rolling_std)
    return restore_frame(work, order_col)


def add_atr(
    df: pd.DataFrame,
    *,
    period: int = 14,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with Average True Range.

    True Range is the maximum of ``high - low``, ``abs(high - previous close)``,
    and ``abs(low - previous close)``. ATR is the rolling mean of True Range
    over ``period`` rows. Previous close is grouped by symbol.
    """

    if period <= 0:
        raise ValueError("ATR period must be a positive integer.")

    work, order_col = prepare_frame(
        df,
        [high_col, low_col, close_col],
        date_col=date_col,
        symbol_col=symbol_col,
    )

    def calculate_atr(group: pd.DataFrame) -> pd.DataFrame:
        previous_close = group[close_col].shift(1)
        true_range = pd.concat(
            [
                group[high_col] - group[low_col],
                (group[high_col] - previous_close).abs(),
                (group[low_col] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.rolling(window=period, min_periods=period).mean()
        return pd.DataFrame({f"atr_{period}": atr}, index=group.index)

    atr = grouped_apply_frame(work, calculate_atr, symbol_col=symbol_col)
    work[f"atr_{period}"] = atr[f"atr_{period}"]
    return restore_frame(work, order_col)


def add_rolling_volatility(
    df: pd.DataFrame,
    *,
    periods: Sequence[int],
    price_col: str = "close",
    annualize: bool = False,
    trading_periods: int = 252,
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with trailing realized volatility columns.

    Volatility is the rolling standard deviation of one-period returns within
    each symbol. Set ``annualize=True`` to multiply by ``sqrt(trading_periods)``.
    Insufficient history produces ``NaN``.
    """

    normalized_periods = normalize_periods(periods)
    if trading_periods <= 0:
        raise ValueError("trading_periods must be a positive integer.")

    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)
    one_period_return = grouped_transform(
        work,
        price_col,
        lambda series: (series / series.shift(1)) - 1.0,
        symbol_col=symbol_col,
    )
    scale = sqrt(trading_periods) if annualize else 1.0

    temp_return_col = "__indicator_return"
    while temp_return_col in work.columns:
        temp_return_col += "_"
    work[temp_return_col] = one_period_return

    for period in normalized_periods:
        work[f"volatility_{period}"] = grouped_transform(
            work,
            temp_return_col,
            lambda series, window=period: series.rolling(
                window=window,
                min_periods=window,
            ).std(ddof=0)
            * scale,
            symbol_col=symbol_col,
        )

    work = work.drop(columns=[temp_return_col])
    return restore_frame(work, order_col)

