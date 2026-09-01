"""Evidence and provenance presentation for Research Workspace snapshots."""

from __future__ import annotations

from typing import Any

import pandas as pd

from stock_tool.application.research_snapshot import EvidenceKind, ResearchSnapshot
from stock_tool.dashboard.presentation_mapper import (
    deduplicate_warnings,
    format_iso_datetime,
    format_percentage,
    format_status_label,
)


def render_evidence_panel(st: Any, snapshot: ResearchSnapshot) -> None:
    """Render facts, calculations, and inferences in separate labelled rows."""

    st.subheader("證據與資料來源")
    metadata = snapshot.source_metadata

    # Summary overview metrics
    cols = st.columns(4)
    cols[0].metric("資料來源", metadata.provider or "資料不足")
    cols[1].metric("已載入筆數", str(metadata.row_count))
    cols[2].metric("最後資料日期", format_iso_datetime(metadata.last_data_date))
    cols[3].metric(
        "分數覆蓋率",
        (
            format_percentage(snapshot.score_coverage, is_ratio=True)
            if snapshot.score_coverage is not None
            else "資料不足"
        ),
    )

    st.caption(
        f"資料類別：{format_status_label(metadata.source_type)}｜"
        f"查詢代號：{metadata.query_symbol or snapshot.symbol.code}｜"
        f"取得時間：{format_iso_datetime(metadata.fetched_at)}"
    )

    rows = [
        {
            "類別": _kind_label(item.kind),
            "項目": item.label,
            "內容": item.text,
            "來源": item.source or "資料不足",
        }
        for item in snapshot.evidence_items
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    for warning in deduplicate_warnings(snapshot.warnings):
        st.warning(warning)
    for limitation in snapshot.limitations:
        st.caption(f"限制：{limitation}")
    if snapshot.missing_data:
        st.markdown("**缺少資料與補齊建議**")
        for item in snapshot.missing_data:
            state_zh = format_status_label(item.state.value)
            st.write(f"- {item.field}（{state_zh}）：{item.reason}")


def _kind_label(kind: EvidenceKind) -> str:
    labels = {
        EvidenceKind.FACT: "事實資料",
        EvidenceKind.CALCULATION: "研究計算",
        EvidenceKind.RESEARCH_INFERENCE: "研究推論",
    }
    return labels[kind]
