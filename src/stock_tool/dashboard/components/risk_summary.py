"""Risk and scenario rendering for the Research Workspace."""

from __future__ import annotations

from typing import Any

from stock_tool.application.research_snapshot import ResearchSnapshot


def render_risk_summary(st: Any, snapshot: ResearchSnapshot) -> None:
    """Render principal risks and a non-advisory scenario reference range."""

    st.subheader("風險與情境")
    if snapshot.principal_risks:
        st.markdown("**主要風險**")
        for risk in snapshot.principal_risks:
            st.write(f"- {risk}")
    else:
        st.info("資料不足，尚無法整理主要風險。")
    scenario = snapshot.scenario_reference
    if scenario is None or not scenario.available:
        st.info("資料不足，尚無法建立情境參考區間。")
        return
    st.markdown(f"**{scenario.title}（研究用，非投資建議）**")
    columns = st.columns(3)
    range_text = (
        "資料不足"
        if scenario.range_low is None or scenario.range_high is None
        else f"{scenario.range_low:,.2f} ~ {scenario.range_high:,.2f}"
    )
    columns[0].metric("區間", range_text)
    columns[1].metric(
        "突破觀察值",
        (
            "資料不足"
            if scenario.breakout_observation is None
            else f"{scenario.breakout_observation:,.2f}"
        ),
    )
    columns[2].metric(
        "風險參考值",
        "資料不足" if scenario.risk_reference is None else f"{scenario.risk_reference:,.2f}",
    )
    st.caption(f"方法：{scenario.method}；基準日：{scenario.as_of_date or '資料不足'}。")
    for assumption in scenario.assumptions:
        st.caption(f"假設：{assumption}")
    for limitation in scenario.limitations:
        st.caption(f"限制：{limitation}")
