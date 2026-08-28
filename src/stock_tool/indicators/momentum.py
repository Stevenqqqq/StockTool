"""Momentum indicators such as RSI, MACD, KD, and rolling returns."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from stock_tool.indicators.common import (
    grouped_apply_frame,
    grouped_transform,
    normalize_periods,
    prepare_frame,
    restore_frame,
)


def add_rsi(
    df: pd.DataFrame,
    *,
    period: int = 14,
    price_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with a Relative Strength Index column.

    RSI uses Wilder-style exponential smoothing with ``alpha = 1 / period``.
    It only uses current and historical closes within the same symbol. Rows
    with insufficient price changes produce ``NaN``.
    """

    if period <= 0:
        raise ValueError("RSI period must be a positive integer.")

    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)

    def calculate_rsi(series: pd.Series) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss.where(avg_loss != 0)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
        rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
        rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
        return rsi

    work[f"rsi_{period}"] = grouped_transform(
        work,
        price_col,
        calculate_rsi,
        symbol_col=symbol_col,
    )
    return restore_frame(work, order_col)


def add_macd(
    df: pd.DataFrame,
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    price_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with MACD DIF, DEA, and histogram columns.

    DIF is ``EMA_fast - EMA_slow``. DEA is the EMA of DIF. Histogram is
    ``DIF - DEA``. All EMA calculations are backward-looking and grouped by
    symbol when a symbol column exists.
    """

    if min(fast_period, slow_period, signal_period) <= 0:
        raise ValueError("MACD periods must be positive integers.")
    if fast_period >= slow_period:
        raise ValueError("MACD fast_period must be smaller than slow_period.")

    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)

    def calculate_macd(group: pd.DataFrame) -> pd.DataFrame:
        close = group[price_col]
        ema_fast = close.ewm(span=fast_period, adjust=False, min_periods=fast_period).mean()
        ema_slow = close.ewm(span=slow_period, adjust=False, min_periods=slow_period).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
        histogram = dif - dea
        return pd.DataFrame(
            {
                "macd_dif": dif,
                "macd_dea": dea,
                "macd_histogram": histogram,
            },
            index=group.index,
        )

    macd = grouped_apply_frame(work, calculate_macd, symbol_col=symbol_col)
    work["macd_dif"] = macd["macd_dif"]
    work["macd_dea"] = macd["macd_dea"]
    work["macd_histogram"] = macd["macd_histogram"]
    return restore_frame(work, order_col)


def add_stochastic_oscillator(
    df: pd.DataFrame,
    *,
    k_period: int = 9,
    k_smoothing: int = 3,
    d_period: int = 3,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with KD / stochastic oscillator columns.

    Raw RSV is ``(close - rolling_low) / (rolling_high - rolling_low) * 100``.
    ``stoch_k`` is a rolling mean of RSV, and ``stoch_d`` is a rolling mean of
    ``stoch_k``. Zero trading ranges produce ``NaN`` instead of artificial
    values.
    """

    if min(k_period, k_smoothing, d_period) <= 0:
        raise ValueError("Stochastic oscillator periods must be positive integers.")

    work, order_col = prepare_frame(
        df,
        [high_col, low_col, close_col],
        date_col=date_col,
        symbol_col=symbol_col,
    )

    def calculate_stochastic(group: pd.DataFrame) -> pd.DataFrame:
        rolling_low = group[low_col].rolling(window=k_period, min_periods=k_period).min()
        rolling_high = group[high_col].rolling(window=k_period, min_periods=k_period).max()
        range_width = rolling_high - rolling_low
        raw_k = ((group[close_col] - rolling_low) / range_width.where(range_width != 0)) * 100.0
        stoch_k = raw_k.rolling(window=k_smoothing, min_periods=k_smoothing).mean()
        stoch_d = stoch_k.rolling(window=d_period, min_periods=d_period).mean()
        return pd.DataFrame(
            {
                "stoch_k": stoch_k,
                "stoch_d": stoch_d,
            },
            index=group.index,
        )

    stochastic = grouped_apply_frame(work, calculate_stochastic, symbol_col=symbol_col)
    work["stoch_k"] = stochastic["stoch_k"]
    work["stoch_d"] = stochastic["stoch_d"]
    return restore_frame(work, order_col)


def add_rolling_return(
    df: pd.DataFrame,
    *,
    periods: Sequence[int],
    price_col: str = "close",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """Return a copy of ``df`` with trailing N-period return columns.

    Return is ``close / close.shift(N) - 1`` within each symbol. It does not
    use future prices. Insufficient history produces ``NaN``.
    """

    normalized_periods = normalize_periods(periods)
    work, order_col = prepare_frame(df, [price_col], date_col=date_col, symbol_col=symbol_col)

    for period in normalized_periods:
        shifted = grouped_transform(
            work,
            price_col,
            lambda series, lag=period: series.shift(lag),
            symbol_col=symbol_col,
        )
        work[f"return_{period}"] = (work[price_col] / shifted.where(shifted != 0)) - 1.0

    return restore_frame(work, order_col)

