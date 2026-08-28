from __future__ import annotations

import pandas as pd
import pandas.testing as pdt

from stock_tool.portfolio_management import (
    add_portfolio_position,
    load_portfolio,
    load_portfolio_result,
    normalize_portfolio,
    portfolio_summary,
    remove_portfolio_position,
    save_portfolio,
)


def test_load_portfolio_returns_empty_schema_when_missing(tmp_path) -> None:
    result = load_portfolio(tmp_path / "missing.csv")

    assert list(result.columns) == [
        "symbol",
        "quantity",
        "average_cost",
        "market",
        "currency",
        "note",
    ]
    assert result.empty


def test_add_portfolio_position_updates_without_mutating_input() -> None:
    original = pd.DataFrame(
        {"symbol": ["2330"], "quantity": [1.0], "average_cost": [100.0], "market": ["TW"]}
    )
    snapshot = original.copy(deep=True)

    result = add_portfolio_position(
        original,
        symbol="2330",
        quantity=2.0,
        average_cost=110.0,
        market="tw",
    )

    pdt.assert_frame_equal(original, snapshot)
    assert len(result) == 1
    assert result.loc[0, "quantity"] == 2.0
    assert result.loc[0, "average_cost"] == 110.0


def test_portfolio_summary_calculates_unrealized_pnl_and_weight() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["2330", "0050"],
            "quantity": [10.0, 5.0],
            "average_cost": [100.0, 80.0],
            "market": ["TW", "TW"],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["2330", "0050"],
            "market": ["TWSE", "TWSE"],
            "close": [120.0, 70.0],
        }
    )

    result = portfolio_summary(positions, prices)

    row = result.loc[result["symbol"] == "2330"].iloc[0]
    assert row["market_value"] == 1200.0
    assert row["unrealized_pnl"] == 200.0
    assert result["weight"].sum() == 1.0


def test_portfolio_summary_supports_odd_lot_share_quantity() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["2330"],
            "quantity": [37.0],
            "average_cost": [600.0],
            "market": ["TW"],
        }
    )
    prices = pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"], "close": [650.0]})

    result = portfolio_summary(positions, prices)

    row = result.iloc[0]
    assert row["quantity"] == 37.0
    assert row["cost_basis"] == 22_200.0
    assert row["market_value"] == 24_050.0
    assert row["unrealized_pnl"] == 1_850.0


def test_normalize_portfolio_uppercases_symbols_for_provider_matching() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["mu"],
            "quantity": [1.0],
            "average_cost": [1085.0],
            "market": ["us"],
        }
    )

    result = normalize_portfolio(frame)

    assert result.loc[0, "symbol"] == "MU"
    assert result.loc[0, "market"] == "US"


def test_portfolio_summary_matches_latest_prices_case_insensitively() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["mu"],
            "quantity": [1.0],
            "average_cost": [100.0],
            "market": ["US"],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "symbol": ["MU"],
            "market": ["US"],
            "close": [120.0],
        }
    )

    result = portfolio_summary(positions, prices)

    row = result.iloc[0]
    assert row["symbol"] == "MU"
    assert row["latest_price"] == 120.0
    assert row["market_value"] == 120.0


def test_remove_portfolio_position_and_roundtrip(tmp_path) -> None:
    path = tmp_path / "portfolio.csv"
    frame = normalize_portfolio(
        pd.DataFrame(
            {
                "symbol": ["2330", "AAPL"],
                "quantity": [1, 2],
                "average_cost": [100, 200],
                "market": ["TW", "US"],
            }
        )
    )
    reduced = remove_portfolio_position(frame, symbol="2330", market="TW")

    save_portfolio(reduced, path)
    loaded = load_portfolio(path)

    assert loaded["symbol"].tolist() == ["AAPL"]


def test_legacy_portfolio_missing_market_is_explicitly_unknown(tmp_path) -> None:
    path = tmp_path / "portfolio.csv"
    pd.DataFrame({"symbol": ["2330"], "quantity": [1], "average_cost": [500]}).to_csv(
        path, index=False
    )

    result = load_portfolio_result(path)

    assert result.frame.loc[0, "market"] == "UNKNOWN"
    assert any(item.field == "portfolio.market" for item in result.missing_data)
