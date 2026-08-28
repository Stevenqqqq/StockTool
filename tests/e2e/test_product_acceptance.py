"""Sprint 19 deterministic product acceptance contracts.

Browser execution is recorded separately because these tests intentionally use
controlled provider fixtures and must not claim to be browser automation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

from stock_tool.dashboard.navigation import PRIMARY_NAVIGATION
from stock_tool.dashboard.pages.library import _render_saved_entry
from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio_valuation import PortfolioValuationService
from streamlit.testing.v1 import AppTest

from tests.test_research_library_dashboard import _FakeStreamlit, _entry_with_document


def _journey_module():
    path = Path(__file__).with_name("test_research_journey.py")
    spec = importlib.util.spec_from_file_location("sprint19_research_journey", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_first_user_has_visible_research_start_and_six_fixed_navigation_entries(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/stock_tool/dashboard/app.py")).run(
        timeout=20
    )
    assert not app.exception
    assert {button.label for button in app.button}.issuperset(
        {"研究 2330", "研究 6488", "研究 AAPL"}
    )
    assert [item.key for item in PRIMARY_NAVIGATION] == [
        "home",
        "explore",
        "strategy",
        "holdings",
        "library",
        "settings",
    ]


def test_three_markets_workspace_retains_source_and_honest_partial_score() -> None:
    journey = _journey_module()
    for symbol in (
        Symbol("2330", Market.TWSE),
        Symbol("6488", Market.TPEX),
        Symbol("AAPL", Market.US),
    ):
        analysis = journey._service({symbol: journey._provider_result(symbol)}).analyze(
            __import__(
                "stock_tool.application.results", fromlist=["AnalysisRequest"]
            ).AnalysisRequest(
                __import__(
                    "stock_tool.application.results", fromlist=["DataHydrationRequest"]
                ).DataHydrationRequest(symbol, "2024-01-01", "2024-12-31")
            )
        )
        assert journey._source_metadata(analysis).query_symbol
        assert analysis.stock_score is not None


def test_saved_research_version_renders_without_current_provider(tmp_path: Path) -> None:
    _, entry = _entry_with_document(tmp_path)
    st = _FakeStreamlit()
    _render_saved_entry(st, entry)
    visible = "\n".join(str(event) for event in st.events)
    assert "保存的研究版本" in visible
    assert "引用：price" in visible


def test_missing_price_portfolio_is_not_valued_as_real_position() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["2330"],
            "market": ["TWSE"],
            "currency": ["TWD"],
            "quantity": [1.0],
            "average_cost": [100.0],
        }
    )
    result = PortfolioValuationService().value(positions=positions, prices=None)
    assert result.base_market_value is None
    assert any(item.field == "latest_price" for item in result.missing_data)


def test_strategy_and_export_contracts_are_exercised(tmp_path: Path) -> None:
    _journey_module().test_research_journey_preserves_t_plus_one_costs_benchmark_and_report_provenance(
        tmp_path
    )


def test_fixture_journey_covers_cache_and_provider_failure_honesty() -> None:
    # Retain the existing, deterministic journey as a product acceptance dependency.
    _journey_module().test_research_journey_resolves_three_markets_and_keeps_partial_scores_honest(
        "2330", Market.TWSE, "2330.TW"
    )
