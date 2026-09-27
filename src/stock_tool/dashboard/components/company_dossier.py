"""Source-backed company research, shared by both research entry points."""

from __future__ import annotations

from typing import Any

from stock_tool.company_dossier import CompanyDossier, CompanyFact
from stock_tool.company_explanation import explain_company


def _source(st: Any, fact: CompanyFact) -> None:
    st.caption(
        f"內容日期：{fact.published_at or '未標示，不能確認最新'}｜取得：{fact.fetched_at[:19]}（UTC）"
    )
    st.link_button("核對官網原文", fact.url)


def _section(st: Any, dossier: CompanyDossier, section: str) -> None:
    rows = [fact for fact in dossier.facts if fact.section == section]
    st.markdown(f"**{section}**")
    if not rows:
        st.info("這次讀到的頁面沒有足夠證據；不能據此認定沒有相關業務或風險。")
    if rows:
        with st.expander(f"展開{section}原文與來源"):
            for fact in rows:
                st.text(fact.excerpt)
                _source(st, fact)


def render_company_dossier(st: Any, dossier: CompanyDossier) -> None:
    if st.button("重新讀取公司資料", key=f"company_refresh_{dossier.market}_{dossier.symbol}"):
        st.session_state["company_details_force"] = True
        st.rerun()
    st.caption(f"研究角度：{dossier.industry_lens}｜本次讀取 {len(dossier.documents)} 個官網頁面")
    if dossier.state == "stale":
        st.warning("本次更新失敗，以下是前次官網資料，不能視為最新狀況。")
    st.caption("官網揭露是公司自己的說法。業務存在、進展及收入貢獻需要分開核對。")

    for item in explain_company(dossier):
        st.markdown(f"**{item.heading}**")
        st.caption(item.kind)
        st.text(item.text)
        if item.evidence_indices:
            with st.expander(f"核對「{item.heading}」的依據"):
                for index in dict.fromkeys(item.evidence_indices):
                    fact = dossier.facts[index]
                    st.text(fact.excerpt)
                    _source(st, fact)

    roles = [fact for fact in dossier.facts if fact.section == "公司角色"]
    if roles:
        with st.expander("公司角色原文"):
            st.text(roles[0].excerpt)
            _source(st, roles[0])

    products, operations, sources = st.tabs(("產品與應用", "營運與風險", "來源與缺口"))
    with products:
        rows = [fact for fact in dossier.facts if fact.section == "產品與技術"]
        if rows:
            st.markdown("**官網找到的產品、業務與規格**")
            st.dataframe(
                [
                    {
                        "產品／業務／規格": _product_label(fact.subject),
                        "來源描述的狀態": fact.stage,
                        "內容日期": fact.published_at or "未標示",
                    }
                    for fact in rows
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "規格與容量可能屬於不同產品；展開原文確認搭配關係。未列出不代表公司沒有該產品。"
            )
            with st.expander("逐項產品說明、規格與來源"):
                for fact in rows:
                    st.markdown(f"**{_product_label(fact.subject)}**")
                    st.text(fact.excerpt)
                    _source(st, fact)
        else:
            st.info("尚未讀到可核對的產品／業務細節；不以產業通用模板補成公司事實。")
        _section(st, dossier, "應用與客戶")
    with operations:
        _section(st, dossier, "營運與收入")
        _section(st, dossier, "進度與變化")
        _section(st, dossier, "公司揭露的風險")
        st.caption("產品與營收占比沒有必然關係；風險欄空白不等於低風險。")
    with sources:
        for gap in dossier.gaps:
            st.write(f"- {gap}")
        for doc in dossier.documents:
            st.link_button(doc.title or "官網頁面", doc.url)
    st.markdown("**接下來最值得查什麼**")
    st.caption("這些是依產業選出的研究問題，尚未當作這家公司的事實。")
    for question in dossier.questions:
        st.write(f"- {question}")


def _product_label(subject: str) -> str:
    for original, chinese in (
        ("Consumer&CommunityBanking", "消費與社區銀行"),
        ("Commercial&InvestmentBanking", "商業與投資銀行"),
        ("Commercial&InvestmentBank", "商業與投資銀行"),
        ("Asset&WealthManagement", "資產與財富管理"),
        ("AssetandWealthManagement", "資產與財富管理"),
    ):
        subject = subject.replace(original, chinese)
    return subject
