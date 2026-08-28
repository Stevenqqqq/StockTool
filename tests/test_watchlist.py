from __future__ import annotations

import pandas as pd
import pandas.testing as pdt

from stock_tool.watchlist import (
    add_watchlist_symbol,
    build_effective_watchlist,
    load_watchlist,
    normalize_watchlist,
    remove_watchlist_symbol,
    save_watchlist,
)


def test_load_watchlist_returns_empty_schema_when_missing(tmp_path) -> None:
    result = load_watchlist(tmp_path / "missing.csv")

    assert list(result.columns) == ["symbol", "market", "note"]
    assert result.empty


def test_add_watchlist_symbol_updates_without_mutating_input() -> None:
    original = pd.DataFrame({"symbol": ["2330"], "market": ["TW"], "note": ["old"]})
    snapshot = original.copy(deep=True)

    result = add_watchlist_symbol(original, symbol="2330", market="tw", note="new")

    pdt.assert_frame_equal(original, snapshot)
    assert len(result) == 1
    assert result.loc[0, "market"] == "TW"
    assert result.loc[0, "note"] == "new"


def test_remove_watchlist_symbol_by_symbol_and_market() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TW", "US"],
            "note": ["", ""],
        }
    )

    result = remove_watchlist_symbol(frame, symbol="2330", market="TW")

    assert result["symbol"].tolist() == ["AAPL"]


def test_save_and_load_watchlist_roundtrip(tmp_path) -> None:
    path = tmp_path / "watchlist.csv"
    frame = normalize_watchlist(pd.DataFrame({"symbol": ["2330"], "market": ["TW"]}))

    save_watchlist(frame, path)
    loaded = load_watchlist(path)

    assert loaded["symbol"].tolist() == ["2330"]
    assert loaded["market"].tolist() == ["TW"]


def test_effective_watchlist_unions_manual_and_portfolio_without_writing_inputs() -> None:
    manual = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TW", "US"],
            "note": ["manual note", "manual US"],
        }
    )
    portfolio = pd.DataFrame(
        {
            "symbol": ["2330", "6488", "AAPL", "MYSTERY"],
            "market": ["TWSE", "TPEX", "US", "UNKNOWN"],
            "quantity": [1, 1, 1, 1],
        }
    )
    manual_before = manual.copy(deep=True)
    portfolio_before = portfolio.copy(deep=True)

    result = build_effective_watchlist(manual, portfolio)

    assert [(row.symbol, row.market) for row in result.itertuples(index=False)] == [
        ("6488", "TPEX"),
        ("2330", "TWSE"),
        ("AAPL", "US"),
    ]
    merged = result.loc[(result["symbol"] == "2330") & (result["market"] == "TWSE")].iloc[0]
    assert merged["note"] == "manual note"
    assert merged["tracking_source"] == "手動自選＋持股"
    assert result.loc[result["symbol"] == "6488", "tracking_source"].item() == "持股自動追蹤"
    assert "MYSTERY" not in result["symbol"].tolist()
    pdt.assert_frame_equal(manual, manual_before)
    pdt.assert_frame_equal(portfolio, portfolio_before)


def test_effective_watchlist_keeps_manual_unknown_without_guessing_a_market() -> None:
    manual = pd.DataFrame({"symbol": ["1234"], "market": ["AUTO"], "note": ["keep"]})
    portfolio = pd.DataFrame(columns=["symbol", "market", "quantity"])

    result = build_effective_watchlist(manual, portfolio)

    assert result.loc[0, "symbol"] == "1234"
    assert result.loc[0, "market"] == "AUTO"
    assert result.loc[0, "tracking_source"] == "手動自選"


def test_effective_watchlist_manual_overlap_retains_note_and_removal_keeps_held_symbol() -> None:
    manual = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "note": ["keep this note", "manual only"],
        }
    )
    portfolio = pd.DataFrame(
        {
            "symbol": ["2330", "6488", "MU", "00935"],
            "market": ["TWSE", "TPEX", "US", "TWSE"],
            "quantity": [1, 1, 1, 1],
        }
    )

    union = build_effective_watchlist(manual, portfolio)
    manual_after_remove = remove_watchlist_symbol(manual, symbol="2330", market="TWSE")
    after_remove = build_effective_watchlist(manual_after_remove, portfolio)

    assert len(union) == 5
    overlap = union.loc[(union["symbol"] == "2330") & (union["market"] == "TWSE")].iloc[0]
    assert overlap["note"] == "keep this note"
    assert overlap["tracking_source"] == "手動自選＋持股"
    held = after_remove.loc[
        (after_remove["symbol"] == "2330") & (after_remove["market"] == "TWSE")
    ].iloc[0]
    assert held["tracking_source"] == "持股自動追蹤"
