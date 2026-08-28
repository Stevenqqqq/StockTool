"""Research Library workspace with immutable saved-version and current-data actions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from stock_tool.dashboard.components.data_quality import build_data_evidence, render_data_quality
from stock_tool.research.library import (
    ResearchLibrary,
    ResearchLibraryRestoreError,
    ResolvedResearchDocument,
)


def _display_optional_text(value: object) -> str:
    """Render missing saved metadata without exposing Python's None sentinel."""

    if value is None:
        return "無資料"
    text = str(value).strip()
    return text if text and text.casefold() != "none" else "無資料"


def render_library_workspace(
    st: Any,
    *,
    source: Mapping[str, Any] | None,
    provider_health: Iterable[Mapping[str, Any]] = (),
    library: ResearchLibrary | None = None,
    on_current_research: Callable[[str, str], None] | None = None,
) -> bool:
    """Render the Library page without coupling saved-version viewing to providers."""

    force_refresh = render_data_quality(st, build_data_evidence(source, health=provider_health))
    if library is None:
        return force_refresh

    st.subheader("研究庫")
    st.caption("研究庫保存可驗證的研究版本；查看保存版本不會抓取目前市場資料。")
    symbol = st.text_input("代號篩選", key="library_symbol_filter")
    market = st.selectbox("市場篩選", ("", "TWSE", "TPEX", "US"), key="library_market_filter")
    title = st.text_input("標題篩選", key="library_title_filter")
    entries = library.search(symbol=symbol or None, market=market or None, title=title or None)
    for warning in library.warnings:
        st.warning(warning)
    if not entries:
        st.info("目前沒有符合條件的保存研究版本。")

    for entry in entries:
        with st.expander(f"{entry.title}｜{entry.symbol}（{entry.market}）｜版本 {entry.version}"):
            st.caption(
                f"保存時間：{_display_optional_text(entry.created_at)}｜資料截至：{_display_optional_text(entry.data_as_of)}｜"
                f"模式：{_display_optional_text(entry.note.mode)}｜覆蓋率：{_display_optional_text(entry.note.coverage)}"
            )
            st.write("資料來源：" + ("、".join(entry.sources) or "無資料"))
            for warning in (*entry.note.warnings, *entry.note.missing_data):
                st.caption(f"警告／資料限制：{warning}")
            if st.button("查看保存版本", key=f"library_open_{entry.library_entry_id}"):
                st.session_state["dashboard_library_saved_entry_id"] = entry.library_entry_id
                st.rerun()
            if st.button("以此代號研究目前資料", key=f"library_current_{entry.library_entry_id}"):
                if on_current_research is not None:
                    on_current_research(entry.symbol, entry.market)
                else:
                    # Compatibility path for isolated callers; the dashboard
                    # shell uses the typed handoff callback above.
                    st.session_state["dashboard_library_current_research"] = {
                        "symbol": entry.symbol,
                        "market": entry.market,
                    }
                st.rerun()
            if st.checkbox(
                "確認刪除保存版本",
                key=f"library_delete_confirm_{entry.library_entry_id}",
            ) and st.button("刪除保存版本", key=f"library_delete_{entry.library_entry_id}"):
                library.delete(entry.library_entry_id)
                st.rerun()

    selected_entry_id = st.session_state.get("dashboard_library_saved_entry_id")
    if isinstance(selected_entry_id, str):
        selected_entry = library.get(selected_entry_id)
        if selected_entry is None:
            st.warning("保存版本無法使用，或完整性驗證失敗。")
            st.session_state.pop("dashboard_library_saved_entry_id", None)
        else:
            _render_saved_entry(
                st,
                selected_entry,
                document_resolutions=library.resolve_document_references(selected_entry),
            )
            if st.button("關閉保存版本", key="library_close_saved_version"):
                st.session_state.pop("dashboard_library_saved_entry_id", None)
                st.rerun()

    st.divider()
    st.caption(
        "備份只包含研究庫 JSON 與文件引用 metadata，不包含文件內容、持股、自選股或行情快取。"
    )
    if st.button("建立研究庫備份", key="library_backup"):
        backup = library.create_backup(
            library.directory.parent / "backups" / "research-library-backup.zip"
        )
        st.success(f"備份完成：{backup.archive_path.name}")
    uploaded = st.file_uploader("選擇研究庫備份", type=["zip"], key="library_restore_upload")
    if (
        uploaded is not None
        and st.checkbox("確認還原研究庫備份", key="library_restore_confirm")
        and st.button("還原研究庫備份", key="library_restore")
    ):
        candidate = library.directory.parent / ".research-library-restore-upload.zip"
        candidate.write_bytes(uploaded.getvalue())
        try:
            library.restore(candidate)
            st.success("研究庫備份還原完成。")
        except ResearchLibraryRestoreError:
            st.error("研究庫備份驗證失敗，現有資料未被取代。")
        finally:
            candidate.unlink(missing_ok=True)
    return force_refresh


def _render_saved_entry(
    st: Any,
    entry: Any,
    *,
    document_resolutions: Sequence[ResolvedResearchDocument] = (),
) -> None:
    """Render immutable persisted content only; this function has no provider inputs."""

    st.divider()
    st.subheader("保存的研究版本")
    st.caption(
        f"{entry.symbol}（{entry.market}）｜版本 {entry.version}｜保存時間 {_display_optional_text(entry.created_at)}｜"
        f"資料截至 {_display_optional_text(entry.data_as_of)}"
    )
    st.caption(
        f"模式：{_display_optional_text(entry.note.mode)}｜信心：{_display_optional_text(entry.note.confidence_label)}｜"
        f"覆蓋率：{_display_optional_text(entry.note.coverage)}"
    )
    st.write("資料來源：" + ("、".join(entry.sources) or "無資料"))

    if entry.document_reference_integrity == "legacy_unverified":
        st.warning("警告：此舊版文件引用未受完整性保護，已安全略過。")

    for document in document_resolutions:
        reference = document.reference
        if document.status == "available" and reference is not None:
            status = "可用"
            title = reference.title
        elif document.status == "changed":
            status = "文件內容已變更（引用失效）"
            title = reference.title if reference is not None else "缺少文件"
        else:
            status = "文件遺失（引用失效）"
            title = reference.title if reference is not None else "缺少文件"
        page = f"第 {document.link.page} 頁" if document.link.page is not None else "未指定頁碼"
        st.caption(f"文件標題：{title}｜狀態：{status}｜頁碼引用：{page}")

    citations = {citation.evidence_id: citation for citation in entry.note.citations}
    for claim in entry.note.claims:
        kind_label = {
            "fact": "事實",
            "opinion": "觀點",
            "risk": "風險",
            "unknown": "其他",
        }.get(claim.kind.value, "研究主張")
        st.markdown(f"**{kind_label}｜{claim.section}**")
        st.write(claim.text)
        for evidence_id in claim.citation_ids:
            citation = citations.get(evidence_id)
            if citation is None:
                st.warning(f"缺少保存的引用資料：{evidence_id}")
                continue
            st.caption(
                "引用："
                f"{citation.evidence_id}｜來源：{_display_optional_text(citation.source)}｜"
                f"提供者：{_display_optional_text(citation.provider)}｜摘錄：{_display_optional_text(citation.excerpt)}"
            )
            if citation.url:
                st.caption(f"參考網址：{citation.url}")
    for missing in entry.note.missing_data:
        st.caption(f"資料缺口／限制：{missing}")
    for warning in entry.note.warnings:
        st.caption(f"警告：{warning}")
