from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
from stock_tool.research.document_store import DocumentStore
from stock_tool.research.evidence import ClaimKind, EvidenceBundle, EvidenceRecord
from stock_tool.research.library import (
    ResearchLibrary,
    ResearchLibraryEntry,
    ResearchLibraryError,
    ResearchDocumentLink,
    _content_hash,
)
from stock_tool.runtime_paths import RuntimePaths


def _bundle(symbol: str = "MU", market: str = "US") -> EvidenceBundle:
    return EvidenceBundle(
        symbol=symbol,
        market=market,
        snapshot_fingerprint="snapshot-1",
        evidence=(
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="??",
                text="????? 100?",
                source="fixture",
                provider="fixture",
                symbol=symbol,
                market=market,
                available_at="2026-07-27",
                fetched_at="2026-07-27T08:00:00+00:00",
            ),
        ),
    )


def _note(bundle: EvidenceBundle):
    return AIResearchAssistant(cache=ResearchAssistantCache(Path("unused"))).generate(bundle)


def test_save_reload_versions_and_market_identity(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    us = _bundle("MU", "US")
    tw = _bundle("MU", "TWSE")
    first = library.save(bundle=us, note=_note(us), title="MU ??")
    second = library.save(bundle=us, note=_note(us), title="MU ????")
    other_market = library.save(bundle=tw, note=_note(tw), title="?? MU")

    assert first.library_entry_id != second.library_entry_id
    assert (first.version, second.version) == (1, 2)
    loaded_first = library.get(first.library_entry_id)
    loaded_other_market = library.get(other_market.library_entry_id)
    assert loaded_first is not None and loaded_first.symbol == "MU"
    assert loaded_other_market is not None and loaded_other_market.market == "TWSE"
    assert [item.title for item in library.search(symbol="MU", market="US")] == ["MU ????", "MU ??"]


def test_delete_is_explicit_tombstone_and_preserves_record(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    entry = library.save(bundle=bundle, note=_note(bundle), title="??")
    assert library.delete(entry.library_entry_id).lifecycle_state == "deleted"
    deleted = library.get(entry.library_entry_id, include_deleted=True)
    assert deleted is not None and deleted.lifecycle_state == "deleted"
    assert library.list_entries() == ()


def test_corrupted_entry_fails_closed_without_losing_other_entries(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    saved = library.save(bundle=bundle, note=_note(bundle), title="??")
    library.entry_path(saved.library_entry_id).write_text("{bad", encoding="utf-8")
    assert library.get(saved.library_entry_id) is None
    assert library.warnings


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("note", "citations", 0, "url"), "https://forged.example"),
        (("note", "citations", 0, "provider"), "forged-provider"),
        (("note", "coverage"), 0.0),
    ),
)
def test_forged_saved_note_metadata_fails_closed(
    tmp_path: Path, path: tuple[object, ...], value: object
) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    saved = library.save(bundle=bundle, note=_note(bundle), title="研究")
    raw = json.loads(library.entry_path(saved.library_entry_id).read_text(encoding="utf-8"))
    target: Any = raw
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    library.entry_path(saved.library_entry_id).write_text(json.dumps(raw), encoding="utf-8")
    assert library.get(saved.library_entry_id) is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("sources", ["forged-provider"]),
        ("data_as_of", "2099-01-01"),
        ("snapshot_fingerprint", "forged-snapshot"),
    ),
)
def test_forged_entry_derived_metadata_fails_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    saved = library.save(bundle=bundle, note=_note(bundle), title="Saved research")
    raw = json.loads(library.entry_path(saved.library_entry_id).read_text(encoding="utf-8"))
    raw[field] = value
    library.entry_path(saved.library_entry_id).write_text(json.dumps(raw), encoding="utf-8")

    assert library.get(saved.library_entry_id) is None


def test_unknown_schema_is_rejected_and_restart_can_load_valid_entry(tmp_path: Path) -> None:
    root = tmp_path / "library"
    library = ResearchLibrary(root)
    bundle = _bundle()
    saved = library.save(bundle=bundle, note=_note(bundle), title="研究")
    assert ResearchLibrary(root).get(saved.library_entry_id) is not None
    raw = json.loads(library.entry_path(saved.library_entry_id).read_text(encoding="utf-8"))
    raw["schema_version"] = 999
    with pytest.raises(ResearchLibraryError):
        type(saved).from_dict(raw)


def test_library_runtime_path_is_isolated_from_other_user_data(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "isolated-runtime").ensure_directories()

    library = ResearchLibrary(paths.research_library_dir)
    bundle = _bundle()
    library.save(bundle=bundle, note=_note(bundle), title="隔離研究")

    assert paths.research_library_dir.is_dir()
    assert not paths.portfolio_file.exists()
    assert not paths.watchlist_file.exists()


def test_invalid_library_operations_fail_closed(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    assert library.get("missing") is None
    with pytest.raises(ResearchLibraryError):
        library.delete("missing")
    with pytest.raises(ResearchLibraryError):
        ResearchLibraryEntry.from_dict({})


def test_save_rejects_cross_market_note_and_blank_title(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    us = _bundle("MU", "US")
    tw = _bundle("MU", "TWSE")
    with pytest.raises(ResearchLibraryError):
        library.save(bundle=us, note=_note(tw), title="研究")
    with pytest.raises(ResearchLibraryError):
        library.save(bundle=us, note=_note(us), title="   ")


def test_entry_loader_rejects_duplicate_evidence_ids_and_bad_lifecycle(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    saved = library.save(bundle=bundle, note=_note(bundle), title="研究")
    raw = saved.to_dict()
    raw["lifecycle_state"] = "unsupported"
    with pytest.raises(ResearchLibraryError):
        ResearchLibraryEntry.from_dict(raw)
    raw = saved.to_dict()
    bundle_payload = raw["bundle"]
    assert isinstance(bundle_payload, dict)
    evidence = bundle_payload["evidence"]
    assert isinstance(evidence, list) and evidence
    evidence.append(evidence[0])
    with pytest.raises(ResearchLibraryError):
        ResearchLibraryEntry.from_dict(raw)


def test_optional_evidence_metadata_preserves_null_without_rendering_none(tmp_path: Path) -> None:
    bundle = EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="snapshot-1",
        evidence=(
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="Price",
                text="Latest close is 100.",
                source=None,
                provider=None,
                symbol="MU",
                market="US",
                field=None,
                url=None,
                publisher=None,
                available_at=None,
                fetched_at=None,
            ),
        ),
    )
    record = bundle.evidence[0]
    entry = ResearchLibrary(tmp_path / "library").save(
        bundle=bundle,
        note=_note(bundle),
        title="Saved research",
    )

    assert record.to_dict()["source"] is None
    assert record.to_dict()["provider"] is None
    assert record.to_dict()["publisher"] is None
    assert entry.sources == ()


def test_saved_entry_production_document_reference_resolves_available_missing_changed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "research.pdf"
    source.write_bytes(b"original document")
    document_store = DocumentStore(tmp_path / "documents")
    registered = document_store.register(
        document_id="doc-1", source_path=source, title="Research PDF"
    )
    library = ResearchLibrary(tmp_path / "library", document_store=document_store)
    bundle = _bundle()
    entry = library.save(
        bundle=bundle,
        note=_note(bundle),
        title="Saved with source",
        document_references=(ResearchDocumentLink("doc-1", ("price",), page=12),),
    )
    assert entry.document_reference_ids == (registered.document_id,)

    reopened = ResearchLibrary(
        tmp_path / "library", document_store=DocumentStore(tmp_path / "documents")
    )
    loaded = reopened.get(entry.library_entry_id)
    assert loaded is not None and loaded.document_reference_ids == ("doc-1",)
    resolved = reopened.resolve_document_references(loaded)
    assert resolved[0].status == "available"
    assert resolved[0].reference is not None and resolved[0].reference.title == "Research PDF"

    source.unlink()
    missing = reopened.resolve_document_references(loaded)
    assert missing[0].status == "missing"
    assert missing[0].reference is not None and missing[0].reference.url is None

    source.write_bytes(b"changed document")
    changed = reopened.resolve_document_references(loaded)
    assert changed[0].status == "changed"
    assert changed[0].reference is not None and changed[0].reference.url is None


def test_old_library_entry_schema_defaults_to_empty_document_references(tmp_path: Path) -> None:
    bundle = _bundle()
    entry = ResearchLibrary(tmp_path / "library").save(
        bundle=bundle, note=_note(bundle), title="Legacy entry"
    )
    legacy = entry.to_dict()
    legacy.pop("document_references")
    loaded = ResearchLibraryEntry.from_dict(legacy)
    assert loaded.document_references == ()
    assert loaded.document_reference_ids == ()


def test_library_backup_contains_document_metadata_without_document_content(tmp_path: Path) -> None:
    source = tmp_path / "private.pdf"
    source.write_bytes(b"private document content")
    store = DocumentStore(tmp_path / "library" / "documents")
    store.register(document_id="doc-1", source_path=source, title="Private PDF")
    library = ResearchLibrary(tmp_path / "library", document_store=store)
    bundle = _bundle()
    entry = library.save(
        bundle=bundle,
        note=_note(bundle),
        title="Backup metadata",
        document_references=(ResearchDocumentLink("doc-1", ("price",), page=3),),
    )
    backup = library.create_backup(tmp_path / "backup.zip")
    with ZipFile(backup.archive_path) as archive:
        names = set(archive.namelist())
        assert "documents/documents.json" in names
        assert all("private.pdf" not in name for name in names)
        assert b"private document content" not in archive.read("documents/documents.json")

    restored_root = tmp_path / "restored"
    restored = ResearchLibrary(restored_root)
    restored.restore(backup.archive_path)
    restored_entry = restored.get(entry.library_entry_id)
    assert restored_entry is not None
    assert restored_entry.document_reference_ids == ("doc-1",)


def _two_evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="snapshot-two",
        evidence=(
            EvidenceRecord(
                evidence_id="alpha",
                kind=ClaimKind.FACT,
                label="Alpha",
                text="Alpha evidence.",
                source="fixture",
                provider="fixture",
                symbol="MU",
                market="US",
            ),
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="Price",
                text="Price evidence.",
                source="fixture",
                provider="fixture",
                symbol="MU",
                market="US",
            ),
        ),
    )


def _linked_entry_for_integrity(tmp_path: Path):
    root = tmp_path / "library"
    source_a = tmp_path / "a.pdf"
    source_b = tmp_path / "b.pdf"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")
    store = DocumentStore(root / "documents")
    store.register(document_id="doc-a", source_path=source_a, title="A")
    store.register(document_id="doc-b", source_path=source_b, title="B")
    library = ResearchLibrary(root, document_store=store)
    bundle = _two_evidence_bundle()
    entry = library.save(
        bundle=bundle,
        note=_note(bundle),
        title="Reference integrity",
        document_references=(
            ResearchDocumentLink("doc-b", ("price", "alpha"), page=8),
            ResearchDocumentLink("doc-a", ("price",), page=2),
        ),
    )
    return library, entry


def test_new_document_reference_metadata_is_canonical_and_hash_protected(tmp_path: Path) -> None:
    library, entry = _linked_entry_for_integrity(tmp_path)
    assert entry.schema_version == 2
    assert entry.document_reference_ids == ("doc-a", "doc-b")
    assert entry.document_references[1].citation_ids == ("alpha", "price")
    raw = json.loads(library.entry_path(entry.library_entry_id).read_text(encoding="utf-8"))
    assert raw["document_references"] == [item.to_dict() for item in entry.document_references]
    assert raw["content_hash"] != _content_hash(entry.note, entry.bundle)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda raw: raw["document_references"][0].__setitem__("document_id", "doc-b"),
        lambda raw: raw["document_references"][0].__setitem__("citation_ids", ["alpha"]),
        lambda raw: raw["document_references"][0].__setitem__("page", 99),
        lambda raw: raw["document_references"].append(
            {"document_id": "doc-extra", "citation_ids": [], "page": None}
        ),
        lambda raw: raw["document_references"].pop(),
        lambda raw: raw["document_references"].reverse(),
        lambda raw: raw["document_references"][1].__setitem__("citation_ids", ["price", "alpha"]),
    ),
)
def test_document_reference_json_tampering_fails_closed(tmp_path: Path, mutate) -> None:
    library, entry = _linked_entry_for_integrity(tmp_path)
    raw = json.loads(library.entry_path(entry.library_entry_id).read_text(encoding="utf-8"))
    mutate(raw)
    library.entry_path(entry.library_entry_id).write_text(json.dumps(raw), encoding="utf-8")

    assert library.get(entry.library_entry_id) is None
    assert library.warnings


def test_legacy_entries_load_but_legacy_document_references_are_safely_unverified(
    tmp_path: Path,
) -> None:
    library, entry = _linked_entry_for_integrity(tmp_path)
    raw = entry.to_dict()
    raw["schema_version"] = 1
    raw["content_hash"] = _content_hash(entry.note, entry.bundle)
    raw.pop("document_references")
    legacy_without_references = ResearchLibraryEntry.from_dict(raw)
    assert legacy_without_references.document_reference_integrity == "legacy_no_references"
    assert legacy_without_references.document_references == ()

    raw["document_references"] = [item.to_dict() for item in entry.document_references]
    legacy_with_unprotected_references = ResearchLibraryEntry.from_dict(raw)
    assert legacy_with_unprotected_references.document_reference_integrity == "legacy_unverified"
    assert legacy_with_unprotected_references.document_references == ()
    assert legacy_with_unprotected_references.document_reference_ids == ()

    library.entry_path(entry.library_entry_id).write_text(json.dumps(raw), encoding="utf-8")
    loaded = library.get(entry.library_entry_id)
    assert loaded is not None
    assert loaded.document_reference_integrity == "legacy_unverified"
    assert loaded.document_references == ()


def test_backup_restore_preserves_verified_reference_metadata_and_entry_hash(
    tmp_path: Path,
) -> None:
    library, entry = _linked_entry_for_integrity(tmp_path)
    backup = library.create_backup(tmp_path / "verified-references.zip")
    restored = ResearchLibrary(tmp_path / "restored")
    restored.restore(backup.archive_path)

    loaded = restored.get(entry.library_entry_id)
    assert loaded is not None
    assert loaded.content_hash == entry.content_hash
    assert loaded.document_references == entry.document_references
    assert loaded.document_reference_integrity == "verified"
    assert (restored.directory / "documents" / "documents.json").read_text(encoding="utf-8") == (
        library.directory / "documents" / "documents.json"
    ).read_text(encoding="utf-8")
