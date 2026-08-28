from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_portfolio_risk_center_renders_isolated_fixture_states(tmp_path, monkeypatch) -> None:
    """The portfolio-risk view shows exposures, data gaps, and assumptions safely."""

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    script = """
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from stock_tool.application.portfolio_risk import PortfolioRiskService
from stock_tool.dashboard.app import _display_portfolio_risk_center
from stock_tool.portfolio_health import PortfolioHealthService
from stock_tool.portfolio_valuation import Currency, FxQuote, PortfolioValuationService, StaticFxRateProvider

portfolio = pd.DataFrame({
    "symbol": ["2330", "AAPL"], "market": ["TWSE", "US"],
    "currency": ["TWD", "USD"], "quantity": [1.0, 1.0],
    "average_cost": [500.0, 100.0], "note": ["", ""],
})
prices = pd.DataFrame({
    "date": ["2026-07-20", "2026-07-01"], "symbol": ["2330", "AAPL"],
    "market": ["TWSE", "US"], "close": [600.0, 120.0],
})
quote = FxQuote.manual(Currency.USD, Currency.TWD, 32.0, "2026-07-20T00:00:00+00:00")
valuation = PortfolioValuationService(StaticFxRateProvider([quote])).value(positions=portfolio, prices=prices)
health = PortfolioHealthService().assess(portfolio=portfolio, valuation=valuation)
result = PortfolioRiskService(now=lambda: datetime(2026, 7, 21, tzinfo=timezone.utc)).assess(
    portfolio=portfolio, prices=prices, valuation=valuation, health=health,
    classifications=pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"], "sector": ["Semiconductors"], "industry": ["Foundry"], "source": ["fixture"]}),
)
_display_portfolio_risk_center(st, result)
"""

    app = AppTest.from_string(script).run(timeout=20)

    assert not app.exception
    assert any(item.value == "投資組合風險中心" for item in app.subheader)
    rendered = "\n".join(
        [item.value for item in app.caption]
        + [item.value for item in app.info]
        + [item.value for item in app.warning]
    )
    assert "市場曝險" in rendered
    assert "價格資料覆蓋或新鮮度不足" in rendered
    assert "資料不足" in rendered
    assert any("確定性假設" in item.label for item in app.expander)
