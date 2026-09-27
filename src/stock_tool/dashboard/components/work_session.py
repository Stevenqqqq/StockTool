"""Local-first continuation of a holding and company research session."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Callable

from stock_tool.application.holding_analysis import HoldingAnalysis
from stock_tool.application.research_snapshot import ResearchSnapshot
from stock_tool.research.public_selection import (
    PUBLIC_QUESTIONS,
    select_public_evidence,
)
from stock_tool.research.public_request import PreparedPublicRequest, PublicResponse
from stock_tool.research.request_controller import ResearchRequestController
from stock_tool.research.work_session import (
    CombinedSnapshot,
    ResearchWorkSession,
    WorkSessionError,
    WorkSessionStore,
    combine_snapshots,
)
from stock_tool.runtime_paths import RuntimePaths


def render_ai_attempt(st: Any, session: ResearchWorkSession) -> None:
    """Show receipts as historical diagnostics, never as accepted research."""
    attempt = json.loads(session.ai_attempt_json)
    if attempt is None:
        return
    labels = {
        "unverified": "尚未通過引用語意驗證",
        "invalid": "回應失效",
        "failed": "請求失敗",
        "timed_out": "請求逾時",
        "superseded": "證據已變更，回應不適用",
        "model_reviewed": "已完成模型引用核對，仍須核對原文",
    }
    if attempt["status"] == "model_reviewed":
        st.info("AI 研究草稿：已完成第二次模型引用核對，並非人工驗證或投資建議。")
        for claim in json.loads(attempt["raw_response"])["claims"]:
            st.text(claim["text"])
            for citation in claim["citations"]:
                evidence = next(
                    row
                    for row in attempt["payload"]["evidence"]
                    if row["evidence_id"] == citation["evidence_id"]
                )
                st.caption(f"文件日期：{evidence['content_date'] or '未知'}")
                st.link_button("核對原文", evidence["url"])
    else:
        st.warning(f"外部 AI：{labels[attempt['status']]}。以下紀錄不是有效結論。")
    st.caption(f"供應商：{attempt['provider']}｜模型：{attempt['model']}")
    st.caption(
        f"請求時間：{attempt['started_at']}｜完成時間：{attempt['completed_at']}"
        "（不是來源資料日期或可確認的模型產生時間）"
    )
    st.caption(f"供應商回報的回應建立時間：{attempt.get('generated_at') or '未知'}")
    with st.expander("核對本次 AI 實際輸入與失效／未驗證原文", expanded=False):
        st.caption("此處僅為本次選取證據，不代表 AI 完整審閱本機資料。")
        st.json(attempt["payload"])
        st.json(attempt["selection"])
        if attempt.get("review") is not None:
            st.text(attempt["review"]["raw_response"])
        if attempt["raw_response"] is not None:
            # Plain text prevents model output from creating active Markdown links.
            st.text(attempt["raw_response"])


def render_combined_evidence(st: Any, snapshot: CombinedSnapshot) -> None:
    """Render only this immutable snapshot, without provider calls."""
    st.caption(
        f"{snapshot.identity.symbol} / {snapshot.identity.market} · {snapshot.identity.instrument_type}"
    )
    for item in snapshot.company["explanations"]:
        st.markdown(f"**{item['heading']}**")
        st.write(item["text"])
        st.caption(item["kind"])
    dossier = snapshot.company["profile"].get("dossier")
    if snapshot.identity.instrument_type == "ETF":
        st.info("ETF 僅整理基金身分與持股影響；未取得的成分與費用保持未知，不使用公司模型。")
    elif not dossier or not dossier["facts"]:
        st.info("尚無足夠公司原文，不能據此判斷公司風險低。")
    with st.expander("核對持股與完整公司證據", expanded=False):
        st.caption(f"持股證據指紋：{snapshot.holding_fingerprint}")
        st.caption(f"公司證據指紋：{snapshot.company_fingerprint}")
        st.caption(f"組合建立時間：{snapshot.created_at}（不是資料截至日）")
        price_source = snapshot.company["price_source"]
        st.caption(
            f"公司研究行情來源：{price_source['provider'] or '未知'}｜"
            f"行情日期：{price_source['last_data_date'] or '未知'}｜"
            f"抓取時間：{price_source['fetched_at'] or '未知'}（不取代持股估值資料）"
        )
        for datum in snapshot.holding["data"]:
            st.write(f"{datum['label']}：{datum['value']}｜{datum['status']}")
            st.caption(
                f"來源：{datum['source']}｜資料日期：{datum['as_of']}｜抓取時間：{datum['fetched_at']}｜{datum['reason']}"
            )
        for observation in snapshot.holding["observations"]:
            st.write(observation)
        for gap in snapshot.holding["gaps"]:
            st.write(gap)
        if dossier:
            for gap in dossier["gaps"]:
                st.write(gap)
            for i, doc in enumerate(dossier["documents"]):
                st.text(doc["title"])
                st.caption(
                    f"文件日期：{doc['published_at'] or '未知'}｜抓取時間：{doc['fetched_at'] or '未知'}"
                )
                # Display-safe source links are already collected from the public company domain.
                st.link_button(f"公司原文 {i + 1}", doc["url"])
                st.text(doc["text"])


def render_work_session(
    st: Any,
    holding: HoldingAnalysis,
    company: ResearchSnapshot | None,
    *,
    transport: Callable[[bytes], PublicResponse] | None = None,
    provider: str = "",
    model: str = "",
    allow_local_groq: bool = False,
) -> None:
    st.subheader("持股接上公司研究")
    controller = st.session_state.setdefault("work_ai_controller", ResearchRequestController())
    if company is None:
        controller.discard()
        st.info(
            "這筆持股的本機分析已可用。請從下方「深入研究這筆持股」取得公司資料，再返回接續與保存。"
        )
        return
    try:
        combined = combine_snapshots(holding, company)
    except (ValueError, TypeError, KeyError):
        controller.discard()
        st.warning(
            "持股與公司身分／類型尚未一致，已拒絕組合。請核對身分並更新公司研究；本機持股分析仍可查看。"
        )
        return
    render_combined_evidence(st, combined)
    controller.synchronize(combined)
    controller.poll(combined)
    key = combined.fingerprint
    question = st.text_area(
        "我的研究問題（只保存在本機）", key=f"work_question_{key}", max_chars=4000
    )
    if st.button("保存這次持股與公司研究", key=f"work_save_{key}"):
        try:
            session = ResearchWorkSession(
                combined,
                question,
                datetime.now(UTC).isoformat(),
                controller.attempt_json,
            )
            store = WorkSessionStore(
                RuntimePaths.from_environment().data_dir / "research_work_sessions"
            )
            saved = store.save(session)
            st.success(f"已保存完整本機工作階段 {saved[:12]}；可在研究庫接續。")
        except (OSError, WorkSessionError):
            st.error("保存未完成；既有研究版本未被覆寫。")
    st.caption(
        "外部 AI 尚未啟用；本機分析、切換與保存不必等待 AI。"
        if transport is None and not allow_local_groq
        else "本機分析、切換與保存不必等待 AI。"
    )
    if combined.identity.instrument_type == "股票":
        with st.expander("外部 AI 傳送預覽（尚未送出）", expanded=False):
            st.caption(
                "上面的自由文字不會傳送。請改選公開公司問題；股數、成本、損益、權重與備註均留在本機。"
            )
            public_question = st.selectbox(
                "公開公司問題", PUBLIC_QUESTIONS, key=f"work_public_question_{key}"
            )
            selection = select_public_evidence(combined, public_question)
            st.json(selection.payload)
            st.caption(selection.manifest["coverage_label"])
            if transport is None and allow_local_groq:
                from stock_tool.research.groq_transport import DEFAULT_MODEL, LocalGroqTransport

                free_confirmed = st.checkbox(
                    "使用已在本機保存的 Groq 專用金鑰；我的帳號仍為 Free 免費方案",
                    key="work_groq_free_confirmed",
                )
                st.caption(
                    "每次送出最多呼叫兩次：產生草稿、另一次核對引用。額度不足即停止，"
                    "不自動重試或升級。僅傳上方公開證據，不傳本機問題或持股。"
                )
                if free_confirmed:
                    transport = LocalGroqTransport(True)
                    provider, model = "Groq", DEFAULT_MODEL
            if transport is not None:
                st.caption(f"傳送至：{provider}｜模型：{model}")
                if st.button(
                    "傳送以上公開證據",
                    key=f"work_send_{key}",
                    disabled=controller.poll(combined) == "pending",
                ):
                    try:
                        controller.start(
                            combined,
                            PreparedPublicRequest.prepare(combined, public_question),
                            transport,
                            provider=provider,
                            model=model,
                            timeout_seconds=30.0,
                        )
                    except WorkSessionError as exc:
                        st.warning(str(exc))

    # Fragment polling never reruns the whole company/price acquisition flow.
    def show_request() -> None:
        state = controller.poll(combined)
        if state == "pending":
            st.info("AI 處理中；你可以繼續本機研究或保存，不需停在這裡。")
        elif controller.attempt_json != "null":
            render_ai_attempt(
                st,
                ResearchWorkSession(
                    combined, "", datetime.now(UTC).isoformat(), controller.attempt_json
                ),
            )

    if controller.job is not None:
        st.fragment(run_every="1s" if controller.poll(combined) == "pending" else None)(
            show_request
        )()


def render_saved_work_sessions(st: Any, store: WorkSessionStore) -> None:
    st.subheader("持股與公司研究工作階段")
    try:
        keys = store.keys()
    except (OSError, WorkSessionError):
        st.error("無法安全開啟工作階段目錄。")
        return
    for key in keys:
        try:
            session = store.load(key)
        except (OSError, ValueError, TypeError, KeyError):
            st.warning(f"工作階段 {key[:12]} 損毀或格式不符，已拒絕載入。")
            continue
        with st.expander(f"{session.snapshot.identity.symbol} · {session.created_at} · {key[:8]}"):
            st.text(session.question or "未填研究問題")
            st.caption("保存的歷史版本；沒有抓取新行情。")
            render_combined_evidence(st, session.snapshot)
            render_ai_attempt(st, session)
            revised = st.text_area(
                "接續研究問題（另存新版本）",
                value=session.question,
                key=f"work_continue_{key}",
                max_chars=4000,
            )
            if st.button("另存接續版本", key=f"work_continue_save_{key}"):
                try:
                    store.save(
                        ResearchWorkSession(
                            session.snapshot,
                            revised,
                            datetime.now(UTC).isoformat(),
                            session.ai_attempt_json,
                        )
                    )
                    st.success("已另存，原研究版本保持不變。")
                    st.rerun()
                except (OSError, WorkSessionError):
                    st.error("另存未完成，原研究未被覆寫。")
    if keys:
        try:
            backup = store.backup_bytes()
            st.download_button(
                "備份全部工作階段（不含舊研究庫）",
                backup,
                file_name="research-work-sessions.json",
                mime="application/json",
            )
        except (OSError, ValueError):
            st.warning("有工作階段無法驗證，未提供不完整備份。")
    if callable(getattr(st, "file_uploader", None)):
        uploaded = st.file_uploader(
            "還原工作階段備份（只新增，不覆寫）", type=["json"], key="work_restore_file"
        )
        if uploaded is not None and st.button("核對並還原工作階段", key="work_restore"):
            try:
                store.restore_bytes(uploaded.getvalue(), append_only=True)
                st.success("完整性核對通過，工作階段已還原；既有版本未覆寫。")
                st.rerun()
            except (OSError, ValueError, TypeError, KeyError):
                st.error("還原未完成；備份可能損毀或格式不符，既有版本未覆寫。")
