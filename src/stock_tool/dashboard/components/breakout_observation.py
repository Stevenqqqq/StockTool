"""Compact historical-pattern explanation beside the existing price chart."""

from typing import Any

from stock_tool.application.breakout_observation import observe_breakout
from stock_tool.application.research_snapshot import ResearchSnapshot


def render_breakout_observation(st: Any, snapshot: ResearchSnapshot) -> None:
    result = observe_breakout(snapshot)
    st.subheader("突破形態觀察")
    st.write(f"**{result.status}**｜觀測日：{result.date or '未確認'}")
    if result.reason:
        st.write(result.reason)
    if result.reference is not None and result.distance is not None:
        st.write(
            f"前20日高點 **{result.reference:,.2f}**｜收盤相距 **{result.distance:+.2%}**"
            f"｜當日量／前20日均量 **{result.volume_ratio:.2f} 倍**"
        )
        st.write(" · ".join(result.conditions))
    if result.events:
        st.write("最近可判讀的歷史突破：" + "；".join(f"{d} {s}" for d, s in result.events))
    else:
        st.caption("已載入且可判讀的視窗內尚無突破事件；不代表完整歷史沒有事件。")
    st.caption(
        "僅觀察已完成日線，不是買賣建議。公司行動與交易日涵蓋尚未完整核驗；"
        "無重大跳變不代表資料資格通過，正式 Scenario Research 仍未開放。"
    )
