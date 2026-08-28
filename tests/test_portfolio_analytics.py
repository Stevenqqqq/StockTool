from __future__ import annotations

import pandas as pd
import pandas.testing as pdt
import pytest

from stock_tool.dashboard import app as dashboard_app
from stock_tool.domain.models import MissingData, MissingDataState
from stock_tool.portfolio_analytics import (
    PortfolioDataGap,
    PortfolioIdentity,
    build_portfolio_data_gaps,
    build_portfolio_risk_inputs,
)

IDENTITY_COLUMN = "\u8b58\u5225"
REPAIR_COLUMN = "\u4fee\u5fa9\u65b9\u5f0f"
PORTFOLIO_WIDE = "\u6574\u9ad4\u6295\u8cc7\u7d44\u5408"
UNKNOWN_IDENTITY = "\u7121\u6cd5\u5224\u5b9a"


def _prices() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=21, freq="D")
    return pd.DataFrame(
        {
            "date": list(dates) * 2,
            "symbol": ["A"] * 21 + ["B"] * 21,
            "market": ["TWSE"] * 21 + ["US"] * 21,
            "close": list(range(100, 121)) + [100, 90] * 10 + [100],
        }
    )


def test_risk_inputs_are_canonical_per_identity_and_do_not_mutate() -> None:
    positions = pd.DataFrame({"symbol": ["A", "B"], "market": ["TWSE", "US"], "weight": [0.5, 0.5]})
    prices = _prices()
    original = prices.copy(deep=True)

    result = build_portfolio_risk_inputs(prices, positions)

    assert set(map(tuple, result.frame[["symbol", "market"]].to_numpy())) == {
        ("A", "TWSE"),
        ("B", "US"),
    }
    assert len(result.frame) == 2
    assert result.frame["volatility_20"].notna().all()
    assert result.frame.loc[result.frame["symbol"] == "A", "max_drawdown"].iloc[0] == 0.0
    assert result.frame.loc[result.frame["symbol"] == "B", "max_drawdown"].iloc[0] == pytest.approx(
        -0.1
    )
    pdt.assert_frame_equal(prices, original)


def test_risk_inputs_do_not_mix_histories_or_markets() -> None:
    positions = pd.DataFrame(
        {"symbol": ["DUP", "DUP"], "market": ["TWSE", "US"], "weight": [0.5, 0.5]}
    )
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3, freq="D").tolist() * 2,
            "symbol": ["DUP"] * 6,
            "market": ["TWSE"] * 3 + ["US"] * 3,
            "close": [100.0, 90.0, 100.0, 100.0, 50.0, 100.0],
        }
    )

    result = build_portfolio_risk_inputs(prices, positions)

    drawdowns = result.frame.set_index(["symbol", "market"])["max_drawdown"]
    assert drawdowns["DUP", "TWSE"] == pytest.approx(-0.1)
    assert drawdowns["DUP", "US"] == pytest.approx(-0.5)
    assert result.frame["volatility_20"].isna().all()
    assert all(item.state is MissingDataState.MISSING for item in result.missing_data)
    assert not (result.frame["volatility_20"] == 0.0).any()


def test_data_gap_table_uses_structured_identity_not_all_positions() -> None:
    positions = pd.DataFrame({"symbol": ["A", "B"], "market": ["TWSE", "US"]})
    original_positions = positions.copy(deep=True)
    result = build_portfolio_risk_inputs(
        pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=21, freq="D"),
                "symbol": ["B"] * 21,
                "market": ["US"] * 21,
                "close": range(100, 121),
            }
        ),
        positions,
    )
    original_risk_frame = result.frame.copy(deep=True)
    table = build_portfolio_data_gaps(
        positions=positions,
        missing_data=result.missing_data + result.missing_data,
        structured_gaps=result.data_gaps,
    )

    assert len(table) == len(result.missing_data)
    assert REPAIR_COLUMN in table.columns
    assert table.loc[0, IDENTITY_COLUMN] == "A/TWSE"
    assert "B/US" not in table.loc[0, IDENTITY_COLUMN]
    pdt.assert_frame_equal(positions, original_positions)
    pdt.assert_frame_equal(result.frame, original_risk_frame)


def test_data_gap_table_keeps_same_symbol_different_market_distinct() -> None:
    missing = MissingData(
        field="technical_indicators",
        state=MissingDataState.MISSING,
        reason="Structured identity is required.",
    )
    table = build_portfolio_data_gaps(
        positions=pd.DataFrame({"symbol": ["DUP", "DUP"], "market": ["TWSE", "US"]}),
        missing_data=(missing,),
        structured_gaps=(
            PortfolioDataGap(
                missing_data=missing,
                affected_identities=(PortfolioIdentity("DUP", "US"),),
            ),
        ),
    )

    assert table.loc[0, IDENTITY_COLUMN] == "DUP/US"


def test_data_gap_table_marks_portfolio_fx_as_portfolio_wide() -> None:
    missing = MissingData(
        field="portfolio_fx",
        state=MissingDataState.MISSING,
        reason="A manual FX quote is required.",
    )

    table = build_portfolio_data_gaps(
        positions=pd.DataFrame({"symbol": ["A"], "market": ["TWSE"]}),
        missing_data=(missing,),
    )

    assert table.loc[0, IDENTITY_COLUMN] == PORTFOLIO_WIDE


def test_data_gap_table_does_not_parse_reason_when_identity_metadata_is_absent() -> None:
    missing = MissingData(
        field="technical_indicators",
        state=MissingDataState.MISSING,
        reason="A/TWSE is mentioned here but is not structured metadata.",
    )

    table = build_portfolio_data_gaps(
        positions=pd.DataFrame({"symbol": ["A", "B"], "market": ["TWSE", "US"]}),
        missing_data=(missing,),
    )

    assert table.loc[0, IDENTITY_COLUMN] == UNKNOWN_IDENTITY


def test_dashboard_missing_metric_uses_visible_dash() -> None:
    assert dashboard_app._score_value(None) == "\u2014"
    assert dashboard_app._currency_value(None, "TWD") == "\u2014"
