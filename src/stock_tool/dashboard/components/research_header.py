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
from stock_tool.dashboard.instrument_names import current_names, name_notice
from stock_tool.company_explanation import explain_company
from stock_tool.application.breakout_observation import observe_breakout
from stock_tool.dashboard.components.price_volume_observation import observation_summary


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

    market_zh = format_market_label(snapshot.symbol.market.value)
    st.write(f"{snapshot.symbol.code} · {market_zh}")
    status_zh = _research_status_label(snapshot)
    st.warning(f"研究狀態：{status_zh}")
    notice = name_notice(snapshot.symbol.market.value, snapshot.symbol.code)
    if notice:
        st.caption(
            "名稱：" + ("沿用前次確認；不代表研究已更新。" if "沿用前次" in notice else notice)
        )

    dossier = snapshot.company_profile.dossier if snapshot.company_profile else None
    if dossier is not None and (dossier.symbol, dossier.market) != (
        snapshot.symbol.code,
        snapshot.symbol.market.value,
    ):
        dossier = None
    explanations = explain_company(dossier) if dossier is not None else ()
    if explanations:
        # Use existing explanation sentences verbatim, never a new model/inference.
        sentences = explanations[0].text.split("。")
        business = sentences[0].rstrip("。") + "。"
    else:
        business = "公司業務證據尚不足，不能只靠名稱或產業猜測。"

    price = snapshot.price
    simulated = _simulated_prices(snapshot)
    if simulated:
        st.warning("模擬資料／Synthetic：以下價格與價量觀察僅供測試，不是真實行情。")
    currency = "TWD" if snapshot.symbol.market.value in {"TWSE", "TPEX"} else "USD"
    columns = st.columns(2)
    _wrapped_value(
        columns[0],
        "模擬收盤價（測試資料）" if simulated else "最新可用收盤價",
        format_currency(price.latest_close, currency=currency) if price else "資料不足",
    )
    _wrapped_value(
        columns[1],
        "最後資料日期",
        format_iso_datetime(price.last_data_date) if price else "資料不足",
    )
    st.caption(
        f"行情來源：{snapshot.source_metadata.provider or '未確認'}；"
        "以上為已載入的最新有效日線，可能落後交易所；不是即時報價。"
    )
    if snapshot.source_metadata.provider == "yfinance":
        st.caption(
            "使用 Yahoo Close／OHLC 與成交量，不使用 Adj Close 計算此處價量指標。"
            "歷史價格可能已由來源調整分割，量能口徑未必等同交易所總成交量；不混接其他來源。"
        )
    for notice in snapshot.source_metadata.warnings:
        if notice.startswith("收盤研究："):
            st.info(notice)
    _render_focus(st, snapshot, business=business)
    if snapshot.composite_score is None and snapshot.available_score is not None:
        st.write(
            f"可用項目評分：{snapshot.available_score:.1f} 分；"
            f"評分項目覆蓋率 {format_percentage(snapshot.score_coverage, is_ratio=True)}。"
            "僅按已具備項目換算，並非完整總分；分項見「評分解釋」。"
        )
    elif snapshot.price is not None and snapshot.composite_score is not None:
        st.caption(
            f"既有指標模型：{snapshot.composite_score:.1f} 分；不代表公司證據完整，"
            "分項依據見「評分解釋」。"
        )
    question = (
        dossier.questions[0]
        if dossier is not None and dossier.questions
        else "先補齊可核對的公司官方文件與資料日期。"
    )
    st.markdown("**優先待查｜接下來先確認（待查，非已確認事實）**\n\n" + question)
    _render_focus_sources(st, snapshot)
    gaps = _visible_gaps(snapshot)
    # Keep material gaps visible once; the full repeated technical text belongs below.
    additional_gaps = _visible_gaps(snapshot, exclude_text=status_zh, compact=True)
    if additional_gaps:
        st.caption("待補資料：" + "；".join(additional_gaps))
    if gaps:
        st.caption(
            "補救方式：公司內容可按「重新讀取公司資料」；評分缺項請到「評分解釋」核對所需欄位。"
        )

    with st.expander("核對來源、完整限制與指標分數"):
        for gap in gaps:
            st.write(f"• {gap}")
        directory = current_names.get()
        if directory is not None:
            record, _ = directory.resolve(snapshot.symbol.market.value, snapshot.symbol.code)
            if record is not None:
                st.write(record.full_name or record.name)
                st.caption(
                    f"名稱資料日期：{record.data_date}；取得：{record.fetched_at[:10]}（與行情日期分開）"
                )
                st.link_button("官方中文名稱來源", record.source)
        if notice:
            st.info(notice)
        _render_company_data_status(st, snapshot)
        for reason in dict.fromkeys(item.reason for item in snapshot.missing_data):
            st.write(f"• {reason}")
        if explanations and dossier is not None:
            st.write(explanations[0].text)
            for index in dict.fromkeys(explanations[0].evidence_indices):
                fact = dossier.facts[index]
                st.caption(
                    f"公司原文發布：{fact.published_at or '日期未知'}；取得：{fact.fetched_at}。"
                )
                st.link_button("核對業務來源", fact.url)
        columns = st.columns(2)
        columns[0].metric(
            "指標模型分數",
            (
                f"{snapshot.composite_score:.1f} 分"
                if snapshot.composite_score is not None
                else "資料不足"
            ),
        )
        _wrapped_value(
            columns[1],
            "評分項目覆蓋率（依權重）",
            (
                format_percentage(snapshot.score_coverage, is_ratio=True)
                if snapshot.score_coverage is not None
                else "資料不足"
            ),
        )
        st.caption(
            "指標模型只反映目前可計算的技術、基本面、估值與風險指標權重；不代表公司介紹、官方文件、財報期間的完整性或新鮮度。"
        )
        st.caption(
            f"資料來源：{snapshot.source_metadata.provider or '資料不足'}；類型：{format_status_label(snapshot.source_metadata.source_type)}；實際查詢代號：{snapshot.source_metadata.query_symbol or '資料不足'}。"
        )
        for risk in snapshot.principal_risks:
            st.write(f"• {risk}")


def _simulated_prices(snapshot: ResearchSnapshot) -> bool:
    """Keep sample provenance visible even if a different source label was cached."""
    labels = [snapshot.source_metadata.provider, snapshot.source_metadata.source_type]
    frame = snapshot.price_history
    if frame is not None and "provider" in frame:
        labels.extend(frame.provider.dropna().unique())
    return snapshot.symbol.code.startswith("SYNTH_") or any(
        any(marker in str(label).lower() for marker in ("synthetic", "sample", "模擬", "範例"))
        for label in labels
    )


def _render_focus(st: Any, snapshot: ResearchSnapshot, *, business: str) -> None:
    """Arrange existing findings; no new score, prediction or company inference."""
    st.markdown("#### 目前觀察")
    st.markdown("**這家公司做什麼**　" + business)
    result = observe_breakout(snapshot)
    st.write(f"突破觀察：{result.status}｜觀測日：{result.date or '未確認'}")
    if result.reference is not None and result.distance is not None:
        st.write(
            f"前20日高點 {result.reference:,.2f}；收盤相距 {result.distance:+.2%}；"
            f"當日量／此前20日均量 {result.volume_ratio:.2f} 倍。"
        )
    else:
        # A pattern gap must not suppress otherwise available close/SMA/volume.
        for text in observation_summary(snapshot)[:2]:
            st.write(text)
        if result.reason:
            st.caption("突破判讀缺口：" + result.reason)

    st.markdown("#### 支持與反向證據")
    st.caption("只核對既有突破條件；不是看多／看空評級，缺資料也不是反向證據。")
    supports = [
        c for c in result.conditions if c.startswith(("量能 達標", "收盤 高於", "SMA20 向上"))
    ]
    counters = [
        c for c in result.conditions if c.startswith(("量能 未達標", "收盤 未高於", "SMA20 未向上"))
    ]
    left, right = st.columns(2)
    for column, heading, items in (
        (left, "已符合的條件", supports),
        (right, "尚未符合的條件", counters),
    ):
        text = "\n\n".join("• " + item for item in items)
        if not text:
            text = "尚無可判讀證據。" if result.reason else "本次沒有此類條件。"
        column.markdown(f"**{heading}**\n\n{text}")
    if snapshot.price is not None and snapshot.weaknesses:
        st.write("既有評分提醒（非新增判斷）：" + snapshot.weaknesses[0])


def _render_focus_sources(st: Any, snapshot: ResearchSnapshot) -> None:
    """Retain original evidence dates separately after the three reading priorities."""
    st.caption(
        f"價量依據：{snapshot.symbol.canonical}／{snapshot.source_metadata.provider or '來源未確認'}；"
        f"完成日線截至 {snapshot.price.last_data_date if snapshot.price else '未確認'}；"
        f"取得：{snapshot.source_metadata.fetched_at or '未確認'}。詳細價量與來源見總覽／證據頁籤。"
    )
    profile = snapshot.company_profile
    dossier = profile.dossier if profile else None
    if dossier is not None and (dossier.symbol, dossier.market) == (
        snapshot.symbol.code,
        snapshot.symbol.market.value,
    ):
        facts = [f for f in dossier.facts if f.section == "公司揭露的風險"]
        if facts:
            fact = facts[0]
            st.write("公司風險原文（需核對是否仍適用）：" + fact.statement)
            st.caption(f"發布：{fact.published_at or '日期未知'}；取得：{fact.fetched_at}。")
            st.link_button("核對這項風險來源", fact.url)
        explanations = explain_company(dossier)
        if explanations and explanations[0].evidence_indices:
            used = [dossier.facts[i] for i in explanations[0].evidence_indices]
            dates = "、".join(dict.fromkeys(f.published_at or "日期未知" for f in used))
            fetched = "、".join(
                dict.fromkeys(f.fetched_at.split("T", 1)[0] or "未確認" for f in used)
            )
            st.caption(
                f"公司業務證據發布日：{dates}；原文取得日（依來源時間）：{fetched}。"
                "與行情日期分開；完整時間及原文見下方「核對來源」。"
            )


def _visible_gaps(
    snapshot: ResearchSnapshot, *, exclude_text: str = "", compact: bool = False
) -> tuple[str, ...]:
    """Compress known repetitive disclosures; retain unknown gaps in full."""
    profile = snapshot.company_profile
    dossier = profile.dossier if profile is not None else None
    reasons = [item.reason for item in snapshot.missing_data]
    if dossier is not None:
        reasons.extend(dossier.gaps)
    labels = []
    mappings = (
        ("尚未取得足夠的公司揭露的風險公司證據", "公司風險原文不足"),
        ("產品列示不代表已量產", "產品列示不等於量產、供貨或主要營收"),
        ("尚未逐一核對最新財報分部占比及完整年報", "最新財報分部占比與完整年報未核對"),
        ("部分頁面未提供發布／生效日期", "部分文件日期未知，不能確認最新"),
        ("本次已達頁數或時間上限", "未讀完全部官網／文件"),
        ("畫面與 AI 共用精選的公司證據", "僅整理精選證據"),
        ("既有評分模型缺少此必要資料", "評分資料不足，不能形成完整總分"),
    )
    for reason in reasons:
        if reason and reason in exclude_text:
            continue
        if compact and reason.startswith(
            ("產品列示不代表已量產", "本次已達頁數或時間上限", "畫面與 AI 共用精選的公司證據")
        ):
            continue
        label = next((short for prefix, short in mappings if reason.startswith(prefix)), reason)
        if label not in labels:
            labels.append(label)
    stale = _stale_reason(snapshot)
    if stale and stale not in labels and stale not in exclude_text:
        labels.insert(0, stale)
    return tuple(labels)


def _research_status_label(snapshot: ResearchSnapshot) -> str:
    """Describe what the current snapshot can support without overstating it."""

    if snapshot.error_message or snapshot.status is ResearchSnapshotStatus.ERROR:
        return f"錯誤：{snapshot.error_message or '研究資料載入失敗。'}"

    # A missing price prevents the page from being a usable stock snapshot;
    # this takes precedence over company-profile messages and stale markers.
    if snapshot.status is ResearchSnapshotStatus.INSUFFICIENT_DATA or snapshot.price is None:
        reason = _missing_reason(snapshot, "price_data") or "沒有可用的價格資料。"
        return f"資料不足：{reason}"

    stale_reason = _stale_reason(snapshot)
    if stale_reason:
        return f"資料可能過期：{stale_reason}"

    profile = snapshot.company_profile
    if profile is None:
        reason = _missing_reason(snapshot, "company_profile") or "沒有可驗證的公司介紹資料。"
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
        if item.field != "company_profile" and item.state is not MissingDataState.STALE:
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
            "公司資料狀態：僅有基本資料，尚未取得可核對的官方公司文件；" "不能視為完整公司研究。"
        )
        return

    if dossier.state == "stale":
        st.warning("公司資料狀態：保留前次官方資料，這次更新未完成，不能視為最新。")

    document_count = len(dossier.documents)
    fact_count = len(dossier.facts)
    if document_count:
        st.write(
            f"公司資料狀態：已取得 {document_count} 個官方頁面，整理出 {fact_count} 項可核對內容；"
            "頁面範圍有限，不以此宣稱公司資料完整。"
        )
    else:
        st.warning(
            "公司資料狀態：已有公司資料檔，但尚未取得可核對的官方頁面；" "不能視為完整公司研究。"
        )

    if dossier.gaps:
        st.warning("仍缺或未完成：" + "；".join(dossier.gaps))
