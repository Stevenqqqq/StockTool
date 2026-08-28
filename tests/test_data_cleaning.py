from __future__ import annotations

import pytest

from stock_tool.data.cleaner import DataValidationError, PriceDataWarning, clean_price_data


def test_clean_price_data_converts_dates_and_removes_duplicates() -> None:
    rows = [
        {
            "date": "20240102",
            "symbol": "2330",
            "open": "590",
            "high": "593",
            "low": "589",
            "close": "592",
            "volume": "26,000,000",
            "adjusted_close": "",
        },
        {
            "date": "2024-01-02",
            "symbol": "2330",
            "open": "590",
            "high": "593",
            "low": "589",
            "close": "592",
            "volume": "26000000",
            "adjusted_close": "",
        },
    ]

    with pytest.warns(PriceDataWarning, match="已移除重複股價資料"):
        result = clean_price_data(rows)

    assert len(result.records) == 1
    assert result.records[0]["date"] == "2024-01-02"
    assert result.records[0]["adjusted_close"] is None
    assert result.records[0]["volume"] == 26000000.0
    assert result.warnings[0].code == "duplicate_removed"


def test_clean_price_data_warns_and_skips_missing_required_values() -> None:
    rows = [
        {
            "date": "2024-01-02",
            "symbol": "2330",
            "open": "",
            "high": "593",
            "low": "589",
            "close": "592",
            "volume": "26000000",
            "adjusted_close": "",
        }
    ]

    with pytest.warns(PriceDataWarning, match="缺少必要欄位值"):
        result = clean_price_data(rows)

    assert result.records == []
    assert result.warnings[0].code == "missing_required_value"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("open", "-1", "invalid_price"),
        ("high", "570", "high_below_open_or_close"),
        ("low", "600", "low_above_open_or_close"),
        ("volume", "-10", "invalid_volume"),
    ],
)
def test_clean_price_data_rejects_invalid_values(
    field: str,
    value: str,
    expected_code: str,
) -> None:
    row = {
        "date": "2024-01-02",
        "symbol": "2330",
        "open": "590",
        "high": "593",
        "low": "589",
        "close": "592",
        "volume": "26000000",
        "adjusted_close": "592",
    }
    row[field] = value

    with pytest.raises(DataValidationError) as exc_info:
        clean_price_data([row])

    assert any(issue.code == expected_code for issue in exc_info.value.issues)


def test_clean_price_data_rejects_high_lower_than_low() -> None:
    row = {
        "date": "2024-01-02",
        "symbol": "2330",
        "open": "590",
        "high": "580",
        "low": "589",
        "close": "579",
        "volume": "26000000",
        "adjusted_close": "579",
    }

    with pytest.raises(DataValidationError) as exc_info:
        clean_price_data([row])

    assert any(issue.code == "high_lower_than_low" for issue in exc_info.value.issues)


def test_clean_price_data_returns_errors_when_fail_on_errors_is_false() -> None:
    rows = [
        {
            "date": "not-a-date",
            "symbol": "2330",
            "open": "590",
            "high": "593",
            "low": "589",
            "close": "592",
            "volume": "26000000",
            "adjusted_close": "",
        }
    ]

    result = clean_price_data(rows, fail_on_errors=False)

    assert result.records == []
    assert result.errors
    assert result.errors[0].code == "invalid_date"
