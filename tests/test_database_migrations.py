from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import threading

import pytest

from stock_tool.data.storage import MigrationError, SQLitePriceStorage


def _create_v11_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE prices (
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                adjusted_close REAL,
                PRIMARY KEY (date, symbol)
            )
            """)
        connection.execute("""
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
        connection.execute("INSERT INTO schema_migrations (version) VALUES ('001_ingestion_runs')")
        connection.execute("""
            INSERT INTO prices (date, symbol, open, high, low, close, volume, adjusted_close)
            VALUES ('2024-01-02', '2330', 590, 600, 585, 595, 1000, 595)
            """)
        connection.execute("CREATE TABLE legacy_notes (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_notes (note) VALUES ('preserve me')")


def _table_hash(path: Path, table: str) -> str:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _database_snapshot(path: Path) -> tuple[tuple[str, str], ...]:
    """Return the complete table schema and row state for migration rollback checks."""

    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        snapshot: list[tuple[str, str]] = []
        for table, schema in tables:
            rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            snapshot.append((str(table), f"{schema!s}|{rows!r}"))
    return tuple(snapshot)


def _failing_storage(path: Path, migration_path: Path) -> SQLitePriceStorage:
    class FailingMigrationStorage(SQLitePriceStorage):
        def _migration_paths(self) -> tuple[Path, ...]:
            return (*super()._migration_paths(), migration_path)

    return FailingMigrationStorage(path)


def test_empty_database_creates_latest_research_schema(tmp_path: Path) -> None:
    storage = SQLitePriceStorage(tmp_path / "empty.sqlite")

    storage.initialize()

    assert storage.schema_version() == "003_concept_evidence"
    assert storage.applied_migrations() == (
        "001_ingestion_runs",
        "002_research_entities",
        "003_concept_evidence",
    )
    with sqlite3.connect(storage.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "research_fundamentals",
        "research_company_profiles",
        "research_concepts",
        "research_concept_relations",
        "research_documents",
    } <= tables


def test_v11_database_upgrade_is_additive_backed_up_and_repeat_safe(tmp_path: Path) -> None:
    database_path = tmp_path / "v11.sqlite"
    _create_v11_database(database_path)
    prices_before = _table_hash(database_path, "prices")
    notes_before = _table_hash(database_path, "legacy_notes")
    storage = SQLitePriceStorage(database_path)

    storage.initialize()
    first_backup = storage.last_migration_backup
    storage.initialize()

    assert first_backup is not None and first_backup.is_file()
    assert storage.last_migration_backup is None
    assert _table_hash(database_path, "prices") == prices_before
    assert _table_hash(database_path, "legacy_notes") == notes_before
    assert len(tuple(tmp_path.glob("v11.pre-migration-*.sqlite"))) == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT note FROM legacy_notes").fetchone()[0] == "preserve me"


def test_failed_migration_rolls_back_schema_and_restores_backup(tmp_path: Path) -> None:
    database_path = tmp_path / "failure.sqlite"
    storage = SQLitePriceStorage(database_path)
    storage.initialize()
    storage.save_price_data(
        [
            {
                "date": "2024-01-02",
                "symbol": "2330",
                "open": 590.0,
                "high": 600.0,
                "low": 585.0,
                "close": 595.0,
                "volume": 1000.0,
                "adjusted_close": 595.0,
            }
        ]
    )
    prices_before = _table_hash(database_path, "prices")
    bad_migration = tmp_path / "999_failure.sql"
    bad_migration.write_text(
        "CREATE TABLE migration_should_rollback (id INTEGER PRIMARY KEY);\nINVALID SQL;\n",
        encoding="utf-8",
    )

    failing = _failing_storage(database_path, bad_migration)
    with pytest.raises(MigrationError, match="999_failure"):
        failing.initialize()

    assert failing.last_migration_backup is not None
    assert failing.last_migration_backup.is_file()
    assert _table_hash(database_path, "prices") == prices_before
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("migration_should_rollback",),
        ).fetchone()
    assert table is None


def test_prices_only_database_failure_restores_the_exact_pre_upgrade_snapshot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "prices-only.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("""
            CREATE TABLE prices (
                date TEXT NOT NULL, symbol TEXT NOT NULL, open REAL NOT NULL,
                high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
                volume REAL NOT NULL, adjusted_close REAL,
                PRIMARY KEY (date, symbol)
            )
            """)
        connection.execute("INSERT INTO prices VALUES ('2024-01-02', '2330', 1, 2, 1, 2, 3, 2)")
    snapshot_before = _database_snapshot(database_path)
    failing_migration = tmp_path / "999_failure.sql"
    failing_migration.write_text("CREATE TABLE temporary_table (id INTEGER);\nINVALID SQL;\n")

    failing = _failing_storage(database_path, failing_migration)

    with pytest.raises(MigrationError, match="999_failure"):
        failing.initialize()

    assert failing.last_migration_backup is not None
    assert _database_snapshot(database_path) == snapshot_before


def test_unknown_table_only_database_failure_restores_the_exact_pre_upgrade_snapshot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "unknown-only.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE legacy_unknown (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO legacy_unknown (value) VALUES ('preserve me')")
    snapshot_before = _database_snapshot(database_path)
    failing_migration = tmp_path / "999_failure.sql"
    failing_migration.write_text("CREATE TABLE temporary_table (id INTEGER);\nINVALID SQL;\n")

    failing = _failing_storage(database_path, failing_migration)

    with pytest.raises(MigrationError, match="999_failure"):
        failing.initialize()

    assert failing.last_migration_backup is not None
    assert _database_snapshot(database_path) == snapshot_before


def test_incompatible_existing_base_table_is_rejected_without_schema_writes(tmp_path: Path) -> None:
    database_path = tmp_path / "incompatible.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE prices (id INTEGER PRIMARY KEY, incompatible TEXT)")
        connection.execute("INSERT INTO prices (incompatible) VALUES ('preserve me')")
    snapshot_before = _database_snapshot(database_path)

    with pytest.raises(MigrationError, match="Incompatible existing table schema"):
        SQLitePriceStorage(database_path).initialize()

    assert _database_snapshot(database_path) == snapshot_before


def test_concurrent_initialize_applies_each_migration_once_without_reverting_another_instance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "concurrent.sqlite"
    _create_v11_database(database_path)
    first = SQLitePriceStorage(database_path)
    second = SQLitePriceStorage(database_path)
    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def initialize(storage: SQLitePriceStorage) -> None:
        try:
            start.wait(timeout=5)
            storage.initialize()
        except BaseException as exc:  # Assert both competing initializers succeed below.
            errors.append(exc)

    threads = [threading.Thread(target=initialize, args=(storage,)) for storage in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert first.applied_migrations() == (
        "001_ingestion_runs",
        "002_research_entities",
        "003_concept_evidence",
    )
    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                ("002_research_entities",),
            ).fetchone()[0]
            == 1
        )


def test_corrupt_database_is_rejected_without_overwriting_original_bytes(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupt.sqlite"
    original = b"not a sqlite database"
    database_path.write_bytes(original)
    storage = SQLitePriceStorage(database_path)

    with pytest.raises(sqlite3.DatabaseError):
        storage.initialize()

    assert database_path.read_bytes() == original
