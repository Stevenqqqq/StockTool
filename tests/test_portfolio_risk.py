from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pandas.testing as pdt

from stock_tool.application.portfolio_risk import PortfolioRiskService
from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio.ledger import LedgerEntry, LedgerEntryType, replay_ledger
from stock_tool.portfolio_health import PortfolioHealthService
from stock_tool.portfolio_valuation import (
    Currency,
    FxQuote,
    PortfolioValuationService,
    StaticFxRateProvider,
)


def _portfolio() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "6488", "UNCLASSIFIED"],
            "market": ["TWSE", "US", "TPEX", "US"],
            "currency": ["TWD", "USD", "TWD", "USD"],
            "quantity": [10.0, 2.0, 5.0, 1.0],
            "average_cost": [500.0, 100.0, 80.0, 20.0],
            "note": ["", "", "", ""],
        }
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-07-20"] * 4,
            "symbol": ["2330", "AAPL", "6488", "UNCLASSIFIED"],
            "market": ["TWSE", "US", "TPEX", "US"],
            "close": [600.0, 120.0, 100.0, 30.0],
        }
    )


def _valuation():
    quote = FxQuote.manual(
        Currency.USD,
        Currency.TWD,
        32.0,
        "2026-07-20T00:00:00+00:00",
    )
    return PortfolioValuationService(StaticFxRateProvider([quote])).value(
        positions=_portfolio(), prices=_prices()
    )


def _classifications() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "6488"],
            "market": ["TWSE", "US", "TPEX"],
            "sector": ["Semiconductors", "Technology", "Semiconductors"],
            "industry": ["Foundry", "Hardware", "Memory"],
            "source": ["fixture"] * 3,
            "as_of_date": ["2026-07-20"] * 3,
        }
    )


def test_risk_service_reports_market_qualified_exposure_and_is_serializable() -> None:
    portfolio = _portfolio()
    prices = _prices()
    valuation = _valuation()
    result = PortfolioRiskService(now=lambda: datetime(2026, 7, 21, tzinfo=timezone.utc)).assess(
        portfolio=portfolio,
        prices=prices,
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=portfolio, valuation=valuation),
        classifications=_classifications(),
    )

    pdt.assert_frame_equal(portfolio, _portfolio())
    pdt.assert_frame_equal(prices, _prices())
    assert result.total_portfolio_value == valuation.base_market_value
    assert result.position_concentration is not None
    assert result.top_three_concentration is not None
    assert result.market_exposure.items[0].identity == "US"
    assert result.currency_exposure.items[0].identity == "USD"
    assert result.sector_exposure.classified_weight is not None
    assert result.sector_exposure.unclassified_weight is not None
    assert result.factor_exposure.status == "unknown"
    assert result.data_as_of == "2026-07-20"
    assert result.to_dict()["base_currency"] == "TWD"


def test_risk_service_refuses_combined_exposure_when_fx_or_price_is_missing() -> None:
    portfolio = _portfolio()
    prices = _prices().loc[lambda frame: frame["symbol"].ne("AAPL")]
    valuation = PortfolioValuationService().value(positions=portfolio, prices=prices)

    result = PortfolioRiskService().assess(
        portfolio=portfolio,
        prices=prices,
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=portfolio, valuation=valuation),
        classifications=_classifications(),
    )

    assert result.market_exposure.status == "unknown"
    assert result.market_exposure.items == ()
    assert any(item.field == "portfolio_risk.exposure" for item in result.missing_data)


def test_risk_service_runs_deterministic_stress_and_preserves_valuation() -> None:
    valuation = _valuation()
    before = valuation.positions.copy(deep=True)
    result = PortfolioRiskService().assess(
        portfolio=_portfolio(),
        prices=_prices(),
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=_portfolio(), valuation=valuation),
        classifications=_classifications(),
    )

    pdt.assert_frame_equal(valuation.positions, before)
    assert {item.scenario.name for item in result.stress_results} >= {
        "all_holdings_correction_10",
        "largest_holding_decline_25",
        "twse_market_decline_15",
        "us_market_decline_15",
        "usd_twd_plus_5",
        "usd_twd_minus_5",
    }
    assert all(item.disclaimer for item in result.stress_results)


def test_risk_service_does_not_leak_sensitive_text() -> None:
    valuation = _valuation()
    result = PortfolioRiskService().assess(
        portfolio=_portfolio(),
        prices=_prices(),
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=_portfolio(), valuation=valuation),
        classifications=_classifications(),
        warnings=("provider failed token=secret-value",),
    )

    serialized = str(result.to_dict())
    assert "secret-value" not in serialized
    assert "[REDACTED]" in serialized


def test_cross_market_classification_is_not_inferred_or_mixed() -> None:
    portfolio = pd.DataFrame(
        {
            "symbol": ["DUP", "DUP"],
            "market": ["TWSE", "US"],
            "currency": ["TWD", "USD"],
            "quantity": [1.0, 1.0],
            "average_cost": [10.0, 10.0],
            "note": ["", ""],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2026-07-20", "2026-07-20"],
            "symbol": ["DUP", "DUP"],
            "market": ["TWSE", "US"],
            "close": [10.0, 10.0],
        }
    )
    quote = FxQuote.manual(Currency.USD, Currency.TWD, 32.0, "2026-07-20T00:00:00+00:00")
    valuation = PortfolioValuationService(StaticFxRateProvider([quote])).value(
        positions=portfolio, prices=prices
    )
    classifications = pd.DataFrame(
        {
            "symbol": ["DUP"],
            "market": ["US"],
            "sector": ["Technology"],
            "industry": ["Hardware"],
            "source": ["fixture"],
        }
    )

    result = PortfolioRiskService().assess(
        portfolio=portfolio,
        prices=prices,
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=portfolio, valuation=valuation),
        classifications=classifications,
    )

    assert result.sector_exposure.status == "partial"
    assert result.sector_exposure.items == (result.sector_exposure.items[0],)
    assert result.sector_exposure.items[0].identity == "Technology"
    assert result.sector_exposure.unclassified_weight == 10.0 / 330.0


def test_ledger_realized_profit_uses_explicit_fx_evidence() -> None:
    symbol = Symbol.parse("AAPL", market=Market.US)
    entries = (
        LedgerEntry(
            entry_id="deposit",
            entry_type=LedgerEntryType.CASH_DEPOSIT,
            effective_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            sequence=0,
            currency="USD",
            native_cash_delta=Decimal("100"),
        ),
        LedgerEntry(
            entry_id="buy",
            entry_type=LedgerEntryType.BUY,
            effective_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            sequence=1,
            symbol=symbol,
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            currency="USD",
        ),
        LedgerEntry(
            entry_id="sell",
            entry_type=LedgerEntryType.SELL,
            effective_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            sequence=2,
            symbol=symbol,
            quantity=Decimal("1"),
            unit_price=Decimal("120"),
            currency="USD",
        ),
    )
    valuation = _valuation()
    result = PortfolioRiskService().assess(
        portfolio=_portfolio(),
        prices=_prices(),
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=_portfolio(), valuation=valuation),
        classifications=_classifications(),
        ledger_snapshot=replay_ledger(entries),
    )

    assert result.realized_pnl == 640.0


def test_risk_service_uses_oldest_latest_holding_price_and_marks_stale_or_missing() -> None:
    prices = _prices().copy(deep=True)
    prices.loc[prices["symbol"].eq("AAPL"), "date"] = "2026-07-10"
    prices = prices.loc[prices["symbol"].ne("6488")]
    valuation = PortfolioValuationService().value(positions=_portfolio(), prices=prices)

    result = PortfolioRiskService(now=lambda: datetime(2026, 7, 21, tzinfo=timezone.utc)).assess(
        portfolio=_portfolio(),
        prices=prices,
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=_portfolio(), valuation=valuation),
    )

    assert result.data_as_of == "2026-07-10"
    assert "AAPL|US" in result.price_data_status.stale_identities
    assert "6488|TPEX" in result.price_data_status.missing_identities
    assert result.price_data_status.status == "partial"


def test_risk_service_fails_closed_for_conflicting_classification_sources() -> None:
    classifications = _classifications()
    classifications = pd.concat(
        [
            classifications,
            pd.DataFrame(
                {
                    "symbol": ["2330"],
                    "market": ["TWSE"],
                    "sector": ["Different sector"],
                    "industry": ["Foundry"],
                    "source": ["second-source"],
                }
            ),
        ],
        ignore_index=True,
    )
    valuation = _valuation()
    result = PortfolioRiskService().assess(
        portfolio=_portfolio(),
        prices=_prices(),
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=_portfolio(), valuation=valuation),
        classifications=classifications,
    )

    assert result.sector_exposure.status == "partial"
    assert result.sector_exposure.unclassified_weight is not None
    assert result.sector_exposure.conflicts[0]["identity"] == "2330|TWSE"
    assert result.sector_exposure.conflicts[0]["sources"] == ["fixture", "second-source"]


def test_evidence_stress_requires_explicit_sensitivity_and_uses_it_when_complete() -> None:
    valuation = _valuation()
    service = PortfolioRiskService()
    unknown = service.assess(
        portfolio=_portfolio(),
        prices=_prices(),
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=_portfolio(), valuation=valuation),
    )
    assert {item.name for item in unknown.evidence_stress_results} == {
        "volatility_spike",
        "interest_rate_shock",
    }
    assert all(item.status == "unknown" for item in unknown.evidence_stress_results)

    inputs = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "6488", "UNCLASSIFIED"] * 2,
            "market": ["TWSE", "US", "TPEX", "US"] * 2,
            "scenario_type": ["volatility_spike"] * 4 + ["interest_rate_shock"] * 4,
            "shock_pct": [0.10] * 4 + [0.01] * 4,
            "sensitivity": [-0.50] * 4 + [-2.0] * 4,
            "source": ["fixture"] * 8,
        }
    )
    complete = service.assess(
        portfolio=_portfolio(),
        prices=_prices(),
        valuation=valuation,
        health=PortfolioHealthService().assess(portfolio=_portfolio(), valuation=valuation),
        scenario_inputs=inputs,
    )
    volatility = next(
        item for item in complete.evidence_stress_results if item.name == "volatility_spike"
    )
    rate = next(
        item for item in complete.evidence_stress_results if item.name == "interest_rate_shock"
    )
    assert volatility.status == "available"
    assert rate.status == "available"
    assert volatility.base_impact is not None and volatility.base_impact < 0
    assert rate.base_impact is not None and rate.base_impact < 0
