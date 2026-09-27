"""Research Workspace page built from one immutable application snapshot."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any

from stock_tool.application.research_library import (
    DocumentCitationSelection,
    ResearchLibraryApplicationService,
)
from stock_tool.application.research_snapshot import ResearchSnapshot
from stock_tool.dashboard.components.evidence_panel import render_evidence_panel
from stock_tool.dashboard.components.research_chart import (
    build_research_chart,
    render_research_chart,
)
from stock_tool.dashboard.components.research_header import render_research_header
from stock_tool.dashboard.components.risk_summary import render_risk_summary
from stock_tool.dashboard.components.scorecard import render_scorecard
from stock_tool.dashboard.components.search import render_global_search
from stock_tool.dashboard.state import SearchPreparation
from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
from stock_tool.research.evidence import build_evidence_bundle
from stock_tool.research.library import ResearchLibrary, ResearchLibraryError
from stock_tool.runtime_paths import default_runtime_paths

SCENARIO_REFERENCE_HEADING = "情境參考區間"


def render_research_workspace(
    st: Any,
    snapshot: ResearchSnapshot,
    *,
    library: ResearchLibrary | None = None,
    ai_cache_directory: Path | None = None,
    on_handoff: Callable[[str, ResearchSnapshot], None] | None = None,
) -> SearchPreparation | None:
    """Render a focused workspace without recalculating snapshot data in the UI."""

    render_research_header(st, snapshot)
    paths = default_runtime_paths()
    library = library or ResearchLibrary(paths.research_library_dir)
    library_service = ResearchLibraryApplicationService(library)
    bundle = build_evidence_bundle(snapshot)
    with st.expander("研究其他股票", expanded=False):
        preparation = render_global_search(
            st,
            key_prefix="research",
            default_symbol=snapshot.symbol.code,
            default_market=snapshot.symbol.market.value,
        )

    overview, chart_tab, fundamentals, scoring, evidence, risk = st.tabs(
        ("總覽", "圖表", "基本面", "評分解釋", "證據與資料", "風險與情境")
    )
    with overview:
        if snapshot.company_profile is not None and snapshot.company_profile.dossier is not None:
            _render_company_overview(st, snapshot, compact=True)
        else:
            company, chart = st.columns((1, 1))
            with company:
                _render_company_overview(st, snapshot, compact=True)
            with chart:
                _render_overview_chart(st, snapshot)
        render_risk_summary(st, snapshot)
    with chart_tab:
        _render_chart(st, snapshot)
    with fundamentals:
        _render_fundamentals(st, snapshot)
    with scoring:
        render_scorecard(st, snapshot)
    with evidence:
        render_evidence_panel(st, snapshot)
    with risk:
        render_risk_summary(st, snapshot)
    _render_save_research_controls(
        st,
        library_service,
        bundle=bundle,
        title=(snapshot.company_name or snapshot.symbol.code) + " 研究",
        ai_cache_directory=ai_cache_directory or paths.ai_research_dir,
    )
    if on_handoff is not None:
        _render_workspace_handoff_controls(st, snapshot, on_handoff=on_handoff)
    return preparation


def _render_workspace_handoff_controls(
    st: Any,
    snapshot: ResearchSnapshot,
    *,
    on_handoff: Callable[[str, ResearchSnapshot], None],
) -> None:
    """Offer explicit, non-mutating hand-offs to the other native workspaces."""

    st.subheader("接力到其他工作區")
    st.caption("接力只帶入同一市場與代號；不會自動抓資料、修改持股或保存研究。")
    columns = st.columns(3)
    actions = (
        (columns[0], "前往策略工作區", "strategy", "research_to_strategy"),
        (columns[1], "查看持倉（預填）", "holdings", "research_to_holdings"),
        (columns[2], "研究庫套用篩選", "library", "research_to_library"),
    )
    for column, label, destination, key in actions:
        with column:
            if st.button(label, key=key):
                on_handoff(destination, snapshot)


def _render_save_research_controls(
    st: Any,
    service: ResearchLibraryApplicationService,
    *,
    bundle: Any,
    title: str,
    ai_cache_directory: Path,
) -> None:
    """Keep optional save/document controls below the first-screen research evidence."""

    with st.expander("儲存研究與本機文件引用（可選）", expanded=False):
        document_selections, document_selection_error = _render_document_citation_controls(
            st,
            service,
            evidence_ids=tuple(record.evidence_id for record in bundle.evidence),
        )
        save_button = getattr(st, "button", None)
        if callable(save_button) and save_button("儲存至研究庫", key="research_save_to_library"):
            try:
                if document_selection_error:
                    raise ValueError("文件頁碼必須是正整數。")
                note = AIResearchAssistant(
                    cache=ResearchAssistantCache(ai_cache_directory)
                ).generate(bundle)
                entry = service.save_research(
                    bundle=bundle,
                    note=note,
                    title=title,
                    document_selections=document_selections,
                )
                st.success(f"已儲存研究庫版本 {entry.version}；儲存時間：{entry.created_at}。")
            except (ResearchLibraryError, ValueError):
                st.error("無法安全儲存研究；既有研究庫未被修改。")


def _render_document_citation_controls(
    st: Any,
    service: ResearchLibraryApplicationService,
    *,
    evidence_ids: tuple[str, ...],
) -> tuple[tuple[DocumentCitationSelection, ...], bool]:
    """Render a metadata-only local-path document workflow for saved research."""

    required = ("text_input", "multiselect", "checkbox", "caption", "subheader")
    if any(not callable(getattr(st, name, None)) for name in required):
        return (), False

    st.subheader("本機文件引用（可選）")
    st.caption(
        "請輸入原始文件的完整本機路徑後登錄。系統只保存路徑、標題與 SHA-256；"
        "不會上傳或複製文件內容，也不會把暫存上傳檔當成永久引用。"
    )
    source_path = st.text_input("原始文件完整路徑", key="research_document_source_path")
    title = st.text_input("文件標題（可留空）", key="research_document_title")
    register_button = getattr(st, "button", None)
    if callable(register_button) and register_button(
        "登錄本機文件", key="research_register_document"
    ):
        try:
            registered = service.register_local_document(source_path=source_path, title=title)
            st.success(f"已登錄文件：{registered.title}")
            rerun = getattr(st, "rerun", None)
            if callable(rerun):
                rerun()
        except (OSError, ValueError):
            st.error("無法登錄文件。請提供存在且可讀取的原始絕對路徑。")

    selections: list[DocumentCitationSelection] = []
    invalid_page = False
    try:
        documents = service.registered_local_documents()
    except ValueError:
        st.error("已登錄文件的 metadata 無法驗證，已安全略過。")
        return (), False
    for document in documents:
        status = {"available": "可用", "missing": "文件遺失", "changed": "文件內容已變更"}.get(
            document.status, "不可用"
        )
        st.caption(f"文件：{document.title}｜狀態：{status}｜原始路徑：{document.source_path}")
        if document.status != "available":
            continue
        selected = st.checkbox("引用此文件", key=f"research_document_use_{document.document_id}")
        if not selected:
            continue
        citation_ids = st.multiselect(
            "引用證據項目（Evidence IDs）",
            options=evidence_ids,
            key=f"research_document_citations_{document.document_id}",
        )
        page_text = st.text_input(
            "頁碼（可留空）", key=f"research_document_page_{document.document_id}"
        ).strip()
        page: int | None = None
        if page_text:
            try:
                page = int(page_text)
                if page < 1:
                    raise ValueError
            except ValueError:
                invalid_page = True
                st.warning("頁碼必須是正整數。")
        selections.append(
            DocumentCitationSelection(
                document_id=document.document_id,
                citation_ids=tuple(str(item) for item in citation_ids),
                page=page,
            )
        )
    return tuple(selections), invalid_page


def _render_company_overview(st: Any, snapshot: ResearchSnapshot, *, compact: bool = False) -> None:
    profile = snapshot.company_profile
    st.subheader("公司介紹")
    if profile is None:
        st.info("公司資料不足。請確認代號與市場，或補充可驗證的公開公司資料。")
        return
    if profile.dossier is not None:
        from stock_tool.dashboard.components.company_dossier import render_company_dossier

        st.write(f"{profile.company_name}（{profile.symbol}）")
        render_company_dossier(st, profile.dossier)
        return
    st.caption("公司名稱與產業分類標示為事實資料；業務與產業鏈內容標示為研究推論。")
    st.markdown("**事實資料**")
    st.write(f"公司名稱：{profile.company_name}")
    industry_str = (
        f"{profile.industry}／{profile.sector}"
        if profile.sector and profile.sector != profile.industry
        else profile.industry
    )
    st.write(f"產業類別：{industry_str or '資料不足'}")
    sources = [
        str(s).replace("online", "線上來源").replace("canonical", "標準格式")
        for s in profile.data_sources
    ]
    st.write(f"資料來源：{'；'.join(sources)}")
    st.markdown("**研究推論：主要業務與技術**")
    for item in (*profile.main_business, *profile.technical_features):
        st.write(f"- {item}")
    if compact:
        with st.expander("完整公司脈絡"):
            _render_company_inferences(st, profile)
    else:
        _render_company_inferences(st, profile)
    for limitation in profile.limitations:
        lim_text = (
            str(limitation)
            .replace("Point-in-time", "歷史切點（PIT）")
            .replace("point-in-time", "歷史切點（PIT）")
            .replace("online", "線上來源")
        )
        st.caption(f"限制：{lim_text}")


def _render_company_inferences(st: Any, profile: Any) -> None:
    st.markdown("**研究推論：產業鏈與應用**")
    for item in (*profile.linked_industries, *profile.current_applications):
        st.write(f"- {item}")
    st.markdown("**研究推論：瓶頸與待查證事項**")
    for item in (*profile.bottlenecks, *profile.additional_checks):
        st.write(f"- {item}")


def _render_overview_chart(st: Any, snapshot: ResearchSnapshot) -> None:
    st.subheader("價格圖")
    model = build_research_chart(
        snapshot.price_history,
        indicators=snapshot.indicators,
        period="1Y",
    )
    render_research_chart(st, model, compact=True)


def _render_chart(st: Any, snapshot: ResearchSnapshot) -> None:
    st.subheader("價格與成交量")
    period = st.selectbox("期間", ("6M", "1Y", "3Y", "MAX"), index=1, key="research_chart_period")
    columns = st.columns(2)
    show_sma20 = columns[0].checkbox("顯示 SMA20", value=True, key="research_chart_sma20")
    show_sma60 = columns[1].checkbox("顯示 SMA60", value=True, key="research_chart_sma60")
    model = build_research_chart(
        snapshot.price_history,
        indicators=snapshot.indicators,
        period=period,
        show_sma20=show_sma20,
        show_sma60=show_sma60,
    )
    render_research_chart(st, model)
    st.caption("研究圖表使用已載入資料，不宣稱即時行情。")


def _render_fundamentals(st: Any, snapshot: ResearchSnapshot) -> None:
    st.subheader("基本面")
    if snapshot.fundamental_results is None or snapshot.fundamental_results.empty:
        st.info("資料不足，尚無可用基本面結果。")
        return
    frame = snapshot.fundamental_results.copy(deep=True)
    cols = st.columns(3)
    cols[0].metric("指標項目筆數", str(len(frame)))
    if "date" in frame.columns or "日期" in frame.columns:
        date_col = "date" if "date" in frame.columns else "日期"
        latest_date = str(frame[date_col].iloc[-1])
        cols[1].metric("最新資料日期", str(latest_date)[:10])
    else:
        cols[1].metric("資料格式", "已驗證指標")
    cols[2].metric("覆蓋狀態", "可查核公開數據")

    st.markdown("#### 詳細財務指標數據")
    st.dataframe(frame, width="stretch", hide_index=True)
