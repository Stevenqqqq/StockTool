from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
import threading
from typing import Iterator

import pytest

from stock_tool.data.repositories import (
    CompanyProfileRecord,
    ConceptKnowledgeRecord,
    ConceptRelationRecord,
    FundamentalRecord,
    ResearchDocumentRecord,
    ResearchIdentity,
    ResearchProvenance,
    ResearchRepository,
    RepositoryDataError,
)
from stock_tool.runtime_paths import RuntimePaths


def _provenance(
    *, provider: str = "fixture-provider", state: str = "complete"
) -> ResearchProvenance:
    return ResearchProvenance(
        provider=provider,
        source_type="fixture",
        provider_symbol="MU",
        source_url="https://example.test/source?token=not-stored",
        fetched_at="2026-07-14T00:00:00+00:00",
        updated_at="2026-07-14T00:00:01+00:00",
        state=state,
        warnings=("fixture warning",),
    )


def _fundamental(
    identity: ResearchIdentity, *, revenue: float, state: str = "complete"
) -> FundamentalRecord:
    return FundamentalRecord(
        identity=identity,
        fiscal_period="2025FY",
        period_type="annual",
        as_of_date="2025-12-31",
        metrics={"revenue": revenue, "eps": 4.2},
        provenance=_provenance(state=state),
    )


def _document(
    identity: ResearchIdentity,
    *,
    document_id: str,
    title: str,
    content_hash: str,
) -> ResearchDocumentRecord:
    """Build deterministic document metadata for repository concurrency tests."""

    return ResearchDocumentRecord(
        document_id=document_id,
        identity=identity,
        title=title,
        source_name=f"{identity.symbol}-{identity.market}.pdf",
        document_type="pdf_summary",
        content_hash=content_hash,
        metadata={"summary": title},
        as_of_date="2026-07-14",
        provenance=_provenance(),
    )


class _WriteBarrierConnection:
    """Synchronize the first document write without changing production SQL."""

    def __init__(self, connection: sqlite3.Connection, barrier: threading.Barrier) -> None:
        self._connection = connection
        self._barrier = barrier
        self._waited_for_document_write = False

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
        if not self._waited_for_document_write and "INSERT INTO research_documents" in sql:
            self._waited_for_document_write = True
            self._barrier.wait(timeout=5)
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


def _synchronize_document_writes(
    repository: ResearchRepository,
    barrier: threading.Barrier,
) -> None:
    """Install a test-only write barrier while preserving connection cleanup."""

    original_connection = repository.storage.repository_connection

    @contextmanager
    def coordinated_connection() -> Iterator[_WriteBarrierConnection]:
        with original_connection() as connection:
            yield _WriteBarrierConnection(connection, barrier)

    setattr(repository.storage, "repository_connection", coordinated_connection)


def test_fundamentals_are_market_qualified_and_duplicate_upserts_are_deterministic(
    tmp_path: Path,
) -> None:
    repository = ResearchRepository(tmp_path / "research.sqlite")
    mu_us = ResearchIdentity("MU", "US")
    mu_twse = ResearchIdentity("MU", "TWSE")

    repository.upsert_fundamental(_fundamental(mu_us, revenue=100.0))
    repository.upsert_fundamental(_fundamental(mu_twse, revenue=200.0, state="partial"))
    repository.upsert_fundamental(_fundamental(mu_us, revenue=300.0, state="stale"))
    repository.upsert_fundamental(
        _fundamental(ResearchIdentity("MU", "UNKNOWN"), revenue=50.0, state="partial")
    )

    us_lookup = repository.get_fundamental(mu_us, fiscal_period="2025FY")
    twse_lookup = repository.get_fundamental(mu_twse, fiscal_period="2025FY")

    assert us_lookup.status == "stale"
    assert us_lookup.record is not None
    assert us_lookup.record.metrics["revenue"] == 300.0
    assert twse_lookup.status == "partial"
    assert twse_lookup.record is not None
    assert twse_lookup.record.metrics["revenue"] == 200.0
    assert len(repository.list_fundamentals(mu_us)) == 1
    assert (
        repository.get_fundamental(ResearchIdentity("MU", "UNKNOWN"), fiscal_period="2025FY").record
        is not None
    )
    assert (
        repository.get_fundamental(ResearchIdentity("MU", "TPEX"), fiscal_period="2025FY").status
        == "missing"
    )
    assert repository.delete_fundamental(mu_us, fiscal_period="2025FY") is True
    assert repository.get_fundamental(mu_us, fiscal_period="2025FY").status == "missing"
    assert repository.get_fundamental(mu_twse, fiscal_period="2025FY").record is not None


def test_repository_persists_profiles_concepts_relations_documents_and_provenance(
    tmp_path: Path,
) -> None:
    repository = ResearchRepository(tmp_path / "research.sqlite")
    identity = ResearchIdentity("2330", "TWSE")
    provenance = _provenance(provider="profile-provider")

    repository.upsert_company_profile(
        CompanyProfileRecord(
            identity=identity,
            company_name="Fixture Semiconductor",
            business_summary="Foundry services",
            technology_summary="Advanced packaging",
            industry="Semiconductors",
            as_of_date="2026-07-01",
            provenance=provenance,
        )
    )
    repository.upsert_concept(
        ConceptKnowledgeRecord(
            concept_key="advanced-packaging",
            display_name="Advanced packaging",
            description="Fixture concept",
            as_of_date="2026-07-01",
            provenance=provenance,
        )
    )
    repository.upsert_concept_relation(
        ConceptRelationRecord(
            concept_key="advanced-packaging",
            identity=identity,
            relation_type="supply_chain",
            evidence="Fixture evidence",
            as_of_date="2026-07-01",
            provenance=provenance,
        )
    )
    document = ResearchDocumentRecord(
        document_id="fixture-doc-001",
        identity=identity,
        title="Fixture report",
        source_name="fixture.pdf",
        document_type="pdf_summary",
        content_hash="abc123",
        metadata={"summary": "metadata only"},
        as_of_date="2026-07-01",
        provenance=provenance,
    )
    repository.upsert_research_document(document)

    profile = repository.get_company_profile(identity)
    concept = repository.get_concept("advanced-packaging")
    relations = repository.list_concept_relations("advanced-packaging", identity=identity)
    loaded_document = repository.get_research_document("fixture-doc-001")

    assert profile is not None and profile.identity == identity
    assert concept is not None and concept.display_name == "Advanced packaging"
    assert len(relations) == 1 and relations[0].identity == identity
    assert loaded_document is not None and loaded_document.metadata == {"summary": "metadata only"}
    assert "not-stored" not in str(loaded_document.provenance)
    assert repository.delete_research_document("fixture-doc-001") is True
    assert repository.get_research_document("fixture-doc-001") is None


def test_invalid_record_does_not_modify_existing_research_data(tmp_path: Path) -> None:
    database_path = tmp_path / "research.sqlite"
    repository = ResearchRepository(database_path)
    identity = ResearchIdentity("AAPL", "US")
    repository.upsert_fundamental(_fundamental(identity, revenue=100.0))
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()

    with pytest.raises(RepositoryDataError, match="fiscal_period"):
        repository.upsert_fundamental(
            FundamentalRecord(
                identity=identity,
                fiscal_period="",
                period_type="annual",
                as_of_date="2025-12-31",
                metrics={"revenue": 999.0},
                provenance=_provenance(),
            )
        )

    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before
    lookup = repository.get_fundamental(identity, fiscal_period="2025FY")
    assert lookup.record is not None and lookup.record.metrics["revenue"] == 100.0


def test_runtime_database_path_is_separate_from_sample_and_release_paths(tmp_path: Path) -> None:
    paths = RuntimePaths(root=tmp_path / "runtime").ensure_directories()
    database_path = paths.processed_dir / "research.sqlite"
    repository = ResearchRepository(database_path)

    repository.initialize()

    assert database_path.is_file()
    assert database_path.is_relative_to(paths.root)
    assert not database_path.is_relative_to(Path("data/sample").resolve())
    assert not database_path.is_relative_to(Path("release").resolve())


def test_repository_never_selects_the_real_user_data_root(tmp_path: Path) -> None:
    paths = RuntimePaths(root=tmp_path / "isolated-runtime").ensure_directories()
    repository = ResearchRepository(paths.processed_dir / "research.sqlite")

    repository.initialize()

    assert repository.storage.database_path == paths.processed_dir / "research.sqlite"
    assert repository.storage.database_path.is_relative_to(tmp_path)


def test_research_identity_delegates_known_markets_to_the_domain_symbol_parser() -> None:
    assert ResearchIdentity("2330", "TWSE") == ResearchIdentity("2330.TW", "TWSE")
    assert ResearchIdentity("6488.TWO", "TPEX") == ResearchIdentity("6488", "TPEX")
    assert ResearchIdentity("AAPL", "US") == ResearchIdentity("AAPL", "US")

    with pytest.raises(RepositoryDataError, match="market"):
        ResearchIdentity("2330.TWO", "TWSE")

    unresolved = ResearchIdentity("MU", "UNKNOWN")
    assert unresolved.symbol == "MU"
    assert unresolved.market == "UNKNOWN"
    with pytest.raises(RepositoryDataError, match="unresolved"):
        ResearchIdentity("2330.TW", "UNKNOWN")


def test_document_id_is_global_and_cannot_silently_overwrite_another_market(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research.sqlite")
    us_document = ResearchDocumentRecord(
        document_id="shared-document",
        identity=ResearchIdentity("MU", "US"),
        title="US document",
        source_name="us.pdf",
        document_type="pdf_summary",
        content_hash="us-hash",
        metadata={"summary": "US metadata"},
        as_of_date="2026-07-14",
        provenance=_provenance(),
    )
    repository.upsert_research_document(us_document)
    repository.upsert_research_document(
        ResearchDocumentRecord(
            document_id="shared-document",
            identity=ResearchIdentity("MU", "US"),
            title="Updated US document",
            source_name="us.pdf",
            document_type="pdf_summary",
            content_hash="us-hash-2",
            metadata={"summary": "updated"},
            as_of_date="2026-07-15",
            provenance=_provenance(),
        )
    )

    with pytest.raises(RepositoryDataError, match="globally unique"):
        repository.upsert_research_document(
            ResearchDocumentRecord(
                document_id="shared-document",
                identity=ResearchIdentity("MU", "TWSE"),
                title="Different market document",
                source_name="tw.pdf",
                document_type="pdf_summary",
                content_hash="tw-hash",
                metadata={"summary": "TW metadata"},
                as_of_date="2026-07-15",
                provenance=_provenance(),
            )
        )

    loaded = repository.get_research_document("shared-document")
    assert loaded is not None
    assert loaded.identity == ResearchIdentity("MU", "US")
    assert loaded.title == "Updated US document"
    assert repository.delete_research_document("shared-document") is True
    assert repository.get_research_document("shared-document") is None


def test_concurrent_cross_market_document_claims_allow_exactly_one_owner(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent-documents.sqlite"
    us_repository = ResearchRepository(database_path)
    twse_repository = ResearchRepository(database_path)
    us_repository.initialize()

    start_barrier = threading.Barrier(2)
    write_barrier = threading.Barrier(2)
    _synchronize_document_writes(us_repository, write_barrier)
    _synchronize_document_writes(twse_repository, write_barrier)
    results: list[str] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def write_document(repository: ResearchRepository, record: ResearchDocumentRecord) -> None:
        try:
            start_barrier.wait(timeout=5)
            repository.upsert_research_document(record)
        except BaseException as error:
            with results_lock:
                errors.append(error)
        else:
            with results_lock:
                results.append(record.identity.market)

    us_document = _document(
        ResearchIdentity("MU", "US"),
        document_id="concurrent-document",
        title="US owner",
        content_hash="us-owner-hash",
    )
    twse_document = _document(
        ResearchIdentity("MU", "TWSE"),
        document_id="concurrent-document",
        title="TWSE contender",
        content_hash="twse-contender-hash",
    )
    threads = (
        threading.Thread(target=write_document, args=(us_repository, us_document)),
        threading.Thread(target=write_document, args=(twse_repository, twse_document)),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RepositoryDataError)

    stored = ResearchRepository(database_path).get_research_document("concurrent-document")
    assert stored is not None
    expected = us_document if results[0] == "US" else twse_document
    assert stored.identity == expected.identity
    assert stored.title == expected.title
    assert stored.content_hash == expected.content_hash
    assert stored.metadata == expected.metadata
    renamed_database = tmp_path / "concurrent-documents-closed.sqlite"
    database_path.replace(renamed_database)
    renamed_database.replace(database_path)


def test_concurrent_same_identity_updates_and_distinct_document_ids_succeed(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent-document-updates.sqlite"
    first_repository = ResearchRepository(database_path)
    second_repository = ResearchRepository(database_path)
    first_repository.initialize()

    start_barrier = threading.Barrier(2)
    write_barrier = threading.Barrier(2)
    _synchronize_document_writes(first_repository, write_barrier)
    _synchronize_document_writes(second_repository, write_barrier)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def write_document(repository: ResearchRepository, record: ResearchDocumentRecord) -> None:
        try:
            start_barrier.wait(timeout=5)
            repository.upsert_research_document(record)
        except BaseException as error:
            with errors_lock:
                errors.append(error)

    same_identity_threads = (
        threading.Thread(
            target=write_document,
            args=(
                first_repository,
                _document(
                    ResearchIdentity("MU", "US"),
                    document_id="same-identity-document",
                    title="first update",
                    content_hash="first-hash",
                ),
            ),
        ),
        threading.Thread(
            target=write_document,
            args=(
                second_repository,
                _document(
                    ResearchIdentity("MU", "US"),
                    document_id="same-identity-document",
                    title="second update",
                    content_hash="second-hash",
                ),
            ),
        ),
    )
    for thread in same_identity_threads:
        thread.start()
    for thread in same_identity_threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in same_identity_threads)
    assert errors == []
    same_identity = ResearchRepository(database_path).get_research_document(
        "same-identity-document"
    )
    assert same_identity is not None
    assert same_identity.identity == ResearchIdentity("MU", "US")
    assert same_identity.title in {"first update", "second update"}

    first_distinct_repository = ResearchRepository(database_path)
    second_distinct_repository = ResearchRepository(database_path)
    distinct_start_barrier = threading.Barrier(2)
    distinct_write_barrier = threading.Barrier(2)
    _synchronize_document_writes(first_distinct_repository, distinct_write_barrier)
    _synchronize_document_writes(second_distinct_repository, distinct_write_barrier)
    first_distinct = _document(
        ResearchIdentity("MU", "US"),
        document_id="distinct-us-document",
        title="US document",
        content_hash="distinct-us-hash",
    )
    second_distinct = _document(
        ResearchIdentity("MU", "TWSE"),
        document_id="distinct-twse-document",
        title="TWSE document",
        content_hash="distinct-twse-hash",
    )
    distinct_errors: list[BaseException] = []

    def write_distinct_document(
        repository: ResearchRepository, record: ResearchDocumentRecord
    ) -> None:
        try:
            distinct_start_barrier.wait(timeout=5)
            repository.upsert_research_document(record)
        except BaseException as error:
            with errors_lock:
                distinct_errors.append(error)

    distinct_threads = (
        threading.Thread(
            target=write_distinct_document,
            args=(first_distinct_repository, first_distinct),
        ),
        threading.Thread(
            target=write_distinct_document,
            args=(second_distinct_repository, second_distinct),
        ),
    )
    for thread in distinct_threads:
        thread.start()
    for thread in distinct_threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in distinct_threads)
    assert distinct_errors == []
    repository = ResearchRepository(database_path)
    assert repository.get_research_document(first_distinct.document_id) == first_distinct
    assert repository.get_research_document(second_distinct.document_id) == second_distinct


def test_corrupted_stored_json_raises_without_modifying_the_repository_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrupt-json.sqlite"
    repository = ResearchRepository(database_path)
    identity = ResearchIdentity("MU", "US")
    repository.upsert_fundamental(_fundamental(identity, revenue=100.0))
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE research_fundamentals SET metrics_json = '{invalid-json'")
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()

    with pytest.raises(RepositoryDataError, match="metrics_json is corrupted"):
        repository.get_fundamental(identity, fiscal_period="2025FY")

    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before
