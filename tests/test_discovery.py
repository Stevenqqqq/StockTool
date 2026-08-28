"""Sprint 9 Discovery UI tests using only local canonical evidence fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_tool.concept_repository import ConceptRepository
from stock_tool.dashboard.pages.discovery import render_discovery
from stock_tool.data.repositories import ResearchRepository, RepositoryDataError


class _FakeStreamlit:
    def __init__(self, query: str) -> None:
        self.query = query
        self.messages: list[str] = []
        self.links: list[tuple[str, str]] = []

    def subheader(self, value: str) -> None:
        self.messages.append(value)

    def text_input(self, _label: str, *, key: str) -> str:
        assert key == "canonical_concept_query"
        return self.query

    def markdown(self, value: str) -> None:
        self.messages.append(value)

    def caption(self, value: str) -> None:
        self.messages.append(value)

    def info(self, value: str) -> None:
        self.messages.append(value)

    def link_button(self, label: str, url: str) -> None:
        self.links.append((label, url))


@pytest.fixture
def concept_repository(tmp_path: Path) -> ConceptRepository:
    repository = ResearchRepository(tmp_path / "research.sqlite")
    repository.initialize()
    adapter = ConceptRepository(repository)
    adapter.import_dataset(Path("tests/fixtures/concepts"))
    return adapter


def test_discovery_groups_exact_canonical_relations_with_evidence(
    concept_repository: ConceptRepository,
) -> None:
    streamlit = _FakeStreamlit("HBM")

    render_discovery(streamlit, concept_repository)

    rendered = "\n".join(streamlit.messages)
    assert "高頻寬記憶體" in rendered
    assert "核心製造" in rendered
    assert "設備／材料" in rendered
    assert "設計／平台" in rendered
    assert "下游需求" in rendered
    assert "間接受益" in rendered
    assert "HBMMANUAL / US" in rendered
    assert "人工種子" in rendered
    assert "HBMSTALE / US" in rendered
    assert "資料已過期" in rendered
    assert streamlit.links
    assert all(url.startswith("https://") for _label, url in streamlit.links)


def test_discovery_does_not_expand_blank_or_fuzzy_queries(
    concept_repository: ConceptRepository,
) -> None:
    blank = _FakeStreamlit("")
    fuzzy = _FakeStreamlit("hbm 供應鏈")

    render_discovery(blank, concept_repository)
    render_discovery(fuzzy, concept_repository)

    assert not blank.links
    assert not fuzzy.links
    assert any("無可信結果" in message for message in fuzzy.messages)


def test_discovery_handles_missing_repository_record_without_raw_exception(
    concept_repository: ConceptRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    streamlit = _FakeStreamlit("HBM")
    monkeypatch.setattr(
        concept_repository,
        "concept",
        lambda _key: (_ for _ in ()).throw(RepositoryDataError("database failure token=secret")),
    )

    render_discovery(streamlit, concept_repository)

    assert any("資料" in message for message in streamlit.messages)
    assert "secret" not in "\n".join(streamlit.messages)
