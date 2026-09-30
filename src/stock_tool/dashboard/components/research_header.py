"""Header primitives for the Research Workspace."""

from __future__ import annotations

from typing import Any

from stock_tool.application.research_snapshot import ResearchSnapshot, ResearchSnapshotStatus
from stock_tool.dashboard.presentation_mapper import (
    format_currency,
    format_iso_datetime,
    format_market_label,
    format_percentage,
    format_status_label,
    format_taiwan_company_display,
)
from stock_tool.domain.models import MissingDataState


def render_research_header(st: Any, snapshot: ResearchSnapshot) -> None:
    """Render identity, separated model coverage, and company-data status.

    The score model and the company dossier answer different questions.  Keep
    them visibly separate so a fully computable score cannot imply that the
    company's public disclosures were fully reviewed.
    """

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

    status_zh = _research_status_label(snapshot)
    market_zh = format_market_label(snapshot.symbol.market.value)
    st.caption(f"{snapshot.symbol.code} · {market_zh} · " f"研究狀態：{status_zh}")
    price = snapshot.price
    columns = st.columns(4)
    currency = "TWD" if snapshot.symbol.market.value in {"TWSE", "TPEX"} else "USD"
    # ``st.metric`` truncates long labels/values in narrow columns.  Markdown
    # keeps the value wrapped and makes the unit/meaning explicit on both wide
    # and narrow layouts.
    _wrapped_value(
        columns[0],
        "最新可用收盤價",
        format_currency(price.latest_close, currency=currency) if price else "資料不足",
    )
    _wrapped_value(
        columns[1],
        "最後資料日期",
        format_iso_datetime(price.last_data_date) if price else "資料不足",
    )
    columns[2].metric(
        "指標模型分數",
        (
            f"{snapshot.composite_score:.1f} 分"
            if snapshot.composite_score is not None
            else "資料不足"
        ),
    )
    _wrapped_value(
        columns[3],
        "評分項目覆蓋率（依權重）",
        (
            format_percentage(snapshot.score_coverage, is_ratio=True)
            if snapshot.score_coverage is not None
            else "資料不足"
        ),
    )
    st.caption(
        "指標模型只反映目前可計算的技術、基本面、估值與風險指標權重；"
        "不代表公司介紹、官方文件、財報期間的完整性或新鮮度。"
    )
    _render_company_data_status(st, snapshot)
    st.caption(
        f"資料來源：{snapshot.source_metadata.provider or '資料不足'}；"
        f"類型：{format_status_label(snapshot.source_metadata.source_type)}；"
        f"實際查詢代號：{snapshot.source_metadata.query_symbol or '資料不足'}。"
    )
    if snapshot.principal_risks:
        st.caption(f"主要風險：{snapshot.principal_risks[-1]}")


def _research_status_label(snapshot: ResearchSnapshot) -> str:
    """Describe what the current snapshot can support without overstating it."""

    if snapshot.error_message or snapshot.status is ResearchSnapshotStatus.ERROR:
        return f"錯誤：{snapshot.error_message or '研究資料載入失敗。'}"

    # A missing price prevents the page from being a usable stock snapshot;
    # this takes precedence over company-profile messages and stale markers.
    if (
        snapshot.status is ResearchSnapshotStatus.INSUFFICIENT_DATA
        or snapshot.price is None
    ):
        reason = _missing_reason(snapshot, "price_data") or "沒有可用的價格資料。"
        return f"資料不足：{reason}"

    stale_reason = _stale_reason(snapshot)
    if stale_reason:
        return f"資料可能過期：{stale_reason}"

    profile = snapshot.company_profile
    if profile is None:
        reason = (
            _missing_reason(snapshot, "company_profile") or "沒有可驗證的公司介紹資料。"
        )
        return f"部分可用：{reason}"

    dossier = profile.dossier
    if dossier is None:
        return "部分可用：僅有基本公司資料，尚未取得可核對的官方公司文件。"
    if not dossier.documents:
        return "部分可用：尚未取得可核對的官方公司頁面。"
    if dossier.gaps:
        return f"部分可用：公司資料仍有缺口：{dossier.gaps[0]}"

    if snapshot.status is ResearchSnapshotStatus.PARTIAL:
        partial_reason = _first_research_gap(snapshot)
        return f"部分可用：{partial_reason or '部分研究資料尚未取得。'}"

    return "目前資料可供研究（範圍有限）"


def _missing_reason(snapshot: ResearchSnapshot, field: str) -> str | None:
    """Return the first concrete reason for one missing snapshot field."""

    for item in snapshot.missing_data:
        if item.field == field:
            return item.reason
    return None


def _stale_reason(snapshot: ResearchSnapshot) -> str | None:
    """Return a real freshness reason from snapshot or dossier state."""

    stale_items = [
        item.reason for item in snapshot.missing_data if item.state is MissingDataState.STALE
    ]
    if stale_items:
        return stale_items[0]
    dossier = snapshot.company_profile.dossier if snapshot.company_profile is not None else None
    if dossier is not None and dossier.state == "stale":
        return "公司官方資料更新未完成，畫面保留前次資料。"
    if snapshot.status is ResearchSnapshotStatus.STALE:
        return "部分資料已標示為過期。"
    return None


def _first_research_gap(snapshot: ResearchSnapshot) -> str | None:
    """Return a user-facing missing-data reason excluding company identity."""

    for item in snapshot.missing_data:
        if (
            item.field != "company_profile"
            and item.state is not MissingDataState.STALE
        ):
            return item.reason
    return None


def _wrapped_value(container: Any, label: str, value: str) -> None:
    """Render a labelled value without Streamlit metric truncation."""

    container.markdown(f"**{label}**\n\n{value}")


def _render_company_data_status(st: Any, snapshot: ResearchSnapshot) -> None:
    """Show company disclosure availability independently of model coverage."""

    profile = snapshot.company_profile
    if profile is None:
        missing = next(
            (item for item in snapshot.missing_data if item.field == "company_profile"),
            None,
        )
        reason = missing.reason if missing is not None else "尚未取得可驗證的公司介紹資料。"
        st.warning(f"公司資料狀態：資料不足。{reason}")
        return

    dossier = profile.dossier
    if dossier is None:
        st.info(
            "公司資料狀態：僅有基本資料，尚未取得可核對的官方公司文件；"
            "不能視為完整公司研究。"
        )
        return

    if dossier.state == "stale":
        st.warning("公司資料狀態：保留前次官方資料，這次更新未完成，不能視為最新。")

    document_count = len(dossier.documents)
    fact_count = len(dossier.facts)
    if document_count:
        st.caption(
            f"公司資料狀態：已取得 {document_count} 個官方頁面，整理出 {fact_count} 項可核對內容；"
            "頁面範圍有限，不以此宣稱公司資料完整。"
        )
    else:
        st.warning(
            "公司資料狀態：已有公司資料檔，但尚未取得可核對的官方頁面；"
            "不能視為完整公司研究。"
        )

    if dossier.gaps:
        st.caption("仍缺或未完成：" + "；".join(dossier.gaps))
