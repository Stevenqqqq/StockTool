from __future__ import annotations

import pandas as pd
import pandas.testing as pdt

from stock_tool.portfolio_health import PortfolioHealthConfig, PortfolioHealthService
from stock_tool.portfolio_valuation import (
    Currency,
    FxQuote,
    PortfolioValuationService,
    StaticFxRateProvider,
)


def _portfolio() -> pd.DataFrame:
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


def _valuation():
    quote = FxQuote.manual(Currency.USD, Currency.TWD, 32.0, "2026-01-02T00:00:00+00:00")
    return PortfolioValuationService(StaticFxRateProvider([quote])).value(
        positions=_portfolio(), prices=_prices()
    )


def test_health_result_is_deterministic_uses_evidence_and_does_not_mutate_inputs() -> None:
    portfolio = _portfolio()
    prices = _prices()
    fundamentals = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "roe": [0.2, 0.2],
        }
    )
    indicators = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "rolling_volatility_20": [0.2, 0.2],
            "max_drawdown": [-0.1, -0.1],
        }
    )
    stock_scores = pd.DataFrame(
        {"symbol": ["2330", "AAPL"], "market": ["TWSE", "US"], "total_score": [70.0, 80.0]}
    )
    originals = [
        item.copy(deep=True) for item in (portfolio, prices, fundamentals, indicators, stock_scores)
    ]
    service = PortfolioHealthService(PortfolioHealthConfig(minimum_coverage_pct=0.6))

    first = service.assess(
        portfolio=portfolio,
        valuation=_valuation(),
        prices=prices,
        fundamentals=fundamentals,
        indicators=indicators,
        stock_scores=stock_scores,
    )
    second = service.assess(
        portfolio=portfolio,
        valuation=_valuation(),
        prices=prices,
        fundamentals=fundamentals,
        indicators=indicators,
        stock_scores=stock_scores,
    )

    for actual, expected in zip(
        (portfolio, prices, fundamentals, indicators, stock_scores), originals, strict=True
    ):
        pdt.assert_frame_equal(actual, expected)
    assert first == second
    assert first.overall_score is not None
    assert first.coverage.coverage_pct == 1.0
    assert all(component.evidence for component in first.components)


def test_low_coverage_returns_unknown_without_using_profit_loss_as_a_score_factor() -> None:
    result = PortfolioHealthService(PortfolioHealthConfig(minimum_coverage_pct=0.9)).assess(
        portfolio=_portfolio(), valuation=_valuation()
    )

    assert result.overall_score is None
    assert result.status == "insufficient_data"
    assert any(item.field == "portfolio_health" for item in result.missing_data)
    assert all(
        "unrealized" not in " ".join(component.reasons).lower() for component in result.components
    )
