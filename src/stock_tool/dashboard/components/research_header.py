"""Header primitives for the Research Workspace."""

from __future__ import annotations

from typing import Any

from stock_tool.application.research_snapshot import ResearchSnapshot
from stock_tool.dashboard.presentation_mapper import (
    format_currency,
    format_iso_datetime,
    format_market_label,
    format_percentage,
    format_status_label,
    format_taiwan_company_display,
)


def render_research_header(st: Any, snapshot: ResearchSnapshot) -> None:
    """Render identity, latest available price, freshness, and score coverage."""

    known_name = format_taiwan_company_display(
        snapshot.symbol.code,
        snapshot.company_name,
        market=snapshot.symbol.market.value,
    )
    if "(" in known_name and known_name.endswith(f"({snapshot.symbol.code})"):
        name = known_name.rsplit(" (", 1)[0]
    else:
        name = snapshot.company_name or known_name
    st.title(name)

    status_zh = format_status_label(snapshot.status.value)
    market_zh = format_market_label(snapshot.symbol.market.value)
    st.caption(f"{snapshot.symbol.code} · {market_zh} · " f"研究狀態：{status_zh}")
    price = snapshot.price
    columns = st.columns(4)
    currency = "TWD" if snapshot.symbol.market.value in {"TWSE", "TPEX"} else "USD"
    columns[0].metric(
        "最新可用收盤",
        format_currency(price.latest_close, currency=currency) if price else "資料不足",
    )
    columns[1].metric(
        "最後資料日期",
        format_iso_datetime(price.last_data_date) if price else "資料不足",
    )
    columns[2].metric(
        "完整研究分數",
        (
            f"{snapshot.composite_score:.1f} 分"
            if snapshot.composite_score is not None
            else "資料不足"
        ),
    )
    columns[3].metric(
        "資料覆蓋率",
        (
            format_percentage(snapshot.score_coverage, is_ratio=True)
            if snapshot.score_coverage is not None
            else "資料不足"
        ),
    )
    st.caption(
        f"資料來源：{snapshot.source_metadata.provider or '資料不足'}；"
        f"類型：{format_status_label(snapshot.source_metadata.source_type)}；"
        f"實際查詢代號：{snapshot.source_metadata.query_symbol or '資料不足'}。"
    )
    if snapshot.principal_risks:
        st.caption(f"主要風險：{snapshot.principal_risks[-1]}")
