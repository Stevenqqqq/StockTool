from __future__ import annotations

import pandas as pd
import pandas.testing as pdt

from stock_tool.portfolio_management import (
    add_portfolio_position,
    portfolio_summary,
    remove_portfolio_position,
)
from stock_tool.portfolio_valuation import (
    Currency,
    FxQuote,
    PortfolioValuationService,
    StaticFxRateProvider,
)


def _positions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "currency": ["TWD", "USD"],
            "quantity": [10.0, 2.0],
            "average_cost": [500.0, 100.0],
            "note": ["", ""],
        }
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02"],
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "close": [600.0, 120.0],
        }
    )


def test_same_symbol_in_different_markets_coexists_and_removal_uses_full_identity() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["ABC", "ABC"],
            "market": ["US", "TWSE"],
            "currency": ["USD", "TWD"],
            "quantity": [1.0, 2.0],
            "average_cost": [10.0, 20.0],
            "note": ["", ""],
        }
    )

    retained = remove_portfolio_position(positions, symbol="ABC", market="US")

    assert retained[["symbol", "market"]].to_dict("records") == [
        {"symbol": "ABC", "market": "TWSE"}
    ]

    try:
        remove_portfolio_position(positions, symbol="ABC")
    except ValueError as exc:
        assert "market-qualified" in str(exc)
    else:
        raise AssertionError("Ambiguous legacy removal must not delete both positions")


def test_portfolio_summary_uses_symbol_and_market_for_price_lookup() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["ABC", "ABC"],
            "market": ["US", "TWSE"],
            "currency": ["USD", "TWD"],
            "quantity": [1.0, 1.0],
            "average_cost": [10.0, 20.0],
            "note": ["", ""],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02"],
            "symbol": ["ABC", "ABC"],
            "market": ["US", "TWSE"],
            "close": [30.0, 40.0],
        }
    )

    summary = portfolio_summary(positions, prices)

    assert summary.loc[summary["market"] == "US", "latest_price"].iloc[0] == 30.0
    assert summary.loc[summary["market"] == "TWSE", "latest_price"].iloc[0] == 40.0


def test_legacy_summary_does_not_mix_native_currency_weights() -> None:
    summary = portfolio_summary(_positions(), _prices())

    assert summary["weight"].isna().all()


def test_mixed_currency_portfolio_has_unknown_consolidated_totals_without_fx() -> None:
    positions = _positions()
    prices = _prices()
    original_positions = positions.copy(deep=True)
    original_prices = prices.copy(deep=True)

    result = PortfolioValuationService().value(positions=positions, prices=prices)

    pdt.assert_frame_equal(positions, original_positions)
    pdt.assert_frame_equal(prices, original_prices)
    assert result.base_market_value is None
    assert result.positions["weight"].isna().all()
    assert any(item.field == "fx_rate_to_base" for item in result.missing_data)


def test_mixed_currency_portfolio_uses_fixed_fx_quote_for_base_totals_and_weights() -> None:
    quote = FxQuote.manual(
        from_currency=Currency.USD,
        to_currency=Currency.TWD,
        rate=32.0,
        effective_at="2026-01-02T00:00:00+00:00",
    )
    result = PortfolioValuationService(fx_provider=StaticFxRateProvider([quote])).value(
        positions=_positions(), prices=_prices()
    )

    assert result.base_currency is Currency.TWD
    assert result.base_cost_basis == 11_400.0
    assert result.base_market_value == 13_680.0
    assert result.base_unrealized_pnl == 2_280.0
    assert result.positions["weight"].sum() == 1.0
    assert (
        result.positions.loc[result.positions["market"] == "US", "fx_rate_to_base"].iloc[0] == 32.0
    )


def test_stale_fx_quote_is_explicitly_warned_not_labeled_as_live_data() -> None:
    quote = FxQuote(
        from_currency=Currency.USD,
        to_currency=Currency.TWD,
        rate=32.0,
        source="fixture",
        fetched_at="2026-01-01T00:00:00+00:00",
        effective_at="2026-01-01T00:00:00+00:00",
        stale=True,
    )
    result = PortfolioValuationService(fx_provider=StaticFxRateProvider([quote])).value(
        positions=_positions(), prices=_prices()
    )

    assert result.base_market_value is not None
    assert any("stale" in warning.lower() for warning in result.warnings)
    assert (
        result.positions.loc[result.positions["market"] == "US", "fx_source"].iloc[0] == "fixture"
    )


def test_custom_market_requires_explicit_currency() -> None:
    frame = pd.DataFrame(
        columns=["symbol", "market", "currency", "quantity", "average_cost", "note"]
    )

    try:
        add_portfolio_position(
            frame,
            symbol="PRIVATE",
            market="CUSTOM",
            quantity=1,
            average_cost=1,
        )
    except ValueError as exc:
        assert "currency" in str(exc).lower()
    else:
        raise AssertionError("CUSTOM position without currency must be rejected")


def test_unknown_legacy_market_is_reported_without_guessing_or_raising() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["ABC"],
            "market": ["UNKNOWN"],
            "currency": ["UNKNOWN"],
            "quantity": [1.0],
            "average_cost": [10.0],
            "note": [""],
        }
    )

    result = PortfolioValuationService().value(positions=positions, prices=None)

    assert result.base_market_value is None
    assert any(item.field == "portfolio.identity" for item in result.missing_data)
