from __future__ import annotations

from pathlib import Path

import pytest

from stock_tool.application.research_library import (
    DocumentCitationSelection,
    ResearchLibraryApplicationService,
)
from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
from stock_tool.research.evidence import ClaimKind, EvidenceBundle, EvidenceRecord
from stock_tool.research.library import ResearchLibrary


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="application-fixture",
        evidence=(
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="Price",
                text="Latest close is 100.",
                source="fixture",
                provider="fixture",
                symbol="MU",
                market="US",
            ),
        ),
    )


def test_application_service_registers_original_path_saves_links_and_reopens(
    tmp_path: Path,
) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic PDF bytes")
    root = tmp_path / "runtime" / "research_library"
    service = ResearchLibraryApplicationService(ResearchLibrary(root))
    registered = service.register_local_document(
        source_path=str(source.resolve()), title="Synthetic PDF"
    )
    assert registered.source_path == str(source.resolve())
    assert registered.status == "available"

    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "ai-cache")).generate(bundle)
    entry = service.save_research(
        bundle=bundle,
        note=note,
        title="Application save",
        document_selections=(
            DocumentCitationSelection(registered.document_id, ("price",), page=7),
        ),
    )
    reopened = ResearchLibrary(root)
    loaded = reopened.get(entry.library_entry_id)
    assert loaded is not None
    assert loaded.document_reference_ids == (registered.document_id,)
    assert reopened.resolve_document_references(loaded)[0].status == "available"
    metadata = (root / "documents" / "documents.json").read_bytes()
    assert b"synthetic PDF bytes" not in metadata

    source.unlink()
    assert reopened.resolve_document_references(loaded)[0].status == "missing"
    source.write_bytes(b"modified synthetic PDF bytes")
    assert reopened.resolve_document_references(loaded)[0].status == "changed"


def test_application_service_rejects_relative_or_missing_paths(tmp_path: Path) -> None:
    service = ResearchLibraryApplicationService(ResearchLibrary(tmp_path / "library"))
    with pytest.raises(ValueError):
        service.register_local_document(source_path="relative.pdf")
    with pytest.raises(ValueError):
        service.register_local_document(source_path=str(tmp_path / "missing.pdf"))


def test_application_service_optional_identifiers_and_titles_are_safe(tmp_path: Path) -> None:
    source = tmp_path / "original-name.pdf"
    source.write_bytes(b"document metadata only")
    service = ResearchLibraryApplicationService(ResearchLibrary(tmp_path / "library"))

    omitted = service.register_local_document(source_path=str(source.resolve()))
    none_values = service.register_local_document(
        source_path=str(source.resolve()), document_id=None, title=None
    )
    blank_values = service.register_local_document(
        source_path=str(source.resolve()), document_id="   ", title="\t"
    )

    registered = (omitted, none_values, blank_values)
    assert len({item.document_id for item in registered}) == 3
    assert all(item.document_id.startswith("doc-") for item in registered)
    assert all(item.document_id != "None" for item in registered)
    assert all(item.title == source.name for item in registered)
    assert all(item.title != "None" for item in registered)


def test_second_document_registration_preserves_saved_first_reference(tmp_path: Path) -> None:
    source_a = tmp_path / "first.pdf"
    source_b = tmp_path / "second.pdf"
    source_a.write_bytes(b"first original document")
    source_b.write_bytes(b"second original document")
    root = tmp_path / "runtime" / "research_library"
    service = ResearchLibraryApplicationService(ResearchLibrary(root))

    first = service.register_local_document(source_path=str(source_a.resolve()))
    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "ai-cache")).generate(bundle)
    entry = service.save_research(
        bundle=bundle,
        note=note,
        title="First-document save",
        document_selections=(DocumentCitationSelection(first.document_id, ("price",), page=3),),
    )
    second = service.register_local_document(source_path=str(source_b.resolve()))

    assert first.document_id != second.document_id
    reopened = ResearchLibrary(root)
    records = reopened.document_store.list_references()
    assert {record.document_id for record in records} == {first.document_id, second.document_id}
    assert len(records) == 2
    loaded = reopened.get(entry.library_entry_id)
    assert loaded is not None
    resolved = reopened.resolve_document_references(loaded)
    assert len(resolved) == 1
    assert resolved[0].status == "available"
    assert resolved[0].reference is not None
    assert resolved[0].reference.document_id == first.document_id
    assert resolved[0].reference.title == source_a.name
    metadata = reopened.document_store.path.read_bytes()
    assert b"first original document" not in metadata
    assert b"second original document" not in metadata
