"""Descriptive daily patterns only; never executes or qualifies Scenario Research."""

from dataclasses import dataclass
from datetime import datetime
import math

import pandas as pd

from stock_tool.application.completed_daily_prices import completed_daily_prices
from stock_tool.application.research_snapshot import ResearchSnapshot
from stock_tool.application.scenario_research import Rules
from stock_tool.data.corporate_actions import raw_research_safety_errors
from stock_tool.indicators import add_sma


@dataclass(frozen=True)
class BreakoutObservation:
    date: str | None = None
    status: str = "資料不足"
    reference: float | None = None
    distance: float | None = None
    volume_ratio: float | None = None
    conditions: tuple[str, ...] = ()
    reason: str | None = None
    events: tuple[tuple[str, str], ...] = ()


def observe_breakout(
    snapshot: ResearchSnapshot, *, now: datetime | None = None
) -> BreakoutObservation:
    """Use causal windows of completed exchange-local sessions, without filling gaps.

    Reuses the default mathematical confirmation filters, not the strategy's
    state machine, qualification, orders, exits or replay. Historical events are
    daily crossings, not completed strategy cases. Coverage remains unknown.
    """
    r = Rules()
    source = snapshot.source_metadata
    data = snapshot.price_history
    cutoff = snapshot.price.last_data_date if snapshot.price else None
    if data is None or data.empty or not cutoff or not source.provider:
        return BreakoutObservation(reason="缺少行情、觀測日期或來源；請重新載入免費行情。")
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(data.columns):
        return BreakoutObservation(reason="缺少完整 OHLCV；不以收盤價代替最高／最低價。")
    frame = data.copy(deep=True)
    for field, value in (
        ("market", snapshot.symbol.market.value),
        ("symbol", snapshot.symbol.code),
    ):
        if field in frame and not frame[field].eq(value).all():
            return BreakoutObservation(reason="行情身分不一致；請重新載入此標的。")
        frame[field] = value
    if pd.to_datetime(frame.date, errors="coerce", utc=True).isna().any():
        return BreakoutObservation(reason="行情日期無法確認。")
    frame, _ = completed_daily_prices(
        frame, market=snapshot.symbol.market.value, fetched_at=source.fetched_at, now=now
    )
    try:
        end = pd.Timestamp(cutoff)
        if end.tzinfo is not None or pd.isna(end):
            raise ValueError("snapshot date must be exchange local")
        frame = frame.loc[frame.date <= end].sort_values("date").reset_index(drop=True)
    except (ValueError, TypeError):
        return BreakoutObservation(reason="快照觀測日期未正規化，無法一致比較。")
    if frame.empty or frame.date.iloc[-1] != end:
        return BreakoutObservation(reason="觀測日尚無可確認完成的日線；請重新載入。")
    if frame.date.duplicated().any():
        return BreakoutObservation(reason="日期重複／衝突，不能將兩筆當兩個交易日。")
    for field in ("open", "high", "low", "close", "volume"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = add_sma(frame, periods=(r.F,))
    needed = max(r.N + 1, r.V + 1, r.F + r.S)
    latest = BreakoutObservation(
        date=end.date().isoformat(), reason=f"至少需要 {needed} 筆完整日線。"
    )
    events: list[tuple[str, str]] = []
    for i in range(needed - 1, len(frame)):
        window = frame.iloc[i - needed + 1 : i + 1]
        day = frame.date.iloc[i].date().isoformat()
        reason = None
        values = window[["open", "high", "low", "close", "volume"]]
        if not values.map(lambda x: math.isfinite(x) and x > 0).all().all():
            reason = "計算視窗內 OHLCV 缺漏、零值或無效；不跳過、不補值。"
        elif (window.high < window[["open", "low", "close"]].max(axis=1)).any() or (
            window.low > window[["open", "high", "close"]].min(axis=1)
        ).any():
            reason = "最高／最低價與開收盤不一致。"
        elif raw_research_safety_errors(window):
            reason = "視窗內價格重大不連續，可能涉及公司行動；暫不判讀、不推算調整比例。"
        for field in ("dividends", "stock_splits", "Dividends", "Stock Splits"):
            if (
                field in window
                and pd.to_numeric(window[field], errors="coerce").fillna(0).ne(0).any()
            ):
                reason = "視窗內有公司行動記錄，價格可比性尚未確認。"
        if reason:
            latest = BreakoutObservation(date=day, reason=reason)
            continue
        close = float(window.close.iloc[-1])
        peak = float(window.high.iloc[-r.N - 1 : -1].max())
        average = float(window.volume.iloc[-r.V - 1 : -1].mean())
        sma = float(frame[f"sma_{r.F}"].iloc[i])
        old_sma = float(frame[f"sma_{r.F}"].iloc[i - r.S])
        crossed = float(window.close.iloc[-2]) <= peak < close
        flags = (float(window.volume.iloc[-1]) > r.M * average, close > sma, sma > old_sma)
        conditions = (
            f"量能 {'達標' if flags[0] else '未達標'}（須大於 {r.M:g} 倍）",
            f"收盤 {'高於' if flags[1] else '未高於'} SMA20",
            f"SMA20 {'向上' if flags[2] else '未向上'}（對比五筆前）",
        )
        status = (
            "突破・確認條件齊備"
            if crossed and all(flags)
            else ("價格突破・確認條件未齊" if crossed else "尚未突破")
        )
        if crossed:
            events.append((day, status))
        latest = BreakoutObservation(
            date=day,
            status=status,
            reference=peak,
            distance=close / peak - 1,
            volume_ratio=float(window.volume.iloc[-1]) / average,
            conditions=conditions,
        )
    return BreakoutObservation(**{**latest.__dict__, "events": tuple(events[-3:])})
