"""Repository boundary for additive, market-qualified research storage."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from datetime import date
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.data.storage import SQLitePriceStorage
from stock_tool.domain.models import Market, Symbol

_RECORD_STATES = frozenset({"complete", "partial", "stale", "unknown"})


class RepositoryDataError(ValueError):
    """Raised when a repository record is incomplete, invalid, or corrupted."""


@dataclass(frozen=True, slots=True)
class ResearchIdentity:
    """Stable storage identity delegated to the canonical domain symbol parser."""

    symbol: str
    market: str

    def __post_init__(self) -> None:
        raw_market = str(self.market).strip().upper()
        if raw_market == "UNKNOWN":
            try:
                unresolved = Symbol.parse(str(self.symbol), market=Market.AUTO)
            except ValueError as exc:
                raise RepositoryDataError("Research identity requires a symbol.") from exc
            if unresolved.market is not Market.AUTO:
                raise RepositoryDataError(
                    "An unresolved research identity cannot include a market-resolving suffix."
                )
            object.__setattr__(self, "symbol", unresolved.code)
            object.__setattr__(self, "market", "UNKNOWN")
            return

        try:
            market = Market.parse(self.market)
            if market not in {Market.TWSE, Market.TPEX, Market.US}:
                raise ValueError("Research storage requires an explicit market or UNKNOWN.")
            symbol = Symbol.parse(str(self.symbol), market=market)
        except ValueError as exc:
            raise RepositoryDataError(f"Invalid research identity market/symbol: {exc}") from exc
        object.__setattr__(self, "symbol", symbol.code)
        object.__setattr__(self, "market", symbol.market.value)


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    """Redacted provider/source metadata persisted with one research record."""

    provider: str
    source_type: str
    provider_symbol: str | None
    source_url: str | None
    fetched_at: str
    updated_at: str
    state: str = "complete"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider = _required_text(self.provider, "provider")
        source_type = _required_text(self.source_type, "source_type")
        fetched_at = _required_text(self.fetched_at, "fetched_at")
        updated_at = _required_text(self.updated_at, "updated_at")
        state = _normalize_state(self.state)
        object.__setattr__(self, "provider", sanitize_provider_text(provider))
        object.__setattr__(self, "source_type", sanitize_provider_text(source_type))
        object.__setattr__(
            self,
            "provider_symbol",
            _optional_sanitized_text(self.provider_symbol),
        )
        object.__setattr__(self, "source_url", _optional_sanitized_text(self.source_url))
        object.__setattr__(self, "fetched_at", fetched_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "warnings",
            tuple(sanitize_provider_text(str(item)) for item in self.warnings),
        )


@dataclass(frozen=True, slots=True)
class FundamentalRecord:
    """One fiscal-period fundamental record with explicit provenance and state."""

    identity: ResearchIdentity
    fiscal_period: str
    period_type: str
    as_of_date: str | None
    metrics: Mapping[str, Any]
    provenance: ResearchProvenance

    def __post_init__(self) -> None:
        fiscal_period = _required_text(self.fiscal_period, "fiscal_period")
        period_type = _required_text(self.period_type, "period_type")
        metrics = _json_mapping(self.metrics, field="metrics")
        if not metrics:
            raise RepositoryDataError("Fundamental metrics must contain at least one known value.")
        object.__setattr__(self, "fiscal_period", fiscal_period)
        object.__setattr__(self, "period_type", period_type)
        object.__setattr__(self, "as_of_date", _optional_text(self.as_of_date))
        object.__setattr__(self, "metrics", metrics)


@dataclass(frozen=True, slots=True)
class CompanyProfileRecord:
    """A company profile keyed by a market-qualified security identity."""

    identity: ResearchIdentity
    company_name: str
    business_summary: str
    technology_summary: str
    industry: str
    as_of_date: str | None
    provenance: ResearchProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "company_name", _required_text(self.company_name, "company_name"))
        object.__setattr__(self, "business_summary", _optional_text(self.business_summary) or "")
        object.__setattr__(
            self, "technology_summary", _optional_text(self.technology_summary) or ""
        )
        object.__setattr__(self, "industry", _optional_text(self.industry) or "")
        object.__setattr__(self, "as_of_date", _optional_text(self.as_of_date))


@dataclass(frozen=True, slots=True)
class ConceptKnowledgeRecord:
    """One concept node with evidence provenance, independent of a security."""

    concept_key: str
    display_name: str
    description: str
    as_of_date: str | None
    provenance: ResearchProvenance
    aliases: tuple[str, ...] = ()
    dataset_version: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "concept_key", _required_text(self.concept_key, "concept_key").lower()
        )
        object.__setattr__(self, "display_name", _required_text(self.display_name, "display_name"))
        object.__setattr__(self, "description", _optional_text(self.description) or "")
        object.__setattr__(self, "as_of_date", _optional_text(self.as_of_date))
        object.__setattr__(
            self, "aliases", tuple(_required_text(item, "alias") for item in self.aliases)
        )
        object.__setattr__(
            self, "dataset_version", _required_text(self.dataset_version, "dataset_version")
        )


@dataclass(frozen=True, slots=True)
class ConceptRelationRecord:
    """One market-qualified security-to-concept relation with a stated evidence boundary."""

    concept_key: str
    identity: ResearchIdentity
    relation_type: str
    evidence: str
    as_of_date: str | None
    provenance: ResearchProvenance
    confidence: float = 0.0
    verified_at: str | None = None
    dataset_version: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "concept_key", _required_text(self.concept_key, "concept_key").lower()
        )
        object.__setattr__(
            self, "relation_type", _required_text(self.relation_type, "relation_type")
        )
        object.__setattr__(self, "evidence", _optional_text(self.evidence) or "")
        object.__setattr__(self, "as_of_date", _optional_text(self.as_of_date))
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError) as exc:
            raise RepositoryDataError("Concept relation confidence must be numeric.") from exc
        if not 0.0 <= confidence <= 1.0:
            raise RepositoryDataError("Concept relation confidence must be between 0 and 1.")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "verified_at", _optional_text(self.verified_at))
        object.__setattr__(
            self, "dataset_version", _required_text(self.dataset_version, "dataset_version")
        )

    @property
    def source_url(self) -> str | None:
        """Expose the provenance URL as the relation's evidence source."""

        return self.provenance.source_url

    @property
    def source_name(self) -> str:
        """Expose the provenance provider as the human-readable evidence source."""

        return self.provenance.provider

    @property
    def is_manual_seed(self) -> bool:
        """Return whether this relation is explicitly seeded rather than externally verified."""

        return self.provenance.source_type == "manual_seed"

    @property
    def is_stale(self) -> bool:
        """Treat evidence verified more than one year ago as stale for presentation."""

        if not self.verified_at:
            return False
        try:
            return (date.today() - date.fromisoformat(self.verified_at)).days > 365
        except ValueError:
            return True


@dataclass(frozen=True, slots=True)
class ResearchDocumentRecord:
    """Research-document metadata boundary without a dedicated raw-content field."""

    document_id: str
    identity: ResearchIdentity
    title: str
    source_name: str
    document_type: str
    content_hash: str
    metadata: Mapping[str, Any]
    as_of_date: str | None
    provenance: ResearchProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", _required_text(self.document_id, "document_id"))
        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(self, "source_name", _required_text(self.source_name, "source_name"))
        object.__setattr__(
            self, "document_type", _required_text(self.document_type, "document_type")
        )
        object.__setattr__(self, "content_hash", _required_text(self.content_hash, "content_hash"))
        object.__setattr__(self, "metadata", _json_mapping(self.metadata, field="metadata"))
        object.__setattr__(self, "as_of_date", _optional_text(self.as_of_date))


@dataclass(frozen=True, slots=True)
class RepositoryLookup:
    """Read result that distinguishes missing records from partial or stale records."""

    status: str
    record: FundamentalRecord | None


class ResearchRepository:
    """Repository API for Sprint 7 research entities; callers never build SQL."""

    def __init__(self, database_path: str | Path | SQLitePriceStorage) -> None:
        self.storage = (
            database_path
            if isinstance(database_path, SQLitePriceStorage)
            else SQLitePriceStorage(database_path)
        )

    def initialize(self) -> None:
        """Create or safely migrate the repository database schema."""

        self.storage.initialize()

    def upsert_fundamental(self, record: FundamentalRecord) -> None:
        """Create or replace exactly one market-qualified fundamental record."""

        with self.storage.repository_connection() as connection:
            connection.execute(
                """
                INSERT INTO research_fundamentals (
                    symbol, market, fiscal_period, period_type, as_of_date, metrics_json,
                    provider, source_type, provider_symbol, source_url, fetched_at, updated_at,
                    state, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, fiscal_period, period_type, as_of_date) DO UPDATE SET
                    metrics_json = excluded.metrics_json,
                    provider = excluded.provider,
                    source_type = excluded.source_type,
                    provider_symbol = excluded.provider_symbol,
                    source_url = excluded.source_url,
                    fetched_at = excluded.fetched_at,
                    updated_at = excluded.updated_at,
                    state = excluded.state,
                    warnings_json = excluded.warnings_json
                """,
                (
                    *_identity_values(record.identity),
                    record.fiscal_period,
                    record.period_type,
                    record.as_of_date or "",
                    _json_text(record.metrics),
                    *_provenance_values(record.provenance),
                ),
            )

    def get_fundamental(
        self,
        identity: ResearchIdentity,
        *,
        fiscal_period: str,
    ) -> RepositoryLookup:
        """Load the latest saved fiscal-period record or an explicit missing result."""

        fiscal_period = _required_text(fiscal_period, "fiscal_period")
        with self.storage.repository_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_fundamentals
                WHERE symbol = ? AND market = ? AND fiscal_period = ?
                ORDER BY updated_at DESC, as_of_date DESC, period_type DESC
                LIMIT 1
                """,
                (*_identity_values(identity), fiscal_period),
            ).fetchone()
        if row is None:
            return RepositoryLookup(status="missing", record=None)
        record = _fundamental_from_row(row)
        return RepositoryLookup(status=record.provenance.state, record=record)

    def list_fundamentals(self, identity: ResearchIdentity) -> tuple[FundamentalRecord, ...]:
        """List records for one identity without colliding with another market."""

        with self.storage.repository_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_fundamentals
                WHERE symbol = ? AND market = ?
                ORDER BY fiscal_period DESC, updated_at DESC, period_type DESC
                """,
                _identity_values(identity),
            ).fetchall()
        return tuple(_fundamental_from_row(row) for row in rows)

    def delete_fundamental(
        self,
        identity: ResearchIdentity,
        *,
        fiscal_period: str,
    ) -> bool:
        """Delete all period variants for exactly one repository-owned identity."""

        fiscal_period = _required_text(fiscal_period, "fiscal_period")
        with self.storage.repository_connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM research_fundamentals
                WHERE symbol = ? AND market = ? AND fiscal_period = ?
                """,
                (*_identity_values(identity), fiscal_period),
            )
        return cursor.rowcount > 0

    def upsert_company_profile(self, record: CompanyProfileRecord) -> None:
        """Create or replace one market-qualified company profile."""

        with self.storage.repository_connection() as connection:
            connection.execute(
                """
                INSERT INTO research_company_profiles (
                    symbol, market, company_name, business_summary, technology_summary, industry,
                    as_of_date, provider, source_type, provider_symbol, source_url, fetched_at,
                    updated_at, state, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market) DO UPDATE SET
                    company_name = excluded.company_name,
                    business_summary = excluded.business_summary,
                    technology_summary = excluded.technology_summary,
                    industry = excluded.industry,
                    as_of_date = excluded.as_of_date,
                    provider = excluded.provider,
                    source_type = excluded.source_type,
                    provider_symbol = excluded.provider_symbol,
                    source_url = excluded.source_url,
                    fetched_at = excluded.fetched_at,
                    updated_at = excluded.updated_at,
                    state = excluded.state,
                    warnings_json = excluded.warnings_json
                """,
                (
                    *_identity_values(record.identity),
                    record.company_name,
                    record.business_summary,
                    record.technology_summary,
                    record.industry,
                    record.as_of_date or "",
                    *_provenance_values(record.provenance),
                ),
            )

    def get_company_profile(self, identity: ResearchIdentity) -> CompanyProfileRecord | None:
        """Return the profile for exactly one market-qualified identity."""

        with self.storage.repository_connection() as connection:
            row = connection.execute(
                "SELECT * FROM research_company_profiles WHERE symbol = ? AND market = ?",
                _identity_values(identity),
            ).fetchone()
        if row is None:
            return None
        return CompanyProfileRecord(
            identity=ResearchIdentity(row["symbol"], row["market"]),
            company_name=row["company_name"],
            business_summary=row["business_summary"],
            technology_summary=row["technology_summary"],
            industry=row["industry"],
            as_of_date=_none_if_empty(row["as_of_date"]),
            provenance=_provenance_from_row(row),
        )

    def upsert_concept(self, record: ConceptKnowledgeRecord) -> None:
        """Create or replace a concept-knowledge node."""

        with self.storage.repository_connection() as connection:
            _upsert_concept(connection, record)

    def get_concept(self, concept_key: str) -> ConceptKnowledgeRecord | None:
        """Return a concept node by its normalized key."""

        concept_key = _required_text(concept_key, "concept_key").lower()
        with self.storage.repository_connection() as connection:
            row = connection.execute(
                "SELECT * FROM research_concepts WHERE concept_key = ?", (concept_key,)
            ).fetchone()
        if row is None:
            return None
        return ConceptKnowledgeRecord(
            concept_key=row["concept_key"],
            display_name=row["display_name"],
            description=row["description"],
            as_of_date=_none_if_empty(row["as_of_date"]),
            provenance=_provenance_from_row(row),
            aliases=tuple(_read_json_sequence(row["aliases_json"], field="aliases_json")),
            dataset_version=row["dataset_version"],
        )

    def list_concepts(self) -> tuple[ConceptKnowledgeRecord, ...]:
        """List canonical concept metadata for exact alias lookup and discovery."""

        with self.storage.repository_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM research_concepts ORDER BY concept_key"
            ).fetchall()
        return tuple(
            ConceptKnowledgeRecord(
                concept_key=row["concept_key"],
                display_name=row["display_name"],
                description=row["description"],
                as_of_date=_none_if_empty(row["as_of_date"]),
                provenance=_provenance_from_row(row),
                aliases=tuple(_read_json_sequence(row["aliases_json"], field="aliases_json")),
                dataset_version=row["dataset_version"],
            )
            for row in rows
        )

    def upsert_concept_relation(self, record: ConceptRelationRecord) -> None:
        """Create or replace one concept relation for a specific symbol and market."""

        with self.storage.repository_connection() as connection:
            _upsert_concept_relation(connection, record)

    def upsert_concept_dataset(
        self,
        concepts: Sequence[ConceptKnowledgeRecord],
        relations: Sequence[ConceptRelationRecord],
    ) -> None:
        """Persist one prevalidated concept dataset in a single SQLite transaction."""

        with self.storage.repository_connection() as connection:
            for concept in concepts:
                _upsert_concept(connection, concept)
            for relation in relations:
                _upsert_concept_relation(connection, relation)

    def list_concept_relations(
        self,
        concept_key: str,
        *,
        identity: ResearchIdentity | None = None,
    ) -> tuple[ConceptRelationRecord, ...]:
        """List concept relations, optionally scoped to one precise identity."""

        concept_key = _required_text(concept_key, "concept_key").lower()
        query = "SELECT * FROM research_concept_relations WHERE concept_key = ?"
        parameters: list[str] = [concept_key]
        if identity is not None:
            query += " AND symbol = ? AND market = ?"
            parameters.extend(_identity_values(identity))
        query += " ORDER BY market, symbol, relation_type"
        with self.storage.repository_connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            ConceptRelationRecord(
                concept_key=row["concept_key"],
                identity=ResearchIdentity(row["symbol"], row["market"]),
                relation_type=row["relation_type"],
                evidence=row["evidence"],
                as_of_date=_none_if_empty(row["as_of_date"]),
                provenance=_provenance_from_row(row),
                confidence=row["confidence"],
                verified_at=_none_if_empty(row["verified_at"]),
                dataset_version=row["dataset_version"],
            )
            for row in rows
        )

    def upsert_research_document(self, record: ResearchDocumentRecord) -> None:
        """Persist document metadata; callers must not place raw private content in metadata."""

        with self.storage.repository_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO research_documents (
                    document_id, symbol, market, title, source_name, document_type, content_hash,
                    metadata_json, as_of_date, provider, source_type, provider_symbol, source_url,
                    fetched_at, updated_at, state, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    title = excluded.title,
                    source_name = excluded.source_name,
                    document_type = excluded.document_type,
                    content_hash = excluded.content_hash,
                    metadata_json = excluded.metadata_json,
                    as_of_date = excluded.as_of_date,
                    provider = excluded.provider,
                    source_type = excluded.source_type,
                    provider_symbol = excluded.provider_symbol,
                    source_url = excluded.source_url,
                    fetched_at = excluded.fetched_at,
                    updated_at = excluded.updated_at,
                    state = excluded.state,
                    warnings_json = excluded.warnings_json
                WHERE research_documents.symbol = excluded.symbol
                  AND research_documents.market = excluded.market
                """,
                (
                    record.document_id,
                    *_identity_values(record.identity),
                    record.title,
                    record.source_name,
                    record.document_type,
                    record.content_hash,
                    _json_text(record.metadata),
                    record.as_of_date or "",
                    *_provenance_values(record.provenance),
                ),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    "SELECT symbol, market FROM research_documents WHERE document_id = ?",
                    (record.document_id,),
                ).fetchone()
                if existing is None:
                    raise RepositoryDataError(
                        "Research document upsert did not persist the requested document_id."
                    )
                raise RepositoryDataError(
                    "Research document_id is globally unique and already belongs to a different "
                    "market-qualified identity."
                )

    def get_research_document(self, document_id: str) -> ResearchDocumentRecord | None:
        """Return one document metadata record without exposing absent records as data."""

        document_id = _required_text(document_id, "document_id")
        with self.storage.repository_connection() as connection:
            row = connection.execute(
                "SELECT * FROM research_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        if row is None:
            return None
        return ResearchDocumentRecord(
            document_id=row["document_id"],
            identity=ResearchIdentity(row["symbol"], row["market"]),
            title=row["title"],
            source_name=row["source_name"],
            document_type=row["document_type"],
            content_hash=row["content_hash"],
            metadata=_read_json_mapping(row["metadata_json"], field="metadata_json"),
            as_of_date=_none_if_empty(row["as_of_date"]),
            provenance=_provenance_from_row(row),
        )

    def delete_research_document(self, document_id: str) -> bool:
        """Delete exactly one repository-owned document metadata row."""

        document_id = _required_text(document_id, "document_id")
        with self.storage.repository_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM research_documents WHERE document_id = ?", (document_id,)
            )
        return cursor.rowcount == 1


def _upsert_concept(connection: sqlite3.Connection, record: ConceptKnowledgeRecord) -> None:
    """Execute the concept upsert using the caller's repository transaction."""

    connection.execute(
        """
        INSERT INTO research_concepts (
            concept_key, display_name, description, as_of_date, provider, source_type,
            provider_symbol, source_url, fetched_at, updated_at, state, warnings_json,
            aliases_json, dataset_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(concept_key) DO UPDATE SET
            display_name = excluded.display_name,
            description = excluded.description,
            as_of_date = excluded.as_of_date,
            provider = excluded.provider,
            source_type = excluded.source_type,
            provider_symbol = excluded.provider_symbol,
            source_url = excluded.source_url,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at,
            state = excluded.state,
            warnings_json = excluded.warnings_json,
            aliases_json = excluded.aliases_json,
            dataset_version = excluded.dataset_version
        """,
        (
            record.concept_key,
            record.display_name,
            record.description,
            record.as_of_date or "",
            *_provenance_values(record.provenance),
            _json_text(list(record.aliases)),
            record.dataset_version,
        ),
    )


def _upsert_concept_relation(connection: sqlite3.Connection, record: ConceptRelationRecord) -> None:
    """Execute the relation upsert using the caller's repository transaction."""

    connection.execute(
        """
        INSERT INTO research_concept_relations (
            concept_key, symbol, market, relation_type, evidence, as_of_date, provider,
            source_type, provider_symbol, source_url, fetched_at, updated_at, state,
            warnings_json, confidence, verified_at, dataset_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(concept_key, symbol, market, relation_type) DO UPDATE SET
            evidence = excluded.evidence,
            as_of_date = excluded.as_of_date,
            provider = excluded.provider,
            source_type = excluded.source_type,
            provider_symbol = excluded.provider_symbol,
            source_url = excluded.source_url,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at,
            state = excluded.state,
            warnings_json = excluded.warnings_json,
            confidence = excluded.confidence,
            verified_at = excluded.verified_at,
            dataset_version = excluded.dataset_version
        """,
        (
            record.concept_key,
            *_identity_values(record.identity),
            record.relation_type,
            record.evidence,
            record.as_of_date or "",
            *_provenance_values(record.provenance),
            record.confidence,
            record.verified_at or "",
            record.dataset_version,
        ),
    )


def _identity_values(identity: ResearchIdentity) -> tuple[str, str]:
    return identity.symbol, identity.market


def _provenance_values(provenance: ResearchProvenance) -> tuple[Any, ...]:
    return (
        provenance.provider,
        provenance.source_type,
        provenance.provider_symbol,
        provenance.source_url,
        provenance.fetched_at,
        provenance.updated_at,
        provenance.state,
        _json_text(list(provenance.warnings)),
    )


def _provenance_from_row(row: sqlite3.Row) -> ResearchProvenance:
    return ResearchProvenance(
        provider=row["provider"],
        source_type=row["source_type"],
        provider_symbol=row["provider_symbol"],
        source_url=row["source_url"],
        fetched_at=row["fetched_at"],
        updated_at=row["updated_at"],
        state=row["state"],
        warnings=tuple(_read_json_sequence(row["warnings_json"], field="warnings_json")),
    )


def _fundamental_from_row(row: sqlite3.Row) -> FundamentalRecord:
    return FundamentalRecord(
        identity=ResearchIdentity(row["symbol"], row["market"]),
        fiscal_period=row["fiscal_period"],
        period_type=row["period_type"],
        as_of_date=_none_if_empty(row["as_of_date"]),
        metrics=_read_json_mapping(row["metrics_json"], field="metrics_json"),
        provenance=_provenance_from_row(row),
    )


def _normalize_state(value: str) -> str:
    state = _required_text(value, "state").lower()
    if state not in _RECORD_STATES:
        raise RepositoryDataError(f"Unsupported repository state: {value!r}")
    return state


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RepositoryDataError(f"Research record requires {field}.")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_sanitized_text(value: object) -> str | None:
    text = _optional_text(value)
    return sanitize_provider_text(text) if text else None


def _json_mapping(value: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RepositoryDataError(f"Research record {field} must be a mapping.")
    return {str(key): _json_safe(item) for key, item in value.items()}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]
    raise RepositoryDataError(
        f"Research metadata contains unsupported value type: {type(value).__name__}"
    )


def _json_text(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json_mapping(value: str, *, field: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RepositoryDataError(f"Stored {field} is corrupted.") from exc
    if not isinstance(payload, dict):
        raise RepositoryDataError(f"Stored {field} is not a mapping.")
    return _json_mapping(payload, field=field)


def _read_json_sequence(value: str, *, field: str) -> list[Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RepositoryDataError(f"Stored {field} is corrupted.") from exc
    if not isinstance(payload, list):
        raise RepositoryDataError(f"Stored {field} is not a list.")
    return [_json_safe(item) for item in payload]


def _none_if_empty(value: object) -> str | None:
    return _optional_text(value)
