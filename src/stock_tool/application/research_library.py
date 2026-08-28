"""Application service for local Research Library document citations.

This module is the only path used by the dashboard to register local source
files and attach their metadata-only references to a saved research version.
It never copies or reads document contents beyond ``DocumentStore`` hashing the
original local file during registration and resolution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from stock_tool.research.assistant import AIResearchNote
from stock_tool.research.evidence import EvidenceBundle
from stock_tool.research.library import ResearchDocumentLink, ResearchLibrary, ResearchLibraryEntry


@dataclass(frozen=True, slots=True)
class RegisteredLocalDocument:
    """Safe UI-facing metadata for one registered original local document."""

    document_id: str
    title: str
    source_path: str
    status: str


@dataclass(frozen=True, slots=True)
class DocumentCitationSelection:
    """A user's requested evidence/page association for one registered file."""

    document_id: str
    citation_ids: tuple[str, ...] = ()
    page: int | None = None


class ResearchLibraryApplicationService:
    """Coordinate document registration and immutable Library saves for the UI."""

    def __init__(self, library: ResearchLibrary) -> None:
        self.library = library

    def register_local_document(
        self,
        *,
        source_path: str,
        title: str | None = None,
        document_id: str | None = None,
    ) -> RegisteredLocalDocument:
        """Register an original absolute path; uploaded temporary files are not accepted."""

        raw_path = _optional_text(source_path)
        path = Path(raw_path).expanduser() if raw_path else Path()
        if not raw_path or not path.is_absolute():
            raise ValueError("Please provide the original document's absolute local path.")
        resolved = path.resolve()
        document_title = _optional_text(title) or resolved.name
        record = self.library.document_store.register(
            document_id=_optional_text(document_id) or f"doc-{uuid.uuid4().hex}",
            source_path=resolved,
            title=document_title,
        )
        return RegisteredLocalDocument(
            document_id=record.document_id,
            title=record.title,
            source_path=record.source_path,
            status="available",
        )

    def registered_local_documents(self) -> tuple[RegisteredLocalDocument, ...]:
        """Return registered documents after resolving their original paths."""

        results: list[RegisteredLocalDocument] = []
        for record in self.library.document_store.list_references(resolve=True):
            if record.state == "active":
                status = "available"
            elif record.broken_reason == "changed":
                status = "changed"
            else:
                status = "missing"
            results.append(
                RegisteredLocalDocument(
                    document_id=record.document_id,
                    title=record.title,
                    source_path=record.source_path,
                    status=status,
                )
            )
        return tuple(results)

    def save_research(
        self,
        *,
        bundle: EvidenceBundle,
        note: AIResearchNote,
        title: str,
        document_selections: Iterable[DocumentCitationSelection] = (),
    ) -> ResearchLibraryEntry:
        """Build verified document links and persist the immutable research version."""

        links = tuple(
            ResearchDocumentLink(
                document_id=selection.document_id,
                citation_ids=selection.citation_ids,
                page=selection.page,
            )
            for selection in document_selections
        )
        return self.library.save(
            bundle=bundle,
            note=note,
            title=title,
            document_references=links,
        )


def _optional_text(value: object) -> str | None:
    """Return meaningful user text without coercing ``None`` into ``\"None\"``."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
