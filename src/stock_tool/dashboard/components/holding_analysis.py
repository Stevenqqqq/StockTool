"""Chinese single-holding explanation driven by one immutable evidence snapshot."""

from __future__ import annotations

from typing import Any

import pandas as pd

from stock_tool.application.holding_analysis import build_holding_analysis
from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
from stock_tool.runtime_paths import RuntimePaths


def render_holding_analysis(st: Any, positions: pd.DataFrame, analysis: object) -> None:
    st.subheader("看懂一筆持股")
    identities = [f"{row.symbol} / {row.market}" for row in positions.itertuples(index=False)]
    selection_key = "portfolio_workspace_research_identity"
    if st.session_state.get(selection_key) not in identities:
        st.session_state[selection_key] = identities[0]
    selected = st.selectbox("選擇要分析與研究的持股", identities, key=selection_key)
    symbol, market = selected.split(" / ", 1)
    position = (
        positions.loc[(positions.symbol == symbol) & (positions.market == market)].iloc[0].to_dict()
    )
    profiles = st.session_state.get("holding_profiles", {})
    identity = f"{symbol}|{market}"
    profile = dict(profiles.get(identity, {}))
    override = st.session_state.get("holding_type_overrides", {}).get(identity)
    if override:
        profile["instrument_type"] = override
    kinds = ["未確認", "股票", "ETF"]
    effective_kind = profile.get("instrument_type", "未確認")
    if effective_kind not in kinds:
        effective_kind = "未確認"
    with st.expander("確認標的身份／修正類型", expanded=False):
        st.write(f"市場：{market}；代號：{symbol}；成本幣別：{position['currency']}")
        st.write(
            f"名稱：{profile.get('name', '尚未取得')}；資料類型：{profile.get('instrument_type', '未確認')}"
        )
        st.caption(
            f"來源：{profile.get('source', '未確認')}；取得時間：{profile.get('fetched_at', '未提供')}"
        )
        kind = st.selectbox(
            "人工確認類型", kinds, index=kinds.index(effective_kind), key=f"holding_kind_{identity}"
        )
        if st.button("採用我確認的類型", key=f"holding_kind_apply_{identity}"):
            st.session_state.setdefault("holding_type_overrides", {})[identity] = kind
            from stock_tool.application.holding_identity import save_identity_state

            try:
                save_identity_state(
                    RuntimePaths.from_environment().data_dir / "holding_identity.json",
                    {"profiles": profiles, "overrides": st.session_state["holding_type_overrides"]},
                )
            except OSError:
                st.error("類型修正尚未存到磁碟；目前只在本次使用生效。")
            st.session_state.pop("portfolio_workspace_analysis", None)
            st.session_state.pop("portfolio_workspace_stress_result", None)
            st.rerun()
        st.caption("市場或成本幣別不符時，請在持股管理修正；資料更新不會改寫股數、成本與備註。")
    error = st.session_state.get("holding_profile_errors", {}).get(identity)
    if error:
        st.warning(error)
    weight = None
    valuation = getattr(analysis, "valuation", None)
    if valuation is not None and not valuation.positions.empty:
        rows = valuation.positions
        matching = rows.loc[(rows.symbol == symbol) & (rows.market == market)]
        if not matching.empty:
            raw = matching.iloc[0].get("weight")
            weight = float(raw) if raw is not None and pd.notna(raw) else None
    result = st.session_state.get("portfolio_workspace_refresh_result", ())
    failed = bool(st.session_state.get("holding_refresh_failed", False))
    for outcome in result if isinstance(result, tuple) else (result,):
        for item in getattr(outcome, "items", ()):
            if item.symbol == symbol and item.market == market and item.status == "failed":
                failed = True
    resolution = st.session_state.get("portfolio_fx_resolution")
    from stock_tool.dashboard.pages.portfolio_workspace import _resolved_fx_quote

    snapshot = build_holding_analysis(
        position,
        prices=st.session_state.get("price_data"),
        fx_quote=getattr(resolution, "quote", None) or _resolved_fx_quote(st),
        weight=weight,
        profile=profile,
        refresh_failed=failed,
    )
    st.session_state.setdefault("holding_analysis_snapshots", {})[identity] = snapshot
    st.markdown(f"**{profile.get('name', symbol)} · {snapshot.instrument_type}**")
    labels = {
        "Technology": "科技",
        "Semiconductors": "半導體",
        "Financial Services": "金融服務",
        "Healthcare": "醫療保健",
        "Industrials": "工業",
    }
    if profile.get("sector") in labels or profile.get("industry") in labels:
        st.caption(
            "／".join(
                labels[str(profile[key])]
                for key in ("sector", "industry")
                if profile.get(key) in labels
            )
        )
    metrics = ("原幣市值", "原幣未實現損益", "台幣參考市值")
    columns = st.columns(2) + st.columns(2)
    for index, label in enumerate(metrics):
        datum = next((item for item in snapshot.data if item.label == label), None)
        columns[index].metric(label, datum.value if datum else "暫無法計算")
        if datum and datum.status != "可用":
            columns[index].caption(datum.status)
    for datum in snapshot.data:
        if datum.label in (*metrics, "標的名稱", "產業領域", "細分產業"):
            continue
        st.write(f"{datum.label}：{datum.value}")
        if datum.as_of != "不適用":
            st.caption(
                f"{datum.source}｜資料日期 {datum.as_of}｜{datum.status}"
                + (f"｜{datum.reason}" if datum.reason else "")
            )
    st.markdown("**這筆持股對我的影響**")
    for observation in snapshot.observations:
        st.write(observation)
    st.markdown("**目前還不能下的結論**")
    for gap in snapshot.gaps:
        st.write(gap)
    st.subheader("AI 輔助理解")
    st.caption("以這筆持股的同一份證據整理原因、反面證據與下一步；不以綜合分數代替分析。")
    bundle = snapshot.evidence_bundle()
    notes = st.session_state.setdefault("holding_ai_notes", {})
    if st.button("整理這筆持股的證據", key="holding_generate_ai"):
        if bundle.fingerprint not in notes:
            # Holding evidence contains private amounts. This legacy local
            # summary must never inherit an external provider from environment.
            assistant = AIResearchAssistant(
                cache=ResearchAssistantCache(
                    RuntimePaths.from_environment().cache_dir / "holding_ai"
                )
            )
            notes[bundle.fingerprint] = assistant.generate(bundle)
    note = notes.get(bundle.fingerprint)
    if note is not None:
        st.caption("AI 整理" if note.mode == "ai" else "本機證據整理（尚未取得 AI 分析）")
        for claim in note.claims:
            st.write(claim.text)
        if note.warnings:
            st.caption("AI 未完成或資料有限時，請以以下原始證據核對。")
    with st.expander("資料來源與 AI 共用證據", expanded=False):
        for record in bundle.evidence:
            st.write(f"{record.evidence_id}：{record.text}")
            st.caption(
                f"來源：{record.source or '無'}｜資料日期：{record.available_at or '未提供'}｜取得時間：{record.fetched_at or '未提供'}"
            )
    st.caption("這份新版持股分析尚未接入舊版 Excel 匯出，請勿以舊報表代替此分析。")
    from stock_tool.application.research_snapshot import ResearchSnapshot
    from stock_tool.dashboard.components.work_session import render_work_session

    candidates = st.session_state.get("dashboard_research_snapshots", {}).values()
    company = next(
        (
            item
            for item in candidates
            if isinstance(item, ResearchSnapshot)
            and item.symbol.code == symbol
            and item.symbol.market.value == market
        ),
        None,
    )
    render_work_session(st, snapshot, company, allow_local_groq=True)
