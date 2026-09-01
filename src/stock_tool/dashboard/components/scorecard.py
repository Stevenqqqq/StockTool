"""Explainable score presentation for the Research Workspace."""

from __future__ import annotations

from typing import Any

from stock_tool.application.research_snapshot import ResearchSnapshot


def render_scorecard(st: Any, snapshot: ResearchSnapshot) -> None:
    """Render canonical score components without substituting missing values."""

    st.subheader("評分解釋")
    if snapshot.composite_score is None:
        st.info("未形成完整總分；下方僅顯示已有資料的分項與覆蓋率。")
    else:
        st.caption("完整總分使用既有權重：技術 30%、基本面 30%、估值 20%、風險 20%。")
    for component in snapshot.component_scores:
        score = "資料不足" if component.score == "unknown" else f"{float(component.score):.1f} 分"
        contribution = snapshot.component_contributions.get(component.name)
        contrib_str = f"{float(contribution):.1f} 分" if contribution is not None else "資料不足"
        with st.container(border=True):
            st.markdown(f"**{component.name}** · 權重 {component.weight:.0f}% · 貢獻 {contrib_str}")
            st.write(f"分項得分：{score}")
            for reason in component.reasons:
                st.caption(f"指標判斷：{reason}")
            for missing in component.missing_data:
                st.caption(f"缺少資料：{missing}")

    # Deduplicate strengths and ensure reasons don't duplicate into weaknesses
    seen_reasons: set[str] = set()
    filtered_strengths: list[str] = []
    for item in snapshot.strengths:
        text = str(item).strip()
        if text and text not in seen_reasons:
            seen_reasons.add(text)
            filtered_strengths.append(text)

    filtered_weaknesses: list[str] = []
    for item in snapshot.weaknesses:
        text = str(item).strip()
        if text and text not in seen_reasons:
            seen_reasons.add(text)
            filtered_weaknesses.append(text)

    if filtered_strengths:
        st.markdown("**研究優點**")
        for item in filtered_strengths:
            st.write(f"- {item}")
    if filtered_weaknesses:
        st.markdown("**缺點與限制**")
        for item in filtered_weaknesses:
            st.write(f"- {item}")
