"""Read-only overview of existing price, indicator and scenario evidence."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from stock_tool.application.research_snapshot import ResearchSnapshot
from stock_tool.dashboard.components.research_chart import (
    build_research_chart,
    render_research_chart,
)

from stock_tool.dashboard.components.scenario_reference_presentation import (
    normalized_date as _date,
    scenario_date_status,
)


def _number(value: Any, *, zero: bool = False) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and (number >= 0 if zero else number > 0) else None
    except (TypeError, ValueError):
        return None


def observation_history(snapshot: ResearchSnapshot) -> pd.DataFrame:
    """Restrict to the snapshot observation date; never infer it from future rows."""
    cutoff = _date(snapshot.price.last_data_date) if snapshot.price else None
    frame = snapshot.price_history
    if cutoff is None or frame is None or "date" not in frame:
        return pd.DataFrame()
    result = frame.copy(deep=True)
    result["date"] = result["date"].map(_date)
    return result.loc[result.date.notna() & (result.date <= cutoff)].sort_values(
        "date", kind="stable"
    )


def observation_summary(snapshot: ResearchSnapshot) -> tuple[str, str, str]:
    """Describe evidence, not signals. Volume uses the preceding 20 observed rows."""
    frame = observation_history(snapshot)
    cutoff = _date(snapshot.price.last_data_date) if snapshot.price else None
    unavailable = "資料不足（unavailable）"
    trend = f"趨勢：{unavailable}；缺少觀測日收盤價或同日均線。"
    volume = f"量能：{unavailable}；需觀測日及其前 20 筆有效成交量。"
    valid_dates = not frame.empty and not frame.date.duplicated().any()
    if valid_dates and frame.date.iloc[-1] == cutoff:
        close = _number(frame.iloc[-1].get("close"))
        indicators = snapshot.indicators
        if close is not None and indicators is not None and "date" in indicators:
            same_day = indicators.loc[indicators.date.map(_date) == cutoff]
            if len(same_day) == 1:
                parts = []
                for label, field in (("SMA20", "sma_20"), ("SMA60", "sma_60")):
                    mean = _number(same_day.iloc[0].get(field))
                    if mean is None:
                        parts.append(f"{label} {unavailable}")
                    else:
                        relation = "高於" if close > mean else "低於" if close < mean else "等於"
                        parts.append(f"{relation} {label}（{mean:,.2f}）")
                trend = f"趨勢：收盤 {close:,.2f}，" + "；".join(parts) + "。只描述相對位置。"
        if "volume" in frame and len(frame) >= 21:
            values = [_number(v, zero=True) for v in frame.volume.iloc[-21:]]
            if all(v is not None for v in values):
                previous = [float(v) for v in values[:-1] if v is not None]
                average = sum(previous) / 20
                current = float(values[-1])  # type: ignore[arg-type]
                if average > 0:
                    ratio = current / average
                    relation = "高於" if ratio > 1 else "低於" if ratio < 1 else "等於"
                    volume = (
                        f"量能：觀測日成交量為此前 20 筆平均的 {ratio:.2f} 倍（{relation}均量）。"
                        "基準不含當日；零量保留，缺漏不跳過、不補值。"
                    )
    if not valid_dates and not frame.empty:
        trend = f"趨勢：{unavailable}；價格日期重複，無法唯一確認。"
        volume = f"量能：{unavailable}；價格日期重複，無法唯一確認。"
    scenario = snapshot.scenario_reference
    usable, date_label = scenario_date_status(snapshot)
    reference = f"觀察價位：{unavailable}；{date_label}"
    if usable and scenario is not None:

        def price(value: Any) -> str:
            number = _number(value)
            return f"{number:,.2f}" if number is not None else unavailable

        reference = (
            f"觀察價位：區間 {price(scenario.range_low)}～{price(scenario.range_high)}；"
            f"突破觀察 {price(scenario.breakout_observation)}；"
            f"風險參考 {price(scenario.risk_reference)}。"
            f"{date_label}；方法：{scenario.method}。"
        )
    return trend, volume, reference


def render_price_volume_observation(st: Any, snapshot: ResearchSnapshot) -> None:
    from stock_tool.dashboard.components.breakout_observation import render_breakout_observation

    with st.expander("突破條件與歷史（研究重點已摘要）", expanded=False):
        render_breakout_observation(st, snapshot)
    st.subheader("價量觀察")
    date = snapshot.price.last_data_date if snapshot.price else None
    st.caption(
        f"觀測日：{date or '未確認'}｜使用已載入行情，非即時報價；"
        "圖表期間只改變顯示範圍，不改變摘要觀測日。"
    )
    for text in observation_summary(snapshot):
        st.write(text)
    scenario = snapshot.scenario_reference
    if scenario is not None:
        with st.expander("情境計算依據與完整限制"):
            for text in (*scenario.assumptions, *scenario.limitations):
                st.caption(f"情境限制／假設：{text}")
    st.caption("上述為歷史價量與既有情境參考，不是買賣訊號，亦不代表真實回測資料已合格。")
    period = st.selectbox(
        "總覽圖表期間", ("6M", "1Y", "3Y", "MAX"), index=1, key="research_overview_period"
    )
    model = build_research_chart(
        observation_history(snapshot), indicators=snapshot.indicators, period=period
    )
    render_research_chart(st, model)
