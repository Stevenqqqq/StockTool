from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import stock_tool.dashboard.shell as shell
from stock_tool.application.research_context import ResearchContext, ResearchHandoffAction
from stock_tool.dashboard.state import consume_research_handoff, initialize_dashboard_state
from stock_tool.dashboard.pages.portfolio_workspace import _consume_portfolio_focus
from stock_tool.dashboard.pages.strategy_workspace import _select_loaded_symbol
from stock_tool.domain.models import Market, Symbol


class _Streamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, object] = {}
        self.messages: list[str] = []
        self.reruns = 0

    def warning(self, message: str) -> None:
        self.messages.append(message)

    def info(self, message: str) -> None:
        self.messages.append(message)

    def rerun(self) -> None:
        self.reruns += 1

    def selectbox(
        self, _label: str, options: list[str], *, index: int = 0, **_kwargs: object
    ) -> str:
        return options[index]

    def success(self, message: str) -> None:
        self.messages.append(message)


def _snapshot(symbol: str = "2330", market: Market = Market.TWSE) -> object:
    return SimpleNamespace(
        symbol=Symbol(symbol, market),
        price=SimpleNamespace(last_data_date="2026-08-03"),
    )


def test_explore_to_research_is_canonical_one_shot_and_non_fetching() -> None:
    st = _Streamlit()
    calls: list[str] = []
    shell._route_explore_research(st, Symbol("2330", Market.TWSE))

    request = st.session_state["dashboard_search_request"]
    assert request.symbol == "2330"
    assert request.market == "TWSE"
    assert st.session_state["dashboard_pending_workspace_destination"]["workspace"] == "home"
    assert consume_research_handoff(st.session_state, destination="research") is None
    assert calls == []
    assert st.reruns == 1


def test_library_to_research_rejects_invalid_market_and_valid_route_is_one_shot() -> None:
    st = _Streamlit()
    shell._route_library_current_research(st, "2330", "AUTO")
    assert not st.session_state.get("dashboard_research_handoff_queue")
    assert st.messages

    shell._route_library_current_research(st, "2330.TW", "TWSE")
    request = st.session_state["dashboard_search_request"]
    assert (request.symbol, request.market) == ("2330", "TWSE")
    assert consume_research_handoff(st.session_state, destination="research") is None


def test_research_to_library_and_holdings_only_focus_without_mutation() -> None:
    for destination, expected_key in (
        ("library", "library_symbol_filter"),
        ("holdings", "portfolio_workspace_focus"),
    ):
        st = _Streamlit()
        st.session_state["portfolio_workspace_positions"] = pd.DataFrame(
            [{"symbol": "2330", "market": "TWSE", "quantity": 1.0}]
        )
        shell._route_research_workspace_handoff(st, destination, _snapshot())
        context = consume_research_handoff(st.session_state, destination=destination)
        assert context is not None
        shell._apply_workspace_handoff(st, context)
        assert st.session_state[expected_key]
        assert len(st.session_state["portfolio_workspace_positions"]) == 1


def test_research_to_strategy_requires_matching_identity_and_snapshot() -> None:
    st = _Streamlit()
    st.session_state["price_data"] = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-03"]),
            "symbol": ["2330"],
            "market": ["TWSE"],
        }
    )
    st.session_state["strategy_workspace_run"] = object()
    context = ResearchContext(
        symbol="2330",
        market="TWSE",
        origin_workspace="research",
        destination_workspace="strategy",
        action=ResearchHandoffAction.OPEN_STRATEGY,
        data_as_of="2026-08-03",
        snapshot_fingerprint="snap-1",
    )
    initialize_dashboard_state(st.session_state)
    st.session_state["dashboard_research_handoff_queue"].enqueue(context)
    shell._apply_workspace_handoff(
        st, consume_research_handoff(st.session_state, destination="strategy")
    )
    assert "strategy_workspace_run" not in st.session_state
    assert st.session_state["strategy_workspace_handoff_error"]

    st.session_state["strategy_workspace_run"] = object()
    st.session_state["research_snapshot_fingerprint"] = "snap-1"
    shell._apply_workspace_handoff(st, context)
    assert st.session_state["strategy_workspace_run"] is not None
    assert st.session_state["strategy_workspace_handoff_context"]["market"] == "TWSE"
    assert st.session_state["active_symbol"] == "2330"


def test_destination_queue_consumption_is_not_head_of_line_blocked_on_rerun() -> None:
    st = _Streamlit()
    initialize_dashboard_state(st.session_state)
    strategy = ResearchContext(
        symbol="AAPL",
        market="US",
        origin_workspace="research",
        destination_workspace="strategy",
        action=ResearchHandoffAction.OPEN_STRATEGY,
    )
    research = ResearchContext(
        symbol="2330",
        market="TWSE",
        origin_workspace="explore",
        destination_workspace="research",
        action=ResearchHandoffAction.EXPLORE_TO_RESEARCH,
    )
    st.session_state["dashboard_research_handoff_queue"].enqueue_many([strategy, research])
    assert consume_research_handoff(st.session_state, destination="research") is research
    assert consume_research_handoff(st.session_state, destination="research") is None
    assert consume_research_handoff(st.session_state, destination="strategy") is strategy
    assert consume_research_handoff(st.session_state, destination="strategy") is None


def test_strategy_loaded_selection_is_market_qualified() -> None:
    st = _Streamlit()
    st.session_state["strategy_workspace_handoff_context"] = {
        "symbol": "2330",
        "market": "TPEX",
    }
    prices = pd.DataFrame(
        [
            {"symbol": "2330", "market": "TWSE", "close": 100},
            {"symbol": "2330.TWO", "market": "TPEX", "close": 200},
            {"symbol": "AAPL", "market": "US", "close": 300},
        ]
    )
    symbol, selected, market = _select_loaded_symbol(st, prices)
    assert (symbol, market) == ("2330", "TPEX")
    assert selected["market"].tolist() == ["TPEX"]


def test_holdings_focus_is_consumed_and_visibly_selects_exact_market() -> None:
    st = _Streamlit()
    st.session_state["portfolio_workspace_focus"] = {"symbol": "2330", "market": "TPEX"}
    positions = pd.DataFrame(
        [
            {"symbol": "2330", "market": "TWSE", "quantity": 1},
            {"symbol": "2330", "market": "TPEX", "quantity": 2},
        ]
    )
    assert _consume_portfolio_focus(st, positions) == "2330 / TPEX"
    assert st.session_state["portfolio_workspace_research_identity"] == "2330 / TPEX"
    assert "portfolio_workspace_focus" not in st.session_state
    assert _consume_portfolio_focus(st, positions) is None


def test_holdings_focus_missing_position_is_honest_and_does_not_mutate() -> None:
    st = _Streamlit()
    st.session_state["portfolio_workspace_focus"] = {"symbol": "AAPL", "market": "US"}
    positions = pd.DataFrame([{"symbol": "2330", "market": "TWSE", "quantity": 1}])
    before = positions.copy(deep=True)
    assert _consume_portfolio_focus(st, positions) is None
    pd.testing.assert_frame_equal(positions, before)
    assert any("目前不在持倉" in message for message in st.messages)


def test_strategy_and_holdings_return_to_research_preserve_identity_without_fetch() -> None:
    for origin, symbol, market in (("strategy", "6488", "TPEX"), ("holdings", "AAPL", "US")):
        st = _Streamlit()
        shell._route_workspace_to_research(st, origin, symbol, market)
        request = st.session_state["dashboard_search_request"]
        assert (request.symbol, request.market) == (symbol, market)
        assert st.reruns == 1
