from __future__ import annotations

from contextlib import nullcontext
import logging
from pathlib import Path
from types import SimpleNamespace

import stock_tool.dashboard.pages.library as library_page
import stock_tool.dashboard.shell as dashboard_shell
from stock_tool.dashboard.navigation import navigation_for_key
from stock_tool.dashboard.shell import DashboardShellDependencies
from stock_tool.dashboard.state import SearchRequest
from stock_tool.research.document_store import DocumentStore
from stock_tool.dashboard.pages.library import _render_saved_entry
from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
from stock_tool.research.evidence import ClaimKind, EvidenceBundle, EvidenceRecord
from stock_tool.research.library import ResearchLibrary
from stock_tool.research.library import ResearchDocumentLink


class _FakeStreamlit:
    def __init__(self) -> None:
        self.events: list[str] = []

    def divider(self) -> None:
        self.events.append("divider")

    def subheader(self, value: str) -> None:
        self.events.append(value)

    def caption(self, value: str) -> None:
        self.events.append(value)

    def write(self, value: str) -> None:
        self.events.append(value)

    def text(self, value: str) -> None:
        self.events.append(value)

    def link_button(self, label: str, url: str) -> None:
        self.events.extend((label, url))

    def markdown(self, value: str) -> None:
        self.events.append(value)

    def warning(self, value: str) -> None:
        self.events.append(value)


class _LibraryStreamlit(_FakeStreamlit):
    def __init__(self, *, clicked: set[str] | None = None) -> None:
        super().__init__()
        self.session_state = _SessionState(price_data_source={})
        self.clicked = clicked or set()
        self.rerun_count = 0

    def text_input(self, _label: str, *, key: str) -> str:
        return str(self.session_state.get(key, ""))

    def selectbox(self, _label: str, options: tuple[str, ...], *, key: str) -> str:
        value = self.session_state.get(key, "")
        return value if value in options else ""

    def expander(self, _label: str):
        return nullcontext()

    def button(self, _label: str, *, key: str, **_kwargs: object) -> bool:
        return key in self.clicked

    def checkbox(self, _label: str, *, key: str) -> bool:
        return bool(self.session_state.get(key, False))

    def file_uploader(self, _label: str, **_kwargs: object):
        return None

    def info(self, value: str) -> None:
        self.events.append(value)

    def success(self, value: str) -> None:
        self.events.append(value)

    def error(self, value: str) -> None:
        self.events.append(value)

    def rerun(self) -> None:
        self.rerun_count += 1


class _SessionState(dict):
    def __getattr__(self, name: str):
        return self.get(name)


def test_saved_version_renderer_uses_only_the_immutable_entry_payload(tmp_path: Path) -> None:
    bundle = EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="fixture",
        evidence=(
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="Price",
                text="Latest close is 100.",
                source="fixture source",
                provider="fixture provider",
                symbol="MU",
                market="US",
                url="https://example.invalid/price",
            ),
        ),
    )
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    entry = ResearchLibrary(tmp_path / "library").save(
        bundle=bundle, note=note, title="Saved research"
    )
    st = _FakeStreamlit()

    _render_saved_entry(st, entry)

    rendered = "\n".join(st.events)
    assert "保存的研究版本" in rendered
    assert "Latest close is 100." in rendered
    assert "引用：price" in rendered
    assert "https://example.invalid/price" in rendered


def _entry_with_document(tmp_path: Path):
    source = tmp_path / "research.pdf"
    source.write_bytes(b"original")
    store = DocumentStore(tmp_path / "library" / "documents")
    store.register(document_id="doc-1", source_path=source, title="Research PDF")
    library = ResearchLibrary(tmp_path / "library", document_store=store)
    bundle = EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="fixture",
        evidence=(
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="Price",
                text="Latest close is 100.",
                source="fixture source",
                provider="fixture provider",
                symbol="MU",
                market="US",
                url="https://example.invalid/price",
            ),
        ),
    )
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    entry = library.save(
        bundle=bundle,
        note=note,
        title="Saved research",
        document_references=(ResearchDocumentLink("doc-1", ("price",), page=4),),
    )
    return library, entry


def test_actual_library_render_saved_version_is_provider_free_and_survives_rerun(
    tmp_path: Path, monkeypatch
) -> None:
    library, entry = _entry_with_document(tmp_path)
    monkeypatch.setattr(library_page, "render_data_quality", lambda *_args, **_kwargs: False)
    first = _LibraryStreamlit(clicked={f"library_open_{entry.library_entry_id}"})
    library_page.render_library_workspace(first, source={}, library=library)
    assert first.session_state["dashboard_library_saved_entry_id"] == entry.library_entry_id

    provider_calls: list[str] = []

    def fail_provider(*_args, **_kwargs):
        provider_calls.append("called")
        raise AssertionError("saved version must not call provider")

    second = _LibraryStreamlit()
    second.session_state.update(first.session_state)
    library_page.render_library_workspace(second, source={}, library=library)
    assert provider_calls == []
    rendered = "\n".join(second.events)
    assert "保存的研究版本" in rendered
    assert "Research PDF" in rendered
    assert "可用" in rendered
    assert "頁碼引用：第 4 頁" in rendered
    assert "Latest close is 100." in rendered
    assert "引用：price" in rendered
    assert "核對保存的來源原文\nhttps://example.invalid/price" in rendered

    # Exercise the production shell path with a provider that fails on any call.
    monkeypatch.setattr(
        dashboard_shell,
        "default_runtime_paths",
        lambda: SimpleNamespace(research_library_dir=tmp_path / "library"),
    )
    monkeypatch.setattr(dashboard_shell, "render_page_header", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        dashboard_shell, "render_workspace_overview", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        dashboard_shell, "_render_workspace_legacy_entry", lambda *_args, **_kwargs: None
    )
    guarded = _LibraryStreamlit(clicked={f"library_open_{entry.library_entry_id}"})
    dependencies = DashboardShellDependencies(
        ensure_symbol_data=fail_provider,
        render_legacy_page=lambda *_args: None,
        portfolio_path=tmp_path / "portfolio.csv",
        watchlist_path=tmp_path / "watchlist.csv",
        risk_notice="test",
        app_title="StockTool",
        logger=logging.getLogger("test.saved.version"),
    )
    dashboard_shell._render_workspace(guarded, dependencies, navigation_for_key("library"))
    assert provider_calls == []


def test_actual_library_render_current_action_routes_to_current_research_flow(
    tmp_path: Path, monkeypatch
) -> None:
    library, entry = _entry_with_document(tmp_path)
    monkeypatch.setattr(library_page, "render_data_quality", lambda *_args, **_kwargs: False)
    st = _LibraryStreamlit(clicked={f"library_current_{entry.library_entry_id}"})
    library_page.render_library_workspace(st, source={}, library=library)
    assert st.session_state["dashboard_library_current_research"] == {
        "symbol": "MU",
        "market": "US",
    }
    assert "dashboard_library_saved_entry_id" not in st.session_state

    dashboard_shell._route_current_library_research(st)
    pending = st.session_state["dashboard_pending_search"]
    assert isinstance(pending, SearchRequest)
    assert (pending.symbol, pending.market) == ("MU", "US")
    assert st.session_state["dashboard_active_workspace"] == "home"
    assert st.rerun_count == 2


def test_actual_library_render_marks_missing_and_changed_documents_broken(
    tmp_path: Path, monkeypatch
) -> None:
    library, entry = _entry_with_document(tmp_path)
    monkeypatch.setattr(library_page, "render_data_quality", lambda *_args, **_kwargs: False)
    source = tmp_path / "research.pdf"
    source.unlink()
    missing = _LibraryStreamlit()
    missing.session_state["dashboard_library_saved_entry_id"] = entry.library_entry_id
    library_page.render_library_workspace(missing, source={}, library=library)
    assert "遺失" in "\n".join(missing.events)

    source.write_bytes(b"changed")
    changed = _LibraryStreamlit()
    changed.session_state["dashboard_library_saved_entry_id"] = entry.library_entry_id
    library_page.render_library_workspace(changed, source={}, library=library)
    assert "變更" in "\n".join(changed.events)
