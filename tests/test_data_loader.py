from __future__ import annotations

from pathlib import Path

import pytest

from stock_tool.data.loader import MissingColumnError, load_csv, load_excel


def test_load_csv_standardizes_sample_file() -> None:
    rows = load_csv(Path("data/sample/sample_tw_prices.csv"))

    assert len(rows) == 8
    assert set(rows[0]) == {
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjusted_close",
    }
    assert rows[0]["symbol"] == "2330"


def test_load_csv_raises_for_missing_required_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "missing_columns.csv"
    csv_path.write_text("date,symbol,open\n2024-01-02,2330,590\n", encoding="utf-8")

    with pytest.raises(MissingColumnError) as exc_info:
        load_csv(csv_path)

    assert "high" in exc_info.value.missing_columns
    assert "volume" in exc_info.value.missing_columns


def test_load_excel_standardizes_rows(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "prices"
    worksheet.append(["日期", "股票代號", "開盤價", "最高價", "最低價", "收盤價", "成交量"])
    worksheet.append(["2024/01/02", "2330", 590, 593, 589, 592, 26000000])

    excel_path = tmp_path / "prices.xlsx"
    workbook.save(excel_path)

    rows = load_excel(excel_path, sheet_name="prices")

    assert rows == [
        {
            "date": "2024/01/02",
            "symbol": "2330",
            "open": 590,
            "high": 593,
            "low": 589,
            "close": 592,
            "volume": 26000000,
            "adjusted_close": None,
        }
    ]

