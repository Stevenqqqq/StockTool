"""Private document-reference metadata for the local Research Library.

The store never copies document content.  It only records an explicit local
reference and hash so a later missing file is shown as broken, never as a
verifiable citation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DocumentReference:
    """Metadata for one user-selected local document, without its contents."""

    document_id: str
    title: str
    source_path: str
    content_hash: str | None
    created_at: str
    updated_at: str
    state: str = "active"
    url: str | None = None
    broken_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.document_id, str)
            or not self.document_id.strip()
            or not isinstance(self.title, str)
            or not self.title.strip()
            or not isinstance(self.source_path, str)
            or not self.source_path.strip()
            or not isinstance(self.created_at, str)
            or not self.created_at.strip()
            or not isinstance(self.updated_at, str)
            or not self.updated_at.strip()
            or not isinstance(self.state, str)
            or self.state not in {"active", "deleted", "broken_reference", "restored"}
            or (self.content_hash is not None and not _is_sha256(self.content_hash))
            or (self.url is not None and not isinstance(self.url, str))
            or self.broken_reason not in {None, "missing", "changed"}
            or (self.state == "active" and self.broken_reason is not None)
        ):
            raise ValueError("Research document metadata is invalid.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "DocumentReference":
        required = {
            "document_id",
            "title",
            "source_path",
            "content_hash",
            "created_at",
            "updated_at",
            "state",
            "url",
        }
        if not isinstance(payload, dict) or set(payload) not in (
            required,
            required | {"broken_reason"},
        ):
            raise ValueError("Research document metadata is invalid.")
        result = cls(**{**payload, "broken_reason": payload.get("broken_reason")})
        return result


class DocumentStore:
    """Atomic document metadata store; document contents remain outside it."""

    _SCHEMA_VERSION = 1

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / "documents.json"

    def register(
        self, *, document_id: str | None, source_path: Path, title: str | None
    ) -> DocumentReference:
        document_id = _required_text(document_id)
        title = _required_text(title)
        source = Path(source_path).resolve()
        if not document_id or not title or not source.is_file():
            raise ValueError("Document registration requires an existing file and metadata.")
        now = _now()
        records = self._load()
        existing = records.get(document_id)
        record = DocumentReference(
            document_id=document_id,
            title=title,
            source_path=str(source),
            content_hash=_sha256(source),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            state="active",
            url=None,
        )
        records[document_id] = record
        self._save(records)
        return record

    def resolve(self, document_id: str) -> DocumentReference | None:
        records = self._load()
        record = records.get(str(document_id).strip())
        if record is None or record.state == "deleted":
            return record
        source = Path(record.source_path)
        is_intact = False
        try:
            is_intact = source.is_file() and (
                record.content_hash is not None and _sha256(source) == record.content_hash
            )
        except OSError:
            is_intact = False
        next_state = "active" if is_intact else "broken_reference"
        next_reason = None if is_intact else ("missing" if not source.is_file() else "changed")
        if record.state != next_state or record.broken_reason != next_reason:
            record = DocumentReference(
                document_id=record.document_id,
                title=record.title,
                source_path=record.source_path,
                content_hash=record.content_hash,
                created_at=record.created_at,
                updated_at=_now(),
                state=next_state,
                url=None,
                broken_reason=next_reason,
            )
            records[record.document_id] = record
            self._save(records)
        return record

    def list_references(self, *, resolve: bool = False) -> tuple[DocumentReference, ...]:
        """List registered metadata without copying document contents."""

        records = self._load()
        if not resolve:
            return tuple(records[key] for key in sorted(records))
        return tuple(
            resolved for key in sorted(records) if (resolved := self.resolve(key)) is not None
        )

    def _load(self) -> dict[str, DocumentReference]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != self._SCHEMA_VERSION
            ):
                raise ValueError
            items = payload.get("documents")
            if not isinstance(items, list):
                raise ValueError
            records = {
                item.document_id: item
                for item in (DocumentReference.from_dict(row) for row in items)
            }
            if len(records) != len(items):
                raise ValueError
            return records
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("Research document metadata is corrupted.") from exc

    def _save(self, records: dict[str, DocumentReference]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            self.path,
            {
                "schema_version": self._SCHEMA_VERSION,
                "documents": [records[key].to_dict() for key in sorted(records)],
            },
        )


def _atomic_json(path: Path, payload: object) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".document-", suffix=".json", dir=path.parent
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _required_text(value: object) -> str | None:
    """Validate explicit metadata without ever converting ``None`` to text."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _now() -> str:
    return datetime.now(UTC).isoformat()
