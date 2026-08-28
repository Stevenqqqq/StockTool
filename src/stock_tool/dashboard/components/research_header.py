"""Header primitives for the Research Workspace."""

from __future__ import annotations

from typing import Any

from stock_tool.application.research_snapshot import ResearchSnapshot


def render_research_header(st: Any, snapshot: ResearchSnapshot) -> None:
    """Render identity, latest available price, freshness, and score coverage."""

    name = snapshot.company_name or snapshot.symbol.code
    st.title(name)
    st.caption(
        f"{snapshot.symbol.code} · {snapshot.symbol.market.value} · "
        f"研究狀態：{snapshot.status.value}"
    )
    price = snapshot.price
    columns = st.columns(4)
    columns[0].metric("最新可用收盤", _number(price.latest_close) if price else "資料不足")
    columns[1].metric("最後資料日期", price.last_data_date if price else "資料不足")
    columns[2].metric(
        "完整研究分數",
        _number(snapshot.composite_score) if snapshot.composite_score is not None else "資料不足",
    )
    columns[3].metric(
        "資料覆蓋率",
        f"{snapshot.score_coverage:.0%}" if snapshot.score_coverage is not None else "資料不足",
    )
    st.caption(
        f"資料來源：{snapshot.source_metadata.provider or '資料不足'}；"
        f"類型：{snapshot.source_metadata.source_type}；"
        f"實際查詢代號：{snapshot.source_metadata.query_symbol or '資料不足'}。"
    )
    if snapshot.principal_risks:
        st.caption(f"主要風險：{snapshot.principal_risks[-1]}")


def _number(value: float | None) -> str:
    return "資料不足" if value is None else f"{value:,.2f}"
