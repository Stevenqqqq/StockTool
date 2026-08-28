from __future__ import annotations

from pathlib import Path

import pytest

from stock_tool.data import CSVPriceDataProvider, ExcelPriceDataProvider, provider_for_file


def test_csv_price_data_provider_loads_standard_rows() -> None:
    provider = CSVPriceDataProvider("data/sample/sample_tw_prices.csv")

    rows = provider.load_price_data()

    assert len(rows) == 8
    assert rows[0]["symbol"] == "2330"
    assert "adjusted_close" in rows[0]


def test_provider_for_file_selects_excel_provider(tmp_path: Path) -> None:
    excel_path = tmp_path / "prices.xlsx"

    provider = provider_for_file(excel_path)

    assert isinstance(provider, ExcelPriceDataProvider)


def test_provider_preserves_point_in_time_universe_metadata() -> None:
    provider = provider_for_file(
        "data/sample/sample_tw_prices.csv",
        point_in_time_universe="data/raw/historical_universe.csv",
    )

    assert isinstance(provider, CSVPriceDataProvider)
    assert provider.point_in_time_universe == "data/raw/historical_universe.csv"


def test_provider_for_file_rejects_legacy_xls() -> None:
    with pytest.raises(ValueError, match="Legacy .xls"):
        provider_for_file("prices.xls")
