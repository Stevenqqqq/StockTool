from __future__ import annotations

from pathlib import Path

import pytest

from stock_tool.research.document_store import DocumentReference, DocumentStore


def test_removed_document_is_marked_broken_without_fake_url(tmp_path: Path) -> None:
    source = tmp_path / "private.pdf"
    source.write_bytes(b"private")
    store = DocumentStore(tmp_path / "documents")
    record = store.register(document_id="doc-1", source_path=source, title="????")
    assert record.state == "active"
    source.unlink()
    broken = store.resolve("doc-1")
    assert broken is not None
    assert broken.state == "broken_reference"
    assert broken.url is None
    assert broken.content_hash is not None


def test_document_metadata_rejects_corruption_and_missing_registration(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "documents")
    assert store.resolve("missing") is None
    with pytest.raises(ValueError):
        store.register(document_id="", source_path=tmp_path / "missing.pdf", title="")
    store.path.parent.mkdir(parents=True)
    store.path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupted"):
        store.resolve("missing")


def test_changed_document_is_marked_broken_by_hash_without_a_fake_url(tmp_path: Path) -> None:
    source = tmp_path / "private.pdf"
    source.write_bytes(b"original")
    store = DocumentStore(tmp_path / "documents")
    record = store.register(document_id="doc-1", source_path=source, title="Private document")
    source.write_bytes(b"changed")

    broken = store.resolve(record.document_id)

    assert broken is not None
    assert broken.state == "broken_reference"
    assert broken.content_hash == record.content_hash
    assert broken.url is None


def test_unchanged_document_remains_an_active_verified_reference(tmp_path: Path) -> None:
    source = tmp_path / "private.pdf"
    source.write_bytes(b"original")
    store = DocumentStore(tmp_path / "documents")
    record = store.register(document_id="doc-1", source_path=source, title="Private document")

    resolved = store.resolve(record.document_id)

    assert resolved == record


def test_reregistering_document_preserves_created_time_and_replaces_hash(tmp_path: Path) -> None:
    source = tmp_path / "private.pdf"
    source.write_bytes(b"original")
    store = DocumentStore(tmp_path / "documents")
    first = store.register(document_id="doc-1", source_path=source, title="Private document")
    source.write_bytes(b"replacement")

    second = store.register(document_id="doc-1", source_path=source, title="Updated document")

    assert second.created_at == first.created_at
    assert second.title == "Updated document"
    assert second.content_hash != first.content_hash


def test_document_metadata_with_invalid_field_type_fails_closed(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "documents")
    store.path.parent.mkdir(parents=True)
    store.path.write_text(
        '{"schema_version":1,"documents":[{"document_id":"doc","title":"title",'
        '"source_path":null,"content_hash":null,"created_at":"now","updated_at":"now",'
        '"state":"active","url":null}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="corrupted"):
        store.resolve("doc")


def test_document_reference_schema_rejects_unknown_state(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        DocumentReference.from_dict(
            {
                "document_id": "doc",
                "title": "title",
                "source_path": str(tmp_path / "source.pdf"),
                "content_hash": None,
                "created_at": "2026-07-27T00:00:00+00:00",
                "updated_at": "2026-07-27T00:00:00+00:00",
                "state": "unknown",
                "url": None,
            }
        )
    with pytest.raises(ValueError):
        DocumentReference.from_dict({})
    with pytest.raises(ValueError):
        DocumentReference.from_dict(
            {
                "document_id": "doc",
                "title": "title",
                "source_path": str(tmp_path / "source.pdf"),
                "content_hash": "not-a-sha256",
                "created_at": "2026-07-27T00:00:00+00:00",
                "updated_at": "2026-07-27T00:00:00+00:00",
                "state": "active",
                "url": None,
            }
        )
