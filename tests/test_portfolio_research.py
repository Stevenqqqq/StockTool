from __future__ import annotations

import pandas as pd

from stock_tool.portfolio_health import PortfolioHealthConfig, PortfolioHealthService
from stock_tool.portfolio_research import build_portfolio_research_brief
from stock_tool.portfolio_stress import PortfolioStressService, StressScenario, StressScenarioType
from stock_tool.portfolio_valuation import PortfolioValuationService


def _valuation():
    positions = pd.DataFrame(
        {
            "symbol": ["2330"],
            "market": ["TWSE"],
            "currency": ["TWD"],
            "quantity": [10.0],
            "average_cost": [500.0],
            "note": [""],
        }
    )
    prices = pd.DataFrame(
        {"date": ["2026-01-02"], "symbol": ["2330"], "market": ["TWSE"], "close": [600.0]}
    )
    return PortfolioValuationService().value(positions=positions, prices=prices)


def test_local_research_brief_is_data_bound_and_has_no_trade_instruction() -> None:
    health = PortfolioHealthService(PortfolioHealthConfig(minimum_coverage_pct=0.0)).assess(
        portfolio=pd.DataFrame(
            {
                "symbol": ["2330"],
                "market": ["TWSE"],
                "currency": ["TWD"],
                "quantity": [10.0],
                "average_cost": [500.0],
                "note": [""],
            }
        ),
        valuation=_valuation(),
    )

    brief = build_portfolio_research_brief(health)
    text = " ".join(
        [
            brief.overall_summary,
            *brief.strengths,
            *brief.top_risks,
            *brief.next_checks,
            brief.disclaimer,
        ]
    )

    assert brief.evidence
    assert "外部" in brief.disclaimer
    assert not any(word in text for word in ("買進", "賣出", "加碼", "減碼", "保證獲利"))


def test_stress_test_is_transparent_deterministic_and_does_not_mutate_valuation() -> None:
    valuation = _valuation()
    before = valuation.positions.copy(deep=True)
    scenario = StressScenario(
        name="all-holdings-down",
        scenario_type=StressScenarioType.ALL_HOLDINGS_DECLINE,
        shock_pct=0.1,
    )

    result = PortfolioStressService().run(valuation=valuation, scenario=scenario)

    assert result.base_value_before == 6_000.0
    assert result.base_value_after == 5_400.0
    assert result.base_impact == -600.0
    pd.testing.assert_frame_equal(valuation.positions, before)
    assert "not a forecast" in result.disclaimer.lower()
