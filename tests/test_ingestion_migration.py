from __future__ import annotations

import sqlite3
from pathlib import Path

from stock_tool.data.storage import SQLitePriceStorage


def _legacy_prices_database(path: Path) -> None:
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
            INSERT INTO prices (date, symbol, open, high, low, close, volume, adjusted_close)
            VALUES ('2024-01-02', '2330', 590, 600, 585, 595, 1000, 595)
            """)


def _ingestion_record(run_id: str = "run-001") -> dict[str, object]:
    return {
        "run_id": run_id,
        "started_at": "2025-01-02T03:04:05+00:00",
        "completed_at": "2025-01-02T03:04:06+00:00",
        "requested_symbol": {"code": "2330", "market": "TWSE"},
        "resolved_symbol": {"code": "2330", "market": "TWSE"},
        "provider_symbol": "2330.TW",
        "provider": "fixture-provider",
        "source_type": "online",
        "request_start": "2024-01-01",
        "request_end": "2024-12-31",
        "cache_hit": False,
        "status": "success",
        "input_rows": 100,
        "output_rows": 99,
        "quality_summary": {"status": "valid", "output_rows": 99},
        "warnings": ["download warning token=secret-value"],
        "errors": ["HTTP 429 while downloading"],
        "attempts": [{"provider": "fixture-provider", "success": True, "reason": "completed"}],
        "last_data_date": "2024-12-31",
    }


def test_migration_applies_repeats_and_upgrades_legacy_database_without_losing_prices(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy.sqlite"
    _legacy_prices_database(database_path)
    storage = SQLitePriceStorage(database_path)

    storage.initialize()
    storage.initialize()

    assert storage.count_price_rows() == 1
    assert storage.load_price_data(symbol="2330")[0]["close"] == 595.0
    assert storage.applied_migrations() == (
        "001_ingestion_runs",
        "002_research_entities",
        "003_concept_evidence",
    )


def test_ingestion_metadata_is_redacted_and_rollback_or_restore_is_available(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "lineage.sqlite"
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
    backup_path = tmp_path / "lineage-backup.sqlite"
    storage.backup_database(backup_path)

    storage.record_ingestion_run(_ingestion_record())
    stored = storage.list_ingestion_runs()

    assert len(stored) == 1
    assert stored[0]["warnings"] == ["download warning token=[REDACTED]"]
    assert "secret-value" not in str(stored)

    storage.rollback_ingestion_runs_migration()
    assert storage.applied_migrations() == (
        "002_research_entities",
        "003_concept_evidence",
    )
    assert storage.count_price_rows() == 1
    assert storage.list_ingestion_runs() == []
    with sqlite3.connect(database_path) as connection:
        lineage_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ingestion_runs'"
        ).fetchone()
    assert lineage_table is None

    storage.restore_database(backup_path)
    assert storage.count_price_rows() == 1
    assert storage.list_ingestion_runs() == []
