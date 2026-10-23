"""Read-only, identity-bound completed-close comparisons; no cross-date ranking."""

from dataclasses import dataclass
from datetime import datetime
import math

import pandas as pd

from stock_tool.application.completed_daily_prices import completed_daily_prices
from stock_tool.domain.models import Market, Symbol
from stock_tool.indicators import add_rolling_return, add_sma, add_volume_moving_average


@dataclass(frozen=True)
class ComparisonRow:
    symbol: Symbol
    date: str | None = None
    source: str | None = None
    close: float | None = None
    return_5: float | None = None
    return_20: float | None = None
    sma_20_position: float | None = None
    sma_60_position: float | None = None
    volume_ratio: float | None = None
    notices: tuple[str, ...] = ()


def _positive(values: pd.Series, *, zero: bool = False) -> pd.Series:
    numbers = pd.to_numeric(values, errors="coerce")
    return numbers.where(numbers.map(math.isfinite) & (numbers.ge(0) if zero else numbers.gt(0)))


def compare_symbol(
    prices: pd.DataFrame | None, symbol: Symbol, *, now: datetime | None = None
) -> ComparisonRow:
    """Compute independently without borrowing another identity's acquisition metadata.

    Returns count observed daily sessions, not calendar days. Missing values are
    never filled or dropped to manufacture a full window. Raw data stays intact.
    """
    unavailable = ComparisonRow(symbol, notices=("缺少市場別行情；請載入免費行情。",))
    if symbol.market not in {Market.TWSE, Market.TPEX, Market.US}:
        return ComparisonRow(symbol, notices=("市場未確認；請先確認上市／上櫃／美股。",))
    if prices is None or not {"symbol", "market", "date"}.issubset(prices.columns):
        return unavailable
    frame = prices.loc[prices.symbol.eq(symbol.code) & prices.market.eq(symbol.market.value)].copy(
        deep=True
    )
    if frame.empty:
        return unavailable
    frame, notices = completed_daily_prices(frame, market=symbol.market.value, now=now)
    if frame.empty:
        return ComparisonRow(symbol, notices=notices + ("尚無已確認完成的日線；請重新載入。",))
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    if frame.date.duplicated().any():
        return ComparisonRow(symbol, notices=("日期重複或衝突；請重新載入行情。",))
    latest = frame.iloc[-1]
    source_value = latest.get("source", latest.get("provider"))
    source = str(source_value) if pd.notna(source_value) and str(source_value).strip() else None
    date = pd.Timestamp(latest.date).date().isoformat()
    if source is None:
        return ComparisonRow(symbol, date=date, notices=notices + ("行情來源未確認。",))
    frame["close"] = _positive(frame.get("close", pd.Series(index=frame.index, dtype=float)))
    frame["volume"] = _positive(
        frame.get("volume", pd.Series(index=frame.index, dtype=float)), zero=True
    )
    calculated = add_sma(add_rolling_return(frame, periods=(5, 20)), periods=(20, 60))
    latest = calculated.iloc[-1]

    def finite(value: object) -> float | None:
        return float(value) if pd.notna(value) and math.isfinite(float(value)) else None

    close = finite(latest.close)
    values: dict[str, float | None] = {}
    missing: list[str] = []
    for period in (5, 20):
        valid = len(frame) >= period + 1 and frame.close.iloc[-period - 1 :].notna().all()
        values[f"return_{period}"] = finite(latest[f"return_{period}"]) if valid else None
        if values[f"return_{period}"] is None:
            missing.append(f"{period}日報酬需{period + 1}筆有效收盤")
    for period in (20, 60):
        mean = finite(latest[f"sma_{period}"])
        values[f"sma_{period}_position"] = close / mean - 1 if close is not None and mean else None
        if values[f"sma_{period}_position"] is None:
            missing.append(f"SMA{period}需{period}筆有效收盤")
    volume_ratio = None
    if len(frame) >= 21:
        average = add_volume_moving_average(frame, periods=(20,)).volume_ma_20.iloc[-2]
        volume = frame.volume.iloc[-1]
        if pd.notna(average) and average > 0 and pd.notna(volume):
            volume_ratio = float(volume / average)
    if volume_ratio is None:
        missing.append("量比需當日及前20筆有效成交量，且前20筆均量大於0")
    if close is None:
        missing.append("最新收盤無效")
    return ComparisonRow(
        symbol,
        date,
        source,
        close,
        **values,
        volume_ratio=volume_ratio,
        notices=notices + tuple(missing),
    )


def comparison_notices(rows: tuple[ComparisonRow, ...]) -> tuple[str, ...]:
    dates = {row.date for row in rows if row.close is not None}
    notices = []
    if len(dates) > 1:
        notices.append("比較基準不一致：各檔收盤日期不同，不可視為同日橫向排名。")
    if len({row.symbol.market for row in rows}) > 1:
        notices.append("跨市場交易日、收盤時區及幣別不同；相同日期也不代表同一時點。")
    return tuple(notices)
