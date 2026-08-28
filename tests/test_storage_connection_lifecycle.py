from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stock_tool.data.storage import SQLitePriceStorage


def _record() -> dict[str, object]:
    return {
        "date": "2024-01-02",
        "symbol": "2330",
        "open": 590.0,
        "high": 600.0,
        "low": 585.0,
        "close": 595.0,
        "volume": 1000.0,
        "adjusted_close": 595.0,
    }


def test_successful_storage_operation_closes_connection_for_windows_file_rename(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "prices.sqlite"
    storage = SQLitePriceStorage(database_path)

    storage.save_price_data([_record()])
    renamed_path = tmp_path / "prices-renamed.sqlite"
    database_path.rename(renamed_path)
    renamed_path.unlink()

    assert not database_path.exists()
    assert not renamed_path.exists()


def test_sql_failure_rolls_back_and_closes_connection_for_windows_file_cleanup(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "failed.sqlite"
    storage = SQLitePriceStorage(database_path)
    invalid_record = _record()
    invalid_record["open"] = object()

    with pytest.raises(sqlite3.ProgrammingError):
        storage.save_price_data([invalid_record])

    renamed_path = tmp_path / "failed-renamed.sqlite"
    database_path.rename(renamed_path)
    renamed_path.unlink()

    assert not database_path.exists()
    assert not renamed_path.exists()
