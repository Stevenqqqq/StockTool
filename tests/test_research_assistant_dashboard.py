from __future__ import annotations

from contextlib import nullcontext

from stock_tool.dashboard.components.research_assistant import render_research_assistant
from stock_tool.research.assistant import (
    AIResearchAssistant,
    ClaimKind,
    EvidenceBundle,
    EvidenceRecord,
    ResearchAssistantCache,
)


class _FakeStreamlit:
    def __init__(self, button_key: str | None = None) -> None:
        self.button_key = button_key
        self.events: list[str] = []

    def subheader(self, value: str) -> None:
        self.events.append(value)

    def caption(self, value: str) -> None:
        self.events.append(value)

    def info(self, value: str) -> None:
        self.events.append(value)

    def warning(self, value: str) -> None:
        self.events.append(value)

    def write(self, value: str) -> None:
        self.events.append(value)

    def markdown(self, value: str) -> None:
        self.events.append(value)

    def button(self, _label: str, *, key: str, **_kwargs: object) -> bool:
        return key == self.button_key

    def container(self, **_kwargs: object):
        return nullcontext()

    def expander(self, *_args: object, **_kwargs: object):
        return nullcontext()


def _note(tmp_path):
    bundle = EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="fixture",
        evidence=(
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="最新收盤價",
                text="最新收盤價為 100。",
                source="fixture provider",
                provider="fixture",
                symbol="MU",
                market="US",
                field="close",
            ),
        ),
    )
    return AIResearchAssistant(cache=ResearchAssistantCache(tmp_path)).generate(bundle)


def test_home_assistant_uses_local_label_when_ai_is_not_configured(tmp_path) -> None:
    st = _FakeStreamlit()
    note = _note(tmp_path)
    brief = type(
        "Brief",
        (),
        {
            "generated_at": "2026-07-27",
            "notes": (note,),
            "unavailable_identities": (),
            "warnings": (),
        },
    )()

    action = render_research_assistant(st, brief, can_generate=True)

    assert action is None
    assert any("本機規則模式" in event for event in st.events)
    assert not any("AI 模式" in event for event in st.events)


def test_local_note_renders_the_structured_research_sections(tmp_path) -> None:
    st = _FakeStreamlit()
    note = _note(tmp_path)
    brief = type(
        "Brief",
        (),
        {
            "generated_at": "2026-07-27",
            "notes": (note,),
            "unavailable_identities": (),
            "warnings": (),
        },
    )()

    render_research_assistant(st, brief, can_generate=True)

    for heading in ("今日重點摘要", "技術面變化", "主要風險", "資料不足與待確認事項"):
        assert any(heading in event for event in st.events)


def test_home_assistant_can_generate_and_open_market_qualified_research(tmp_path) -> None:
    generate_st = _FakeStreamlit(button_key="home_generate_ai_research")
    generate_action = render_research_assistant(generate_st, None, can_generate=True)

    note = _note(tmp_path)
    brief = type(
        "Brief",
        (),
        {
            "generated_at": "2026-07-27",
            "notes": (note,),
            "unavailable_identities": (),
            "warnings": (),
        },
    )()
    open_st = _FakeStreamlit(button_key="home_ai_research_open_US_MU_0")
    open_action = render_research_assistant(open_st, brief, can_generate=True)

    assert generate_action is not None and generate_action.kind == "generate"
    assert open_action is not None
    assert (open_action.kind, open_action.symbol, open_action.market) == (
        "open_research",
        "MU",
        "US",
    )
