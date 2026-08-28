"""Small, safe Daily Research Home presentation for evidence-linked notes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from stock_tool.research.assistant import (
    AIResearchNote,
    ClaimKind,
    DailyResearchAssistantBrief,
    ResearchClaim,
)

_SECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("today_summary", "今日重點摘要"),
    ("changes", "與前次資料相比的變化"),
    ("facts", "可確認的事實"),
    ("technical", "技術面變化"),
    ("fundamentals_valuation", "基本面與估值變化"),
    ("catalysts", "重要催化因素"),
    ("risks", "主要風險"),
    ("contradictions", "相互矛盾的證據"),
    ("missing", "資料不足與待確認事項"),
    ("serenity", "Serenity 供應鏈瓶頸觀察"),
    ("next_steps", "建議的下一步研究動作"),
    ("warnings", "來源與資料限制"),
)


@dataclass(frozen=True, slots=True)
class ResearchAssistantAction:
    """Explicit user intent returned to the Dashboard shell."""

    kind: Literal["generate", "open_research"]
    symbol: str | None = None
    market: str | None = None
    force_regenerate: bool = False


def render_research_assistant(
    st: Any,
    brief: DailyResearchAssistantBrief | None,
    *,
    can_generate: bool,
) -> ResearchAssistantAction | None:
    """Render one bounded assistant block without interpreting results as advice."""

    st.subheader("今日 AI 研究簡報")
    st.caption("研究整理不提供買賣指令、報酬預測或目標價；所有事實均需有引用。")
    if brief is None:
        if can_generate and st.button("產生今日 AI 研究簡報", key="home_generate_ai_research"):
            return ResearchAssistantAction(kind="generate")
        if not can_generate:
            st.info("請先完成至少一檔個股研究，才可建立有引用的今日研究簡報。")
        return None

    st.caption(f"簡報產生時間：{brief.generated_at}；研究重點：{len(brief.notes)} 檔。")
    if not brief.notes:
        st.info("資料不足：目前沒有可用的研究快照可建立今日簡報。")
    for index, note in enumerate(brief.notes):
        _render_note(st, note, index)
        if st.button(
            "查看完整研究",
            key=f"home_ai_research_open_{note.market}_{note.symbol}_{index}",
            width="stretch",
        ):
            return ResearchAssistantAction(
                kind="open_research",
                symbol=note.symbol,
                market=note.market,
            )
    if brief.unavailable_identities:
        st.warning("待確認研究快照：" + "、".join(brief.unavailable_identities))
    for warning in brief.warnings:
        st.warning(warning)
    if can_generate and st.button("重新產生", key="home_regenerate_ai_research"):
        return ResearchAssistantAction(kind="generate", force_regenerate=True)
    return None


def _render_note(st: Any, note: AIResearchNote, index: int) -> None:
    """Render labels and citations as plain Streamlit text, never raw model HTML."""

    mode = "AI 模式" if note.mode == "ai" else "本機規則模式"
    with st.container(border=True):
        st.markdown(f"#### {note.symbol} ({note.market})")
        st.info(f"目前使用：{mode}" + (f"；模型：{note.model}" if note.model else ""))
        st.caption(
            f"資料覆蓋率：{_coverage(note.coverage)}；證據信心：{_confidence(note.confidence_label)}；"
            f"引用數：{len(note.citations)}；"
            f"產生時間：{note.generated_at}"
        )
        claims_by_section = _claims_by_section(note)
        for section, label in _SECTION_LABELS:
            st.markdown(f"**{label}**")
            claims = claims_by_section.get(section, ())
            if claims:
                for claim in claims[:3]:
                    st.write(f"[{_kind_label(claim.kind)}] {claim.text}")
            else:
                st.caption("資料不足：目前沒有可引用的結構化資料。")
        if note.missing_data:
            st.caption("資料缺口：" + "；".join(note.missing_data[:3]))
        for warning in note.warnings:
            st.caption(f"限制：{warning}")
        with st.expander("完整引用清單", expanded=False):
            if not note.citations:
                st.info("資料不足：此本機規則摘要沒有可顯示的外部引用。")
            for citation in note.citations:
                st.write(
                    f"{citation.evidence_id}｜{citation.symbol} ({citation.market})｜"
                    f"{citation.source or '資料不足'}｜{citation.provider or citation.publisher or '資料提供者未記錄'}｜"
                    f"{citation.available_at or citation.fetched_at or '資料時間未記錄'}"
                )
                st.caption(citation.excerpt)
                if citation.url:
                    st.caption(f"來源網址：{citation.url}")


def _kind_label(kind: ClaimKind) -> str:
    return {
        ClaimKind.FACT: "FACT",
        ClaimKind.CALCULATION: "CALCULATION",
        ClaimKind.INFERENCE: "INFERENCE",
        ClaimKind.MISSING: "MISSING",
        ClaimKind.WARNING: "WARNING",
    }[kind]


def _claims_by_section(note: AIResearchNote) -> dict[str, tuple[ResearchClaim, ...]]:
    """Group already validated claims without deriving facts from display text."""

    grouped: dict[str, list[ResearchClaim]] = {}
    for claim in note.claims:
        grouped.setdefault(claim.section, []).append(claim)
    return {section: tuple(claims) for section, claims in grouped.items()}


def _coverage(value: float | None) -> str:
    return "資料不足" if value is None else f"{value:.0%}"


def _confidence(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}[value]
