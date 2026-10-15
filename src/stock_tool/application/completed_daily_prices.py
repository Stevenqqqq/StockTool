"""A non-mutating completed-bar input boundary for current close research only.

This does not qualify historical securities or alter backtest inputs. Acquisition
time, rather than a later cache read, bounds what a daily bar could contain.
Same-day publication buffers match the existing daily-holdings scheduler.
"""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd


def completed_daily_prices(
    prices: pd.DataFrame,
    *,
    market: str,
    fetched_at: object = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Keep completed rows; never promote a cached intraday bar by wall-clock age.

    Date-only bar labels are exchange-local dates. Aware labels are converted
    to the exchange timezone. Naive/unknown acquisition times fail closed.
    Per-row acquisition provenance takes precedence, including missing values.
    """
    clock = now if now is not None else datetime.now(timezone.utc)
    zones = {"TWSE": "Asia/Taipei", "TPEX": "Asia/Taipei", "US": "America/New_York"}
    accepted: list[bool] = []
    local_dates: list[pd.Timestamp] = []
    for _, row in prices.iterrows():
        valid = False
        try:
            zone = ZoneInfo(zones[market])
            stamp = pd.Timestamp(row.get("fetched_at", fetched_at))
            day = pd.Timestamp(row.get("date"))
            if pd.isna(stamp) or pd.isna(day) or stamp.tzinfo is None or clock.tzinfo is None:
                raise ValueError("completion provenance unavailable")
            if stamp > pd.Timestamp(clock):
                raise ValueError("future acquisition time")
            acquired = stamp.tz_convert(zone)
            local_day = day.tz_convert(zone).date() if day.tzinfo else day.date()
            cutoff = time(18) if market == "US" else time(18, 30)
            valid = local_day < acquired.date() or (
                local_day == acquired.date() and acquired.time() >= cutoff
            )
            if valid:
                local_dates.append(pd.Timestamp(local_day))
        except (ValueError, TypeError, KeyError, OverflowError):
            pass
        accepted.append(valid)
    result = prices.loc[accepted].copy(deep=True)
    if not result.empty:
        # All downstream consumers must use the same exchange-local day that
        # passed the gate. Only the research copy changes; provenance stays raw.
        result["date"] = pd.to_datetime(local_dates)
    excluded = len(prices) - len(result)
    notices: tuple[str, ...] = ()
    if excluded:
        notices = (
            f"收盤研究：已排除 {excluded} 筆未收盤或完成狀態無法確認的日線；"
            "原始行情保留，未用於圖表、量能、評分與情境。"
            "當日行情須在台灣時間18:30／美東時間18:00後重新取得；"
            "缺取得時間的資料請重新載入。",
        )
    return result, notices
