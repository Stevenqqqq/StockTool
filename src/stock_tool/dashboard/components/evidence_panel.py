"""Evidence and provenance presentation for Research Workspace snapshots."""

from __future__ import annotations

from typing import Any

import pandas as pd

from stock_tool.application.research_snapshot import EvidenceKind, ResearchSnapshot


def render_evidence_panel(st: Any, snapshot: ResearchSnapshot) -> None:
    """Render facts, calculations, and inferences in separate labelled rows."""

    st.subheader("證據與資料來源")
    rows = [
        {
            "類別": _kind_label(item.kind),
            "項目": item.label,
            "內容": item.text,
            "來源": item.source or "資料不足",
        }
        for item in snapshot.evidence_items
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    metadata = snapshot.source_metadata
    st.caption(
        f"資料筆數：{metadata.row_count}；最後資料日期："
        f"{metadata.last_data_date or '資料不足'}；取得時間：{metadata.fetched_at or '未記錄'}。"
    )
    for warning in snapshot.warnings:
        st.warning(warning)
    for limitation in snapshot.limitations:
        st.caption(f"限制：{limitation}")
    if snapshot.missing_data:
        st.markdown("**缺少資料**")
        for item in snapshot.missing_data:
            st.write(f"- {item.field}（{item.state.value}）：{item.reason}")


def _kind_label(kind: EvidenceKind) -> str:
    labels = {
        EvidenceKind.FACT: "事實資料",
        EvidenceKind.CALCULATION: "研究計算",
        EvidenceKind.RESEARCH_INFERENCE: "研究推論",
    }
    return labels[kind]
