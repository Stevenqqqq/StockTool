from __future__ import annotations

from pathlib import Path

import pandas as pd

from stock_tool.fundamentals.loader import FUNDAMENTAL_COLUMNS, load_fundamentals_csv
from stock_tool.fundamentals.models import (
    FundamentalPointInTimeMode,
    prepare_fundamental_strategy_frame,
    visible_fundamentals_as_of,
)
from stock_tool.strategies import FundamentalGrowthStrategy


def _fundamental_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["2330", "2330"],
            "market": ["TWSE", "TWSE"],
            "fiscal_period": ["2024Q4", "2025Q1"],
            "filing_date": ["2025-02-01", "2025-05-01"],
            "available_date": ["2025-02-10", "2025-05-15"],
            "source": ["fixture", "fixture"],
            "eps_growth": [0.20, 0.01],
            "revenue_growth": [0.20, 0.01],
            "roe": [0.20, 0.05],
            "debt_ratio": [0.30, 0.80],
        }
    )


def test_fundamentals_are_not_visible_before_available_date() -> None:
    fundamentals = _fundamental_rows()

    before = visible_fundamentals_as_of(
        fundamentals,
        "2025-02-09",
        mode=FundamentalPointInTimeMode.STRICT,
    )
    on_date = visible_fundamentals_as_of(
        fundamentals,
        "2025-02-10",
        mode=FundamentalPointInTimeMode.STRICT,
    )

    assert before.data.empty
    assert on_date.data["fiscal_period"].tolist() == ["2024Q4"]


def test_filing_date_does_not_make_fundamentals_visible_early() -> None:
    fundamentals = _fundamental_rows()

    result = visible_fundamentals_as_of(
        fundamentals,
        "2025-02-05",
        mode=FundamentalPointInTimeMode.STRICT,
    )

    assert result.data.empty


def test_strict_mode_excludes_missing_available_date_and_warns() -> None:
    fundamentals = _fundamental_rows()
    fundamentals.loc[0, "available_date"] = pd.NA

    result = visible_fundamentals_as_of(
        fundamentals,
        "2025-02-20",
        mode=FundamentalPointInTimeMode.STRICT,
    )

    assert result.data.empty
    assert any("available_date" in warning for warning in result.warnings)


def test_legacy_mode_keeps_compatibility_but_warns_on_missing_available_date() -> None:
    legacy = (
        _fundamental_rows().rename(columns={"available_date": "date"}).drop(columns=["filing_date"])
    )

    result = prepare_fundamental_strategy_frame(
        legacy,
        mode=FundamentalPointInTimeMode.LEGACY,
    )

    assert result.data["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-02-10",
        "2025-05-15",
    ]
    assert any("legacy" in warning.lower() or "相容" in warning for warning in result.warnings)


def test_fundamental_loader_standardizes_available_date_metadata(tmp_path: Path) -> None:
    source = tmp_path / "fundamentals.csv"
    source.write_text(
        "\n".join(
            [
                "symbol,market,fiscal_period,filing_date,available_date,source,eps",
                "MU,US,2025Q2,2025-06-25,2025-07-01,yfinance,1.23",
            ]
        ),
        encoding="utf-8",
    )

    fundamentals = load_fundamentals_csv(source)

    assert "filing_date" in FUNDAMENTAL_COLUMNS
    assert fundamentals.loc[0, "filing_date"] == "2025-06-25"
    assert fundamentals.loc[0, "available_date"] == "2025-07-01"
    assert fundamentals.loc[0, "source"] == "yfinance"


def test_fundamental_growth_strategy_uses_available_date_not_filing_date() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2025-02-05", "2025-02-10", "2025-02-11"],
            "symbol": ["2330", "2330", "2330"],
            "open": [10.0, 11.0, 12.0],
            "high": [10.0, 11.0, 12.0],
            "low": [10.0, 11.0, 12.0],
            "close": [10.0, 11.0, 12.0],
            "volume": [100, 100, 100],
        }
    )
    fundamentals = _fundamental_rows().iloc[[0]]
    strategy = FundamentalGrowthStrategy(
        quantity=10,
        point_in_time_mode=FundamentalPointInTimeMode.STRICT,
    )

    signals = strategy.generate_signals(prices, fundamentals=fundamentals)

    assert signals.loc[signals["date"] == "2025-02-05", "signal"].iloc[0] == 0
    assert signals.loc[signals["date"] == "2025-02-10", "signal"].iloc[0] == 1


def test_legacy_csv_preserves_date_when_loader_adds_empty_available_date(tmp_path: Path) -> None:
    source = tmp_path / "legacy_fundamentals.csv"
    source.write_text(
        "symbol,fiscal_period,date,eps_growth,revenue_growth,roe,debt_ratio\n"
        "2330,2024Q4,2025-02-10,0.20,0.20,0.20,0.30\n",
        encoding="utf-8",
    )

    loaded = load_fundamentals_csv(source)
    prepared = prepare_fundamental_strategy_frame(loaded, mode="legacy")
    signals = FundamentalGrowthStrategy(quantity=1).generate_signals(
        pd.DataFrame({"date": ["2025-02-10"], "symbol": ["2330"], "close": [10.0]}),
        fundamentals=loaded,
    )

    assert loaded.loc[0, "date"] == "2025-02-10"
    assert pd.notna(prepared.data.loc[0, "date"])
    assert signals.loc[0, "signal"] == 1


def test_legacy_mode_uses_available_date_when_present_and_date_when_missing() -> None:
    fundamentals = pd.DataFrame(
        {
            "symbol": ["2330", "2330"],
            "date": ["2025-02-01", "2025-03-01"],
            "available_date": ["2025-02-10", pd.NA],
        }
    )

    prepared = prepare_fundamental_strategy_frame(fundamentals, mode="legacy")

    assert prepared.data["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-02-10", "2025-03-01"]
    assert pd.api.types.is_datetime64_any_dtype(prepared.data["available_date"])
