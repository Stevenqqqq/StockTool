from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pandas as pd

import stock_tool.dashboard.pages.research as research_page
from stock_tool.application.research_snapshot import (
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.domain.models import Market, Symbol
from stock_tool.research.evidence import build_evidence_bundle
from stock_tool.research.library import ResearchLibrary


class _WorkspaceStreamlit:
    def __init__(self, *, clicked: set[str], values: dict[str, object]) -> None:
        self.clicked = clicked
        self.values = values
        self.session_state: dict[str, object] = {}
        self.events: list[str] = []
        self.rerun_count = 0

    def button(self, _label: str, *, key: str, **_kwargs: object) -> bool:
        return key in self.clicked

    def text_input(self, _label: str, *, key: str, **_kwargs: object) -> str:
        return str(self.values.get(key, ""))

    def multiselect(self, _label: str, *, options: tuple[str, ...], key: str):
        value = self.values.get(key, ())
        return [item for item in value if item in options]

    def checkbox(self, _label: str, *, key: str, **_kwargs: object) -> bool:
        return bool(self.values.get(key, False))

    def subheader(self, value: str) -> None:
        self.events.append(value)

    def caption(self, value: str) -> None:
        self.events.append(value)

    def success(self, value: str) -> None:
        self.events.append(value)

    def error(self, value: str) -> None:
        self.events.append(value)

    def warning(self, value: str) -> None:
        self.events.append(value)

    def expander(self, *_args: object, **_kwargs: object):
        return nullcontext()

    def tabs(self, labels: tuple[str, ...]):
        return [nullcontext() for _ in labels]

    def columns(self, count: int | tuple[int, ...]):
        return [nullcontext() for _ in range(count if isinstance(count, int) else len(count))]

    def rerun(self) -> None:
        self.rerun_count += 1


def _snapshot():
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "symbol": ["MU", "MU", "MU"],
            "close": [100.0, 101.0, 102.0],
        }
    )
    return ResearchWorkspaceService().build(
        symbol=Symbol("MU", Market.US),
        price_data=prices,
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        company_profile=None,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata.empty(symbol="MU", market="US"),
    )


def _isolate_workspace_rendering(monkeypatch) -> None:
    for name in (
        "render_research_header",
        "render_global_search",
        "_render_company_overview",
        "_render_overview_chart",
        "_render_chart",
        "_render_fundamentals",
        "render_scorecard",
        "render_evidence_panel",
        "render_risk_summary",
    ):
        monkeypatch.setattr(research_page, name, lambda *_args, **_kwargs: None)


def test_workspace_renders_core_research_before_optional_document_controls(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    _isolate_workspace_rendering(monkeypatch)
    monkeypatch.setattr(
        research_page,
        "render_risk_summary",
        lambda *_args, **_kwargs: calls.append("risk"),
    )
    monkeypatch.setattr(
        research_page,
        "_render_save_research_controls",
        lambda *_args, **_kwargs: calls.append("optional_save_controls"),
    )

    research_page.render_research_workspace(
        _WorkspaceStreamlit(clicked=set(), values={}),
        _snapshot(),
        library=ResearchLibrary(tmp_path / "library"),
    )

    assert calls[-1] == "optional_save_controls"
    assert calls.count("risk") == 2


def test_workspace_ui_registers_local_file_and_saves_page_link(tmp_path: Path, monkeypatch) -> None:
    _isolate_workspace_rendering(monkeypatch)
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic pdf")
    library = ResearchLibrary(tmp_path / "runtime" / "research_library")
    snapshot = _snapshot()

    register = _WorkspaceStreamlit(
        clicked={"research_register_document"},
        values={
            "research_document_source_path": str(source.resolve()),
            "research_document_title": "Synthetic PDF",
        },
    )
    research_page.render_research_workspace(
        register,
        snapshot,
        library=library,
        ai_cache_directory=tmp_path / "ai-cache",
    )
    document = library.document_store.list_references()[0]
    assert document.title == "Synthetic PDF"
    assert document.source_path == str(source.resolve())
    assert b"synthetic pdf" not in library.document_store.path.read_bytes()

    evidence_id = build_evidence_bundle(snapshot).evidence[0].evidence_id
    save = _WorkspaceStreamlit(
        clicked={"research_save_to_library"},
        values={
            f"research_document_use_{document.document_id}": True,
            f"research_document_citations_{document.document_id}": [evidence_id],
            f"research_document_page_{document.document_id}": "5",
        },
    )
    research_page.render_research_workspace(
        save,
        snapshot,
        library=library,
        ai_cache_directory=tmp_path / "ai-cache",
    )
    entry = library.list_entries()[0]
    assert entry.document_references[0].document_id == document.document_id
    assert entry.document_references[0].citation_ids == (evidence_id,)
    assert entry.document_references[0].page == 5


def test_workspace_ui_registers_and_selects_two_documents(tmp_path: Path, monkeypatch) -> None:
    _isolate_workspace_rendering(monkeypatch)
    source_a = tmp_path / "first.pdf"
    source_b = tmp_path / "second.pdf"
    source_a.write_bytes(b"first synthetic pdf")
    source_b.write_bytes(b"second synthetic pdf")
    library = ResearchLibrary(tmp_path / "runtime" / "research_library")
    snapshot = _snapshot()

    for source in (source_a, source_b):
        register = _WorkspaceStreamlit(
            clicked={"research_register_document"},
            values={
                "research_document_source_path": str(source.resolve()),
                "research_document_title": "",
            },
        )
        research_page.render_research_workspace(
            register,
            snapshot,
            library=library,
            ai_cache_directory=tmp_path / "ai-cache",
        )

    documents = library.document_store.list_references()
    assert len(documents) == 2
    assert {document.title for document in documents} == {source_a.name, source_b.name}
    evidence_id = build_evidence_bundle(snapshot).evidence[0].evidence_id
    save_values: dict[str, object] = {}
    for page, document in enumerate(documents, start=4):
        save_values.update(
            {
                f"research_document_use_{document.document_id}": True,
                f"research_document_citations_{document.document_id}": [evidence_id],
                f"research_document_page_{document.document_id}": str(page),
            }
        )
    save = _WorkspaceStreamlit(clicked={"research_save_to_library"}, values=save_values)
    research_page.render_research_workspace(
        save,
        snapshot,
        library=library,
        ai_cache_directory=tmp_path / "ai-cache",
    )

    entry = library.list_entries()[0]
    assert {link.document_id for link in entry.document_references} == {
        document.document_id for document in documents
    }
    assert {link.page for link in entry.document_references} == {4, 5}
    assert "本機文件引用" in "\n".join(save.events)
