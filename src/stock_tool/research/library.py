"""Versioned, local-only Research Library with verified backup and restore."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import replace
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from stock_tool.domain.models import Market, Symbol
from stock_tool.research.assistant import (
    AIResearchNote,
    _citations_for_claims,
    _confidence,
    _coverage,
    _missing_texts,
)
from stock_tool.research.citations import ResearchClaimValidationError, validate_research_claims
from stock_tool.research.document_store import DocumentReference, DocumentStore
from stock_tool.research.evidence import ClaimKind, EvidenceBundle, EvidenceRecord

_ENTRY_SCHEMA_VERSION = 2
_LEGACY_ENTRY_SCHEMA_VERSION = 1
_BACKUP_SCHEMA_VERSION = 1
_INDEX_NAME = "library-index.json"
_ENTRY_DIR = "entries"
_DOCUMENT_DIR = "documents"
_MANIFEST_NAME = "RESEARCH_LIBRARY_MANIFEST.json"
_MAX_BACKUP_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_BACKUP_UNCOMPRESSED_BYTES = 128 * 1024 * 1024


class ResearchLibraryError(ValueError):
    """Raised for invalid or unsafe local research-library data."""


class ResearchLibraryRestoreError(ResearchLibraryError):
    """Raised when a backup cannot be validated and restored atomically."""


@dataclass(frozen=True, slots=True)
class ResearchDocumentLink:
    """A saved citation-to-document link containing metadata only, never content."""

    document_id: str
    citation_ids: tuple[str, ...] = ()
    page: int | None = None

    def __post_init__(self) -> None:
        document_id = str(self.document_id).strip()
        citation_ids = tuple(str(item).strip() for item in self.citation_ids if str(item).strip())
        if (
            not document_id
            or not _safe_id(document_id)
            or len(set(citation_ids)) != len(citation_ids)
            or (
                self.page is not None
                and (isinstance(self.page, bool) or not isinstance(self.page, int) or self.page < 1)
            )
        ):
            raise ResearchLibraryError("Research document link is invalid.")
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "citation_ids", citation_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "citation_ids": list(self.citation_ids),
            "page": self.page,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ResearchDocumentLink":
        if not isinstance(payload, dict) or set(payload) != {"document_id", "citation_ids", "page"}:
            raise ResearchLibraryError("Research document link schema is invalid.")
        citation_ids = payload["citation_ids"]
        if not isinstance(citation_ids, list) or any(
            not isinstance(item, str) for item in citation_ids
        ):
            raise ResearchLibraryError("Research document link citations are invalid.")
        page = payload["page"]
        if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
            raise ResearchLibraryError("Research document link page is invalid.")
        return cls(
            document_id=str(payload["document_id"]), citation_ids=tuple(citation_ids), page=page
        )


@dataclass(frozen=True, slots=True)
class ResolvedResearchDocument:
    """One saved document link resolved through DocumentStore at display time."""

    link: ResearchDocumentLink
    reference: DocumentReference | None
    status: str


@dataclass(frozen=True, slots=True)
class ResearchLibraryEntry:
    """Immutable version of one saved, evidence-linked research result."""

    library_entry_id: str
    schema_version: int
    symbol: str
    market: str
    title: str
    created_at: str
    updated_at: str
    version: int
    lifecycle_state: str
    snapshot_fingerprint: str
    evidence_fingerprint: str
    content_hash: str
    data_as_of: str | None
    sources: tuple[str, ...]
    note: AIResearchNote
    bundle: EvidenceBundle
    document_references: tuple[ResearchDocumentLink, ...] = ()
    document_reference_integrity: str = "verified"

    def __post_init__(self) -> None:
        try:
            identity = Symbol.parse(self.symbol, market=Market.parse(self.market))
        except ValueError as exc:
            raise ResearchLibraryError("Research library identity is invalid.") from exc
        if (
            self.schema_version not in {_LEGACY_ENTRY_SCHEMA_VERSION, _ENTRY_SCHEMA_VERSION}
            or not self.library_entry_id
            or not self.title.strip()
        ):
            raise ResearchLibraryError("Research library entry schema is invalid.")
        if self.lifecycle_state not in {"active", "deleted", "broken_reference", "restored"}:
            raise ResearchLibraryError("Research library lifecycle state is invalid.")
        if identity.code != self.note.symbol or identity.market.value != self.note.market:
            raise ResearchLibraryError("Saved note identity does not match Research Library entry.")
        if identity.code != self.bundle.symbol or identity.market.value != self.bundle.market:
            raise ResearchLibraryError(
                "Saved evidence identity does not match Research Library entry."
            )
        _validate_note(self.note, self.bundle)
        if len({link.document_id for link in self.document_references}) != len(
            self.document_references
        ):
            raise ResearchLibraryError("Saved document references must be unique.")
        citation_ids = {record.evidence_id for record in self.bundle.evidence}
        if any(
            citation_id not in citation_ids
            for link in self.document_references
            for citation_id in link.citation_ids
        ):
            raise ResearchLibraryError("Saved document link cites unknown evidence.")
        if self.snapshot_fingerprint != self.bundle.snapshot_fingerprint:
            raise ResearchLibraryError("Saved snapshot fingerprint is invalid.")
        if self.sources != _sources(self.bundle) or self.data_as_of != _data_as_of(self.bundle):
            raise ResearchLibraryError("Saved research derived metadata is invalid.")
        if self.schema_version == _ENTRY_SCHEMA_VERSION:
            canonical_links = _canonical_document_references(self.document_references)
            if self.document_references != canonical_links:
                raise ResearchLibraryError("Saved document references are not in canonical order.")
            expected = _content_hash(self.note, self.bundle, canonical_links)
            if self.document_reference_integrity != "verified":
                raise ResearchLibraryError("Saved document reference integrity state is invalid.")
        else:
            expected = _content_hash(self.note, self.bundle)
            integrity = "legacy_unverified" if self.document_references else "legacy_no_references"
            object.__setattr__(self, "document_reference_integrity", integrity)
            if integrity == "legacy_unverified":
                # Sprint 17.1.1 references were not covered by content_hash.
                # Keep the entry readable but never expose those forgeable links.
                object.__setattr__(self, "document_references", ())
        if self.content_hash != expected or self.evidence_fingerprint != self.bundle.fingerprint:
            raise ResearchLibraryError("Saved research content hash is invalid.")
        object.__setattr__(self, "symbol", identity.code)
        object.__setattr__(self, "market", identity.market.value)
        object.__setattr__(self, "sources", tuple(sorted(set(self.sources))))

    @property
    def document_reference_ids(self) -> tuple[str, ...]:
        """Stable document IDs persisted with this immutable saved version."""

        return tuple(link.document_id for link in self.document_references)

    def to_dict(self) -> dict[str, object]:
        return {
            "library_entry_id": self.library_entry_id,
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "market": self.market,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "lifecycle_state": self.lifecycle_state,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "evidence_fingerprint": self.evidence_fingerprint,
            "content_hash": self.content_hash,
            "data_as_of": self.data_as_of,
            "sources": list(self.sources),
            "note": self.note.to_dict(),
            "bundle": {
                "symbol": self.bundle.symbol,
                "market": self.bundle.market,
                "snapshot_fingerprint": self.bundle.snapshot_fingerprint,
                "evidence": [item.to_dict() for item in self.bundle.evidence],
            },
            "document_references": [item.to_dict() for item in self.document_references],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ResearchLibraryEntry":
        required = {
            "library_entry_id",
            "schema_version",
            "symbol",
            "market",
            "title",
            "created_at",
            "updated_at",
            "version",
            "lifecycle_state",
            "snapshot_fingerprint",
            "evidence_fingerprint",
            "content_hash",
            "data_as_of",
            "sources",
            "note",
            "bundle",
        }
        if not isinstance(payload, dict) or set(payload) not in (
            required,
            required | {"document_references"},
        ):
            raise ResearchLibraryError("Research library entry has an unsupported schema.")
        bundle_payload = payload["bundle"]
        if (
            not isinstance(bundle_payload, dict)
            or set(bundle_payload) != {"symbol", "market", "snapshot_fingerprint", "evidence"}
            or not isinstance(bundle_payload["evidence"], list)
        ):
            raise ResearchLibraryError("Saved evidence bundle is invalid.")
        try:
            bundle = EvidenceBundle(
                symbol=str(bundle_payload["symbol"]),
                market=str(bundle_payload["market"]),
                snapshot_fingerprint=str(bundle_payload["snapshot_fingerprint"]),
                evidence=tuple(_evidence_from_dict(row) for row in bundle_payload["evidence"]),
            )
            sources = payload["sources"]
            if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
                raise ValueError
            note = AIResearchNote.from_dict(payload["note"])
            if isinstance(payload["note"], dict) and payload["note"].get("model") is None:
                note = replace(note, model=None)
            document_references_payload = payload.get("document_references", [])
            if not isinstance(document_references_payload, list):
                raise ValueError
            return cls(
                library_entry_id=str(payload["library_entry_id"]),
                schema_version=int(payload["schema_version"]),
                symbol=str(payload["symbol"]),
                market=str(payload["market"]),
                title=str(payload["title"]),
                created_at=str(payload["created_at"]),
                updated_at=str(payload["updated_at"]),
                version=int(payload["version"]),
                lifecycle_state=str(payload["lifecycle_state"]),
                snapshot_fingerprint=str(payload["snapshot_fingerprint"]),
                evidence_fingerprint=str(payload["evidence_fingerprint"]),
                content_hash=str(payload["content_hash"]),
                data_as_of=_optional_text(payload["data_as_of"]),
                sources=tuple(sources),
                note=note,
                bundle=bundle,
                document_references=tuple(
                    ResearchDocumentLink.from_dict(item) for item in document_references_payload
                ),
                document_reference_integrity="verified",
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ResearchLibraryError("Research library entry is corrupted.") from exc


@dataclass(frozen=True, slots=True)
class ResearchLibraryBackup:
    archive_path: Path
    sha256: str
    entry_count: int


class ResearchLibrary:
    """Private append-versioned store independent of provider and AI caches."""

    def __init__(self, directory: Path, *, document_store: DocumentStore | None = None) -> None:
        self.directory = Path(directory)
        self.entries_dir = self.directory / _ENTRY_DIR
        self.index_path = self.directory / _INDEX_NAME
        self.document_store = document_store or DocumentStore(self.directory / _DOCUMENT_DIR)
        self.warnings: tuple[str, ...] = ()

    def entry_path(self, entry_id: str) -> Path:
        if not _safe_id(entry_id):
            raise ResearchLibraryError("Research library entry ID is invalid.")
        return self.entries_dir / f"{entry_id}.json"

    def save(
        self,
        *,
        bundle: EvidenceBundle,
        note: AIResearchNote,
        title: str,
        document_references: Iterable[ResearchDocumentLink] = (),
    ) -> ResearchLibraryEntry:
        _validate_note(note, bundle)
        links = _canonical_document_references(tuple(document_references))
        self._validate_document_references(links, bundle)
        identity = Symbol.parse(bundle.symbol, market=bundle.market)
        now = _now()
        existing = self.list_entries(include_deleted=True)
        version = 1 + max(
            (
                item.version
                for item in existing
                if item.symbol == identity.code and item.market == identity.market.value
            ),
            default=0,
        )
        entry = ResearchLibraryEntry(
            library_entry_id=str(uuid.uuid4()),
            schema_version=_ENTRY_SCHEMA_VERSION,
            symbol=identity.code,
            market=identity.market.value,
            title=str(title).strip(),
            created_at=now,
            updated_at=now,
            version=version,
            lifecycle_state="active",
            snapshot_fingerprint=bundle.snapshot_fingerprint,
            evidence_fingerprint=bundle.fingerprint,
            content_hash=_content_hash(note, bundle, links),
            data_as_of=_data_as_of(bundle),
            sources=_sources(bundle),
            note=note,
            bundle=bundle,
            document_references=links,
            document_reference_integrity="verified",
        )
        self._write_entry(entry)
        self._write_index(self.list_entries(include_deleted=True))
        return entry

    def resolve_document_references(
        self, entry: ResearchLibraryEntry
    ) -> tuple[ResolvedResearchDocument, ...]:
        """Resolve saved links without reading or copying document contents."""

        resolved: list[ResolvedResearchDocument] = []
        for link in entry.document_references:
            reference = self.document_store.resolve(link.document_id)
            if reference is None or reference.state == "deleted":
                status = "missing"
            elif reference.state == "broken_reference":
                status = "changed" if reference.broken_reason == "changed" else "missing"
            else:
                status = "available"
            resolved.append(ResolvedResearchDocument(link=link, reference=reference, status=status))
        return tuple(resolved)

    def _validate_document_references(
        self, links: tuple[ResearchDocumentLink, ...], bundle: EvidenceBundle
    ) -> None:
        citation_ids = {record.evidence_id for record in bundle.evidence}
        if len({link.document_id for link in links}) != len(links):
            raise ResearchLibraryError("Saved document references must be unique.")
        for link in links:
            if any(citation_id not in citation_ids for citation_id in link.citation_ids):
                raise ResearchLibraryError("Saved document link cites unknown evidence.")
            reference = self.document_store.resolve(link.document_id)
            if reference is None or reference.state != "active":
                raise ResearchLibraryError("Saved document reference is unavailable.")

    def get(self, entry_id: str, *, include_deleted: bool = False) -> ResearchLibraryEntry | None:
        try:
            entry = self._read_entry(entry_id)
        except ResearchLibraryError:
            self.warnings = ("研究庫資料損毀或不相容，已安全略過。",)
            return None
        if entry is None or (entry.lifecycle_state == "deleted" and not include_deleted):
            return None
        return entry

    def list_entries(self, *, include_deleted: bool = False) -> tuple[ResearchLibraryEntry, ...]:
        self.warnings = ()
        if not self.entries_dir.is_dir():
            return ()
        entries: list[ResearchLibraryEntry] = []
        warnings: list[str] = []
        for path in sorted(self.entries_dir.glob("*.json")):
            try:
                entry = ResearchLibraryEntry.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ResearchLibraryError,
                ValueError,
            ):
                warnings.append("研究庫含損毀或不相容項目，已安全略過。")
                continue
            if include_deleted or entry.lifecycle_state != "deleted":
                entries.append(entry)
        self.warnings = tuple(dict.fromkeys(warnings))
        return tuple(
            sorted(entries, key=lambda item: (item.updated_at, item.library_entry_id), reverse=True)
        )

    def search(
        self, *, symbol: str | None = None, market: str | None = None, title: str | None = None
    ) -> tuple[ResearchLibraryEntry, ...]:
        code = str(symbol or "").strip().upper()
        selected_market = str(market or "").strip().upper()
        text = str(title or "").strip().casefold()
        return tuple(
            item
            for item in self.list_entries()
            if (not code or item.symbol == code)
            and (not selected_market or item.market == selected_market)
            and (not text or text in item.title.casefold())
        )

    def delete(self, entry_id: str) -> ResearchLibraryEntry:
        entry = self.get(entry_id, include_deleted=True)
        if entry is None:
            raise ResearchLibraryError("Research library entry does not exist.")
        tombstone = ResearchLibraryEntry.from_dict(
            {**entry.to_dict(), "lifecycle_state": "deleted", "updated_at": _now()}
        )
        self._write_entry(tombstone)
        self._write_index(self.list_entries(include_deleted=True))
        return tombstone

    def library_hash(self) -> str:
        return _hash_files(self.directory)

    def create_backup(self, archive_path: Path) -> ResearchLibraryBackup:
        entries = self.list_entries(include_deleted=True)
        self._write_index(entries)
        archive_path = Path(archive_path)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = _backup_manifest(self.directory)
        manifest_files = manifest["files"]
        if not isinstance(manifest_files, dict):
            raise ResearchLibraryError("Research library backup manifest is invalid.")
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            for relative in manifest_files:
                archive.write(self.directory / str(relative), str(relative))
            archive.writestr(
                _MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, sort_keys=True)
            )
        digest = _sha256(archive_path)
        archive_path.with_suffix(archive_path.suffix + ".sha256").write_text(
            f"{digest}  {archive_path.name}\n", encoding="ascii"
        )
        return ResearchLibraryBackup(
            archive_path=archive_path, sha256=digest, entry_count=len(entries)
        )

    def restore(self, archive_path: Path) -> None:
        archive_path = Path(archive_path)
        staging = self.directory.parent / f".{self.directory.name}-restore-{uuid.uuid4().hex}"
        rollback = self.directory.parent / f".{self.directory.name}-rollback-{uuid.uuid4().hex}"
        try:
            _extract_verified_backup(archive_path, staging)
            candidate = ResearchLibrary(staging)
            candidate_entries = candidate.list_entries(include_deleted=True)
            if candidate.warnings:
                raise ResearchLibraryRestoreError("Research library backup is invalid.")
            candidate._write_index(candidate_entries)
            if self.directory.exists():
                os.replace(self.directory, rollback)
            os.replace(staging, self.directory)
            shutil.rmtree(rollback, ignore_errors=True)
        except Exception as exc:
            if self.directory.exists() and rollback.exists():
                shutil.rmtree(self.directory, ignore_errors=True)
            if rollback.exists():
                os.replace(rollback, self.directory)
            raise ResearchLibraryRestoreError("Research library restore failed safely.") from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _read_entry(self, entry_id: str) -> ResearchLibraryEntry | None:
        path = self.entry_path(entry_id)
        if not path.is_file():
            return None
        try:
            return ResearchLibraryEntry.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ResearchLibraryError("Research library entry is corrupted.") from exc

    def _write_entry(self, entry: ResearchLibraryEntry) -> None:
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.entry_path(entry.library_entry_id), entry.to_dict())

    def _write_index(self, entries: tuple[ResearchLibraryEntry, ...]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            self.index_path,
            {
                "schema_version": _BACKUP_SCHEMA_VERSION,
                "entries": [
                    {
                        "library_entry_id": item.library_entry_id,
                        "symbol": item.symbol,
                        "market": item.market,
                        "title": item.title,
                        "updated_at": item.updated_at,
                        "lifecycle_state": item.lifecycle_state,
                    }
                    for item in entries
                ],
            },
        )


def _validate_note(note: AIResearchNote, bundle: EvidenceBundle) -> None:
    if (
        note.symbol != bundle.symbol
        or note.market != bundle.market
        or note.fingerprint != bundle.fingerprint
    ):
        raise ResearchLibraryError("Saved research note does not match its evidence bundle.")
    try:
        validated, _ = validate_research_claims(note.claims, bundle, fail_closed=True)
    except ResearchClaimValidationError as exc:
        raise ResearchLibraryError("Saved research claims failed citation validation.") from exc
    if validated != note.claims or note.citations != _citations_for_claims(note.claims, bundle):
        raise ResearchLibraryError("Saved research citations are not evidence-linked.")
    if (
        note.coverage != _coverage(bundle)
        or note.confidence_label != _confidence(bundle)
        or note.missing_data != _missing_texts(bundle)
    ):
        raise ResearchLibraryError("Saved research derived metadata is invalid.")


def _evidence_from_dict(payload: object) -> EvidenceRecord:
    if not isinstance(payload, dict) or set(payload) != {
        "evidence_id",
        "kind",
        "label",
        "text",
        "source",
        "provider",
        "symbol",
        "market",
        "field",
        "url",
        "publisher",
        "available_at",
        "fetched_at",
    }:
        raise ValueError
    return EvidenceRecord(
        evidence_id=str(payload["evidence_id"]),
        kind=ClaimKind(str(payload["kind"])),
        label=str(payload["label"]),
        text=str(payload["text"]),
        source=_optional_text(payload["source"]),
        provider=_optional_text(payload["provider"]),
        symbol=str(payload["symbol"]),
        market=str(payload["market"]),
        field=_optional_text(payload["field"]),
        url=_optional_text(payload["url"]),
        publisher=_optional_text(payload["publisher"]),
        available_at=_optional_text(payload["available_at"]),
        fetched_at=_optional_text(payload["fetched_at"]),
    )


def _canonical_document_references(
    links: Iterable[ResearchDocumentLink],
) -> tuple[ResearchDocumentLink, ...]:
    """Return the one persisted ordering for reference IDs, evidence IDs, and pages."""

    normalized = tuple(
        ResearchDocumentLink(
            document_id=link.document_id,
            citation_ids=tuple(sorted(link.citation_ids)),
            page=link.page,
        )
        for link in links
    )
    return tuple(sorted(normalized, key=lambda link: link.document_id))


def _content_hash(
    note: AIResearchNote,
    bundle: EvidenceBundle,
    document_references: Iterable[ResearchDocumentLink] | None = None,
) -> str:
    payload: dict[str, object] = {
        "note": note.to_dict(),
        "bundle": {
            "symbol": bundle.symbol,
            "market": bundle.market,
            "snapshot_fingerprint": bundle.snapshot_fingerprint,
            "evidence": [row.to_dict() for row in bundle.evidence],
        },
    }
    if document_references is not None:
        payload["document_references"] = [
            link.to_dict() for link in _canonical_document_references(document_references)
        ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sources(bundle: EvidenceBundle) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item
                for record in bundle.evidence
                for item in (record.source, record.provider)
                if item
            }
        )
    )


def _data_as_of(bundle: EvidenceBundle) -> str | None:
    values = sorted(record.available_at for record in bundle.evidence if record.available_at)
    return values[-1] if values else None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _safe_id(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character == "-" for character in value)


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".research-library-", suffix=".json", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _backup_manifest(root: Path) -> dict[str, object]:
    files = _library_relative_files(root)
    return {
        "schema_version": _BACKUP_SCHEMA_VERSION,
        "created_at": _now(),
        "file_count": len(files),
        "files": {
            item: {"size": (root / item).stat().st_size, "sha256": _sha256(root / item)}
            for item in files
        },
    }


def _extract_verified_backup(archive_path: Path, destination: Path) -> None:
    try:
        with ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if any(item.is_dir() for item in infos):
                raise ValueError
            names = [item.filename for item in infos]
            if (
                _MANIFEST_NAME not in names
                or len(names) != len(set(names))
                or any(not _safe_archive_name(name) for name in names)
            ):
                raise ValueError
            if (
                any(
                    item.file_size < 0 or item.file_size > _MAX_BACKUP_MEMBER_BYTES
                    for item in infos
                )
                or sum(item.file_size for item in infos) > _MAX_BACKUP_UNCOMPRESSED_BYTES
            ):
                raise ValueError
            manifest = json.loads(archive.read(_MANIFEST_NAME).decode("utf-8"))
            if (
                not isinstance(manifest, dict)
                or set(manifest) != {"schema_version", "created_at", "file_count", "files"}
                or manifest["schema_version"] != _BACKUP_SCHEMA_VERSION
                or not isinstance(manifest["created_at"], str)
                or not manifest["created_at"].strip()
                or isinstance(manifest["file_count"], bool)
                or not isinstance(manifest["file_count"], int)
                or not isinstance(manifest.get("files"), dict)
            ):
                raise ValueError
            raw_files = manifest["files"]
            if (
                not isinstance(raw_files, dict)
                or manifest["file_count"] != len(raw_files)
                or any(not isinstance(name, str) for name in raw_files)
            ):
                raise ValueError
            files = dict(raw_files)
            if set(names) != set(files) | {_MANIFEST_NAME}:
                raise ValueError
            info_by_name = {item.filename: item for item in infos}
            for name, metadata in files.items():
                path = PurePosixPath(name)
                if (
                    not _safe_library_member_name(name)
                    or not isinstance(metadata, dict)
                    or set(metadata) != {"size", "sha256"}
                    or isinstance(metadata["size"], bool)
                    or not isinstance(metadata["size"], int)
                    or metadata["size"] < 0
                    or metadata["size"] > _MAX_BACKUP_MEMBER_BYTES
                    or not isinstance(metadata["sha256"], str)
                    or len(metadata["sha256"]) != 64
                    or any(character not in "0123456789abcdef" for character in metadata["sha256"])
                    or info_by_name[name].file_size != metadata["size"]
                ):
                    raise ValueError
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                if target.stat().st_size != metadata.get("size") or _sha256(target) != metadata.get(
                    "sha256"
                ):
                    raise ValueError
            _library_relative_files(destination)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ResearchLibraryRestoreError("Research library backup failed validation.") from exc


def _hash_files(root: Path) -> str:
    if not root.is_dir():
        return hashlib.sha256(b"").hexdigest()
    payload = {
        path.relative_to(root).as_posix(): _sha256(path) for path in sorted(root.rglob("*.json"))
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _safe_library_member_name(name: str) -> bool:
    if not _safe_archive_name(name):
        return False
    if name == _INDEX_NAME:
        return True
    path = PurePosixPath(name)
    return (
        len(path.parts) == 2
        and path.parts[0] in {_ENTRY_DIR, _DOCUMENT_DIR}
        and path.suffix == ".json"
        and (_safe_id(path.stem) if path.parts[0] == _ENTRY_DIR else path.name == "documents.json")
    )


def _library_relative_files(root: Path) -> list[str]:
    if not root.is_dir():
        raise ResearchLibraryError("Research library storage is unavailable.")
    files = [item.relative_to(root).as_posix() for item in sorted(root.rglob("*.json"))]
    if _INDEX_NAME not in files or any(not _safe_library_member_name(item) for item in files):
        raise ResearchLibraryError("Research library contains unsupported files.")
    return files


def _now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "ResearchLibrary",
    "ResearchLibraryBackup",
    "ResearchLibraryEntry",
    "ResearchLibraryError",
    "ResearchLibraryRestoreError",
    "ResearchDocumentLink",
    "ResolvedResearchDocument",
]
