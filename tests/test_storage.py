from __future__ import annotations

from pathlib import Path

from stock_tool.data.cleaner import clean_price_data
from stock_tool.data.loader import load_csv
from stock_tool.data.storage import SQLitePriceStorage


def test_sqlite_storage_saves_and_loads_price_data(tmp_path: Path) -> None:
    rows = load_csv(Path("data/sample/sample_tw_prices.csv"))
    cleaned = clean_price_data(rows)
    storage = SQLitePriceStorage(tmp_path / "prices.sqlite")

    saved_count = storage.save_price_data(cleaned.records)
    loaded = storage.load_price_data(symbol="2330")

    assert saved_count == len(cleaned.records)
    assert storage.count_price_rows() == len(cleaned.records)
    assert len(loaded) == 5
    assert loaded[0]["date"] == "2024-01-02"
    assert loaded[0]["symbol"] == "2330"
    assert loaded[0]["close"] == 592.0

